"""
64×64 方块世界 - 实时自动寻路 · 能量收集与分裂
================================================
规则：
1. 有限世界 64×64，外围有边界墙
2. 所有方块自动寻路到最近能量方块，连续移动
3. 每步消耗1点能量，移动到能量方块上获得随机能量
4. 能量达到100时分裂，能量平分
5. 方向键/WASD 手动控制主方块方向
"""

import pygame
import random
import math
import sys
from typing import Tuple, List, Optional, Set
from collections import deque

# ==================== 常量 ====================
WORLD_SIZE = 64
TILE_SIZE = 32
GRID_LINE = True

VIEW_COLS = 40
VIEW_ROWS = 30
WINDOW_WIDTH = VIEW_COLS * TILE_SIZE
WINDOW_HEIGHT = VIEW_ROWS * TILE_SIZE + 60  # 底部信息栏

# 颜色
COLOR_VOID = (5, 5, 10)
COLOR_WALL = (80, 65, 55)
COLOR_WALL_DARK = (55, 45, 38)
COLOR_BG = (18, 18, 24)
COLOR_GRID = (30, 30, 40)
COLOR_BLOCK = (60, 120, 60)
COLOR_BLOCK_ALT = (55, 110, 55)
COLOR_ENERGY_BLOCK = (255, 215, 0)
COLOR_ENERGY_GLOW = (255, 240, 150)
COLOR_UI_TEXT = (220, 220, 220)
COLOR_UI_BG = (24, 24, 34)
COLOR_ENERGY_BAR = (255, 200, 50)

# 游戏参数
INITIAL_ENERGY = 50
SPLIT_THRESHOLD = 100
MOVE_COST = 1

# 能量波动参数（正弦周期）
ENERGY_WAVE_PERIOD = 30.0      # 完整波周期（秒）
ENERGY_VALUE_MIN = 2           # 波谷时每个能量块最低值
ENERGY_VALUE_MAX = 25          # 波峰时每个能量块最高值
ENERGY_SPAWN_BASE = 2          # 波谷时每次生成数量
ENERGY_SPAWN_EXTRA = 6         # 波峰额外增加数量

# 自动移动间隔（秒）
AUTO_MOVE_INTERVAL = 0.15
# 能量刷新间隔（秒）
ENERGY_SPAWN_INTERVAL = 2.0
ENERGY_SPAWN_PER_TICK = 5
MAX_ENERGY_BLOCKS = 400

# 统计图表
STATS_MAX_POINTS = 300          # 保存最近多少帧的统计
CHART_WIDTH = 900
CHART_HEIGHT = 500
CHART_COLOR_BLOCKS = (70, 180, 255)      # 方块数线条颜色
CHART_COLOR_ENERGY = (255, 215, 0)       # 能量块数线条颜色
CHART_COLOR_GRID = (50, 50, 65)
CHART_COLOR_AXIS = (100, 100, 120)


# ==================== 方块世界 ====================

class BlockWorld:
    """64×64 有限方块世界"""

    def __init__(self, size: int = WORLD_SIZE):
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
        available = MAX_ENERGY_BLOCKS - current
        if available <= 0:
            return
        count = min(count, available)
        val_range = ENERGY_VALUE_MAX - ENERGY_VALUE_MIN
        for _ in range(count):
            for _ in range(100):
                x = random.randint(0, self.size - 1)
                y = random.randint(0, self.size - 1)
                if self.grid[y][x] == 0:
                    # 能量值 = 基础值 + (波幅 * 波动因子) + 随机抖动
                    e_min = max(1, int(ENERGY_VALUE_MIN + val_range * wave_factor * 0.7))
                    e_max = int(ENERGY_VALUE_MIN + val_range * wave_factor * 1.3)
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


# ==================== 移动方块 ====================

class MovingBlock:
    """自动寻路的移动方块"""

    _COLOR_POOL = [
        (70, 180, 255),    # 蓝
        (255, 100, 100),   # 红
        (100, 255, 100),   # 绿
        (255, 180, 70),    # 橙
        (200, 130, 255),   # 紫
        (255, 255, 100),   # 黄
        (100, 255, 255),   # 青
        (255, 150, 200),   # 粉
        (150, 255, 150),   # 浅绿
        (180, 180, 255),   # 浅紫
        (255, 200, 120),   # 浅橙
        (120, 255, 200),   # 薄荷
        (255, 130, 180),   # 玫红
        (180, 220, 255),   # 天蓝
        (220, 180, 255),   # 薰衣草
    ]

    _next_id = 0

    def __init__(self, x: int, y: int, energy: int, world_size: int,
                 parent_color: Optional[Tuple[int, int, int]] = None):
        self.x = x
        self.y = y
        self.energy = energy
        self.world_size = world_size
        self.steps_taken = 0
        self.total_collected = 0
        self.alive = True
        self.target: Optional[Tuple[int, int]] = None

        # 颜色
        self.id = MovingBlock._next_id
        MovingBlock._next_id += 1
        if parent_color:
            r = min(255, max(30, parent_color[0] + random.randint(-30, 30)))
            g = min(255, max(30, parent_color[1] + random.randint(-30, 30)))
            b = min(255, max(30, parent_color[2] + random.randint(-30, 30)))
            self.color = (r, g, b)
        elif self.id < len(MovingBlock._COLOR_POOL):
            self.color = MovingBlock._COLOR_POOL[self.id]
        else:
            self.color = (random.randint(60, 255),
                          random.randint(60, 255),
                          random.randint(60, 255))
        self.outline_color = (
            max(10, self.color[0] - 50),
            max(10, self.color[1] - 50),
            max(10, self.color[2] - 50),
        )

    def find_nearest_energy(self, world: BlockWorld,
                            occupied: Set[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if not world.energy_positions:
            return None
        best_dist = float('inf')
        best_pos = None
        for ep in world.energy_positions:
            if ep in occupied:
                continue
            dist = abs(ep[0] - self.x) + abs(ep[1] - self.y)
            if dist < best_dist:
                best_dist = dist
                best_pos = ep
        return best_pos

    def get_move_dir_toward(self, tx: int, ty: int) -> Tuple[int, int]:
        dx = tx - self.x
        dy = ty - self.y
        if dx == 0 and dy == 0:
            return (0, 0)
        if abs(dx) >= abs(dy):
            return (1 if dx > 0 else -1, 0)
        else:
            return (0, 1 if dy > 0 else -1)

    def try_move(self, dx: int, dy: int, world: BlockWorld) -> int:
        """
        尝试移动一格。返回：>0 收集到能量, 0 普通移动, -1 失败
        注意：不做 occupied 检查（由调用方负责）
        """
        nx = self.x + dx
        ny = self.y + dy
        if not (0 <= nx < self.world_size and 0 <= ny < self.world_size):
            return -1
        if self.energy < MOVE_COST:
            return -1

        # 执行移动
        old_x, old_y = self.x, self.y
        self.x = nx
        self.y = ny
        self.energy -= MOVE_COST
        self.steps_taken += 1

        # 收集能量
        gained = 0
        if world.is_energy_block(self.x, self.y):
            gained = world.collect_energy(self.x, self.y)
            self.energy += gained
            self.total_collected += gained
            self.target = None

        return gained

    def should_split(self) -> bool:
        return self.energy >= SPLIT_THRESHOLD

    def split(self) -> 'MovingBlock':
        half = self.energy // 2
        self.energy -= half
        offsets = [(1, 0), (-1, 0), (0, 1), (0, -1),
                   (1, 1), (-1, -1), (1, -1), (-1, 1)]
        nx, ny = self.x, self.y
        for ox, oy in offsets:
            tx, ty = self.x + ox, self.y + oy
            if 0 <= tx < self.world_size and 0 <= ty < self.world_size:
                nx, ny = tx, ty
                break
        return MovingBlock(nx, ny, half, self.world_size, parent_color=self.color)


# ==================== 摄像机 ====================

class Camera:
    def __init__(self, world_size: int, view_cols: int, view_rows: int):
        self.world_size = world_size
        self.view_cols = view_cols
        self.view_rows = view_rows
        self.x = world_size // 2 - view_cols // 2
        self.y = world_size // 2 - view_rows // 2

    def update(self, target_x: int, target_y: int):
        self.x = target_x - self.view_cols // 2
        self.y = target_y - self.view_rows // 2
        self.x = max(0, min(self.x, self.world_size - self.view_cols))
        self.y = max(0, min(self.y, self.world_size - self.view_rows))


# ==================== 游戏主控 ====================

class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption(f"{WORLD_SIZE}×{WORLD_SIZE} 方块世界 — 自动寻路 · 分裂")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Consolas", 16)
        self.font_small = pygame.font.SysFont("Consolas", 13)
        self.running = True
        self.game_over_flag = False

        # 世界
        self.world = BlockWorld(WORLD_SIZE)
        primary = MovingBlock(WORLD_SIZE // 2, WORLD_SIZE // 2,
                             INITIAL_ENERGY, WORLD_SIZE)
        self.blocks: List[MovingBlock] = [primary]
        self.camera = Camera(WORLD_SIZE, VIEW_COLS, VIEW_ROWS)

        # 计时器
        self.move_timer = 0.0
        self.energy_spawn_timer = 0.0
        self.energy_wave_time = 0.0  # 能量波动计时

        # 粒子
        self.particles: List[dict] = []

        # 玩家手动移动方向（由 KEYDOWN 设置，auto_move 使用后清空）
        self.player_dx, self.player_dy = 0, 0

        # 统计数据与图表
        self.stats_data: deque = deque(maxlen=STATS_MAX_POINTS)
        self.show_chart = False
        self.stats_tick = 0

        self.world.spawn_energy_blocks(80)

    # ---- 粒子 ----
    def spawn_particles(self, wx: int, wy: int, count: int,
                        color: Tuple[int, int, int]):
        cam = self.camera
        sx = (wx - cam.x) * TILE_SIZE + TILE_SIZE // 2
        sy = (wy - cam.y) * TILE_SIZE + TILE_SIZE // 2
        for _ in range(count):
            angle = random.uniform(0, 6.2832)
            speed = random.uniform(1, 4)
            life = random.uniform(0.3, 0.8)
            self.particles.append({
                'x': sx, 'y': sy,
                'vx': speed * pygame.math.Vector2(1, 0).rotate_rad(angle).x,
                'vy': speed * pygame.math.Vector2(1, 0).rotate_rad(angle).y,
                'life': life, 'max_life': life,
                'color': color,
            })

    # ---- 自动移动（所有方块一步） ----
    def auto_move_blocks(self):
        """所有方块同时走一步（主方块优先按玩家方向）"""
        alive = [b for b in self.blocks if b.alive]
        if not alive:
            self.game_over_flag = True
            return

        primary = alive[0]

        # -----------------------------------------------------
        # 第一步：构建当前占用集合，处理主方块
        # -----------------------------------------------------
        occupied: Set[Tuple[int, int]] = set()
        for b in alive:
            occupied.add((b.x, b.y))

        # 主方块：如果玩家指定了方向，用玩家方向；否则自动寻路
        if self.player_dx != 0 or self.player_dy != 0:
            occupied.discard((primary.x, primary.y))
            gained = primary.try_move(self.player_dx, self.player_dy, self.world)
            self.player_dx, self.player_dy = 0, 0
            if gained >= 0:
                occupied.add((primary.x, primary.y))
                self.camera.update(primary.x, primary.y)
                if gained > 0:
                    self.spawn_particles(primary.x, primary.y, 12, primary.color)
        else:
            # 主方块自动寻路（和其他方块一起处理，在下方循环中）
            pass

        # -----------------------------------------------------
        # 第二步：所有方块（含主方块未手动移动时）自动寻路一步
        # -----------------------------------------------------
        # 重新计算当前占用
        occupied = {(b.x, b.y) for b in self.blocks if b.alive}

        for block in alive:
            # 如果主方块已经在本轮手动移动过，跳过
            if block is primary and (self.player_dx == 0 and self.player_dy == 0):
                # 但主方块还没被手动处理过（没收到方向输入）
                pass

            if block.energy < MOVE_COST:
                continue  # 能量不足 → 站着不动，不扣能量

            # 寻路
            block.target = block.find_nearest_energy(self.world, occupied)
            if block.target is None:
                continue  # 没有能量方块 → 站着不动，不扣能量

            dx, dy = block.get_move_dir_toward(block.target[0], block.target[1])
            if dx == 0 and dy == 0:
                block.target = None
                continue  # 已在目标上（理论上不可能因为能量方块已收集），不扣能

            # 尝试首选方向
            occupied.discard((block.x, block.y))
            gained = block.try_move(dx, dy, self.world)
            occupied.add((block.x, block.y))

            if gained < 0:
                # 边界/能量不足 / 被挡住 → 尝试其他三个方向
                alt_dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
                random.shuffle(alt_dirs)
                moved = False
                for adx, ady in alt_dirs:
                    if (adx, ady) == (dx, dy):
                        continue
                    occupied.discard((block.x, block.y))
                    g2 = block.try_move(adx, ady, self.world)
                    occupied.add((block.x, block.y))
                    if g2 >= 0:
                        gained = g2
                        moved = True
                        break
                if not moved:
                    # 所有方向都不行 → 不动，不扣能量
                    continue

            # 移动成功后更新摄像机（主方块）
            if block is primary:
                self.camera.update(primary.x, primary.y)

            if gained > 0:
                self.spawn_particles(block.x, block.y, 8, block.color)
            elif gained == 0:
                self.spawn_particles(block.x, block.y, 1, block.color)

    # ---- 统计采集 ----
    def collect_stats(self):
        """采集当前帧的统计数据"""
        alive_count = sum(1 for b in self.blocks if b.alive)
        energy_sum = self.world.total_energy_sum()
        energy_count = len(self.world.energy_positions)
        self.stats_data.append((alive_count, energy_sum, energy_count))

    # ---- 更新 ----
    def update(self, dt: float):
        if self.game_over_flag:
            return

        # 1) 自动移动
        self.move_timer += dt
        if self.move_timer >= AUTO_MOVE_INTERVAL:
            self.move_timer -= AUTO_MOVE_INTERVAL
            self.auto_move_blocks()

            # 移动完成后处理分裂与死亡
            new_blocks = []
            for block in self.blocks:
                if block.alive and block.should_split():
                    child = block.split()
                    new_blocks.append(child)
                    self.spawn_particles(block.x, block.y, 20, block.color)
            self.blocks.extend(new_blocks)

            for block in self.blocks:
                if block.alive and block.energy <= 0:
                    block.alive = False
                    self.spawn_particles(block.x, block.y, 15, (255, 80, 80))

            alive = [b for b in self.blocks if b.alive]
            if alive:
                self.blocks = alive
            elif self.blocks:
                self.blocks = [self.blocks[0]]
                self.game_over_flag = True

            # 统计采集（每次自动移动后）
            self.stats_tick += 1
            if self.stats_tick % 2 == 0:  # 每2步采集一次减少噪点
                self.collect_stats()

        # 2) 能量波动与刷新
        self.energy_wave_time += dt
        wave_factor = 0.5 + 0.5 * math.sin(2 * math.pi * self.energy_wave_time / ENERGY_WAVE_PERIOD)
        self.energy_spawn_timer += dt
        if self.energy_spawn_timer >= ENERGY_SPAWN_INTERVAL:
            self.energy_spawn_timer -= ENERGY_SPAWN_INTERVAL
            # 生成数量随波峰波动
            spawn_count = round(ENERGY_SPAWN_BASE + ENERGY_SPAWN_EXTRA * wave_factor)
            self.world.spawn_energy_blocks(spawn_count, wave_factor)

    # ---- 渲染 ----
    def draw_world(self):
        cx = int(self.camera.x)
        cy = int(self.camera.y)
        world = self.world

        self.screen.fill(COLOR_VOID)

        for row in range(VIEW_ROWS + 2):
            wy = cy + row - 1
            for col in range(VIEW_COLS + 2):
                wx = cx + col - 1
                sx = col * TILE_SIZE
                sy = row * TILE_SIZE
                if sx > WINDOW_WIDTH or sy > VIEW_ROWS * TILE_SIZE:
                    continue

                inside = 0 <= wx < WORLD_SIZE and 0 <= wy < WORLD_SIZE
                on_edge = (wx == 0 or wx == WORLD_SIZE - 1 or
                           wy == 0 or wy == WORLD_SIZE - 1) if inside else False

                if inside and not on_edge:
                    val = world.grid[wy][wx]
                    if val == 0:
                        c = COLOR_BLOCK if (wx + wy) % 2 == 0 else COLOR_BLOCK_ALT
                        pygame.draw.rect(self.screen, c, (sx, sy, TILE_SIZE, TILE_SIZE))
                    else:
                        self._draw_energy_tile(sx, sy, val)
                elif inside and on_edge:
                    self._draw_wall_tile(sx, sy)

                if inside and not on_edge and GRID_LINE:
                    pygame.draw.rect(self.screen, COLOR_GRID,
                                     (sx, sy, TILE_SIZE, TILE_SIZE), 1)

        # 绘制移动方块
        for i, block in enumerate(self.blocks):
            if not block.alive:
                continue
            bx = (block.x - cx) * TILE_SIZE
            by = (block.y - cy) * TILE_SIZE

            glow_sz = TILE_SIZE + 6 if i == 0 else TILE_SIZE + 2
            gx = bx - 3 if i == 0 else bx - 1
            gy = by - 3 if i == 0 else by - 1
            pygame.draw.rect(self.screen, (*block.color, 60),
                             (gx, gy, glow_sz, glow_sz), border_radius=4)
            rect = (bx + 2, by + 2, TILE_SIZE - 4, TILE_SIZE - 4)
            pygame.draw.rect(self.screen, block.color, rect, border_radius=4)
            pygame.draw.rect(self.screen, block.outline_color, rect, 2, border_radius=4)
            if i == 0:
                pygame.draw.rect(self.screen, (255, 255, 255),
                                 (bx, by, TILE_SIZE, TILE_SIZE), 2, border_radius=4)

            e_text = self.font_small.render(str(block.energy), True, (255, 255, 255))
            e_rect = e_text.get_rect(center=(bx + TILE_SIZE // 2, by + TILE_SIZE // 2))
            self.screen.blit(e_text, e_rect)

        # 粒子
        for p in self.particles:
            alpha = p['life'] / p['max_life']
            size = max(1, int(5 * alpha))
            c = p['color']
            color = (int(c[0] * alpha), int(c[1] * alpha), int(c[2] * alpha))
            pygame.draw.circle(self.screen, color, (int(p['x']), int(p['y'])), size)

    def _draw_energy_tile(self, sx: int, sy: int, val: int):
        pulse = (pygame.time.get_ticks() % 1000) / 1000.0
        glow_a = 0.4 + 0.3 * pygame.math.Vector2(1, 0).rotate_rad(pulse * 6.2832).x
        gc = (int(COLOR_ENERGY_GLOW[0] * glow_a),
              int(COLOR_ENERGY_GLOW[1] * glow_a),
              int(COLOR_ENERGY_GLOW[2] * glow_a))
        pygame.draw.rect(self.screen, gc, (sx - 2, sy - 2, TILE_SIZE + 4, TILE_SIZE + 4))
        intensity = min(1.0, 0.7 + 0.3 * (val / ENERGY_VALUE_MAX))
        bc = (int(COLOR_ENERGY_BLOCK[0] * intensity),
              int(COLOR_ENERGY_BLOCK[1] * intensity),
              int(COLOR_ENERGY_BLOCK[2] * intensity))
        pygame.draw.rect(self.screen, bc, (sx, sy, TILE_SIZE, TILE_SIZE))
        vt = self.font_small.render(str(val), True, (80, 40, 0))
        vr = vt.get_rect(center=(sx + TILE_SIZE // 2, sy + TILE_SIZE // 2))
        self.screen.blit(vt, vr)

    def _draw_wall_tile(self, sx: int, sy: int):
        pygame.draw.rect(self.screen, COLOR_WALL, (sx, sy, TILE_SIZE, TILE_SIZE))
        pygame.draw.rect(self.screen, COLOR_WALL_DARK,
                         (sx, sy, TILE_SIZE, TILE_SIZE), 1)
        if (sx // TILE_SIZE + sy // TILE_SIZE) % 2 == 0:
            bar = pygame.Rect(sx + 2, sy + 2, TILE_SIZE - 4, TILE_SIZE // 2 - 2)
            pygame.draw.rect(self.screen, COLOR_WALL_DARK, bar)

    def draw_ui(self):
        ui_y = VIEW_ROWS * TILE_SIZE
        pygame.draw.rect(self.screen, COLOR_UI_BG, (0, ui_y, WINDOW_WIDTH, 60))
        pygame.draw.line(self.screen, (60, 60, 80),
                         (0, ui_y), (WINDOW_WIDTH, ui_y), 2)

        alive = [b for b in self.blocks if b.alive]
        primary = alive[0] if alive else (self.blocks[0] if self.blocks else None)
        if primary is None:
            return

        bar_x, bar_y = 15, ui_y + 8
        bar_w, bar_h = 240, 18
        ratio = min(1.0, primary.energy / SPLIT_THRESHOLD)
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (bar_x, bar_y, bar_w, bar_h), border_radius=5)
        if primary.energy > 0:
            fw = int(bar_w * ratio)
            bc = COLOR_ENERGY_BAR if ratio < 0.9 else (255, 100, 100)
            pygame.draw.rect(self.screen, bc, (bar_x, bar_y, fw, bar_h), border_radius=5)
        pygame.draw.rect(self.screen, (100, 100, 120),
                         (bar_x, bar_y, bar_w, bar_h), 2, border_radius=5)
        pygame.draw.line(self.screen, (255, 150, 150),
                         (bar_x + bar_w, bar_y), (bar_x + bar_w, bar_y + bar_h), 2)

        self.screen.blit(
            self.font.render(f"能量: {primary.energy}", True, COLOR_UI_TEXT),
            (bar_x + 5, bar_y + 1))

        alive_count = len(alive)
        total_steps = sum(b.steps_taken for b in self.blocks)
        total_collected = sum(b.total_collected for b in self.blocks)
        self.screen.blit(
            self.font.render(
                f"方块: {alive_count}  步数: {total_steps}  收集: {total_collected}",
                True, COLOR_UI_TEXT),
            (bar_x, bar_y + 22))

        self.screen.blit(
            self.font.render(f"能量方块: {len(self.world.energy_positions)}  总能量: {self.world.total_energy_sum()}",
                             True, COLOR_UI_TEXT),
            (bar_x + 430, bar_y + 22))

        # 波动指示
        wave_factor = 0.5 + 0.5 * math.sin(2 * math.pi * self.energy_wave_time / ENERGY_WAVE_PERIOD)
        wave_bar_w = 50
        wave_ratio = max(0, min(1, wave_factor))
        wave_fill = int(wave_bar_w * wave_ratio)
        wave_x = bar_x + 630
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (wave_x, bar_y + 23, wave_bar_w, 8), border_radius=3)
        if wave_fill > 0:
            wc = (255, int(200 * (1 - wave_factor*0.5)), int(50 * (1 - wave_factor)))
            pygame.draw.rect(self.screen, wc,
                             (wave_x, bar_y + 23, wave_fill, 8), border_radius=3)
        wave_label = self.font_small.render(f"波{wave_factor:.2f}", True, (150, 150, 160))
        self.screen.blit(wave_label, (wave_x + wave_bar_w + 4, bar_y + 20))

        self.screen.blit(
            self.font_small.render(
                "↑↓←/WASD: 手动方向  R: 重开  ESC: 退出",
                True, (150, 150, 160)),
            (bar_x + 430, bar_y + 1))

        if primary.energy >= SPLIT_THRESHOLD * 0.8:
            self.screen.blit(
                self.font_small.render(f"⚡ 即将分裂 ({SPLIT_THRESHOLD})",
                                       True, (255, 180, 80)),
                (bar_x + 300, bar_y + 1))

        if self.game_over_flag:
            gt = self.font.render("所有方块能量耗尽！按 R 重新开始", True, (255, 100, 100))
            gr = gt.get_rect(center=(WINDOW_WIDTH // 2, VIEW_ROWS * TILE_SIZE // 2))
            self.screen.blit(gt, gr)
        else:
            # 显示自动移动状态
            status = self.font_small.render(
                f"⏱ 自动移动中 (每 {AUTO_MOVE_INTERVAL*1000:.0f}ms)",
                True, (120, 200, 120))
            self.screen.blit(status, (bar_x + 140, bar_y + 1))

    # ---- 图表绘制 ----
    def draw_chart(self):
        """绘制折线统计图"""
        data = list(self.stats_data)
        if len(data) < 2:
            return

        # 半透明遮罩
        overlay = pygame.Surface((WINDOW_WIDTH, VIEW_ROWS * TILE_SIZE))
        overlay.set_alpha(170)
        overlay.fill((5, 5, 12))
        self.screen.blit(overlay, (0, 0))

        cx = (WINDOW_WIDTH - CHART_WIDTH) // 2
        cy = (VIEW_ROWS * TILE_SIZE - CHART_HEIGHT) // 2

        # 图表背景
        pygame.draw.rect(self.screen, (18, 18, 32),
                         (cx, cy, CHART_WIDTH, CHART_HEIGHT))
        pygame.draw.rect(self.screen, (60, 60, 80),
                         (cx, cy, CHART_WIDTH, CHART_HEIGHT), 2)

        ml, mr, mt, mb = 65, 30, 40, 55
        pw = CHART_WIDTH - ml - mr
        ph = CHART_HEIGHT - mt - mb

        # Y 轴范围
        all_vals = [v for d in data for v in d]
        max_val = max(max(all_vals), 10)
        # 向上取整到 50 的倍数
        max_val = ((max_val + 49) // 50) * 50
        if max_val < 50:
            max_val = 50

        h_lines = 5
        for i in range(h_lines + 1):
            y_val = max_val * (h_lines - i) // h_lines
            py = cy + mt + ph * i // h_lines
            # 网格横线
            pygame.draw.line(self.screen, CHART_COLOR_GRID,
                             (cx + ml, py), (cx + ml + pw, py), 1)
            # Y 轴标签
            label = self.font_small.render(str(y_val), True, CHART_COLOR_AXIS)
            self.screen.blit(label, (cx + ml - 8 - label.get_width(), py - 6))

        # X 轴刻度
        x_ticks = 5
        for i in range(x_ticks + 1):
            idx = len(data) * i // x_ticks
            if idx >= len(data):
                idx = len(data) - 1
            px = cx + ml + pw * i // x_ticks
            pygame.draw.line(self.screen, CHART_COLOR_GRID,
                             (px, cy + mt), (px, cy + mt + ph), 1)
            label = self.font_small.render(str(idx), True, CHART_COLOR_AXIS)
            lr = label.get_rect(center=(px, cy + mt + ph + 16))
            self.screen.blit(label, lr)

        # 折线绘制
        for col_idx in (0, 1):
            pts = []
            for i, d in enumerate(data):
                val = d[0] if col_idx == 0 else d[1]
                px = cx + ml + (i / max(1, len(data) - 1)) * pw
                py = cy + mt + ph - (val / max_val) * ph
                pts.append((int(px), int(py)))
            color = CHART_COLOR_BLOCKS if col_idx == 0 else CHART_COLOR_ENERGY
            if len(pts) >= 2:
                pygame.draw.lines(self.screen, color, False, pts, 2)

        # 坐标轴边框
        pygame.draw.line(self.screen, CHART_COLOR_AXIS,
                         (cx + ml, cy + mt), (cx + ml, cy + mt + ph), 2)
        pygame.draw.line(self.screen, CHART_COLOR_AXIS,
                         (cx + ml, cy + mt + ph), (cx + ml + pw, cy + mt + ph), 2)

        # 实时数值
        last = data[-1]
        val_label = self.font.render(
            f"当前: 方块 {last[0]} | 总能量 {last[1]} | 能量块 {last[2]}",
            True, CHART_COLOR_AXIS)
        vlr = val_label.get_rect(center=(cx + CHART_WIDTH // 2, cy + mt + ph + 50))
        self.screen.blit(val_label, vlr)

        # 标题
        title = self.font.render("移动方块数 / 能量总和 走势图", True, COLOR_UI_TEXT)
        tr = title.get_rect(center=(cx + CHART_WIDTH // 2, cy + 14))
        self.screen.blit(title, tr)

        # 图例
        leg_y = cy + mt + ph + 32
        leg_items = [
            (CHART_COLOR_BLOCKS, "移动方块数"),
            (CHART_COLOR_ENERGY, "能量总和"),
        ]
        leg_x = cx + ml
        for color, text in leg_items:
            pygame.draw.line(self.screen, color,
                             (leg_x, leg_y - 2), (leg_x + 25, leg_y - 2), 3)
            lbl = self.font_small.render(text, True, COLOR_UI_TEXT)
            self.screen.blit(lbl, (leg_x + 30, leg_y - 9))
            leg_x += 35 + lbl.get_width() + 30

        # 关闭提示
        close_hint = self.font_small.render("按 G 关闭图表", True, (120, 120, 140))
        hr = close_hint.get_rect(right=cx + CHART_WIDTH - mr, top=cy + 8)
        self.screen.blit(close_hint, hr)

    # ---- 主循环 ----
    def restart(self):
        self.world = BlockWorld(WORLD_SIZE)
        primary = MovingBlock(WORLD_SIZE // 2, WORLD_SIZE // 2,
                             INITIAL_ENERGY, WORLD_SIZE)
        self.blocks = [primary]
        self.camera = Camera(WORLD_SIZE, VIEW_COLS, VIEW_ROWS)
        self.move_timer = 0.0
        self.energy_spawn_timer = 0.0
        self.particles.clear()
        self.game_over_flag = False
        self.player_dx, self.player_dy = 0, 0
        self.stats_data.clear()
        self.show_chart = False
        self.stats_tick = 0
        self.energy_wave_time = 0.0
        self.world.spawn_energy_blocks(80)

    def run(self):
        while self.running:
            dt = self.clock.tick(60) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_r:
                        self.restart()
                    elif not self.game_over_flag:
                        # 记录玩家手动方向（auto_move_blocks 中消费）
                        if event.key in (pygame.K_LEFT, pygame.K_a):
                            self.player_dx, self.player_dy = -1, 0
                        elif event.key in (pygame.K_RIGHT, pygame.K_d):
                            self.player_dx, self.player_dy = 1, 0
                        elif event.key in (pygame.K_UP, pygame.K_w):
                            self.player_dx, self.player_dy = 0, -1
                        elif event.key in (pygame.K_DOWN, pygame.K_s):
                            self.player_dx, self.player_dy = 0, 1
                        elif event.key == pygame.K_g:
                            self.show_chart = not self.show_chart

            # 更新粒子
            for p in self.particles[:]:
                p['x'] += p['vx']
                p['y'] += p['vy']
                p['life'] -= dt
                p['vx'] *= 0.97
                p['vy'] *= 0.97
                if p['life'] <= 0:
                    self.particles.remove(p)

            # 更新游戏
            self.update(dt)

            # 渲染
            self.draw_world()
            self.draw_ui()
            if self.show_chart:
                self.draw_chart()
            pygame.display.flip()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = Game()
    game.run()
