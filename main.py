# -*- coding: utf-8 -*-
"""
程序入口（MVVM 架构）。
创建 Application、ViewModel、MainWindow，完成绑定后启动事件循环。
"""

import sys

from PySide6.QtWidgets import QApplication

from viewmodels import MainViewModel
from views import MainWindow


def main() -> None:
    """创建应用、ViewModel 与主窗口，绑定后显示并进入事件循环。"""
    app = QApplication(sys.argv)
    view_model = MainViewModel()
    window = MainWindow(view_model)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
