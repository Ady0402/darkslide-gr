"""Compose reviewed edits on one official payload and pack exactly once."""
from . import edit_core as builder, a_shutdown

class CompositeError(ValueError):
    pass

def _merge_delta(before, merged, declared, ranges, changed, changes):
    """Validate each delta completely before merging any of its spans."""
    builder._require(type(changed) is bytes and len(changed) == len(before), 'delta size')
    builder._require(type(changes) is list, 'delta declarations')
    pending = []
    for item in changes:
        builder._require(type(item) is dict and 'offset' in item and 'length' in item,
                         'delta record')
        a, n = item['offset'], item['length']
        builder._require(type(a) is int and type(n) is int and n > 0, 'typed delta span')
        b = a + n
        builder._require(0 <= a < b <= len(before)-4, 'delta bounds/checksum ownership')
        builder._require(not any(a < y and b > x for x, y in ranges + pending),
                         'overlapping feature edits')
        pending.append((a, b))
    previous = 0
    for a, b in sorted(pending) + [(len(before), len(before))]:
        for at in range(previous, a, 65536):
            end = min(a, at + 65536)
            builder._require(changed[at:end] == before[at:end], 'undeclared delta bytes')
        previous = b
    for item, (a, b) in zip(changes, pending):
        merged[a:b] = changed[a:b]
        ranges.append((a, b))
        declared.append(dict(item))

def build_composite(official, edits, template, jpeg=None):
    try:
        builder._template(template)
        builder._require(type(edits) is list and len(edits) <= 7 and
                         (bool(edits) or jpeg is not None), 'no requested changes')
        if edits:
            builder._validate_edits(edits, template)
        builder._require(type(official) is bytes and len(official) == builder.INPUT_SIZE and
                         builder._sha(official) == builder.INPUT_SHA, 'fixed official input required')
        before, frames, stop, footer = builder._decode(official)
        builder._require(builder._sha(before) == builder.PAYLOAD_SHA, 'official payload identity')
        merged, declared, ranges = bytearray(before), [], []
        if edits:
            changed, changes = builder.apply_edits(before, edits, template)
            _merge_delta(before, merged, declared, ranges, changed, changes)
        shutdown = None
        if jpeg is not None:
            changed, shutdown = a_shutdown.apply_a_shutdown(before, jpeg)
            _merge_delta(before, merged, declared, ranges, changed, shutdown['edits'])
        builder._require(declared, 'no actual payload changes')
        result = builder._pack_payload(official, before, frames, stop, footer, bytes(merged), declared)
        result.update(features=sorted({e['kind'] for e in edits} | ({'shutdown'} if jpeg is not None else set())),
                      shutdown=shutdown, compositor='Darkslide one-payload compositor v01',
                      candidate_file_written=False, camera_verified=False, exportable=False,
                      device_installation_verified=False,
                      independent_entropy_decode_required=jpeg is not None)
        if shutdown is not None:
            result.update(shared_capacity=shutdown['capacity'],
                          request_ids=shutdown['request_ids'], shared_path=shutdown['shared_path'])
        return result
    except (builder.BuildError, a_shutdown.AShutdownError) as exc:
        raise CompositeError(str(exc)) from exc
