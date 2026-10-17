"""Production ABI adapter over the immutable, local metadata service fixture."""
import importlib.util
import os
from pathlib import Path
from darkslide import photo_recipe_native as N, photo_recipe_extension as E

research = Path(os.environ['DARKSLIDE_RESEARCH_ROOT'])
spec = importlib.util.spec_from_file_location('owned_recipe_io_fixture',
    research/'GRIIIx_160完整配方接入_2026-10-13_v10/formatter_probe.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
C, V = F.C, F.V


class Machine(F.Machine):
    def __init__(self, raw, extension):
        super().__init__(raw, N.compile_lab())
        self.ext = extension
        regions = list(self.u.mem_regions())
        lo, hi = E.TAIL & ~4095, (extension['end']+4095) & ~4095
        for at in range(lo, hi, 4096):
            if not any(a <= at and at+4095 <= b for a, b, _ in regions):
                self.u.mem_map(at, 4096)
        self.u.mem_write(E.TAIL, extension['extension'])
        self.u.mem_protect(lo, hi-lo, C.U.UC_PROT_READ | C.U.UC_PROT_EXEC)
        for w in extension['windows']:
            previous = next((p for p in reversed(self.patch_windows)
                             if int(p['address'],16) == w.address), None)
            self.patch(w.address, bytes.fromhex(previous['after']) if previous else w.expected,
                       w.replacement, 'production recipe binding')
        self.symbols = extension['native']['symbols']

    def block(self, u, a, n, x):
        if hasattr(self, 'ext') and E.TAIL <= a and a+n <= self.ext['catalog']:
            return
        return super().block(u, a, n, x)

    def new_job(self):
        # The frozen fixture's old 1684-byte assertion must not hide the real
        # production allocation. Execute its original call site with new ABI.
        job = self.call(0x534ac2a4, 0x55086f08, 8)
        V.need(job == self.get(0x55086f28), 'job registry')
        V.need((job,job+1692) in self.allocations, 'production RAW job size')
        self.call(0x534bf134, job)
        prop = self.get(job+0x24)
        photo, work = self.get(prop+0x5d0), self.get(job+0x28)
        V.need(photo != work and all((p,p+0x74270) in self.allocations
                                    for p in (photo,work)), 'stock photo allocations')
        return job, prop, photo, work
