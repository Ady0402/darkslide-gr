"""Small, bounded A32 interpreter. No firmware instructions or tables embedded.

This is an instruction interpreter, not an independent mathematical colour model.
Unsupported encodings and memory accesses fail rather than being approximated.
"""
import struct

MASK = 0xffffffff


def signed(value, bits=32):
    value &= (1 << bits)-1
    return value-(1 << bits) if value & (1 << (bits-1)) else value


def ror(value, amount):
    amount %= 32
    return ((value >> amount) | (value << ((32-amount) % 32))) & MASK


class CPU:
    def __init__(self, rom):
        if type(rom) is not bytes or len(rom) != 0x10b55c0:
            raise ValueError('fixed runtime RTOS required')
        self.regs = [0]*16
        self.n = self.z = self.c = self.v = 0
        self.segments = [(0x53000000, bytes(rom), False),
                         (0x55000000, bytearray(0x40000), True),
                         (0x60000000, bytearray(0x10000), True),
                         (0x5eff0000, bytearray(0x10000), True)]
        self.segments[1][1][:0x3a080] = rom[0x107b540:0x107b540+0x3a080]
        self.steps = 0
        self.writes = set()
        self.declared_helpers = {}

    def region(self, address, size, write=False):
        for base, data, writable in self.segments:
            if base <= address and address+size <= base+len(data):
                if write and not writable:
                    raise ValueError('write to original ROM')
                return data, address-base
        raise ValueError('unmapped address %#x/%d' % (address, size))

    def read(self, address, size=4):
        data, offset = self.region(address, size)
        return int.from_bytes(data[offset:offset+size], 'little')

    def write(self, address, value, size=4):
        data, offset = self.region(address, size, True)
        data[offset:offset+size] = (value & ((1 << (size*8))-1)).to_bytes(size, 'little')
        self.writes.update(range(address, address+size))

    def reg(self, index):
        return (self.regs[15]+8) & MASK if index == 15 else self.regs[index]

    def condition(self, cond):
        conditions = (self.z, not self.z, self.c, not self.c, self.n, not self.n,
                      self.v, not self.v, self.c and not self.z, not self.c or self.z,
                      self.n == self.v, self.n != self.v, not self.z and self.n == self.v,
                      self.z or self.n != self.v, True, False)
        if cond == 15:
            raise ValueError('unsupported unconditional encoding')
        return conditions[cond]

    def shift(self, value, kind, amount, register=False):
        if register and amount == 0:
            return value, self.c
        if not register and amount == 0:
            if kind == 0: return value, self.c
            if kind == 3: return (self.c << 31) | (value >> 1), value & 1
            amount = 32
        if kind == 0:
            return ((value << amount) & MASK if amount < 32 else 0), ((value >> (32-amount)) & 1 if amount <= 32 else 0)
        if kind == 1:
            return (value >> amount if amount < 32 else 0), ((value >> (amount-1)) & 1 if amount <= 32 else 0)
        if kind == 2:
            return (signed(value) >> min(amount, 32)) & MASK, (value >> (min(amount, 32)-1)) & 1
        result = ror(value, amount)
        return result, (result >> 31) & 1

    def operand(self, word):
        if word & (1 << 25):
            amount = ((word >> 8) & 15)*2
            value = ror(word & 255, amount)
            return value, self.c if amount == 0 else value >> 31
        amount = (self.reg((word >> 8) & 15) & 255) if word & 16 else (word >> 7) & 31
        return self.shift(self.reg(word & 15), (word >> 5) & 3, amount, bool(word & 16))

    def arithmetic_flags(self, left, right, result, subtraction=False):
        if subtraction:
            self.c = int(left >= right)
            self.v = int(bool(((left ^ right) & (left ^ result)) & 0x80000000))
        else:
            self.c = int(left+right > MASK)
            self.v = int(bool((~(left ^ right) & (left ^ result)) & 0x80000000))

    def step(self):
        pc = self.regs[15]
        if pc & 3: raise ValueError('unaligned/Thumb PC')
        word = self.read(pc)
        next_pc = pc+4
        self.steps += 1
        if not self.condition(word >> 28):
            self.regs[15] = next_pc; return
        op = word & 0x0fffffff
        rd, rn, rm = (word >> 12) & 15, (word >> 16) & 15, word & 15
        if op & 0x0ffffff0 == 0x012fff10:
            if rm == 15: raise ValueError('unsupported BX PC')
            next_pc = self.reg(rm)
        elif op & 0x0e000000 == 0x0a000000:
            if word & (1 << 24): self.regs[14] = pc+4
            next_pc = (pc+8+(signed(word & 0xffffff, 24) << 2)) & MASK
        elif op & 0x0fb00000 == 0x03000000:
            if rd == 15: raise ValueError('invalid MOVW/MOVT PC')
            imm = ((word >> 4) & 0xf000) | (word & 0xfff)
            self.regs[rd] = ((self.regs[rd] & 0xffff) | (imm << 16)) if word & (1 << 22) else imm
        elif op & 0x0fff03f0 in (0x06ff0070, 0x06ef0070):
            if rd == 15 or rm == 15: raise ValueError('unsupported extend PC')
            value = ror(self.reg(rm), ((word >> 10) & 3)*8)
            self.regs[rd] = value & (65535 if op & 0x0fff03f0 == 0x06ff0070 else 255)
        elif op & 0x0f8000f0 == 0x00800090:
            lo, hi = rd, rn
            if 15 in (lo, hi, rm, (word >> 8) & 15) or lo == hi: raise ValueError('invalid long multiply registers')
            a, b = self.reg(rm), self.reg((word >> 8) & 15)
            if word & (1 << 22): a, b = signed(a), signed(b)
            value = a*b
            if word & (1 << 21): value += self.regs[lo] | (self.regs[hi] << 32)
            value &= (1 << 64)-1
            self.regs[lo], self.regs[hi] = value & MASK, value >> 32
            if word & (1 << 20): self.n, self.z = value >> 63, int(value == 0)
        elif op & 0x0fc000f0 == 0x00000090:
            if 15 in (rn, rd, rm, (word >> 8) & 15): raise ValueError('invalid multiply PC')
            if not word & (1 << 21) and rd != 0: raise ValueError('reserved MUL accumulator field')
            value = self.reg(rm)*self.reg((word >> 8) & 15)
            if word & (1 << 21): value += self.reg(rd)
            value &= MASK; self.regs[rn] = value
            if word & (1 << 20): self.n, self.z = value >> 31, int(value == 0)
        elif op & 0x0e000090 == 0x00000090:
            kind = (word >> 5) & 3
            if rd == 15 or (not word & (1 << 22) and rm == 15): raise ValueError('unsupported extra transfer PC')
            if kind == 0: raise ValueError('reserved extra load/store')
            if not word & (1 << 22) and word & 0xf00: raise ValueError('reserved extra register-offset high bits')
            if rn == 15 and (word & (1 << 21) or not word & (1 << 24)): raise ValueError('extra PC writeback')
            if word & (1 << 20) and rd == rn and (word & (1 << 21) or not word & (1 << 24)): raise ValueError('extra load base overlap')
            offset = ((word >> 4) & 0xf0) | (word & 15) if word & (1 << 22) else self.reg(rm)
            base = self.reg(rn); delta = offset if word & (1 << 23) else -offset
            address = (base+delta) & MASK if word & (1 << 24) else base
            if word & (1 << 20):
                size = 1 if kind == 2 else 2
                value = self.read(address, size)
                if kind in (2, 3): value = signed(value, size*8) & MASK
                self.regs[rd] = value
            elif kind == 1: self.write(address, self.reg(rd), 2)
            else: raise ValueError('unsupported extra load/store')
            if word & (1 << 21) or not word & (1 << 24): self.regs[rn] = (base+delta) & MASK
        elif op & 0x0e000000 == 0x08000000:
            if word & (1 << 22): raise ValueError('unsupported user-bank block transfer')
            indices = [i for i in range(16) if word & (1 << i)]
            if not indices: raise ValueError('empty block transfer')
            if rn == 15: raise ValueError('unsupported block PC base')
            if word & (1 << 21) and rn in indices: raise ValueError('unsupported block base overlap')
            base = self.reg(rn); up, pre = bool(word & (1 << 23)), bool(word & (1 << 24))
            address = base+(4 if pre else 0) if up else base-4*len(indices)+(0 if pre else 4)
            values = [(i, self.read(address+4*n)) for n, i in enumerate(indices)] if word & (1 << 20) else [(i, self.reg(i)) for i in indices]
            for n, (i, value) in enumerate(values):
                if word & (1 << 20):
                    if i == 15: next_pc = value
                    else: self.regs[i] = value
                else: self.write(address+4*n, value)
            if word & (1 << 21): self.regs[rn] = (base+(4*len(indices) if up else -4*len(indices))) & MASK
        elif op & 0x0c000000 == 0x04000000:
            if word & (1 << 22) and rd == 15: raise ValueError('invalid byte transfer PC')
            if rn == 15 and (word & (1 << 21) or not word & (1 << 24)): raise ValueError('single transfer PC writeback')
            if word & (1 << 25) and rm == 15: raise ValueError('memory offset PC')
            if (word & (1 << 20) and rd == rn and (word & (1 << 21) or not word & (1 << 24))) or (not word & (1 << 20) and rd == 15): raise ValueError('unsupported memory register overlap/PC store')
            base = self.reg(rn)
            if word & (1 << 25):
                if word & 16: raise ValueError('register-shift memory offset')
                offset, _ = self.shift(self.reg(rm), (word >> 5) & 3, (word >> 7) & 31)
            else: offset = word & 0xfff
            delta = offset if word & (1 << 23) else -offset
            address = (base+delta) & MASK if word & (1 << 24) else base
            size = 1 if word & (1 << 22) else 4
            if word & (1 << 20):
                value = self.read(address, size)
                if rd == 15: next_pc = value
                else: self.regs[rd] = value
            else: self.write(address, self.reg(rd), size)
            if word & (1 << 21) or not word & (1 << 24): self.regs[rn] = (base+delta) & MASK
        elif op & 0x0c000000 == 0:
            code = (word >> 21) & 15
            if (word & (1 << 20) and rd == 15 and code not in (8,9,10,11)) or (not word & (1 << 25) and word & 16 and 15 in (rm,(word >> 8) & 15)): raise ValueError('unsupported status restore/shift PC')
            if code in (8, 9, 10, 11) and not word & (1 << 20):
                raise ValueError('reserved test encoding')
            if code in (5, 6, 7): raise ValueError('unsupported carry arithmetic')
            left = self.reg(rn); right, carry = self.operand(word)
            if code == 0 or code == 8: value = left & right
            elif code == 1 or code == 9: value = left ^ right
            elif code == 2 or code == 10: value = (left-right) & MASK
            elif code == 3: value = (right-left) & MASK
            elif code == 4 or code == 11: value = (left+right) & MASK
            elif code == 12: value = left | right
            elif code == 13: value = right
            elif code == 14: value = left & ~right & MASK
            elif code == 15: value = ~right & MASK
            else: raise ValueError('data opcode')
            if word & (1 << 20):
                self.n, self.z = value >> 31, int(value == 0)
                if code in (2, 10): self.arithmetic_flags(left, right, value, True)
                elif code == 3: self.arithmetic_flags(right, left, value, True)
                elif code in (4, 11): self.arithmetic_flags(left, right, value)
                else: self.c = carry
            if code not in (8, 9, 10, 11):
                if rd == 15: next_pc = value
                else: self.regs[rd] = value
        else:
            raise ValueError('unsupported instruction %#x at %#x' % (word, pc))
        self.regs[15] = next_pc & MASK

    def run(self, address, args, budget=200000):
        if type(budget) is not int or not 0 < budget <= 200000 or len(args) > 4:
            raise ValueError('bounded run parameters')
        self.regs = [0]*16
        for i, value in enumerate(args): self.regs[i] = value & MASK
        self.regs[13], self.regs[14], self.regs[15] = 0x5effff00, 0x5e000000, address
        self.n = self.z = self.c = self.v = 0
        start = self.steps
        while self.regs[15] != 0x5e000000:
            if self.steps-start >= budget: raise ValueError('bounded instruction count exceeded')
            pc = self.regs[15]
            if not (0x536e7b64 <= pc < 0x536e82d0 or pc in (0x5313d850,0x5313d884)):
                raise ValueError('undeclared function %#x' % pc)
            if pc in (0x5313d850,0x5313d884):
                self.steps += 1
                if pc == 0x5313d884 and (self.regs[0] > 0x7fffffff or not 0 < self.regs[1] <= 0x7fffffff): raise ValueError('signed helper limited to nonnegative dividend and positive int32 divisor')
                if not self.regs[1]: raise ValueError('zero unsigned divisor')
                record = self.declared_helpers.setdefault(pc, dict(count=0, dividend_min=self.regs[0],
                    dividend_max=self.regs[0], divisor_min=self.regs[1], divisor_max=self.regs[1]))
                record['count'] += 1
                record['dividend_min'] = min(record['dividend_min'], self.regs[0])
                record['dividend_max'] = max(record['dividend_max'], self.regs[0])
                record['divisor_min'] = min(record['divisor_min'], self.regs[1])
                record['divisor_max'] = max(record['divisor_max'], self.regs[1])
                self.regs[0] //= self.regs[1]
                self.regs[15] = self.regs[14]
            else: self.step()
        return self.steps-start
