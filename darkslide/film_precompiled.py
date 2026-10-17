"""Checked ARM fragments for the released film planners; no compiler fallback.

The bundle contains only code assembled from distributed source, never firmware
arrays. SHA pinning detects accidental/stale resources, not hostile modification
of an application whose Python code can also be replaced.
"""
import hashlib
import json
from pathlib import Path
from .film_precompiled_pin import BUNDLE_SHA256

BUNDLE = Path(__file__).with_name('data') / 'film_arm_v1.json'
FAMILIES = ('GRIII-2.10-v29', 'GRIIIx-1.60-v29')


def source_key(source, base):
    if type(source) is not str or type(base) is not int or not 0 <= base < 2**32 or base % 4:
        raise ValueError('typed aligned A32 source/base required')
    return '%08x:%s' % (base, hashlib.sha256(source.encode('utf-8')).hexdigest())


def assemble_bundled(source, base, family):
    key = source_key(source, base)
    if family not in FAMILIES:
        raise ValueError('unsupported precompiled ARM family')
    # Read afresh: resource replacement/corruption must not hide behind a cache.
    try:
        raw = BUNDLE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != BUNDLE_SHA256:
            raise ValueError('precompiled ARM bundle fingerprint mismatch')
        bundle = json.loads(raw)
        if bundle['schema'] != 1:
            raise ValueError('unsupported precompiled ARM schema')
        row = bundle['families'][family]['entries'][key]
        blob = bytes.fromhex(row['hex'])
        if (not blob or len(blob) % 4 or len(blob) != row['size'] or
                hashlib.sha256(blob).hexdigest() != row['sha256']):
            raise ValueError('precompiled ARM fragment integrity mismatch')
        return blob
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('预编译胶片组件缺失或与源码不匹配，请使用完整匹配的程序包') from exc
