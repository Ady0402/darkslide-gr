"""Re-capture the pinned v29 range table and reference after film_own_checks.

    python3 tools/capture_v29_reference.py <official fwdc239b.bin> [--write]

The readback (film_inplace_complete) only reads the ranges pinned in
film_inplace_ranges.json, and film_inplace_integrity compares their bytes with the
fingerprints in film_inplace_reference.json. Adding the own-check words changes
both, so they are captured again here, under three conditions that stop the run:

1. With film_own_checks switched off, the writer reproduces the old ranges and the
   old fingerprints for all 16 slot masks exactly (the capture method is sound).
2. With it switched on, the only new bytes are the own-check words: each one was a
   stock `cmp r3,#tone` of an installed tone and becomes the same compare against
   tone 0xFF; the fingerprint of everything else still equals the old reference.
3. Every own-check address lies outside the HDF protected windows.

Without --write nothing is changed. Run again after a capture, it checks that the
pinned files already equal the writer's output with own checks (conditions 2 and 3
are re-checked; condition 1 needs the pre-capture files, e.g. from git history).
"""
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from darkslide import (film_inplace_cache as cache, film_inplace_integrity as integrity,  # noqa: E402
                       film_own_checks, film_profiles, fwread, hdf_guard)

FILMS = {8: "portra400", 9: "pro400h", 10: "gold200", 11: "ektar100"}  # any built-in film works


def payload_of(path):
    u = fwread.unpack(Path(path).read_bytes())
    return bytes(u if isinstance(u, (bytes, bytearray)) else u[0])


def plan(raw, slots):
    edits = [dict(kind="film", slot=s, film=FILMS[s]) for s in slots]
    profiles = {FILMS[s]: film_profiles.load_profile(FILMS[s]) for s in slots}
    return cache.plan_offline(raw, edits, profiles)


def overlay_of(windows):
    return {w.address + i: b for w in windows for i, b in enumerate(w.replacement)}


def ranges_of(windows):
    return sorted((dict(address=w.address, length=len(w.replacement)) for w in windows),
                  key=lambda r: r["address"])


def main(argv):
    raw = payload_of(argv[0])
    write = "--write" in argv[1:]
    old_ranges = json.loads((ROOT / "darkslide/film_inplace_ranges.json").read_text(encoding="utf-8"))
    old_ref = json.loads(integrity.REFERENCE.read_text(encoding="utf-8"))
    protected = [(a, b) for _, a, b in hdf_guard.WINDOWS]
    new_masks, new_ranges, added, current = {}, {}, 0, 0
    for mask in range(16):
        slots = [8 + i for i in range(4) if mask >> i & 1]
        dynamic = integrity.data_addresses(slots)
        if not slots:
            new_masks["0"], new_ranges["0"] = old_ref["masks"]["0"], []
            continue
        with mock.patch.object(film_own_checks, "changes", lambda read, s: ()):
            before = plan(raw, slots)["windows"]
        after = plan(raw, slots)["windows"]
        pinned_ranges, pinned_ref = old_ranges["masks"][str(mask)], old_ref["masks"][str(mask)]
        if pinned_ranges == ranges_of(after) and pinned_ref == integrity.fingerprint(overlay_of(after), dynamic):
            current += 1            # already captured: re-check the own-check words below
            old_ref_mask = integrity.fingerprint(overlay_of(before), dynamic)
        elif (pinned_ranges == ranges_of(before) and
              pinned_ref == integrity.fingerprint(overlay_of(before), dynamic)):
            old_ref_mask = pinned_ref
        else:
            sys.exit("mask %d: the pinned data match neither the writer with nor without own checks" % mask)
        own = {at: (old, new) for at, old, new in
               film_own_checks.changes(lambda a, n: raw[fwread.Payload(raw).off(a):fwread.Payload(raw).off(a) + n], slots)}
        ov_before, ov_after = overlay_of(before), overlay_of(after)
        extra = set(ov_after) - set(ov_before)
        if extra != {at + i for at in own for i in range(4)}:
            sys.exit("mask %d: new bytes are not exactly the own-check words" % mask)
        if any(ov_after[a] != ov_before[a] for a in ov_before):
            sys.exit("mask %d: an existing byte changed" % mask)
        for at, (old, new) in own.items():
            word = int.from_bytes(bytes(ov_after[at + i] for i in range(4)), "little")
            if word != new or old & 0xFFFFF000 != 0xE3530000 or new & 0xFFFFF000 != 0xE3530000 or \
                    new & 0xFFF not in (0x8FF, 0x0FF) or any(a <= at < b for a, b in protected):
                sys.exit("mask %d: own-check word at %x is not a plain tone compare" % (mask, at))
        rest = {a: v for a, v in ov_after.items() if a not in extra}
        if integrity.fingerprint(rest, dynamic) != old_ref_mask:
            sys.exit("mask %d: shared bytes outside the own checks changed" % mask)
        new_masks[str(mask)] = integrity.fingerprint(ov_after, dynamic)
        new_ranges[str(mask)] = ranges_of(after)
        added += len(own)
        print("mask %2d: %3d own-check words, %4d bytes total" % (mask, len(own), len(ov_after)))
    if current == 15:
        print("pinned ranges and reference already include the %d own-check words; all checks passed" % added)
        return
    if current:
        sys.exit("only %d of 15 masks are already captured" % current)
    print("all 16 masks reproduce the pinned data; %d own-check words in total" % added)
    if not write:
        return
    candidate = hashlib.sha256((ROOT / "darkslide/film_inplace_cache.py").read_bytes()).hexdigest()
    ranges = dict(old_ranges, masks=new_ranges)
    ref = dict(old_ref, masks=new_masks, candidate_source_sha256=candidate,
               provenance=old_ref["provenance"] + " | Re-captured 2026-10-19 by tools/capture_v29_reference.py: "
               "identical to the previous reference except the film_own_checks words (installed tones' own "
               "still checks compare against tone 0xFF).")
    (ROOT / "darkslide/film_inplace_ranges.json").write_text(json.dumps(ranges, separators=(",", ":")) + "\n", encoding="utf-8")
    body = (json.dumps(ref, indent=1, sort_keys=False) + "\n").encode("utf-8")
    integrity.REFERENCE.write_bytes(body)
    src = (ROOT / "darkslide/film_inplace_integrity.py").read_text(encoding="utf-8")
    src = src.replace(integrity.REFERENCE_SHA256, hashlib.sha256(body).hexdigest())
    src = src.replace("CANDIDATE_SHA256 = '%s'" % integrity.CANDIDATE_SHA256, "CANDIDATE_SHA256 = '%s'" % candidate)
    (ROOT / "darkslide/film_inplace_integrity.py").write_text(src, encoding="utf-8")
    print("wrote ranges, reference and the two pinned digests")


if __name__ == "__main__":
    main(sys.argv[1:])
