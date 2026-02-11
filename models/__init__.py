# -*- coding: utf-8 -*-
"""
Model 层：应用核心数据与领域对象。
- AppState：全局应用状态（光标、窗宽窗位、体数据引用等）
- DicomVolume：DICOM 体数据封装（数组、间距、来源路径）
"""

from .app_state import AppState
from .dicom_volume import DicomVolume

__all__ = ["AppState", "DicomVolume"]
