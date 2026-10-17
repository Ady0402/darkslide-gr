"""Adopt licensed matrix/curves/post fits without executing upstream patchers."""
import hashlib
import json
import math
import re
from pathlib import Path
from .film_profiles import validate_profile
from .film_requests import validate_request,FilmRequestError
from ._vendor.gr3_fit_numeric import q13_matrix

UPSTREAM_COMMIT="04d5d5dd6e85d80089c6200bd0f0de5fff2d658f"
SOURCE_ROOT=Path(__file__).resolve().parent.parent/"film_curves"/"upstream_gr3_fits"


def read_fit(path):
    raw=Path(path).read_bytes()
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise FilmRequestError("拟合文件字段重复")
            result[key]=value
        return result
    def invalid(value):raise FilmRequestError("拟合文件非有限数值")
    def finite(value):
        n=float(value)
        if not math.isfinite(n):invalid(value)
        return n
    try:data=json.loads(raw.decode("utf-8"),object_pairs_hook=pairs,parse_constant=invalid,parse_float=finite)
    except (UnicodeError,json.JSONDecodeError,RecursionError) as error:raise FilmRequestError("拟合文件无效") from error
    return data,hashlib.sha256(raw).hexdigest()


def convert_fit(data,ident,source_path,source_sha256):
    """Caller admits license/origin first; this function validates numeric format."""
    validate_request(dict(kind="film",slot=8,film=ident))
    if type(source_path) is not str or not source_path.startswith("work/") or ".." in source_path.split("/") or "films_v16" in source_path.split("/") or type(source_sha256) is not str or not re.fullmatch("[0-9a-f]{64}",source_sha256):
        raise FilmRequestError("拟合来源记录无效")
    def unsupported(value):
        if type(value) is dict:
            return bool(set(value)&{"hue_q10","v16","hue_sectors"}) or any(unsupported(v) for v in value.values())
        if type(value) is list:return any(unsupported(v) for v in value)
        return False
    if type(data) is not dict or unsupported(data):
        raise FilmRequestError("此拟合包含尚未接入的色相分区")
    if type(data.get("presets")) is not list or len(data["presets"])!=1 or type(data["presets"][0]) is not dict:
        raise FilmRequestError("需要单个明确的胶片拟合结果")
    preset=data["presets"][0]
    encoding=preset.get("in_cs","vlog");ev=preset.get("ev",0.0)
    if encoding not in ("vlog","srgb") or type(ev) not in (int,float) or not math.isfinite(ev):
        raise FilmRequestError("拟合目标编码或曝光记录无效")
    spec=preset.get("spec")
    if type(spec) is not str or "spektrafilm_v034_" not in spec:
        raise FilmRequestError("未核准的拟合数据来源")
    if type(data.get("mid_index")) not in (int,float) or data["mid_index"]!=7.8:
        raise FilmRequestError("拟合的基础曝光模型不匹配")
    try:matrix=q13_matrix(data.get("matrix"))
    except ValueError as error:raise FilmRequestError(str(error)) from error
    post=data.get("post_q512",data.get("cca1_q512"))
    if "post_q512" in data and "cca1_q512" in data and data["post_q512"]!=data["cca1_q512"]:
        raise FilmRequestError("存在冲突的曲线后矩阵")
    profile=dict(schema=1,id=ident,model="GR III",firmware="2.10",
                 look_matrix_q13=matrix,curves_u14=preset.get("curves"),post_matrix_q512=post,
                 provenance=dict(project="idontknownihil/gr3-film-mods",commit=UPSTREAM_COMMIT,
                     source_path=source_path,source_sha256=source_sha256,target_spec=spec,
                     target_input_encoding=encoding,target_ev=ev,
                     target_input_encoding_source="explicit" if "in_cs" in preset else "upstream target_of default",
                     target_ev_source="explicit" if "ev" in preset else "upstream target_of default",
                     source_mid_index=7.8,absolute_exposure_calibrated=False,
                     authors=["Andrea Volpato","idontknownihil"],modified_by="LiorMoment",
                     license="CC-BY-SA-4.0",quantization="ties-to-even then diagonal row repair"),
                 native_effect_verified=False)
    return validate_profile(profile,ident)


def convert_file(path,ident,source_path):
    data,sha=read_fit(path)
    return convert_fit(data,ident,source_path,sha)
