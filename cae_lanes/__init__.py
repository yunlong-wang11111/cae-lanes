# -*- coding: utf-8 -*-
"""simlib: COMSOL/ABAQUS 已验证通路的封装库。
规格来源:
  COMSOL: aic_race\\out\\COMSOL-AI使用手册.md (含 2026-10-08 §9 增补)
  ABAQUS: piml_fingertip 工作区 HANDBOOK-abaqus-automation.md
验证状态: v1.0 双端 / v1.1a 有支管 2D(机器精度) / v1.1b 3D Port+S11(1e-9)
"""
from .comsol import Comsol2D, ComsolResult, ComsolError, k_comsol, read_comsol_csv  # noqa: F401
from .comsol3d import Comsol3D, Comsol3DResult  # noqa: F401
from .abaqus import AbaqusBatch, AbaqusLibError, RunSpec  # noqa: F401
