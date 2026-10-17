"""Guarded RAW parser/request/pool-photo fixture shared by JPEG and DNG tests.

The base initializes its original formatter and RAW job. RTOS sender, boot pool
inventory and heap services are fixtures; parser/copy/queue hook sites execute.
"""
import struct
from darkslide import photo_recipe as P, photo_recipe_extension as E
from gr3x_recipe_io import C, V


def queue_machine(Base):
    class Machine(Base):
        def __init__(self, raw, ext):
            super().__init__(raw, ext)
            self.u.mem_map(0x72200000, 0x600000)  # bounded multi-photo test arena
            self.requests = []
            self.queue_calls = []
            self.cancel_during_send = False
            self.pool = self.allocate(E.POOL_EXTENDED)
            self.put(self.pool+0x20, E.PHOTO_EXTENDED)
            self.put(0x55344d7c+0x5ac, self.pool)
            self.allowed.append((0x55344d7c, 0x55344d7c+0x9b0))
            self.allowed.append((C.SOURCE, C.SOURCE+0x6c))
            self.transport = self.allocate(4)
            self.put(0x55344d7c+0x5a8, self.transport)
            self.photos = [self.allocate(E.PHOTO_EXTENDED) for _ in range(2)]
            for i, photo in enumerate(self.photos):
                self.call('ds_pool_photo_ctor', photo)
                self.put(self.pool+0x88+4*i, photo)
            self.process = self.allocate(0x44cc)
            fixture = C.transport_fixture()
            needle = bytes.fromhex('0410a0e30020a0e3')
            V.need(fixture.count(needle) == 1, 'transport namespace fixture')
            self.u.mem_write(C.NEAR+0xe000, fixture.replace(needle, bytes.fromhex('0410a0e30820a0e3')))

        def allocate(self, count):
            # Same guard/failure protocol as immutable fixture, larger
            # arena because JPEG + RAW + two concurrent photos coexist.
            V.need(0 < count <= 0x100000, 'heap size')
            self.alloc_log.append(count)
            if count == self.fail_size or self.fail_nth == len(self.alloc_log):return 0
            at = self.heap
            self.heap += (count+31)&~15
            V.need(self.heap < (0x72800000 if hasattr(self,'requests') else 0x72200000), 'heap bound')
            self.allocations.append((at,at+count))
            self.u.mem_write(at,bytes(count))
            self.u.mem_write(at-8,b'LEFT!!!!');self.u.mem_write(at+count,b'RIGHT!!!')
            return at

        def block(self, u, a, n, x):
            if a == 0x5382d074:
                p = self.allocate(u.reg_read(self.reg(1)))
                if p:self.requests.append(p)
                self.ret(p);return
            if a == 0x5382d088:
                p = u.reg_read(self.reg(1));V.need(p in self.requests, 'request ownership')
                self.free(p);self.ret(0);return
            if a == 0x534d6260:
                self.queue_calls.append([u.reg_read(self.reg(i)) for i in range(4)])
                if self.cancel_during_send:self.free(u.reg_read(self.reg(2)))
                self.ret(0);return  # stock sender has no usable success result
            if any(lo <= a and a+n <= hi for lo,hi in (
                (0x534d6624,0x534d662c),(0x534d668c,0x534d66a8),
                (0x5351d3e4,0x5351d3f0),(0x53516b40,0x53516bfc),
                (0x53522688,0x53522690),(0x53510800,0x53510834),
                (0x53523a24,0x53523ac4),(0x534bf468,0x534bf46c))):
                self.executed.add(a);return
            return super().block(u,a,n,x)

        def segment(self, start, end, regs):
            for i in range(13):self.u.reg_write(self.reg(i),0)
            self.u.reg_write(C.A.UC_ARM_REG_SP,V.STACK-0x100)
            self.u.reg_write(C.A.UC_ARM_REG_LR,V.STOP)
            self.u.reg_write(C.A.UC_ARM_REG_CPSR,0x13)
            for i,v in regs.items():self.u.reg_write(self.reg(i),v)
            self.u.emu_start(start,end,count=8000000,timeout=20000000)
            V.need(self.u.reg_read(C.A.UC_ARM_REG_PC)==end,'segment returned')
            self.canaries()
            return self.u.reg_read(self.reg(0))

        def canaries(self):
            for lo, hi in self.allocations:
                V.need(bytes(self.u.mem_read(lo-8,8))==b'LEFT!!!!' and
                       bytes(self.u.mem_read(hi,8))==b'RIGHT!!!','heap canary')

        def load(self, data):
            directory = b'RICOH\0II'+struct.pack('<HHHIII',1,0xd534,7,len(data),26,0)+data
            directory += bytes((-len(directory))%4)
            self.task_load(self.job,self.prop,self.work,directory)
            V.need(self.get(self.job+96+8)==1,'parser restored')
            self.u.mem_write(self.work+0x77c,bytes([P.decode(data)['slot']+10]))
            p,n = self.ref(self.job+96)
            if p:V.need(bytes(self.u.mem_read(p,n))==data,'parser full packet')
            return p

        def ref(self, context):
            return struct.unpack('<II',self.u.mem_read(context+1588,8))

        def send(self):
            request = self.segment(0x534d6624,0x534d662c,{0:self.transport})
            V.need(request != 0,'request allocation')
            self.put(request+16,self.get(self.prop+0x5d0));self.put(request+20,self.work)
            self.segment(0x534d668c,0x534d66a8,{0:request,1:0x72c8100d,6:0,11:V.STACK-0x80})
            return request

        def accept(self, request, index=0):
            self.segment(0x5351d3e4,0x5351d3f0,{5:0x55344d7c,7:request})
            V.need(not any(lo==request for lo,hi in self.allocations),'request freed')
            photo=self.photos[index];self.put(self.process+0x44c8,photo)
            self.segment(0x53510800,0x53510834,{0:self.process,1:9,2:self.work})
            self.call('ds_begin',self.pool+0x218,0,0)
            self.photo=photo
            self.call(0x535fc2d0,C.SOURCE,photo)  # original selected-photo setter
            V.need(self.call(0x535fc2f8,C.SOURCE)==photo,'JPEG source binding')
            return photo
    return Machine
