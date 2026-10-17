"""Independent merged-image readback: no compiler, planner or writer imports."""
from collections import namedtuple
import hashlib
from . import fwread, models, photo_recipe, photo_recipe_candidate_verify
from . import gr3x_inplace_integrity as integrity, gr3x_inplace_readback as reader

ReadWindow = namedtuple('ReadWindow', 'address expected replacement')


def verify(official, output, curve_base, ordinary_base, windows, selection, profiles, packets, native, *, shutdown_hdf=False):
    checks = []
    def need(ok,why):
        if not ok: raise ValueError(why)
    try:
        raw, plain, cur = (fwread.unpack(b) for b in (official,ordinary_base,curve_base))
        need(hashlib.sha256(raw).hexdigest()==models.GR3X.payload_sha,'target original')
        need(len(raw)==len(plain)==len(cur),'curve stage growth')
        def off(at,n):
            if 0x55000000<=at and at+n<=0x5503a080:at=at-0x55000000+0x5407b540
            need(0x53000000<=at and at+n<=0x540b55c0,'target span')
            return 0x10870+at-0x53000000
        actual=[];restored=bytearray(cur)
        for w in windows:
            at=off(w.address,len(w.expected));end=at+len(w.expected)
            need(plain[at:end]==raw[at:end],'ordinary/curve overlap')
            actual.append(ReadWindow(w.address,raw[at:end],cur[at:end]))
            restored[at:end]=plain[at:end]
        # Coverage and shared-byte reference are fixed by mask, independent of
        # the generator's declarations. Data oracle uses dense rational fitting.
        checked=integrity.verify(raw,tuple(actual),selection,profiles,layout=reader.LAYOUT)
        need(bytes(restored[:-4])==plain[:-4],'undeclared curve-stage difference')
        checks.append(dict(id='independent_curve_stage',ok=True,details=checked))
        need(set(packets)==set(selection),'snapshot slots')
        for slot,ident in selection.items():
            snap=photo_recipe.decode(packets[slot]);p=snap['profile'];source=profiles[ident]
            need(snap['slot']==slot and p['id']==ident,'snapshot identity')
            need(p['look_matrix_q13']==source['look_matrix_q13'] and
                 p['post_matrix_q512']==source['post_matrix_q512'],'snapshot matrices')
            for channel,curve in enumerate(source['curves_u14']):
                nodes=reader.nodes(tuple(curve))
                reconstructed=[nodes[i//8]+(nodes[i//8+1]-nodes[i//8])*(i%8)//8 for i in range(256)]
                need(p['curves_u14'][channel]==reconstructed,'snapshot not actual applied curve')
            for key,value in source.items():
                if key not in ('curves_u14','curve_storage'):
                    need(p.get(key)==value,'snapshot provenance changed')
        checks.append(dict(id='snapshots_match_actual_curves',ok=True))
        checks.extend(photo_recipe_candidate_verify.verify(official,output,curve_base,packets,native,
                      tuple(sorted(selection)),inplace=True,shutdown_hdf=shutdown_hdf))
    except (ValueError,TypeError,KeyError,IndexError) as error:
        checks.append(dict(id='merged_closed_failure',ok=False,detail=str(error)))
    return checks
