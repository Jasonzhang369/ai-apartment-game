#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「南极科考站」俯视像素地图（assets/station.png）。

风格对齐 assets/apartment.png：正俯视、16px 网格、可读的家具剪影。
输出：
    assets/station.png          可直接当场景底图（720x704）
    design/科考站俯视图.png       放大 2 倍并带中文房间标注，方便看

用法：python3 tools/gen_station.py
"""
import json
import os
import random
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 720, 704

# ---------------- 调色板 ----------------
SNOW = (206, 219, 235)
SNOW_HI = (233, 241, 250)
SNOW_LO = (184, 199, 219)
ICE = (176, 214, 228)
WALL = (64, 70, 86)
WALL_HI = (116, 124, 142)
WALL_LO = (26, 30, 40)
WALL_LINE = (40, 45, 58)

F_METAL = (104, 112, 120)
F_METAL_L = (116, 124, 132)
F_METAL_D = (90, 98, 106)
F_WOOD = (124, 97, 70)
F_WOOD_D = (104, 80, 57)
F_TILE = (178, 182, 190)
F_TILE_D = (160, 165, 175)
F_TILEL = (196, 200, 208)
F_CARPET = (74, 88, 120)
F_CARPET_D = (64, 77, 106)
F_SOIL = (74, 58, 46)
F_SOIL_D = (60, 47, 37)
F_CONC = (116, 116, 112)
F_CONC_D = (98, 98, 94)
F_DARK = (58, 66, 82)

WOOD = (146, 110, 78)
WOOD_HI = (170, 132, 96)
WOOD_D = (112, 82, 56)
METAL = (132, 138, 148)
METAL_HI = (160, 166, 176)
METAL_D = (104, 110, 120)
ORANGE = (222, 140, 80)
ORANGE_D = (176, 104, 56)
GLOW = (120, 200, 220)
GLOW_D = (72, 150, 176)
GREEN = (98, 168, 108)
GREEN_L = (132, 198, 134)
RED = (214, 92, 84)
YELLOW = (226, 196, 96)

rng = random.Random(20261030)

DOOR_SPECS = [
    (204, 120), (204, 340), (204, 540),
    (252, 120), (252, 340), (252, 540),
    (428, 120), (428, 340), (428, 540),
    (476, 120), (476, 340), (476, 540),
]
VERT_DOORS = [(246, 106), (246, 330), (246, 548),
              (462, 106), (462, 330), (462, 548)]


def P(s, x, y, w, h, c):
    pygame.draw.rect(s, c, (int(x), int(y), int(w), int(h)))


def outline(s, x, y, w, h, c=WALL_LO, t=1):
    pygame.draw.rect(s, c, (int(x), int(y), int(w), int(h)), t)


def noise(s, x, y, w, h, base, amount=8, step=4, seed=0):
    r = random.Random(seed)
    for yy in range(int(y), int(y + h), step):
        for xx in range(int(x), int(x + w), step):
            d = r.randint(-amount, amount)
            c = (max(0, min(255, base[0] + d)),
                 max(0, min(255, base[1] + d)),
                 max(0, min(255, base[2] + d)))
            s.fill(c, (int(xx), int(yy), step, step))


def wall_h(s, x, y, w, t=12):
    P(s, x, y, w, t, WALL)
    P(s, x, y, w, 3, WALL_HI)
    P(s, x, y + t - 2, w, 2, WALL_LO)
    outline(s, x, y, w, t, WALL_LINE)


def wall_v(s, x, y, h, t=12):
    P(s, x, y, t, h, WALL)
    P(s, x, y, 3, h, WALL_HI)
    P(s, x + t - 2, y, 2, h, WALL_LO)
    outline(s, x, y, t, h, WALL_LINE)


def door(s, x, y, w=30, horizontal=True):
    """在墙上开个门洞（先擦成地板色，再画门框）。"""
    if horizontal:
        s.fill(F_METAL, (x, y, w, 12))
        P(s, x, y, w, 3, F_METAL_L)
        P(s, x, y, 3, 12, WALL_HI)
        P(s, x + w - 3, y, 3, 12, WALL_HI)
    else:
        s.fill(F_METAL, (x, y, 12, w))
        P(s, x, y, 3, w, F_METAL_L)
        P(s, x, y, 12, 3, WALL_HI)
        P(s, x, y + w - 3, 12, 3, WALL_HI)


def window(s, x, y, w, h, horiz=True):
    P(s, x, y, w, h, (146, 178, 196))
    P(s, x, y, w, 2, (198, 226, 240))
    P(s, x, y + h - 2, w, 2, (110, 140, 160))
    if horiz:
        sx = x + w // 2
        P(s, sx - 1, y, 2, h, (110, 140, 160))
    else:
        sy = y + h // 2
        P(s, x, sy - 1, w, 2, (110, 140, 160))


# ---------------- 房间地板 ----------------
def floor_metal(s, r, seed=1, base=F_METAL, grid=16):
    noise(s, r.x, r.y, r.w, r.h, base, 6, 4, seed)
    for x in range(r.x, r.right, grid):
        P(s, x, r.y, 1, r.h, F_METAL_D)
    for y in range(r.y, r.bottom, grid):
        P(s, r.x, y, r.w, 1, F_METAL_D)
    for x in range(r.x + 8, r.right, grid):
        for y in range(r.y + 8, r.bottom, grid):
            P(s, x, y, 2, 2, F_METAL_L)


def floor_wood(s, r, seed=2):
    noise(s, r.x, r.y, r.w, r.h, F_WOOD, 7, 4, seed)
    for y in range(r.y, r.bottom, 12):
        P(s, r.x, y, r.w, 1, F_WOOD_D)
    rr = random.Random(seed)
    for x in range(r.x + 4, r.right, 40):
        for y in range(r.y + 6, r.bottom, 12):
            if rr.random() < 0.5:
                P(s, x + rr.randint(0, 20), y + 3, 2, 1, F_WOOD_D)


def floor_tile(s, r, seed=3, base=F_TILE, dark=F_TILE_D, light=F_TILEL, size=24):
    noise(s, r.x, r.y, r.w, r.h, base, 5, 4, seed)
    for x in range(r.x, r.right, size):
        P(s, x, r.y, 1, r.h, dark)
    for y in range(r.y, r.bottom, size):
        P(s, r.x, y, r.w, 1, dark)
    for x in range(r.x, r.right, size):
        for y in range(r.y, r.bottom, size):
            if (x // size + y // size) % 3 == 0:
                P(s, x + 2, y + 2, size - 4, 1, light)


def floor_carpet(s, r, seed=4, base=F_CARPET, dark=F_CARPET_D):
    noise(s, r.x, r.y, r.w, r.h, base, 5, 3, seed)
    for y in range(r.y, r.bottom, 6):
        P(s, r.x, y, r.w, 1, dark)


def floor_concrete(s, r, seed=5, base=F_CONC, dark=F_CONC_D):
    noise(s, r.x, r.y, r.w, r.h, base, 7, 5, seed)
    rr = random.Random(seed)
    for _ in range(30):
        x = rr.randint(r.x, r.right - 3)
        y = rr.randint(r.y, r.bottom - 3)
        P(s, x, y, rr.randint(2, 8), 1, dark)


def floor_soil(s, r, seed=6):
    noise(s, r.x, r.y, r.w, r.h, F_SOIL, 6, 4, seed)
    for y in range(r.y + 8, r.bottom, 22):
        P(s, r.x, y, r.w, 2, F_SOIL_D)


# ---------------- 家具 ----------------
def shadow(s, x, y, w, h, a=60):
    dark = pygame.Surface((int(w), int(h)), pygame.SRCALPHA)
    dark.fill((10, 8, 14, a))
    s.blit(dark, (int(x + 3), int(y + 4)))


def desk(s, x, y, w=44, h=26, col=WOOD):
    shadow(s, x, y, w, h)
    P(s, x, y, w, h, col)
    P(s, x, y, w, 3, WOOD_HI)
    P(s, x, y + h - 3, w, 3, WOOD_D)
    P(s, x + 4, y + h, 3, 5, WOOD_D)
    P(s, x + w - 7, y + h, 3, 5, WOOD_D)


def monitor(s, x, y, w=20, h=14, on=True):
    P(s, x, y, w, h, (38, 42, 52))
    P(s, x + 2, y + 2, w - 4, h - 4, (28, 30, 38))
    if on:
        P(s, x + 2, y + 2, w - 4, h - 4, GLOW_D)
        P(s, x + 3, y + 3, w - 8, 3, GLOW)
        P(s, x + 3, y + 7, w - 12, 2, (150, 220, 236))
    P(s, x + w // 2 - 3, y + h, 6, 3, (54, 58, 70))
    P(s, x + w // 2 - 7, y + h + 3, 14, 2, (54, 58, 70))


def chair(s, x, y):
    P(s, x, y, 14, 12, (60, 64, 76))
    P(s, x + 2, y + 2, 10, 6, (78, 84, 98))
    P(s, x + 1, y + 10, 12, 2, (40, 44, 56))


def bunk(s, x, y, w=54, h=26, col=(96, 118, 150)):
    shadow(s, x, y, w, h)
    P(s, x, y, w, h, (86, 90, 104))
    P(s, x + 2, y + 2, w - 4, h - 4, col)
    P(s, x + 4, y + 4, w - 8, 8, (216, 218, 224))      # 枕头
    P(s, x + 4, y + 14, w - 10, h - 18, (150, 162, 186))
    P(s, x, y, w, 2, (118, 124, 138))


def shelf(s, x, y, w=48, h=16, items=True):
    shadow(s, x, y, w, h)
    P(s, x, y, w, h, WOOD_D)
    P(s, x, y, w, 3, WOOD)
    P(s, x, y + h - 2, w, 2, (86, 62, 44))
    if items:
        r = random.Random(int(x) * 31 + int(y))
        xx = x + 3
        while xx < x + w - 5:
            c = r.choice([(190, 120, 96), (120, 160, 190), (200, 190, 130),
                          (140, 170, 140), (210, 150, 90)])
            P(s, xx, y + 4, 4, h - 8, c)
            xx += 5


def crate(s, x, y, w=20, h=18):
    shadow(s, x, y, w, h)
    P(s, x, y, w, h, (150, 118, 82))
    P(s, x, y, w, 2, (176, 142, 102))
    P(s, x, y + h - 2, w, 2, (112, 86, 58))
    P(s, x + 2, y + 2, 1, h - 4, (118, 90, 60))
    P(s, x + w - 3, y + 2, 1, h - 4, (118, 90, 60))


def pipe(s, x1, y, x2, col=(150, 156, 166), t=4):
    P(s, x1, y, x2 - x1, t, col)
    P(s, x1, y, x2 - x1, 1, (196, 200, 208))
    P(s, x1, y + t - 1, x2 - x1, 1, (104, 110, 120))


def plant(s, x, y, w=10, h=10):
    P(s, x + 2, y + h - 4, w - 4, 4, (128, 92, 66))
    P(s, x + 3, y + 2, 3, h - 5, GREEN)
    P(s, x + 6, y, 3, h - 3, GREEN_L)
    P(s, x, y + 4, 3, h - 6, GREEN)


def glow_dot(s, x, y, c=GLOW):
    P(s, x, y, 3, 3, c)
    P(s, x + 1, y + 1, 1, 1, (255, 255, 255))


# ---------------- 场景 ----------------
def glow(s, x, y, r=46, color=(255, 214, 150), a=52):
    """柔和的光晕（多圈叠加，像素游戏里当灯光）。"""
    surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    for i in range(6, 0, -1):
        rr = int(r * i / 6)
        alpha = int(a * (1 - i / 7))
        pygame.draw.circle(surf, (*color, alpha), (r, r), rr)
    s.blit(surf, (int(x - r), int(y - r)))


def rivets(s, x, y, w, h, step=18):
    for xx in range(int(x) + 8, int(x + w) - 4, step):
        P(s, xx, y + 4, 2, 2, WALL_HI)
        P(s, xx, y + h - 6, 2, 2, WALL_LO)


def wall_h2(s, x, y, w, t=12):
    wall_h(s, x, y, w, t)
    for xx in range(int(x) + 30, int(x + w) - 10, 60):
        P(s, xx, y, 1, t, WALL_LINE)
    rivets(s, x, y, w, t)


def wall_v2(s, x, y, h, t=12):
    wall_v(s, x, y, h, t)
    for yy in range(int(y) + 30, int(y + h) - 10, 60):
        P(s, x, yy, t, 1, WALL_LINE)
    rivets(s, x, y, t, h)


def door_leaf(s, x, y, w=36, vertical=False):
    """一扇关闭的钢门（带观察窗）。"""
    if not vertical:
        P(s, x, y, w, 12, (74, 82, 96))
        P(s, x, y, w, 2, (108, 118, 134))
        P(s, x + w // 2 - 6, y + 3, 12, 6, (140, 190, 206))
        P(s, x, y, 2, 12, (48, 54, 66))
        P(s, x + w - 2, y, 2, 12, (48, 54, 66))
    else:
        P(s, x, y, 12, w, (74, 82, 96))
        P(s, x, y, 2, w, (108, 118, 134))
        P(s, x + 3, y + w // 2 - 6, 6, 12, (140, 190, 206))


def poster(s, x, y, w, h, kind=0):
    cols = [(214, 206, 186), (196, 214, 206), (214, 194, 196)]
    P(s, x, y, w, h, cols[kind % 3])
    P(s, x, y, w, 1, (240, 240, 236))
    if kind == 0:
        for i in range(4):
            P(s, x + 3, y + 4 + i * 4, w - 6, 1, (120, 130, 150))
    elif kind == 1:
        P(s, x + 3, y + 3, w - 6, h - 6, (150, 190, 180))
        P(s, x + w // 2, y + 4, 1, h - 8, (100, 140, 130))
    else:
        P(s, x + 3, y + 3, w - 6, 3, (200, 120, 110))
        P(s, x + 3, y + 9, w - 10, 2, (160, 150, 150))


def vent(s, x, y, w=20, h=10):
    P(s, x, y, w, h, (70, 76, 88))
    for i in range(4):
        P(s, x + 2, y + 2 + i * 2, w - 4, 1, (110, 118, 132))


def extinguisher(s, x, y):
    P(s, x, y, 6, 12, (206, 92, 84))
    P(s, x, y, 6, 2, (150, 60, 56))
    P(s, x + 1, y - 3, 4, 3, (60, 64, 74))


def mug(s, x, y):
    P(s, x, y, 5, 5, (222, 226, 230))
    P(s, x + 5, y + 1, 2, 3, (190, 196, 202))


def papers(s, x, y, n=3):
    r = random.Random(int(x) + int(y))
    for i in range(n):
        P(s, x + i * 4, y + r.randint(0, 4), 10, 8, (226, 226, 220))
        P(s, x + i * 4, y + r.randint(0, 4), 10, 1, (200, 200, 194))


def cable(s, pts, col=(50, 54, 66)):
    for i in range(len(pts) - 1):
        pygame.draw.line(s, col, pts[i], pts[i + 1], 2)


def toolbox(s, x, y):
    P(s, x, y, 20, 10, (188, 92, 84))
    P(s, x, y, 20, 2, (216, 120, 110))
    P(s, x + 7, y - 3, 6, 3, (140, 70, 64))


def boots(s, x, y):
    P(s, x, y, 6, 10, (60, 58, 64))
    P(s, x + 7, y + 2, 6, 8, (60, 58, 64))


def snow_field(s):
    s.fill(SNOW)
    noise(s, 0, 0, W, H, SNOW, 12, 4, 41)
    r = random.Random(77)
    # 风吹出来的雪纹
    for _ in range(140):
        x, y = r.randint(0, W), r.randint(0, H)
        ln = r.randint(18, 70)
        P(s, x, y, ln, 1, SNOW_HI if r.random() < 0.6 else SNOW_LO)
    # 雪脊（斜向短笔触）
    for _ in range(220):
        x, y = r.randint(0, W - 12), r.randint(0, H - 6)
        ln = r.randint(4, 10)
        P(s, x, y, ln, 1, SNOW_LO)
        P(s, x + 2, y - 1, max(2, ln - 4), 1, SNOW_HI)
    # 冰面
    for _ in range(10):
        x, y = r.randint(0, W - 60), r.randint(0, H - 30)
        pygame.draw.ellipse(s, ICE, (x, y, r.randint(30, 70), r.randint(10, 22)))
    # 极光
    aur = pygame.Surface((W, 170), pygame.SRCALPHA)
    for i in range(170):
        a = int(46 * (1 - i / 170))
        pygame.draw.line(aur, (86, 210, 178, a), (0, i), (W, i))
    s.blit(aur, (0, 0))


def station_shadow(s):
    sh = pygame.Surface((640, 664), pygame.SRCALPHA)
    sh.fill((20, 26, 44, 60))
    s.blit(sh, (40, 34))


def room_shade(s, r, t=4, a=70):
    """房间内侧贴墙的一圈暗边，立刻有"墙高"的感觉。"""
    sh = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.rect(sh, (8, 10, 16, a), (0, 0, r.w, r.h), t)
    s.blit(sh, (r.x, r.y))


def lamp(s, x, y, col=(255, 224, 168), r=86, a=44):
    """顶灯：只画光晕 + 一个小亮点（俯视看不到灯罩）。"""
    glow(s, x, y, r, col, a)
    glow(s, x, y, max(8, r // 5), (255, 250, 232), min(150, a + 70))
    P(s, x - 1, y - 1, 3, 3, (255, 252, 236))


def guide_line(s, x1, x2, y, col=(206, 186, 96)):
    P(s, x1, y, x2 - x1, 2, col)
    for x in range(x1, x2, 26):
        P(s, x, y, 12, 2, (60, 58, 48))


def accent(s, r, side, col):
    if side == 'top':
        P(s, r.x, r.y, r.w, 3, col)
    elif side == 'bottom':
        P(s, r.x, r.bottom - 3, r.w, 3, col)
    elif side == 'left':
        P(s, r.x, r.y, 3, r.h, col)


def build():
    pygame.init()
    s = pygame.Surface((W, H))
    snow_field(s)
    station_shadow(s)

    # ---------------- 房间几何 ----------------
    rooms = {
        'weather': pygame.Rect(56, 40, 190, 164),
        'control': pygame.Rect(258, 40, 204, 164),
        'power':   pygame.Rect(474, 40, 178, 164),
        'green':   pygame.Rect(56, 264, 190, 164),
        'canteen': pygame.Rect(258, 264, 204, 164),
        'dorm':    pygame.Rect(474, 264, 178, 164),
        'lab':     pygame.Rect(56, 488, 150, 164),
        'hall':    pygame.Rect(206, 488, 294, 164),
        'warehouse': pygame.Rect(500, 488, 152, 164),
    }
    corr_a = pygame.Rect(56, 216, 596, 36)
    corr_b = pygame.Rect(56, 440, 596, 36)

    floor_metal(s, rooms['weather'], 21, (120, 128, 138))
    floor_metal(s, rooms['control'], 22)
    floor_concrete(s, rooms['power'], 23, (132, 124, 110), (112, 104, 90))
    floor_soil(s, rooms['green'], 24)
    floor_wood(s, rooms['canteen'], 25)
    floor_carpet(s, rooms['dorm'], 26, (86, 98, 134), (74, 85, 118))
    floor_tile(s, rooms['lab'], 27, (200, 204, 210), (176, 182, 190), (220, 224, 228), 22)
    floor_wood(s, rooms['hall'], 28)
    floor_concrete(s, rooms['warehouse'], 29, (144, 132, 116), (120, 110, 96))
    floor_metal(s, corr_a, 31, (104, 112, 122))
    floor_metal(s, corr_b, 32, (104, 112, 122))
    for rr in rooms.values():
        room_shade(s, rr)
    for cr in (corr_a, corr_b):
        room_shade(s, cr, 3, 55)

    # 分区色带
    accent(s, rooms['weather'], 'top', (92, 140, 178))
    accent(s, rooms['control'], 'top', (86, 176, 196))
    accent(s, rooms['power'], 'top', (206, 150, 74))
    accent(s, rooms['green'], 'top', (96, 168, 106))
    accent(s, rooms['canteen'], 'top', (198, 138, 88))
    accent(s, rooms['dorm'], 'top', (126, 140, 190))
    accent(s, rooms['lab'], 'top', (110, 176, 180))
    accent(s, rooms['hall'], 'top', (196, 138, 88))
    accent(s, rooms['warehouse'], 'top', (196, 168, 92))

    # 走廊：格栅 + 管道 + 壁灯 + 线槽
    for cr in (corr_a, corr_b):
        for x in range(cr.x, cr.right, 8):
            P(s, x, cr.y, 1, cr.h, F_METAL_D)
        for y in range(cr.y, cr.bottom, 12):
            P(s, cr.x, y, cr.w, 1, F_METAL_D)
        pipe(s, cr.x + 4, cr.y + 3, cr.right - 4, (152, 158, 168), 3)
        pipe(s, cr.x + 4, cr.y + cr.h - 7, cr.right - 4, (118, 124, 136), 3)
        for x in range(cr.x + 34, cr.right - 20, 74):
            glow_dot(s, x, cr.y + cr.h // 2 - 3, (250, 236, 190))
            glow(s, x + 1, cr.y + cr.h // 2 - 2, 34, (255, 226, 160), 22)

    # ---------------- 墙体 ----------------
    wall_h2(s, 44, 28, 620, 12)          # 上外墙
    wall_h2(s, 44, 664, 620, 12)         # 下外墙
    wall_v2(s, 44, 28, 648, 12)          # 左
    wall_v2(s, 652, 28, 648, 12)         # 右
    for y in (204, 252, 428, 476, 652):
        wall_h2(s, 56, y, 596, 12)
    for x in (246, 462):
        for (y0, y1) in ((40, 204), (264, 428)):
            wall_v2(s, x, y0, y1 - y0, 12)
    for x in (206, 500):
        wall_v2(s, x, 488, 164, 12)

    # 门（每段墙一个，带门扇）
    for y, x in DOOR_SPECS:
        s.fill(F_METAL, (x, y, 38, 12))
        door_leaf(s, x, y, 38)

    for x, y in VERT_DOORS:
        s.fill(F_METAL, (x, y, 12, 38))
        door_leaf(s, x, y, 38, vertical=True)

    # 窗（含窗台积雪）
    for x in (86, 300, 520):
        window(s, x, 28, 62, 10)
        P(s, x - 2, 26, 66, 2, SNOW_HI)
    window(s, 44, 96, 10, 56, horiz=False)
    window(s, 44, 560, 10, 50, horiz=False)
    window(s, 652, 300, 10, 54, horiz=False)
    window(s, 140, 664, 58, 10)
    window(s, 476, 664, 58, 10)

    # ================= 气象观测室 =================
    r = rooms['weather']
    desk(s, r.x + 16, r.y + 18, 64, 26)
    monitor(s, r.x + 24, r.y + 22)
    monitor(s, r.x + 48, r.y + 22)
    papers(s, r.x + 84, r.y + 24)
    mug(s, r.x + 88, r.y + 34)
    desk(s, r.x + 16, r.y + 76, 50, 22)
    P(s, r.x + 24, r.y + 80, 32, 12, (46, 52, 66))
    for i in range(4):
        glow_dot(s, r.x + 28 + i * 6, r.y + 84,
                 (120, 200, 160) if i % 2 else (220, 180, 90))
    poster(s, r.x + 100, r.y + 14, 26, 34, 0)
    vent(s, r.x + 150, r.y + 16, 22, 10)
    shelf(s, r.x + 16, r.y + 130, 56, 18)
    crate(s, r.x + 88, r.y + 126)
    crate(s, r.x + 110, r.y + 130)
    # 三脚架观测仪
    P(s, r.x + 150, r.y + 96, 4, 22, (128, 134, 144))
    P(s, r.x + 140, r.y + 116, 24, 3, (128, 134, 144))
    P(s, r.x + 146, r.y + 118, 3, 14, (108, 114, 124))
    P(s, r.x + 158, r.y + 118, 3, 14, (108, 114, 124))
    pygame.draw.circle(s, (156, 176, 196), (r.x + 152, r.y + 94), 7)
    plant(s, r.x + 172, r.y + 20)
    glow(s, r.x + 48, r.y + 110, 60, (255, 220, 160), 20)

    # ================= 主控通信 =================
    r = rooms['control']
    P(s, r.x + 22, r.y + 22, 136, 30, (38, 44, 58))
    P(s, r.x + 26, r.y + 26, 128, 22, (28, 32, 44))
    for i in range(3):
        monitor(s, r.x + 30 + i * 42, r.y + 28, 38, 18)
    P(s, r.x + 22, r.y + 50, 136, 4, (66, 74, 92))
    chair(s, r.x + 56, r.y + 62)
    chair(s, r.x + 108, r.y + 62)
    # 大屏
    P(s, r.x + 168, r.y + 18, 26, 4, (34, 38, 50))
    P(s, r.x + 162, r.y + 22, 38, 50, (34, 38, 50))
    P(s, r.x + 166, r.y + 26, 30, 42, (24, 50, 64))
    for i in range(5):
        P(s, r.x + 170 + i * 5, r.y + 58 - i * 5, 4, 4 + i * 5, (110, 200, 220))
    # 通讯机柜
    for i in range(3):
        x = r.x + 22 + i * 28
        P(s, x, r.y + 84, 24, 54, (54, 60, 74))
        P(s, x + 2, r.y + 86, 20, 6, (76, 84, 100))
        for j in range(5):
            glow_dot(s, x + 5 + (j % 2) * 9, r.y + 96 + j * 8,
                     (120, 210, 170) if j % 2 else (220, 160, 90))
    # 卫星电话 + 桌面杂物
    P(s, r.x + 110, r.y + 92, 28, 18, (60, 66, 80))
    P(s, r.x + 118, r.y + 80, 3, 14, (140, 146, 156))
    pygame.draw.circle(s, (180, 190, 200), (r.x + 119, r.y + 76), 6)
    mug(s, r.x + 150, r.y + 96)
    papers(s, r.x + 160, r.y + 112, 2)
    extinguisher(s, r.x + 180, r.y + 90)
    poster(s, r.x + 168, r.y + 130, 24, 22, 1)
    glow(s, r.x + 90, r.y + 40, 70, (120, 200, 230), 18)

    # ================= 发电舱 =================
    r = rooms['power']
    for i in range(2):
        x, y = r.x + 12 + i * 80, r.y + 20
        P(s, x, y, 66, 74, (154, 152, 140))
        P(s, x, y, 66, 5, (184, 182, 168))
        P(s, x, y + 69, 66, 5, (112, 110, 102))
        for j in range(5):
            P(s, x + 6, y + 12 + j * 11, 54, 4, (120, 120, 112))
        glow_dot(s, x + 8, y + 62, (224, 88, 78))
        glow_dot(s, x + 16, y + 62, (120, 212, 150))
        pipe(s, x + 60, y + 22, r.right - 6, (150, 150, 140), 4)
        glow(s, x + 30, y + 60, 46, (255, 150, 90), 18)
    # 配电盘
    P(s, r.x + 12, r.y + 104, 48, 44, (58, 64, 78))
    for i in range(6):
        glow_dot(s, r.x + 18 + (i % 3) * 13, r.y + 110 + (i // 3) * 15,
                 (220, 160, 90) if i % 2 else (120, 210, 160))
    # 油桶
    for i in range(4):
        x, y = r.x + 78 + (i % 2) * 20, r.y + 108 + (i // 2) * 22
        pygame.draw.circle(s, (172, 122, 72), (x + 8, y + 8), 8)
        pygame.draw.circle(s, (204, 152, 92), (x + 8, y + 6), 5)
        pygame.draw.circle(s, (120, 82, 50), (x + 8, y + 8), 8, 1)
    toolbox(s, r.x + 130, r.y + 120)
    # 危险条纹
    for i in range(8):
        P(s, r.x + 10 + i * 9, r.y + 156, 5, 6, YELLOW if i % 2 == 0 else (38, 38, 44))
    vent(s, r.x + 140, r.y + 96, 22, 10)

    # ================= 温室 =================
    r = rooms['green']
    for row in range(3):
        y = r.y + 18 + row * 44
        P(s, r.x + 12, y, 146, 30, (98, 76, 58))
        P(s, r.x + 12, y, 146, 3, (124, 100, 76))
        P(s, r.x + 12, y + 27, 146, 3, (72, 56, 42))
        for i in range(9):
            plant(s, r.x + 18 + i * 16, y + 7, 10, 14)
        P(s, r.x + 16, y - 6, 138, 4, (58, 52, 70))
        for i in range(7):
            glow_dot(s, r.x + 22 + i * 20, y - 5, (218, 128, 190))
        glow(s, r.x + 88, y + 10, 72, (230, 120, 190), 14)
    P(s, r.x + 10, r.y + 142, 34, 18, (86, 150, 170))
    P(s, r.x + 10, r.y + 142, 34, 4, (120, 190, 210))
    desk(s, r.x + 112, r.y + 138, 62, 24)
    plant(s, r.x + 118, r.y + 132)
    plant(s, r.x + 138, r.y + 134)
    toolbox(s, r.x + 60, r.y + 146)

    # ================= 食堂 =================
    r = rooms['canteen']
    P(s, r.x + 18, r.y + 30, 122, 34, WOOD)
    P(s, r.x + 18, r.y + 30, 122, 4, WOOD_HI)
    P(s, r.x + 18, r.y + 60, 122, 4, WOOD_D)
    for i in range(4):
        chair(s, r.x + 24 + i * 32, r.y + 66)
        chair(s, r.x + 24 + i * 32, r.y + 14)
    P(s, r.x + 34, r.y + 40, 12, 10, (222, 226, 232))
    P(s, r.x + 62, r.y + 38, 10, 12, (216, 180, 120))
    P(s, r.x + 100, r.y + 40, 14, 8, (140, 170, 150))
    mug(s, r.x + 78, r.y + 42)
    # 厨房
    P(s, r.x + 14, r.y + 112, 160, 36, (170, 176, 184))
    P(s, r.x + 14, r.y + 112, 160, 4, (208, 214, 220))
    P(s, r.x + 20, r.y + 118, 36, 24, (70, 74, 84))
    P(s, r.x + 24, r.y + 122, 10, 10, (40, 44, 52))
    P(s, r.x + 40, r.y + 122, 10, 10, (40, 44, 52))
    P(s, r.x + 64, r.y + 116, 40, 28, (200, 206, 214))
    P(s, r.x + 68, r.y + 120, 32, 3, (162, 170, 180))
    P(s, r.x + 112, r.y + 116, 42, 26, (150, 120, 86))
    for i in range(3):
        P(s, r.x + 116, r.y + 120 + i * 7, 34, 3, (120, 94, 66))
    P(s, r.x + 160, r.y + 116, 16, 22, (60, 64, 76))
    glow_dot(s, r.x + 164, r.y + 122, (220, 160, 90))
    glow(s, r.x + 70, r.y + 50, 80, (255, 214, 150), 24)
    poster(s, r.x + 152, r.y + 26, 26, 20, 2)

    # ================= 宿舍 =================
    r = rooms['dorm']
    for i in range(2):
        bunk(s, r.x + 10, r.y + 18 + i * 62, 58, 30)
        bunk(s, r.x + 80, r.y + 18 + i * 62, 58, 30)
    for i in range(4):
        P(s, r.x + 10 + i * 17, r.y + 140, 15, 20, (96, 104, 120))
        P(s, r.x + 10 + i * 17, r.y + 140, 15, 3, (126, 134, 152))
        glow_dot(s, r.x + 15 + i * 17, r.y + 149, (200, 206, 216))
    P(s, r.x + 146, r.y + 26, 14, 96, (150, 110, 96))
    P(s, r.x + 146, r.y + 26, 14, 6, (176, 132, 112))
    glow(s, r.x + 60, r.y + 80, 90, (255, 210, 150), 22)
    boots(s, r.x + 76, r.y + 146)
    mug(s, r.x + 92, r.y + 146)
    poster(s, r.x + 140, r.y + 128, 24, 18, 0)

    # ================= 实验室 =================
    r = rooms['lab']
    desk(s, r.x + 12, r.y + 24, 74, 26, (150, 156, 166))
    for i in range(4):
        P(s, r.x + 20 + i * 15, r.y + 28, 8, 12, (150, 200, 210))
        P(s, r.x + 20 + i * 15, r.y + 32, 8, 8, (110, 170, 190))
        glow(s, r.x + 24 + i * 15, r.y + 34, 16, (140, 220, 210), 16)
    desk(s, r.x + 96, r.y + 24, 52, 26, (150, 156, 166))
    P(s, r.x + 104, r.y + 28, 4, 12, (60, 64, 74))
    P(s, r.x + 100, r.y + 38, 12, 4, (60, 64, 74))
    pygame.draw.circle(s, (200, 206, 214), (r.x + 106, r.y + 28), 3)
    papers(s, r.x + 120, r.y + 32, 2)
    # 通风柜
    P(s, r.x + 12, r.y + 112, 54, 42, (120, 140, 156))
    P(s, r.x + 16, r.y + 116, 46, 34, (96, 120, 140))
    P(s, r.x + 16, r.y + 116, 46, 3, (152, 182, 202))
    # 离心机
    pygame.draw.circle(s, (90, 96, 108), (r.x + 96, r.y + 126), 13)
    pygame.draw.circle(s, (150, 156, 168), (r.x + 96, r.y + 126), 9)
    pygame.draw.circle(s, (60, 66, 78), (r.x + 96, r.y + 126), 3)
    poster(s, r.x + 76, r.y + 60, 30, 22, 1)
    vent(s, r.x + 140, r.y + 20, 22, 10)

    # ================= 大厅（所有人在这儿上班） =================
    r = rooms['hall']
    # 长条桌
    table = pygame.Rect(r.x + 26, r.y + 62, r.w - 52, 48)
    shadow(s, table.x, table.y, table.w, table.h, 70)
    P(s, table.x, table.y, table.w, table.h, WOOD)
    P(s, table.x, table.y, table.w, 5, WOOD_HI)
    P(s, table.x, table.y + table.h - 5, table.w, 5, WOOD_D)
    for i in range(8):
        P(s, table.x + 14 + i * 30, table.y + 10, 20, 3, (120, 96, 70))
    # 桌上的东西：杯子、文件、终端
    mug(s, table.x + 24, table.y + 22)
    papers(s, table.x + 54, table.y + 20, 2)
    P(s, table.x + 120, table.y + 16, 26, 16, (46, 52, 66))
    P(s, table.x + 123, table.y + 19, 20, 10, GLOW_D)
    mug(s, table.x + 190, table.y + 24)
    P(s, table.x + 240, table.y + 18, 30, 14, (54, 60, 76))
    glow(s, table.x + 118, table.y + 24, 30, (120, 200, 220), 18)
    # 椅子（上下各 5 把，正好对应 10 个工位）
    for i in range(5):
        cx = table.x + 18 + i * ((table.w - 40) // 4)
        chair(s, cx, table.y - 20)
        chair(s, cx, table.y + table.h + 6)
    # 墙上的值班表 + 公告
    poster(s, r.x + 40, r.y + 16, 52, 30, 0)
    poster(s, r.x + 112, r.y + 16, 30, 30, 1)
    # 咖啡角
    P(s, r.x + r.w - 92, r.y + 14, 70, 26, (150, 120, 86))
    P(s, r.x + r.w - 88, r.y + 18, 30, 16, (60, 64, 76))
    glow_dot(s, r.x + r.w - 76, r.y + 24, (220, 160, 90))
    lamp(s, r.centerx, r.centery - 52, (255, 224, 164), 110, 44)

    # ================= 仓库（补给船送来的物资） =================
    r = rooms['warehouse']
    for i in range(3):
        shelf(s, r.x + 14, r.y + 18 + i * 40, r.w - 28, 20)
    crate(s, r.x + 14, r.y + 128)
    crate(s, r.x + 36, r.y + 130)
    crate(s, r.x + 14, r.y + 146)
    crate(s, r.x + 58, r.y + 128)
    P(s, r.x + r.w - 52, r.y + 132, 40, 12, (120, 126, 136))
    P(s, r.x + r.w - 48, r.y + 128, 32, 4, (150, 156, 166))
    # 补给标记
    P(s, r.x + 10, r.y + 6, 44, 8, YELLOW)
    P(s, r.x + 10, r.y + 6, 44, 2, (250, 230, 150))
    cable(s, [(r.x + 8, r.y + 2), (r.x + r.w - 8, r.y + 2), (r.x + r.w - 8, r.y + r.h - 6)])

    # ================= 气闸 =================
    P(s, 318, 658, 104, 34, (92, 98, 112))
    P(s, 318, 658, 104, 4, (128, 134, 146))
    for i in range(9):
        P(s, 322 + i * 11, 686, 6, 6, YELLOW if i % 2 == 0 else (40, 40, 44))
    P(s, 348, 664, 44, 18, (62, 68, 82))
    P(s, 352, 668, 36, 10, (110, 170, 186))
    glow(s, 370, 700, 60, (255, 220, 150), 26)
    # 脚印
    rr = random.Random(9)
    for i in range(18):
        P(s, 366 + rr.randint(-6, 6), 700 - i * 0 + i * 2, 3, 2, (172, 188, 208))

    # ================= 室外 =================
    # 天线塔
    P(s, 676, 66, 4, 66, (140, 146, 156))
    for i in range(4):
        P(s, 668 + i * 4, 70 + i * 14, 14, 1, (120, 126, 136))
    pygame.draw.arc(s, (176, 184, 196), (656, 44, 44, 44), 3.5, 6.0, 3)
    glow_dot(s, 678, 62, (230, 120, 110))
    # 气象杆
    P(s, 24, 300, 3, 64, (150, 156, 166))
    P(s, 18, 296, 15, 2, (150, 156, 166))
    P(s, 27, 302, 22, 12, (206, 88, 80))
    # 雪地车
    P(s, 636, 618, 58, 26, (198, 122, 72))
    P(s, 642, 612, 46, 10, (172, 102, 60))
    P(s, 644, 622, 18, 12, (140, 190, 206))
    for cx in (648, 690):
        pygame.draw.circle(s, (48, 52, 60), (cx, 648), 9)
        pygame.draw.circle(s, (122, 128, 138), (cx, 648), 5)
    # 油桶
    for i in range(2):
        pygame.draw.circle(s, (172, 122, 72), (596 + i * 18, 640), 8)
        pygame.draw.circle(s, (204, 152, 92), (596 + i * 18, 638), 5)
    # 箱子
    crate(s, 84, 636)
    crate(s, 106, 640)
    crate(s, 84, 658)
    # 雪堆（扁一点、带阴影）
    for (x, y, w, h) in ((8, 622, 34, 10), (694, 430, 16, 46), (8, 214, 16, 40)):
        pygame.draw.ellipse(s, (186, 202, 222), (x + 1, y + 2, w, h))
        pygame.draw.ellipse(s, SNOW_HI, (x, y, w, max(4, h - 2)))

    # 站体边缘投影（左侧和下侧）
    sh = pygame.Surface((W, H), pygame.SRCALPHA)
    pygame.draw.rect(sh, (26, 34, 56, 70), (36, 40, 636, 632))
    pygame.draw.rect(sh, (0, 0, 0, 0), (44, 28, 620, 648))
    s.blit(sh, (0, 0))

    # 灯光与地面细节
    lamp(s, rooms['weather'].centerx, rooms['weather'].centerx and rooms['weather'].centery, (255, 226, 170), 96, 40)
    lamp(s, rooms['control'].centerx, rooms['control'].centery, (140, 210, 236), 100, 40)
    lamp(s, rooms['power'].centerx, rooms['power'].centery, (255, 170, 110), 90, 36)
    lamp(s, rooms['green'].centerx, rooms['green'].centery, (232, 140, 200), 100, 40)
    lamp(s, rooms['canteen'].centerx, rooms['canteen'].centery, (255, 214, 150), 110, 46)
    lamp(s, rooms['dorm'].centerx, rooms['dorm'].centery, (255, 210, 156), 100, 42)
    lamp(s, rooms['lab'].centerx, rooms['lab'].centery, (170, 230, 226), 96, 38)
    lamp(s, rooms['hall'].centerx, rooms['hall'].centery, (255, 224, 164), 110, 42)
    lamp(s, rooms['warehouse'].centerx, rooms['warehouse'].centery, (255, 214, 150), 80, 30)
    for cr in (corr_a, corr_b):
        for x in range(cr.x + 70, cr.right - 40, 150):
            lamp(s, x, cr.centery, (255, 228, 176), 70, 34)

    # 走廊导引线
    for cr in (corr_a, corr_b):
        guide_line(s, cr.x + 10, cr.right - 10, cr.bottom - 10)

    # 地面贴花
    P(s, rooms['canteen'].x + 24, rooms['canteen'].y + 84, 92, 20, (128, 72, 66))
    P(s, rooms['canteen'].x + 24, rooms['canteen'].y + 84, 92, 2, (154, 92, 84))
    pygame.draw.circle(s, (92, 104, 134), (rooms['control'].x + 60, rooms['control'].y + 128), 18)
    pygame.draw.circle(s, (110, 124, 158), (rooms['control'].x + 60, rooms['control'].y + 128), 15)
    pygame.draw.circle(s, (92, 104, 134), (rooms['control'].x + 60, rooms['control'].y + 128), 15, 2)
    # 大厅：地面上的安全区标线
    P(s, rooms['hall'].x + 30, rooms['hall'].y + 134, 234, 2, (150, 128, 96))
    # 温室：走道
    P(s, rooms['green'].x + 8, rooms['green'].y + 154, 174, 6, (110, 92, 70))

    # 门口指示灯
    for y, x in DOOR_SPECS:
        glow_dot(s, x + 17, y + (2 if y in (204, 428) else 8), (150, 220, 180))

    # 气闸外的雪坡
    pygame.draw.polygon(s, (216, 228, 242),
                        [(318, 692), (422, 692), (446, 704), (294, 704)])
    pygame.draw.line(s, (196, 210, 228), (300, 700), (440, 700), 2)

    # 雪地碎石
    rr = random.Random(31)
    for _ in range(40):
        x, y = rr.randint(0, W - 6), rr.randint(0, H - 6)
        if 36 < x < 668 and 24 < y < 676:
            continue
        P(s, x, y, 2, 2, (150, 166, 188))

    return s


def main():
    s = build()
    out = os.path.join(ROOT, 'assets', 'station.png')
    pygame.image.save(s, out)
    print('saved', out, s.get_size())
    # 行走掩码：墙 = 画墙的那些矩形
    cells = set()
    def mark(rect):
        x0, y0, w, h = rect
        for cy in range(int(y0 // 16), int((y0 + h) // 16) + 1):
            for cx in range(int(x0 // 16), int((x0 + w) // 16) + 1):
                # 只收"中心点落在矩形里"的格子
                px, py = cx * 16 + 8, cy * 16 + 8
                if x0 <= px <= x0 + w and y0 <= py <= y0 + h:
                    cells.add((cx, cy))
    walls = [
        (44, 28, 620, 12), (44, 664, 620, 12), (44, 28, 12, 648), (652, 28, 12, 648),
    ]
    for y in (204, 252, 428, 476, 652):
        walls.append((56, y, 596, 12))
    for x in (246, 462):
        walls += [(x, 40, 12, 164), (x, 264, 12, 164)]
    for x in (206, 500):
        walls += [(x, 488, 12, 164)]
    for wr in walls:
        mark(wr)
    # 门洞：门所在的那格清掉
    door_cells = set()
    for y, x in DOOR_SPECS:
        for cx in range(int(x // 16), int((x + 38) // 16) + 1):
            door_cells.add((cx, int((y + 6) // 16)))
    for x, y in VERT_DOORS:
        for cy in range(int(y // 16), int((y + 38) // 16) + 1):
            door_cells.add((int((x + 6) // 16), cy))
    # 气闸口：底墙中间开一格
    for cx in range(22, 27):
        door_cells.add((cx, 41))
    cells -= door_cells
    # 场景里站体摆在 APT_POS_ST=(112,0)，掩码要跟着挪到世界网格（960x720）
    SH = (7, 0)
    cells = {(cx + SH[0], cy + SH[1]) for cx, cy in cells}
    mask = dict(cell=16, cols=60, rows=45, walls=sorted([list(c) for c in cells]))
    with open(os.path.join(ROOT, 'assets', 'walkmask_station.json'), 'w') as f:
        json.dump(mask, f)
    print('saved assets/walkmask_station.json (%d 墙格)' % len(cells))

    # 带标注的预览
    pygame.image.save(s, '/tmp/station_raw.png')
    try:
        from PIL import Image, ImageDraw, ImageFont
        im = Image.open('/tmp/station_raw.png').convert('RGB')
        im = im.resize((W * 2, H * 2), Image.NEAREST)
        cands = ['/System/Library/Fonts/Hiragino Sans GB.ttc',
                 '/System/Library/Fonts/STHeiti Medium.ttc',
                 '/System/Library/Fonts/Supplemental/Songti.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
                 '/System/Library/Fonts/PingFang.ttc']
        fp = next((c for c in cands if os.path.exists(c)), cands[-1])
        f = ImageFont.truetype(fp, 26)
        fs = ImageFont.truetype(fp, 18)
        dr = ImageDraw.Draw(im, 'RGBA')
        labels = [
            ('气象观测室', 56, 40), ('主控通信', 258, 40), ('发电舱', 474, 40),
            ('温室', 56, 264), ('食堂', 258, 264), ('宿舍', 474, 264),
            ('实验室', 56, 488), ('大厅', 206, 488), ('仓库', 500, 488),
        ]
        for name, x, y in labels:
            dr.rectangle((x * 2 + 6, y * 2 + 8, x * 2 + 8 + 22 * len(name), y * 2 + 44),
                         fill=(10, 12, 18, 190))
            dr.text((x * 2 + 16, y * 2 + 12), name, font=f, fill=(240, 244, 252))
        dr.text((10, H * 2 - 28),
                '科考站 · 俯视像素地图（设计稿）  9 个房间 + 两条主走廊 + 气闸',
                font=fs, fill=(170, 180, 200))
        im.save(os.path.join(ROOT, 'design', '科考站俯视图.png'))
        print('saved design/科考站俯视图.png')
    except Exception as e:
        print('预览生成失败：', e)


if __name__ == '__main__':
    sys.exit(main())
