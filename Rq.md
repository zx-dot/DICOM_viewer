
# CT影像气道分割与病灶标注系统 (AirwayLesion-Seg) 需求规格说明书

**版本**: v2.0 (Vibe Coding Optimized)  
**日期**: 2026-02-09  
**开发模式**: Vibe Coding (Python + PySide6 + PyVista)

---

## 1. 项目概述 (Project Overview)

本项目旨在通过 Python 开发一款桌面端医疗影像处理软件。核心目标是实现**"所见即所得"**的交互体验：用户读取 DICOM 序列后，软件自动重建气道 3D 模型，并提供专业的标注工具对肺部病灶进行分割。开发过程采用 Vibe Coding 模式，强调 UI 的现代感（Medical Dark Theme）与交互的流畅性。

---

## 2. 技术栈选型 (Tech Stack)

为了让 Vibe Coding 能够生成高质量代码，我们选用社区支持最强、AI 最熟悉的库：

*   **GUI 框架**: **PySide6 (Qt for Python)**
    *   *理由*：比 PyQt5 更新，对 High-DPI 支持更好，AI 生成的代码结构更现代。
*   **3D/2D 可视化**: **PyVistaQt** (基于 VTK)
    *   *理由*：比原始 VTK 简洁 10 倍，非常适合 AI 快速生成 3D 渲染和切片逻辑。
*   **图像处理**: **SimpleITK** & **NumPy**
    *   *理由*：医学图像处理的标准库。
*   **AI/算法**: **PyTorch** & **MONAI** (可选) / **Scikit-image**
    *   *理由*：MONAI 提供现成的医疗影像 AI 组件。
*   **样式/主题**: **QSS (Qt Style Sheets)**
    *   *理由*：类似 CSS，AI 非常擅长根据描述生成漂亮的深色主题。

---

## 3. UI/UX "Vibe" 描述 (Design Specs)

此部分用于指导 AI 生成界面代码。关键词：**深色医疗风、专业、高对比度、扁平化**。

### 3.1 整体配色方案 (Color Palette)
*   **背景色 (Background)**: `#1E1E2E` (深空灰蓝，护眼)
*   **面板背景 (Panel BG)**: `#252535` (稍亮的灰，用于区分模块)
*   **强调色 (Accent)**: `#3A86FF` (亮蓝，用于按钮、滑块、选中状态)
*   **文字色 (Text)**: `#E0E0E0` (主文字), `#A0A0B0` (副标签)
*   **边框/分割线**: `#303040`

### 3.2 界面布局 (Layout Structure)
采用 **BorderLayout** 风格：

1.  **左侧工具栏 (Left Toolbar)**:
    *   宽度固定 (e.g., 60px)。
    *   垂直排列图标按钮 (Icon Buttons)。
    *   选中状态需有明显的背景高亮 (Active State)。
2.  **右侧控制面板 (Right Control Panel)**:
    *   宽度固定 (e.g., 280px)。
    *   内容垂直分布：
        *   **患者信息卡片**: 显示 DICOM Tag 信息。
        *   **窗宽窗位控制**: 滑块 (Slider) + 输入框 (SpinBox)。
        *   **标注工具设置**: 画笔大小、透明度滑块。
3.  **中间主视口 (Central Viewport)**:
    *   **2x2 网格布局 (QGridLayout)**。
    *   无间隙或极小间隙 (Spacing = 2px)。
    *   包含：Axial (横断), Sagittal (矢状), Coronal (冠状), 3D Render。
4.  **底部状态栏 (Bottom Status Bar)**:
    *   高度 25px。
    *   左对齐：显示层厚、电压、电流。
    *   右对齐：缩放比例、当前鼠标坐标 (x, y, z)。

---

## 4. 功能模块详述 (Functional Requirements)

### 4.1 数据加载与预处理 (Data Loading)
*   **功能**: 点击“文件” -> “打开文件夹”，读取 DICOM 序列。
*   **逻辑**:
    1.  使用 `SimpleITK.ImageSeriesReader` 读取序列。
    2.  读取 DICOM Tags (PatientName, PatientID, SliceThickness, KVP, XRayTubeCurrent)。
    3.  转换为 Numpy 数组 `(z, y, x)`，注意调整方向 (Direction) 和 间距 (Spacing)。
    4.  **Vibe 提示**: *“加载时显示进度条，若缺少切片需弹出警告。”*

### 4.2 MPR 四视图显示 (MPR Visualization)
*   **功能**: 三个 2D 切面 + 一个 3D 视图。
*   **交互**:
    *   **切层联动**: 滚动鼠标滚轮切换切片。
    *   **十字光标 (Crosshair)**: 在任意 2D 视图点击，更新所有视图的中心点坐标。
    *   **窗宽窗位 (W/L)**: 拖动右侧滑块，或者在图像上按住鼠标右键拖动（水平调窗宽，垂直调窗位），实时调整灰度显示。
        *   *预设*: 肺窗 (W:1500, L:-600), 纵隔窗 (W:350, L:40)。

### 4.3 气道 3D 建模 (Airway Segmentation & Rendering)
*   **功能**: 自动提取气道并生成模型。
*   **逻辑**:
    1.  后台运行分割算法 (可先用简单的阈值法+区域生长做原型，后续接入 MONAI)。
    2.  生成 Binary Mask。
    3.  使用 `PyVista` 的 `contour()` 或 `marching_cubes` 生成 Mesh。
    4.  在右下角 3D 视口渲染 Mesh（颜色：支气管蓝 #00FFFF，半透明）。

### 4.4 病灶交互式标注 (Lesion Annotation)
*   **工具模式**:
    *   **画笔 (Brush)**: 在 2D 切片上涂抹，修改 Mask 数组。
    *   **橡皮擦 (Eraser)**: 清除 Mask。
    *   **智能魔棒 (Magic Wand, 可选)**: 点击病灶中心，自动区域生长。
*   **逻辑**:
    *   维护一个与原图同尺寸的 `LabelMap` (Numpy uint8)。
    *   用户涂抹时，实时更新 `LabelMap`。
    *   **实时 3D 更新**: 当用户在 2D 画完一笔，右下角 3D 视图应异步更新病灶的 3D 形态（红色高亮）。
*   **右侧面板联动**:
    *   调节“大小”滑块 -> 改变画笔直径。
    *   调节“透明度”滑块 -> 改变标注层在 CT 图上的覆盖透明度 (Overlay Opacity)。

### 4.5 数据导出 (Export)
*   **保存结果**:
    *   点击“保存”按钮。
    *   导出标注 Mask 为 `.nii.gz` (NIfTI 格式)。
    *   导出气道模型为 `.stl` 或 `.obj` 格式。

---

## 5. Vibe Coding 开发提示词指南 (Prompts for AI)

在开发过程中，建议按照以下模块顺序向 AI 发送指令（Prompts）：

### 阶段 1：搭建界面框架 (UI Skeleton)
> **Prompt**: "使用 Python PySide6 搭建一个医疗影像浏览器的 GUI 框架。参考深色系医疗软件风格（背景 #1E1E2E）。界面包含：左侧固定宽度的工具栏（放置5个占位图标按钮），右侧固定宽度的属性面板（包含患者信息区、窗宽窗位滑块），中间是一个 2x2 的 Grid 布局，用于放置视图。请使用 QSS 美化界面，按钮要有 Hover 效果。"

### 阶段 2：集成 PyVista 显示器 (Visualization Integration)
> **Prompt**: "在中间的 2x2 Grid 中，前三个窗口使用 PyVistaQt 的 `QtInteractor` 来显示 2D 图像切片（分别对应 Axial, Sagittal, Coronal），第四个窗口用于 3D 渲染。请编写代码实现加载一个示例的 `.nii` 文件（或随机生成的 3D numpy 数组），并显示在三个切面窗口中。实现鼠标滚轮切换切片的功能。"

### 阶段 3：实现窗宽窗位与十字联动 (Interaction Logic)
> **Prompt**: "完善 PyVista 的交互逻辑：1. 实现‘十字光标’联动，当我在 Axial 视图点击一点时，Sagittal 和 Coronal 视图自动跳转到对应切片，并更新十字线位置。2. 实现右侧面板的滑块控制窗宽（Window Width）和窗位（Window Level），实时更新三个视图的对比度。"

### 阶段 4：标注工具开发 (Annotation Tool)
> **Prompt**: "现在实现画笔标注功能。当点击左侧‘画笔’工具时，鼠标在 2D 视图上拖动应当在一个空白的 Overlay Mask 上绘制数值。画笔大小由右侧滑块控制。请注意，Overlay 应当以半透明红色叠加在原始 CT 图像上。"

### 阶段 5：气道分割对接 (Algorithm Integration)
> **Prompt**: "编写一个函数 `segment_airway(ct_volume)`，这里先用简单的阈值分割 (-1000 到 -950) 模拟。分割后，使用 PyVista 将生成的 Binary Mask 转换为 3D Mesh，并显示在右下角的 3D 视图中。颜色设为青色。"

---

## 6. 数据结构定义 (Data Structures)

为了保证代码的健壮性，请遵循以下数据流标准：

*   **GlobalState (全局状态类)**:
    ```python
    class AppState:
        raw_image: np.ndarray        # 原始 CT 数据 (Z, Y, X)
        mask_image: np.ndarray       # 标注 Mask (Z, Y, X), 0=背景, 1=气道, 2=病灶
        spacing: tuple               # (z_spacing, y_spacing, x_spacing)
        origin: tuple                # (z, y, x) origin
        current_cursor: tuple        # (z, y, x) 当前光标位置
        window_level: int            # 当前窗位
        window_width: int            # 当前窗宽
    ```

---

## 7. 验收标准 (Acceptance Criteria)

1.  **UI 还原**: 必须与提供的 UI 设计图在布局和配色上保持 95% 一致。
2.  **性能**: 512x512x300 的 CT 序列加载时间 < 3秒；滚轮切层无明显卡顿 (> 30fps)。
3.  **坐标对齐**: 2D 切面上的标注点，必须在 3D 视图的对应空间位置准确显示，无镜像或翻转错误。
4.  **文件兼容**: 能成功解析标准 DICOM 文件夹并显示正确的患者元数据。

---
**[文档结束]**