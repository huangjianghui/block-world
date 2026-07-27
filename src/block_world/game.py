"""
方块世界 - 游戏主控模块

Game 类整合所有子系统，管理游戏循环、事件处理、渲染与 UI。
"""

import random
import math
import sys
import os
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, List, Optional, Set, Dict

import pygame

from . import config
from .world import BlockWorld
from .entities import MovingBlock
from .camera import Camera


class Game:
    """方块世界游戏主控器"""

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((config.WINDOW_WIDTH, config.WINDOW_HEIGHT))
        pygame.display.set_caption(
            f"{config.WORLD_SIZE}×{config.WORLD_SIZE} 方块世界 — 自动寻路 · 分裂 · 种族演化")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("microsoftyahei, simhei, consolas", 14)
        self.font_small = pygame.font.SysFont("microsoftyahei, simhei, consolas", 10)
        self.running = True
        self.game_over_flag = False

        # ── 世界与实体 ──
        self.world = BlockWorld(config.WORLD_SIZE)
        primary = MovingBlock(config.WORLD_SIZE // 2, config.WORLD_SIZE // 2,
                             config.INITIAL_ENERGY, config.WORLD_SIZE, birth_step=0)
        self.blocks: List[MovingBlock] = [primary]
        self.primary_block = primary
        self.camera = Camera(config.WORLD_SIZE, config.VIEW_COLS, config.VIEW_ROWS)

        # ── 计时器 ──
        self.move_timer = 0.0
        self.energy_spawn_timer = 0.0
        self.energy_wave_time = 0.0

        # ── 粒子 ──
        self.particles: List[dict] = []

        # ── 玩家手动移动方向 ──
        self.player_dx, self.player_dy = 0, 0

        # ── 统计 ──
        self.global_step = 0
        self.survival_times: List[int] = []
        self.stats_data: deque = deque(maxlen=config.STATS_MAX_POINTS)
        self.show_chart = False
        self.show_survival_chart = False
        self.show_race_tree = False
        self.show_race_census = False
        self.stats_tick = 0
        self.race_tree: List[Tuple[str, str, int]] = []  # (父代基因, 子代基因, 世代)

        # ── 种族颜色 ──
        self.race_color_map: Dict[str, Tuple[int, int, int]] = {}
        self._used_color_indices: Set[int] = set()
        self._assign_block_color(primary)

        # ── 种群历史 ──
        self.race_history: deque = deque(maxlen=config.STATS_MAX_POINTS)

        # 初始能量生成
        self.world.spawn_energy_blocks(config.WORLD_SIZE * config.WORLD_SIZE // 50)

    # ===================== 种族颜色管理 =====================

    def _assign_block_color(self, block: MovingBlock):
        """为方块分配种族颜色，新种族从颜色池取未用颜色"""
        if block.race not in self.race_color_map:
            for idx in range(len(config.RACE_COLORS)):
                if idx not in self._used_color_indices:
                    self._used_color_indices.add(idx)
                    self.race_color_map[block.race] = config.RACE_COLORS[idx]
                    break
            else:
                h = 0
                for c in block.race:
                    h = h * 31 + ord(c)
                fallback = (
                    ((h % 7) * 30 + 60),
                    (((h // 7) % 7) * 30 + 60),
                    (((h // 49) % 7) * 30 + 60),
                )
                self.race_color_map[block.race] = fallback
        block.color = self.race_color_map[block.race]
        block.outline_color = (
            max(10, block.color[0] - 50),
            max(10, block.color[1] - 50),
            max(10, block.color[2] - 50),
        )

    def _cleanup_race_colors(self):
        """清理已灭绝种族的颜色映射"""
        alive_races = {b.race for b in self.blocks if b.alive}
        extinct = [r for r in self.race_color_map if r not in alive_races]
        for race in extinct:
            color = self.race_color_map.pop(race)
            for idx, c in enumerate(config.RACE_COLORS):
                if c == color:
                    self._used_color_indices.discard(idx)
                    break

    # ===================== 粒子系统 =====================

    def spawn_particles(self, wx: int, wy: int, count: int,
                        color: Tuple[int, int, int]):
        cam = self.camera
        sx = (wx - cam.x) * config.TILE_SIZE + config.TILE_SIZE // 2
        sy = (wy - cam.y) * config.TILE_SIZE + config.TILE_SIZE // 2
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

    def _update_particles(self, dt: float):
        for p in self.particles[:]:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['life'] -= dt
            p['vx'] *= 0.97
            p['vy'] *= 0.97
            if p['life'] <= 0:
                self.particles.remove(p)

    # ===================== 自动移动（所有方块一步） =====================

    def auto_move_blocks(self):
        """所有方块同时走一步（主方块优先按玩家方向）"""
        self.global_step += 1

        alive = [b for b in self.blocks if b.alive]
        if not alive:
            self.game_over_flag = True
            return

        primary = self.primary_block
        if not primary.alive:
            primary = alive[0] if alive else None
        if primary is None:
            self.game_over_flag = True
            return

        # 第一步：构建当前占用集合，处理主方块
        occupied: Set[Tuple[int, int]] = set()
        for b in alive:
            occupied.add((b.x, b.y))

        player_moved = False
        if self.player_dx != 0 or self.player_dy != 0:
            occupied.discard((primary.x, primary.y))
            gained = primary.try_move(self.player_dx, self.player_dy, self.world)
            self.player_dx, self.player_dy = 0, 0
            if gained >= 0:
                player_moved = True
                occupied.add((primary.x, primary.y))
                self.camera.update(primary.x, primary.y)
                if gained > 0:
                    self.spawn_particles(primary.x, primary.y, 12, primary.color)

        # 第二步：并行预计算所有方块的BFS路径
        occupied = {(b.x, b.y) for b in self.blocks if b.alive}

        bfs_results = {}
        bfs_blocks = [b for b in alive if not (b is primary and player_moved)]
        workers = min(8, os.cpu_count() or 4, len(bfs_blocks))
        if workers >= 2 and len(bfs_blocks) >= 2:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(b.find_path_bfs, self.world, occupied): b
                    for b in bfs_blocks
                }
                for future in as_completed(future_map):
                    try:
                        b = future_map[future]
                        bfs_results[b] = future.result()
                    except Exception:
                        pass
        else:
            for b in bfs_blocks:
                bfs_results[b] = b.find_path_bfs(self.world, occupied)

        # 第三步：所有方块按预计算的路径移动
        for block in bfs_blocks:
            if not block.alive:
                continue

            bfs_dir = bfs_results.get(block)
            if bfs_dir is None:
                alt_dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
                random.shuffle(alt_dirs)
                for adx, ady in alt_dirs:
                    occupied.discard((block.x, block.y))
                    g = block.try_move(adx, ady, self.world)
                    occupied.add((block.x, block.y))
                    if g >= 0:
                        break
                continue

            dx, dy = bfs_dir
            occupied.discard((block.x, block.y))
            gained = block.try_move(dx, dy, self.world)
            occupied.add((block.x, block.y))

            if gained < 0:
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
                    continue

            if block is primary:
                self.camera.update(primary.x, primary.y)

            if gained > 0:
                self.spawn_particles(block.x, block.y, 8, block.color)
            elif gained == 0:
                self.spawn_particles(block.x, block.y, 1, block.color)

        # 捕食判定：同位置不同种族的方块进行攻击力对决
        pos_groups: Dict[Tuple[int, int], List[MovingBlock]] = {}
        for b in self.blocks:
            if b.alive:
                key = (b.x, b.y)
                pos_groups.setdefault(key, []).append(b)
        for pos, group in pos_groups.items():
            if len(group) < 2:
                continue
            race_groups = {}
            for b in group:
                race_groups.setdefault(b.race, []).append(b)
            if len(race_groups) < 2:
                continue
            races = list(race_groups.keys())
            for i in range(len(races)):
                for j in range(i + 1, len(races)):
                    attackers = race_groups[races[i]]
                    defenders = race_groups[races[j]]
                    for atk in attackers:
                        if not atk.alive:
                            continue
                        for dfd in defenders:
                            if not dfd.alive:
                                continue
                            atk_roll = random.uniform(0, max(0.001, atk.attack_power))
                            dfd_roll = random.uniform(0, max(0.001, dfd.attack_power))
                            if atk_roll > dfd_roll:
                                atk.energy += dfd.energy
                                atk.total_collected += dfd.energy
                                dfd.alive = False
                                self.spawn_particles(dfd.x, dfd.y, 15, (255, 80, 80))
                            elif dfd_roll > atk_roll:
                                dfd.energy += atk.energy
                                dfd.total_collected += atk.energy
                                atk.alive = False
                                self.spawn_particles(atk.x, atk.y, 15, (255, 80, 80))

    # ===================== 统计采集 =====================

    def collect_stats(self):
        """采集当前帧的统计数据"""
        alive_count = sum(1 for b in self.blocks if b.alive)
        energy_sum = self.world.total_energy_sum()
        energy_count = len(self.world.energy_positions)
        race_count = len({b.race for b in self.blocks if b.alive})
        self.stats_data.append((alive_count, energy_sum, energy_count, race_count))

        race_pop = {}
        for b in self.blocks:
            if b.alive:
                race_pop[b.race] = race_pop.get(b.race, 0) + 1
        self.race_history.append(race_pop)

    # ===================== 主更新 =====================

    def update(self, dt: float):
        if self.game_over_flag:
            return

        # 1. 自动移动
        self.move_timer += dt
        if self.move_timer >= config.AUTO_MOVE_INTERVAL:
            self.move_timer -= config.AUTO_MOVE_INTERVAL
            self.auto_move_blocks()

            # 移动完成后处理分裂与死亡
            new_blocks = []
            for block in self.blocks:
                if block.alive and block.should_split():
                    child = block.split()
                    child.birth_step = self.global_step
                    self.race_tree.append((block.race, child.race, child.generation))
                    new_blocks.append(child)
                    self.spawn_particles(block.x, block.y, 20, block.color)
            self.blocks.extend(new_blocks)
            for child in new_blocks:
                self._assign_block_color(child)

            # 衰老
            for block in self.blocks:
                if block.alive:
                    block.age += config.AUTO_MOVE_INTERVAL
                    if block.split_cooldown > 0:
                        block.split_cooldown -= config.AUTO_MOVE_INTERVAL
                    if block.age >= config.MATURITY_AGE and block.stage == "young":
                        block.stage = "adult"

            # 寿命耗尽 → 老死
            for block in self.blocks:
                if block.alive and block.max_age > 0 and block.age >= block.max_age:
                    block.alive = False
                    energy_val = max(5, int(block.energy * config.ENERGY_FROM_DEATH_RATIO))
                    self.world.grid[block.y][block.x] += energy_val
                    self.world.energy_positions.add((block.x, block.y))
                    self.spawn_particles(block.x, block.y, 25, (200, 150, 50))
                    self.survival_times.append(self.global_step - block.birth_step)

            # 能量耗尽 → 死亡
            for block in self.blocks:
                death_threshold = max(config.MOVE_COST, config.MOVE_COST * block.energy_efficiency)
                if block.alive and block.energy < death_threshold:
                    block.alive = False
                    self.survival_times.append(self.global_step - block.birth_step)
                    self.spawn_particles(block.x, block.y, 15, (255, 80, 80))

            # 基础代谢消耗
            for block in self.blocks:
                if block.alive:
                    block.energy -= (
                        config.MAINTENANCE_COST
                        + block.attack_power * config.ATTACK_METABOLISM_RATIO
                    )

            alive = [b for b in self.blocks if b.alive]
            if alive:
                self.blocks = alive
            elif self.blocks:
                self.blocks = [self.blocks[0]]
                self.game_over_flag = True

            self._cleanup_race_colors()

            self.stats_tick += 1
            if self.stats_tick % 2 == 0:
                self.collect_stats()

        # 2. 能量波动与刷新
        self.energy_wave_time += dt
        wave_factor = config.compute_wave_factor(self.energy_wave_time)
        self.energy_spawn_timer += dt
        if self.energy_spawn_timer >= config.ENERGY_SPAWN_INTERVAL:
            self.energy_spawn_timer -= config.ENERGY_SPAWN_INTERVAL
            spawn_count = round(config.ENERGY_SPAWN_BASE + config.ENERGY_SPAWN_EXTRA * wave_factor)
            self.world.spawn_energy_blocks(spawn_count, wave_factor)

    # ===================== 渲染：世界 =====================

    def draw_world(self):
        cx = int(self.camera.x)
        cy = int(self.camera.y)
        world = self.world

        self.screen.fill(config.COLOR_VOID)

        for row in range(config.VIEW_ROWS + 2):
            wy = cy + row - 1
            for col in range(config.VIEW_COLS + 2):
                wx = cx + col - 1
                sx = col * config.TILE_SIZE
                sy = row * config.TILE_SIZE
                if sx > config.WINDOW_WIDTH or sy > config.VIEW_ROWS * config.TILE_SIZE:
                    continue

                inside = 0 <= wx < config.WORLD_SIZE and 0 <= wy < config.WORLD_SIZE
                on_edge = (wx == 0 or wx == config.WORLD_SIZE - 1
                           or wy == 0 or wy == config.WORLD_SIZE - 1) if inside else False

                if inside and not on_edge:
                    val = world.grid[wy][wx]
                    if val == 0:
                        c = config.COLOR_BLOCK if (wx + wy) % 2 == 0 else config.COLOR_BLOCK_ALT
                        pygame.draw.rect(self.screen, c, (sx, sy, config.TILE_SIZE, config.TILE_SIZE))
                    else:
                        self._draw_energy_tile(sx, sy, val)
                elif inside and on_edge:
                    self._draw_wall_tile(sx, sy)

                if inside and not on_edge and config.GRID_LINE:
                    pygame.draw.rect(self.screen, config.COLOR_GRID,
                                     (sx, sy, config.TILE_SIZE, config.TILE_SIZE), 1)

        # 绘制移动方块
        for i, block in enumerate(self.blocks):
            if not block.alive:
                continue
            bx = (block.x - cx) * config.TILE_SIZE
            by = (block.y - cy) * config.TILE_SIZE

            glow_sz = config.TILE_SIZE + 6 if i == 0 else config.TILE_SIZE + 2
            gx = bx - 3 if i == 0 else bx - 1
            gy = by - 3 if i == 0 else by - 1
            pygame.draw.rect(self.screen, (*block.color, 60),
                             (gx, gy, glow_sz, glow_sz), border_radius=4)
            rect = (bx + 2, by + 2, config.TILE_SIZE - 4, config.TILE_SIZE - 4)
            pygame.draw.rect(self.screen, block.color, rect, border_radius=4)
            pygame.draw.rect(self.screen, block.outline_color, rect, 2, border_radius=4)
            if i == 0:
                pygame.draw.rect(self.screen, (255, 255, 255),
                                 (bx, by, config.TILE_SIZE, config.TILE_SIZE), 2, border_radius=4)

        # 粒子
        for p in self.particles:
            alpha = p['life'] / p['max_life']
            size = max(1, int(5 * alpha))
            c = p['color']
            color = (int(c[0] * alpha), int(c[1] * alpha), int(c[2] * alpha))
            pygame.draw.circle(self.screen, color, (int(p['x']), int(p['y'])), size)

    def _draw_energy_tile(self, sx: int, sy: int, val: int):
        intensity = min(1.0, 0.7 + 0.3 * (val / config.ENERGY_VALUE_MAX))
        bc = (
            int(config.COLOR_ENERGY_BLOCK[0] * intensity),
            int(config.COLOR_ENERGY_BLOCK[1] * intensity),
            int(config.COLOR_ENERGY_BLOCK[2] * intensity),
        )
        pygame.draw.rect(self.screen, bc, (sx, sy, config.TILE_SIZE, config.TILE_SIZE))
        vt = self.font_small.render(str(val), True, (80, 40, 0))
        vr = vt.get_rect(center=(sx + config.TILE_SIZE // 2, sy + config.TILE_SIZE // 2))
        self.screen.blit(vt, vr)

    def _draw_wall_tile(self, sx: int, sy: int):
        pygame.draw.rect(self.screen, config.COLOR_WALL,
                         (sx, sy, config.TILE_SIZE, config.TILE_SIZE))
        pygame.draw.rect(self.screen, config.COLOR_WALL_DARK,
                         (sx, sy, config.TILE_SIZE, config.TILE_SIZE), 1)
        if (sx // config.TILE_SIZE + sy // config.TILE_SIZE) % 2 == 0:
            bar = pygame.Rect(sx + 2, sy + 2,
                              config.TILE_SIZE - 4, config.TILE_SIZE // 2 - 2)
            pygame.draw.rect(self.screen, config.COLOR_WALL_DARK, bar)

    # ===================== 渲染：UI =====================

    def draw_ui(self):
        ui_y = config.VIEW_ROWS * config.TILE_SIZE
        pygame.draw.rect(self.screen, config.COLOR_UI_BG,
                         (0, ui_y, config.WINDOW_WIDTH, 60))
        pygame.draw.line(self.screen, (60, 60, 80),
                         (0, ui_y), (config.WINDOW_WIDTH, ui_y), 2)

        alive = [b for b in self.blocks if b.alive]
        primary = alive[0] if alive else (self.blocks[0] if self.blocks else None)
        if primary is None:
            return

        bar_x, bar_y = 15, ui_y + 8
        bar_w, bar_h = 240, 18
        ratio = min(1.0, primary.energy / config.SPLIT_THRESHOLD)
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (bar_x, bar_y, bar_w, bar_h), border_radius=5)
        if primary.energy > 0:
            fw = int(bar_w * ratio)
            bc = config.COLOR_ENERGY_BAR if ratio < 0.9 else (255, 100, 100)
            pygame.draw.rect(self.screen, bc, (bar_x, bar_y, fw, bar_h), border_radius=5)
        pygame.draw.rect(self.screen, (100, 100, 120),
                         (bar_x, bar_y, bar_w, bar_h), 2, border_radius=5)
        pygame.draw.line(self.screen, (255, 150, 150),
                         (bar_x + bar_w, bar_y), (bar_x + bar_w, bar_y + bar_h), 2)

        self.screen.blit(
            self.font.render(f"能量: {primary.energy:.0f}", True, config.COLOR_UI_TEXT),
            (bar_x + 5, bar_y + 1))

        alive_count = len(alive)
        self.screen.blit(
            self.font.render(f"方块: {alive_count}", True, config.COLOR_UI_TEXT),
            (bar_x, bar_y + 22))

        race_count = len({b.race for b in alive})
        self.screen.blit(
            self.font_small.render(f"种族: {race_count}", True, (180, 180, 200)),
            (bar_x + 120, bar_y + 22))

        self.screen.blit(
            self.font_small.render(
                f"世代:G{primary.generation}  "
                f"种族:{primary.race}  "
                f"效率:{primary.energy_efficiency:.2f}",
                True, (150, 200, 150)),
            (bar_x + 430, bar_y + 22))

        speed_text = (f"速度:{primary.move_speed:.1f}  攻击:{primary.attack_power}  "
                      f"步数:{primary.steps_taken}")
        self.screen.blit(
            self.font_small.render(speed_text, True, (150, 200, 150)),
            (bar_x + 430, bar_y + 1))

        self.screen.blit(
            self.font.render(
                f"能量方块: {len(self.world.energy_positions)}  "
                f"总能量: {self.world.total_energy_sum()}",
                True, config.COLOR_UI_TEXT),
            (bar_x + 430, bar_y + 22))

        # 波动指示
        wave_factor = config.compute_wave_factor(self.energy_wave_time)
        wave_bar_w = 50
        wave_ratio = max(0, min(1, wave_factor))
        wave_fill = int(wave_bar_w * wave_ratio)
        wave_x = bar_x + 630
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (wave_x, bar_y + 23, wave_bar_w, 8), border_radius=3)
        if wave_fill > 0:
            wc = (255, int(200 * (1 - wave_factor * 0.5)),
                  int(50 * (1 - wave_factor)))
            pygame.draw.rect(self.screen, wc,
                             (wave_x, bar_y + 23, wave_fill, 8), border_radius=3)
        wave_label = self.font_small.render(f"波{wave_factor:.2f}", True, (150, 150, 160))
        self.screen.blit(wave_label, (wave_x + wave_bar_w + 4, bar_y + 20))

        self.screen.blit(
            self.font_small.render(
                "↑↓←/WASD:手动方向  R:重开  G:图表  H:存活  T:种族树  C:统计  ESC:退出",
                True, (150, 150, 160)),
            (bar_x + 430, bar_y + 1))

        if primary.stage == "adult" and primary.energy >= config.SPLIT_THRESHOLD:
            self.screen.blit(
                self.font_small.render(f"⚡ 可分裂 (消耗{config.SPLIT_ENERGY})",
                                       True, (255, 180, 80)),
                (bar_x + 300, bar_y + 1))

        if self.game_over_flag:
            gt = self.font.render("所有方块能量耗尽！按 R 重新开始", True, (255, 100, 100))
            gr = gt.get_rect(center=(config.WINDOW_WIDTH // 2,
                                     config.VIEW_ROWS * config.TILE_SIZE // 2))
            self.screen.blit(gt, gr)
        else:
            status = self.font_small.render(
                f"⏱ 自动移动中 (每 {config.AUTO_MOVE_INTERVAL * 1000:.0f}ms)",
                True, (120, 200, 120))
            self.screen.blit(status, (bar_x + 140, bar_y + 1))

    # ===================== 渲染：图表 =====================

    def draw_chart(self):
        """绘制双 Y 轴折线统计图 + 种族走势"""
        data = list(self.stats_data)
        if len(data) < 2:
            return

        overlay = pygame.Surface((config.WINDOW_WIDTH,
                                  config.VIEW_ROWS * config.TILE_SIZE))
        overlay.set_alpha(170)
        overlay.fill((5, 5, 12))
        self.screen.blit(overlay, (0, 0))

        cx = (config.WINDOW_WIDTH - config.CHART_WIDTH) // 2
        cy = (config.VIEW_ROWS * config.TILE_SIZE - config.CHART_HEIGHT) // 2

        pygame.draw.rect(self.screen, (18, 18, 32),
                         (cx, cy, config.CHART_WIDTH, config.CHART_HEIGHT))
        pygame.draw.rect(self.screen, (60, 60, 80),
                         (cx, cy, config.CHART_WIDTH, config.CHART_HEIGHT), 2)

        ml, mr, mt, mb = 65, 30, 40, 55
        pw = config.CHART_WIDTH - ml - mr
        ph = config.CHART_HEIGHT - mt - mb

        block_vals = [d[0] for d in data]
        max_blocks = max(max(block_vals), 5)
        max_blocks = ((max_blocks + 4) // 5) * 5
        if max_blocks < 5:
            max_blocks = 5

        energy_vals = [d[1] for d in data]
        max_energy = max(max(energy_vals), 50)
        max_energy = ((max_energy + 49) // 50) * 50
        if max_energy < 50:
            max_energy = 50

        h_lines = 5
        for i in range(h_lines + 1):
            block_val = max_blocks * (h_lines - i) // h_lines
            py = cy + mt + ph * i // h_lines
            pygame.draw.line(self.screen, config.CHART_COLOR_GRID,
                             (cx + ml, py), (cx + ml + pw, py), 1)
            b_label = self.font_small.render(str(block_val), True,
                                             config.CHART_COLOR_BLOCKS)
            self.screen.blit(b_label, (cx + ml - 8 - b_label.get_width(), py - 6))
            energy_val = max_energy * (h_lines - i) // h_lines
            e_label = self.font_small.render(str(energy_val), True,
                                             config.CHART_COLOR_ENERGY)
            self.screen.blit(e_label, (cx + ml + pw + 6, py - 6))

        x_ticks = 5
        for i in range(x_ticks + 1):
            idx = len(data) * i // x_ticks
            if idx >= len(data):
                idx = len(data) - 1
            px = cx + ml + pw * i // x_ticks
            pygame.draw.line(self.screen, config.CHART_COLOR_GRID,
                             (px, cy + mt), (px, cy + mt + ph), 1)
            label = self.font_small.render(str(idx), True, config.CHART_COLOR_AXIS)
            lr = label.get_rect(center=(px, cy + mt + ph + 16))
            self.screen.blit(label, lr)

        # 折线：方块数（左轴）
        pts = []
        for i, d in enumerate(data):
            val = d[0]
            px = cx + ml + (i / max(1, len(data) - 1)) * pw
            py = cy + mt + ph - (val / max_blocks) * ph
            pts.append((int(px), int(py)))
        if len(pts) >= 2:
            pygame.draw.lines(self.screen, config.CHART_COLOR_BLOCKS, False, pts, 2)

        # 折线：能量总和（右轴）
        pts = []
        for i, d in enumerate(data):
            val = d[1]
            px = cx + ml + (i / max(1, len(data) - 1)) * pw
            py = cy + mt + ph - (val / max_energy) * ph
            pts.append((int(px), int(py)))
        if len(pts) >= 2:
            pygame.draw.lines(self.screen, config.CHART_COLOR_ENERGY, False, pts, 2)

        # 种族走势（至多5种）
        race_data = list(self.race_history)
        if race_data:
            latest_races = sorted(race_data[-1].items(),
                                  key=lambda x: -x[1])[:5]
            for race, _ in latest_races:
                color = self.race_color_map.get(race, (180, 180, 180))
                pts = []
                for i, pop in enumerate(race_data):
                    val = pop.get(race, 0)
                    px = cx + ml + (i / max(1, len(race_data) - 1)) * pw
                    py = cy + mt + ph - (val / max_blocks) * ph
                    pts.append((int(px), int(py)))
                if len(pts) >= 2:
                    pygame.draw.lines(self.screen, color, False, pts, 1)

        # 坐标轴
        pygame.draw.line(self.screen, config.CHART_COLOR_AXIS,
                         (cx + ml, cy + mt), (cx + ml, cy + mt + ph), 2)
        pygame.draw.line(self.screen, config.CHART_COLOR_AXIS,
                         (cx + ml, cy + mt + ph), (cx + ml + pw, cy + mt + ph), 2)
        pygame.draw.line(self.screen, config.CHART_COLOR_ENERGY,
                         (cx + ml + pw, cy + mt), (cx + ml + pw, cy + mt + ph), 2)

        last = data[-1]
        val_label = self.font.render(
            f"当前: 方块 {last[0]}  |  总能量 {last[1]}  |  能量块 {last[2]}  |  种族 {last[3]}",
            True, config.CHART_COLOR_AXIS)
        vlr = val_label.get_rect(
            center=(cx + config.CHART_WIDTH // 2, cy + mt + ph + 50))
        self.screen.blit(val_label, vlr)

        title = self.font.render("方块数量 / 能量总和 走势图", True, config.COLOR_UI_TEXT)
        tr = title.get_rect(center=(cx + config.CHART_WIDTH // 2, cy + 14))
        self.screen.blit(title, tr)

        leg_y = cy + mt + ph + 32
        leg_items = [
            (config.CHART_COLOR_BLOCKS, "方块数（左轴）"),
            (config.CHART_COLOR_ENERGY, "能量总和（右轴）"),
        ]
        if race_data:
            for race, _ in latest_races:
                c = self.race_color_map.get(race, (180, 180, 180))
                leg_items.append((c, race))
        leg_x = cx + ml
        for color, text in leg_items:
            pygame.draw.line(self.screen, color,
                             (leg_x, leg_y - 2), (leg_x + 25, leg_y - 2), 3)
            lbl = self.font_small.render(text, True, config.COLOR_UI_TEXT)
            self.screen.blit(lbl, (leg_x + 30, leg_y - 9))
            leg_x += 35 + lbl.get_width() + 30

        close_hint = self.font_small.render("按 G 关闭图表", True, (120, 120, 140))
        hr = close_hint.get_rect(right=cx + config.CHART_WIDTH - mr, top=cy + 8)
        self.screen.blit(close_hint, hr)

    # ===================== 渲染：存活分布 =====================

    def draw_survival_chart(self):
        """绘制方块存活时间分布直方图"""
        if not self.survival_times:
            overlay = pygame.Surface((config.WINDOW_WIDTH,
                                      config.VIEW_ROWS * config.TILE_SIZE))
            overlay.set_alpha(170)
            overlay.fill((5, 5, 12))
            self.screen.blit(overlay, (0, 0))
            msg = self.font.render(
                "尚无死亡记录，等待方块自然死亡后查看", True, (180, 180, 180))
            mr = msg.get_rect(
                center=(config.WINDOW_WIDTH // 2,
                        config.VIEW_ROWS * config.TILE_SIZE // 2))
            self.screen.blit(msg, mr)
            close_hint = self.font_small.render("按 H 关闭分布图", True, (120, 120, 140))
            hr = close_hint.get_rect(right=config.WINDOW_WIDTH - 30, top=10)
            self.screen.blit(close_hint, hr)
            return

        overlay = pygame.Surface((config.WINDOW_WIDTH,
                                  config.VIEW_ROWS * config.TILE_SIZE))
        overlay.set_alpha(170)
        overlay.fill((5, 5, 12))
        self.screen.blit(overlay, (0, 0))

        cx = (config.WINDOW_WIDTH - config.CHART_WIDTH) // 2
        cy = (config.VIEW_ROWS * config.TILE_SIZE - config.CHART_HEIGHT) // 2

        pygame.draw.rect(self.screen, (18, 18, 32),
                         (cx, cy, config.CHART_WIDTH, config.CHART_HEIGHT))
        pygame.draw.rect(self.screen, (60, 60, 80),
                         (cx, cy, config.CHART_WIDTH, config.CHART_HEIGHT), 2)

        ml, mr, mt, mb = 65, 30, 40, 55
        pw = config.CHART_WIDTH - ml - mr
        ph = config.CHART_HEIGHT - mt - mb

        max_time = max(self.survival_times)
        num_bins = min(40, max(5, max_time // 5 + 1))
        bin_size = max(1, (max_time + num_bins - 1) // num_bins)

        bins = [0] * num_bins
        for t in self.survival_times:
            idx = min(t // bin_size, num_bins - 1)
            bins[idx] += 1

        max_count = max(bins) or 1

        for i in range(6):
            y_val = max_count * (5 - i) // 5
            py = cy + mt + ph * i // 5
            pygame.draw.line(self.screen, config.CHART_COLOR_GRID,
                             (cx + ml, py), (cx + ml + pw, py), 1)
            label = self.font_small.render(str(y_val), True, config.CHART_COLOR_AXIS)
            self.screen.blit(label, (cx + ml - 8 - label.get_width(), py - 6))

        bar_w = max(2, pw // num_bins - 1)
        for i, count in enumerate(bins):
            if count == 0:
                continue
            bar_h = int((count / max_count) * ph)
            bx = cx + ml + (i * pw // num_bins)
            by = cy + mt + ph - bar_h
            intensity = 0.35 + 0.65 * (count / max_count)
            color = (int(70 * intensity), int(200 * intensity), int(120 * intensity))
            pygame.draw.rect(self.screen, color, (bx, by, max(bar_w, 1), bar_h))

        max_label_idx = num_bins - 1
        x_ticks = min(10, num_bins)
        for i in range(x_ticks + 1):
            idx = int(i * max_label_idx / x_ticks)
            if idx >= num_bins:
                idx = num_bins - 1
            label_val = idx * bin_size
            px = cx + ml + (idx * pw // num_bins) + bar_w // 2
            label = self.font_small.render(str(label_val), True, config.CHART_COLOR_AXIS)
            lr = label.get_rect(center=(px, cy + mt + ph + 16))
            self.screen.blit(label, lr)

        pygame.draw.line(self.screen, config.CHART_COLOR_AXIS,
                         (cx + ml, cy + mt), (cx + ml, cy + mt + ph), 2)
        pygame.draw.line(self.screen, config.CHART_COLOR_AXIS,
                         (cx + ml, cy + mt + ph), (cx + ml + pw, cy + mt + ph), 2)

        avg_time = sum(self.survival_times) / len(self.survival_times)
        if len(self.survival_times) >= 2:
            sorted_st = sorted(self.survival_times)
            mid = len(sorted_st) // 2
            median_time = (sorted_st[mid] if len(sorted_st) % 2
                           else (sorted_st[mid - 1] + sorted_st[mid]) / 2)
        else:
            median_time = avg_time

        info = self.font.render(
            f"方块存活时间分布 | 样本: {len(self.survival_times)}  | "
            f"平均: {avg_time:.1f}步  | 中位数: {median_time:.0f}步  | "
            f"最长: {max_time}步",
            True, config.COLOR_UI_TEXT)
        ir = info.get_rect(center=(cx + config.CHART_WIDTH // 2, cy + 14))
        self.screen.blit(info, ir)

        leg_y = cy + mt + ph + 38
        pygame.draw.rect(self.screen, (70, 200, 120), (cx + ml, leg_y - 10, 20, 12))
        lbl = self.font_small.render("方块数 (柱高)", True, config.COLOR_UI_TEXT)
        self.screen.blit(lbl, (cx + ml + 26, leg_y - 9))

        close_hint = self.font_small.render("按 H 关闭分布图", True, (120, 120, 140))
        hr = close_hint.get_rect(right=cx + config.CHART_WIDTH - mr, top=cy + 8)
        self.screen.blit(close_hint, hr)

    # ===================== 渲染：种族演化树 =====================

    def draw_race_tree(self):
        """绘制种族演化树"""
        if len(self.race_tree) < 1:
            return

        overlay = pygame.Surface((config.WINDOW_WIDTH,
                                  config.VIEW_ROWS * config.TILE_SIZE))
        overlay.set_alpha(200)
        overlay.fill((5, 5, 12))
        self.screen.blit(overlay, (0, 0))

        gen_of = {}
        for parent, child, gen in self.race_tree:
            if child not in gen_of or gen < gen_of[child]:
                gen_of[child] = gen
            if parent not in gen_of or gen - 1 < gen_of[parent]:
                gen_of[parent] = gen - 1
        if self.race_tree:
            gen_of[self.race_tree[0][0]] = 0

        max_gen = max(gen_of.values()) if gen_of else 0
        gen_groups = {}
        for race, gen in gen_of.items():
            gen_groups.setdefault(gen, []).append(race)

        pad = 20
        node_r = 18
        v_sp = (config.VIEW_ROWS * config.TILE_SIZE - pad * 2) // max(1, max_gen + 1)
        aw = config.WINDOW_WIDTH - pad * 2

        color_map = {}
        for race in gen_of:
            if race in self.race_color_map:
                color_map[race] = self.race_color_map[race]
            else:
                h = 0
                for c in race:
                    h = h * 31 + ord(c)
                color_map[race] = (
                    ((h % 7) * 30 + 60),
                    (((h // 7) % 7) * 30 + 60),
                    (((h // 49) % 7) * 30 + 60),
                )

        x_pos = {}
        for gen in sorted(gen_groups.keys()):
            races = gen_groups[gen]
            cnt = len(races)
            for i, race in enumerate(races):
                x_pos[race] = pad + aw * (i + 1) // (cnt + 1)

        for parent, child, _ in self.race_tree:
            if parent in x_pos and child in x_pos:
                px = x_pos[parent]
                py = pad + gen_of[parent] * v_sp + v_sp // 2
                cx = x_pos[child]
                cy = pad + gen_of[child] * v_sp + v_sp // 2
                pygame.draw.line(self.screen, (80, 80, 100), (px, py), (cx, cy), 2)

        title = self.font.render(
            f"种族演化树 (共{len(gen_of)}个种族)", True, (200, 200, 220))
        tr = title.get_rect(center=(config.WINDOW_WIDTH // 2, 8))
        self.screen.blit(title, tr)

        for race, gen in gen_of.items():
            x = x_pos[race]
            y = pad + gen * v_sp + v_sp // 2
            c = color_map[race]
            pygame.draw.circle(self.screen, c, (x, y), node_r)
            pygame.draw.circle(self.screen, (255, 255, 255), (x, y), node_r, 2)
            label = self.font_small.render(race, True, (255, 255, 255))
            lr = label.get_rect(center=(x, y))
            self.screen.blit(label, lr)
            gl = self.font_small.render(f"G{gen}", True, (180, 180, 200))
            self.screen.blit(gl, (x + node_r + 4, y - 6))

        close_hint = self.font_small.render("按 T 关闭种族树", True, (120, 120, 140))
        hr = close_hint.get_rect(right=config.WINDOW_WIDTH - 20, top=8)
        self.screen.blit(close_hint, hr)

    # ===================== 渲染：种族统计 =====================

    def draw_race_census(self):
        """绘制种族统计"""
        race_counts = {}
        for b in self.blocks:
            if b.alive:
                race_counts[b.race] = race_counts.get(b.race, 0) + 1
        if not race_counts:
            return

        race_sorted = sorted(race_counts.items(), key=lambda x: -x[1])

        overlay = pygame.Surface((config.WINDOW_WIDTH,
                                  config.VIEW_ROWS * config.TILE_SIZE))
        overlay.set_alpha(200)
        overlay.fill((5, 5, 12))
        self.screen.blit(overlay, (0, 0))

        total_blocks = sum(c for _, c in race_sorted)
        title = self.font.render(
            f"种族统计 ({len(race_sorted)}种  {total_blocks}个方块)",
            True, (200, 200, 220))
        tr = title.get_rect(center=(config.WINDOW_WIDTH // 2, 10))
        self.screen.blit(title, tr)

        start_x = 60
        start_y = 36
        line_h = 18
        max_rows = (config.VIEW_ROWS * config.TILE_SIZE - start_y) // line_h - 2

        for idx, (race, count) in enumerate(race_sorted):
            if idx >= max_rows:
                self.screen.blit(
                    self.font_small.render(
                        f"... 还有{len(race_sorted) - max_rows}种",
                        True, (120, 120, 140)),
                    (start_x, start_y + idx * line_h))
                break
            y = start_y + (idx + 1) * line_h
            dot_color = self.race_color_map.get(race, (180, 180, 180))
            pygame.draw.circle(self.screen, dot_color, (start_x + 8, y + 5), 5)
            text = f"{race}  x{count}"
            if count > 1:
                text += f"  ({100 * count // total_blocks}%)"
            lbl = self.font_small.render(text, True, (220, 220, 230))
            self.screen.blit(lbl, (start_x + 20, y))

        close_hint = self.font_small.render("按 C 关闭种族统计", True, (120, 120, 140))
        hr = close_hint.get_rect(right=config.WINDOW_WIDTH - 20, top=8)
        self.screen.blit(close_hint, hr)

    # ===================== 主循环 =====================

    def restart(self):
        self.world = BlockWorld(config.WORLD_SIZE)
        primary = MovingBlock(config.WORLD_SIZE // 2, config.WORLD_SIZE // 2,
                             config.INITIAL_ENERGY, config.WORLD_SIZE, birth_step=0)
        self.blocks = [primary]
        self.primary_block = primary
        self.camera = Camera(config.WORLD_SIZE, config.VIEW_COLS, config.VIEW_ROWS)
        self.move_timer = 0.0
        self.energy_spawn_timer = 0.0
        self.particles.clear()
        self.game_over_flag = False
        self.player_dx, self.player_dy = 0, 0
        self.global_step = 0
        self.survival_times.clear()
        self.stats_data.clear()
        self.show_chart = False
        self.show_survival_chart = False
        self.stats_tick = 0
        self.energy_wave_time = 0.0
        self.race_tree.clear()
        self.show_race_tree = False
        self.show_race_census = False
        self.race_color_map.clear()
        self._used_color_indices.clear()
        self._assign_block_color(primary)
        self.race_history.clear()
        self.world.spawn_energy_blocks(config.WORLD_SIZE * config.WORLD_SIZE // 50)

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_r:
                    self.restart()
                elif not self.game_over_flag:
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
                    elif event.key == pygame.K_h:
                        self.show_survival_chart = not self.show_survival_chart
                    elif event.key == pygame.K_t:
                        self.show_race_tree = not self.show_race_tree
                    elif event.key == pygame.K_c:
                        self.show_race_census = not self.show_race_census

    def run(self):
        while self.running:
            dt = self.clock.tick(0) / 1000.0

            self._handle_events()
            self._update_particles(dt)
            self.update(dt)

            self.draw_world()
            self.draw_ui()
            if self.show_chart:
                self.draw_chart()
            if self.show_survival_chart:
                self.draw_survival_chart()
            if self.show_race_tree:
                self.draw_race_tree()
            if self.show_race_census:
                self.draw_race_census()

            pygame.display.flip()

        pygame.quit()
        sys.exit()
