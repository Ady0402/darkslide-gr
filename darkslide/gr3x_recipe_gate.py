"""Request-independent IIIx RTOS-tail constraints. No writer or export bypass.

Only the pinned IIIx original and the known DSIIIXR1 extension are admitted.
Passing these static constraints does not prove installation or recovery.
"""
import hashlib
import struct
from . import fwread, models, rescue_gate, photo_recipe_extension_read


def gate(official, output):
    checks=[]
    def need(ok,why):
        if not ok:raise ValueError(why)
    def add(name,title):checks.append(dict(id=name,title=title,ok=True))
    try:
        need(type(official) is bytes and hashlib.sha256(official).hexdigest()==models.GR3X.input_sha,'IIIx official identity')
        need(type(output) is bytes and output[:128]==official[:128],'original header/version')
        need(len(output)>=152 and len(output)%4==0,'container extent')
        project,marker,op,encoded,decoded,_=struct.unpack_from('<6I',output,len(output)-24)
        need((project,marker,op)==(models.GR3X.project,0xa55a5aa5,2),'footer model')
        end=128+encoded;aligned=(end+3)&~3
        need(128<end<=aligned<=len(output)-24 and not any(output[end:aligned]),'container boundaries')
        original_end=(128+struct.unpack_from('<I',official,len(official)-12)[0]+3)&~3
        need(output[aligned:-24]==official[original_end:-24],'auxiliary bytes')
        need(sum(v[0] for v in struct.iter_unpack('<I',output))&0xffffffff==0,'file checksum')
        need(all(output[o:o+4]==models.GR3X.version for o in (0x38,0x50)),'IIIx version')
        add('recipe_rescue_identity','IIIx 官方原件、文件头及版本字保持不变')
        before,after=fwread.unpack(official),fwread.unpack(output)
        need(len(after)==decoded and len(after)%4==0 and
             sum(v[0] for v in struct.iter_unpack('<I',after))&0xffffffff==0,'payload length/checksum')
        need(hashlib.sha256(before).hexdigest()==models.GR3X.payload_sha,'original payload')
        old,new=rescue_gate.records(before),rescue_gate.records(after)
        need(len(old)==len(new),'record count')
        need([r[0] for r in old]==[r[0] for r in new] and len({r[0] for r in old})==len(old),'record order')
        a=next(r for r in old if r[0]=='RTOS');b=next(r for r in new if r[0]=='RTOS')
        need(a[1]==b[1]==0x10860 and a[2]==0x10870+0x10b55c0,'original RTOS location')
        growth=b[2]-a[2]
        need(0<growth<=0xf4aa40 and growth%512==0 and len(after)-len(before)==growth,'only bounded RTOS growth')
        extension=photo_recipe_extension_read.inspect(after[a[2]:b[2]])
        need(extension['end']<=0x55000000 and b[2]-b[1]-16<=0x4000000,'RAM/flash bound')
        add('recipe_rescue_extension','仅允许已识别的配方扩展；长度、目录及 RAM/闪存上限通过')
        for x,y in zip(old,new):
            name,start,end=x;_,s,e=y
            need(before[start:start+12]==after[s:s+12],'record type/index')
            if name=='RTOS':continue
            need(end-start==e-s,'non-RTOS growth')
            need(before[start:start+16]==after[s:s+16],'non-RTOS header')
            if name not in ('ICONBIN','RES'):need(before[start:end]==after[s:e],'protected record '+name)
        add('recipe_rescue_boot_records','引导链及其它非编辑记录逐字节保持；仅 RTOS 尾部增长')
        for _,_,lo,hi in rescue_gate.PROTECTED:
            start=0x10870+lo-0x53000000;end=0x10870+hi-0x53000000
            need(before[start:end]==after[start:end],'updater/boot flow changed')
        # Original partition, TTBR and every section covering the appended code.
        need(struct.unpack_from('<4I',after,0x2a4+20)==(0x4000000,0x53000000,0,0x53000000),'partition')
        need(struct.unpack_from('<I',after,0x10870+0x434)[0]==0x53004000,'TTBR literal')
        need(struct.unpack_from('<I',after,0x10870+0x2d0)[0]==0xee020f10,'TTBR instruction')
        for index in range(0x540b55c0>>20,((extension['end']-1)>>20)+1):
            off=0x10870+0x4000+index*4
            need(before[off:off+4]==after[off:off+4] and struct.unpack_from('<I',after,off)[0]==((index<<20)|0x1c826),'extension RX mapping')
        add('recipe_rescue_loader_mapping','更新器、引导路径、原分区和扩展执行映射保持已核对状态')
    except (ValueError,TypeError,KeyError,IndexError,struct.error) as exc:
        checks.append(dict(id='recipe_rescue_closed_failure',title='配方扩展离线约束不通过',ok=False,detail=str(exc)))
    return checks
