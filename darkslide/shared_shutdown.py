from . import jpeg_profile
"""Offline shared shutdown slot editor. No camera, container export, or disk writes.

All four known shutdown JPEG IDs resolve to the original Diary descriptor.
User JPEG is independently validated and padded to the original fixed capacity.
"""
import hashlib
import struct

PIN = '53da690797f35ad6dc2c429d8ca1d0de8e333c211ed959816813982cd093b703'
SIZE = 59718388
TABLE_LMA = 0x5407e0bc
DIARY_DESC = 0x53b5f508
TABLE_INDICES = (1, 9, 10, 11)
REQUEST_IDS = (2, 10, 11, 12)
EXPECTED_DESCRIPTORS = (0x53b5f520, 0x53b5f540, 0x53b5f550, 0x53b5f530,
                        0x53b5f518, 0x53b5f528, 0x53b5f568, 0x53b5f538,
                        0x53b5f560, 0x53b5f510, 0x53b5f558, DIARY_DESC)
PIXEL_OFFSET = 59298689
CAPACITY = 112509
DIARY_SHA = '0ad9a73876f58ef6d380a00e4f17f2584b83ec2a46c11a429a0d52002614e2ef'

class SharedSlotError(ValueError):
    pass

def need(value, message):
    if not value:
        raise SharedSlotError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def off(va, size=4):
    need(type(va) is int and type(size) is int and size > 0 and
         0x53000000 <= va and va + size <= 0x540b55c0, 'RTOS address out of bounds')
    return va - 0x53000000 + 0x10870

def jpeg_contract(data):
    try:
        return jpeg_profile.inspect(data)
    except jpeg_profile.ProfileError as exc:
        raise SharedSlotError(str(exc)) from exc

def pad_jpeg(jpeg, capacity=CAPACITY):
    need(type(capacity) is int and capacity == CAPACITY, 'Only the fixed image slot is supported')
    try:
        return jpeg_profile.fill_comments(jpeg, capacity)
    except jpeg_profile.ProfileError as exc:
        raise SharedSlotError(str(exc)) from exc

def apply_shared(decoded, jpeg=None):
    need(type(decoded) is bytes and len(decoded) == SIZE and sha(decoded) == PIN,
         'immutable official decoded GR III 2.10 required')
    t = off(TABLE_LMA, 48)
    need(struct.unpack_from('<12I', decoded, t) == EXPECTED_DESCRIPTORS, 'original JPEG index table')
    need(decoded[off(DIARY_DESC, 8):off(DIARY_DESC, 8) + 8] ==
         struct.pack('<HHI', 720, 480, 0x53b2298c), 'original Diary descriptor')
    need(sha(decoded[PIXEL_OFFSET:PIXEL_OFFSET + CAPACITY]) == DIARY_SHA and
         struct.unpack_from('<I', decoded, PIXEL_OFFSET - 4)[0] == CAPACITY,
         'original largest JPEG resource identity')
    updated = bytearray(decoded)
    edits = []
    for index in TABLE_INDICES:
        p = t + index * 4
        if EXPECTED_DESCRIPTORS[index] != DIARY_DESC:
            before = decoded[p:p + 4]
            value = struct.pack('<I', DIARY_DESC)
            updated[p:p + 4] = value
            edits.append(dict(what='jpeg_index_alias', table_index=index,
                              request_id=index + 1, offset=p, length=4,
                              before=before.hex(), after=value.hex()))
    if jpeg is not None:
        padded = pad_jpeg(jpeg)
        if padded != decoded[PIXEL_OFFSET:PIXEL_OFFSET + CAPACITY]:
            updated[PIXEL_OFFSET:PIXEL_OFFSET + CAPACITY] = padded
            edits.append(dict(what='fixed_diary_jpeg', offset=PIXEL_OFFSET, length=CAPACITY,
                              input_jpeg_sha256=sha(jpeg), padded_sha256=sha(padded)))
    need(len(updated) == len(decoded), 'payload expansion')
    return bytes(updated), dict(schema='gr3-shared-shutdown-offline-v1',
             input_sha256=PIN, output_payload_sha256=sha(updated), edits=edits,
             table_indices=list(TABLE_INDICES), request_ids=list(REQUEST_IDS),
             shared_descriptor=DIARY_DESC,
             shared_path='B:\\Resource\\Jpeg\\GB_Diary.jpg', capacity=CAPACITY,
             decoded_size_unchanged=True, resource_count_unchanged=True,
             custom_jpeg_applied=jpeg is not None, checksum_updated=False,
             independent_entropy_decode_required=True, loader_verified=False,
             exportable=False, camera_verified=False)
