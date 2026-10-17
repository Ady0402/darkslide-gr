"""Archive the actual merged-output packets; independent of the build planner."""
import base64
from . import fwread, photo_recipe as P, photo_recipe_extension_read as R
from . import rescue_gate

LAYOUT='gr3x160_inplace_with_photo_recipe_v1'


def packets(output):
    raw=fwread.unpack(output)
    rows=rescue_gate.records(raw)
    rtos=next((r for r in rows if r[0]=='RTOS'),None)
    if rtos is None or rtos[1]!=0x10860:raise ValueError('RTOS layout')
    start=0x10870+0x10b55c0;blob=raw[start:rtos[2]];info=R.inspect(blob)
    return {r['slot']:blob[r['address']-R.BASE:r['address']-R.BASE+r['size']] for r in info['packets']}


def from_output(output):
    rows=[]
    for slot,packet in packets(output).items():
        value=P.decode(packet)
        rows.append(dict(slot=slot,film=value['profile']['id'],packet_sha256=value['packet_sha256'],
                         numeric_sha256=value['numeric_sha256'],packet_base64=base64.b64encode(packet).decode('ascii')))
    return dict(schema=1,layout=LAYOUT,abi=P.ABI,scope='darkslide-film-core',snapshots=rows,
                stored_in_build_manifest=True,automatically_stored_in_photos=True,
                camera_restore_implemented=True,camera_verified=False,
                photo_format='DNG private tag d534; JPEG DSRECIPE APP15 v1',
                jpeg_capture_implemented=True,jpeg_archived_raw_reexport=True,
                dng_history_formatter_implemented=True,raw_to_dng_camera_entry_implemented=False,
                raw_development_documented_output='JPEG',
                jpeg_history_storage='owned full packet; request-inline copy; exact APP15 re-export',
                jpeg_optional_metadata_fallback='preserve stock JPEG on admission failure',
                per_shot_controls_included=False)


def verify(output,edits,archive):
    actual=packets(output);selected={e['slot']:e['film'] for e in edits if e['kind']=='film'}
    if (archive.get('layout')!=LAYOUT or archive.get('schema')!=1 or archive.get('abi')!=P.ABI or
            archive.get('scope')!='darkslide-film-core' or set(actual)!=set(selected)):
        raise ValueError('配方归档布局/槽位不一致')
    rows=archive.get('snapshots')
    if type(rows) is not list or len(rows)!=len(actual):raise ValueError('配方归档数量不一致')
    seen=set()
    for row in rows:
        slot=row['slot'];value=P.decode(actual[slot])
        if slot in seen or row['film']!=selected[slot] or value['profile']['id']!=selected[slot]:raise ValueError('配方归档身份不一致')
        seen.add(slot)
        if (base64.b64decode(row['packet_base64'],validate=True)!=actual[slot] or
                row['packet_sha256']!=value['packet_sha256'] or row['numeric_sha256']!=value['numeric_sha256']):
            raise ValueError('配方归档与输出中的实际数值不一致')
    return dict(id='gr3x_film_recipe_archive',title='配方备份与输出内实际曲线及许可包一致',ok=True)
