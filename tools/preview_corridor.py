#!/usr/bin/env python3
"""走廊预览 C：暖木地板、不从客厅穿过、不加"像墙"的门槛横条、不接楼梯。"""
import os
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'assets', 'apartment.png')
OUT = os.path.join(ROOT, 'assets', 'apartment.png')   # 正式写入（备份见 apartment_before_corridor.png）
S = 0.55
CX0, CX1 = int(397 * S), int(474 * S)     # 走廊宽度
CY0, CY1 = 126, 546                       # 从客厅下方开始，到最下面一排房间

apt = Image.open(SRC).convert('RGB')
d = ImageDraw.Draw(apt)
w, h = CX1 - CX0, CY1 - CY0

# 暖木地板：程序化木条（竖条 + 错缝），不要横纹
import random
random.seed(7)
floor = Image.new('RGB', (w, h), (150, 120, 86))
fd = ImageDraw.Draw(floor)
plank = 10
for i in range(0, w, plank):
    base = 150 + random.randint(-8, 8)
    fd.rectangle([i, 0, i + plank - 1, h], fill=(base, base - 26, base - 58))
    fd.line([i, 0, i, h], fill=(112, 90, 64))
# 错缝：每列在不同高度断开
for i in range(0, w, plank):
    y = random.randint(0, 12)
    while y < h:
        fd.line([i, y, i + plank - 1, y], fill=(124, 100, 72))
        y += random.randint(28, 44)
apt.paste(floor, (CX0, CY0))

# 两侧细墙线（1px）+ 极轻的内阴影
d.rectangle([CX0, CY0, CX0 + 1, CY1], fill=(64, 52, 38))
d.rectangle([CX1 - 1, CY0, CX1, CY1], fill=(64, 52, 38))
for i in range(2):
    c = (120 - i * 20, 100 - i * 16, 74 - i * 14)
    d.rectangle([CX0 + 2 + i, CY0, CX0 + 2 + i, CY1], fill=c)
    d.rectangle([CX1 - 3 - i, CY0, CX1 - 3 - i, CY1], fill=c)

# 两端收口（上下各一条细边，不是门槛横条）
d.rectangle([CX0, CY0, CX1, CY0 + 1], fill=(96, 80, 58))
d.rectangle([CX0, CY1 - 1, CX1, CY1], fill=(96, 80, 58))

# 两盏壁灯 + 柔和暖光
glow = Image.new('L', apt.size, 0)
gd = ImageDraw.Draw(glow)
for ly in (CY0 + 90, CY1 - 100):
    d.rectangle([CX0 + 4, ly - 3, CX0 + 9, ly + 3], fill=(255, 222, 156))
    gd.ellipse([CX0 - 16, ly - 22, CX1 + 16, ly + 22], fill=55)
glow = glow.filter(ImageFilter.GaussianBlur(8))
apt = Image.composite(Image.new('RGB', apt.size, (255, 230, 182)), apt, glow)
apt.save(OUT)
print('saved', OUT)
