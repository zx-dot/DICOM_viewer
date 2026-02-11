# -*- coding: utf-8 -*-
"""
ViewModel 层：连接 Model 与 View，暴露状态与命令，驱动 UI 更新。
- MainViewModel：主界面状态与 DICOM/3D 业务逻辑，通过信号通知 View 刷新。
"""

from .main_view_model import MainViewModel

__all__ = ["MainViewModel"]
