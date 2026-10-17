"""IIIx-only experimental RTOS-tail fragments, never a flashable firmware export.

Storage rationale: independently checked PARTPARA, BOOT size loader and MMU.
See internal validation report; physical boot/recovery remains untested. This
module does not relax the product's in-place rescue gate or enable a download.
"""
import hashlib
import struct
import zlib
from . import photo_recipe, photo_recipe_native
from .film_arm_assemble import assemble
from .film_patch_plan import Window, _branch

PAYLOAD_SHA='c4bfc09d1148deec2155b21bd3d63be8085cf835cbe5e5cde4832747f519e630'
RTOS_BODY=0x10870
RTOS_BASE=0x53000000
STOCK_SIZE=0x10b55c0
TAIL=RTOS_BASE+STOCK_SIZE
LIMIT=0x55000000
PHOTO_BYTES=0x74270
PHOTO_EXTENDED=PHOTO_BYTES+1596
POOL_EXTENDED=0x218+1596
REQUEST_EXTENDED=24+1596+4 # base; allocator adds bounded inline packet

def require(ok, why):
    if not ok: raise ValueError(why)

def build_fragments(raw, packets, *, post_fallback=0x536e4720, selected_slots=(), inplace=False, shutdown_hdf=False):
    """Four immutable packet slots; absent slots are null, with no license loss.

    post_fallback is either the untouched original calc or the existing film
    writer's reviewed CSP entry. Caller must independently verify composition.
    """
    require(type(raw) is bytes and hashlib.sha256(raw).hexdigest()==PAYLOAD_SHA,'pinned IIIx 1.60 payload required')
    require(type(packets) is dict and all(type(k) is int and 8<=k<=11 for k in packets),'packet slots')
    require(type(selected_slots) is tuple and all(type(s) is int and 8<=s<=11 for s in selected_slots),'selected film slots')
    require(type(inplace) is bool and type(shutdown_hdf) is bool,'typed layout choice')
    require(post_fallback == (0x53dc3218 if selected_slots else 0x536e4720) if inplace
            else post_fallback in (0x536e4720,0x536ef6fc),'unknown post fallback')
    for slot,packet in packets.items():
        decoded=photo_recipe.decode(packet)
        require(decoded['slot']==slot,'packet slot mismatch')
    native=photo_recipe_native.compile_extension(TAIL+64)
    buf=bytearray(64)+native['code'];symbols=native['symbols'];windows=[];purposes=[]
    def align(n=16):buf.extend(bytes((-len(buf))%n))
    def emit(source):
        align();at=TAIL+len(buf);code=assemble(source,at);buf.extend(code);return at
    def write(at,old,new,purpose):
        expected=struct.pack('<I',old) if type(old) is int else old
        replacement=struct.pack('<I',new) if type(new) is int else new
        off=RTOS_BODY+at-RTOS_BASE
        require(raw[off:off+len(expected)]==expected,'preimage '+hex(at))
        require(len(expected)==len(replacement) and not any(at<w.address+len(w.expected) and w.address<at+len(expected) for w in windows),'overlap')
        require(not any(lo<=at<hi for lo,hi in ((0x53620000,0x53640000),(0x53820000,0x53840000))),'recovery path')
        windows.append(Window(at,expected,replacement));purposes.append(purpose)
    def call(site,old,name):write(site,_branch(site,old,link=True),_branch(site,symbols[name],link=True),name)
    def immediate(site,old,source):write(site,old,assemble(source,site),'owned allocation/frame')
    immediate(0x534ac468,0xe3a00060,'movw r0,#1692')
    call(0x534ac474,0x534bef10,'ds_raw_job_ctor')
    call(0x534bf4e8,0x534ad47c,'ds_raw_job_load')
    call(0x534bf468,0x534bf300,'ds_raw_job_release')
    for site,old,name in ((0x53d31374,0x53606738,'ds_firmware_write'),(0x53d2fa8c,0x535ee924,'ds_firmware_read'),(0x53d2e310,0x535d0694,'ds_bounded_entry_parse')):
        write(site,old,symbols[name],name)
    write(0x535eae94,0xe12fff3c,_branch(0x535eae94,symbols['ds_directory_entry'],link=True),'failed parser cleanup')
    immediate(0x53520c34,0xe3a00f86,'movw r0,#'+str(POOL_EXTENDED))
    call(0x53520c40,0x535226c4,'ds_pool_ctor')
    immediate(0x53523984,0xe3043270,'movw r3,#'+str(PHOTO_EXTENDED&65535))
    call(0x535239e4,0x5355e87c,'ds_pool_photo_ctor')
    call(0x53523c10,0x53523a24,'ds_pool_return')
    call(0x53289558,0x53289058,'ds_ui_selector')
    immediate(0x534d6624,0xe3a01018,'movw r1,#'+str(REQUEST_EXTENDED))
    call(0x534d6628,0x5382d074,'ds_request_alloc')
    call(0x534d66a4,0x534d6260,'ds_queue_send')
    call(0x5351d3ec,0x53516b40,'ds_queue_accept')
    call(0x53510830,0x5313fd80,'ds_photo_copy')
    immediate(0x536dd904,0xe24ddf51,'sub sp,sp,#0x1c4')
    call(0x536ddb38,0x536dc0f4,'ds_make_fill')
    for at in (0x536dc124,0x536dc894,0x536dd29c):call(at,0x536db7d8,'ds_numeric_controls')
    for site,photo_reg,stock_target,normal_target in ((0x536dc27c,7,0x536dc818,0x536dc280),(0x535131fc,1,0x53513274,0x53513218)):
        fallback=normal_target if 10 in selected_slots else stock_target
        source='bne abs(%s)\npush {r0,r1,r2,r3,r12,lr}\nmov r0,r%d\nbl abs(%s)\ncmp r0,#0\npop {r0,r1,r2,r3,r12,lr}\nbne abs(%s)\nb abs(%s)'%(hex(site+4),photo_reg,hex(symbols['ds_is_archived']),hex(normal_target),hex(fallback))
        at=emit(source);write(site,_branch(site,stock_target,condition=0),_branch(site,at),'conditional HDR neutralization')
    call(0x536e8690,0x536eed90,'ds_t3_descriptor')
    if inplace and selected_slots:
        # The original descriptor belongs to the current installed look. Its
        # getter returns 33 knots; a stack-owned archived descriptor returns
        # full 256-value curves. The existing composer selects by P+8 record,
        # so an archived stack record follows the original full-curve loop.
        getter=emit('movw r12,#0xdab8\nmovt r12,#0x5536\ncmp r0,r12\nbeq abs(0x53dc3468)\nb abs(%s)'%hex(symbols['ds_t3_curves']))
        write(0x536e87c4,_branch(0x536e87c4,0x536eedf0,link=True),
              _branch(0x536e87c4,getter,link=True),'owned full curves or current readonly knots')
    else:
        call(0x536e87c4,0x536eedf0,'ds_t3_curves')
    post=emit('movw r2,#%d\nmovt r2,#%d\nb abs(%s)'%(post_fallback&65535,post_fallback>>16,hex(symbols['ds_make_post'])))
    write(0x536e4774,_branch(0x536e4774,0x536e4720,link=True),_branch(0x536e4774,post,link=True),'owned post or existing film fallback')
    if shutdown_hdf:
        # Fail closed on uninitialized/foreign identity. Do not call getters or
        # dereference the descriptor: both can be unsafe during shutdown.
        at=emit('cmp r1,#3\nbne abs(0x5322e4a8)\npush {r0,r2,r3,lr}\n'
            'movw r2,#0x8ae0\nmovt r2,#0x5501\nldrb r2,[r2]\ncmp r2,#0\nbne restore\n'
            'movw r2,#0xd054\nmovt r2,#0x5536\nldr r2,[r2]\n'
            'movw r3,#0x2124\nmovt r3,#0x53d6\ncmp r2,r3\nmoveq r1,#12\n'
            'restore: pop {r0,r2,r3,lr}\nb abs(0x5322e4a8)')
        write(0x5319f234,_branch(0x5319f234,0x5322e4a8,link=True),
            _branch(0x5319f234,at,link=True),'conditional IIIx HDF Street shutdown')
    # Catalog trampolines have fixed size; compute their catalog address first.
    align();trampoline_start=len(buf);catalog_at=TAIL+trampoline_start+4*16
    for site,old,name,reg in ((0x535fb044,0x535d0ca8,'ds_dng_reserve',1),(0x535faa90,0x535fa764,'ds_dng_layout',2),(0x535fada4,0x535fac78,'ds_dng_second_layout',2),(0x53603a78,0x53603844,'ds_jpeg_capture',1)):
        at=emit('movw r%d,#%d\nmovt r%d,#%d\nb abs(%s)'%(reg,catalog_at&65535,reg,catalog_at>>16,hex(symbols[name])))
        write(site,_branch(site,old,link=True),_branch(site,at,link=True),name)
    align();require(TAIL+len(buf)==catalog_at,'catalog layout');cat_offset=len(buf);buf.extend(bytes(32));entries=[]
    for slot in range(8,12):
        if slot not in packets:continue
        align(4);at=TAIL+len(buf);data=packets[slot];buf.extend(data)
        struct.pack_into('<II',buf,cat_offset+8*(slot-8),at,len(data))
        entries.append(dict(slot=slot,address=at,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    align(512)
    require(TAIL+len(buf)<=LIMIT and STOCK_SIZE+len(buf)<=0x4000000,'extension memory/flash bound')
    struct.pack_into('<8s8I',buf,0,b'DSIIIXR1',1,len(buf),64,len(native['code']),cat_offset,4,zlib.crc32(buf[64:])&0xffffffff,int(shutdown_hdf))
    return dict(extension=bytes(buf),windows=tuple(windows),purposes=purposes,native=native,catalog=catalog_at,packets=entries,
                address=TAIL,end=TAIL+len(buf),stock_size=STOCK_SIZE,new_rtos_size=STOCK_SIZE+len(buf),
                physical_boot_verified=False,product_export_enabled=False)
