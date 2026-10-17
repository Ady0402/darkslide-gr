"""IIIx bounded complete Make harness, adapted from local v05/v11 probes.
RTOS message transport, heap and selected services are substituted, not hardware.
No firmware file is created. Source hashes recorded in the v19 report.
"""
import sys,json,struct,hashlib
from darkslide import photo_recipe_extension as E,photo_recipe as P,film_profiles as F,models
from darkslide import gr3x_recipe_merge as MERGE
from darkslide._vendor.gr3_base_emulator import OriginalEmulator,DEFAULTS,STACK,STOP
import unicorn
def need(ok,why):
 if not ok:raise AssertionError(why)

def sha(b):return hashlib.sha256(b).hexdigest()

class Trace(OriginalEmulator):
    def __init__(self,rtos,plan,tone):
        self.service8_calls=0;self.trace=[];self.tone=tone;self.private_reads=set();self.record_matrix_reads=set();self.matrix_windows=[]
        super().__init__(rtos)
        for w in plan['windows']:self.u.mem_write(w.address,w.replacement)
        self.matrix_windows=[(r['matrix'],r['matrix']+18) for r in plan['records']]
        import unicorn
        self.u.hook_add(unicorn.UC_HOOK_MEM_READ,self.onread)
    def _code(self,u,a,n,user):
        self.trace.append(hex(a));self.trace=self.trace[-80:]
        if a==0x536afbe4:
            destination=u.reg_read(self.A.UC_ARM_REG_R0)
            if not 0x5ef00000<=destination<=0x5efffff8:raise ValueError('service output not in bounded stack')
            self.service8_calls+=1;u.mem_write(destination,struct.pack('<Q',1));self._return(1);return
        return super()._code(u,a,n,user)
    def _intr(self,u,number,user):
        try:return super()._intr(u,number,user)
        except Exception:
            print(json.dumps({'failure_pc':hex(u.reg_read(self.A.UC_ARM_REG_PC)),'lr':hex(u.reg_read(self.A.UC_ARM_REG_LR)),'recent_addresses':self.trace,'private_reads_before_stop':list(self.private_reads)}),file=sys.stderr);raise
    def putbyte(self,a,v):
        if self.allocations and self.allocations[-1][1]-self.allocations[-1][0]==0x80000 and a==self.allocations[-1][0]+0x71248+0x77c and v==11:v=self.tone
        super().putbyte(a,v)
    def onread(self,u,access,a,n,value,_):
        pc=u.reg_read(self.A.UC_ARM_REG_PC)
        if 0x53d36400<=a<0x53d37400:self.private_reads.add((pc,a,n))
        if any(lo<=a<hi for lo,hi in self.matrix_windows):self.record_matrix_reads.add((pc,a,n))

class Machine(Trace):
 def alloc(self,size):
  at=OriginalEmulator.alloc(self,size+32);self.allocations.pop();self.allocations.append((at+16,at+16+size));self.u.mem_write(at,b'L'*16);self.u.mem_write(at+16+size,b'R'*16);return at+16
 def canaries(self):
  for a,b in self.allocations:need(bytes(self.u.mem_read(a-16,16))==b'L'*16 and bytes(self.u.mem_read(b,16))==b'R'*16,'heap canary '+hex(a))
 def segment(self,start,end,registers):
  for i in range(13):self.u.reg_write(getattr(self.A,'UC_ARM_REG_R'+str(i)),0)
  self.u.reg_write(self.A.UC_ARM_REG_SP,STACK-0x100);self.u.reg_write(self.A.UC_ARM_REG_LR,STOP);self.u.reg_write(self.A.UC_ARM_REG_CPSR,0x13)
  for i,v in registers.items():self.u.reg_write(getattr(self.A,'UC_ARM_REG_R'+str(i)),v)
  self.u.emu_start(start,end,count=3_000_000,timeout=20_000_000);need(self.u.reg_read(self.A.UC_ARM_REG_PC)==end,'segment return');self.canaries()
 def __init__(self,raw,selection,recipe=True):
  profiles={name:F.load_profile(name,models.GR3X.id) for name in selection.values()}
  edits=[dict(kind='film',slot=s,film=name) for s,name in selection.items()]
  merged=MERGE.prepare(raw,edits,profiles)
  plan=merged['curve'];self.curve=plan;self.packets=merged['packets']
  super().__init__(raw[E.RTOS_BODY:E.RTOS_BODY+E.STOCK_SIZE],plan,18)
  self.ext=merged['extension']
  lo=(E.TAIL+65535)&~65535;hi=(self.ext['end']+65535)&~65535
  if hi>lo:self.u.mem_map(lo,hi-lo)
  self.u.mem_write(E.TAIL,self.ext['extension'])
  self.u.mem_protect(E.TAIL&~0xffff,hi-(E.TAIL&~0xffff),unicorn.UC_PROT_READ|unicorn.UC_PROT_EXEC)
  if recipe:
   for w in self.ext['windows']:
    expected=next((v.replacement for v in plan['windows'] if v.address==w.address),w.expected)
    need(bytes(self.u.mem_read(w.address,len(expected)))==expected,'patch guard '+hex(w.address))
    self.u.mem_write(w.address,w.replacement)
  self.symbols=self.ext['native']['symbols'];self.stub_services={};self.core_reads=set();self.post_seen=[];self.stream_message=None
  self.u.hook_add(unicorn.UC_HOOK_MEM_READ,self._core_read)
  self.transport=self.alloc(4);self.putword(0x55344d7c+0x5a8,self.transport)
  self.pool=self.alloc(E.POOL_EXTENDED);self.putword(0x55344d7c+0x5ac,self.pool);self.putword(self.pool+0x20,E.PHOTO_EXTENDED)
  self.photos=[self.alloc(E.PHOTO_EXTENDED) for _ in range(2)]
  for i,p in enumerate(self.photos):self.putword(self.pool+0x88+4*i,p)
  self.job=self.alloc(1692);self.property=self.alloc(0x5d4);self.original=self.alloc(E.PHOTO_BYTES);self.work=self.alloc(E.PHOTO_BYTES)
  self.putword(0x55086f28,self.job);self.putword(self.job+0x24,self.property);self.putword(self.property+0x5d0,self.original);self.putword(self.job+0x28,self.work)
  self.request=self.alloc(E.REQUEST_EXTENDED+P.MAX_PACKET);self.putword(self.request+E.REQUEST_EXTENDED-4,P.MAX_PACKET);self.putword(self.request+16,self.original);self.putword(self.request+20,self.work)
  self.ui_snapshot=self.alloc(0x820);self.ui_wrapper=self.alloc(12);self.putword(0x550666e0+0x24,self.ui_snapshot);self.putword(0x550666e0+0x18,self.ui_wrapper)
  self.obj=self.alloc(0x400);cfg=self.alloc(0x1000);self.putword(self.obj,0x53dbd8a0)
  self.call(0x536da1fc,self.obj,cfg);self.call(0x536da62c,self.obj,cfg);self.putword(self.obj,0x53dbd8a0)
  self.info=self.alloc(0x9000);self.process=self.alloc(0x4778);self.params=self.alloc(0x3c);self.scratch=self.alloc(0x700);self.putword(self.process+0x5c,self.params)
  device=self.alloc(0x20);self.putword(0x553458ac,1);self.putword(0x553458b4,device);config=self.alloc(0x20);self.putword(device+0x14,config);dims=self.alloc(16);self.putword(config+0x1c,dims);self.u.mem_write(dims+4,struct.pack('<4H',6000,4000,6000,4000))
  self.call(0x536eea90,0x5536dab8);self.putword(0x5536dab4,1)
 def _core_read(self,u,access,a,n,value,x):
  if hasattr(self,'photos'):
   for p in self.photos:
    if p+E.PHOTO_BYTES+16<=a<p+E.PHOTO_EXTENDED:self.core_reads.add((u.reg_read(self.A.UC_ARM_REG_PC),a,n))
 def _code(self,u,a,n,x):
  if not hasattr(self,'stub_services'):return super()._code(u,a,n,x)
  if a==0x534d6260:
   self.stream_message=[u.reg_read(getattr(self.A,'UC_ARM_REG_R'+str(i))) for i in range(4)];self.stub_services['send']=1;self._return(1);return
  if a==0x5382d088:
   req=u.reg_read(self.A.UC_ARM_REG_R1);need(req==self.request,'request freed');u.mem_write(req,bytes([0xdd])*E.REQUEST_EXTENDED);self.stub_services['request_free']=1;self._return(0);return
  if hasattr(self,'symbols') and a==self.symbols['ds_post']:
   at=u.reg_read(self.A.UC_ARM_REG_R1);self.pre_post=list(struct.unpack('<9I',u.mem_read(at,36)))
  if a==0x536e4778:
   ptr=u.reg_read(self.A.UC_ARM_REG_R0) # caller reloads r0 after calc; observed separately below
  if a==0x536e4720:self.last_post_matrix=u.reg_read(self.A.UC_ARM_REG_R0)
  return super()._code(u,a,n,x)
 def call(self,address,*args):
  if isinstance(address,str):address=self.symbols[address]
  need(len(args)<=4,'register argument budget')
  for i in range(13):self.u.reg_write(getattr(self.A,'UC_ARM_REG_R'+str(i)),0)
  for i,v in enumerate(args):self.u.reg_write(getattr(self.A,'UC_ARM_REG_R'+str(i)),v)
  self.u.reg_write(self.A.UC_ARM_REG_SP,STACK-0x100);self.u.reg_write(self.A.UC_ARM_REG_LR,STOP);self.u.reg_write(self.A.UC_ARM_REG_CPSR,0x13)
  self.u.emu_start(address,STOP,count=8_000_000,timeout=20_000_000)
  need(self.u.reg_read(self.A.UC_ARM_REG_PC)==STOP,'bounded return '+hex(address))
  self.canaries();return self.u.reg_read(self.A.UC_ARM_REG_R0)
 def restore(self,packet):
  p=self.alloc(len(packet));self.u.mem_write(p,packet);self.call('ds_begin',self.job+96,self.original,7);need(self.call('ds_restore',self.job+96,p,len(packet))==1,'restore');self.u.mem_write(p,bytes(len(packet)))
 def submit(self,slot,photo=0,selector=0):
  tone=slot+10
  for o,v in DEFAULTS.items():self.putbyte(self.work+o,v)
  self.putbyte(self.work+0x77c,tone);self.putbyte(self.original+0x77c,tone);self.putbyte(self.ui_snapshot+0x77c,tone)
  self.putbyte(0x550666e0+0x3a1,selector);self.segment(0x53289554,0x5328955c,{0:0x550666e0})
  self.putword(self.request+16,self.original);self.putword(self.request+20,self.work);self.putword(self.request+E.REQUEST_EXTENDED-4,P.MAX_PACKET)
  self.segment(0x534d668c,0x534d66a8,{0:self.request,1:0x72c8100d,6:0,11:STACK-0x80})
  self.call('ds_begin',self.job+96,0,8) # later RAW load cannot change queued snapshot
  self.segment(0x5351d3e4,0x5351d3f0,{5:0x55344d7c,7:self.request})
  need(bytes(self.u.mem_read(self.request,8))==bytes([0xdd])*8,'stock handler did not release request')
  self.putword(self.process+0x44c8,self.photos[photo]);self.segment(0x53510800,0x53510834,{0:self.process,1:9,2:self.work})
  self.call('ds_begin',self.pool+0x218,0,0) # pool staging no longer needed by consumer
  return self.photos[photo]
 def make(self,photo):
  self.putbyte(photo+0x7c3,1);self.putword(self.process+0x44c8,photo)
  self.call(0x5350e624,self.process,21);need(self.word(self.process+0x938)==photo,'process header identity')
  self.call(0x535059ec,0,self.info,self.scratch,self.process+0x904)
  need(self.word(self.info+0x82d0)==photo and bytes(self.u.mem_read(self.info+0x82ac,1))==b'\x00','stock Make source binding')
  self.core_reads.clear();self.phase='make'
  self.pre_post=None;self.call(0x536dd8f0,self.obj,self.info)
  need(not self.assertions,'stock assertion '+repr(self.assertions))
  gamma=self.word(self.obj+0x17c)
  return dict(registers=sha(bytes(self.u.mem_read(self.info,0x82ac))),pre_post=self.pre_post,base=sha(bytes(self.u.mem_read(gamma,512))),rgb=sha(bytes(self.u.mem_read(gamma+0x2a08,1536))),post=list(struct.unpack('<9I',self.u.mem_read(self.last_post_matrix,36))),
    core_reads=[list(map(hex,r)) for r in sorted(self.core_reads)])

def validate_consumption(m,p,packet,result):
 core=packet[24:1596];begin=p+E.PHOTO_BYTES+16
 look=[(pc,a,n) for pc,a,n in m.core_reads if pc==0x536dee0c]
 need(len(look)==9 and b''.join(bytes(m.u.mem_read(a,n)) for pc,a,n in sorted(look,key=lambda x:x[1]))==core[:18],'nine actual look reads')
 curves=[(pc,a,n) for pc,a,n in m.core_reads if 0x536e8800<=pc<0x536e89c0]
 need(curves and all(begin+18<=a and a+n<=begin+1554 for pc,a,n in curves),'actual T3 reads')
 matrix=struct.unpack('<9h',core[1554:]);h=[v if v<0x40000 else v-0x80000 for v in result['pre_post']]
 oracle=[((sum(h[3*r+k]*matrix[3*k+c] for k in range(3))+256)>>9)&0x7ffff for r in range(3) for c in range(3)]
 need(result['post']==oracle,'independent post multiplication')
 return dict(look_reads=len(look),curve_reads=len(curves),post_verified=True)

