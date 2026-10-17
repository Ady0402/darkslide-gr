"""Compile freestanding A32 recipe hooks for laboratory or audited RTOS-tail use.

Object extensions require matching allocation patches. No field is treated as
unused space in a stock camera object; this module never serializes firmware.
"""
import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path
from .arm_compiler import resolve_clang

SOURCE = Path(__file__).resolve().parent.parent/'native'/'gr3x_photo_recipe.c'
LAB_BASE = 0x71000000
CONTEXT_SIZE = 1596
RAW_JOB_STOCK_SIZE = 96
RAW_JOB_EXTENDED_SIZE = RAW_JOB_STOCK_SIZE + CONTEXT_SIZE
PRIVATE_TAG = 0xd534
INTEGRATION_ENTRIES = frozenset({'ds_register_ifd', 'ds_refresh_ifd',
    'ds_jpeg_append', 'ds_jpeg_capture', 'ds_dng_reserve', 'ds_dng_layout', 'ds_dng_second_layout',
    'ds_firmware_write', 'ds_bounded_entry_parse', 'ds_directory_entry', 'ds_raw_job_ctor',
    'ds_raw_job_load', 'ds_raw_job_release', 'ds_firmware_read', 'ds_raw_job_view',
    'ds_pool_ctor', 'ds_pool_photo_ctor', 'ds_pool_return', 'ds_ui_selector',
    'ds_request_alloc', 'ds_queue_send', 'ds_queue_accept', 'ds_photo_copy', 'ds_is_archived',
    'ds_make_fill', 'ds_t3_descriptor', 'ds_t3_curves', 'ds_make_post', 'ds_numeric_controls'})


def _need(value, why):
    if not value:
        raise ValueError(why)


def link_lab_object(blob, base=LAB_BASE):
    """Strict single-text ELF32 loader: only local A32 CALL/JUMP relocations.

    No dynamic loader, external symbols, data/BSS allocation or firmware caves.
    ELF bytes must be produced by the local compiler, not a downloaded binary.
    """
    _need(type(base) is int and 0x71000000 <= base <= 0x71ff0000 and base%16 == 0,
          'laboratory address required')
    return _link_object(blob, base)


def _link_object(blob, base):
    _need(type(blob) is bytes and len(blob)>=52 and blob[:7]==b'\x7fELF\x01\x01\x01', 'ELF32 LE required')
    _need(struct.unpack_from('<HH',blob,16)==(1,40), 'relocatable ARM object required')
    offset=struct.unpack_from('<I',blob,32)[0]
    width,count,names=struct.unpack_from('<HHH',blob,46)
    _need(width==40 and 0<names<count and offset+width*count<=len(blob),'ELF section bounds')
    rows=[struct.unpack_from('<10I',blob,offset+width*i) for i in range(count)]
    def data(row):
        a,n=row[4:6]; _need(a+n<=len(blob),'section bounds'); return blob[a:a+n]
    strings=data(rows[names])
    def name(table,at):
        _need(at<len(table),'string offset'); end=table.find(b'\0',at)
        _need(end>=at,'unterminated string'); return table[at:end].decode('ascii')
    section_names=[name(strings,r[0]) for r in rows]
    _need(section_names.count('.text')==1,'one text section required')
    ti=section_names.index('.text'); code=bytearray(data(rows[ti]))
    _need(0<len(code)<=65536 and len(code)%4==0,'text bounds')
    _need(all(i==ti or not (r[2]&2) or r[1]==0x70000001 or not r[5]
              for i,r in enumerate(rows)),'unexpected allocated data')
    syms={}; by_index={}
    for i,r in enumerate(rows):
        if r[1]!=2: continue
        _need(r[9]==16 and r[5]%16==0 and r[6]<count,'symbol table shape')
        table=data(rows[r[6]])
        entries=[struct.unpack_from('<IIIBBH',data(r),j) for j in range(0,r[5],16)]
        by_index[i]=entries
        for n,value,size,info,other,section in entries:
            if info&15==2 and section==ti:
                _need(value%4==0 and value+size<=len(code),'function outside text')
                syms[name(table,n)]=base+value
    for r in rows:
        if r[1] not in (4,9) or r[7]!=ti or not r[5]: continue
        _need(r[1]==9 and r[9]==8 and r[5]%8==0 and r[6] in by_index,'unsupported relocation table')
        entries=by_index[r[6]]
        for j in range(0,r[5],8):
            at,info=struct.unpack_from('<II',data(r),j); kind=info&255; symbol=info>>8
            _need(kind in (28,29) and symbol<len(entries) and at%4==0 and at+4<=len(code),'unsupported relocation')
            n,value,size,bind,other,section=entries[symbol]
            _need(section==ti and value%4==0 and value<len(code),'external symbol')
            word=struct.unpack_from('<I',code,at)[0]
            _need(word&0xfe000000==0xea000000,'not an unconditional A32 branch')
            addend=(word&0xffffff)<<2
            if addend&(1<<25): addend-=1<<26
            delta=value+addend-at
            _need(delta%4==0 and -(1<<25)<=delta<(1<<25),'branch bounds')
            struct.pack_into('<I',code,at,(word&0xff000000)|((delta>>2)&0xffffff))
    expected={'ds_validate','ds_begin','ds_restore','ds_view','ds_capture',
              'ds_write_adapter','ds_read_adapter','ds_post'}
    _need((expected | INTEGRATION_ENTRIES)<=set(syms),'native entry missing')
    return dict(code=bytes(code),symbols=syms,base=base)


def compile_lab(base=LAB_BASE):
    _need(type(base) is int and 0x71000000 <= base <= 0x71ff0000 and base%16 == 0,
          'laboratory address required')
    return _compile(base)


def compile_extension(base=0x540b5600):
    """Link only into the separately audited IIIx RTOS tail, not a stock cave.

    This emits a code fragment. It does not alter, repack or export firmware.
    """
    _need(type(base) is int and 0x540b55c0 <= base <= 0x54ff0000 and base%16 == 0,
          'IIIx extension address required')
    return _compile(base)


def _compile(base):
    flags=['-target','armv7a-none-eabi','-marm','-O2','-ffreestanding','-fno-builtin',
           '-fno-stack-protector','-fno-jump-tables','-fno-unwind-tables',
           '-fno-asynchronous-unwind-tables','-Wall','-Wextra','-Werror']
    with tempfile.TemporaryDirectory(prefix='darkslide-photo-native-') as directory:
        obj=Path(directory)/'runtime.o'
        result=subprocess.run([resolve_clang(),*flags,'-c',str(SOURCE),'-o',str(obj)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        _need(result.returncode==0,'A32 compile failed: '+result.stderr)
        raw=obj.read_bytes(); out=_link_object(raw,base)
    out.update(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               code_sha256=hashlib.sha256(out['code']).hexdigest(),flags=flags,
               raw_job_extended_bytes=RAW_JOB_EXTENDED_SIZE,
               firmware_installed=False,object_ownership_verified=False)
    return out
