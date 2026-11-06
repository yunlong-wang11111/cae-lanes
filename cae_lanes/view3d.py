# -*- coding: utf-8 -*-
"""view3d: 仿真产物 → 手机 3D 查看器投递（inbox 自动转换链路的封装）。

链路: 复制进 <root>/inbox/ → autodrop（8178 查看服务自带的转换线程）自动转换
→ <root>/models/ → 手机浏览器 http://<主机IP>:8178/viewer.html 刷新即看。

  .odb             → <stem>.anim.json + .anim.bin  动画包（abaqus 后台导出, 分钟级）
  .stp / .step     → <stem>.stl                    秒级
  .vtk/.vtu 同名_N 序列 → <stem>.anim.json+bin     动画包（COMSOL 多时间步导出）
  .vtk/.vtu 单帧   → <stem>.stl
  .bdf / .nas      → <stem>.stl                    仅网格几何
  .stl/.ply/.glb/.gltf → 直接入库（复制）

本模块只做同机文件系统操作; 转换/查看服务本体是 view3d-server.py（须在跑, 见
service_up()）。溯源: models/sources.json 记录 产物→源文件 映射（查看器
"原始文件⇄中间格式"切换用）。清理须产物与源一起删——只删一边 autodrop 会重新转出来。
"""
import glob
import json
import os
import re
import shutil
import socket
import time

try:
    from . import config as _cfg  # package mode
except ImportError:
    import config as _cfg         # standalone MCP mode

ROOT = _cfg.VIEW3D_ROOT
INBOX = os.path.join(ROOT, 'inbox')
MODELS = os.path.join(ROOT, 'models')
LOG = os.path.join(ROOT, 'autodrop.log')
SOURCES = os.path.join(MODELS, 'sources.json')

DIRECT = ('.stl', '.ply', '.glb', '.gltf')
TO_STL = ('.stp', '.step', '.bdf', '.nas', '.vtk', '.vtu')
SUPPORTED = DIRECT + TO_STL + ('.odb',)

_seq_re = re.compile(r'^(.*)_(\d+)$')


class View3dError(Exception):
    pass


# ---------------------------------------------------------------- 基础
def products_for(src_name):
    """源文件名 → 预期 models 产物名列表（与 autodrop.plan 同口径）。"""
    stem, ext = os.path.splitext(src_name)
    ext = ext.lower()
    if ext in DIRECT:
        return [src_name]
    if ext in TO_STL:
        return [stem + '.stl']
    if ext == '.odb':
        return [stem + '.anim.json', stem + '.anim.bin']
    return []


def service_up():
    """查看服务（含 autodrop 转换线程）是否在跑。"""
    sk = socket.socket()
    sk.settimeout(1.5)
    try:
        sk.connect(('127.0.0.1', _cfg.VIEW3D_PORT))
        return True
    except Exception:
        return False
    finally:
        sk.close()


def lan_ip():
    """本机局域网 IP（connect 到保留地址拿路由出口, 不实际发包）。"""
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sk.connect(('192.0.2.1', 9))
        return sk.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        sk.close()


def viewer_url(name=''):
    base = 'http://%s:%d/viewer.html' % (lan_ip(), _cfg.VIEW3D_PORT)
    return base + ('?part=' + name if name else '')


def _read_sources():
    try:
        with open(SOURCES, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_sources(m):
    tmp = SOURCES + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(m, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, SOURCES)


def _handled(src_path, outs):
    return all(os.path.isfile(os.path.join(MODELS, o))
               and os.path.getmtime(os.path.join(MODELS, o)) > os.path.getmtime(src_path)
               for o in outs)


# ---------------------------------------------------------------- 投递
def drop(path, alias=None):
    """把文件复制进 inbox（支持 glob 通配符与目录展开），返回投递报告。

    alias 仅在恰好一个文件时生效（换名入库, 含扩展名）;
    vtk/vtu 序列建议直接传通配符 path（如 D:/x/demo_*.vtk）整组投递。
    """
    path = os.path.expanduser(str(path))
    if os.path.isdir(path):
        files = sorted(os.path.join(path, n) for n in os.listdir(path)
                       if os.path.isfile(os.path.join(path, n)))
    else:
        files = sorted(glob.glob(path))
    if not files:
        raise View3dError('没匹配到文件: %s' % path)
    if alias and len(files) > 1:
        raise View3dError('多个文件不能用 alias（glob=%d 个）' % len(files))
    unsupported = [f for f in files
                   if os.path.splitext(f)[1].lower() not in SUPPORTED]
    if unsupported:
        raise View3dError('不支持的类型: %s（支持 %s）'
                          % (', '.join(os.path.basename(f) for f in unsupported[:5]),
                             ' '.join(SUPPORTED)))
    os.makedirs(INBOX, exist_ok=True)
    dropped = []
    for f in files:
        name = alias or os.path.basename(f)
        dst = os.path.join(INBOX, name)
        if os.path.abspath(dst) == os.path.abspath(f):
            dropped.append({'file': name, 'note': '已在 inbox, 跳过复制'})
            continue
        shutil.copy2(f, dst)
        dropped.append({'file': name, 'size_mb': round(os.path.getsize(dst) / 1048576.0, 1)})
    expect = sorted({o for d in dropped for o in products_for(d['file'])})
    up = service_up()
    return {
        'dropped': dropped,
        'expect_models': expect,
        'service_up': up,
        'url': viewer_url(expect[0]) if expect else viewer_url(),
        'note': ('autodrop 在跑, 几秒~几分钟后 view3d_list 查进度' if up
                 else '服务未在跑: 先启动 view3d-server.py（否则不会自动转换）'),
    }


# ---------------------------------------------------------------- 状态
def _inbox_flight():
    """inbox 里尚未转出的条目（vtk/vtu 序列成员按组合并, 产物=组stem.anim 包）。"""
    rows = {}
    try:
        names = sorted(os.listdir(INBOX))
    except OSError:
        return []
    for n in names:
        if n.startswith('.') or n.lower().endswith(('.txt', '.md')):
            continue
        p = os.path.join(INBOX, n)
        if not os.path.isfile(p):
            continue
        stem, ext = os.path.splitext(n)
        m = _seq_re.match(stem)
        is_seq = bool(m) and ext.lower() in ('.vtk', '.vtu')
        if is_seq:
            key, outs = m.group(1) + '_*', [m.group(1) + '.anim.json', m.group(1) + '.anim.bin']
        else:
            key, outs = stem, products_for(n)
        row = rows.setdefault(key, {'source': key, 'frames': 0, 'done': True, 'mb': 0.0})
        row['frames'] += 1
        row['mb'] += os.path.getsize(p) / 1048576.0
        if outs and not _handled(p, outs):
            row['done'] = False
    return [dict(v, mb=round(v['mb'], 1)) for v in rows.values() if not v['done']]


def _recent_failures(limit=8):
    try:
        with open(LOG, encoding='utf-8', errors='replace') as fh:
            tail = fh.readlines()[-300:]
    except OSError:
        return []
    out = []
    for line in tail:
        if '失败' in line or 'AUTODROP-OFF' in line:
            out.append(line.strip()[-220:])
    return out[-limit:]


def status(pattern=None):
    """在途/已入库/最近失败 三段汇总; pattern 对模型 stem 做包含过滤。"""
    src_map = _read_sources()
    models = []
    try:
        names = sorted(os.listdir(MODELS))
    except OSError:
        names = []
    for n in names:
        if n == 'sources.json':
            continue
        if not n.lower().endswith(('.stl', '.ply', '.glb', '.gltf', '.json')):
            continue
        if pattern and pattern.lower() not in os.path.splitext(n)[0].lower():
            continue
        st = os.stat(os.path.join(MODELS, n))
        models.append({'name': n, 'mb': round(st.st_size / 1048576.0, 1),
                       'anim': n.endswith('.anim.json'),
                       'source': src_map.get(n, '')})
    models.sort(key=lambda x: -x['mb'])
    return {
        'service_up': service_up(),
        'url': viewer_url(),
        'in_flight': _inbox_flight(),
        'models': models,
        'recent_failures': _recent_failures(),
    }


# ---------------------------------------------------------------- 清理
def clean(name, confirm=False):
    """删查看器条目: models 产物族 + inbox 源 + sources.json 记录（一起删,
    只删一边 autodrop 会重新转出来）。confirm=False 只干跑返回清单。"""
    name = os.path.basename(str(name))
    stem, ext = os.path.splitext(name)
    will = []
    # 产物族: anim 包两个文件 / stl 等单文件（name 可能给的是产物名或源名）
    prod_names = products_for(name) or ([name] if os.path.isfile(os.path.join(MODELS, name)) else [])
    for cand in {p for n2 in prod_names for p in products_for(n2)} | set(prod_names):
        p = os.path.join(MODELS, cand)
        if os.path.isfile(p):
            will.append(p)
    # anim 包另一半
    if stem.endswith('.anim') or ext == '.anim.json':
        for extra in (stem + '.anim.json', stem + '.anim.bin', stem + '.anim.bin'):
            p = os.path.join(MODELS, extra)
            if os.path.isfile(p) and p not in will:
                will.append(p)
    # inbox 源: 同 stem 的任意支持扩展名 + sources.json 反查
    src_map = _read_sources()
    inbox_hits = []
    try:
        for n in os.listdir(INBOX):
            s2, e2 = os.path.splitext(n)
            if (s2 == stem or s2 == stem.replace('.anim', '')) and e2.lower() in SUPPORTED:
                inbox_hits.append(os.path.join(INBOX, n))
            elif _seq_re.match(s2) and _seq_re.match(s2).group(1) == stem.replace('.anim', '') \
                    and e2.lower() in ('.vtk', '.vtu'):
                inbox_hits.append(os.path.join(INBOX, n))  # vtk 序列成员
    except OSError:
        pass
    for prod, src in list(src_map.items()):
        if os.path.splitext(prod)[0] in (stem, stem.replace('.anim', '')):
            sp = os.path.abspath(src)
            if sp.startswith(INBOX) and os.path.isfile(sp) and sp not in inbox_hits:
                inbox_hits.append(sp)
    will += inbox_hits
    if not will:
        raise View3dError('没找到对应条目: %s（用 view3d_list 先看名字）' % name)
    will = sorted(set(will))
    if not confirm:
        return {'will_delete': will, 'confirm': False,
                'note': '干跑; 确认后 clean(confirm=True) 执行'}
    for p in will:
        os.remove(p)
    for prod in list(src_map):
        if os.path.join(MODELS, prod) in will:
            src_map.pop(prod, None)
    _write_sources(src_map)
    return {'deleted': will, 'confirm': True}
