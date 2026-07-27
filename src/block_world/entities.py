"""
方块世界 - 移动方块实体

MovingBlock 是游戏的核心实体类，包含寻路、移动、分裂、遗传变异等功能。
"""

import random
from collections import deque
from typing import Optional, Set, Tuple

from . import config


class MovingBlock:
    """自动寻路的移动方块"""

    _next_id = 0

    def __init__(self, x: int, y: int, energy: int, world_size: int,
                 birth_step: int = 0,
                 generation: int = 0,
                 sight_range: Optional[int] = None,
                 energy_efficiency: float = 1.0,
                 move_speed: float = 1.0,
                 attack_power: int = 0):
        self.x = x
        self.y = y
        self.energy = float(energy)
        self.world_size = world_size
        self.steps_taken = 0
        self.total_collected = 0
        self.alive = True
        self.birth_step = birth_step
        self.generation = generation
        self.sight_range = sight_range if sight_range is not None else world_size
        self.energy_efficiency = energy_efficiency
        self.move_speed = move_speed
        self.attack_power = attack_power
        self.race = MovingBlock.random_race()
        self.age = 0.0
        self.stage = "young"  # young → adult
        self.split_cooldown = 0.0
        self.max_age = 0.0       # 寿命上限（秒），0=无上限，分裂时设定
        self.target: Optional[Tuple[int, int]] = None
        self.color = None        # 由 Game 的 race_color_map 分配
        self.outline_color = None

        self.id = MovingBlock._next_id
        MovingBlock._next_id += 1

    def find_path_bfs(self, world: 'BlockWorld',
                      occupied: Set[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """
        BFS寻路到最近的能量方块。
        返回 (dx, dy) 下一步移动方向，无可达路径返回 None。
        同时设置 self.target 为目标位置。
        """
        from .world import BlockWorld  # type: ignore
        if not world.energy_positions:
            self.target = None
            return None

        actual_occupied = occupied - {(self.x, self.y)}
        visited = [[False] * world.size for _ in range(world.size)]
        prev = [[None] * world.size for _ in range(world.size)]

        q = deque()
        q.append((self.x, self.y, 0))
        visited[self.y][self.x] = True

        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        target_pos = None

        while q:
            cx, cy, depth = q.popleft()

            if ((cx, cy) != (self.x, self.y)
                    and (cx, cy) in world.energy_positions
                    and (cx, cy) not in actual_occupied):
                target_pos = (cx, cy)
                break

            if depth >= self.sight_range:
                continue

            for dx, dy in dirs:
                nx, ny = cx + dx, cy + dy
                if (0 <= nx < world.size and 0 <= ny < world.size
                        and not visited[ny][nx] and (nx, ny) not in actual_occupied):
                    visited[ny][nx] = True
                    prev[ny][nx] = (cx, cy)
                    q.append((nx, ny, depth + 1))

        if target_pos is None:
            self.target = None
            return None

        cx, cy = target_pos
        while prev[cy][cx] is not None and prev[cy][cx] != (self.x, self.y):
            cx, cy = prev[cy][cx]

        dx = cx - self.x
        dy = cy - self.y
        self.target = target_pos
        return (dx, dy)

    def try_move(self, dx: int, dy: int, world: 'BlockWorld') -> int:
        """
        尝试移动一格。返回：>0 收集到能量, 0 普通移动, -1 失败
        注意：不做 occupied 检查（由调用方负责）
        """
        from .world import BlockWorld  # type: ignore
        nx = self.x + dx
        ny = self.y + dy
        if not (0 <= nx < self.world_size and 0 <= ny < self.world_size):
            return -1
        if self.energy < config.MOVE_COST * self.energy_efficiency:
            return -1

        old_x, old_y = self.x, self.y
        self.x = nx
        self.y = ny
        cost = config.MOVE_COST * self.energy_efficiency
        self.energy -= cost
        self.steps_taken += 1

        gained = 0
        if world.is_energy_block(self.x, self.y):
            gained = world.collect_energy(self.x, self.y)
            self.energy += gained
            self.total_collected += gained
            self.target = None

        return gained

    # ---- 种族系统 ----

    @staticmethod
    def random_race() -> str:
        """随机生成一段基因编码作为种族标识"""
        return ''.join(random.choice(config.RACE_GENE_CHARS) for _ in range(config.RACE_CODE_LENGTH))

    @staticmethod
    def mutate_race(race: str) -> str:
        """遗传变异：每个基因位点以 RACE_MUTATION_RATE 概率突变"""
        chars = list(race)
        for i in range(len(chars)):
            if random.random() < config.RACE_MUTATION_RATE:
                chars[i] = random.choice(config.RACE_GENE_CHARS)
        return ''.join(chars)

    # ---- 分裂 ----

    def should_split(self) -> bool:
        """成年、冷却结束、且能量充足才可分裂"""
        if self.stage != "adult" or self.split_cooldown > 0:
            return False
        return self.energy >= config.SPLIT_THRESHOLD

    def split(self) -> 'MovingBlock':
        self.energy -= config.SPLIT_ENERGY
        self.split_cooldown = config.SPLIT_COOLDOWN
        # 在 ±5 格正方形范围内随机选择子代诞生位置
        candidates = []
        for ox in range(-5, 6):
            for oy in range(-5, 6):
                if ox == 0 and oy == 0:
                    continue
                tx, ty = self.x + ox, self.y + oy
                if 0 <= tx < self.world_size and 0 <= ty < self.world_size:
                    candidates.append((tx, ty))
        nx, ny = random.choice(candidates) if candidates else (self.x, self.y)
        # 子代继承父代属性并变异
        child_sight = max(12, min(self.world_size,
                                 self.sight_range + random.randint(-4, 8)))
        child_sight = min(child_sight, max(12, self.world_size * 2 // 3))
        child_eff = max(0.6, min(1.4,
                         self.energy_efficiency + random.uniform(-0.15, 0.15)))
        child_speed = max(0.5, min(3.0,
                          self.move_speed + random.uniform(-0.25, 0.25)))
        child_attack = max(0, self.attack_power + random.randint(-1, 2))
        child = MovingBlock(nx, ny, config.SPLIT_ENERGY, self.world_size,
                          generation=self.generation + 1,
                          sight_range=child_sight,
                          energy_efficiency=child_eff,
                          move_speed=child_speed,
                          attack_power=child_attack)
        child.race = MovingBlock.mutate_race(self.race)
        child.max_age = max(30.0, config.LIFESPAN_BASE + random.uniform(-config.LIFESPAN_VARIANCE, config.LIFESPAN_VARIANCE))
        child.stage = "young"
        return child
