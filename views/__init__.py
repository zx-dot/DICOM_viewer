# -*- coding: utf-8 -*-
"""
View 层：纯 UI 展示与用户输入，通过 ViewModel 获取数据与执行命令。
- SliceView：单个 MPR 切片视图（轴状位/冠状位/矢状位）
- MainWindow：主窗口布局、菜单、右侧面板、3D 窗口，与 ViewModel 绑定
"""

from .slice_view import SliceView
from .main_window import MainWindow

__all__ = ["SliceView", "MainWindow"]
