# -*- coding: utf-8 -*-
"""
MPR 切片视图（View）。
仅负责展示与交互：滚轮切层、左键设十字光标、右键拖拽调窗宽窗位；
数据与坐标换算均由 ViewModel 提供。
"""

from typing import TYPE_CHECKING, Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt, QPoint, QPointF, QSize
from PySide6.QtGui import QMouseEvent, QWheelEvent, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QSizePolicy

if TYPE_CHECKING:
    from viewmodels.main_view_model import MainViewModel


class SliceView(QFrame):
    """
    单个 2D 切片视图（轴状位/冠状位/矢状位）。
    - 通过 ViewModel 获取带十字线的 QImage 并显示
    - 滚轮：更新当前层号并请求 ViewModel 刷新图像
    - 左键点击：将屏幕坐标交给 ViewModel 反算体素并设置光标，触发联动
    - 右键拖拽：通知 ViewModel 更新窗宽窗位
    """

    def __init__(
        self,
        title: str,
        orientation: str,
        view_model: "MainViewModel",
        parent=None,
    ):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName(f"SliceView-{orientation}")

        self._orientation = orientation
        self._view_model = view_model
        self._current_index: int = 0
        # 显示区域与切片尺寸，用于点击时屏幕坐标 -> 体素坐标
        self._display_origin = QPoint(0, 0)
        self._display_size = QSize(1, 1)
        self._img_shape_hw: tuple = (0, 0)  # (height, width) 当前切片图像尺寸
        self._drawing: bool = False  # 阶段 4：画笔模式下是否正在拖拽

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(self._title_label)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setScaledContents(True)
        self._image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self._image_label, 1)

    @property
    def orientation(self) -> str:
        return self._orientation

    @property
    def current_index(self) -> int:
        return self._current_index

    @current_index.setter
    def current_index(self, value: int):
        self._current_index = value

    def set_volume_loaded(self) -> None:
        """体数据加载后由 MainWindow 调用：用当前光标初始化层号并刷新显示。"""
        self._current_index = self._view_model.get_initial_slice_index(self._orientation)
        self._refresh_display()

    def refresh_from_cursor(self) -> None:
        """光标变化时由 MainWindow 调用：用 ViewModel 当前光标同步本视图层号并刷新。"""
        z, y, x = self._view_model.get_current_cursor_slice_indices()
        if self._orientation == "axial":
            self._current_index = z
        elif self._orientation == "coronal":
            self._current_index = y
        else:
            self._current_index = x
        self._refresh_display()

    def refresh_display(self) -> None:
        """窗宽窗位或数据变化时由 MainWindow 调用：仅重绘当前层。"""
        self._refresh_display()

    def _refresh_display(self) -> None:
        """从 ViewModel 获取当前朝向、当前层的展示图并更新 Label。"""
        if self._view_model.volume is None:
            self._image_label.clear()
            self._image_label.setText("未加载数据")
            return

        label_w = max(self._image_label.size().width(), 1)
        label_h = max(self._image_label.size().height(), 1)
        qimg = self._view_model.get_slice_display_image(
            self._orientation,
            self._current_index,
            (label_h, label_w),
        )
        if qimg is None:
            return
        self._img_shape_hw = (qimg.height(), qimg.width())
        self._image_label.setPixmap(QPixmap.fromImage(qimg))
        self._display_origin = QPoint(0, 0)
        self._display_size = QSize(label_w, label_h)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """滚轮：在当前朝向上切换层号并刷新。"""
        if self._view_model.volume is None:
            return
        delta = event.angleDelta().y()
        step = 1 if delta > 0 else -1
        lo, hi = self._view_model.get_slice_index_range(self._orientation)
        self._current_index = max(lo, min(hi, self._current_index + step))
        self._refresh_display()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键：画笔模式下开始绘制；选择模式下设十字光标。右键：记录起点用于窗宽窗位拖拽。"""
        if event.button() == Qt.LeftButton and self._view_model.volume is not None:
            if self._view_model.get_tool() == "brush":
                self._drawing = True
                self._on_brush_draw(event.position())
            else:
                self._on_left_click(event.position())
            return
        if event.button() == Qt.LeftButton:
            self._drawing = False
        if event.button() == Qt.RightButton:
            self._last_right_pos = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """左键释放：结束画笔拖拽。"""
        if event.button() == Qt.LeftButton:
            self._drawing = False
        super().mouseReleaseEvent(event)

    def _pos_in_image_label(self, pos: QPointF) -> Tuple[float, float, int, int]:
        """
        将 SliceView 内的点击坐标转换为图像 Label 内的坐标及 Label 尺寸。
        因图像在标题下方的 _image_label 内，必须用其相对坐标与尺寸，否则十字线/标注会偏下。
        返回 (local_x, local_y, label_w, label_h)，若不在 Label 内则 label_w/label_h 为 0。
        """
        p = self._image_label.mapFrom(self, QPoint(int(pos.x()), int(pos.y())))
        local_x = p.x()
        local_y = p.y()
        label_w = max(self._image_label.width(), 1)
        label_h = max(self._image_label.height(), 1)
        return local_x, local_y, label_w, label_h

    def _on_left_click(self, pos: QPointF) -> None:
        """左键点击（选择模式）：将坐标换算到图像 Label 内再反算体素，避免标题栏导致偏下。"""
        local_x, local_y, label_w, label_h = self._pos_in_image_label(pos)
        if local_x < 0 or local_y < 0 or local_x >= label_w or local_y >= label_h:
            return
        vox = self._view_model.screen_to_voxel(
            self._orientation,
            self._current_index,
            local_x,
            local_y,
            label_w,
            label_h,
            self._img_shape_hw,
        )
        if vox is not None:
            self._view_model.set_cursor(*vox)

    def _on_brush_draw(self, pos: QPointF) -> None:
        """画笔模式：将坐标换算到图像 Label 内再交给 ViewModel 画圆，避免标注偏下。"""
        local_x, local_y, label_w, label_h = self._pos_in_image_label(pos)
        if local_x < 0 or local_y < 0 or local_x >= label_w or local_y >= label_h:
            return
        self._view_model.draw_on_mask(
            self._orientation,
            self._current_index,
            local_x,
            local_y,
            label_w,
            label_h,
            self._img_shape_hw,
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """右键拖拽：更新窗宽窗位。左键拖拽（画笔模式）：连续在 Mask 上绘制。"""
        if event.buttons() & Qt.RightButton:
            if not hasattr(self, "_last_right_pos"):
                self._last_right_pos = event.position()
            delta = event.position() - self._last_right_pos
            self._last_right_pos = event.position()
            ww = self._view_model.app_state.window_width
            wl = self._view_model.app_state.window_level
            ww = int(np.clip(ww + delta.x() * 4.0, 200, 3000))
            wl = int(np.clip(wl - delta.y() * 4.0, -1000, 1000))
            self._view_model.set_window(ww, wl)
            event.accept()
            return
        if (event.buttons() & Qt.LeftButton) and getattr(self, "_drawing", False) and self._view_model.get_tool() == "brush":
            self._on_brush_draw(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)
