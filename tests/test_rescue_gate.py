"""Rescue gate: request-agnostic "can official 2.10 still rescue the camera" checks.

Synthetic tests build a fake decoded payload in memory (no fixture needed);
the real-fixture tests run a true build through generate-style gating.
No modified BIN is ever written."""
import hashlib
import json
import os
import struct
import unittest
from pathlib import Path

from darkslide import build as builder, fwread, rescue_gate as G

APP = Path(__file__).resolve().parents[1]
# Set DARKSLIDE_OFFICIAL_BIN to your own GR III 2.10 fwdc239b.bin to run the real-fixture tests.
STOCK = Path(os.environ.get("DARKSLIDE_OFFICIAL_BIN", "/nonexistent/fwdc239b.bin"))


def record(name, body, typ=4, index=0):
    return name.encode().ljust(8, b"\0") + struct.pack("<HHI", typ, index, len(body)) + body


def synthetic_payload():
    """Same record order as 2.10; RTOS big enough to contain both protected windows."""
    rtos_size = 0x53840000 - fwread.V210["rtos_va"] + 0x1000
    parts = [record("BOOTPARA", bytes(72), 5, 0xFFFF), record("DRAMPARA", bytes(556), 1, 0xFFFF),
             record("PARTPARA", bytes(516), 2, 0xFFFF), record("M0", bytes(44640), 3),
             record("BOOT", bytes(21816), 4)]
    head = sum(len(p) for p in parts)
    # fwread's RTOS body must start at 0x10870 for the VA formula; pad PARTPARA? No — the real
    # layout puts RTOS body at 0x10870 by construction, so assert the synthetic one matches.
    assert head + 16 == fwread.V210["rtos_body"], head
    parts += [record("RTOS", bytes(rtos_size)), record("LINUX", bytes(64)), record("INITFS", bytes(64)),
              record("SRIC", bytes(64)), record("CPU", bytes(131072), 7), record("SHELLCMD", bytes(64)),
              record("ICONBIN", bytes(64)), record("FDRVPARA", bytes(36), 8, 0xFFFF),
              record("RES", bytes(64)) + bytes(4)]
    return b"".join(parts)


def failed(checks):
    return [c["id"] for c in checks if not c["ok"]]


class Synthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = synthetic_payload()
        cls.recs = {n: (s, e) for n, s, e in G.records(cls.before)}

    def mutate(self, offset):
        after = bytearray(self.before)
        after[offset] ^= 0x5A
        return bytes(after)

    def test_identical_passes(self):
        checks = G.gate_payloads(self.before, self.before)
        self.assertEqual(failed(checks), [])
        self.assertEqual([c["id"] for c in checks],
                         ["rescue_length", "rescue_layout", "rescue_boot_chain", "rescue_other_records",
                          "rescue_updater_window", "rescue_bootflow_window"])

    def test_record_table(self):
        self.assertEqual([n for n, _, _ in G.records(self.before)],
                         ["BOOTPARA", "DRAMPARA", "PARTPARA", "M0", "BOOT", "RTOS", "LINUX", "INITFS",
                          "SRIC", "CPU", "SHELLCMD", "ICONBIN", "FDRVPARA", "RES"])
        self.assertEqual(self.recs["RTOS"][0] + 16, fwread.V210["rtos_body"])

    def test_allowed_records_may_change(self):
        for name in ("RTOS", "ICONBIN", "RES"):
            s, _ = self.recs[name]
            self.assertEqual(failed(G.gate_payloads(self.before, self.mutate(s + 20))), [], name)

    def test_boot_chain_records_are_protected(self):
        for name in G.BOOT_CHAIN:
            s, _ = self.recs[name]
            self.assertEqual(failed(G.gate_payloads(self.before, self.mutate(s + 20))), ["rescue_boot_chain"], name)

    def test_other_records_are_protected(self):
        for name in ("LINUX", "INITFS", "SRIC", "SHELLCMD", "FDRVPARA"):
            s, _ = self.recs[name]
            self.assertEqual(failed(G.gate_payloads(self.before, self.mutate(s + 20))), ["rescue_other_records"], name)

    def test_protected_windows(self):
        base = fwread.V210["rtos_body"] - fwread.V210["rtos_va"]
        for va, cid in ((0x536284E0, "rescue_updater_window"), (0x5362BD40, "rescue_updater_window"),
                        (0x5362A4C0, "rescue_updater_window"), (0x5363FFFF, "rescue_updater_window"),
                        (0x53821FCC, "rescue_bootflow_window"), (0x53823644, "rescue_bootflow_window"),
                        (0x5383866C, "rescue_bootflow_window")):
            checks = G.gate_payloads(self.before, self.mutate(va + base))
            self.assertEqual(failed(checks), [cid], hex(va))
            bad = next(c for c in checks if c["id"] == cid)
            self.assertEqual(bad["detail"], "首个差异 VA 0x%08X" % va)
        # just outside both windows: allowed
        for va in (0x5361FFFF, 0x53640000, 0x5381FFFF, 0x53840000):
            self.assertEqual(failed(G.gate_payloads(self.before, self.mutate(va + base))), [], hex(va))

    def test_record_header_change_is_layout_failure(self):
        s, _ = self.recs["M0"]
        self.assertEqual(failed(G.gate_payloads(self.before, self.mutate(s + 12))), ["rescue_layout"])

    def test_length_change(self):
        self.assertEqual(failed(G.gate_payloads(self.before, self.before + b"\0\0\0\0")), ["rescue_length"])

    def test_gate_rejects_raised_version_without_unpacking(self):
        official = bytearray(0x200)
        for o in G.VERSION_OFFSETS:
            official[o:o + 4] = G.VERSION_WORD
        output = bytearray(official)
        output[0x38:0x3C] = b"\x02\x0b\x15\x1b"
        checks = G.gate(bytes(official), bytes(output))
        self.assertIn("rescue_version", failed(checks))
        self.assertFalse(G.all_ok(checks))

    def test_all_ok_rejects_empty(self):
        self.assertFalse(G.all_ok([]))
        self.assertFalse(G.all_ok("x"))


class RealFirmware(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STOCK.exists():
            raise unittest.SkipTest("official GR III 2.10 fixture absent")
        cls.raw = STOCK.read_bytes()
        cls.template = json.loads((APP / "templates/gr3_v210.json").read_text())
        stock = fwread.Payload(fwread.unpack(cls.raw))
        _, native = stock.icon_pixels(232)
        pixels = bytearray(fwread.icon_to_rgba(native))
        for i in range(0, 6400, 4):
            if pixels[i + 3]:
                pixels[i:i + 3] = b"\x10\x80\x30"
        cls.edits = [dict(kind="icon", slot=7, icon_id=232, pixels=bytes(pixels)),
                     dict(kind="name", slot=7, string_id=274, text="Posi Cool")]
        cls.result = builder.build(cls.raw, cls.edits, cls.template)

    def test_records_match_known_layout(self):
        recs = G.records(fwread.unpack(self.raw))
        self.assertEqual(recs[5], ("RTOS", 67680, 17587760))
        self.assertEqual(recs[-1][0], "RES")

    def test_real_build_passes_gate(self):
        checks = G.gate(self.raw, self.result["output"])
        self.assertTrue(G.all_ok(checks), failed(checks))
        self.assertEqual(len(checks), 7)

    def test_official_passes_gate_against_itself(self):
        self.assertTrue(G.all_ok(G.gate(self.raw, self.raw)))

    def test_boot_chain_tamper_in_payload_is_caught(self):
        before = fwread.unpack(self.raw)
        after = bytearray(before)
        m0 = next(s for n, s, _ in G.records(before) if n == "M0")
        after[m0 + 100] ^= 0xFF
        self.assertEqual(failed(G.gate_payloads(before, bytes(after))), ["rescue_boot_chain"])

    def test_updater_tamper_in_payload_is_caught(self):
        before = fwread.unpack(self.raw)
        after = bytearray(before)
        at = 0x536284E0 - fwread.V210["rtos_va"] + fwread.V210["rtos_body"]
        after[at] ^= 0x01
        self.assertEqual(failed(G.gate_payloads(before, bytes(after))), ["rescue_updater_window"])


if __name__ == "__main__":
    unittest.main()
