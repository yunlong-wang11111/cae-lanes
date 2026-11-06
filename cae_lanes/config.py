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

# ── view3d（手机 3D 查看器投递链路） ─────────────────────
VIEW3D_ROOT = _p('CAE_VIEW3D_ROOT', r'D:\view3d')   # view3d-server.py 根目录
VIEW3D_PORT = int(_p('CAE_VIEW3D_PORT', '8178'))

# ── PanaParaMesher（并行四面体网格细化, parallel_tetmesh） ─
# 安装记录见 D:\parallel_tetmesh\parallel_tetmesh\BUILD_NOTES.md
PANA_ROOT = _p('CAE_PANA_ROOT', r'D:\parallel_tetmesh\parallel_tetmesh')
PANA_BIN = os.path.join(PANA_ROOT, 'sdk', 'win64', '2017', 'Release')
PANA_EXE = os.path.join(PANA_BIN, 'PanaPara.exe')
PANA_READ_EXE = os.path.join(PANA_BIN, 'ResultRead.exe')
PANA_MPIEXEC = _p('CAE_PANA_MPIEXEC', 'mpiexec')   # 须在 PATH(MS-MPI)
# 工作根必须 ASCII：PanaPara 内部窄字符路径, 中文路径会 mojibake
PANA_WORK_ROOT = _p('CAE_PANA_WORK', r'D:\panamesh')
