"""One factory-range gate in front of every film write (both layouts).

The range is read from the same official payload the write is planned on, not
from a cache entry, a stored report or what the page last showed. Each bound it
needs must be a plain integer in a sensible order; a missing or odd bound, or any
profile outside the range, stops the write. An empty result never counts as a pass.
"""
from . import factory_envelope, film_fit
from .film_requests import FilmRequestError

FIELDS = ("look_min", "look_max", "look_row_abs_max", "post_min", "post_max",
          "post_col_abs_max", "curve_step_max", "curve_step_min",
          "curve_first_min", "curve_first_max", "curve_last_min", "curve_last_max")


def checked_envelope(payload):
    try:
        env = factory_envelope.factory_envelope_from_payload(payload)
    except factory_envelope.FactoryEnvelopeError as error:
        raise FilmRequestError("读不出原厂范围，不能写入胶片：" + str(error)) from error
    if type(env) is not dict or env.get("model_id") != factory_envelope.MODEL_ID:
        raise FilmRequestError("原厂范围的格式不对，不能写入胶片")
    for name in FIELDS:
        if type(env.get(name)) is not int:
            raise FilmRequestError("原厂范围缺少 %s，不能写入胶片" % name)
    if not (env["look_min"] < env["look_max"] and env["post_min"] < env["post_max"]
            and env["curve_step_min"] < env["curve_step_max"]
            and env["curve_first_min"] <= env["curve_first_max"] < env["curve_last_min"] <= env["curve_last_max"]
            and env["look_row_abs_max"] > 0 and env["post_col_abs_max"] > 0):
        raise FilmRequestError("原厂范围的数值顺序不对，不能写入胶片")
    return env


def require_inside(payload, profiles):
    """profiles: film id -> camera profile (already shape-checked). Returns the envelope used."""
    env = checked_envelope(payload)
    if type(profiles) is not dict or not profiles:
        raise FilmRequestError("没有要检查的胶片参数，不能写入")
    for ident, profile in profiles.items():
        try:
            left = film_fit.envelope_violations(profile, env)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise FilmRequestError("胶片「%s」的参数不完整，不能写入" % ident) from error
        if left:
            raise FilmRequestError("胶片「%s」超出了理光相机原厂的范围，不能写进相机（%s）" % (ident, left[0]))
    return env
