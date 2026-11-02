#!/usr/bin/env python3
"""行走动画预览：把角色放进公寓房间图里走一圈，输出 GIF + 分解图。

用来在接进游戏前先确认「人物与房间的比例」和动画观感。

用法：
    python3 tools/walk_preview.py --char GLM --scale 0.6
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join(ROOT, '图像文件', '公寓', '布局图',
                      'Create_a_pixel_art_TOP_DOWN_fl_2026-10-27T13-56-49_副本.png')
CHARS = os.path.join(ROOT, '图像文件', '人物 64*64')

# 布局图里各房间的裁剪框（原图坐标）与可走动的空地（裁剪图内的 x0,x1,脚底 y）
ROOMS = {
    'GLM': dict(crop=(340, 480, 830, 820), walk=(250, 440, 266)),
    'DeepSeek': dict(crop=(340, 20, 830, 200), walk=(60, 430, 150)),
    'GPT': dict(crop=(340, 250, 830, 560), walk=(60, 430, 400)),
}


def load_frames(char):
    """返回 (侧向行走帧, 正面行走帧)。"""
    d = os.path.join(CHARS, f'{char}像素_副本')
    if not os.path.isdir(d):
        d = os.path.join(CHARS)
    side_p = os.path.join(d, f'{char}_walk_side_sheet_64.png')
    front_p = os.path.join(d, f'{char}_walk_sheet_64.png')
    side, front = [], []
    if os.path.exists(side_p):
        sheet = Image.open(side_p).convert('RGBA')
        side = [sheet.crop((i * 64, 0, i * 64 + 64, 64)) for i in range(sheet.width // 64)]
    if os.path.exists(front_p):
        sheet = Image.open(front_p).convert('RGBA')
        front = [sheet.crop((i * 64, 0, i * 64 + 64, 64)) for i in range(sheet.width // 64)]
    if not side:
        side = front
    return side, front


def build(char, scale, room_name, out_gif, out_strip):
    room = ROOMS[room_name]
    src = Image.open(LAYOUT).convert('RGB').crop(room['crop'])
    if scale != 1.0:
        src = src.resize((int(src.width * scale), int(src.height * scale)),
                         Image.Resampling.LANCZOS)
    W, H = src.size
    side, _ = load_frames(char)
    if not side:
        raise SystemExit(f'没有找到 {char} 的行走帧')

    x0, x1, foot_y = room['walk']
    x0, x1, foot_y = int(x0 * scale), int(x1 * scale), int(foot_y * scale)

    # 一条来回走的路径：右 6 步、左 6 步，每步 7px
    step = max(3, round(7 * scale))
    frames_idx = []
    pos = []
    x = x0
    for i in range(6):
        frames_idx.append((i % len(side), False))
        pos.append(x)
        x += step
    for i in range(6):
        frames_idx.append((i % len(side), True))
        pos.append(x)
        x -= step

    shots = []
    for k, ((fi, flip), px) in enumerate(zip(frames_idx, pos)):
        canvas = src.convert('RGBA')
        fr = side[fi]
        if flip:
            fr = fr.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        # 走路时身体轻微上下：两帧一沉
        bob = -1 if (k // 2) % 2 == 0 else 0
        # 影子
        sh = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse((px - 11, foot_y - 3, px + 11, foot_y + 3), fill=(0, 0, 0, 80))
        canvas.alpha_composite(sh)
        canvas.alpha_composite(fr, (px - 32, foot_y - 63 + bob))
        shots.append(canvas)

    # GIF（放大 2 倍更清楚）
    big = [s.resize((W * 2, H * 2), Image.Resampling.NEAREST).convert('RGB') for s in shots]
    pal = big[0].quantize(colors=200, method=Image.Quantize.MEDIANCUT)
    frames = [b.quantize(palette=pal, dither=Image.Dither.NONE) for b in big]
    frames[0].save(out_gif, save_all=True, append_images=frames[1:], duration=90, loop=0,
                   optimize=False, disposal=1)

    # 分解图（每帧并排，2 倍）
    n = len(shots)
    cols = 3
    rows = (n + cols - 1) // cols
    pad = 6
    strip = Image.new('RGBA', (cols * (W * 2 + pad) + pad,
                               rows * (H * 2 + pad) + pad), (18, 19, 26, 255))
    for i, s in enumerate(shots):
        cx, cy = i % cols, i // cols
        strip.alpha_composite(s.resize((W * 2, H * 2), Image.Resampling.NEAREST),
                              (pad + cx * (W * 2 + pad), pad + cy * (H * 2 + pad)))
    strip.save(out_strip)
    print(f'画布 {W}x{H}（缩放 {scale}），角色 64px，占房间高 {64 / H * 100:.0f}%')
    print('GIF ->', out_gif)
    print('分解图 ->', out_strip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--char', default='GLM')
    ap.add_argument('--room', default='GLM')
    ap.add_argument('--scale', type=float, default=0.6)
    ap.add_argument('--out', default='/tmp')
    a = ap.parse_args()
    build(a.char, a.scale, a.room,
          os.path.join(a.out, f'walk_{a.char}_{a.scale}.gif'),
          os.path.join(a.out, f'walk_{a.char}_{a.scale}_strip.png'))


if __name__ == '__main__':
    main()
