"""
方块世界 - 网格世界与能量系统

BlockWorld 负责管理网格状态、能量方块的生成与收集。
"""

import random
from typing import Tuple, Set

from . import config


class BlockWorld:
    """有限方块世界网格"""

    def __init__(self, size: int = config.WORLD_SIZE):
        self.size = size
        self.grid = [[0 for _ in range(size)] for _ in range(size)]
        self.energy_positions: Set[Tuple[int, int]] = set()

    def is_energy_block(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self.grid[y][x] > 0

    def collect_energy(self, x: int, y: int) -> int:
        energy = self.grid[y][x]
        self.grid[y][x] = 0
        self.energy_positions.discard((x, y))
        return energy

    def spawn_energy_blocks(self, count: int, wave_factor: float = 0.5):
        """
        随机生成能量方块。
        wave_factor: 0~1 之间，控制每个方块的能量值。
        """
        current = len(self.energy_positions)
        available = config.MAX_ENERGY_BLOCKS - current
        if available <= 0:
            return
        count = min(count, available)
        val_range = config.ENERGY_VALUE_MAX - config.ENERGY_VALUE_MIN
        for _ in range(count):
            for _ in range(100):
                x = random.randint(0, self.size - 1)
                y = random.randint(0, self.size - 1)
                if self.grid[y][x] == 0:
                    e_min = max(1, int(config.ENERGY_VALUE_MIN + val_range * wave_factor * 0.7))
                    e_max = int(config.ENERGY_VALUE_MIN + val_range * wave_factor * 1.3)
                    if e_max < e_min + 1:
                        e_max = e_min + 1
                    e = random.randint(e_min, e_max)
                    self.grid[y][x] = e
                    self.energy_positions.add((x, y))
                    break

    def total_energy_sum(self) -> int:
        """返回所有能量方块的能量总和"""
        total = 0
        for x, y in self.energy_positions:
            total += self.grid[y][x]
        return total
