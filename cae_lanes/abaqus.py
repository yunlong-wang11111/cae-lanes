# -*- coding: utf-8 -*-
"""
simlib.abaqus —— Abaqus 2022 批处理链的编排层封装
规格来源: an internal abaqus-automation handbook (2026-10-07)

角色定位(手册 §6 四段式契约): **造命令 + 判日志 + 静态护栏**。
不重造 gen/run/extract/analyze 的既有脚本(它们是真规格), 本模块负责:
  [x] 四段命令构建(gen/run/extract/analyze), 统一 RunSpec
  [x] 日志文本判定, 不信 rc(§5.1: abaqus.bat 与 abaqus python 出错都 rc=0)
  [x] py2.7 静态检查: extract 侧脚本禁 flush= 与非 ASCII print(§5.2/5.3)
  [x] 磁盘护栏: 运行根必须在 D:\\temp\\abaqus_batch 且启动前查可用空间(§5.5, odb 150-330MB/卡)
  [x] tags 不带引号(§3.3); 判据只写关键词不写产物路径(§4.2)

⚠ 求解必须走 quest 车道(§2.4: 沙箱里 WMI 被拒必死)。本模块的 execute() 只应在
  quest 节点进程内调用; 在 AI 会话里请把 spec.cmd 交给 quest_run 派发。
"""
import os
import re
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
DEFAULT_WS_ROOT = _cfg.ABAQUS_WS_ROOT or '.'
DEFAULT_RUN_ROOT = _cfg.ABAQUS_RUN_ROOT
DEFAULT_PY3 = r'E:\python_env\pinn\Scripts\python.exe'
DEFAULT_ABAQUS_BAT = r'D:\SIMULIA\Commands\abaqus.bat'

# 手册 §4.1 判据词表(节选常用的; 脚本可自带覆盖)
KEYWORDS = {
    'run': ['RUNS-COMPLETED'],
    'run_failed': ['RUNS-FAILED'],
    'carrier': ['CARRIER-SOLVE-ALL-OK'],
    'datacheck': ['SHAPE-DATACHECK-OK', 'DATACHECK-OK'],
    'extract_palm': ['PALM-EXTRACT-DONE'],
    'extract_scale': ['SCALE-EXTRACT-DONE'],
    'gen': ['GEN-GEOM-DECKS-OK', 'GEN-PALM-DECKS-OK', 'GEN-B2-DECKS-OK', 'GEN-SCALE-DECKS-OK'],
}

ABAQUS_ERROR_MARKERS = ['Abaqus Error', 'Traceback (most recent call last)', 'getWMI']


class AbaqusLibError(RuntimeError):
    pass


def _tags_arg(tags):
    """tags 归一: 接受 str/list, 返回不带引号的逗号串(§3.3 Windows 引号会被当字面量)。"""
    if isinstance(tags, str):
        tags = [t for t in tags.split(',') if t.strip()]
    tags = [str(t).strip() for t in tags]
    for t in tags:
        if not re.match(r'^[A-Za-z0-9_.\-]+$', t):
            raise AbaqusLibError('tag 含非法字符(引号/空格会毁了 --tags): %r' % t)
    return ','.join(tags)


class RunSpec(dict):
    """统一命令规格: cmd(list)/cmd_str/cwd/success_keywords/notes。"""

    @property
    def quest_hint(self):
        return 'quest_run: success 只写关键词 %s(不写产物路径), cwd=%s' % (
            self['success_keywords'], self['cwd'])


class AbaqusBatch(object):
    def __init__(self, ws_root=DEFAULT_WS_ROOT, run_root=DEFAULT_RUN_ROOT,
                 py3=DEFAULT_PY3, abaqus_bat=DEFAULT_ABAQUS_BAT):
        self.ws_root = ws_root
        self.batch_dir = os.path.join(ws_root, 'abaqus_batch')
        self.run_root = run_root
        self.py3 = py3
        self.abaqus_bat = abaqus_bat
        for p, what in ((self.batch_dir, 'abaqus_batch 目录'),
                        (self.py3, 'py3 解释器'), (self.abaqus_bat, 'abaqus.bat')):
            if not os.path.exists(p):
                raise AbaqusLibError('找不到 %s: %s' % (what, p))

    # ── 护栏 1: py2.7 静态检查(§5.2/5.3) ─────────────────────────────
    def py27_static_check(self, script):
        """扫描 extract 侧脚本: flush= 与 print 行里的非 GBK 字符。
        返回问题列表(空=通过)。注: 注释里的非 ASCII 无害, 只查 print(...) 括号内。"""
        path = script if os.path.isabs(script) else os.path.join(self.batch_dir, script)
        issues = []
        with open(path, encoding='utf-8', errors='replace') as fh:
            for i, L in enumerate(fh, 1):
                if 'flush=' in L:
                    issues.append('%s:%d flush= 在 abaqus python(2.7) 是 TypeError/语法错: %s'
                                  % (os.path.basename(path), i, L.strip()[:80]))
                m = re.search(r'print\s*\(?.*?[\'"]([^\'"]*)', L)
                if m and any(ord(c) > 127 for c in m.group(1)):
                    issues.append('%s:%d print 里含非 ASCII(GBK 车道会当场杀运行): %s'
                                  % (os.path.basename(path), i, L.strip()[:80]))
        return issues

    # ── 护栏 2: 磁盘(§5.5) ───────────────────────────────────────────
    def disk_ok(self, min_free_gb=20.0):
        import shutil as _sh
        total, used, free = _sh.disk_usage(self.run_root[:3])
        free_gb = free / 2 ** 30
        return free_gb >= min_free_gb, free_gb

    # ── 护栏 3: 日志文本判定(§5.1, rc 不可信) ────────────────────────
    @staticmethod
    def judge_log(text, success_keywords):
        """返回 (verdict, found)。verdict: 'ok'|'failed'|'unknown'。
        规则: 命中 success 词 = ok; 未命中但出现 Abaqus Error/Traceback = failed; 其余 unknown。"""
        found = [k for k in success_keywords if k in text]
        if found:
            return 'ok', found
        if any(m in text for m in ABAQUS_ERROR_MARKERS):
            return 'failed', []
        return 'unknown', []

    # ── 四段式命令构建(§6) ───────────────────────────────────────────
    def build_gen(self, script='gen_palm_geom.py', args=None, keywords=None):
        args = list(args or [])
        kw = keywords or KEYWORDS['gen']
        return RunSpec(cmd=[self.py3, os.path.join(self.batch_dir, script)] + args,
                       cwd=self.ws_root, success_keywords=kw,
                       notes='造卡: 纯 py3 秒级; DECKS 单位 cm, 跨距须为 h/2 整数倍(§3.1)')

    def build_run(self, runner='run_palm_geom.py', tags=None, slots=None,
                  cpus=None, mem_floor_gb=None, keywords=None):
        """求解段。⚠ 必须经 quest 派发(沙箱 WMI 必死, §2.4)。"""
        cmd = [self.py3, os.path.join(self.batch_dir, runner)]
        if tags:
            cmd += ['--tags', _tags_arg(tags)]
        if slots:
            cmd += ['--slots', str(int(slots))]
        if cpus:
            cmd += ['--cpus', str(int(cpus))]
        if mem_floor_gb:
            cmd += ['--mem_floor_gb', str(int(mem_floor_gb))]
        kw = keywords or KEYWORDS['run'] + KEYWORDS['run_failed']
        ok, free_gb = self.disk_ok()
        if not ok:
            raise AbaqusLibError('运行根磁盘不足 %.1f GB(当前 %.1f)——odb 150-330MB/卡, 先清理'
                                 % (20.0, free_gb))
        return RunSpec(cmd=cmd, cwd=self.ws_root, success_keywords=kw,
                       notes='求解: 走 quest 车道; 判定看 RUNS-COMPLETED(出现 RUNS-FAILED 即败)')

    def build_extract(self, tags=None, script='extract_fields.py', prefix='',
                      keywords=None):
        """抽取段: 经 run_extract.py 包装器(quest 白名单友好 + 日志落盘)。"""
        cmd = [self.py3, os.path.join(self.batch_dir, 'run_extract.py'),
               '--script', script]
        if prefix:
            cmd += ['--prefix', prefix]
        if tags:
            cmd += ['--tags', _tags_arg(tags)]
        else:
            cmd += ['--all']
        kw = keywords or (KEYWORDS['extract_palm'] if 'palm' in script
                          else KEYWORDS['extract_scale'])
        issues = self.py27_static_check(script)
        if issues:
            raise AbaqusLibError('extract 脚本未过 py2.7 静态检查:\n' + '\n'.join(issues))
        return RunSpec(cmd=cmd, cwd=self.ws_root, success_keywords=kw,
                       notes='抽取: abaqus python 2.7 由包装器接管; rc 不可信, 包装器已读日志')

    def build_analyze(self, harness, args=None, keywords=None):
        args = list(args or [])
        if not keywords:
            base = os.path.splitext(os.path.basename(harness))[0].upper()
            keywords = ['%s-DONE' % base.replace('_', '-')]
        return RunSpec(cmd=[self.py3, os.path.join(self.batch_dir, 'ml', harness)] + args,
                       cwd=self.ws_root, success_keywords=keywords,
                       notes='分析: 纯 py3 零 Abaqus; 新臂加进已认证 harness, 默认严格 no-op(§3.4)')

    # ── 执行(仅限 quest 节点进程内调用) ─────────────────────────────
    def execute(self, spec, timeout=7200):
        """跑一个 spec 并按日志文本判定(不信 rc)。返回 {verdict, keywords, rc, tail}。"""
        t0 = time.time()
        pr = subprocess.run(spec['cmd'], cwd=spec['cwd'],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
        text = (pr.stdout or '') + '\n' + (pr.stderr or '')
        verdict, found = self.judge_log(text, spec['success_keywords'])
        tail = '\n'.join(text.splitlines()[-40:])
        return dict(verdict=verdict, keywords=found, rc=pr.returncode,
                    seconds=time.time() - t0, tail=tail)
