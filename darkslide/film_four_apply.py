"""Four-film layout (four_curve_v1) for the one-payload compositor.

The four presets that can take a film (slots 8/9/10/11) are rewritten together:
every build carries the current film of all four, so changing one keeps the
other three. The plan itself comes from film_four_validation; this module only
turns its windows into payload offsets, the same shape film_writer.apply returns.
"""
import copy

from . import film_four_validation as four
from .film_requests import FilmRequestError, available, validate_batch
from .film_gate import require_inside
from .film_writer import resolve_profiles

LAYOUT = "four_curve_v1"


def apply(raw, edits, *, profiles=None):
    requests = validate_batch(edits)
    if not requests:
        return raw, []
    if not available():
        raise FilmRequestError("胶片写入尚未开启")
    if tuple(e["slot"] for e in requests) != four.SLOTS:
        raise FilmRequestError("胶片写入需要银流冲洗、怀旧、HDR 色调、交叉冲洗四个位置都选好胶片（可以选同一卷）")
    # one defensive snapshot: the profiles that pass the factory-range gate are the ones planned
    resolved = copy.deepcopy(resolve_profiles(list(requests), profiles))
    require_inside(raw, resolved)
    try:
        plan = four.plan_official_payload(bytes(raw), list(requests), resolved)
    except (ValueError, OSError) as error:
        raise FilmRequestError("胶片写入计划未通过原件核对：" + str(error)) from error
    from .fwread import Payload
    p = Payload(raw)
    pending, spans = [], []
    for window in plan["windows"]:
        a = p.off(window.address)
        b = a + len(window.replacement)
        if p.off(window.address + len(window.replacement) - 1) != b - 1 or b > len(raw) - 4:
            raise FilmRequestError("胶片写入越界")
        if any(a < hi and b > lo for lo, hi in spans):
            raise FilmRequestError("胶片写入地址别名冲突")
        if raw[a:b] != window.expected:
            raise FilmRequestError("胶片原字变化")
        spans.append((a, b))
        pending.append((a, b, window.replacement))
    changed = bytearray(raw)
    for a, b, value in pending:
        changed[a:b] = value
    return bytes(changed), [{"offset": a, "length": b - a, "kind": "film"} for a, b, _ in pending]
