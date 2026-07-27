"""
方块世界 - Block World

一个 64×64 的方块世界生态模拟游戏。

核心特性：
  · 自动寻路（BFS）到最近能量方块
  · 能量收集与分裂繁殖
  · 遗传种族演化系统（4位基因编码 + 变异）
  · 捕食对决（攻击力系统）
  · 方块寿命与老死机制
  · 实时统计图表（方块数/能量走势、存活分布、种族树）
"""

from .config import (
    WORLD_SIZE, TILE_SIZE, WINDOW_WIDTH, WINDOW_HEIGHT,
    SPLIT_THRESHOLD, SPLIT_COOLDOWN, SPLIT_ENERGY,
    INITIAL_ENERGY, AUTO_MOVE_INTERVAL,
    RACE_GENE_CHARS, RACE_CODE_LENGTH, RACE_MUTATION_RATE, RACE_COLORS,
    compute_wave_factor,
)
from .world import BlockWorld
from .entities import MovingBlock
from .camera import Camera
from .game import Game

__all__ = [
    "BlockWorld", "MovingBlock", "Camera", "Game",
    "WORLD_SIZE", "TILE_SIZE", "WINDOW_WIDTH", "WINDOW_HEIGHT",
    "SPLIT_THRESHOLD", "SPLIT_COOLDOWN", "SPLIT_ENERGY",
    "INITIAL_ENERGY", "AUTO_MOVE_INTERVAL",
    "RACE_GENE_CHARS", "RACE_CODE_LENGTH", "RACE_MUTATION_RATE", "RACE_COLORS",
    "compute_wave_factor",
]
