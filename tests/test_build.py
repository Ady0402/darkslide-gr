"""Real stock-fixture tests; no modified BIN is ever written."""
import copy
import hashlib
import json
import os
import struct
import unittest
from pathlib import Path
from darkslide import build as builder, fwread

APP = Path(__file__).resolve().parents[1]
# Set DARKSLIDE_OFFICIAL_BIN to your own GR III 2.10 fwdc239b.bin to run these.
STOCK = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))


class Builder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STOCK.exists():
            raise unittest.SkipTest("official GR III 2.10 fixture absent")
        cls.raw = STOCK.read_bytes()
        cls.template = json.loads((APP / "templates/gr3_v210.json").read_text())
        cls.payload = fwread.unpack(cls.raw)
        cls.stock = fwread.Payload(cls.payload)
        cls.edits = []
        for slot, identifier in ((1, 358), (7, 232), (11, 50), (12, 23)):
            _, native = cls.stock.icon_pixels(identifier)
            pixels = bytearray(fwread.icon_to_rgba(native))
            for i in range(0, 6400, 4):
                if pixels[i + 3]:
                    pixels[i:i + 3] = bytes((17 + slot, 67, 193))
                else:
                    # Arbitrary transparent RGB must never enter the output.
                    pixels[i:i + 3] = b"\x12\x34\x56"
            cls.edits.append(dict(kind="icon", slot=slot, icon_id=identifier, pixels=bytes(pixels)))
        for slot, identifier, text in ((7, 274, "Posi Warm"), (11, 278, "Day200"), (12, 273, "Nega Warm")):
            cls.edits.append(dict(kind="name", slot=slot, string_id=identifier, text=text))
        cls.result = builder.build(cls.raw, cls.edits, cls.template)
        cls.decoded = fwread.unpack(cls.result["output"])
        layout = dict(fwread.V210, payload_sha256=hashlib.sha256(cls.decoded).hexdigest())
        cls.changed = fwread.Payload(cls.decoded, layout)

    def refused(self, edits=None, template=None, raw=None):
        with self.assertRaises(builder.BuildError):
            builder.build(self.raw if raw is None else raw,
                          self.edits if edits is None else edits,
                          self.template if template is None else template)

    def test_independent_full_readback(self):
        for edit in self.edits:
            if edit["kind"] == "name":
                for lang in ("en", "zh-CN", "zh-TW"):
                    self.assertEqual(self.changed.string(edit["string_id"], lang)["text"], edit["text"])
            else:
                _, old = self.stock.icon_pixels(edit["icon_id"])
                _, actual = self.changed.icon_pixels(edit["icon_id"])
                for i in range(0, 6400, 4):
                    self.assertEqual(actual[i:i + 4], edit["pixels"][i:i + 4] if old[i + 3] else old[i:i + 4])

    def test_complete_diff_is_declared(self):
        allowed = bytearray(len(self.payload))
        for change in self.result["payload_changes"]:
            a, n = change["offset"], change["length"]
            allowed[a:a + n] = b"\1" * n
        self.assertFalse(any(a != b and not flag for a, b, flag in zip(self.payload, self.decoded, allowed)))
        self.assertEqual(self.raw[:128], self.result["output"][:128])
        old = struct.unpack("<6I", self.raw[-24:])
        new = struct.unpack("<6I", self.result["output"][-24:])
        self.assertEqual(old[:3], new[:3]); self.assertEqual(old[4], new[4])
        old_stop, new_stop = 128 + old[3], 128 + new[3]
        self.assertEqual(self.raw[(old_stop + 3) & ~3:-24], self.result["output"][(new_stop + 3) & ~3:-24])

    def test_untouched_slots_and_languages(self):
        touched_icons = {e["icon_id"] for e in self.edits if e["kind"] == "icon"}
        touched_names = {e["string_id"] for e in self.edits if e["kind"] == "name"}
        for icon, string, _ in builder.MAP:
            if icon not in touched_icons:
                self.assertEqual(self.stock.icon_pixels(icon), self.changed.icon_pixels(icon))
            for lang in fwread.LANG:
                if string not in touched_names or lang not in ("en", "zh-CN", "zh-TW"):
                    self.assertEqual(self.stock.string(string, lang), self.changed.string(string, lang))

    def test_independent_checksums(self):
        for data in (self.decoded, self.result["output"]):
            self.assertEqual(sum(x[0] for x in struct.iter_unpack("<I", data)) & 0xffffffff, 0)
        self.assertEqual(hashlib.sha256(self.result["output"]).hexdigest(), self.result["output_sha256"])

    def test_determinism(self):
        second = builder.build(self.raw, list(reversed(self.edits)), self.template)
        self.assertEqual(second, self.result)

    def test_not_official(self):
        self.refused(raw=bytes((self.raw[0] ^ 1,)) + self.raw[1:])
        self.refused(raw=bytearray(self.raw))

    def test_draft_and_tampered_template(self):
        for mutator in (lambda t: t.update(reviewed=False),
                        lambda t: t.update(unknown=1),
                        lambda t: t.update(review_note=None),
                        lambda t: t["slots"][0].update(unknown=1),
                        lambda t: t["slots"][0].update(name=[]),
                        lambda t: t.update(schema=True),
                        lambda t: t["icon"].update(width=40.0),
                        lambda t: t["slots"][0].update(rename="test"),
                        lambda t: t["slots"][6].update(icon_id=233),
                        lambda t: t["official_inputs"][0].update(size=float(builder.INPUT_SIZE))):
            t = copy.deepcopy(self.template); mutator(t); self.refused(template=t)

    def test_bad_slot_id_and_kind(self):
        for fields in ({"slot": True}, {"slot": 0}, {"slot": 15}, {"slot": 13},
                       {"slot": 7.0}, {"icon_id": 233}, {"kind": []}, {"extra": 1}):
            e = dict(self.edits[0]); e.update(fields); self.refused(edits=[e])

    def test_duplicates_and_empty(self):
        self.refused(edits=[]); self.refused(edits=[self.edits[0]] * 2)
        self.refused(edits={}); self.refused(edits=[None])

    def test_alpha_dimensions_and_mask(self):
        self.refused(edits=[dict(self.edits[0], pixels=b"x")])
        p = bytearray(self.edits[0]["pixels"]); p[3] = 1
        self.refused(edits=[dict(self.edits[0], pixels=bytes(p))])
        p[3] = 255
        self.refused(edits=[dict(self.edits[0], pixels=bytes(p))])

    def test_name_constraints(self):
        for text in (None, "", "x" * 14, "正片", "a\nb", "a\tb", " a", "a ", "a  b", "a\x7fb"):
            self.refused(edits=[dict(kind="name", slot=7, string_id=274, text=text)])

    def test_source_fingerprint(self):
        source = (APP / "darkslide/build.py").read_bytes()
        source = source.replace(builder.SOURCE_SHA256.encode(), b"0" * 64, 1)
        self.assertEqual(hashlib.sha256(source).hexdigest(), builder.SOURCE_SHA256)


if __name__ == "__main__":
    unittest.main()
