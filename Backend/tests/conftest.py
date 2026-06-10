# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# 将 src 目录加入 Python 路径，使测试可以 import 项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
