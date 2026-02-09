# AirwayLesion-Seg - CT 影像气道分割与病灶标注系统

本项目是基于 Python 的桌面应用，目标是提供 CT DICOM 影像读取、多平面重建 (MPR) 浏览、气道分割与病灶标注等功能。

当前版本实现内容：

- 基于 **PySide6** 的桌面 GUI 框架
- DICOM 序列导入（选择目录）
- 简单的 3D 体数据加载（SimpleITK + NumPy）
- 轴位 / 冠状位 / 矢状位 三视图窗口布局与基础交互框架
- 右侧患者信息与窗宽/窗位控制面板（逻辑框架）
- 预留气道分割、3D 可视化与标注工具接口

后续可按 `Rq.md` 中的路线图逐步完善：

1. 集成 MONAI 或自定义气道分割模型，输出气道 Mask；
2. 使用 scikit-image / VTK / PyVista 进行 3D 气道重建与显示；
3. 实现画笔、橡皮擦、半自动分割等标注工具，并支持 NIfTI Mask 导出；
4. 性能优化与打包为 `.exe`。

## 开发环境

- Python 3.8+
- Windows 10+

## 安装依赖

在虚拟环境中执行：

```bash
pip install -r requirements.txt
```

## 运行程序

```bash
python main.py
```

首次运行后，可通过菜单栏「文件 -> 打开 DICOM 目录」加载一组 CT DICOM 序列。

