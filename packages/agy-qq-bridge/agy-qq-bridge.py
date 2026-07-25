#!/usr/bin/env python3
"""
AGY QQ Bridge — 向后兼容入口
pip 安装后直接使用 `agy-qq-bridge` 命令，也可 python3 agy-qq-bridge.py 直接运行
"""
import sys
from pathlib import Path

# 如果未安装 pip 包，先尝试从同目录 src 导入
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agy_qq_bridge.bridge import cli

if __name__ == "__main__":
    sys.exit(cli())
