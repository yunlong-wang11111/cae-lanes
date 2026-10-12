# -*- coding: utf-8 -*-
"""cae-lanes 机器指纹配置：全部可用环境变量覆盖（CAE_* 前缀）。

本文件默认值对应"参考装机"（Windows + 三家软件默认盘符布局）。换机器时：
  ① 改这里，或 ② 设环境变量（优先），如 CAE_COMSOL_ROOT=D:/COMSOL/Multiphysics。
路径一律正斜杠或双反斜杠；不要以反斜杠结尾。
"""
import os

def _p(key, default):
    v = os.environ.get(key)
    return v if v else default

# ── COMSOL ─────────────────────────────────────────────
COMSOL_ROOT = _p('CAE_COMSOL_ROOT', r'D:\COMSOL64\Multiphysics')
COMSOL_BATCH = os.path.join(COMSOL_ROOT, 'bin', 'win64', 'comsolbatch.exe')
COMSOL_JAVAC = os.path.join(COMSOL_ROOT, 'java', 'win64', 'jre', 'bin', 'javac.exe')
COMSOL_PLUGINS = os.path.join(COMSOL_ROOT, 'plugins', '*')
COMSOL_WORKDIR = _p('CAE_COMSOL_WORKDIR', r'D:\comsol_work')

# ── Abaqus ─────────────────────────────────────────────
ABAQUS_WS_ROOT = _p('CAE_ABAQUS_WS', '')        # 你的 abaqus_batch 工作区根（造卡/runner 所在）
ABAQUS_RUN_ROOT = _p('CAE_ABAQUS_RUN', r'D:\temp\abaqus_batch')  # 求解运行根（odb 落盘处, 大盘!）
ABAQUS_PY3 = _p('CAE_PY3', r'D:\python\python.exe')              # 分析侧 Python3
ABAQUS_TORCH_PY3 = _p('CAE_TORCH_PY3', '')                       # 含 torch 的 Python3（可空）

# ── Creo（creoson 链路） ────────────────────────────────
CREO_ROOT = _p('CAE_CREO_ROOT', r'D:\PTC\Creo 12.4.0.0')
CREO_EXE = _p('CAE_CREO_EXE', os.path.join(CREO_ROOT, 'Parametric', 'bin', 'parametric.exe'))
CREO_COMMON = os.path.join(CREO_ROOT, 'Common Files')
CREO_OTK_JAR = os.path.join(CREO_COMMON, 'text', 'java', 'otk.jar')
CREOSON_DIR = _p('CAE_CREOSON_DIR', os.path.join(os.path.expanduser('~'), 'dsh-plugins', 'creoson'))
CREOSON_PORT = int(_p('CAE_CREOSON_PORT', '9056'))
