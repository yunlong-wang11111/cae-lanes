# -*- coding: utf-8 -*-
"""
simlib-creo: PTC Creo 自动化薄封装（creoson 3.0.x + creopyson 0.7.x, 2026-10-12）

架构（与 comsol.py/abaqus.py 同构）: 库 + CLI。Creo 操作经 creoson REST(9056) → J-Link 异步。
执行者=已运行的 Creo GUI 进程（不是无头——Creo 的 J-Link 异步模式就是连一个开着的 Creo）。

已封装的三类坑（2026-10-12 冒烟实测, 写进护栏）:
  ① creoson API 一律文件名/目录分离传参（合并全路径 = Invalid File Name）
  ② Creo 文件名主名 ≤31 字符（导出名超长直接报错）
  ③ setvars.bat 等 cmd 配置必须 CRLF（LF 会把 set 行拆成乱码命令）

工作姿势（Creo 工程惯例, creoson 不做从零建模）:
  参数化模板(.prt 预建好尺寸参数/关系) → parameter_set/dimension_set 改参 → file_regenerate
  → file_massprops 断言 → interface_export_file(STEP/PDF)。

典型链路:
  import creo
  cc = creo.CreoClient()                       # 连不上会自动 ensure_server/ensure_creo
  cc.open_part('duct_v3.prt', r'D:\\temp\\cad_creo_work')
  cc.set_dims({'LEN': 0.614, 'W': 0.046}, regen=True)
  mp = cc.mass_props()                          # 体积断言
  cc.export_step('duct_smk', r'D:\\temp\\cad_creo_work\\out')

CLI（quest 车道友好, 判据词见各子命令尾行打印）:
  python creo.py ensure      # 确保服务器(9056)+Creo 都活着
  python creo.py smoke       # 冒烟: 开示例件→导 STEP→质量属性 (CREO-SMOKE-DONE)
  python creo.py open --f x.prt --d D:\\dir
  python creo.py export-step --n smk --d D:\\out      # (CREO-EXPORT-DONE)
  python creo.py params --list [--f model]
  python creo.py params --set 'LEN=0.62,W=0.05' --regen  # (CREO-SET-DONE)
  python creo.py dims --list / --set 'd1=46' --regen
  python creo.py mass                                  # (CREO-MASS-DONE)
"""
import argparse
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

try:
    from . import config as _cfg  # package mode
except ImportError:
    import config as _cfg      # standalone MCP mode
CREOSON_DIR = _cfg.CREOSON_DIR
CREOSON_PORT = _cfg.CREOSON_PORT
CREO_EXE = _cfg.CREO_EXE
DEMO_PRT = _cfg.CREO_COMMON + r'\afx\demo\d5_endplate_2.prt'
OTK_JAR = _cfg.CREO_OTK_JAR
CREO_PROCS = ['xtop', 'parametric', 'pro_comm_msg', 'creoagent', 'creosvcs', 'proe']
MAX_NAME = 31   # Creo 祖传文件名主名上限（不含扩展名）


class CreoError(RuntimeError):
    pass


def check_name(name):
    """护栏②: 主名 ≤31 字符、无路径分隔符、无空格。返回去扩展名的纯主名。"""
    stem = str(name)
    for ext in ('.prt', '.asm', '.stp', '.step', '.pdf'):
        if stem.lower().endswith(ext):
            stem = stem[:-len(ext)]
            break
    if not stem or len(stem) > MAX_NAME:
        raise CreoError('Creo 文件名主名 %r 非法（须 1~%d 字符, 不含扩展名）' % (stem, MAX_NAME))
    if any(ch in stem for ch in '\\/ :'):
        raise CreoError('Creo 文件名不能含路径分隔符/冒号: %r（目录请传 dirname 参数）' % stem)
    return stem


def ensure_server():
    """9056 没监听则后台拉起 creoson_run.bat（bat 依赖 setvars.bat, 已配好 CRLF）。"""
    import socket
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(('127.0.0.1', CREOSON_PORT))
        return True
    except Exception:
        pass
    finally:
        s.close()
    bat = os.path.join(CREOSON_DIR, 'creoson_run.bat')
    if not os.path.exists(bat):
        raise CreoError('creoson 未部署: %s 不存在' % CREOSON_DIR)
    subprocess.Popen(['cmd', '/c', bat], cwd=CREOSON_DIR,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(15):
        time.sleep(1)
        s = socket.socket()
        s.settimeout(1.5)
        try:
            s.connect(('127.0.0.1', CREOSON_PORT))
            return True
        except Exception:
            pass
        finally:
            s.close()
    raise CreoError('creoson 服务器 15s 内未在 %d 端口就绪' % CREOSON_PORT)


def ensure_creo(client, wait_s=150):
    """Creo 没在跑则拉起。★ 2026-10-12 验证: -g:no_graphics 无头模式（无窗口、不弹 GUI）
    下 J-Link 异步/开文件/导 STEP/读尺寸全部正常——API 调用从此零弹窗。"""
    for _ in range(3):
        try:
            if client.is_creo_running():
                return True
        except Exception:
            pass
        time.sleep(2)
    subprocess.Popen([CREO_EXE, '-g:no_graphics'], cwd=os.path.expanduser('~'),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(5)
        try:
            if client.is_creo_running():
                return True
        except Exception:
            pass
    raise CreoError('Creo %ss 内未就绪' % wait_s)


class CreoClient(object):
    """creopyson 薄封装: 全部操作自动过护栏①②。"""

    def __init__(self, ensure=True):
        import creopyson
        if ensure:
            ensure_server()
        self.c = creopyson.Client(ip_adress='localhost', port=CREOSON_PORT)
        self.c.connect()
        if ensure:
            ensure_creo(self.c)

    # ── 模型操作 ─────────────────────────────────────────────
    def open_part(self, name, dirname):
        """护栏①: name=纯文件名(带扩展), dirname=目录。"""
        check_name(name)
        if not os.path.isfile(os.path.join(dirname, name)):
            raise CreoError('文件不存在: %s' % os.path.join(dirname, name))
        self.c.file_open(file_=name, dirname=dirname)
        time.sleep(2)

    def active(self):
        a = self.c.file_get_active() or {}
        return a.get('file') or ''

    def save(self):
        self.c.file_save()

    def close(self, name=None):
        self.c.file_close_window(file_=name)

    # ── 参数 / 尺寸（参数化模板主力路径） ─────────────────────
    def list_params(self, file_=None):
        rows = self.c.parameter_list(file_=file_) or []
        return {r.get('name'): r.get('value') for r in rows if r.get('name')}

    def set_params(self, params, file_=None, regen=True):
        """params: {名: 值}; 默认自动再生。键必须已存在（no_create=True 防拼写错建新参）。"""
        for k, v in params.items():
            self.c.parameter_set(name=str(k), value=v, file_=file_, no_create=True)
        if regen:
            self.regen(file_)

    def list_dims(self, file_=None):
        rows = self.c.dimension_list(file_=file_) or []
        return {r.get('name'): r.get('value') for r in rows if r.get('name') is not None}

    def set_dims(self, dims, file_=None, regen=True):
        for k, v in dims.items():
            self.c.dimension_set(name=str(k), value=v, file_=file_)
        if regen:
            self.regen(file_)

    def regen(self, file_=None):
        self.c.file_regenerate(file_=file_)
        time.sleep(1)

    # ── 质量属性（断言用） ────────────────────────────────────
    def mass_props(self, file_=None):
        return self.c.file_massprops(file_=file_) or {}

    # ── 导出（护栏②内置） ────────────────────────────────────    def export_step(self, stem, out_dir, wait_s=30):
        stem = check_name(stem)
        os.makedirs(out_dir, exist_ok=True)
        self.c.interface_export_file(file_type='STEP', filename=stem + '.stp',
                                     dirname=out_dir)
        return self._wait_artifact(os.path.join(out_dir, stem + '.stp'), wait_s)

    def export_pdf(self, stem, out_dir, wait_s=30):
        stem = check_name(stem)
        os.makedirs(out_dir, exist_ok=True)
        self.c.interface_export_file(file_type='PDF', filename=stem + '.pdf',
                                     dirname=out_dir)
        return self._wait_artifact(os.path.join(out_dir, stem + '.pdf'), wait_s)

    @staticmethod
    def _wait_artifact(path, wait_s):
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if os.path.exists(path) and os.path.getsize(path) > 500:
                return os.path.getsize(path)
            time.sleep(2)
        raise CreoError('导出产物未出现/过小: %s' % path)


# ── OTK 侧通用工具（收编自 DSH 2026-10-12 的实做经验） ────────────────────
def otk_api_lookup(pattern, class_hint=None, dump=False):
    """在 otk.jar 的 class 常量池反查方法（无 javap 环境的通用法子, DSH 验证）。
    pattern: 方法名片段（不区分大小写）; class_hint: 限定类名子串（如 pfcSession）;
    dump: 命中类时打印该类全部方法描述符（形如 (params)retval）。
    返回 [(类全名, 描述符…)]。"""
    import zipfile
    import re
    z = zipfile.ZipFile(OTK_JAR)
    pat = re.compile(re.escape(pattern), re.I)
    out = []
    for n in z.namelist():
        if not n.endswith('.class'):
            continue
        cls = n[:-6].replace('/', '.')
        if class_hint and class_hint.lower() not in cls.lower():
            continue
        try:
            d = z.read(n).decode('latin-1')
        except Exception:
            continue
        if not pat.search(d):
            continue
        sigs = []
        if dump:
            sigs = sorted(set(re.findall(r'\([^()]{0,160}\)[A-Za-z0-9/$;\[]{0,80}', d)))[:80]
        out.append((cls, sigs))
    return out


def kill_creo():
    """清残留 Creo 进程树（DSH 验证的"jar 锁死循环"解）：上一次 Creo 没退干净会占着
    .jar 导致 javac 永远失败。注意：本命令连链路常驻的无头实例一起杀——之后任何
    creo.py 调用会自动重拉, 无需手工恢复。返回杀掉的进程名列表。"""
    killed = []
    for name in CREO_PROCS:
        r = subprocess.run(['taskkill', '/F', '/T', '/IM', name + '.exe'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            killed.append(name)
    return killed


# ── CLI ──────────────────────────────────────────────────────
def _cli():
    ap = argparse.ArgumentParser(description='simlib Creo runner (creoson/creopyson)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('ensure')
    sub.add_parser('smoke')
    p = sub.add_parser('open'); p.add_argument('--f', required=True); p.add_argument('--d', required=True)
    p = sub.add_parser('export-step'); p.add_argument('--n', required=True); p.add_argument('--d', required=True)
    p = sub.add_parser('params')
    p.add_argument('--list', action='store_true'); p.add_argument('--set')
    p.add_argument('--f'); p.add_argument('--regen', action='store_true')
    p = sub.add_parser('dims')
    p.add_argument('--list', action='store_true'); p.add_argument('--set')
    p.add_argument('--f'); p.add_argument('--regen', action='store_true')
    p = sub.add_parser('mass').add_argument('--f')
    p = sub.add_parser('kill')
    p = sub.add_parser('otk-api')
    p.add_argument('--m', required=True, help='方法名片段（不区分大小写）')
    p.add_argument('--class', dest='cls', help='限定类名子串（如 pfcSession）')
    p.add_argument('--dump', action='store_true', help='打印命中类的全部方法描述符')
    a = ap.parse_args()

    if a.cmd in ('kill', 'otk-api'):   # 离线子命令：不需要 creoson/Creo 在跑
        if a.cmd == 'kill':
            killed = kill_creo()
            print('killed:', killed or '(无残留)')
            print('CREO-KILL-DONE （链路下次调用会自动重拉无头实例）')
        else:
            for cls, sigs in otk_api_lookup(a.m, class_hint=a.cls, dump=a.dump):
                print('== %s' % cls)
                if sigs:
                    for s in sigs[:40]:
                        print('   ', s.replace('\n', ' ')[:110])
            print('CREO-APISIG-DONE')
        return

    cc = CreoClient()
    if a.cmd == 'ensure':
        print('CREO-ENSURE-DONE server+creo running=%s' % cc.c.is_creo_running())
    elif a.cmd == 'smoke':
        cc.open_part(os.path.basename(DEMO_PRT), os.path.dirname(DEMO_PRT))
        act = cc.active()
        assert 'd5_endplate' in act, 'active=%r' % act
        sz = cc.export_step('smk_cli', r'D:\temp\cad_creo_work\smoke')
        mp = cc.mass_props()
        print('active=%s step=%dB volume=%s' % (act, sz, mp.get('volume', mp)))
        print('CREO-SMOKE-DONE')
    elif a.cmd == 'open':
        cc.open_part(a.f, a.d)
        print('CREO-OPEN-DONE active=%s' % cc.active())
    elif a.cmd == 'export-step':
        sz = cc.export_step(a.n, a.d)
        print('CREO-EXPORT-DONE %d bytes' % sz)
    elif a.cmd == 'params':
        if a.set:
            kv = {}
            for part in str(a.set).split(','):
                k, _, v = part.partition('=')
                kv[k.strip()] = float(v) if '.' in v or v.lstrip('-').isdigit() else v.strip()
            cc.set_params(kv, file_=a.f, regen=a.regen)
            print('CREO-SET-DONE %s' % kv)
        else:
            for k, v in sorted(cc.list_params(file_=a.f).items()):
                print('  %-24s = %s' % (k, v))
            print('CREO-PARAMS-DONE')
    elif a.cmd == 'dims':
        if a.set:
            kv = {}
            for part in str(a.set).split(','):
                k, _, v = part.partition('=')
                kv[k.strip()] = float(v)
            cc.set_dims(kv, file_=a.f, regen=a.regen)
            print('CREO-SET-DONE %s' % kv)
        else:
            for k, v in sorted(cc.list_dims(file_=a.f).items()):
                print('  %-24s = %s' % (k, v))
            print('CREO-DIMS-DONE')
    elif a.cmd == 'mass':
        mp = cc.mass_props()
        print('volume=%s mass=%s surf=%s' % (mp.get('volume'), mp.get('mass'), mp.get('surface_area')))
        print('CREO-MASS-DONE')


if __name__ == '__main__':
    _cli()
