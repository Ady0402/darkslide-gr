/* Darkslide GR IIIx 1.60 photo recipe runtime, LiorMoment, 2026.
 * Installed only by the explicit offline extension builder with matching sizes.
 * Contexts belong to RAW jobs, queued requests and pool photos. Restored Make
 * calls use a stack-local descriptor; no mutable shared recipe library.
 * JSON provenance is opaque here: the desktop validates it before ROM packing.
 * Runtime validates the numeric ABI and CRC, not JSON or authenticity.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed int i32;
#define CORE_BYTES 1572u
#define MAX_PACKET (24u + CORE_BYTES + 65536u + 4u)
#define PRIVATE_TAG 0xd534u /* Experimental private namespace, not a vendor assignment. */
struct packet_ref { const u8 *bytes; u32 size; };
struct context { u32 owner, epoch, state, slot; u8 core[CORE_BYTES]; struct packet_ref packet; };
/* These extensions are synthetic test objects, NOT known free firmware fields. */
struct writer_adapter { u8 stock[40]; const struct packet_ref *catalog; };
struct reader_adapter { u8 stock[40]; struct context *context; };
struct tag { u32 vtable; u16 id, type; u32 count, value; u8 *data; u8 enabled; u8 pad[3]; };
_Static_assert(sizeof(struct context)==1596, "context ABI");
_Static_assert(sizeof(struct tag)==24, "original tag ABI");
_Static_assert(sizeof(struct packet_ref)==8, "A32 catalog ABI");
static u32 get16(const u8 *p) { return p[0] | ((u32)p[1]<<8); }
static u32 get32(const u8 *p) { return get16(p) | (get16(p+2)<<16); }
static i32 signed16(const u8 *p) { u32 v=get16(p); return v<32768 ? (i32)v : (i32)v-65536; }
static void copy(u8 *d,const u8 *s,u32 n) { while(n--) *d++=*s++; }
static u32 checksum(const u8 *p,u32 n) {
    u32 c=~0u;
    while(n--) { c^=*p++; for(u32 i=0;i<8;i++) c=(c>>1)^((0u-(c&1))&0xedb88320u); }
    return ~c;
}
u32 ds_validate(const u8 *p,u32 n) {
    if(!p || n<24+CORE_BYTES+4 || n>MAX_PACKET) return 0;
    if(get32(p)!=0x49465344 || get32(p+4)!=0x00004d4c ||
       get16(p+8)!=1 || get16(p+10)!=1 || get16(p+14)!=0 ||
       get32(p+16)!=CORE_BYTES || get32(p+20)>65536 ||
       get32(p+20)!=n-24-CORE_BYTES-4 || get16(p+12)<8 || get16(p+12)>11) return 0;
    if(checksum(p,n-4)!=get32(p+n-4)) return 0;
    const u8 *q=p+24;
    for(u32 row=0;row<3;row++) {
        i32 sum=0;
        for(u32 col=0;col<3;col++) sum+=signed16(q+6*row+2*col);
        if(sum!=8192) return 0;
    }
    for(u32 i=0;i<768;i++) if(get16(q+18+2*i)>16383) return 0;
    q+=1554;
    for(u32 row=0;row<3;row++) {
        i32 sum=0;
        for(u32 col=0;col<3;col++) sum+=signed16(q+6*row+2*col);
        if(sum!=512) return 0;
    }
    for(u32 col=0;col<3;col++) {
        u32 sum=0;
        for(u32 row=0;row<3;row++) { i32 v=signed16(q+6*row+2*col); sum+=(u32)(v<0?-v:v); }
        if(sum>8191) return 0;
    }
    return 1;
}
static void init(struct context *c,u32 owner,u32 epoch) {
    /* Drop state first: a missing/bad tag must never reuse the preceding photo. */
    c->state=0; c->owner=owner; c->epoch=epoch; c->slot=0;
    c->packet.bytes=(void*)0; c->packet.size=0;
    for(u32 i=0;i<CORE_BYTES;i++) c->core[i]=0;
}
static void discard(struct context *c) {
    const u8 *p=c->packet.bytes;
    c->packet.bytes=(void*)0; c->packet.size=0;
    if(p) ((void (*)(const void*))0x536af2e4u)(p);
}
void ds_begin(struct context *c,u32 owner,u32 epoch) {
    /* Already initialized, exclusively owned context. Constructors use init. */
    discard(c); init(c,owner,epoch);
}
static void retain(struct context *c,const u8 *p,u32 n) {
    /* Failure drops only the optional archive; numerical restoration survives.
     * Never fall back to a current catalog for an archived photo in this case. */
    if(!p || n<24+CORE_BYTES+4 || n>MAX_PACKET) return;
    u8 *owned=((u8 *(*)(u32))0x536af2a8u)(n);
    if(owned) { copy(owned,p,n); c->packet.bytes=owned; c->packet.size=n; }
}
u32 ds_restore(struct context *c,const u8 *p,u32 n) {
    if(!c || !c->owner) return 0;
    if(c->state) { discard(c); c->state=2; return 0; } /* Duplicate is ambiguous. */
    c->state=2;
    if(!ds_validate(p,n)) return 0;
    copy(c->core,p+24,CORE_BYTES); c->slot=get16(p+12); c->state=1;
    retain(c,p,n);
    return 1;
}
u32 ds_view(struct context *c,u32 owner,u32 epoch,u32 selector,u32 *out) {
    /* Explicitly selecting another look does not apply the archived recipe. */
    if(!c || c->state!=1 || c->owner!=owner || c->epoch!=epoch || selector!=0) return 0;
    out[0]=(u32)c->core;
    out[1]=(u32)(c->core+18); out[2]=(u32)(c->core+530); out[3]=(u32)(c->core+1042);
    out[4]=(u32)(c->core+1554); out[5]=c->slot+10;
    return 1;
}
static const struct packet_ref *capture_ref(const u8 *photo,const struct packet_ref *catalog);
u32 ds_capture(const u8 *photo,const struct packet_ref *catalog,struct tag *t) {
    if(!t || t->id!=PRIVATE_TAG || t->type!=7 || !t->data) return 0;
    const struct packet_ref *r=capture_ref(photo,catalog);
    /* Exact preallocated size: changing count during serialization breaks offsets. */
    if(!r || t->count!=r->size) return 0;
    copy(t->data,r->bytes,r->size); return 1;
}
static u32 prepare_ref(const struct packet_ref *r,struct tag *t) {
    /* NEW tag object only, before IFD layout/size calculation. Its enclosing
     * IFD must register it and retain ownership through serialization. */
    u32 valid=r!=0;
    ((void (*)(void*,u32,u32,u32,u32))0x535d0230u)(t,PRIVATE_TAG,7,valid?r->size:0,0);
    if(!valid || !t->data) { t->enabled=0; return 0; }
    return 1;
}
u32 ds_prepare(const u8 *photo,const struct packet_ref *catalog,struct tag *t) {
    return prepare_ref(capture_ref(photo,catalog),t);
}
u32 ds_write_adapter(struct writer_adapter *w,struct tag *t,u32 ns,u32 index) {
    if(t->id!=PRIVATE_TAG)
        return ((u32 (*)(void*,void*,u32,u32))0x53606738u)(w,t,ns,index);
    if(ns!=4) return 0;
    const u8 *photo=(const u8*)get32(w->stock+24);
    return ds_capture(photo,w->catalog,t);
}
u32 ds_read_adapter(struct reader_adapter *r,struct tag *t,u32 ns,u32 index) {
    if(t->id!=PRIVATE_TAG)
        return ((u32 (*)(void*,void*,u32,u32))0x535ee924u)(r,t,ns,index);
    if(ns!=4) return 0;
    struct context *c=r->context;
    if(!c || c->owner!=get32(r->stock+8)) return 0;
    if(t->type!=7 || !t->data || t->count>MAX_PACKET) { discard(c); c->state=2; return 1; }
    ds_restore(c,t->data,t->count);
    /* Malformed optional metadata disables restoration, not the whole photo. */
    return 1;
}
void ds_post(struct context *c,u32 *matrix) {
    if(!c || c->state!=1) return;
    i32 a[9];
    for(u32 i=0;i<9;i++) { u32 v=matrix[i]&0x7ffff; a[i]=v<0x40000 ? (i32)v : (i32)v-0x80000; }
    for(u32 row=0;row<3;row++) for(u32 col=0;col<3;col++) {
        i32 sum=256;
        for(u32 k=0;k<3;k++) sum+=a[3*row+k]*signed16(c->core+1554+6*k+2*col);
        /* ARM arithmetic shift, floor rounding; result is a signed19 bit field. */
        matrix[3*row+col]=((u32)(sum>>9))&0x7ffff;
    }
}

/* Integration candidates, executed with original call sites in the offline
 * address space. Deployment still requires a reviewed ROM placement and RAW
 * queue/pipeline binding. Original writer/reader objects remain exactly 40 B. */
struct raw_job { u8 stock[96]; struct context recipe; };
_Static_assert(sizeof(struct raw_job)==1692, "extended RAW job ABI");
static void *tag_alloc(u32 n) {
    void *a=((void *(*)(u32))0x536abf18u)(4);
    u32 *v=*(u32**)a;
    return ((void *(*)(void*,u32,u32,u32))v[2])(a,n,0,0);
}
static void delete_tag(struct tag *t) {
    ((void (*)(void*))0x535d0a3cu)(t);
}
u32 ds_register_ifd(u8 *ifd,const u8 *photo,const struct packet_ref *catalog) {
    /* Only a fresh writer directory: never infer ownership of an existing tag.
     * All bytes are prepared BEFORE the original layout pass. */
    if(!ifd || ifd[0x24]!=4) return 0;
    u32 lo=get32(ifd+12),end=get32(ifd+16),cap=get32(ifd+20);
    if(!lo || (lo|end|cap)&3 || end<lo || cap<end || (end-lo)/4>255 || cap-end<4) return 0;
    for(u32 at=lo;at<end;at+=4) {
        struct tag *old=*(struct tag**)at;
        if(!old || old->id==PRIVATE_TAG) return 0;
    }
    const struct packet_ref *r=capture_ref(photo,catalog);
    if(!r) return 0;
    struct tag *t=tag_alloc(sizeof(*t));
    if(!t) return 0;
    if(!prepare_ref(r,t)) { delete_tag(t); return 0; }
    copy(t->data,r->bytes,r->size);
    ((void (*)(void*,void*))0x535cfaa0u)(ifd,t);
    /* Capacity was checked, so the stock vector cannot allocate while inserting. */
    if(get32(ifd+16)!=end+4 || *(struct tag**)end!=t) { delete_tag(t); return 0; }
    return 1;
}
u32 ds_firmware_write(void *writer,struct tag *t,u32 ns,u32 index) {
    if(t->id!=PRIVATE_TAG)
        return ((u32 (*)(void*,void*,u32,u32))0x53606738u)(writer,t,ns,index);
    /* Prepared data is immutable for this directory, including its byte count.
     * No allocation, mode lookup or CRC work occurs during serialization. */
    return ns==4 && t->enabled && t->type==7 && t->data &&
           t->count>=24+CORE_BYTES+4 && t->count<=MAX_PACKET;
}
u32 ds_refresh_ifd(u8 *ifd,const u8 *photo,const struct packet_ref *catalog) {
    /* The original formatter may be reused. Call before EACH layout pass on
     * its owned writer directory, never an imported reader directory. */
    if(!ifd || ifd[0x24]!=4) return 0;
    u32 lo=get32(ifd+12),end=get32(ifd+16),cap=get32(ifd+20),found=0;
    struct tag *t=(void*)0;
    if(!lo || (lo|end|cap)&3 || end<lo || cap<end || (end-lo)/4>255) return 0;
    for(u32 at=lo;at<end;at+=4) {
        struct tag *item=*(struct tag**)at;
        if(!item) return 0;
        if(item->id==PRIVATE_TAG) { item->enabled=0; t=item; found++; }
    }
    if(!found) return ds_register_ifd(ifd,photo,catalog);
    if(found!=1 || t->vtable!=0x53d2e308u) return 0;
    ((void (*)(void*))0x535d0198u)(t);
    const struct packet_ref *r=capture_ref(photo,catalog);
    if(!prepare_ref(r,t)) return 0;
    copy(t->data,r->bytes,r->size);
    return 1;
}
u32 ds_dng_reserve(void *wrapper,const struct packet_ref *catalog) {
    /* 535fb044 runs before a source photo is attached. A later restored RAW
     * may carry the ABI maximum even when this ROM has no catalog. Reserve
     * that bound once, including entry/alignment, before parent allocation.
     * This increases metadata workspace only; no photo/object size changes. */
    (void)catalog;
    return ((u32 (*)(void*))0x535d0ca8u)(wrapper)+12+((MAX_PACKET+3)&~3u);
}
static void dng_refresh(u8 *formatter,void *source,const struct packet_ref *catalog) {
    const u8 *photo=((const u8 *(*)(void*))0x535fc2f8u)(source);
    u8 *ifd=formatter+0x134;
    ds_refresh_ifd(ifd,photo,catalog);
    /* A caller reusing the object with a larger/different catalog must not
     * overrun the parent reservation. Drop ONLY our optional tag on overflow;
     * the original assertion continues to protect the original directory. */
    if(((u32 (*)(void*))0x535d0ca8u)(formatter+0x124)>get32(formatter+0x290)) {
        u32 end=get32(ifd+16);
        for(u32 at=get32(ifd+12);at<end;at+=4) {
            struct tag *t=*(struct tag**)at;
            if(t->id==PRIVATE_TAG) t->enabled=0;
        }
    }
}
void ds_dng_layout(u8 *formatter,void *source,const struct packet_ref *catalog) {
    /* Replacement of the call at 535faa90, not the middle of a function. */
    dng_refresh(formatter,source,catalog);
    ((void (*)(void*,void*))0x535fa764u)(formatter,source);
}
void ds_dng_second_layout(u8 *formatter,void *source,const struct packet_ref *catalog) {
    /* Additional-image directory pass at 535fada4. Its parent reservation is
     * retained, but this pass selects source variant 1 or 2 independently. */
    dng_refresh(formatter,source,catalog);
    ((void (*)(void*,void*))0x535fac78u)(formatter,source);
}
u32 ds_bounded_entry_parse(struct tag *t,void *stream,u32 offset) {
    /* Hook only the generic tag parser. The factory already supplies the ID;
     * bound the optional packet before the original parser allocates its data. */
    if(t->id==PRIVATE_TAG) {
        u32 *v=*(u32**)stream;
        u16 header[2]={0,0}; u32 count=0;
        if(offset>0xfffffff3u) return 0;
        u32 ok=((u32 (*)(void*,void*,u32,u32))v[3])(stream,header,2,offset);
        ok=ok && ((u32 (*)(void*,void*,u32,u32))v[4])(stream,&count,1,offset+4);
        if(!ok) return 0;
        if(header[0]!=PRIVATE_TAG || header[1]!=7 || count<24+CORE_BYTES+4 || count>MAX_PACKET) {
            /* Retain a zero-sized invalid marker: the reader invalidates a
             * previous valid duplicate instead of silently accepting it. */
            t->type=7; t->count=0; t->value=0; t->enabled=1; return 1;
        }
        /* Stock 535d0598 discards the stream read status. Our optional payload
         * needs a checked read; retain the stock allocator and tag destructor. */
        u32 position=0;
        if(!((u32 (*)(void*,void*,u32,u32))v[4])(stream,&position,1,offset+8) ||
           position>0xffffffffu-count || t->data) return 0;
        t->type=7; t->count=count; t->value=position;
        if(!((u32 (*)(void*,u32))0x535d01d8u)(t,count)) return 0;
        return ((u32 (*)(void*,void*,u32,u32))v[2])(stream,t->data,count,position);
    }
    return ((u32 (*)(void*,void*,u32))0x535d0694u)(t,stream,offset);
}
u32 ds_directory_entry(struct tag *t,void *stream,u32 offset) {
    /* Replacement for the parse call at 535eae94 ONLY: the directory factory
     * has created this entry but has not inserted it. Its original failure
     * branch frees the directory, omitting the not-yet-inserted entry. */
    u32 *v=(u32*)t->vtable;
    u32 result=((u32 (*)(void*,void*,u32))v[2])(t,stream,offset);
    if(!result) ((void (*)(void*))v[1])(t);
    return result;
}
void *ds_raw_job_ctor(struct raw_job *job) {
    ((void (*)(void*))0x534bef10u)(job);
    init(&job->recipe,0,0);
    return job;
}
u32 ds_raw_job_load(struct raw_job *job,void *property,void *file) {
    u32 owner=(property && get32(job->stock+0x24)==(u32)property)?get32((u8*)property+0x5d0):0;
    ds_begin(&job->recipe,owner,job->recipe.epoch+1);
    u32 result=((u32 (*)(void*,void*,void*))0x534ad47cu)(job,property,file);
    if(result) ds_begin(&job->recipe,0,job->recipe.epoch);
    return result;
}
void ds_raw_job_release(struct raw_job *job) {
    ds_begin(&job->recipe,0,job->recipe.epoch+1);
    ((void (*)(void*))0x534bf300u)(job);
}
u32 ds_firmware_read(void *reader,struct tag *t,u32 ns,u32 index) {
    if(t->id!=PRIVATE_TAG)
        return ((u32 (*)(void*,void*,u32,u32))0x535ee924u)(reader,t,ns,index);
    if(ns!=4) return 0;
    /* Existing PlayJob registry slot 8. This function may only be installed as
     * part of the plan that enlarges and initializes that unique allocation. */
    struct raw_job *job=*(struct raw_job**)0x55086f28u;
    if(!job) return 1;
    struct context *c=&job->recipe;
    if(!c->owner || c->owner!=get32((u8*)reader+8)) return 1;
    if(t->type!=7 || !t->data || t->count>MAX_PACKET) { discard(c); c->state=2; return 1; }
    ds_restore(c,t->data,t->count); return 1;
}
u32 ds_raw_job_view(struct raw_job *job,u32 photo,u32 selector,u32 *out) {
    /* A candidate handoff API, NOT a discovered pipeline hook. The caller must
     * pin this task until consumption finishes and supply the genuine selector. */
    u32 property=get32(job->stock+0x24);
    if(!property || get32((u8*)property+0x5d0)!=job->recipe.owner || !photo ||
       (photo!=job->recipe.owner && photo!=get32(job->stock+0x28))) return 0;
    return ds_view(&job->recipe,job->recipe.owner,job->recipe.epoch,selector,out);
}

/* Queue integration for the pinned 1.60 image. These extensions are installed
 * together with their allocation patches; they are never stock spare fields. */
#define PHOTO_BYTES 0x74270u
#define POOL_BYTES 0x218u
#define ENGINE 0x55344d7cu
#define POOL_PHOTO_BYTES (PHOTO_BYTES + sizeof(struct context))
static u8 *pool_current(void) { return *(u8**)(ENGINE+0x5ac); }
static struct context *pool_photo(u8 *pool,const u8 *photo,u32 busy) {
    if(!pool || !photo || get32(pool+0x20)!=POOL_PHOTO_BYTES) return (void*)0;
    for(u32 i=0;i<100;i++) if(get32(pool+0x88+4*i)==(u32)photo) {
        if(busy && pool[0x24+i]) return (void*)0;
        return (struct context*)(photo+PHOTO_BYTES);
    }
    return (void*)0;
}
/* Shared JPEG/DNG admission: an active owned archive is authoritative.
 * A missing/damaged packet must never be relabelled with today's catalog. */
static const struct packet_ref *capture_ref(const u8 *photo,const struct packet_ref *catalog) {
    if(!photo) return (void*)0;
    u32 tone=photo[0x77c];
    if(tone<18 || tone>21) return 0;
    struct context *c=pool_photo(pool_current(),photo,1);
    const struct packet_ref *r;
    if(c && c->state==1 && c->owner==(u32)photo) {
        if(tone!=c->slot+10) return 0;
        r=&c->packet;

    } else {
        if(!catalog) return 0;
        r=catalog+tone-18;
    }
    if(!ds_validate(r->bytes,r->size) || get16(r->bytes+12)!=tone-10) return 0;
    if(c && c->state==1 && c->owner==(u32)photo)
        for(u32 i=0;i<CORE_BYTES;i++) if(c->core[i]!=r->bytes[24+i]) return 0;
    return r;
}
static void snapshot(struct context *dst,const struct context *src,u32 owner) {
    ds_begin(dst,owner,src?src->epoch:0);
    if(src && src->state==1 && src->owner && src->slot>=8 && src->slot<=11) {
        copy(dst->core,src->core,CORE_BYTES); dst->slot=src->slot; dst->state=1;
        retain(dst,src->packet.bytes,src->packet.size);
    }
}
void *ds_pool_ctor(u8 *pool) {
    ((void (*)(void*))0x535226c4u)(pool);
    init((struct context*)(pool+POOL_BYTES),0,0); return pool;
}
void *ds_pool_photo_ctor(u8 *photo) {
    ((void (*)(void*))0x5355e87cu)(photo);
    init((struct context*)(photo+PHOTO_BYTES),0,0); return photo;
}
void ds_pool_return(u8 *pool,u8 *photo) {
    struct context *c=pool_photo(pool,photo,0);
    if(c) ds_begin(c,0,c->epoch+1);
    ((void (*)(void*,void*))0x53523a24u)(pool,photo);
}
u32 ds_ui_selector(u8 *model,u32 selector) {
    /* ONLY the apply call at 53289558, not the menu-query function itself.
     * Preserve the validated recipe while remembering an explicit selection,
     * including reselecting the same numbered film slot. */
    struct raw_job *job=*(struct raw_job**)0x55086f28u;
    /* model +24 is an owned 0x820-byte settings snapshot, and +18 a
     * 12-byte editor wrapper: neither is a RAW photo identity pointer.
     * This dedicated apply call acts on the sole registered RAW job. Verify
     * that job still owns the loaded property before changing its selection. */
    u8 *property=job ? *(u8**)(job->stock+0x24) : (void*)0;
    if(job && model==(u8*)0x550666e0u && property && job->recipe.owner &&
       get32(property+0x5d0)==job->recipe.owner && get32(model+0x24)) {
        u32 state=job->recipe.state;
        if(state==1 || (state>=0x101 && state<=0x10c))
            job->recipe.state=selector==0 ? 1 : selector<=12 ? 0x100+selector : 2;
    }
    return ((u32 (*)(void*,u32))0x53289058u)(model,selector);
}
#define REQUEST_BASE (24u + sizeof(struct context) + 4u)
void *ds_request_alloc(void *allocator,u32 size) {
    /* Store the queued packet INSIDE the stock-owned request allocation.
     * Send/cancel/discard/free paths therefore cannot leak a separate packet.
     * No assumptions about the stock sender's return value or consumption time. */
    (void)size;
    struct raw_job *job=*(struct raw_job**)0x55086f28u;
    u32 n=job && job->recipe.state==1 ? job->recipe.packet.size : 0;
    if(n>MAX_PACKET || (n && !job->recipe.packet.bytes)) n=0;
    u8 *p=((u8 *(*)(void*,u32))0x5382d074u)(allocator,REQUEST_BASE+n);
    if(!p && n) { n=0; p=((u8 *(*)(void*,u32))0x5382d074u)(allocator,REQUEST_BASE); }
    if(p) *(u32*)(p+REQUEST_BASE-4)=n;
    return p;
}
u32 ds_queue_send(void *sender,u32 message,u8 *request,u32 flags,void *shared) {
    struct context *dst=(struct context*)(request+24);
    struct raw_job *job=*(struct raw_job**)0x55086f28u;
    u8 *property=job ? *(u8**)(job->stock+0x24) : (void*)0;
    init(dst,0,0); /* Fresh request; its packet is borrowed from its own tail. */
    if(message==0x72c8100du && job && property &&
       get32(property+0x5d0)==job->recipe.owner && get32(request+16)==job->recipe.owner &&
       get32(request+20)==get32(job->stock+0x28) && job->recipe.state==1 &&
       job->recipe.slot>=8 && job->recipe.slot<=11) {
        const struct context *src=&job->recipe;
        dst->owner=get32(request+20); dst->epoch=src->epoch;
        dst->state=1; dst->slot=src->slot; copy(dst->core,src->core,CORE_BYTES);
        u32 n=src->packet.size,capacity=get32(request+REQUEST_BASE-4);
        if(src->packet.bytes && n && n<=MAX_PACKET && n<=capacity && capacity<=MAX_PACKET) {
            copy(request+REQUEST_BASE,src->packet.bytes,n);
            dst->packet.bytes=request+REQUEST_BASE; dst->packet.size=n;
        }
    }
    return ((u32 (*)(void*,u32,void*,u32,void*))0x534d6260u)(sender,message,request,flags,shared);
}
void ds_queue_accept(u8 *engine,u8 *request) {
    u8 *pool=*(u8**)(engine+0x5ac);
    if(pool && get32(pool+0x20)==POOL_PHOTO_BYTES) {
        struct context *src=(struct context*)(request+24);
        struct context *dst=(struct context*)(pool+POOL_BYTES);
        if(src->owner==get32(request+20)) snapshot(dst,src,src->owner);
        else ds_begin(dst,0,0);
    }
    /* This call frees the request via 53522688; never read it afterwards. */
    ((void (*)(void*,void*))0x53516b40u)(engine,request);
}
void *ds_photo_copy(u8 *dst,const u8 *src,u32 size) {
    ((void (*)(void*,const void*,u32))0x5313fd80u)(dst,src,size);
    u8 *pool=pool_current(); struct context *c=pool_photo(pool,dst,1);
    if(c) {
        struct context *pending=(struct context*)(pool+POOL_BYTES);
        ds_begin(c,0,0);
        if(size==PHOTO_BYTES && get16((u8*)ENGINE+0x99c)==2 &&
           *(u32*)(ENGINE+0x9a8)==(u32)src && pending->owner==(u32)src)
            snapshot(c,pending,(u32)dst);
    }
    return dst;
}
u32 ds_is_archived(const u8 *photo) {
    struct context *c=pool_photo(pool_current(),photo,1);
    return c && c->state==1 && c->owner==(u32)photo && photo[0x77c]==c->slot+10;
}
/* 128 bytes added to the stock Make stack frame, below its packet. No shared
 * T3 descriptor or shared library pointers are used for an archived recipe. */
struct make_frame { u32 magic; struct context *context; u8 record[84]; u8 descriptor[12]; };
_Static_assert(sizeof(struct make_frame)==104,"Make frame budget");
static struct make_frame *bound_frame(u8 *packet) {
    struct make_frame *f=(struct make_frame*)(packet-128);
    /* Test the stock packet's valid record pointer BEFORE reading an extension
     * that ordinary callers of the shared T3/CSP functions need not allocate. */
    if(get32(packet+8)!=(u32)f->record) return (void*)0;
    if(f->magic!=0x44534652u || !f->context || f->context->state!=1) return (void*)0;
    return f;
}
void ds_make_fill(void *object,u8 *config,u8 *packet) {
    ((void (*)(void*,void*,void*))0x536dc0f4u)(object,config,packet);
    struct make_frame *f=(struct make_frame*)(packet-128); f->magic=0;
    const u8 *photo=*(const u8**)(config+0x82d0);
    struct context *c=config[0x82ac]==0 ? pool_photo(pool_current(),photo,1) : (void*)0;
    if(!c || c->state!=1 || c->owner!=(u32)photo || photo[0x77c]!=c->slot+10) return;
    f->context=c;
    copy(f->record,(const u8*)0x5501900cu,84);
    *(u32*)(f->record+4)=(u32)c->core;
    for(u32 i=0;i<12;i++) f->descriptor[i]=0;
    f->descriptor[0]=1;
    *(u32*)(f->descriptor+4)=(u32)f->record;
    *(u32*)(packet+8)=(u32)f->record; packet[0x9b]=1;
    f->magic=0x44534652u;
}
void *ds_t3_descriptor(void *gamma,u8 *packet) {
    (void)gamma;
    struct make_frame *f=bound_frame(packet);
    if(f) return f->descriptor;
    return ((void *(*)(void))0x536eed90u)();
}
void ds_t3_curves(u8 *descriptor,u32 *red,u32 *green,u32 *blue) {
    if(descriptor==(u8*)0x5536dab8u) {
        ((void (*)(void*,void*,void*,void*))0x536eedf0u)(descriptor,red,green,blue); return;
    }
    struct make_frame *f=(struct make_frame*)(descriptor-92);
    if(f->magic!=0x44534652u || !f->context || f->context->state!=1) {
        *red=*green=*blue=0; return;
    }
    *red=(u32)(f->context->core+18); *green=*red+512; *blue=*green+512;
    descriptor[0]=0;
}
void ds_make_post(u32 *matrix,u8 *packet,u32 fallback) {
    struct make_frame *f=bound_frame(packet);
    if(!f) { ((void (*)(void*,void*))fallback)(matrix,packet); return; }
    ((void (*)(void*,void*))0x536e4720u)(matrix,packet);
    ds_post(f->context,matrix);
}
void ds_numeric_controls(u8 *object,u8 *config) {
    ((void (*)(void*,void*))0x536db7d8u)(object,config);
    const u8 *photo=*(const u8**)(config+0x82d0);
    if(config[0x82ac] || !ds_is_archived(photo)) return;
    /* Match the already-validated film neutralization even when a later build
     * no longer replaces this slot. Never alter an ordinary HDR/Retro photo. */
    if(photo[0x77c]==20) {
        *(u16*)(object+0x1f0)=0; *(u16*)(object+0x1fa)=0;
        ((u8*)photo)[0x796]=0;
    } else if(photo[0x77c]==19) *(u16*)(object+0x1fc)=0;
}

/* JPEG carrier v1: APP15, DSRECIPE, version/index/count/padding (u8), then
 * little-endian total/offset/chunk size. Chunks are at most 60000 bytes. The
 * last payload ends in 0..31 zero bytes and FF D8. The latter are the stock
 * main-image SOI already skipped by the preceding APP7 length. We relocate
 * that boundary, retaining the main descriptor and its DMA alignment. */
static void put32(u8 *p,u32 v) { for(u32 i=0;i<4;i++) p[i]=(u8)(v>>(8*i)); }
u32 ds_jpeg_append(u8 *outer,const u8 *photo,const struct packet_ref *catalog) {
    if(!outer) return 0;
    const struct packet_ref *r=capture_ref(photo,catalog);
    if(!r) return 0;
    u32 base=get32(outer+0x18),capacity=get32(outer+0x1c),end=get32(outer+0x50);
    u32 app7=get32(outer+0x48),main=get32(outer+0x64),main_size=get32(outer+0x68);
    u32 chunks=r->size>60000 ? 2 : 1;
    u32 extra=2+28*chunks+r->size, pad=(0u-extra)&31u; extra+=pad;
    /* Complete admission before any write. Original bytes and descriptors
     * remain untouched when optional metadata cannot be represented. */
    if(!base || capacity>0x50000 || end>capacity || extra>capacity-end ||
       base>0xffffffffu-capacity || (end&31) || end<12 || app7<12 ||
       app7>end-4 || end-app7>65535 || !main || main_size<2 ||
       main>0xffffffffu-main_size || get32(outer+0x58)!=base ||
       get32(outer+0x5c)!=end || get32(outer+0x60)!=end || get32(outer+0x54)!=0) return 0;
    const u8 *image=(const u8*)main;u8 *buffer=(u8*)base;
    if(image[0]!=255 || image[1]!=216 || buffer[0]!=255 || buffer[1]!=216 ||
       buffer[app7]!=255 || buffer[app7+1]!=231 ||
       ((u32)buffer[app7+2]*256+buffer[app7+3])!=end-app7) return 0;
    u32 pos=end,offset=0;
    buffer[pos++]=255;buffer[pos++]=216;
    for(u32 i=0;i<chunks;i++) {
        u32 n=r->size-offset;if(n>60000)n=60000;
        u32 last=i+1==chunks, padding=last?pad:0;
        u32 length=2+24+n+(last?padding+2:0);
        u8 *p=buffer+pos;
        p[0]=255;p[1]=239;p[2]=(u8)(length>>8);p[3]=(u8)length;
        put32(p+4,0x45525344u);put32(p+8,0x45504943u); /* DSRECIPE */
        p[12]=1;p[13]=(u8)i;p[14]=(u8)chunks;p[15]=(u8)padding;
        put32(p+16,r->size);put32(p+20,offset);put32(p+24,n);
        copy(p+28,r->bytes+offset,n);
        for(u32 j=0;j<padding;j++)p[28+n+j]=0;
        pos+=28+n+padding;offset+=n;
        /* Final FF D8 belongs to the unchanged main descriptor, contiguous
         * in the output file. It is deliberately not copied past capacity. */
    }
    *(u32*)(outer+0x50)=pos;*(u32*)(outer+0x5c)=pos;*(u32*)(outer+0x60)=pos;
    return 1;
}
u32 ds_jpeg_capture(u8 *outer,const struct packet_ref *catalog) {
    u32 ok=((u32 (*)(void*))0x53603844u)(outer);
    if(ok) {
        void *source=*(void**)(outer+8);
        const u8 *photo=source?((const u8 *(*)(void*))0x535fc2f8u)(source):(void*)0;
        ds_jpeg_append(outer,photo,catalog);
    }
    return ok;
}
