# -*- coding: utf-8 -*-
"""
主界面 ViewModel（MVVM）。
负责：DICOM 加载、窗宽窗位/光标状态、切片与十字线数据生成、患者信息、3D 渲染数据。
View 通过信号接收刷新通知，通过方法获取展示数据与执行命令。
"""

from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import SimpleITK as sitk
import pydicom
import pyvista as pv
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QColor, QPen, QPainter

from models import AppState, DicomVolume


class MainViewModel(QObject):
    """
    主界面 ViewModel。
    - 持有 AppState、DicomVolume，提供加载 DICOM、设置光标/窗宽窗位等命令
    - 提供按朝向与层号生成带十字线的切片 QImage，供 View 直接显示
    - 发出信号：volume_loaded, cursor_changed, window_changed, patient_info_changed, status_message
    """

    # 体数据加载完成（View 可据此刷新三视图与 3D）
    volume_loaded = Signal()
    # 十字光标变化（View 刷新三视图当前层与十字线）
    cursor_changed = Signal()
    # 窗宽窗位变化（View 刷新三视图显示）
    window_changed = Signal()
    # 患者信息更新（View 刷新右侧面板）
    patient_info_changed = Signal()
    # 状态栏文案
    status_message = Signal(str)
    # 标注 Mask 被修改（View 刷新三视图以显示 Overlay）
    mask_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_state = AppState()
        self._volume: Optional[DicomVolume] = None
        self._patient_info: dict = {}
        # 阶段 4：标注工具状态
        self._current_tool: str = "select"  # "select" | "brush"
        self._brush_radius: int = 5  # 画笔半径（体素），由右侧滑块控制
        self._overlay_opacity: float = 0.5  # 标注层半透明红色叠加透明度 0~1

    @property
    def app_state(self) -> AppState:
        """全局应用状态，只读供 View 绑定滑条等。"""
        return self._app_state

    @property
    def volume(self) -> Optional[DicomVolume]:
        """当前 DICOM 体数据，未加载时为 None。"""
        return self._volume

    # ---------- 命令：数据加载 ----------

    def load_dicom_directory(self, directory: Path) -> bool:
        """
        从指定目录加载 DICOM 序列，更新 AppState 与 _volume。
        成功时发出 volume_loaded、patient_info_changed、status_message。
        """
        try:
            reader = sitk.ImageSeriesReader()
            reader.MetaDataDictionaryArrayUpdateOn()
            reader.LoadPrivateTagsOn()
            dicom_names = reader.GetGDCMSeriesFileNames(str(directory))
            if not dicom_names:
                raise RuntimeError("所选目录下未找到 DICOM 序列。")
            first_dcm_path = dicom_names[0]
            ds = pydicom.dcmread(first_dcm_path, stop_before_pixels=True)
            reader.SetFileNames(dicom_names)
            image = reader.Execute()
        except Exception as e:
            self.status_message.emit(f"加载 DICOM 失败：{e}")
            return False

        self._volume = DicomVolume(image, directory)
        self._app_state.raw_image = self._volume.array
        self._app_state.spacing = image.GetSpacing()
        self._app_state.origin = image.GetOrigin()
        d, h, w = self._volume.shape
        self._app_state.current_cursor = (d // 2, h // 2, w // 2)
        # 阶段 4：初始化空白 Overlay Mask（与体数据同尺寸，0=背景 1=病灶标注）
        self._app_state.mask_image = np.zeros((d, h, w), dtype=np.uint8)

        self.status_message.emit(
            f"已加载 DICOM 序列：{directory}，体数据形状 {self._volume.shape}"
        )
        self._emit_patient_info(ds)
        self.volume_loaded.emit()
        return True

    def _emit_patient_info(self, ds: pydicom.Dataset) -> None:
        """从 pydicom Dataset 解析患者信息并发出 patient_info_changed。"""
        def get_attr(name: str, default: str = "-") -> str:
            value = getattr(ds, name, default)
            return str(value) if value is not None else default

        self._patient_info = {
            "name": get_attr("PatientName", "-"),
            "patient_id": get_attr("PatientID", "-"),
            "study_date": get_attr("StudyDate", "-"),
            "modality": get_attr("Modality", "CT"),
            "slice_thickness": get_attr("SliceThickness", "?"),
            "kvp": get_attr("KVP", "?"),
            "tube_current": get_attr("XRayTubeCurrent", "?"),
        }
        self.patient_info_changed.emit()

    def get_patient_info(self) -> dict:
        """返回当前患者信息字典，供 View 绑定到右侧面板。"""
        return getattr(self, "_patient_info", {})

    # ---------- 命令：光标与窗宽窗位 ----------

    def set_cursor(self, z: int, y: int, x: int) -> None:
        """设置全局十字光标 (z,y,x)，并发出 cursor_changed。"""
        if self._volume is None:
            return
        d, h, w = self._volume.shape
        z = int(np.clip(z, 0, d - 1))
        y = int(np.clip(y, 0, h - 1))
        x = int(np.clip(x, 0, w - 1))
        self._app_state.current_cursor = (z, y, x)
        self.cursor_changed.emit()

    def set_window(self, window_width: int, window_level: int) -> None:
        """设置窗宽窗位，并发出 window_changed。"""
        self._app_state.window_width = window_width
        self._app_state.window_level = window_level
        self.window_changed.emit()

    def sync_sliders_from_state(self) -> Tuple[int, int]:
        """返回当前窗宽、窗位，供 View 同步滑条数值（避免循环触发）。"""
        return self._app_state.window_width, self._app_state.window_level

    # ---------- 阶段 4：标注工具 ----------

    def get_tool(self) -> str:
        """当前工具："select" 十字光标联动 | "brush" 画笔标注。"""
        return self._current_tool

    def set_tool(self, tool: str) -> None:
        """设置当前工具，供左侧工具栏「选择」/「标注」切换。"""
        if tool in ("select", "brush"):
            self._current_tool = tool

    def set_brush_radius(self, radius: int) -> None:
        """设置画笔半径（体素），由右侧「画笔大小」滑块调用。"""
        self._brush_radius = max(1, min(50, radius))

    def set_overlay_opacity(self, opacity: float) -> None:
        """设置标注层叠加透明度 0~1，由右侧「透明度」滑块调用。"""
        self._overlay_opacity = max(0.0, min(1.0, opacity))

    def draw_on_mask(
        self,
        orientation: str,
        slice_index: int,
        local_x: float,
        local_y: float,
        display_width: int,
        display_height: int,
        img_shape_hw: Tuple[int, int],
    ) -> None:
        """
        在 Overlay Mask 上以当前画笔半径在指定屏幕位置画圆（标注值=1）。
        仅在 brush 模式下由 View 在鼠标拖拽时调用；完成后发出 mask_changed。
        """
        vox = self.screen_to_voxel(
            orientation, slice_index, local_x, local_y,
            display_width, display_height, img_shape_hw,
        )
        if vox is None or self._app_state.mask_image is None:
            return
        z, y, x = vox
        d, h, w = self._app_state.mask_image.shape
        r = self._brush_radius
        label = 1  # 病灶标注
        # 在当前切片平面内以 (z,y,x) 投影为圆心、r 为半径画圆
        if orientation == "axial":
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dy * dy + dx * dx <= r * r:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w:
                            self._app_state.mask_image[z, ny, nx] = label
        elif orientation == "coronal":
            for dz in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if dz * dz + dx * dx <= r * r:
                        nz, nx = z + dz, x + dx
                        if 0 <= nz < d and 0 <= nx < w:
                            self._app_state.mask_image[nz, slice_index, nx] = label
        else:  # sagittal
            for dz in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if dz * dz + dy * dy <= r * r:
                        nz, ny = z + dz, y + dy
                        if 0 <= nz < d and 0 <= ny < h:
                            self._app_state.mask_image[nz, ny, slice_index] = label
        self.mask_changed.emit()

    # ---------- 供 View 获取展示数据 ----------

    def get_slice_display_image(
        self,
        orientation: str,
        slice_index: int,
        img_shape_hw: Tuple[int, int],
    ) -> Optional[QImage]:
        """
        根据朝向与层号生成带窗宽窗位与十字线的切片 QImage。
        orientation: "axial" | "coronal" | "sagittal"
        img_shape_hw: (height, width) 目标显示尺寸，用于记录 _img_shape 供坐标换算（由 View 传入当前 label 尺寸）
        返回 RGB32 QImage，无数据时返回 None。
        """
        if self._volume is None or self._app_state.raw_image is None:
            return None

        arr = self._volume.array
        d, h, w = arr.shape
        ww = float(self._app_state.window_width)
        wl = float(self._app_state.window_level)

        # 按朝向取切片并做显示用旋转/翻转（保证与轴状位解剖方向一致）
        if orientation == "axial":
            slice_img = arr[slice_index, :, :]
        elif orientation == "coronal":
            slice_img = arr[:, slice_index, :]  # (Z, X)，Z 为头脚方向
            slice_img = np.flipud(slice_img)   # 仅上下翻转，使头在上、脚在下（不做左右镜像）
        else:  # sagittal
            slice_tmp = arr[:, :, slice_index]
            slice_tmp = np.rot90(slice_tmp, k=1)
            slice_tmp = np.fliplr(slice_tmp)
            slice_img = np.rot90(slice_tmp, k=3)
        slice_img = np.ascontiguousarray(slice_img)

        low = wl - ww / 2
        high = wl + ww / 2
        slice_clipped = np.clip(slice_img, low, high)
        slice_norm = (slice_clipped - low) / (high - low + 1e-5)
        slice_uint8 = np.ascontiguousarray((slice_norm * 255).astype(np.uint8))
        h_img, w_img = slice_uint8.shape
        bytes_per_line = w_img
        qimg = QImage(
            slice_uint8.data,
            w_img,
            h_img,
            bytes_per_line,
            QImage.Format_Grayscale8,
        ).convertToFormat(QImage.Format_RGB32)

        # 十字线在显示图像上的像素坐标 (row, col)，与各朝向的旋转/翻转一致
        z, y, x = self._app_state.current_cursor
        row = col = None
        if orientation == "axial":
            if 0 <= y < h and 0 <= x < w:
                row, col = y, x
        elif orientation == "coronal":
            if 0 <= z < d and 0 <= x < w:
                # 仅上下翻转：row=d-1-z（头在上），col=x（不左右镜像）
                row, col = d - 1 - z, x
        else:  # sagittal
            if 0 <= z < d and 0 <= y < h:
                row, col = d - 1 - z, y

        if row is not None and col is not None:
            painter = QPainter(qimg)
            if orientation == "axial":
                color = QColor(255, 0, 0)
            elif orientation == "coronal":
                color = QColor(0, 255, 0)
            else:
                color = QColor(0, 160, 255)
            pen = QPen(color)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(0, int(row), w_img - 1, int(row))
            painter.drawLine(int(col), 0, int(col), h_img - 1)
            painter.end()

        # 阶段 4：标注 Overlay 以半透明红色叠加在 CT 上
        if self._app_state.mask_image is not None:
            mask = self._app_state.mask_image
            d, h, w = mask.shape
            if orientation == "axial":
                mask_slice = mask[slice_index, :, :]
            elif orientation == "coronal":
                mask_slice = np.flipud(mask[:, slice_index, :])
            else:  # sagittal
                tmp = mask[:, :, slice_index]
                tmp = np.rot90(tmp, k=1)
                tmp = np.fliplr(tmp)
                mask_slice = np.rot90(tmp, k=3)
            mask_slice = np.ascontiguousarray(mask_slice)
            # 半透明红色叠加：当前像素与红色按 overlay_opacity 混合
            for i in range(min(mask_slice.shape[0], qimg.height())):
                for j in range(min(mask_slice.shape[1], qimg.width())):
                    if mask_slice[i, j] > 0:
                        # 与当前像素混合
                        c = qimg.pixelColor(j, i)
                        r = int(c.red() * (1 - self._overlay_opacity) + 255 * self._overlay_opacity)
                        g = int(c.green() * (1 - self._overlay_opacity))
                        b = int(c.blue() * (1 - self._overlay_opacity))
                        qimg.setPixelColor(j, i, QColor(r, g, b))

        return qimg

    def get_current_cursor_slice_indices(self) -> Tuple[int, int, int]:
        """返回 (axial_index, coronal_index, sagittal_index) 供 View 同步三视图层号。"""
        if self._volume is None:
            return 0, 0, 0
        z, y, x = self._app_state.current_cursor
        return z, y, x

    def screen_to_voxel(
        self,
        orientation: str,
        slice_index: int,
        local_x: float,
        local_y: float,
        display_width: int,
        display_height: int,
        img_shape_hw: Tuple[int, int],
    ) -> Optional[Tuple[int, int, int]]:
        """
        将 View 上鼠标位置 (local_x, local_y) 反算为体素坐标 (z, y, x)。
        display_* 为当前显示区域宽高，img_shape_hw 为该朝向切片的 (height, width)。
        """
        if self._volume is None:
            return None
        h_img, w_img = img_shape_hw
        if h_img <= 0 or w_img <= 0 or display_width <= 0 or display_height <= 0:
            return None
        img_x = int(local_x * w_img / display_width)
        img_y = int(local_y * h_img / display_height)
        d, h, w = self._volume.shape
        z, y, x = self._app_state.current_cursor

        # 由显示坐标反推体素 (z,y,x)，与 get_slice_display_image 中十字线映射一致
        if orientation == "axial":
            z = slice_index
            y = img_y
            x = img_x
        elif orientation == "coronal":
            z = d - 1 - img_y  # 上下翻转的逆
            x = img_x         # 不左右镜像
            y = slice_index
        else:  # sagittal
            z = d - 1 - img_y
            y = img_x
            x = slice_index

        z = int(np.clip(z, 0, d - 1))
        y = int(np.clip(y, 0, h - 1))
        x = int(np.clip(x, 0, w - 1))
        return (z, y, x)

    def get_slice_index_range(self, orientation: str) -> Tuple[int, int]:
        """返回某朝向的层索引范围 (min_index, max_index)，无数据时 (0, 0)。"""
        if self._volume is None:
            return 0, 0
        d, h, w = self._volume.shape
        if orientation == "axial":
            return 0, d - 1
        if orientation == "coronal":
            return 0, h - 1
        return 0, w - 1

    def get_initial_slice_index(self, orientation: str) -> int:
        """根据当前光标返回该朝向的初始层号（用于加载后定位到中心层）。"""
        if self._volume is None:
            return 0
        z, y, x = self._app_state.current_cursor
        d, h, w = self._volume.shape
        if orientation == "axial":
            return int(np.clip(z, 0, d - 1))
        if orientation == "coronal":
            return int(np.clip(y, 0, h - 1))
        return int(np.clip(x, 0, w - 1))

    # ---------- 阶段 5：气道分割对接 ----------

    def segment_airway(self, ct_volume: np.ndarray) -> np.ndarray:
        """
        气道分割（简单阈值模拟）。
        HU 在 [-1000, -950] 视为气道/空气，输出二值 Mask (Z,Y,X)，1=气道 0=背景。
        后续可替换为 MONAI 等模型推理。
        """
        mask = ((ct_volume >= -1000) & (ct_volume <= -950)).astype(np.float32)
        return mask

    def build_airway_mesh(self):
        """
        对当前体数据运行气道分割，将 Binary Mask 转为 PyVista 3D Mesh。
        返回 (mesh, color, opacity) 供 View 在 3D 视图中显示，失败返回 None。
        颜色为青色 #00FFFF。
        """
        if self._volume is None or self._app_state.raw_image is None:
            return None
        vol = self._volume.array
        mask = self.segment_airway(vol)
        z_dim, y_dim, x_dim = mask.shape
        grid = pv.UniformGrid()
        grid.dimensions = (x_dim, y_dim, z_dim)
        spacing = self._app_state.spacing or (1.0, 1.0, 1.0)
        grid.spacing = (float(spacing[0]), float(spacing[1]), float(spacing[2]))
        grid.origin = (0.0, 0.0, 0.0)
        grid.point_data["values"] = mask.ravel(order="F")
        try:
            mesh = grid.contour(isosurfaces=[0.5])
            return (mesh, "#00FFFF", 0.6)
        except Exception:
            return None

    # ---------- 3D 相关（供 View 调用） ----------

    def build_3d_volume_actor(self):
        """
        使用当前体数据在 PyVista 中构建 3D 等值面/体渲染。
        返回 (plotter_clear, add_mesh_or_volume_callable) 或 (clear, None) 表示仅清空。
        """
        if self._volume is None or self._app_state.raw_image is None:
            return None
        vol = self._volume.array.astype(np.float32)
        z_dim, y_dim, x_dim = vol.shape
        grid = pv.UniformGrid()
        grid.dimensions = (x_dim, y_dim, z_dim)
        spacing = self._app_state.spacing or (1.0, 1.0, 1.0)
        grid.spacing = (float(spacing[0]), float(spacing[1]), float(spacing[2]))
        grid.origin = (0.0, 0.0, 0.0)
        grid.point_data["values"] = vol.ravel(order="F")
        try:
            contour = grid.contour(isosurfaces=[-500])
            return ("clear", contour, "#808080", 0.5)
        except Exception:
            return ("volume", grid, "gray", 0.1)

    def load_3d_model_file(self, file_path: str) -> Optional[object]:
        """
        从本地路径加载 3D 模型（PyVista 可读格式）。
        返回 (mesh, color, opacity) 供 View 在 3D 窗口中显示，失败返回 None。
        """
        try:
            mesh = pv.read(file_path)
            return (mesh, "#FF0000", 0.5)
        except Exception:
            return None
