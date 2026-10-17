"""Copy an explicitly chosen IIIx development store; never move or rewrite it."""
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from . import models
from .store import Store, StoreError, read_json, write_json, _keep_blob


def digest(data):return hashlib.sha256(data).hexdigest()


def tree(folder):
    rows = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():raise StoreError('旧目录包含符号链接，未导入')
        if path.is_file():
            if path.stat().st_size > 512 * 1024 * 1024:raise StoreError('旧文件过大，未导入')
            rows[str(path.relative_to(folder))] = digest(path.read_bytes())
    return rows


def fingerprint(rows):return digest(json.dumps(rows,sort_keys=True).encode())


def source_plan(destination, source):
    source = Path(source).expanduser()
    if source.is_symlink():raise StoreError('请选择实际旧数据目录')
    source = source.resolve(); target = destination.root.resolve()
    if not source.is_dir() or source == target or source in target.parents or target in source.parents:
        raise StoreError('新旧数据目录必须独立，不能相互包含')
    for relative in ('projects','inputs','builds'):
        if (source/relative).is_symlink():raise StoreError('旧目录包含符号链接')
    original = source/'inputs'/(models.GR3X.input_sha+'.bin')
    if original.is_symlink() or not original.is_file():raise StoreError('旧目录缺少 IIIx 官方原件')
    data = original.read_bytes()
    if len(data) != models.GR3X.input_size or digest(data) != models.GR3X.input_sha:
        raise StoreError('旧目录的 IIIx 官方原件校验失败')
    projects=[]; mapping={}
    for folder in sorted((source/'projects').glob('p_*')):
        if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'p_[0-9a-f]{12}',folder.name):
            raise StoreError('旧工程目录无效')
        rows=tree(folder); project=read_json(folder/'project.json')
        if not isinstance(project,dict):raise StoreError('旧工程记录格式无效')
        index=read_json(folder/'film_luts.json',{})
        if not isinstance(index,dict) or any(not isinstance(v,dict) for v in index.values()):
            raise StoreError('旧 LUT 索引格式无效')
        if models.for_project(project) != models.GR3X or project.get('id') != folder.name:
            raise StoreError('旧目录包含非 IIIx 工程或工程身份不符')
        ident='p_'+digest((str(source)+'/'+folder.name).encode())[:12]
        mapping[folder.name]=ident
        projects.append(dict(source_id=folder.name,id=ident,title=project.get('title'),files=rows,fingerprint=fingerprint(rows)))
    builds=[]
    for folder in sorted((source/'builds').glob('b_*')):
        if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'b_[0-9a-f]{12}',folder.name):
            raise StoreError('旧生成目录无效')
        rows=tree(folder); manifest=read_json(folder/'manifest.json')
        if manifest.get('project_id') not in mapping:raise StoreError('旧生成记录没有对应工程')
        if checked_build(folder,manifest)[0] != models.GR3X:raise StoreError("旧构建不是 IIIx")
        ident='b_'+digest((str(source)+'/'+folder.name).encode())[:12]
        builds.append(dict(source_id=folder.name,id=ident,project_id=mapping[manifest['project_id']],files=rows,fingerprint=fingerprint(rows)))
    return dict(source=str(source),projects=projects,builds=builds,source_digest=fingerprint({'projects':projects,'builds':builds}),input_sha256=models.GR3X.input_sha)


def checked_build(folder, manifest):
    if not isinstance(manifest,dict):raise StoreError('历史构建记录格式无效')
    model=models.from_sha(manifest.get('input_sha256'))
    filename=manifest.get('output_filename', models.GR3.filename)
    if filename != model.filename:raise StoreError('历史构建文件名与机型不一致')
    if not re.fullmatch(r'[0-9a-f]{64}',str(manifest.get('output_sha256',''))):raise StoreError('历史构建缺少完整校验值')
    path=folder/filename
    if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != manifest['output_sha256']:
        raise StoreError('历史构建文件已改变或缺失')
    checks=manifest.get('checks')
    if not isinstance(checks,list) or not checks or any(not isinstance(c,dict) or c.get('ok') is not True for c in checks):
        raise StoreError('历史构建核对记录未通过')
    return model,path


def import_store(destination, source, *, apply=False, expected_digest=None):
    plan=source_plan(destination,source)
    if not apply:return plan
    if expected_digest != plan['source_digest']:raise StoreError('旧目录内容已变化，请重新查看导入清单')
    src=Path(plan['source'])
    # Check all destination identities before modifying anything.
    for kind in ('projects','builds'):
        for row in plan[kind]:
            dest=destination.root/kind/row['id']
            marker=dict(source=plan['source'],source_id=row['source_id'],fingerprint=row['fingerprint'])
            if dest.exists() and read_json(dest/'legacy-import.json',{}) != marker:
                raise StoreError('导入目标编号冲突，保留现有内容')
    original = (src/'inputs'/(models.GR3X.input_sha+'.bin')).read_bytes()
    if len(original) != models.GR3X.input_size or digest(original) != models.GR3X.input_sha:
        raise StoreError("复制前官方原件已改变，未导入")
    _keep_blob(destination.input_path(models.GR3X.input_sha), original)
    for kind in ('projects','builds'):
        parent=destination.root/kind;parent.mkdir(parents=True,exist_ok=True)
        for row in plan[kind]:
            dest=parent/row['id']
            if dest.exists():continue
            with tempfile.TemporaryDirectory(prefix='.import-',dir=parent) as temporary:
                stage=Path(temporary)/'data'
                shutil.copytree(src/kind/row['source_id'],stage,symlinks=True)
                if tree(stage) != row['files']:raise StoreError('复制期间旧目录发生变化，未保存该项')
                marker=dict(source=plan['source'],source_id=row['source_id'],fingerprint=row['fingerprint'])
                if kind=='projects':
                    project=read_json(stage/'project.json');project['id']=row['id']
                    write_json(stage/'project.json',project)
                    # Preserve the historical record but require refitting with this model revision.
                    index=read_json(stage/'film_luts.json',{})
                    for entry in index.values():
                        if entry.get('profile') is not None:
                            entry['legacy_fit']=dict(profile=entry.get('profile'),fit=entry.get('fit'))
                            entry.update(profile=None,fit=None)
                    if index:write_json(stage/'film_luts.json',index)
                else:
                    manifest=read_json(stage/'manifest.json')
                    manifest.update(build_id=row['id'],project_id=row['project_id'])
                    write_json(stage/'manifest.json',manifest)
                write_json(stage/'legacy-import.json',marker)
                stage.rename(dest)
    rows=destination.builds();known={r['build_id'] for r in rows}
    for row in plan['builds']:
        if row['id'] not in known:
            manifest=read_json(destination.root/'builds'/row['id']/'manifest.json')
            rows.append(dict(build_id=row['id'],project_id=row['project_id'],output_sha256=manifest['output_sha256'],created_at=manifest.get('created_at'),legacy_import=True))
    write_json(destination.root/'builds.json',rows)
    return dict(plan,imported=True,original_preserved=True,legacy_fits_require_refit=True)
