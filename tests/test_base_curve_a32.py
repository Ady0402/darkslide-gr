"""Synthetic ISA checks; never reads official firmware."""
import unittest
from darkslide._base_curve_a32 import CPU, MASK


class TestISA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = bytes(0x10b55c0)

    def cpu(self, *words):
        cpu = CPU(self.rom)
        for at, word in enumerate(words): cpu.write(0x60000000+4*at, word)
        cpu.regs[15] = 0x60000000
        return cpu

    def test_add_sub_flags_condition(self):
        c = self.cpu(0xe2900001, 0x03a01007, 0x13a01009, 0xe2502001)
        c.regs[0] = MASK
        for _ in range(4): c.step()
        self.assertEqual(c.regs[:3], [0, 7, MASK])
        self.assertEqual((c.n, c.z, c.c, c.v), (1, 0, 0, 0))

    def test_overflow_and_ror(self):
        c = self.cpu(0xe2900001, 0xe1b01060)
        c.regs[0] = 0x7fffffff
        c.step(); self.assertEqual((c.regs[0], c.v, c.c), (0x80000000, 1, 0))
        c.step(); self.assertEqual((c.regs[1], c.c), (0x40000000, 0))

    def test_half_signed_and_memory(self):
        c = self.cpu(0xe1d010b0, 0xe1d020d0, 0xe1d030f0)
        c.regs[0] = 0x60001000; c.write(c.regs[0], 0xff80, 2)
        for _ in range(3): c.step()
        self.assertEqual(c.regs[1:4], [0xff80, 0xffffff80, 0xffffff80])

    def test_long_signed_and_multiply(self):
        c = self.cpu(0xe0c32190, 0xe0050491)
        c.regs[0:2] = [MASK, 2]; c.regs[4] = 7
        c.step(); self.assertEqual(c.regs[2:4], [0xfffffffe, MASK])
        c.step(); self.assertEqual(c.regs[5], 14)

    def test_block_push_pop_and_pc(self):
        c = self.cpu(0xe92d4003, 0xe8bd8003)
        c.regs[0:2] = [123, 456]; c.regs[13] = 0x5effff00; c.regs[14] = 0x5e000000
        c.step(); self.assertEqual(c.regs[13], 0x5efffef4)
        c.regs[:2] = [0, 0]; c.step()
        self.assertEqual(c.regs[:2], [123, 456]); self.assertEqual(c.regs[15], 0x5e000000)

    def test_movw_movt_unsigned_extend(self):
        c = self.cpu(0xe30a0bcd, 0xe34e0123, 0xe6ff1070, 0xe6ef2070)
        for _ in range(4): c.step()
        self.assertEqual(c.regs[:3], [0xe123abcd, 0xabcd, 0xcd])

    def test_helper_budget_and_unsigned_division(self):
        c = self.cpu(0xe1a00000)
        count = c.run(0x5313d850, [MASK, 2])
        self.assertEqual((c.regs[0], count), (0x7fffffff, 1))
        with self.assertRaises(ValueError): c.run(0x5313d850, [1, 0])

    def test_reserved_and_unpredictable_register_rejections(self):
        for word in (0xe1b0f00e, 0xe1a00f1f, 0xe8b00001, 0xe4900004, 0xe6fff070):
            with self.assertRaises(ValueError): self.cpu(word).step()

    def test_remaining_PC_and_reserved_transfer_rejections(self):
        for word in (0xe300f001, 0xe340f001, 0xe12fff1f, 0xe89f0001, 0xe5d0f000, 0xe19011b2, 0xe1bf10b0, 0xe1f000b0, 0xe49f0004, 0xe790100f, 0xe0003192, 0xe1f110b0, 0xe1ff10b0, 0xe8af0001):
            with self.assertRaises(ValueError): self.cpu(word).step()

    def test_STM_PC_snapshot_and_writeback(self):
        c = self.cpu(0xe92dc010)
        c.regs[4] = 123; c.regs[14] = 0x5e000000; c.regs[13] = 0x5effff00
        c.step()
        self.assertEqual(c.regs[13], 0x5efffef4)
        self.assertEqual([c.read(c.regs[13]+i*4) for i in range(3)], [123,0x5e000000,0x60000008])
        self.assertEqual(c.regs[15], 0x60000004)

    def test_signed_helper_positive_domain_and_rejections(self):
        c = self.cpu(0xe1a00000)
        count = c.run(0x5313d884, [9, 2])
        self.assertEqual((c.regs[0], count), (4, 1))
        self.assertEqual(c.declared_helpers[0x5313d884], dict(count=1, dividend_min=9,
            dividend_max=9, divisor_min=2, divisor_max=2))
        c.run(0x5313d884, [0, 1]); self.assertEqual(c.regs[0], 0)
        for args in ([MASK, 2], [9,MASK], [9,0]):
            with self.assertRaises(ValueError): c.run(0x5313d884, args)

    def test_reject_unknown_romwrite_call_budget(self):
        c = self.cpu(0xe10f0000)
        with self.assertRaises(ValueError): c.step()
        with self.assertRaises(ValueError): c.write(0x53000000, 1)
        with self.assertRaises(ValueError): c.read(0)
        with self.assertRaises(ValueError): c.run(0x53000000, [])
        with self.assertRaises(ValueError): c.run(0x536e7b64, [], True)
        with self.assertRaises(ValueError): CPU(b'wrong-size')


if __name__ == '__main__':
    unittest.main()
