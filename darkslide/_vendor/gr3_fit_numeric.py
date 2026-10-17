"""Selected numerical algorithms from gr3-film-mods (MIT).

Copyright (c) 2026 idontknownihil. License: GR3_FILM_MODS_LICENSE.txt.
Modified by LiorMoment: explicit finite/domain checks, dependency-free Q13,
and lazy NumPy for the development-only curve fitter. No firmware I/O.
See gr3_fit_numeric_source.json for pinned sources and changes.
"""
import math


def q13_matrix(matrix):
    """make_film.q13_matrix: ties-to-even, repair each diagonal to row sum8192."""
    if type(matrix) is not list or len(matrix)!=3:
        raise ValueError("expected 3 matrix rows")
    q=[]
    for row in matrix:
        if type(row) is not list or len(row)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) or not -4<=v<4 for v in row):
            raise ValueError("finite representable matrix required")
        if abs(math.fsum(row)-1)>1e-12:
            raise ValueError("source matrix must preserve white")
        q.append([round(v*8192) for v in row])
    for i in range(3):
        q[i][i]+=8192-sum(q[i])
    if any(not -32768<=v<=32767 for row in q for v in row):
        raise ValueError("Q13 repair exceeds signed16")
    return q


def fit_curve(g,t,w,lam=3000.0):
    """cube_fit.fit_curve: weighted256-knot LS with second-difference smoothing.

    Requires caller-supplied gamma output g and target t, never substitutes a
    foreign firmware gamma dump or calls a generator. NumPy is a dev dependency.
    """
    import numpy as np
    arrays=[np.asarray(v) for v in (g,t,w)]
    if any(v.ndim!=1 or v.dtype.kind not in "fiu" for v in arrays):
        raise ValueError("one-dimensional numeric samples required")
    g,t,w=[v.astype(float) for v in arrays]
    if not len(g) or len(t)!=len(g) or len(w)!=len(g) or any(not np.isfinite(v).all() for v in (g,t,w)):
        raise ValueError("finite equally-sized samples required")
    if np.any(g<0) or np.any(g>16384) or np.any(t<0) or np.any(t>1) or np.any(w<0) or not np.any(w>0):
        raise ValueError("samples outside gamma/target/weight domain")
    if type(lam) not in (int,float) or not math.isfinite(lam) or lam<0:
        raise ValueError("nonnegative finite smoothing required")
    x=np.clip(g/64.0,0,255)
    i0=np.minimum(x.astype(int),254);f=x-i0
    A=np.zeros((256,256));b=np.zeros(256)
    for a_i,a_w in ((i0,1-f),(i0+1,f)):
        for b_i,b_w in ((i0,1-f),(i0+1,f)):
            np.add.at(A,(a_i,b_i),w*a_w*b_w)
        np.add.at(b,a_i,w*a_w*t*16384)
    D=np.diff(np.eye(256),2,axis=0)
    # Same Gram matrix as D.T@D. The installed NumPy2.2.6 matmul emits
    # floating exceptions even for this bounded integer stencil (-4..6).
    # Scalar contraction avoids that backend path without suppressing warnings.
    penalty=np.einsum("ki,kj->ij",D,D,optimize=False)
    c=np.linalg.solve(A+lam*penalty+1e-6*np.eye(256),b)
    if not np.isfinite(c).all():
        raise ValueError("curve solve produced nonfinite values")
    c=np.maximum.accumulate(np.clip(c,0,16383))
    return np.round(c).astype(int).tolist()
