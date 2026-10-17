"""Independent, narrowly scoped IIIx HDF shutdown exception; no writer imports.

Only the explicit recipe-tail candidate with a supplied custom JPEG qualifies.
The ordinary HDF guard remains strict. This is not hardware compatibility proof.
"""
import hashlib
import struct
from . import photo_recipe_extension_read, jpeg_profile

SITE = 0x5319f234
BASE = 0x540b55c0

def _branch(site, target, link=False, condition=14):
    delta=target-site-8
    if delta%4 or not -(1<<25)<=delta<(1<<25):raise ValueError('Street branch bounds')
    return (condition<<28)|(0xb000000 if link else 0xa000000)|((delta>>2)&0xffffff)

def thunk(at):
    # Independent literal A32 specification, including 12 bytes alignment.
    return struct.pack('<20I',0xe3510003,_branch(at+4,0x5322e4a8,condition=1),
        0xe92d400d,0xe3082ae0,0xe3452501,0xe5d22000,0xe3520000,
        _branch(at+28,at+60,condition=1),0xe30d2054,0xe3452536,0xe5922000,
        0xe3023124,0xe34533d6,0xe1520003,0x03a0100c,0xe8bd400d,
        _branch(at+64,0x5322e4a8),0,0,0)

def verify(before, after, jpeg):
    def need(ok, why):
        if not ok:raise ValueError(why)
    def off(at):return 0x10870+at-0x53000000
    need(type(jpeg) is bytes,'Street requires explicit custom JPEG')
    need(hashlib.sha256(before).hexdigest()==
        'c4bfc09d1148deec2155b21bd3d63be8085cf835cbe5e5cde4832747f519e630','Street original')
    size=struct.unpack_from('<I',after,0x1086c)[0]
    growth=size-0x10b55c0
    need(growth>0 and len(after)==len(before)+growth,'Street extension growth')
    blob=after[off(BASE):0x10870+size]
    manifest=photo_recipe_extension_read.inspect(blob)
    need(manifest['shutdown_hdf'],'Street header flag')
    at=manifest['catalog_address']-64-80
    need(at>=manifest['code_address']+manifest['code_size'] and at%16==0,'Street thunk bounds')
    need(after[off(at):off(at)+80]==thunk(at),'Street exact thunk')
    need(before[off(SITE):off(SITE)+4]==bytes.fromhex('9b3c02eb') and
         struct.unpack_from('<I',after,off(SITE))[0]==_branch(SITE,at,True),'Street exact BL')
    left,right=0x5319f180,0x5319f2bc
    restored=bytearray(after[off(left):off(right)])
    restored[SITE-left:SITE-left+4]=before[off(SITE):off(SITE)+4]
    need(bytes(restored)==before[off(left):off(right)],'Street undeclared selector change')
    path=b'A:\\Resource\\Jpeg\\GB_Diary.jpg'
    need(after[off(0x53b2298c):off(0x53b2298c)+len(path)+1]==path+b'\0','Street runtime path')
    header=59298653+growth
    need(after[header:header+32]==path.ljust(32,b'\0') and
         struct.unpack_from('<I',after,header+32)[0]==112509,'Street installed resource')
    # Independent JPEG reader and entropy identity, not writer padding logic.
    padded=after[header+36:header+36+112509]
    original_info=jpeg_profile.inspect(jpeg);actual_info=jpeg_profile.inspect(padded)
    need([(s.code,s.content) for s in jpeg_profile.segments_of(jpeg) if s.code!=254] ==
         [(s.code,s.content) for s in jpeg_profile.segments_of(padded) if s.code!=254] and
         jpeg[original_info['entropy_offset']:] == padded[actual_info['entropy_offset']:],'Street JPEG content')
    expected=[0x53b5f520,0x53b5f508,0x53b5f508,0x53b5f530,0x53b5f518,0x53b5f528,
              0x53b5f568,0x53b5f538,0x53b5f560,0x53b5f508,0x53b5f508,0x53b5f508]
    need(list(struct.unpack_from('<12I',after,off(0x5407e0bc)))==expected,'Street resource aliases')
    need(after[off(0x53b5f508):off(0x53b5f508)+8]==struct.pack('<HHI',720,480,0x53b2298c),
         'Street descriptor')
    return dict(verified=True,hook=hex(SITE),thunk=hex(at),request_from=3,request_to=12,
        condition='request == 3 AND family byte [0x55018ae0] == 0 AND descriptor [0x5536d054] == 0x53d62124',
        ordinary_body_unchanged=True,unknown_identity_unchanged=True,camera_verified=False)
