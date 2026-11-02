#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""墙体 / 可通行 标注工具（给《AI 中转站》画行走网格）。

用法：
    python3 tools/map_editor.py              # 打开编辑器
    python3 tools/map_editor.py --check      # 不开窗口，只检查已保存的掩码

界面：
    左边是公寓俯视图（默认 1.5 倍放大，能看清房间和家具），
    红色半透明块 = 你涂的墙；没涂的地方一律「可走」。
    右边是小地图 + 图例 + 快捷键。

画法：
    左键拖动 = 涂墙        右键拖动 = 擦掉        Shift+左键拖动 = 矩形涂墙
    1 / 2    = 涂墙 / 擦除   V = 在光标处切换       U = 撤销   C = 清空
    G 网格   H 标注（房间名/门/工位）  T 底图开关
    Z 缩放（1.0 → 1.5 → 2.0）   ↑↓←→ / WASD 平移   F 回正   Esc 退出
    S 保存（assets/walkmask.json + 预览图）      L 重新读取

保存格式（16px 一格，60 x 45）：
    {"cell": 16, "cols": 60, "rows": 45, "walls": [[cx, cy], ...], "note": "..."}
    没写进 walls 的格子一律当「可走」。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

import game  # noqa: E402

CELL = 16
COLS, ROWS = game.WW // CELL, game.WH // CELL      # 60 x 45
MASK_PATH = os.path.join(ROOT, 'assets', 'walkmask.json')
PREVIEW_PATH = os.path.join(ROOT, 'assets', 'walkmask_preview.png')

C_WALL = (236, 96, 104)
C_WALK = (120, 220, 160)
C_GRID = (64, 72, 92)
C_GRID4 = (96, 106, 132)
C_DOOR = (255, 120, 220)
C_STATION = (150, 235, 185)
C_DEVICE = (255, 200, 120)

# 房间名（场景坐标，标在人脚下）
# (名字, x, y)：y 是标签顶边。工位的标签放在脚下，房间的放房间上空
ROOM_LABELS = [
    ('DeepSeek', 330, 128), ('ChatGPT', 300, 276), ('Gemini', 372, 412),
    ('Claude', 330, 548), ('Grok', 700, 274), ('GLM', 660, 416), ('Qwen', 620, 550),
    ('客厅', 540, 42), ('厨房', 735, 42), ('阳台', 855, 42),
    ('门厅', 250, 572), ('楼梯间', 382, 572), ('早餐铺', 96, 482),
]

ZOOMS = [1.0, 1.5, 2.0]


def load_mask(path=MASK_PATH):
    """读掩码；没有文件就返回空集合（= 全都可走）。"""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        cell = int(d.get('cell', CELL))
        if cell != CELL:
            print(f'警告：掩码 cell={cell}，本工具按 {CELL} 读，可能对不上')
        return {(int(x), int(y)) for x, y in d.get('walls', [])}
    except (OSError, ValueError, TypeError) as e:
        print('读掩码失败：', e)
        return set()


def save_mask(walls, path=MASK_PATH, note=''):
    d = dict(cell=CELL, cols=COLS, rows=ROWS,
             walls=[[x, y] for x, y in sorted(walls)], note=note)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    print(f'已保存 {len(walls)} 个墙格 -> {path}')


def cell_rect(cx, cy):
    return pygame.Rect(cx * CELL, cy * CELL, CELL, CELL)


class Editor:
    def __init__(self, path=MASK_PATH):
        pygame.init()
        pygame.display.set_caption('AI 中转站 · 行走网格标注  (左键涂墙 / 右键擦 / Z 放大)')
        self.screen = pygame.display.set_mode((game.SW, game.SH))
        self.clock = pygame.time.Clock()
        self.assets = game.Assets()
        self.path = path
        self.walls = load_mask(path)
        self.mode = 'wall'
        self.show_grid = True
        self.show_help = True
        self.show_base = True
        self.drag = None
        self.rect_start = None
        self.rect_now = None
        self.undo = []
        self.mouse = (0, 0)
        self.toast = None
        self.running = True

        self.zoom = 1.0
        self.cam = [0.0, 0.0]

        self.base = pygame.Surface((game.WW, game.WH)).convert()
        self.world = pygame.Surface((game.WW, game.WH)).convert()
        self._paint_base()
        self.center_on(200 + game.APT_SIZE[0] / 2, 8 + game.APT_SIZE[1] / 2)
        self.mini = pygame.transform.smoothscale(self.base, (286, 214))

    # ---------------------------------------------------------------- 底图
    def _paint_base(self):
        b = self.base
        b.fill((28, 25, 21))
        for y in range(0, game.WH, 24):
            pygame.draw.line(b, (33, 30, 26), (0, y), (game.WW, y))
        if self.assets.apartment:
            b.blit(self.assets.apartment, game.APT_POS)
            # 稍微提亮一点，暗部（家具、楼梯）看得清
            glow = pygame.Surface(game.APT_SIZE, pygame.SRCALPHA)
            glow.fill((255, 255, 255, 18))
            b.blit(glow, game.APT_POS)
            # 楼外压暗一点，让公寓这张图"浮"出来
            shade = pygame.Surface(game.APT_SIZE, pygame.SRCALPHA)
            shade.fill((0, 0, 0, 0))
            b.blit(shade, game.APT_POS)
            pygame.draw.rect(b, (96, 108, 138), (*game.APT_POS, *game.APT_SIZE), 2)
        if self.assets.shop:
            b.blit(self.assets.shop, game.SHOP_POS)
            pygame.draw.rect(b, (96, 108, 138),
                             (*game.SHOP_POS, *self.assets.shop.get_size()), 1)

    # ---------------------------------------------------------------- 相机
    def view_size(self):
        return game.WW / self.zoom, game.WH / self.zoom

    def clamp_cam(self):
        vw, vh = self.view_size()
        self.cam[0] = max(0.0, min(game.WW - vw, self.cam[0]))
        self.cam[1] = max(0.0, min(game.WH - vh, self.cam[1]))

    def center_on(self, wx, wy):
        vw, vh = self.view_size()
        self.cam = [wx - vw / 2.0, wy - vh / 2.0]
        self.clamp_cam()

    def to_world(self, pos):
        return (self.cam[0] + pos[0] / self.zoom,
                self.cam[1] + pos[1] / self.zoom)

    def to_screen(self, wx, wy):
        return ((wx - self.cam[0]) * self.zoom,
                (wy - self.cam[1]) * self.zoom)

    def set_zoom(self, z, anchor=None):
        """换缩放；anchor 是屏幕坐标（默认画面中心）。"""
        if anchor is None:
            anchor = (game.WW / 2, game.WH / 2)
        before = self.to_world(anchor)
        self.zoom = z
        after = self.to_world(anchor)
        self.cam[0] += before[0] - after[0]
        self.cam[1] += before[1] - after[1]
        self.clamp_cam()

    def cycle_zoom(self):
        i = min(range(len(ZOOMS)), key=lambda k: abs(ZOOMS[k] - self.zoom))
        self.set_zoom(ZOOMS[(i + 1) % len(ZOOMS)], self.mouse)

    # ---------------------------------------------------------------- 坐标
    def cell_at(self, pos):
        wx, wy = self.to_world(pos)
        if not (0 <= wx < game.WW and 0 <= wy < game.WH):
            return None
        return (int(wx // CELL), int(wy // CELL))

    @staticmethod
    def shift_down(ev=None):
        """Shift 是否按着（macOS 的 MOUSEBUTTONDOWN 不一定带 mod 字段）。"""
        mods = 0
        try:
            mods = pygame.key.get_mods()
        except pygame.error:
            pass
        if ev is not None:
            mods |= int(getattr(ev, 'mod', 0) or 0)
        return bool(mods & pygame.KMOD_SHIFT)

    def snapshot(self):
        self.undo.append(set(self.walls))
        if len(self.undo) > 40:
            self.undo.pop(0)

    def paint(self, cell, erase=False):
        if cell is None:
            return
        if erase:
            self.walls.discard(cell)
        else:
            self.walls.add(cell)

    def fill_rect(self, a, b):
        if not a or not b:
            return
        for cy in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
            for cx in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
                self.walls.add((cx, cy))

    # ---------------------------------------------------------------- 绘制
    def draw(self):
        w = self.world
        w.fill((18, 16, 14))
        if self.show_base:
            w.blit(self.base, (0, 0))

        # 墙
        layer = pygame.Surface((game.WW, game.WH), pygame.SRCALPHA)
        for cx, cy in self.walls:
            pygame.draw.rect(layer, (*C_WALL, 104), cell_rect(cx, cy))
        w.blit(layer, (0, 0))

        # 网格
        if self.show_grid:
            for cx in range(COLS + 1):
                x = cx * CELL
                pygame.draw.line(w, C_GRID4 if cx % 4 == 0 else C_GRID,
                                 (x, 0), (x, game.WH), 1)
            for cy in range(ROWS + 1):
                y = cy * CELL
                pygame.draw.line(w, C_GRID4 if cy % 4 == 0 else C_GRID,
                                 (0, y), (game.WW, y), 1)

        # 工位 / 门 / 设备（几何部分画进 world，文字另外画）
        if self.show_help:
            for st in game.MODELS:
                pos = game.STANDS.get(st['id'])
                if pos:
                    pygame.draw.circle(w, C_STATION, (int(pos[0]), int(pos[1])), 3)
            for x, y in game.DOORS.values():
                pygame.draw.circle(w, C_DOOR, (int(x), int(y)), 3)
            for (x, y), col in ((game.BREAKER, C_DEVICE),
                                (game.GATEWAY, (120, 200, 255)),
                                (game.FRIDGE, (150, 230, 226))):
                pygame.draw.circle(w, col, (int(x), int(y)), 4, 1)
            pygame.draw.rect(w, (110, 170, 230), game.GEAR_SHOP_RECT, 1)

        # 矩形预览
        if self.drag == 'rect' and self.rect_start and self.rect_now:
            a, b = self.rect_start, self.rect_now
            r = pygame.Rect(min(a[0], b[0]) * CELL, min(a[1], b[1]) * CELL,
                            (abs(a[0] - b[0]) + 1) * CELL, (abs(a[1] - b[1]) + 1) * CELL)
            pygame.draw.rect(w, C_WALL, r, 1)

        # 放大 / 平移
        s = self.screen
        if self.zoom <= 1.001:
            s.blit(w, (0, 0))
        else:
            vw, vh = self.view_size()
            src = pygame.Rect(int(self.cam[0]), int(self.cam[1]),
                              int(vw), int(vh))
            src = src.clip(pygame.Rect(0, 0, game.WW, game.WH))
            if src.w > 2 and src.h > 2:
                s.blit(pygame.transform.scale(w.subsurface(src), (game.WW, game.WH)),
                       (0, 0))

        # 文字类（不随缩放变糊）：房间名、设备名、光标格
        if self.show_help:
            self.draw_labels(s)
        self.draw_cursor(s)
        # 画面左下角常驻操作提示，第一眼就知道该干什么
        hint = '左键涂墙 · 右键擦 · Shift 拉矩形 · Z 放大 · S 保存'
        lab = game.font(11, True).render(hint, True, (226, 232, 246))
        box = pygame.Surface((lab.get_width() + 16, lab.get_height() + 10),
                             pygame.SRCALPHA)
        pygame.draw.rect(box, (8, 10, 16, 208), box.get_rect(), border_radius=4)
        pygame.draw.rect(box, (96, 112, 148, 230), box.get_rect(), 1, border_radius=4)
        box.blit(lab, (8, 5))
        s.blit(box, (10, game.WH - box.get_height() - 8))
        self.draw_hud(s)
        pygame.display.flip()

    def draw_labels(self, s):
        for name, x, y in ROOM_LABELS:
            sx, sy = self.to_screen(x, y)
            if not (-60 <= sx <= game.WW + 60 and -30 <= sy <= game.WH + 30):
                continue
            lab = game.font(10, True).render(name, True, (214, 226, 244))
            pad = 4
            box = pygame.Surface((lab.get_width() + pad * 2, lab.get_height() + 4),
                                 pygame.SRCALPHA)
            pygame.draw.rect(box, (8, 10, 16, 196), box.get_rect(), border_radius=3)
            pygame.draw.rect(box, (86, 104, 140, 220), box.get_rect(), 1, border_radius=3)
            box.blit(lab, (pad, 2))
            s.blit(box, (sx - box.get_width() / 2, sy))
        for (x, y), name, col in ((game.BREAKER, '电闸', C_DEVICE),
                                  (game.GATEWAY, '网关', (140, 205, 255)),
                                  (game.FRIDGE, '冰箱', (160, 232, 226))):
            sx, sy = self.to_screen(x, y)
            game.txt(s, name, sx + 6, sy + 2, 9, col)

    def draw_cursor(self, s):
        cell = self.cell_at(self.mouse)
        if not cell:
            return
        r = pygame.Rect(cell[0] * CELL, cell[1] * CELL, CELL, CELL)
        sx, sy = self.to_screen(r.x, r.y)
        pygame.draw.rect(s, (255, 255, 255), (sx, sy, CELL * self.zoom,
                                              CELL * self.zoom), 1)

    # ---------------------------------------------------------------- HUD
    def draw_hud(self, s):
        P = game.PANE_X
        pygame.draw.rect(s, (13, 14, 21), (P, 0, game.SW - P, game.SH))
        pygame.draw.line(s, (48, 52, 72), (P, 0), (P, game.SH), 2)
        x = P + 14
        R = game.SW - 14
        game.txt(s, '行走网格标注', x, 10, 21, game.C_TEXT, bold=True)
        game.txt(s, '左边就是公寓俯视图', x, 36, 11, (150, 158, 182))
        game.txt(s, f'缩放 {self.zoom:.1f}×　格 {CELL}px', x, 52, 10, (120, 128, 150))

        cell = self.cell_at(self.mouse)
        info = f'格 {cell[0]},{cell[1]}' if cell else '—'
        game.txt(s, f'鼠标：{info}', x, 72, 12, game.C_BLUE)
        game.txt(s, f'墙格：{len(self.walls)} / {COLS * ROWS}', x, 90, 12, game.C_TEXT)
        game.txt(s, f'模式：{"涂墙" if self.mode == "wall" else "擦除"}',
                 x, 108, 12, C_WALL if self.mode == 'wall' else C_WALK)

        # 图例
        ly = 132
        for col, text in ((C_WALL, '红块 = 墙（不能走）'),
                          (C_WALK, '没涂 = 可走'),
                          (C_DOOR, '粉点 = 房门口'),
                          (C_STATION, '绿点 = 工位'),
                          (C_DEVICE, '橙圈 = 电闸')):
            pygame.draw.rect(s, col, (x, ly + 3, 10, 10), border_radius=2)
            game.txt(s, text, x + 18, ly, 10, (170, 178, 198))
            ly += 19

        # 小地图
        my = 244
        game.txt(s, '小地图（白框是当前视野）', x, my - 18, 10, (140, 148, 172))
        s.blit(self.mini, (x, my))
        pygame.draw.rect(s, (70, 78, 100), (x, my, 286, 214), 1)
        vx, vy = self.to_screen(0, 0)
        vw, vh = self.view_size()
        pygame.draw.rect(s, (240, 240, 250),
                         (x + vx / game.WW * 286, my + vy / game.WH * 214,
                          vw / game.WW * 286, vh / game.WH * 214), 1)

        # 快捷键
        ky = my + 226
        rows = [('左键拖动', '涂墙'), ('右键拖动', '擦除'),
                ('Shift+左键', '矩形涂墙'), ('1 / 2', '涂墙 / 擦除'),
                ('Z / 滚轮', '缩放'), ('↑↓←→', '平移'),
                ('F', '回正'), ('G / H / T', '网格 / 标注 / 底图'),
                ('U / C', '撤销 / 清空'), ('S / L', '保存 / 重读')]
        for k, v in rows:
            if ky > game.SH - 30:
                break
            game.txt(s, k, x, ky, 10, (232, 206, 150), bold=True)
            game.txt(s, v, x + 86, ky, 10, (150, 158, 182))
            ky += 17

        if self.toast:
            self.toast[1] -= 1
            if self.toast[1] <= 0:
                self.toast = None
            else:
                game.txt(s, self.toast[0], P + 150, game.SH - 16, 11,
                         (255, 230, 160))

    # ---------------------------------------------------------------- 保存
    def save(self):
        save_mask(self.walls, self.path)
        self.save_preview()
        self.toast = ['已保存 · 游戏下次启动生效', 100]

    def save_preview(self):
        surf = pygame.Surface((game.WW, game.WH)).convert()
        surf.blit(self.base, (0, 0))
        layer = pygame.Surface((game.WW, game.WH), pygame.SRCALPHA)
        for cx, cy in self.walls:
            pygame.draw.rect(layer, (*C_WALL, 110), cell_rect(cx, cy))
        surf.blit(layer, (0, 0))
        for cx in range(COLS + 1):
            pygame.draw.line(surf, (58, 64, 82), (cx * CELL, 0), (cx * CELL, game.WH))
        for cy in range(ROWS + 1):
            pygame.draw.line(surf, (58, 64, 82), (0, cy * CELL), (game.WW, cy * CELL))
        for name, x, y in ROOM_LABELS:
            lab = game.font(10, True).render(name, True, (230, 236, 248))
            surf.blit(lab, (x - lab.get_width() // 2, y - 26))
        pygame.image.save(surf, PREVIEW_PATH)
        print('预览图 ->', PREVIEW_PATH)

    # ---------------------------------------------------------------- 事件
    def run(self):
        while self.running:
            self.clock.tick(60)
            for ev in pygame.event.get():
                self.on_event(ev)
            self.pan_by_keys()
            self.draw()
        pygame.quit()

    def pan_by_keys(self):
        keys = pygame.key.get_pressed()
        step = 6 / self.zoom
        dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
        dy = (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
        if dx or dy:
            self.cam[0] += dx * step
            self.cam[1] += dy * step
            self.clamp_cam()

    def on_event(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type == pygame.KEYDOWN:
            k = ev.key
            if k == pygame.K_ESCAPE:
                self.running = False
            elif k == pygame.K_1:
                self.mode = 'wall'
            elif k == pygame.K_2:
                self.mode = 'erase'
            elif k == pygame.K_v:
                self.snapshot()
                self.paint(self.cell_at(self.mouse),
                           erase=(self.mode == 'wall'))
            elif k == pygame.K_g:
                self.show_grid = not self.show_grid
            elif k == pygame.K_h:
                self.show_help = not self.show_help
            elif k == pygame.K_t:
                self.show_base = not self.show_base
            elif k == pygame.K_z:
                self.cycle_zoom()
            elif k == pygame.K_f:
                self.zoom = 1.0
                self.center_on(200 + game.APT_SIZE[0] / 2, 8 + game.APT_SIZE[1] / 2)
            elif k == pygame.K_s:
                self.save()
            elif k == pygame.K_l:
                self.walls = load_mask(self.path)
                self.toast = [f'已重读 {len(self.walls)} 个墙格', 70]
            elif k == pygame.K_u:
                if self.undo:
                    self.walls = self.undo.pop()
            elif k == pygame.K_c:
                self.snapshot()
                self.walls.clear()
                self.toast = ['已清空', 60]
        elif ev.type == pygame.MOUSEWHEEL:
            nz = self.zoom * (1.25 if ev.y > 0 else 0.8)
            nz = min(ZOOMS[-1], max(ZOOMS[0], nz))
            self.set_zoom(nz, ev.pos if hasattr(ev, 'pos') else None)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 2, 3):
            if ev.button == 2:
                self.drag = 'pan'
                self.pan_from = ev.pos
                return
            self.snapshot()
            cell = self.cell_at(ev.pos)
            if ev.button == 3:
                self.drag = 'erase'
                self.paint(cell, erase=True)
            elif self.shift_down(ev):
                self.drag = 'rect'
                self.rect_start = cell
                self.rect_now = cell
            else:
                self.drag = 'paint'
                self.paint(cell)
        elif ev.type == pygame.MOUSEMOTION:
            self.mouse = ev.pos
            if self.drag in ('paint', 'erase'):
                self.paint(self.cell_at(ev.pos), erase=(self.drag == 'erase'))
            elif self.drag == 'rect':
                self.rect_now = self.cell_at(ev.pos)
            elif self.drag == 'pan':
                dx = ev.pos[0] - self.pan_from[0]
                dy = ev.pos[1] - self.pan_from[1]
                self.pan_from = ev.pos
                self.cam[0] -= dx / self.zoom
                self.cam[1] -= dy / self.zoom
                self.clamp_cam()
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button in (1, 2, 3):
            if self.drag == 'rect':
                self.fill_rect(self.rect_start, self.rect_now)
            self.drag = None
            self.rect_start = self.rect_now = None


def check(path=MASK_PATH):
    """--check：不开窗口，只报告掩码情况。"""
    if not os.path.exists(path):
        print('还没有掩码文件：', path)
        return 1
    walls = load_mask(path)
    print('墙格', len(walls), '/', COLS * ROWS)
    if walls:
        xs = [c[0] for c in walls]
        ys = [c[1] for c in walls]
        print('范围：x %d..%d  y %d..%d（格）' % (min(xs), max(xs), min(ys), max(ys)))
        print('像素范围：x %d..%d  y %d..%d' %
              (min(xs) * CELL, (max(xs) + 1) * CELL,
               min(ys) * CELL, (max(ys) + 1) * CELL))
    walk = {(x, y) for y in range(ROWS) for x in range(COLS)} - walls
    start = next((c for c in [(20, 8), (18, 9), (30, 20)] if c in walk), None)
    if start:
        seen = {start}
        q = [start]
        while q:
            cx, cy = q.pop()
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if (nx, ny) in walk and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    q.append((nx, ny))
        print('从 %s 出发可达 %d 格（可走 %d 格）' % (start, len(seen), len(walk)))
    return 0


def main():
    if '--check' in sys.argv:
        sys.exit(check())
    Editor().run()


if __name__ == '__main__':
    main()
