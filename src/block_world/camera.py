"""
方块世界 - 摄像机（视口滚动）

管理游戏世界的视口偏移，使主方块居中显示。
"""


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
