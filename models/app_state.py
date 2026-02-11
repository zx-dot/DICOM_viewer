# -*- coding: utf-8 -*-
"""
全局应用状态（Model）。
与需求文档中的 GlobalState 对应，供 ViewModel 读写，View 通过 ViewModel 间接访问。
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass
class AppState:
    """
    全局应用状态。
    - raw_image / mask_image：与体数据同尺寸，供 MPR 与标注使用
    - current_cursor：三视图联动的十字光标体素坐标 (z, y, x)
    - window_width / window_level：窗宽窗位，控制灰度显示
    """

    # 原始 CT 体数据，维度 (Z, Y, X)
    raw_image: Optional[np.ndarray] = None
    # 标注/分割掩膜，与 raw_image 同尺寸，0=背景 1=气道 2=病灶 等
    mask_image: Optional[np.ndarray] = None
    # 体素间距 (x, y, z)，来自 SimpleITK
    spacing: Optional[Tuple[float, float, float]] = None
    # 世界坐标原点 (x, y, z)
    origin: Optional[Tuple[float, float, float]] = None
    # 当前十字光标在体数据中的坐标 (z, y, x)
    current_cursor: Tuple[int, int, int] = (0, 0, 0)
    # 当前窗位（中心 HU）
    window_level: int = -600
    # 当前窗宽（HU 范围）
    window_width: int = 1500
