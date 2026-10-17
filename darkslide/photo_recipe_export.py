"""Attributed desktop recipe bundle; no firmware generation."""
import io,json,zipfile
from . import film_luts, photo_recipe
from .store import Store

def export_bundle(packet, cube, grade):
    """A derived preview travels with the exact source and full attribution.

    The preview is supplied by the local UI; it is not certified pixel output.
    All ZIP member names are fixed or sanitised, never archive-provided paths.
    """
    if not isinstance(cube, str) or len(cube.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('预览 LUT 过大或格式错误')
    film_luts.parse_cube(cube.encode('utf-8'))
    grade = Store._clean_grade('调色', {} if grade is None else grade)
    profile = photo_recipe.restored_profile(packet)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('film_data/preview.cube', cube)
        z.writestr('film_data/restored-profile.dsfr', packet)
        z.writestr('film_data/profile.json', json.dumps(profile, ensure_ascii=False, indent=2))
        notices = profile.get('data_notices', {})
        if isinstance(notices, dict):
            for i, (name, contents) in enumerate(notices.items()):
                safe = name if isinstance(name, str) and name in (
                    'README.md', 'SPEKTRAFILM_LICENSE.txt', 'CHANGELOG.txt') else 'notice-%d.txt' % i
                z.writestr('film_data/source-notices/' + safe,
                           contents if isinstance(contents, str) else json.dumps(contents, ensure_ascii=False))
        z.writestr('film_data/CHANGELOG.txt',
            'Derived camera-model preview; modified by LiorMoment / Darkslide.\n'
            'Original provenance and license are retained in profile.json and source-notices/.\n'
            'Preview is approximate; no RAW pixels developed or camera tested.\n'
            'Adjustments: ' + json.dumps(grade, ensure_ascii=False, sort_keys=True) + '\n')
    return out.getvalue()
