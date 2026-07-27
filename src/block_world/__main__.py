"""
方块世界 - 入口模块

可通过以下方式运行：
    python -m block_world          # 作为模块运行
    python src/block_world          # 直接运行包
"""

from .game import Game


def main():
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
