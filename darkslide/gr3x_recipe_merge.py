"""Merge current readonly knots and photo-owned full curves, offline only."""
import copy
from . import gr3x_inplace, gr3x_inplace_integrity, photo_recipe
from . import photo_recipe_extension
from .gr3x_inplace_support import fit_knots, expand_knots


def prepare(raw, requests, profiles, *, shutdown_hdf=False):
    plan = gr3x_inplace.plan_offline(raw, requests, profiles)
    selected = {r['slot']: r['film'] for r in requests}
    checked = gr3x_inplace_integrity.verify(raw, plan['windows'], selected, profiles,
                                          layout=gr3x_inplace.LAYOUT)
    if selected and (plan['code']['getter'] != 0x53dc3468 or plan['code']['post'] != 0x53dc3218):
        raise ValueError('curve code layout changed; merged binding must be reviewed')
    packets = {}
    for slot, ident in selected.items():
        original = profiles[ident]
        applied = copy.deepcopy(original)
        applied['curves_u14'] = [list(expand_knots(fit_knots(c)[0])) for c in original['curves_u14']]
        applied['curve_storage'] = dict(layout=gr3x_inplace.LAYOUT, points=33,
            snapshot='actual expanded 256 values', modified_by='LiorMoment',
            source_numeric_sha256=photo_recipe.decode(photo_recipe.encode(original,slot))['numeric_sha256'])
        packets[slot] = photo_recipe.encode(applied, slot)
    ext = photo_recipe_extension.build_fragments(raw, packets,
        selected_slots=tuple(sorted(selected)), inplace=True, shutdown_hdf=shutdown_hdf,
        post_fallback=0x53dc3218 if selected else 0x536e4720)
    occupied = {w.address+i for w in plan['windows'] for i in range(len(w.replacement))}
    overlap = {w.address for w in ext['windows'] if any(w.address+i in occupied for i in range(len(w.replacement)))}
    expected = ({0x536e4774,0x536e87c4} if selected else set()) | ({0x536dc27c,0x535131fc} if 10 in selected else set())
    if overlap != expected:
        raise ValueError('unreviewed curve/recipe overlap')
    return dict(curve=plan, extension=ext, packets=packets, curve_checks=checked,
                overlap=tuple(sorted(overlap)), layout='gr3x160_inplace_with_photo_recipe_v1')
