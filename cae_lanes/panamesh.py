# -*- coding: utf-8 -*-
"""panamesh: PanaParaMesher(parallel_tetmesh) 并行四面体网格细化的封装。

链路: 粗网格 .inp →(PanaPara.exe: METIS 分区 + MS-MPI 并行 h-refinement)→ 分区二进制
→(ResultRead.exe + *_rst_.refined_json 清单)→ 分区 .inp。
每次细分单元数 ×8(numSubdivision=n → ×8^n), 节点约 ×2^n。

纪律(与 abaqus/comsol 车道一致):
  - 大网格走 quest: mesh_refine(mode=plan) 只造命令(ctrl json + PanaPara 调用),
    经 quest_run 派发; 收尾用 mode=convert 转可视化 .inp + mesh_check 核对单元数。
  - 小网格(输出单元 <= INLINE_MAX_ELEMS)允许 mode=run 在线直跑(含转换+校验)。

坑:
  - PanaPara 内部窄字符路径: 工作区必须全 ASCII, 默认落 D:/panamesh/<stem>/;
    源 .inp 路径含非 ASCII 时自动拷贝为工作区内 coarse.inp 再引用。
  - ResultRead 的输入是 *_rst_.refined_json(结果清单), 不是 bodyMesh.bin。
  - 细化后单元数 = 输入×8^n 为名义值, 分区界面处理可能有小幅偏差(冒烟实测 -1.7%)。
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

try:
    from . import config as _cfg
except ImportError:
    import config as _cfg

PANA_EXE = _cfg.PANA_EXE
PANA_READ_EXE = _cfg.PANA_READ_EXE
WORK_ROOT = _cfg.PANA_WORK_ROOT

INLINE_MAX_ELEMS = 2_000_000   # 输出单元超过此数禁在线直跑, 只出计划
INLINE_TIMEOUT_S = 600
SUCCESS_KEYWORD = 'done running ParallelTetMesh'
_ASCII_RE = re.compile(r'^[\x20-\x7e]+$')


def _is_ascii(s):
    return bool(_ASCII_RE.match(s))


def parse_inp(path):
    """容错解析 .inp: 返回 {'nodes': N, 'elements': M}。只认段头与数据行起始数字。"""
    nodes = elems = 0
    section = ''
    with open(path, 'r', errors='replace') as f:
        for line in f:
            t = line.strip()
            if not t:
                continue
            if t.startswith('**'):          # 注释
                continue
            if t.startswith('*'):           # 段头, 如 *NODE / *ELEMENT, TYPE = C3D4
                u = t.upper()
                section = 'N' if u.startswith('*NODE') else (
                    'E' if u.startswith('*ELEMENT') else '')
                continue
            if t[0].isdigit():
                if section == 'N':
                    nodes += 1
                elif section == 'E':
                    elems += 1
    return {'nodes': nodes, 'elements': elems}


def _default_cores():
    try:
        return max(1, min(8, os.cpu_count() // 2))
    except Exception:
        return 4


def _prepare_workspace(inp_file, out_dir):
    """建工作区(强制 ASCII); 返回 (ascii_inp_path, work_dir)。"""
    inp_file = os.path.abspath(inp_file)
    if not os.path.isfile(inp_file):
        raise FileNotFoundError('inp 不存在: %s' % inp_file)
    stem = os.path.splitext(os.path.basename(inp_file))[0]
    if not _is_ascii(stem):
        stem = 'coarse'
    work = out_dir or os.path.join(WORK_ROOT, stem)
    if not _is_ascii(work):
        raise ValueError('out_dir 含非 ASCII(PanaPara 窄字符路径会 mojibake): %s' % work)
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.join(work, 'output'), exist_ok=True)

    dst = os.path.join(work, stem + '.inp')
    if os.path.abspath(inp_file) != os.path.abspath(dst):
        shutil.copyfile(inp_file, dst)
    return dst, work


def _write_ctrl(inp_ascii, work, num_subdivision, num_partition, num_core,
                num_smooth, par_metis, output_int_type, export_inp):
    ctrl = {
        'inpFile': inp_ascii.replace('\\', '/'),
        'workingDir': (work + '/temp/').replace('\\', '/'),
        'outputPath': (work + '/output/').replace('\\', '/'),
        'parMetis': int(par_metis),
        'mpiexecPath': _cfg.PANA_MPIEXEC,
        'numCore': int(num_core),
        'numPartition': int(num_partition),
        'numSubdivision': int(num_subdivision),
        'numSmooth': int(num_smooth),
        'testMode': 0,
        'exportInpFile': int(export_inp),
        'outputIntType': int(output_int_type),
    }
    ctrl_path = os.path.join(work, 'ctrl.json')
    with open(ctrl_path, 'w', encoding='ascii') as f:   # ensure 工作区全 ASCII
        json.dump(ctrl, f, indent=2)
    return ctrl_path, ctrl


def plan_refine(inp_file, out_dir=None, num_subdivision=1, num_partition=None,
                num_core=None, num_smooth=0, par_metis=0, output_int_type=0,
                export_inp=1):
    """轻操作: 校验输入 → 估规模 → 写 ctrl.json → 造 quest_run 命令。不执行。"""
    inp_ascii, work = _prepare_workspace(inp_file, out_dir)
    cnt = parse_inp(inp_ascii)
    if cnt['elements'] <= 0:
        raise ValueError('未在 %s 中解析到 *ELEMENT 数据(C3D4 四面体网格?)' % inp_file)

    n = int(num_subdivision)
    n = max(0, min(n, 6))
    num_core = int(num_core or _default_cores())
    num_partition = int(num_partition or num_core)
    if num_partition < num_core:
        num_partition = num_core          # 约束: numPartition >= numCore

    ctrl_path, ctrl = _write_ctrl(inp_ascii, work, n, num_partition, num_core,
                                  num_smooth, par_metis, output_int_type, export_inp)

    out_elems = cnt['elements'] * (8 ** n)
    out_nodes = int(cnt['nodes'] * (2 ** n))
    cmd = '"%s" "%s"' % (PANA_EXE, ctrl_path)
    return {
        'cmd': cmd,
        'cwd': _cfg.PANA_ROOT,
        'success_keyword': SUCCESS_KEYWORD,
        'estimate': {
            'input_nodes': cnt['nodes'], 'input_elements': cnt['elements'],
            'subdivision': n,
            'nominal_out_elements': out_elems, 'approx_out_nodes': out_nodes,
            'num_core': num_core, 'num_partition': num_partition,
        },
        'ctrl_json': ctrl_path,
        'output_dir': os.path.join(work, 'output'),
        'inline_ok': out_elems <= INLINE_MAX_ELEMS,
        'quest_hint': ('quest_run: success 只写关键词 %s; cwd=%s; '
                       '跑完用 mesh_refine(mode=convert) 转可视化 .inp, '
                       'mesh_check 核对单元数' % (SUCCESS_KEYWORD, _cfg.PANA_ROOT)),
        'note': 'numSubdivision 每加 1 单元×8; 单机 64GB 建议输出单元 <=1.5亿, 再大上集群。',
    }


def convert_results(out_dir):
    """out_dir 里的 *_rst_.refined_json 逐个转 part<i>.inp 并计数。"""
    manifests = sorted(glob.glob(os.path.join(out_dir, '*_rst_.refined_json')))
    if not manifests:
        raise FileNotFoundError('out_dir 无 *_rst_.refined_json: %s' % out_dir)
    parts = []
    for m in manifests:
        idx = os.path.basename(m).split('_')[0]
        out_inp = os.path.join(out_dir, 'part%s.inp' % idx)
        r = subprocess.run([PANA_READ_EXE, m, out_inp], capture_output=True,
                           text=True, encoding='utf-8', errors='replace',
                           timeout=120)
        if r.returncode != 0 or not os.path.isfile(out_inp):
            raise RuntimeError('ResultRead 失败(%s): %s' % (m, (r.stderr or r.stdout)[-300:]))
        parts.append({'partition': int(idx), 'inp': out_inp,
                      **parse_inp(out_inp)})
    parts.sort(key=lambda p: p['partition'])
    return parts


def run_refine(inp_file, out_dir=None, num_subdivision=1, num_partition=None,
               num_core=None, num_smooth=0, par_metis=0, output_int_type=0,
               export_inp=1, timeout_s=INLINE_TIMEOUT_S):
    """在线直跑(仅小网格): PanaPara → ResultRead → 校验。大网格先走 plan。"""
    spec = plan_refine(inp_file, out_dir, num_subdivision, num_partition,
                       num_core, num_smooth, par_metis, output_int_type, export_inp)
    est = spec['estimate']
    if not spec['inline_ok']:
        return {'refused': ('nominal_out_elements=%d > %d, 走 mode=plan + quest 派发'
                            % (est['nominal_out_elements'], INLINE_MAX_ELEMS)),
                'plan': spec}
    # 清掉上一轮残留(清单名含内容哈希, 新旧会混)——保证 run 幂等
    for pat in ('*_rst_.refined_json', '*_rst_*.bin', 'part*.inp'):
        for f in glob.glob(os.path.join(spec['output_dir'], pat)):
            os.remove(f)
    t0 = time.time()
    r = subprocess.run([PANA_EXE, spec['ctrl_json']], capture_output=True,
                       text=True, encoding='utf-8', errors='replace',
                       cwd=_cfg.PANA_ROOT, timeout=timeout_s)
    elapsed = time.time() - t0
    tail = ((r.stdout or '') + (r.stderr or ''))[-1500:]
    if SUCCESS_KEYWORD not in (r.stdout or ''):
        return {'ok': False, 'elapsed_s': round(elapsed, 1),
                'log_tail': tail, 'hint': '看 workingDir 权限/mpiexec/mpmetis 报错'}

    parts = convert_results(spec['output_dir'])
    total_elems = sum(p['elements'] for p in parts)
    total_nodes = sum(p['nodes'] for p in parts)
    nominal = est['nominal_out_elements']
    dev = (total_elems - nominal) / float(nominal) * 100 if nominal else 0
    return {
        'ok': True,
        'elapsed_s': round(elapsed, 1),
        'partitions': len(parts),
        'total_elements': total_elems, 'total_nodes': total_nodes,
        'nominal_elements': nominal,
        'deviation_pct': round(dev, 2),
        'verdict': 'OK' if abs(dev) <= 5 else 'WARN(偏差>5%, 查分区界面/输入质量)',
        'per_partition': parts,
        'ctrl_json': spec['ctrl_json'],
        'output_dir': spec['output_dir'],
        'log_tail': tail[-400:],
    }


def check(paths, expect_elements=None):
    """mesh_check: 数一批 .inp 的节点/单元; 可选对预期总量核对(±5%)。"""
    files = []
    for p in paths if isinstance(paths, list) else [paths]:
        files.extend(sorted(glob.glob(p)) or ([p] if os.path.isfile(p) else []))
    if not files:
        raise FileNotFoundError('无匹配文件: %r' % (paths,))
    rows, tot_e, tot_n = [], 0, 0
    for f in files:
        c = parse_inp(f)
        tot_e += c['elements']
        tot_n += c['nodes']
        rows.append({'file': f, **c})
    out = {'files': rows, 'total_elements': tot_e, 'total_nodes': tot_n}
    if expect_elements:
        dev = (tot_e - expect_elements) / float(expect_elements) * 100
        out.update({'expect_elements': expect_elements,
                    'deviation_pct': round(dev, 2),
                    'verdict': 'OK' if abs(dev) <= 5 else 'WARN'})
    return out
