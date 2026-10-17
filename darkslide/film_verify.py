"""Independent local film readback: no writer, planner, compiler or ARM execution.

Expected data and authorized physical spans derive from the original reader and
request. Modified code is accepted only after every instruction field is checked.
Passing these software checks never enables export or certifies camera effects.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import struct

ARENA, ARENA_END = 0x53D36400, 0x53D37400
FILL, POST = 0x536EF61C, 0x536EF6FC
LIB, RECORD_TABLE, STD, BOOT_TAIL = 0x55037604, 0x55018D94, 0x5501900C, 0x53DC27A4
SLOTS = {8: (18, (18,22,23)), 9: (19, (19,)), 10: (20, (20,24)), 11: (21, (21,))}
_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z", re.ASCII)

class FilmReadbackError(ValueError):
    pass


def _need(ok, message):
    if not ok:
        raise FilmReadbackError(message)


@dataclass(frozen=True)
class ExpectedWindow:
    address: int
    offset: int
    data: bytes
    label: str
    original: bytes


@dataclass(frozen=True)
class CodeRegion:
    address: int
    offset: int
    size: int
    role: str
    pointers: tuple
    original: bytes


@dataclass(frozen=True)
class ProtectedRegion:
    address: int
    size: int
    label: str
    original: bytes


@dataclass(frozen=True)
class FilmExpectations:
    data_windows: tuple
    code_regions: tuple
    expected_spans: tuple
    protected_regions: tuple
    selected_slots: tuple
    arena_used: int


@dataclass(frozen=True)
class FilmReadbackResult:
    passed: bool
    checks: tuple
    expected_windows: tuple
    expected_spans: tuple


def va_to_offset(address, size=1):
    _need(type(address) is int and type(size) is int and 0 < size and 0 <= address < address+size <= 2**32, 'bounded address')
    end = address + size
    if 0x55000000 <= address and end <= 0x5503A080:
        return 0x10870 + 0x107B540 + address - 0x55000000
    _need(0x53000000 <= address and end <= 0x540B55C0, 'original mapped interval')
    return 0x10870 + address - 0x53000000


def _read(reader, address, size):
    _need(callable(reader), 'read callback required')
    va_to_offset(address, size)
    parts = []
    for start in range(0, size, 512):
        n = min(512, size-start)
        part = reader(address+start, n)
        _need(type(part) is bytes and len(part) == n, 'strict complete source read')
        parts.append(part)
    return b''.join(parts)


def _word(raw):
    _need(type(raw) is bytes and len(raw) == 4, 'word bytes')
    return int.from_bytes(raw, 'little')


def _edits(edits):
    _need(type(edits) is list and len(edits) <= 4, 'film edit list')
    seen, clean = set(), []
    for e in edits:
        _need(type(e) is dict and set(e) == {'kind','slot','film'} and e['kind'] == 'film', 'film edit shape')
        slot, ident = e['slot'], e['film']
        _need(type(slot) is int and slot in SLOTS and slot not in seen, 'unique supported film slot')
        _need(type(ident) is str and _ID.fullmatch(ident), 'camera profile id')
        seen.add(slot); clean.append((slot, ident))
    return tuple(sorted(clean))


def _profile(profile, ident):
    _need(type(profile) is dict and type(profile.get('schema')) is int and profile['schema'] == 1 and profile.get('id') == ident, 'profile schema/id')
    _need(profile.get('model') == 'GR III' and profile.get('firmware') == '2.10', 'profile model/version')
    def matrix(value, total):
        _need(type(value) is list and len(value) == 3, 'three matrix rows')
        rows = []
        for row in value:
            _need(type(row) is list and len(row) == 3 and all(type(v) is int and -32768 <= v <= 32767 for v in row) and sum(row) == total, 'signed white-preserving matrix')
            rows.append(tuple(row))
        return tuple(rows)
    look = matrix(profile.get('look_matrix_q13'), 8192)
    post = matrix(profile.get('post_matrix_q512'), 512)
    _need(all(sum(abs(post[row][column]) for row in range(3)) <= 8191 for column in range(3)), 'post column absolute sum exceeds signed32-safe bound')
    curves = profile.get('curves_u14')
    _need(type(curves) is list and len(curves) == 3, 'three complete film curves')
    out = []
    for row in curves:
        _need(type(row) is list and len(row) == 256 and all(type(v) is int and 0 <= v <= 16383 for v in row), 'strict 256 u14 curve')
        out.append(tuple(row))
    return look, tuple(out), post


def load_profiles(film_edits, root=None):
    edits = _edits(film_edits)
    folder = Path(root) if root is not None else Path(__file__).resolve().parent.parent/'film_curves'/'camera'
    folder = folder.resolve()
    def unique(pairs):
        keys = [k for k,v in pairs]
        _need(len(keys) == len(set(keys)), 'duplicate profile JSON key')
        return dict(pairs)
    def reject(value):
        raise FilmReadbackError('nonfinite profile JSON')
    def finite_float(value):
        number = float(value)
        _need(math.isfinite(number), 'nonfinite profile JSON number')
        return number
    result = {}
    for slot, ident in edits:
        if ident in result:
            continue
        path = folder/(ident+'.json')
        _need(path.resolve().parent == folder, 'profile directory boundary')
        try:
            raw = path.read_text(encoding='utf-8')
            data = json.loads(raw, object_pairs_hook=unique, parse_constant=reject, parse_float=finite_float)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FilmReadbackError('camera profile unavailable or invalid') from exc
        _profile(data, ident)
        result[ident] = data
    return result


def resolve_profiles(film_edits, supplied=None):
    """Snapshot already-fitted Cloud data; never read a LUT or run a fitter.

    Only selected user_lut_ IDs can come from the caller. Bundled profiles are
    loaded independently. The returned schema dictionary contains fresh numeric
    lists, excluding extension metadata that cannot affect firmware readback.
    """
    edits = _edits(film_edits)
    if supplied is None:
        supplied = {}
    _need(type(supplied) is dict, 'supplied profile mapping')
    requested = {ident for slot, ident in edits}
    _need(all(type(key) is str and key in requested and key.startswith('user_lut_')
              for key in supplied), 'supplied profile cannot override bundled or unselected ID')
    builtin_edits = [dict(kind='film', slot=slot, film=ident)
                     for slot, ident in edits if not ident.startswith('user_lut_')]
    bundled = load_profiles(builtin_edits) if builtin_edits else {}
    result = {}
    for slot, ident in edits:
        if ident in result:
            continue
        if ident.startswith('user_lut_'):
            _need(ident in supplied, 'selected custom profile missing')
            value = supplied[ident]
        else:
            value = bundled[ident]
        look, curves, post = _profile(value, ident)
        result[ident] = dict(schema=1, id=ident, model='GR III', firmware='2.10',
                            look_matrix_q13=[list(row) for row in look],
                            curves_u14=[list(row) for row in curves],
                            post_matrix_q512=[list(row) for row in post])
    return result


def _branch_word(at, target, condition=14, link=False):
    delta = target-at-8
    _need(type(at) is int and type(target) is int and at%4 == target%4 == 0 and -(2**25) <= delta < 2**25, 'branch range/alignment')
    return condition*2**28 + (11 if link else 10)*2**24 + ((delta//4) % 2**24)


def _branch(word, at, target, condition=14, link=False):
    _need(word == _branch_word(at,target,condition,link), 'code branch/control target')


def _imm(word):
    n, rotate = word & 255, ((word >> 8) & 15)*2
    return ((n >> rotate) | (n << (32-rotate))) & 0xffffffff if rotate else n


def _dp(w, op, rn, rd, value, *, immediate=True, condition=14, flags=False):
    fields = (w>>28,(w>>26)&3,(w>>25)&1,(w>>21)&15,(w>>20)&1,(w>>16)&15,(w>>12)&15)
    _need(fields == (condition,0,int(immediate),op,int(flags),rn,rd), 'data-processing operands')
    _need((_imm(w) if immediate else w & 0xfff) == value, 'data-processing value/shift')


def _mov16(w, register, value, high=False):
    _need(w & 0xfff0f000 == (0xe3400000 if high else 0xe3000000) | register*4096, 'MOVW/MOVT fixed fields')
    _need(((w>>4)&0xf000)|(w&0xfff) == (value>>16 if high else value&65535), 'code pointer halfword')


def _memory(w, rn, rd, value, *, load=True, immediate=True, pre=True, byte=False):
    fields = (w>>28,(w>>26)&3,(w>>25)&1,(w>>24)&1,(w>>23)&1,(w>>22)&1,(w>>21)&1,(w>>20)&1,(w>>16)&15,(w>>12)&15,w&0xfff)
    _need(fields == (14,1,int(not immediate),int(pre),1,int(byte),0,int(load),rn,rd,value), 'memory transfer operands')


def _signed_halfword(w, rn, rd, rm):
    _need((w>>28,(w>>25)&7,(w>>24)&1,(w>>23)&1,(w>>22)&1,(w>>21)&1,(w>>20)&1,(w>>16)&15,(w>>12)&15,(w>>8)&15,(w>>4)&15,w&15) == (14,0,1,1,0,0,1,rn,rd,0,15,rm), 'signed halfword load')


def _multiply(w, rd, rm, rs, accumulate=None):
    _need((w>>28,(w>>22)&63,(w>>21)&1,(w>>20)&1,(w>>16)&15,(w>>12)&15,(w>>8)&15,(w>>4)&15,w&15) == (14,0,int(accumulate is not None),0,rd,0 if accumulate is None else accumulate,rs,9,rm), 'multiply/accumulate fields')


def _code_words(raw, length):
    _need(type(raw) is bytes and len(raw) == length, 'exact code region')
    return tuple(int.from_bytes(raw[i:i+4],'little') for i in range(0,length,4))


def _check_fill(raw, address, pointers):
    stock, modes, ret = pointers
    w = _code_words(raw,112)
    # STMDB/LDMIA use only r7, update SP, and leave CPSR untouched. Both
    # control exits must restore the temporary word before handing off.
    _need(w[0] == 0xe92d0080, 'fill temporary incoming r7 save')
    _mov16(w[1],0,LIB+36); _mov16(w[2],0,LIB+36,True)
    _mov16(w[3],2,stock); _mov16(w[4],2,stock,True)
    _need(w[5] == 0xe89200b0 and w[6] == 0xe88000b0, 'stock pointer restore block registers')
    _mov16(w[7],2,modes); _mov16(w[8],2,modes,True)
    _memory(w[9],2,4,0); _dp(w[10],10,4,0,0,flags=True)
    _branch(w[11],address+44,address+96,0)
    _dp(w[12],10,4,0,1,immediate=False,flags=True)
    _dp(w[13],4,2,4,4,condition=0)
    _branch(w[14],address+56,address+68,0)
    _dp(w[15],4,2,2,16); _branch(w[16],address+64,address+36)
    _need(w[17] == 0xe8940320 and w[18] == 0xe8800320, 'selected pointer block registers')
    _dp(w[19],4,3,3,0x38000); _dp(w[20],13,0,2,4)
    _memory(w[21],3,2,0xa98,load=False,byte=True)
    _need(w[22] == 0xe8bd0080, 'selected temporary r7 and SP restore')
    _need(w[23] == ret, 'fill saved epilogue')
    _need(w[24] == 0xe8bd0080, 'unselected temporary r7 and SP restore')
    _dp(w[25],10,1,0,21,flags=True)
    _branch(w[26],address+104,0x536DD4B8,0)
    _branch(w[27],address+108,0x536DD458)


def _check_post(raw, address, pointers):
    table, = pointers
    w = _code_words(raw,204)
    _need(w[0] == 0xe92d41f3 and w[50] == 0xe8bd81f3, 'post stack register contract')
    _branch(w[1],address+4,0x536E4720,link=True)
    _memory(w[2],13,0,0); _memory(w[3],13,1,4); _memory(w[4],1,3,8)
    _mov16(w[5],4,table); _mov16(w[6],4,table,True)
    _memory(w[7],4,12,0); _dp(w[8],10,12,0,0,flags=True)
    _branch(w[9],address+36,address+200,0)
    _dp(w[10],10,12,0,3,immediate=False,flags=True)
    _dp(w[11],4,4,4,24,condition=1); _branch(w[12],address+48,address+28,1)
    _dp(w[13],4,4,4,4); _dp(w[14],2,13,13,36); _dp(w[15],13,0,12,0)
    _memory(w[16],0,14,12,immediate=False)
    _dp(w[17],13,0,14,(13<<7)|14,immediate=False)
    _dp(w[18],13,0,14,(13<<7)|(2<<5)|14,immediate=False)
    _memory(w[19],13,14,12,load=False,immediate=False)
    _dp(w[20],4,12,12,4); _dp(w[21],10,12,0,36,flags=True)
    _branch(w[22],address+88,address+64,1)
    _dp(w[23],13,0,5,0); _dp(w[24],13,0,6,0)
    _memory(w[25],13,7,5,immediate=False); _signed_halfword(w[26],4,8,6)
    _multiply(w[27],14,7,8)
    _dp(w[28],4,5,2,4); _memory(w[29],13,7,2,immediate=False)
    _dp(w[30],4,6,2,6); _signed_halfword(w[31],4,8,2); _multiply(w[32],14,7,8,14)
    _dp(w[33],4,5,2,8); _memory(w[34],13,7,2,immediate=False)
    _dp(w[35],4,6,2,12); _signed_halfword(w[36],4,8,2); _multiply(w[37],14,7,8,14)
    _dp(w[38],4,14,14,256)
    _dp(w[39],13,0,14,(9<<7)|(2<<5)|14,immediate=False)
    _dp(w[40],13,0,14,(13<<7)|14,immediate=False)
    _dp(w[41],13,0,14,(13<<7)|(1<<5)|14,immediate=False)
    _memory(w[42],0,14,4,load=False,pre=False)
    _dp(w[43],4,6,6,2); _dp(w[44],10,6,0,6,flags=True)
    _branch(w[45],address+180,address+100,1)
    _dp(w[46],4,5,5,12); _dp(w[47],10,5,0,36,flags=True)
    _branch(w[48],address+192,address+96,1); _dp(w[49],4,13,13,36)


def _pack_u32(value):
    _need(type(value) is int and 0 <= value < 2**32, 'pointer u32')
    return value.to_bytes(4,'little')


def _pack_s16(rows):
    return b''.join((v%65536).to_bytes(2,'little') for row in rows for v in row)


class _Builder:
    def __init__(self, read):
        self.read, self.windows, self.codes, self.cursor = read, [], [], ARENA
    def allocate(self, length):
        address = self.cursor
        self.cursor = (address+length+3)//4*4
        _need(self.cursor <= ARENA_END, 'private arena capacity')
        return address
    def data(self, address, data, label):
        _need(type(data) is bytes and data, 'immutable expected bytes')
        original = _read(self.read,address,len(data))
        if ARENA <= address < ARENA_END:
            _need(address+len(data) <= ARENA_END and not any(original), 'original private bytes must be zero')
        self.windows.append(ExpectedWindow(address,va_to_offset(address,len(data)),data,label,original))
    def guarded(self,address,expected,replacement,label):
        _need(_word(_read(self.read,address,4)) == expected, 'original instruction guard')
        self.data(address,_pack_u32(replacement),label)
    def code(self,address,size,role,pointers):
        self.codes.append(CodeRegion(address,va_to_offset(address,size),size,role,tuple(pointers),_read(self.read,address,size)))


def derive_expected(original_read, film_edits, profiles_by_id):
    edits = _edits(film_edits)
    _need(type(profiles_by_id) is dict, 'profile catalog object')
    if not edits:
        return FilmExpectations((),(),(),(),(),0)
    selected = {slot for slot, ident in edits}
    _need(all(ident in profiles_by_id for slot,ident in edits), 'camera profile missing')
    boot_guards = ((0x536EB0DC,0xe302c7a4),(0x536EB0E0,0xe345c3dc),(0x536EB160,0xe89c000f),(0x536EB164,0xe59f6098),(0x536EB168,0xe59f5098),(0x536EB16C,0xe59f4098),(0x536EB170,0xe59fe098),(0x536EB174,0xe59f7098),(0x536EB178,0xe887000f),(0x536EB214,0x55019050))
    for address,word in boot_guards:
        _need(_word(_read(original_read,address,4)) == word, 'original startup-tail reader guard')
    data = {slot:_profile(profiles_by_id[ident],ident) for slot,ident in edits}
    pointers = tuple(_word(_read(original_read,LIB+4*i,4)) for i in range(12))
    _need(all(0x53EF0000 <= p and p+512 <= 0x53F00000 and p%2 == 0 for p in pointers), 'original full-curve pointer bounds')
    _need(all(abs(p-q) >= 512 for i,p in enumerate(pointers) for q in pointers[i+1:]), 'original 512-byte curve regions overlap')
    standard = _read(original_read,STD,84)
    tail = _read(original_read,BOOT_TAIL,16)
    ret = _word(_read(original_read,0x536DD464,4))
    _need(ret == 0xe89daff8, 'original fill return')
    b = _Builder(original_read); records = {}; curve_addresses = {}
    for slot, ident in edits:
        look, curves, post = data[slot]
        record = b.allocate(84); matrix = b.allocate(18)
        clone = standard[:4]+_pack_u32(matrix)+standard[8:68]+tail
        b.data(record,clone,'private_record_'+str(slot)); b.data(matrix,_pack_s16(look),'look_matrix_'+str(slot))
        records[slot] = record
        if slot in (8,9):
            addresses = []
            for channel, curve in enumerate(curves):
                address = b.allocate(512); addresses.append(address)
                b.data(address,b''.join(v.to_bytes(2,'little') for v in curve),'private_curve_'+str(slot)+'_'+str(channel))
        else:
            first = 0 if slot == 10 else 3
            addresses = list(pointers[first:first+3])
            for channel,curve in enumerate(curves):
                b.data(addresses[channel],b''.join(v.to_bytes(2,'little') for v in curve),'library_curve_'+str(slot)+'_'+str(channel))
        curve_addresses[slot] = tuple(addresses)
        for index in SLOTS[slot][1]:
            b.data(RECORD_TABLE+4*index,_pack_u32(record),'record_binding_'+str(index))
    stock = b.allocate(12); b.data(stock,b''.join(_pack_u32(p) for p in pointers[9:12]),'stock_pointers')
    mode = b.allocate(16*(len(edits)+1))
    rows = b''.join(_pack_u32(SLOTS[slot][0])+b''.join(_pack_u32(p) for p in curve_addresses[slot]) for slot,ident in edits)+bytes(16)
    b.data(mode,rows,'selected_mode_table')
    post_table = b.allocate(24*(len(edits)+1))
    rows = b''.join(_pack_u32(records[slot])+_pack_s16(data[slot][2])+bytes(2) for slot,ident in edits)
    rows += bytes(4)+_pack_s16(((512,0,0),(0,512,0),(0,0,512)))+bytes(2)
    b.data(post_table,rows,'post_table')
    b.code(FILL,112,'fill',(stock,mode,ret)); b.code(POST,204,'post',(post_table,))
    b.guarded(0x536EF618,0xeddf0be0,_branch_word(0x536EF618,0x536EF6DC),'skip_original_area')
    b.guarded(0x536DD450,0x159632d0,0xe59632d0,'fill_source_register')
    b.guarded(0x536DD454,_branch_word(0x536DD454,0x536DD4B8,0),_branch_word(0x536DD454,FILL),'fill_hook')
    b.guarded(0x536E4774,_branch_word(0x536E4774,0x536E4720,link=True),_branch_word(0x536E4774,POST,link=True),'post_hook')
    effects = ((10,0x536DBEB4,0xe5d39788,0xe3a09000),(10,0x536DC27C,_branch_word(0x536DC27C,0x536DC818,0),0xe1a00000),(10,0x536DBEBC,0xe5d32796,0xe3a02000),(10,0x535131FC,_branch_word(0x535131FC,0x53513274,0),_branch_word(0x535131FC,0x53513218,0)),(9,0x536DBE98,0xe1ce40b0,0xe1ce10b0))
    protected = [ProtectedRegion(RECORD_TABLE,104,'complete_record_binding_table',_read(original_read,RECORD_TABLE,104)),ProtectedRegion(FILL+112,80,'unused_fill_area',_read(original_read,FILL+112,80)),ProtectedRegion(POST+204,464,'unused_post_area',_read(original_read,POST+204,464)),ProtectedRegion(0x536DD4B8,88,'original_cross_chain',_read(original_read,0x536DD4B8,88)),ProtectedRegion(STD,84,'original_standard_record',standard),ProtectedRegion(BOOT_TAIL,16,'original_boot_tail',tail)]
    for slot,address,old,new in effects:
        if slot in selected:b.guarded(address,old,new,'selected_effect_'+hex(address))
        else:protected.append(ProtectedRegion(address,4,'unselected_effect',_read(original_read,address,4)))
    for index in (2,11,18,19,20,21,22,23,24):
        cell = _read(original_read,RECORD_TABLE+4*index,4)
        if not any(index in SLOTS[slot][1] for slot in selected):protected.append(ProtectedRegion(RECORD_TABLE+4*index,4,'unselected_record_binding',cell))
        address = _word(cell)
        original = _read(original_read,address,84)
        protected.append(ProtectedRegion(address,84,'original_record',original))
        matrix = _word(original[4:8])
        protected.append(ProtectedRegion(matrix,18,'original_matrix',_read(original_read,matrix,18)))
    for i in range(12):
        if (i < 3 and 10 in selected) or (3 <= i < 6 and 11 in selected):continue
        protected.append(ProtectedRegion(pointers[i],512,'unselected_library_curve',_read(original_read,pointers[i],512)))
    protected.append(ProtectedRegion(LIB,48,'original_library_pointers',b''.join(_pack_u32(p) for p in pointers)))
    original_arena = _read(original_read,ARENA,4096)
    _need(not any(original_arena), 'whole candidate arena original zero guard')
    protected.append(ProtectedRegion(ARENA,4096,'arena_undeclared_bytes',original_arena))
    spans = [(w.offset,w.offset+len(w.data)) for w in b.windows]+[(c.offset,c.offset+c.size) for c in b.codes]
    spans.sort()
    _need(all(spans[i][1] <= spans[i+1][0] for i in range(len(spans)-1)), 'independent expected physical overlap')
    return FilmExpectations(tuple(b.windows),tuple(b.codes),tuple(spans),tuple(protected),tuple(sorted(selected)),b.cursor-ARENA)


def readback_windows(original_read, modified_read, expectations):
    checks = []
    def add(name,ok,detail=''):
        checks.append(dict(id=name,ok=bool(ok),detail=detail))
    try:
        _need(type(expectations) is FilmExpectations, 'independent expected contract')
        accepted = list(expectations.data_windows)
        for w in expectations.data_windows:
            _need(_read(original_read,w.address,len(w.data)) == w.original, 'original changed since derivation')
            _need(_read(modified_read,w.address,len(w.data)) == w.data, 'film data mismatch: '+w.label)
        add('film_requested_data',True)
        for code in expectations.code_regions:
            _need(_read(original_read,code.address,code.size) == code.original, 'original code source changed')
            actual = _read(modified_read,code.address,code.size)
            if code.role == 'fill':_check_fill(actual,code.address,code.pointers)
            elif code.role == 'post':_check_post(actual,code.address,code.pointers)
            else:raise FilmReadbackError('unknown code constraint')
            accepted.append(ExpectedWindow(code.address,code.offset,actual,'validated_'+code.role,code.original))
        add('film_code_fields_and_targets',True)
        for region in expectations.protected_regions:
            _need(_read(original_read,region.address,region.size) == region.original, 'protected source changed')
            want = bytearray(region.original)
            for w in accepted:
                lo,maxend = max(region.address,w.address), min(region.address+region.size,w.address+len(w.data))
                if lo < maxend:want[lo-region.address:maxend-region.address] = w.data[lo-w.address:maxend-w.address]
            _need(_read(modified_read,region.address,region.size) == bytes(want), 'protected film region mismatch: '+region.label)
        add('film_unselected_and_original_protected',True)
        return FilmReadbackResult(True,tuple(checks),tuple(accepted),expectations.expected_spans)
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,struct.error) as exc:
        add('film_closed_failure',False,str(exc))
        return FilmReadbackResult(False,tuple(checks),(),())
