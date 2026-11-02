#!/usr/bin/env python3
"""截取游戏内某个角色在自己房间里踱步的一段，合成 GIF。

用法：python3 tools/shot_walk.py --char GLM
"""
import argparse
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('AIHUB_SAVE', '/tmp/aihub_test_save.json')
os.environ.setdefault('AIHUB_WALKMASK', '/tmp/aihub_no_mask.json')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402
import game as G  # noqa: E402
from PIL import Image  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--char', default='GLM')
    ap.add_argument('--out', default='/tmp')
    ap.add_argument('--zoom', type=int, default=3)
    a = ap.parse_args()

    g = G.Game()
    g.state = 'play'
    st = next(s for s in g.stations if s.m['id'] == a.char)
    st.unlocked = True
    st.walking = True
    st.dir = 1

    # 房间取景框（世界坐标）
    fx, fy = st.cx - 80, st.feet - 104
    fw, fh = 160, 110
    frames = []
    for i in range(28):
        # 一直走，不让她停下
        st.walk_span = 9.0
        g.update(1 / 12)
        g.draw()
        sub = g.screen.subsurface(pygame.Rect(fx, fy, fw, fh)).copy()
        raw = pygame.image.tostring(sub, 'RGB')
        img = Image.frombytes('RGB', (fw, fh), raw)
        frames.append(img.resize((fw * a.zoom, fh * a.zoom), Image.Resampling.NEAREST))

    pal = frames[0].quantize(colors=180, method=Image.Quantize.MEDIANCUT)
    qs = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    out = os.path.join(a.out, f'ingame_{a.char}.gif')
    qs[0].save(out, save_all=True, append_images=qs[1:], duration=84, loop=0, optimize=False)
    print('->', out, frames[0].size, len(frames), '帧')


if __name__ == '__main__':
    main()
