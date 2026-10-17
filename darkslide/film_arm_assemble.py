"""Local compiler adaptation of gr3-film-mods armasm.py (MIT).
Copyright (c) 2026 idontknownihil. See _vendor/GR3_FILM_MODS_LICENSE.txt.
Modified by LiorMoment: installed LLVM discovery, bounded branches, ELF text extraction,
explicit checks and no objcopy/Homebrew dependency. No generated code is executed.
"""
import re
import struct
import subprocess
import tempfile
from pathlib import Path
from .arm_compiler import resolve_clang

COND = {"b":14,"beq":0,"bne":1,"blo":3,"bhs":2,"bls":9,"bhi":8}

def _text(elf):
    if len(elf)<52 or elf[:7]!=b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H",elf,18)[0]!=40:
        raise ValueError("expected ELF32 little-endian ARM object")
    offset=struct.unpack_from("<I",elf,32)[0]
    width,count,names=struct.unpack_from("<HHH",elf,46)
    if width!=40 or not 0<names<count or offset+width*count>len(elf):
        raise ValueError("invalid ELF section table")
    rows=[struct.unpack_from("<10I",elf,offset+width*i) for i in range(count)]
    def data(row):
        a,n=row[4:6]
        if a+n>len(elf):raise ValueError("section outside object")
        return elf[a:a+n]
    strings=data(rows[names]); found=[]
    for i,row in enumerate(rows):
        n=row[0]
        if n>=len(strings):raise ValueError("invalid section name")
        end=strings.find(b"\0",n)
        if end<0:raise ValueError("unterminated section name")
        if strings[n:end]==b".text":found.append(i)
    if len(found)!=1:raise ValueError("one text section required")
    index=found[0]
    if any(row[1] in (4,9) and row[7]==index and row[5] for row in rows):
        raise ValueError("unresolved text relocation")
    return data(rows[index])

def assemble(source,base):
    if type(source) is not str or type(base) is not int or not 0<=base<2**32 or base%4:
        raise ValueError("typed aligned A32 source/base required")
    lines=[line.split("@")[0].rstrip() for line in source.strip().splitlines()]
    lines=[line for line in lines if line.strip()]
    if not lines or base+4*len(lines)>2**32:raise ValueError("invalid code extent")
    fixed=[]
    for i,line in enumerate(lines):
        at=base+4*i
        m=re.match(r"^\s*(\w+:\s*)?(bl|b|beq|bne|blo|bhs|bls|bhi)\s+abs\((0x[0-9a-fA-F]+)\)\s*$",line)
        if m:
            target=int(m.group(3),16);delta=target-at-8
            if not 0<=target<2**32 or delta%4 or not -(1<<25)<=delta<(1<<25):
                raise ValueError("absolute branch outside A32 range/alignment")
            word=(0xeb000000 if m.group(2)=="bl" else (COND[m.group(2)]<<28)|0x0a000000)|((delta>>2)&0xffffff)
            fixed.append(f"{m.group(1) or ''}.word {word:#x}")
        else:
            bare=re.sub(r"^\s*\w+:\s*","",line).strip()
            if bare.startswith(".") and not re.fullmatch(r"\.word\s+0x[0-9a-fA-F]{1,8}",bare):
                raise ValueError("unsupported assembly directive")
            fixed.append(line)
    with tempfile.TemporaryDirectory(prefix="darkslide-film-") as directory:
        p=Path(directory);src=p/"hook.s";obj=p/"hook.o"
        src.write_text(".syntax unified\n.arm\n.text\n"+"\n".join(fixed)+"\n",encoding='utf-8')
        result=subprocess.run([resolve_clang(),"-target","armv7a-none-eabi","-c","-x","assembler",str(src),"-o",str(obj)],capture_output=True,text=True,encoding='utf-8',errors='replace')
        if result.returncode:raise ValueError("A32 assembly failed: "+result.stderr)
        data=_text(obj.read_bytes())
    if len(data)!=4*len(lines):raise ValueError("one-word instruction contract mismatch")
    return data
