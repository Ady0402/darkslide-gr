"""Numeric boundaries for experimental film fitting; no firmware output.

A supplied base table is only range-checked. Acceptance here does not establish
its camera provenance, input domain, calibration, or equivalence to internal q.
"""
import math


class FilmNumericError(ValueError):
    pass


def _need(condition, message):
    if not condition:
        raise FilmNumericError(message)


def _table(value, maximum, label):
    _need(type(value) is list and len(value) == 256, label + ': expected 256 entries')
    _need(all(type(v) is int and 0 <= v <= maximum for v in value),
          label + ': invalid integer or range')
    return tuple(value)


def validate_base_q(value):
    """Validate an explicitly supplied candidate internal table; never infer q.

The base generator can reach 0x4000. This is NOT the limit for film tables.
Neither monotonicity nor a particular gamma law is assumed.
"""
    return _table(value, 16384, 'base q')


def validate_film_curves(value):
    """R, G, B, each 256 u16 samples limited to the verified safe 14-bit domain.

Out-of-range data is rejected, never silently clipped or wrapped.
"""
    _need(type(value) is list and len(value) == 3, 'expected R/G/B tables')
    return tuple(_table(row, 16383, 'film curve') for row in value)


def validate_matrix_q13(value):
    _need(type(value) is list and len(value) == 3, 'expected matrix rows')
    for row in value:
        _need(type(row) is list and len(row) == 3, 'expected three coefficients')
        _need(all(type(v) is int and -32768 <= v <= 32767 for v in row),
              'matrix coefficient outside signed 16-bit domain')
        _need(sum(row) == 8192, 'matrix row must sum to 8192')
    return tuple(tuple(row) for row in value)


def quantize_matrix_q13(value):
    """Round ties away from zero, then repair each row at its diagonal.

Input must already preserve white; only rounding error may be repaired.
The row-sum tolerance (1e-12) admits float arithmetic noise, not normalization.
"""
    _need(type(value) is list and len(value) == 3, 'expected matrix rows')
    result = []
    for i, row in enumerate(value):
        _need(type(row) is list and len(row) == 3, 'expected three coefficients')
        _need(all(type(v) in (int, float) and -4 <= v < 4 for v in row),
              'matrix requires finite representable coefficients')
        _need(abs(math.fsum(row) - 1.0) <= 1e-12, 'input matrix must preserve white')
        scaled = [v * 8192 for v in row]
        quantized = [math.floor(v + 0.5) if v >= 0 else math.ceil(v - 0.5)
                     for v in scaled]
        quantized[i] += 8192 - sum(quantized)
        result.append(quantized)
    return validate_matrix_q13(result)


def quantize_srgb_output(value):
    """One already-composed u14 value -> hardware u10 in the sRGB path.

This is the >>4 stage only, not interpolation, RGB-to-JPEG rendering, or an
AdobeRGB model. Perceptual fitting must evaluate these quantized outputs.
"""
    _need(type(value) is int and 0 <= value <= 16383, 'expected composed u14 value')
    return min(1023, value >> 4)
