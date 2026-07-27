"""快捷启动脚本 — 直接运行即可"""
import sys
from pathlib import Path

# 把 src 目录加入模块搜索路径，无需 pip install
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from block_world.game import Game

if __name__ == "__main__":
    game = Game()
    game.run()
