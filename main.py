import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import SimpleITK as sitk
import pydicom
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import QPoint, Qt, QSize
from PySide6.QtGui import (
    QAction,
    QMouseEvent,
    QWheelEvent,
    QPixmap,
    QImage,
    QPainter,
    QPen,
    QColor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QFrame,
    QFormLayout,
)


@dataclass
class AppState:
    """全局应用状态，参照需求文档中的定义."""

    raw_image: Optional[np.ndarray] = None  # (Z, Y, X)
    mask_image: Optional[np.ndarray] = None  # (Z, Y, X)
    spacing: Tuple[float, float, float] | None = None  # (z, y, x)
    origin: Tuple[float, float, float] | None = None
    current_cursor: Tuple[int, int, int] = (0, 0, 0)  # (z, y, x)
    window_level: int = -600
    window_width: int = 1500


class DicomVolume:
    """
    简单的 DICOM 体数据封装：
    - 使用 SimpleITK 读取 DICOM 序列
    - 暂存为 NumPy array 以及 spacing 信息
    """

    def __init__(self, image: sitk.Image, directory: Path):
        self.image = image
        self.directory = directory
        self.array = sitk.GetArrayFromImage(image)  # (D, H, W)
        self.spacing = image.GetSpacing()[::-1]  # (W_spacing, H_spacing, D_spacing) -> 这里仅示意

    @property
    def shape(self):
        # (D, H, W)
        return self.array.shape


class SliceView(QFrame):
    """
    单个 2D 视图窗口，用于显示某个方向的切片。
    - orientation: "axial" / "coronal" / "sagittal"
    - 支持滚轮切换当前层面
    """

    def __init__(self, title: str, orientation: str, app_state: AppState, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName(f"SliceView-{orientation}")

        self.orientation = orientation
        self.app_state = app_state
        self.volume: DicomVolume | None = None
        self.current_index: int = 0
        self.window_width: float = 1500
        self.window_level: float = -600

        # 记录当前图像在 label 中的显示区域，用于坐标换算
        self._display_origin: QPoint = QPoint(0, 0)
        self._display_size: QSize = QSize(1, 1)
        self._img_shape: tuple[int, int] = (0, 0)  # (h_img, w_img)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        layout.addWidget(self.title_label)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        # 让 QLabel 不再跟随 pixmap 大小无限放大，由布局控制大小
        self.image_label.setScaledContents(True)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.image_label, 1)

    # --- 公共接口 ---

    def set_volume(self, volume: DicomVolume):
        self.volume = volume
        # 根据全局光标位置初始化当前层面，默认使用体数据中心
        if self.app_state.raw_image is not None:
            z, y, x = self.app_state.current_cursor
            if self.orientation == "axial":
                self.current_index = int(np.clip(z, 0, volume.shape[0] - 1))
            elif self.orientation == "coronal":
                self.current_index = int(np.clip(y, 0, volume.shape[1] - 1))
            else:  # sagittal
                self.current_index = int(np.clip(x, 0, volume.shape[2] - 1))
        else:
            self.current_index = volume.shape[0] // 2
        self.update_view()

    def set_window(self, width: float, level: float):
        self.window_width = width
        self.window_level = level
        self.update_view()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.volume is None:
            return

        delta = event.angleDelta().y()
        step = 1 if delta > 0 else -1
        d, h, w = self.volume.shape

        if self.orientation == "axial":
            max_index = d - 1
        elif self.orientation == "coronal":
            max_index = h - 1
        else:
            max_index = w - 1

        self.current_index = int(np.clip(self.current_index + step, 0, max_index))
        self.update_view()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # 左键：更新全局十字光标位置
        if (
            event.button() == Qt.LeftButton
            and self.volume is not None
            and self.app_state.raw_image is not None
        ):
            self._update_cursor_from_mouse(event.position())
            # 使用顶层窗口对象，避免依赖 parent() 层级
            main_window = self.window()
            if hasattr(main_window, "update_all_views_from_cursor"):
                main_window.update_all_views_from_cursor()  # type: ignore[call-arg]
            return

        # 右键按下，记录初始位置用于窗宽窗位调整
        if event.button() == Qt.RightButton:
            self._last_right_pos = event.position()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # 右键拖动：调窗宽窗位
        if event.buttons() & Qt.RightButton:
            if not hasattr(self, "_last_right_pos"):
                self._last_right_pos = event.position()

            delta = event.position() - self._last_right_pos
            self._last_right_pos = event.position()

            # 水平调窗宽，垂直调窗位
            self.window_width = float(
                np.clip(self.window_width + delta.x() * 4.0, 200, 3000)
            )
            self.window_level = float(
                np.clip(self.window_level + delta.y() * -4.0, -1000, 1000)
            )

            # 更新全局状态，并通知主窗口同步滑条
            self.app_state.window_width = int(self.window_width)
            self.app_state.window_level = int(self.window_level)

            main_window: "MainWindow" = self.window()  # type: ignore[assignment]
            main_window.sync_window_sliders_from_state()
            main_window._sync_window_to_views()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def update_view(self):
        if self.volume is None:
            self.image_label.clear()
            self.image_label.setText("未加载数据")
            return

        arr = self.volume.array  # (D, H, W) -> (Z, Y, X)
        d, h, w = arr.shape

        # 取不同方向的切片，并做适当旋转 / 翻转，保证显示方向直观
        if self.orientation == "axial":
            # 轴位：Z 固定，显示 (Y, X)
            slice_img = arr[self.current_index, :, :]
        elif self.orientation == "coronal":
            # 冠状位：Y 固定，显示 (Z, X)，
            # 先按之前方式得到图像，再在此基础上向左旋转 90°
            slice_tmp = arr[:, self.current_index, :]
            slice_tmp = np.rot90(slice_tmp, k=1)  # 原来的显示
            slice_img = np.rot90(slice_tmp, k=1)  # 在当前基础上再左转 90°
        else:  # sagittal
            # 矢状位：X 固定，显示 (Z, Y)，
            # 先按之前方式得到图像，再在此基础上向右旋转 90°
            slice_tmp = arr[:, :, self.current_index]
            slice_tmp = np.rot90(slice_tmp, k=1)
            slice_tmp = np.fliplr(slice_tmp)
            slice_img = np.rot90(slice_tmp, k=3)  # 在当前基础上右转 90°

        # 应用窗宽窗位，将 HU 转换到 [0, 255]
        ww, wl = self.window_width, self.window_level
        low = wl - ww / 2
        high = wl + ww / 2
        slice_clipped = np.clip(slice_img, low, high)
        slice_norm = (slice_clipped - low) / (high - low + 1e-5)
        # 经过 rot90 / fliplr 后数组可能不是 C-contiguous，需要强制连续
        slice_uint8 = np.ascontiguousarray((slice_norm * 255).astype(np.uint8))

        h_img, w_img = slice_uint8.shape
        self._img_shape = (h_img, w_img)
        bytes_per_line = w_img
        # 先创建灰度 QImage，再转换为 RGB32 以便绘制彩色十字线
        qimg = QImage(
            slice_uint8.data,
            w_img,
            h_img,
            bytes_per_line,
            QImage.Format_Grayscale8,
        ).convertToFormat(QImage.Format_RGB32)

        # 在图像上绘制十字光标（基于全局 current_cursor），此时支持彩色
        if self.app_state.raw_image is not None:
            z, y, x = self.app_state.current_cursor
            row = col = None
            d, h, w = self.volume.array.shape
            if self.orientation == "axial":
                # (Y, X)
                if 0 <= y < h and 0 <= x < w:
                    row, col = y, x
            elif self.orientation == "coronal":
                # (Z, X) 经过 180° 旋转
                rz = d - 1 - z
                cx = w - 1 - x
                if 0 <= rz < d and 0 <= cx < w:
                    row, col = rz, cx
            else:  # sagittal
                # (Z, Y) 经过旋转/翻转，最终 (row, col) = (d-1-z, y)
                rz = d - 1 - z
                cy = y
                if 0 <= rz < d and 0 <= cy < h:
                    row, col = rz, cy

            if row is not None and col is not None:
                painter = QPainter(qimg)
                # 不同视图使用不同颜色的十字线，便于区分
                if self.orientation == "axial":
                    color = QColor(255, 0, 0)      # 轴状位：红色
                elif self.orientation == "coronal":
                    color = QColor(0, 255, 0)      # 冠状位：绿色
                else:
                    color = QColor(0, 160, 255)    # 矢状位：蓝色

                pen = QPen(color)
                pen.setWidth(1)
                painter.setPen(pen)
                # 水平线
                painter.drawLine(0, int(row), w_img - 1, int(row))
                # 垂直线
                painter.drawLine(int(col), 0, int(col), h_img - 1)
                painter.end()

        # 交给 QLabel 自己按控件大小缩放，避免控件尺寸被 pixmap 反复放大
        pixmap = QPixmap.fromImage(qimg)
        self.image_label.setPixmap(pixmap)

        # 记录当前显示区域大小（此时等于 label 尺寸），用于坐标换算
        label_size = self.image_label.size()
        self._display_origin = QPoint(0, 0)
        self._display_size = QSize(label_size.width(), label_size.height())

    # --- 内部工具 ---

    def _update_cursor_from_mouse(self, pos: QPoint) -> None:
        """根据点击位置更新全局 (z, y, x) 光标坐标."""

        if self.volume is None or self.app_state.raw_image is None:
            return

        local_x = pos.x() - self._display_origin.x()
        local_y = pos.y() - self._display_origin.y()
        if (
            local_x < 0
            or local_y < 0
            or local_x >= self._display_size.width()
            or local_y >= self._display_size.height()
        ):
            return

        # 反推回原始图像坐标
        h_img, w_img = self._img_shape
        if h_img <= 0 or w_img <= 0:
            return

        label_w = max(self._display_size.width(), 1)
        label_h = max(self._display_size.height(), 1)
        img_x = int(local_x * w_img / label_w)
        img_y = int(local_y * h_img / label_h)

        d, h, w = self.volume.array.shape
        z, y, x = self.app_state.current_cursor

        if self.orientation == "axial":
            z = self.current_index
            y = img_y
            x = img_x
        elif self.orientation == "coronal":
            # 逆映射自 (row=d-1-z, col=w-1-x)
            z = d - 1 - img_y
            x = w - 1 - img_x
            y = self.current_index
        else:  # sagittal
            # 逆映射自 (row=d-1-z, col=y)
            z = d - 1 - img_y
            y = img_x
            x = self.current_index

        # 限制在范围内
        z = int(np.clip(z, 0, d - 1))
        y = int(np.clip(y, 0, h - 1))
        x = int(np.clip(x, 0, w - 1))

        self.app_state.current_cursor = (z, y, x)


class MainWindow(QMainWindow):
    """
    主窗口：
    - 左侧工具栏（预留交互工具）
    - 中间 2x2 视图（轴位 / 冠状位 / 矢状位 / 3D）
    - 右侧患者信息 + 窗宽窗位 + 标注参数
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("医疗影像浏览系统 - AirwayLesion-Seg")
        self.resize(1280, 720)

        # 深色主题基础样式（按 v2.0 配色）
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #1E1E2E;
                color: #E0E0E0;
            }
            QLabel {
                color: #E0E0E0;
            }
            QFrame {
                background-color: #252535;
                border: 1px solid #303040;
            }
            QToolBar {
                background-color: #1E1E2E;
                border: none;
            }
            QToolButton {
                color: #A0A0B0;
                padding: 6px;
            }
            QToolButton:hover {
                background-color: #2E2E40;
                color: #E0E0E0;
            }
            QToolButton:checked {
                background-color: #3A86FF;
                color: #FFFFFF;
            }
            QSlider::groove:horizontal, QSlider::groove:vertical {
                background: #303040;
                height: 6px;
            }
            QSlider::handle:horizontal, QSlider::handle:vertical {
                background: #3A86FF;
                width: 12px;
                border-radius: 6px;
            }
            QPushButton {
                background-color: #3A86FF;
                color: white;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
            """
        )

        self.volume: DicomVolume | None = None
        self.app_state = AppState()

        # 顶部菜单
        self._create_menu()

        # 中央布局
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧工具栏（竖向，固定宽度）
        left_toolbar = self._create_side_toolbar()
        left_toolbar.setFixedWidth(60)
        main_layout.addWidget(left_toolbar)

        # 中间视图区域
        center_widget = QWidget()
        grid_layout = QGridLayout(center_widget)
        grid_layout.setContentsMargins(2, 2, 2, 2)
        grid_layout.setSpacing(2)
        # 行列伸缩比例统一为 1:1:1:1，保证 2x2 四个视图大小均匀
        grid_layout.setRowStretch(0, 1)
        grid_layout.setRowStretch(1, 1)
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 1)

        self.axial_view = SliceView("轴状位", "axial", self.app_state)
        self.coronal_view = SliceView("冠状位", "coronal", self.app_state)
        self.sagittal_view = SliceView("矢状位", "sagittal", self.app_state)

        # 右下角 3D 视图：使用 PyVistaQt QtInteractor
        self.view_3d = QFrame()
        self.view_3d.setFrameShape(QFrame.StyledPanel)
        view_3d_layout = QVBoxLayout(self.view_3d)
        view_3d_layout.setContentsMargins(4, 4, 4, 4)
        label_3d_title = QLabel("3D重建")
        label_3d_title.setStyleSheet("color: #ffffff; font-weight: bold;")
        view_3d_layout.addWidget(label_3d_title)

        self.pv_interactor = QtInteractor(self.view_3d)
        view_3d_layout.addWidget(self.pv_interactor, 1)

        # 设置 PyVista 全局主题与 3D 视图背景为黑色
        pv.global_theme.background = "black"
        # 兼容不同版本 PyVista：有的版本没有 floor / show_edges 属性
        if hasattr(pv.global_theme, "floor"):
            pv.global_theme.floor = False  # type: ignore[assignment]
        if hasattr(pv.global_theme, "show_edges"):
            pv.global_theme.show_edges = False  # type: ignore[assignment]
        # 明确设置当前交互窗口背景为黑色
        try:
            self.pv_interactor.set_background("black")
        except Exception:  # noqa: BLE001
            pass

        grid_layout.addWidget(self.axial_view, 0, 0)
        grid_layout.addWidget(self.coronal_view, 0, 1)
        grid_layout.addWidget(self.sagittal_view, 1, 0)
        grid_layout.addWidget(self.view_3d, 1, 1)

        main_layout.addWidget(center_widget, 1)

        # 右侧控制面板（固定宽度）
        right_panel = self._create_right_panel()
        right_panel.setFixedWidth(280)
        main_layout.addWidget(right_panel)

        # 底部状态栏
        status = QStatusBar()
        status.setStyleSheet("color: #E0E0E0; background-color: #151521;")
        self.setStatusBar(status)
        self.statusBar().showMessage("就绪")

    # ----- UI 构建 -----

    def _create_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("文件")
        open_action = QAction("打开 DICOM 目录", self)
        open_action.triggered.connect(self.open_dicom_directory)
        file_menu.addAction(open_action)

        open_model_action = QAction("导入 3D 模型", self)
        open_model_action.triggered.connect(self.open_3d_model_file)
        file_menu.addAction(open_model_action)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menu_bar.addMenu("视图")
        tools_menu = menu_bar.addMenu("工具")
        help_menu = menu_bar.addMenu("帮助")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def _create_side_toolbar(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        toolbar = QToolBar()
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setIconSize(QSize(18, 18))

        # 简单使用文字代替图标，后续可换成 QIcon
        actions = [
            ("选择", "select"),
            ("平移", "pan"),
            ("缩放", "zoom"),
            ("窗宽窗位", "wl"),
            ("标注", "annotate"),
            ("3D", "3d"),
        ]

        for text, _ in actions:
            act = QAction(text, self)
            toolbar.addAction(act)

        layout.addWidget(toolbar)
        layout.addStretch(1)
        return container

    def _create_right_panel(self) -> QWidget:
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

        self.label_patient_name = QLabel("-")
        self.label_patient_id = QLabel("-")
        self.label_study_date = QLabel("-")
        self.label_modality = QLabel("-")

        form.addRow("姓名:", self.label_patient_name)
        form.addRow("编号:", self.label_patient_id)
        form.addRow("检查日期:", self.label_study_date)
        form.addRow("检查类型:", self.label_modality)

        layout.addLayout(form)

        # 窗宽窗位
        wl_title = QLabel("窗宽窗位")
        wl_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        layout.addWidget(wl_title)

        self.slider_ww = QSlider(Qt.Horizontal)
        self.slider_ww.setMinimum(200)
        self.slider_ww.setMaximum(3000)
        self.slider_ww.setValue(1500)
        self.slider_ww.valueChanged.connect(self.on_window_changed)

        self.slider_wl = QSlider(Qt.Horizontal)
        self.slider_wl.setMinimum(-1000)
        self.slider_wl.setMaximum(1000)
        self.slider_wl.setValue(-600)
        self.slider_wl.valueChanged.connect(self.on_window_changed)

        layout.addWidget(QLabel("窗宽 (W)"))
        layout.addWidget(self.slider_ww)
        layout.addWidget(QLabel("窗位 (L)"))
        layout.addWidget(self.slider_wl)

        # 标注设置占位
        anno_title = QLabel("标记设置")
        anno_title.setStyleSheet("color: #ffffff; font-size: 13px; font-weight: bold;")
        layout.addWidget(anno_title)

        self.slider_brush_size = QSlider(Qt.Horizontal)
        self.slider_brush_size.setMinimum(1)
        self.slider_brush_size.setMaximum(20)
        self.slider_brush_size.setValue(5)

        layout.addWidget(QLabel("画笔大小"))
        layout.addWidget(self.slider_brush_size)

        layout.addStretch(1)

        btn_save = QPushButton("保存")
        layout.addWidget(btn_save)

        return panel

    # ----- 业务逻辑 -----

    def open_dicom_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择 DICOM 目录")
        if not dir_path:
            return

        directory = Path(dir_path)
        try:
            reader = sitk.ImageSeriesReader()
            # 确保元数据被写入到输出图像，便于后续读取患者信息
            reader.MetaDataDictionaryArrayUpdateOn()
            reader.LoadPrivateTagsOn()
            dicom_names = reader.GetGDCMSeriesFileNames(str(directory))
            if not dicom_names:
                raise RuntimeError("所选目录下未找到 DICOM 序列。")

            # 使用 pydicom 从第一张切片读取患者信息等 Tag
            first_dcm_path = dicom_names[0]
            ds = pydicom.dcmread(first_dcm_path, stop_before_pixels=True)

            reader.SetFileNames(dicom_names)
            image = reader.Execute()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"加载 DICOM 失败：{e}")
            return

        self.volume = DicomVolume(image, directory)
        # 更新全局状态
        self.app_state.raw_image = self.volume.array  # (Z, Y, X)
        self.app_state.spacing = image.GetSpacing()   # (x, y, z) in ITK
        self.app_state.origin = image.GetOrigin()
        d, h, w = self.volume.shape
        # 将当前光标初始化在体数据中心，方便用户从中间位置开始浏览
        self.app_state.current_cursor = (d // 2, h // 2, w // 2)

        self.statusBar().showMessage(
            f"已加载 DICOM 序列：{directory}，体数据形状 {self.volume.shape}"
        )

        # 简单填充患者信息（从 DICOM Tag 获取字段）
        self._update_patient_info(ds)

        # 更新各视图（会根据 app_state.current_cursor 自动跳到中间层）
        self.axial_view.set_volume(self.volume)
        self.coronal_view.set_volume(self.volume)
        self.sagittal_view.set_volume(self.volume)

        # 使用 PyVista 在 3D 视图中渲染一个简单的体数据或等值面
        self.update_3d_view()

        self._sync_window_to_views()

    def update_3d_view(self):
        """在右下角 3D 视图中显示当前 CT 体数据的简单 3D 渲染（阶段2原型）。"""
        if self.volume is None or self.app_state.raw_image is None:
            self.pv_interactor.clear()
            self.pv_interactor.add_text("未加载数据", color="white", font_size=10)
            self.pv_interactor.reset_camera()
            return

        vol = self.volume.array.astype(np.float32)  # (Z, Y, X)
        z, y, x = vol.shape

        grid = pv.UniformGrid()
        # PyVista 体素网格维度顺序为 (nx, ny, nz)
        grid.dimensions = (x, y, z)
        spacing = self.app_state.spacing or (1.0, 1.0, 1.0)
        # SimpleITK spacing 为 (x, y, z)
        grid.spacing = (float(spacing[0]), float(spacing[1]), float(spacing[2]))
        grid.origin = (0.0, 0.0, 0.0)
        grid.point_data["values"] = vol.ravel(order="F")

        self.pv_interactor.clear()
        self.pv_interactor.set_background("black")
        # 使用一个简单的等值面近似渲染，颜色为 10% 透明的灰色
        try:
            contour = grid.contour(isosurfaces=[-500])
            self.pv_interactor.add_mesh(
                contour,
                color="#808080",
                opacity=0.5,
            )
        except Exception:  # noqa: BLE001
            # 如果等值面失败，则改用体渲染，整体偏灰
            self.pv_interactor.add_volume(
                grid,
                cmap="gray",
                opacity=0.1,
            )

        self.pv_interactor.reset_camera()

    def _update_patient_info(self, ds: "pydicom.Dataset"):
        """从 pydicom Dataset 中提取患者信息和扫描参数。"""

        def get_attr(name: str, default: str = "-") -> str:
            value = getattr(ds, name, default)
            if value is None:
                return default
            return str(value)

        name = get_attr("PatientName", "-")
        pid = get_attr("PatientID", "-")
        study_date = get_attr("StudyDate", "-")
        modality = get_attr("Modality", "CT")

        self.label_patient_name.setText(name)
        self.label_patient_id.setText(pid)
        self.label_study_date.setText(study_date)
        self.label_modality.setText(modality)

        # 状态栏显示物理参数（若缺失则用 ? 占位）
        slice_thickness = get_attr("SliceThickness", "?")
        kvp = get_attr("KVP", "?")
        tube_current = get_attr("XRayTubeCurrent", "?")
        self.statusBar().showMessage(
            f"层厚: {slice_thickness} mm   电压: {kvp} kV   电流: {tube_current} mA"
        )

    def on_window_changed(self):
        # 来自右侧滑条变化
        self.app_state.window_width = int(self.slider_ww.value())
        self.app_state.window_level = int(self.slider_wl.value())
        self._sync_window_to_views()

    def sync_window_sliders_from_state(self):
        """当通过鼠标右键在视图中调窗宽窗位时，同步右侧滑条位置。"""
        self.slider_ww.blockSignals(True)
        self.slider_wl.blockSignals(True)
        self.slider_ww.setValue(self.app_state.window_width)
        self.slider_wl.setValue(self.app_state.window_level)
        self.slider_ww.blockSignals(False)
        self.slider_wl.blockSignals(False)

    def _sync_window_to_views(self):
        ww = float(self.app_state.window_width)
        wl = float(self.app_state.window_level)
        for view in (self.axial_view, self.coronal_view, self.sagittal_view):
            view.set_window(ww, wl)

    def update_all_views_from_cursor(self):
        """根据全局 current_cursor 更新三视图当前层面。"""
        if self.volume is None:
            return

        z, y, x = self.app_state.current_cursor
        self.axial_view.current_index = z
        self.coronal_view.current_index = y
        self.sagittal_view.current_index = x

        self.axial_view.update_view()
        self.coronal_view.update_view()
        self.sagittal_view.update_view()

    def open_3d_model_file(self):
        """从本地选择 3D 模型文件并显示到 '3D重建' 窗口中."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 3D 模型文件",
            "",
            "3D 模型 (*.stl *.obj *.ply *.vtp);;所有文件 (*.*)",
        )
        if not file_path:
            return

        try:
            mesh = pv.read(file_path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"加载 3D 模型失败：{e}")
            return

        # 在 3D 视图中显示模型
        self.pv_interactor.clear()
        self.pv_interactor.set_background("black")
        # 模型颜色为 10% 不透明度的红色
        self.pv_interactor.add_mesh(mesh, color="#FF0000", opacity=0.5)
        self.pv_interactor.reset_camera()
        self.statusBar().showMessage(f"已加载 3D 模型：{file_path}")

    def show_about_dialog(self):
        QMessageBox.information(
            self,
            "关于",
            "AirwayLesion-Seg\n\n"
            "CT 影像气道分割与病灶标注系统原型。\n"
            "当前版本实现 DICOM 加载与 MPR 三视图基础浏览。",
        )


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

