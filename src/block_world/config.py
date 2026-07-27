"""
方块世界 - 游戏常量与配置

所有可调参数集中管理，便于调优与维护。
"""

import math

# ==================== 世界尺寸 ====================
WORLD_SIZE = 64
# TILE_SIZE 自动适配：使网格区保持在约 880px 宽，限制 8~32px
TILE_SIZE = max(8, min(32, 880 // WORLD_SIZE))

VIEW_COLS = WORLD_SIZE
VIEW_ROWS = WORLD_SIZE
WINDOW_WIDTH = VIEW_COLS * TILE_SIZE
WINDOW_HEIGHT = VIEW_ROWS * TILE_SIZE + 60  # 底部信息栏

# ==================== 颜色 ====================
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
GRID_LINE = True

# ==================== 游戏参数 ====================
INITIAL_ENERGY = 50
MATURITY_AGE = 2.0              # 幼年→成年所需时间（秒）
SPLIT_ENERGY = 50               # 分裂时子代获得能量
MOVE_COST = 1
MAINTENANCE_COST = 0.5          # 每步基础代谢消耗

# ==================== 能量波动参数（正弦周期） ====================
ENERGY_WAVE_PERIOD = 120        # 完整波周期（秒）
ENERGY_VALUE_MIN = 2            # 波谷时每个能量块最低值
ENERGY_VALUE_MAX = 64           # 波峰时每个能量块最高值
ENERGY_SPAWN_BASE = WORLD_SIZE * WORLD_SIZE * 0.02     # 波谷时每次生成数量
ENERGY_SPAWN_EXTRA = WORLD_SIZE * WORLD_SIZE * 0.1    # 波峰额外增加数量

# ==================== 定时器 ====================
AUTO_MOVE_INTERVAL = 0.2        # 自动移动间隔（秒）
ENERGY_SPAWN_INTERVAL = 2.0     # 能量刷新间隔（秒）
ENERGY_SPAWN_PER_TICK = 5
MAX_ENERGY_BLOCKS = WORLD_SIZE * WORLD_SIZE // 2   # 能量方块上限约占网格 12.5%

# ==================== 分裂 ====================
SPLIT_THRESHOLD = 100           # 方块分裂所需的能量
SPLIT_COOLDOWN = 8.0            # 分裂冷却时间（秒）

# ==================== 寿命 ====================
LIFESPAN_BASE = 120             # 方块寿命上限基准值（秒）
LIFESPAN_VARIANCE = 30          # 寿命波动范围（秒）
ENERGY_FROM_DEATH_RATIO = 0.5   # 老死时转化为能量块的比例

# ==================== 攻击力 ====================
ATTACK_METABOLISM_RATIO = 0.3   # 每点攻击力增加的每步代谢消耗

# ==================== 种族系统 ====================
RACE_GENE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RACE_CODE_LENGTH = 4
RACE_MUTATION_RATE = 0.01       # 分裂时每个基因位点的突变概率

# 种族颜色池（36种高区分度颜色）
RACE_COLORS = [
    (255, 80, 80), (80, 200, 80), (80, 140, 255), (255, 200, 50),
    (200, 100, 255), (50, 220, 220), (255, 150, 50), (150, 255, 100),
    (100, 100, 255), (255, 100, 200), (100, 255, 200), (200, 180, 80),
    (200, 80, 180), (80, 180, 200), (255, 180, 180), (180, 255, 180),
    (180, 180, 255), (255, 220, 120), (120, 255, 220), (220, 120, 255),
    (255, 140, 120), (120, 200, 140), (140, 120, 255), (200, 200, 80),
    (80, 200, 140), (200, 140, 200), (140, 200, 80), (200, 120, 140),
    (120, 180, 200), (200, 200, 140), (255, 160, 160), (160, 255, 160),
    (160, 160, 255), (255, 200, 160), (160, 200, 255), (200, 160, 255),
]

# ==================== 统计图表 ====================
STATS_MAX_POINTS = 1000         # 保存最近多少帧的统计
CHART_WIDTH = min(900, max(300, WINDOW_WIDTH - 40))
CHART_HEIGHT = min(500, max(200, VIEW_ROWS * TILE_SIZE - 40))
CHART_COLOR_BLOCKS = (70, 180, 255)       # 方块数线条颜色
CHART_COLOR_ENERGY = (255, 215, 0)        # 能量块数线条颜色
CHART_COLOR_GRID = (50, 50, 65)
CHART_COLOR_AXIS = (100, 100, 120)


def compute_wave_factor(elapsed_time: float) -> float:
    """根据已流逝时间计算能量波动因子（0~1 正弦波）"""
    return 0.5 + 0.5 * math.sin(2 * math.pi * elapsed_time / ENERGY_WAVE_PERIOD)
