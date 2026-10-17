"""Independent readback of the extension experiment, never imports a writer.

The caller supplies an independently verified ordinary composite. This reader
checks unchanged sections, recovery windows, exact hook instruction kinds,
allocation sizes, packet identities and every byte outside the declared sites.
Execution semantics are covered by the separately recorded ARM probes.
"""
import hashlib,struct
from . import fwread,models,photo_recipe_extension_read

CALLS={0x534bf468,0x534d6628,0x534ac474,0x534bf4e8,0x535eae94,0x53520c40,0x535239e4,0x53523c10,0x53289558,
       0x534d66a4,0x5351d3ec,0x53510830,0x536ddb38,0x536dc124,0x536dc894,0x536dd29c,
       0x536e8690,0x536e87c4,0x536e4774,0x535fb044,0x535faa90,0x535fada4,0x53603a78}
POINTERS={0x53d31374,0x53d2fa8c,0x53d2e310}
BRANCHES={0x536dc27c,0x535131fc}
MOVW={0x534ac468:(0,1692),0x53520c34:(0,2132),0x53523984:(3,0x48ac),0x534d6624:(1,1624)}
SITES=CALLS|POINTERS|BRANCHES|set(MOVW)|{0x536dd904}

def _binding_contract(native, selected_slots, inplace=False, shutdown_hdf=False):
    # Independent A32 encoding and site-to-role specification. No assembler,
    # planner or writer import. Native compiler output is a separately tested
    # input, not something the readback independently recompiles or proves.
    symbols=native['symbols'];code=native['code'];base=0x540b5600
    if native['base']!=base or not code or len(code)%4:raise ValueError('native contract')
    def branch(site,target,link=False,condition=14):
        delta=target-site-8
        if delta%4 or not -(1<<25)<=delta<(1<<25):raise ValueError('branch extent')
        return (condition<<28)|(0xb000000 if link else 0xa000000)|((delta>>2)&0xffffff)
    def mov(value,reg,top=False):return (0xe3400000 if top else 0xe3000000)|((value&0xf000)<<4)|(reg<<12)|(value&0xfff)
    roles={0x534bf468:'ds_raw_job_release',0x534d6628:'ds_request_alloc',0x534ac474:'ds_raw_job_ctor',0x534bf4e8:'ds_raw_job_load',0x535eae94:'ds_directory_entry',
      0x53520c40:'ds_pool_ctor',0x535239e4:'ds_pool_photo_ctor',0x53523c10:'ds_pool_return',0x53289558:'ds_ui_selector',
      0x534d66a4:'ds_queue_send',0x5351d3ec:'ds_queue_accept',0x53510830:'ds_photo_copy',0x536ddb38:'ds_make_fill',
      0x536dc124:'ds_numeric_controls',0x536dc894:'ds_numeric_controls',0x536dd29c:'ds_numeric_controls',
      0x536e8690:'ds_t3_descriptor',0x536e87c4:'ds_t3_curves'}
    expected={a:branch(a,symbols[n],True) for a,n in roles.items()}
    expected.update({a:symbols[n] for a,n in {0x53d31374:'ds_firmware_write',0x53d2fa8c:'ds_firmware_read',0x53d2e310:'ds_bounded_entry_parse'}.items()})
    expected.update({a:mov(immediate,reg) for a,(reg,immediate) in MOVW.items()});expected[0x536dd904]=0xe24ddf71
    body=bytearray(code)
    def align():body.extend(bytes((-len(body))%16))
    def put(words):body.extend(struct.pack('<'+'I'*len(words),*words))
    align()
    for site,reg,stock,normal in ((0x536dc27c,7,0x536dc818,0x536dc280),(0x535131fc,1,0x53513274,0x53513218)):
        at=base+len(body);expected[site]=branch(site,at)
        put([branch(at,site+4,condition=1),0xe92d500f,0xe1a00000|reg,branch(at+12,symbols['ds_is_archived'],True),
             0xe3500000,0xe8bd500f,branch(at+24,normal,condition=1),branch(at+28,normal if 10 in selected_slots else stock)])
    if inplace and selected_slots:
        at=base+len(body);expected[0x536e87c4]=branch(0x536e87c4,at,True)
        put([mov(0xdab8,12),mov(0x5536,12,True),0xe150000c,
             branch(at+12,0x53dc3468,condition=0),branch(at+16,symbols['ds_t3_curves'])]);align()
    at=base+len(body);expected[0x536e4774]=branch(0x536e4774,at,True)
    fallback=(0x53dc3218 if inplace else 0x536ef6fc) if selected_slots else 0x536e4720
    put([mov(fallback&65535,2),mov(fallback>>16,2,True),branch(at+8,symbols['ds_make_post'])]);align()
    if shutdown_hdf:
        at=base+len(body);expected[0x5319f234]=branch(0x5319f234,at,True)
        put([0xe3510003,branch(at+4,0x5322e4a8,condition=1),0xe92d400d,
             mov(0x8ae0,2),mov(0x5501,2,True),0xe5d22000,0xe3520000,
             branch(at+28,at+60,condition=1),mov(0xd054,2),mov(0x5536,2,True),
             0xe5922000,mov(0x2124,3),mov(0x53d6,3,True),0xe1520003,
             0x03a0100c,0xe8bd400d,branch(at+64,0x5322e4a8)]);align()
    catalog=base+len(body)+64
    for site,name,reg in ((0x535fb044,'ds_dng_reserve',1),(0x535faa90,'ds_dng_layout',2),(0x535fada4,'ds_dng_second_layout',2),(0x53603a78,'ds_jpeg_capture',1)):
        at=base+len(body);expected[site]=branch(site,at,True)
        put([mov(catalog&65535,reg),mov(catalog>>16,reg,True),branch(at+8,symbols[name])]);align()
    return expected,bytes(body),catalog

def verify(official,output,verified_base,packets,native,selected_slots,*,inplace=False,shutdown_hdf=False):
    checks=[]
    def need(ok,why):
        if not ok:raise ValueError(why)
    def add(name):checks.append(dict(id=name,ok=True))
    def sum32(b):
        need(len(b)%4==0,'word alignment');return sum(v for v, in struct.iter_unpack('<I',b))&0xffffffff
    def container(wire):
        need(type(wire) is bytes and len(wire)>=152 and len(wire)%4==0,'container size')
        project,marker,op,n,decoded,checksum=struct.unpack_from('<6I',wire,len(wire)-24)
        need((project,marker,op)==(models.GR3X.project,0xa55a5aa5,2),'container identity')
        end=128+n;aligned=(end+3)&~3
        need(128<end<=aligned<=len(wire)-24 and wire[end:aligned]==bytes(aligned-end),'container extent')
        need(wire[:128]==official[:128] and sum32(wire)==0,'header/checksum')
        # Walk framing independently to prevent an early terminator hiding bytes.
        p=128
        while p<end:
            word=int.from_bytes(wire[p:p+2],'big');p+=2
            if not word:need(p==end,'early stream terminator');break
            count=word&0x7fff;need(count and p+count<=end,'frame extent');p+=count
        else:raise ValueError('missing terminator')
        data=fwread.unpack(wire);need(len(data)==decoded and sum32(data)==0,'decoded length/checksum')
        return data,wire[aligned:-24]
    def records(data):
        out=[];at=0
        while at+16<=len(data):
            name,kind,index,size=struct.unpack_from('<8sHHI',data,at)
            end=len(data) if name.rstrip(b'\0')==b'RES' else at+16+size
            need(at+16<=end<=len(data),'record bound');out.append((name,kind,index,at,end));at=end
        need(at==len(data) and out[-1][0].rstrip(b'\0')==b'RES','record termination');return out
    try:
        need(hashlib.sha256(official).hexdigest()==models.GR3X.input_sha,'official identity')
        original,aux=container(official);base,baseaux=container(verified_base);after,outaux=container(output)
        need(aux==baseaux==outaux,'auxiliary changed');add('container_and_checksums')
        before_rows,after_rows=records(base),records(after)
        need(len(before_rows)==len(after_rows),'record count')
        rtos=None
        for a,b in zip(before_rows,after_rows):
            need(a[:3]==b[:3],'record order/type/index')
            if a[0].rstrip(b'\0')==b'RTOS':rtos=(a,b);continue
            left=base[a[3]:a[4]];right=after[b[3]:b[4]]
            if a[0].rstrip(b'\0')==b'RES':left=left[:-4];right=right[:-4]
            need(left==right,'non-RTOS record changed')
        need(rtos is not None,'RTOS missing');old,new=rtos
        need(old[3]==new[3]==0x10860 and old[4]-old[3]-16==0x10b55c0,'RTOS original layout')
        tail=new[3]+16+0x10b55c0;blob=after[tail:new[4]];manifest=photo_recipe_extension_read.inspect(blob)
        need(len(after)-len(base)==len(blob) and manifest['end']<=0x55000000,'extension length/RAM limit')
        need(struct.unpack_from('<4I',original,0x2a4+20)==(0x4000000,0x53000000,0,0x53000000),'fixed partition')
        for n in manifest['packets']:
            at=n['address']-manifest['address'];need(blob[at:at+n['size']]==packets.get(n['slot']),'packet changed')
        need(set(packets)=={n['slot'] for n in manifest['packets']},'missing packet');add('extension_and_complete_packets')
        restored=bytearray(after[new[3]+16:tail]);before=base[old[3]+16:old[4]]
        low=manifest['code_address'];high=manifest['catalog_address']
        need(type(inplace) is bool and type(shutdown_hdf) is bool,'typed layout choice')
        need(manifest['shutdown_hdf'] == shutdown_hdf,'shutdown feature flag')
        sites=SITES | ({0x5319f234} if shutdown_hdf else set())
        calls=CALLS | ({0x5319f234} if shutdown_hdf else set())
        expected,body,catalog=_binding_contract(native,selected_slots,inplace,shutdown_hdf)
        need(set(expected)==sites and catalog==high,'binding catalog/roles')
        need(blob[64:high-manifest['address']]==body,'native code or binding thunk changed')
        for address in sites:
            off=address-0x53000000;word=struct.unpack_from('<I',restored,off)[0]
            need(word==expected[address],'hook role mismatch '+hex(address))
            if address in calls|BRANCHES:
                need(word>>24==(0xeb if address in calls else 0xea),'hook opcode')
                delta=(word&0xffffff)<<2
                if delta&0x2000000:delta-=0x4000000
                target=address+8+delta;need(low<=target<high and target%4==0,'hook target')
            elif address in POINTERS:need(low<=word<low+manifest['code_size'] and word%4==0,'virtual hook target')
            elif address in MOVW:
                register,immediate=MOVW[address]
                need(word&0xfff0f000==0xe3000000|(register<<12),'allocation MOVW')
                need(((word>>4)&0xf000)|(word&0xfff)==immediate,'allocation size')
            else:need(word==0xe24ddf71,'Make stack allocation')
            restored[off:off+4]=before[off:off+4]
        need(bytes(restored)==before,'undeclared RTOS difference');add('only_reviewed_hook_sites')
        for lo,hi in ((0x53620000,0x53640000),(0x53820000,0x53840000)):
            a=0x10870+lo-0x53000000;b=0x10870+hi-0x53000000
            need(after[a:b]==original[a:b],'recovery path changed')
        add('recovery_code_unchanged')
    except (ValueError,TypeError,IndexError,KeyError,struct.error) as error:
        checks.append(dict(id='closed_failure',ok=False,detail=str(error)))
    return checks
