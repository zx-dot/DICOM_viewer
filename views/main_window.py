# -*- coding: utf-8 -*-
"""
主窗口（View）。
仅负责布局、菜单、右侧面板、3D 窗口与 ViewModel 的绑定；
业务逻辑与数据均由 ViewModel 提供。
"""

from pathlib import Path
from typing import TYPE_CHECKING

import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QAction

from views.slice_view import SliceView

if TYPE_CHECKING:
    from viewmodels.main_view_model import MainViewModel


# 深色医疗主题 QSS（与需求文档配色一致）
STYLESHEET = """
QMainWindow { background-color: #1E1E2E; color: #E0E0E0; }
QLabel { color: #E0E0E0; }
QFrame { background-color: #252535; border: 1px solid #303040; }
QToolBar { background-color: #1E1E2E; border: none; }
QToolButton { color: #A0A0B0; padding: 6px; }
QToolButton:hover { background-color: #2E2E40; color: #E0E0E0; }
QToolButton:checked { background-color: #3A86FF; color: #FFFFFF; }
QSlider::groove:horizontal, QSlider::groove:vertical {
    background: #303040; height: 6px;
}
QSlider::handle:horizontal, QSlider::handle:vertical {
    background: #3A86FF; width: 12px; border-radius: 6px;
}
QPushButton {
    background-color: #3A86FF; color: white; border-radius: 4px; padding: 4px 10px;
}
QPushButton:hover { background-color: #2563EB; }
"""


class MainWindow(QMainWindow):
    """
    主窗口 View。
    - 左侧工具栏、中间 2x2 视图（三 MPR + 3D）、右侧患者信息与窗宽窗位
    - 通过 ViewModel 加载 DICOM、获取患者信息、刷新切片与 3D
    """

    def __init__(self, view_model: "MainViewModel", parent=None):
        super().__init__(parent)
        self._view_model = view_model
        self.setWindowTitle("医疗影像浏览系统 - AirwayLesion-Seg")
        self.resize(1280, 720)
        self.setStyleSheet(STYLESHEET)

        # 菜单
        self._create_menu()
        # 中央：左侧工具栏 + 中间 2x2 + 右侧面板
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        left_toolbar = self._create_side_toolbar()
        left_toolbar.setFixedWidth(60)
        main_layout.addWidget(left_toolbar)

        center_widget, self._axial_view, self._coronal_view, self._sagittal_view, self._view_3d, self._pv_interactor = self._create_center_views()
        main_layout.addWidget(center_widget, 1)

        right_panel = self._create_right_panel()
        right_panel.setFixedWidth(280)
        main_layout.addWidget(right_panel)

        status = QStatusBar()
        status.setStyleSheet("color: #E0E0E0; background-color: #151521;")
        self.setStatusBar(status)
        self.statusBar().showMessage("就绪")

        # 绑定 ViewModel 信号
        self._view_model.volume_loaded.connect(self._on_volume_loaded)
        self._view_model.cursor_changed.connect(self._on_cursor_changed)
        self._view_model.window_changed.connect(self._on_window_changed)
        self._view_model.patient_info_changed.connect(self._on_patient_info_changed)
        self._view_model.status_message.connect(self.statusBar().showMessage)
        self._view_model.mask_changed.connect(self._on_mask_changed)

    def _create_menu(self) -> None:
        """构建顶部菜单栏。"""
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件")
        open_action = QAction("打开 DICOM 目录", self)
        open_action.triggered.connect(self._on_open_dicom)
        file_menu.addAction(open_action)
        open_model_action = QAction("导入 3D 模型", self)
        open_model_action.triggered.connect(self._on_open_3d_model)
        file_menu.addAction(open_model_action)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        menu_bar.addMenu("视图")
        tools_menu = menu_bar.addMenu("工具")
        airway_action = QAction("气道分割", self)
        airway_action.triggered.connect(self._on_segment_airway)
        tools_menu.addAction(airway_action)
        help_menu = menu_bar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_side_toolbar(self) -> QWidget:
        """左侧竖向工具栏：选择 / 标注（画笔）可切换，其余占位。"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        toolbar = QToolBar()
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setIconSize(QSize(18, 18))
        # 阶段 4：选择 / 标注 为可勾选，互斥
        self._action_select = QAction("选择", self)
        self._action_select.setCheckable(True)
        self._action_select.setChecked(True)
        self._action_select.triggered.connect(lambda: self._on_tool_triggered("select"))
        toolbar.addAction(self._action_select)
        self._action_brush = QAction("标注", self)
        self._action_brush.setCheckable(True)
        self._action_brush.triggered.connect(lambda: self._on_tool_triggered("brush"))
        toolbar.addAction(self._action_brush)
        for text in ("平移", "缩放", "窗宽窗位", "3D"):
            toolbar.addAction(QAction(text, self))
        layout.addWidget(toolbar)
        layout.addStretch(1)
        return container

    def _on_tool_triggered(self, tool: str) -> None:
        """左侧工具栏「选择」/「标注」切换：更新 ViewModel 工具并保持互斥勾选。"""
        self._view_model.set_tool(tool)
        self._action_select.setChecked(tool == "select")
        self._action_brush.setChecked(tool == "brush")

    def _create_center_views(self) -> tuple:
        """中间 2x2 网格：轴状位、冠状位、矢状位、3D。返回 (center_widget, axial, coronal, sagittal, view_3d_frame, pv_interactor)。"""
        center_widget = QWidget()
        grid = QGridLayout(center_widget)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setSpacing(2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        axial_view = SliceView("轴状位", "axial", self._view_model)
        coronal_view = SliceView("冠状位", "coronal", self._view_model)
        sagittal_view = SliceView("矢状位", "sagittal", self._view_model)

        view_3d = QFrame()
        view_3d.setFrameShape(QFrame.StyledPanel)
        view_3d_layout = QVBoxLayout(view_3d)
        view_3d_layout.setContentsMargins(4, 4, 4, 4)
        label_3d = QLabel("3D重建")
        label_3d.setStyleSheet("color: #ffffff; font-weight: bold;")
        view_3d_layout.addWidget(label_3d)
        pv_interactor = QtInteractor(view_3d)
        view_3d_layout.addWidget(pv_interactor, 1)

        pv.global_theme.background = "black"
        if hasattr(pv.global_theme, "floor"):
            pv.global_theme.floor = False  # type: ignore[assignment]
        if hasattr(pv.global_theme, "show_edges"):
            pv.global_theme.show_edges = False  # type: ignore[assignment]
        try:
            pv_interactor.set_background("black")
        except Exception:
            pass

        grid.addWidget(axial_view, 0, 0)
        grid.addWidget(coronal_view, 0, 1)
        grid.addWidget(sagittal_view, 1, 0)
        grid.addWidget(view_3d, 1, 1)

        return center_widget, axial_view, coronal_view, sagittal_view, view_3d, pv_interactor

    def _create_right_panel(self) -> QWidget:
        """右侧面板：患者信息、窗宽窗位滑条、标记设置、保存按钮。"""
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        title = QLabel("患者信息")
        title.setStyleSheet("color: #ffffff; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self._label_patient_name = QLabel("-")
        self._label_patient_id = QLabel("-")
        self._label_study_date = QLabel("-")
        self._label_modality = QLabel("-")
        form.addRow("姓名:", self._label_patient_name)
        form.addRow("编号:", self._label_patient_id)
        form.addRow("检查日期:", self._label_study_date)
        form.addRow("检查类型:", self._label_modality)
        layout.addLayout(form)

        wl_title = QLabel("窗宽窗位")
        wl_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        layout.addWidget(wl_title)
        self._slider_ww = QSlider(Qt.Horizontal)
        self._slider_ww.setMinimum(200)
        self._slider_ww.setMaximum(3000)
        self._slider_ww.setValue(1500)
        self._slider_ww.valueChanged.connect(self._on_slider_window_changed)
        self._slider_wl = QSlider(Qt.Horizontal)
        self._slider_wl.setMinimum(-1000)
        self._slider_wl.setMaximum(1000)
        self._slider_wl.setValue(-600)
        self._slider_wl.valueChanged.connect(self._on_slider_window_changed)
        layout.addWidget(QLabel("窗宽 (W)"))
        layout.addWidget(self._slider_ww)
        layout.addWidget(QLabel("窗位 (L)"))
        layout.addWidget(self._slider_wl)

        anno_title = QLabel("标记设置")
        anno_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        layout.addWidget(anno_title)
        self._slider_brush_size = QSlider(Qt.Horizontal)
        self._slider_brush_size.setMinimum(1)
        self._slider_brush_size.setMaximum(20)
        self._slider_brush_size.setValue(5)
        self._slider_brush_size.valueChanged.connect(self._on_brush_size_changed)
        layout.addWidget(QLabel("画笔大小"))
        layout.addWidget(self._slider_brush_size)
        # 阶段 4：标注层叠加透明度
        self._slider_overlay_opacity = QSlider(Qt.Horizontal)
        self._slider_overlay_opacity.setMinimum(0)
        self._slider_overlay_opacity.setMaximum(100)
        self._slider_overlay_opacity.setValue(50)
        self._slider_overlay_opacity.valueChanged.connect(self._on_overlay_opacity_changed)
        layout.addWidget(QLabel("透明度"))
        layout.addWidget(self._slider_overlay_opacity)
        layout.addStretch(1)
        layout.addWidget(QPushButton("保存"))
        return panel

    # ---------- 菜单与滑条槽 ----------

    def _on_open_dicom(self) -> None:
        """菜单「打开 DICOM 目录」：选目录后交给 ViewModel 加载。"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择 DICOM 目录")
        if not dir_path:
            return
        ok = self._view_model.load_dicom_directory(Path(dir_path))
        if not ok:
            QMessageBox.critical(self, "错误", "加载 DICOM 失败，请查看状态栏或控制台。")

    def _on_segment_airway(self) -> None:
        """阶段 5：运行气道分割，将 Binary Mask 转为 3D Mesh 并以青色显示在 3D 视图中。"""
        result = self._view_model.build_airway_mesh()
        if result is None:
            QMessageBox.warning(self, "提示", "未加载 CT 或气道分割失败，请先加载 DICOM 序列。")
            return
        mesh, color, opacity = result
        self._pv_interactor.clear()
        self._pv_interactor.set_background("black")
        self._pv_interactor.add_mesh(mesh, color=color, opacity=opacity)
        self._pv_interactor.reset_camera()
        self.statusBar().showMessage("气道分割完成，已显示 3D 气道模型（青色）")

    def _on_open_3d_model(self) -> None:
        """菜单「导入 3D 模型」：选文件后由 ViewModel 解析并在 3D 窗口显示。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 3D 模型文件", "",
            "3D 模型 (*.stl *.obj *.ply *.vtp);;所有文件 (*.*)",
        )
        if not file_path:
            return
        result = self._view_model.load_3d_model_file(file_path)
        if result is None:
            QMessageBox.critical(self, "错误", "加载 3D 模型失败。")
            return
        mesh, color, opacity = result
        self._pv_interactor.clear()
        self._pv_interactor.set_background("black")
        self._pv_interactor.add_mesh(mesh, color=color, opacity=opacity)
        self._pv_interactor.reset_camera()
        self.statusBar().showMessage(f"已加载 3D 模型：{file_path}")

    def _on_slider_window_changed(self) -> None:
        """右侧窗宽/窗位滑条变化：同步到 ViewModel。"""
        ww = self._slider_ww.value()
        wl = self._slider_wl.value()
        self._view_model.set_window(ww, wl)

    def _on_brush_size_changed(self, value: int) -> None:
        """右侧「画笔大小」滑条：同步到 ViewModel（体素半径）。"""
        self._view_model.set_brush_radius(value)

    def _on_overlay_opacity_changed(self, value: int) -> None:
        """右侧「透明度」滑条：0~100 映射为 0.0~1.0，同步到 ViewModel 并刷新三视图。"""
        self._view_model.set_overlay_opacity(value / 100.0)
        self._sync_window_to_views()

    def _show_about(self) -> None:
        QMessageBox.information(
            self, "关于",
            "AirwayLesion-Seg\n\nCT 影像气道分割与病灶标注系统原型。\n采用 MVVM 架构。",
        )

    # ---------- ViewModel 信号槽 ----------

    def _on_volume_loaded(self) -> None:
        """体数据加载完成：三视图初始化层号并刷新，3D 更新，窗宽窗位同步到视图。"""
        self._axial_view.set_volume_loaded()
        self._coronal_view.set_volume_loaded()
        self._sagittal_view.set_volume_loaded()
        self._sync_window_to_views()
        self._update_3d_view()

    def _on_cursor_changed(self) -> None:
        """十字光标变化：三视图同步层号并刷新。"""
        self._axial_view.refresh_from_cursor()
        self._coronal_view.refresh_from_cursor()
        self._sagittal_view.refresh_from_cursor()

    def _on_window_changed(self) -> None:
        """窗宽窗位变化：三视图刷新，右侧滑条与 ViewModel 同步（避免循环）。"""
        ww, wl = self._view_model.sync_sliders_from_state()
        self._slider_ww.blockSignals(True)
        self._slider_wl.blockSignals(True)
        self._slider_ww.setValue(ww)
        self._slider_wl.setValue(wl)
        self._slider_ww.blockSignals(False)
        self._slider_wl.blockSignals(False)
        self._sync_window_to_views()

    def _on_mask_changed(self) -> None:
        """标注 Mask 变化（阶段 4）：三视图刷新以显示半透明红色 Overlay。"""
        self._axial_view.refresh_display()
        self._coronal_view.refresh_display()
        self._sagittal_view.refresh_display()

    def _sync_window_to_views(self) -> None:
        """用 ViewModel 当前窗宽窗位刷新三视图显示。"""
        self._axial_view.refresh_display()
        self._coronal_view.refresh_display()
        self._sagittal_view.refresh_display()

    def _on_patient_info_changed(self) -> None:
        """患者信息更新：右侧面板与状态栏。"""
        info = self._view_model.get_patient_info()
        self._label_patient_name.setText(info.get("name", "-"))
        self._label_patient_id.setText(info.get("patient_id", "-"))
        self._label_study_date.setText(info.get("study_date", "-"))
        self._label_modality.setText(info.get("modality", "CT"))
        st = info.get("slice_thickness", "?")
        kvp = info.get("kvp", "?")
        cur = info.get("tube_current", "?")
        self.statusBar().showMessage(f"层厚: {st} mm   电压: {kvp} kV   电流: {cur} mA")

    def _update_3d_view(self) -> None:
        """用 ViewModel 当前体数据更新 3D 窗口（等值面或体渲染）。"""
        result = self._view_model.build_3d_volume_actor()
        self._pv_interactor.clear()
        self._pv_interactor.set_background("black")
        if result is None:
            self._pv_interactor.add_text("未加载数据", color="white", font_size=10)
        elif result[0] == "clear":
            _, contour, color, opacity = result
            self._pv_interactor.add_mesh(contour, color=color, opacity=opacity)
        else:
            _, grid, cmap, opacity = result
            self._pv_interactor.add_volume(grid, cmap=cmap, opacity=opacity)
        self._pv_interactor.reset_camera()
