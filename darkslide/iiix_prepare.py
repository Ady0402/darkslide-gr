"""Bound a saved IIIx project to the existing sparse planner and independent reader."""
import copy
from . import models, film_requests, film_profiles
from . import gr3x_inplace as planner, gr3x_inplace_integrity as reader


def prepare(raw, project, supplied=None):
    if models.for_project(project) != models.GR3X or project.get('unsaved'):
        raise ValueError('需要已保存的 IIIx 官方工程')
    frozen = copy.deepcopy(project)
    requests = film_requests.from_changes(frozen.get('changes', {}))
    supplied = supplied or {}
    required = {r['film'] for r in requests if r['film'].startswith('user_lut_')}
    if set(supplied) != required:raise ValueError('IIIx 用户配方来源不完整或包含额外参数')
    profiles = {r['film']: film_profiles.validate_profile(supplied[r['film']],r['film'],models.GR3X.id)
                if r['film'] in required else film_profiles.load_profile(r['film'],models.GR3X.id) for r in requests}
    plan = planner.plan_offline(raw, list(copy.deepcopy(requests)), copy.deepcopy(profiles))
    if (plan.get('layout') != planner.LAYOUT or type(plan.get('decoded_growth_bytes')) is not int
            or plan['decoded_growth_bytes'] != 0 or any(plan.get(k) is not False for k in
                ('full_image_created', 'production_integration_allowed', 'storage_approved'))):
        raise ValueError('IIIx 稀疏计划超出核对范围')
    windows = copy.deepcopy(plan['windows'])
    checks = reader.verify_project(raw, windows, frozen.get('changes', {}), profiles,
                                  planned_layout=planner.LAYOUT, checked_layout=planner.LAYOUT)
    if (any(checks.get(k) is not True for k in ('data_verified', 'shared_bytes_match_reference',
            'complete_window_coverage_verified')) or any(checks.get(k) is not False for k in
            ('production_approved', 'shared_code_verified'))):
        raise ValueError('IIIx 独立读回未通过')
    return dict(layout=planner.LAYOUT, windows=windows, checks=checks,
                current_slots=film_requests.current_slots(frozen.get('changes', {})))
