# -*- coding: utf-8 -*-
"""
DICOM 体数据封装（Model）。
负责从 SimpleITK 图像中提取 3D 数组与元信息，不包含 UI 与业务编排。
"""

from pathlib import Path
from typing import Tuple

import numpy as np

# 仅类型检查时依赖 SimpleITK
try:
    import SimpleITK as sitk
except ImportError:
    sitk = None


class DicomVolume:
    """
    DICOM 体数据封装。
    - array 维度为 (Z, Y, X)，与 AppState.raw_image 一致
    - spacing 为 (x, y, z) 顺序，与 SimpleITK 一致
    """

    def __init__(self, image: "sitk.Image", directory: Path):
        self.image = image
        self.directory = directory
        # SimpleITK 读入为 (Z,Y,X)，与需求中 (Z,Y,X) 一致
        self.array = sitk.GetArrayFromImage(image)
        # spacing 在 ITK 中为 (x,y,z)，保持原样供 3D 显示使用
        self.spacing: Tuple[float, ...] = image.GetSpacing()

    @property
    def shape(self) -> Tuple[int, int, int]:
        """体数据形状 (Z, Y, X)。"""
        return self.array.shape
