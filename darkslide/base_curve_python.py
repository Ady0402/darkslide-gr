"""Candidate read-only App adapter; keep in the development package until reviewed.

No original arrays on disk, Unicorn import, firmware output or device operations.
The interpreter follows the previously declared synthetic initialization contract.
"""
import copy
import hashlib
import json
import threading
from pathlib import Path
from darkslide import fwread
from . import _base_curve_a32 as interpreter

MODEL_ID = 'gr3-210-python-standard-p64-zero-v1'
KEYS = ('key', 'contrast', 'highlight', 'shadow')
_CACHE = {}
_LOCK = threading.Lock()
_ROM_CACHE = {}
_ROM_LOCK = threading.Lock()


class BaseCurvePythonError(ValueError): pass

# Consumers can catch the same public error name as the existing backend.
BaseCurveError = BaseCurvePythonError


def _settings(value):
    if value is None: value = {}
    if type(value) is not dict or any(type(k) is not str or k not in KEYS for k in value):
        raise BaseCurvePythonError('only key/contrast/highlight/shadow settings')
    if any(type(v) is not int or not -4 <= v <= 4 for v in value.values()):
        raise BaseCurvePythonError('settings must be integers from -4 to 4')
    return {k:value.get(k, 0) for k in KEYS}


def _source_identity():
    paths = [Path(__file__), Path(interpreter.__file__), Path(fwread.__file__)]
    try:
        return tuple((str(p.resolve()), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths)
    except OSError as error:
        raise BaseCurvePythonError('backend source cannot be read') from error


def _original_sha(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise BaseCurvePythonError('official original cannot be rechecked') from error


_IMPORTED_SOURCE = _source_identity()


def _decode_rom(raw):
    decoded = fwread.unpack(raw)
    if len(decoded) != 59718388 or hashlib.sha256(decoded).hexdigest() != fwread.V210['payload_sha256']:
        raise BaseCurvePythonError('decoded original identity differs')
    return bytes(decoded[0x10870:0x10870+0x10b55c0])


def _rom(raw):
    sha = hashlib.sha256(raw).hexdigest()
    if len(raw) != 30391780 or sha != fwread.V210_INPUT_SHA256:
        raise BaseCurvePythonError('official identity required for ROM cache')
    key = (sha, _IMPORTED_SOURCE)
    with _ROM_LOCK:
        if key not in _ROM_CACHE:
            rom = _decode_rom(raw)
            if type(rom) is not bytes or len(rom) != 0x10b55c0:
                raise BaseCurvePythonError('invalid immutable ROM')
            if _source_identity() != _IMPORTED_SOURCE:
                raise BaseCurvePythonError('source changed during ROM decoding')
            _ROM_CACHE[key] = rom
        return _ROM_CACHE[key]


def _compute(raw, settings):
    # Only immutable ROM is shared; each call allocates fresh CPU/RAM/registers.
    cpu = interpreter.CPU(_rom(raw))
    output, frame = 0x60001000, 0x60002000
    words = [14272, settings['key'], settings['contrast'], -settings['shadow'], settings['highlight'], output, 0]
    for i, word in enumerate(words): cpu.write(frame+4*i, word)
    cpu.writes.clear()
    steps = cpu.run(0x536e7b64, [output, output, frame])
    if not all(output+i in cpu.writes for i in range(512)):
        raise BaseCurvePythonError('incomplete Base512 generation')
    values = [cpu.read(output+2*i, 2) for i in range(256)]
    if not all(type(v) is int and 0 <= v <= 16384 for v in values):
        raise BaseCurvePythonError('invalid generated values')
    return dict(schema=1, model='GR III', firmware='2.10', model_id=MODEL_ID,
        official_sha256=fwread.V210_INPUT_SHA256, payload_sha256=fwread.V210['payload_sha256'],
        values=values, values_sha256=hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).hexdigest(),
        output_normalization_divisor=16384, value_range=[0,16384],
        settings=dict(tone=11, stage=1, slider_values=dict(settings),
                      slider_encodings={k:v+4 for k,v in settings.items()}),
        backend=dict(kind='pure Python bounded A32 subset', sources=list(_IMPORTED_SOURCE)),
        method='original Standard first frame interpreted; declared integer division services',
        interpreted_steps=steps, declared_helpers={hex(k):v for k,v in cpu.declared_helpers.items()},
        assumptions=dict(synthetic_startup_RAM=True, P64=0, A14_low_byte=0,
            original_ROM_read_only=True, base_write_coverage=512,
            architecture_model='A32 ARMv7 PCStore=current_instruction_plus8',
            division_helper_flags_and_volatile_ABI_modelled=False,
            physical_pixel_model_verified=False, white_balance_runtime_state_measured=False),
        original_arm_instructions_interpreted=True, Unicorn_executed=False,
        physical_target_CPU_executed=False, native_effect_verified=False,
        full_modified_firmware_created=False)


def base_curve(official_bin_path, settings=None):
    """Compute this Standard model; numeric parity does not mean physical calibration."""
    settings = _settings(settings)
    if _source_identity() != _IMPORTED_SOURCE:
        raise BaseCurvePythonError('loaded source changed; restart before computing')
    try:
        path = Path(official_bin_path).resolve(); raw = path.read_bytes()
    except (OSError, TypeError) as error:
        raise BaseCurvePythonError('official original cannot be read') from error
    sha = hashlib.sha256(raw).hexdigest()
    if len(raw) != 30391780 or sha != fwread.V210_INPUT_SHA256:
        raise BaseCurvePythonError('official GR III 2.10 original required')
    key = (sha, tuple(settings.items()), MODEL_ID, _IMPORTED_SOURCE)
    with _LOCK:
        if key in _CACHE:
            if _original_sha(path) != sha or _source_identity() != _IMPORTED_SOURCE:
                raise BaseCurvePythonError('original or source changed before cached return')
            return copy.deepcopy(_CACHE[key])
    try:
        result = _compute(raw, settings)
    except (ValueError, RuntimeError) as error:
        raise BaseCurvePythonError('bounded original interpretation failed: '+str(error)) from error
    if _original_sha(path) != sha or _source_identity() != _IMPORTED_SOURCE:
        raise BaseCurvePythonError('original or source changed during computation')
    with _LOCK: _CACHE[key] = copy.deepcopy(result)
    return copy.deepcopy(result)
