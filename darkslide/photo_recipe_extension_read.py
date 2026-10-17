"""Independent read-only extension reader; no planner/compiler imports.

Structural validity is not a recovery or physical boot guarantee.
"""
import hashlib
import struct
import zlib
from .photo_recipe import decode

BASE=0x540b55c0

def inspect(blob):
    def check(ok,why):
        if not ok:raise ValueError(why)
    check(type(blob) is bytes and 512<=len(blob)<=0xf4aa40 and len(blob)%512==0,'extension extent')
    magic,version,total,code_at,code_size,catalog_at,slots,crc,flags=struct.unpack_from('<8s8I',blob)
    check(magic==b'DSIIIXR1' and version==1 and flags in (0,1) and not any(blob[40:64]),'extension header')
    check(total==len(blob) and zlib.crc32(blob[64:])&0xffffffff==crc,'extension checksum/length')
    check(code_at==64 and 0<code_size<=65536 and code_size%4==0 and
          code_at+code_size<=catalog_at and catalog_at%16==0 and catalog_at+32<=len(blob) and slots==4,'code/catalog bounds')
    packets=[];intervals=[]
    for i in range(4):
        pointer,size=struct.unpack_from('<II',blob,catalog_at+8*i)
        if pointer==size==0:continue
        off=pointer-BASE
        check(pointer%4==0 and catalog_at+32<=off and 1600<=size<=67136 and off+size<=len(blob),'packet extent')
        check(not any(off<b and a<off+size for a,b in intervals),'aliased packet')
        value=blob[off:off+size];recipe=decode(value)
        check(recipe['slot']==i+8,'catalog/packet slot mismatch')
        intervals.append((off,off+size));packets.append(dict(slot=i+8,address=pointer,size=size,sha256=hashlib.sha256(value).hexdigest()))
    intervals.sort();last=catalog_at+32
    for start,end in intervals:
        check(not any(blob[last:start]),'unowned packet padding');last=end
    check(not any(blob[last:]),'nonzero trailing padding')
    return dict(shutdown_hdf=bool(flags & 1),address=BASE,end=BASE+len(blob),size=len(blob),code_address=BASE+code_at,code_size=code_size,
                code_sha256=hashlib.sha256(blob[code_at:code_at+code_size]).hexdigest(),catalog_address=BASE+catalog_at,packets=packets,
                sha256=hashlib.sha256(blob).hexdigest())
