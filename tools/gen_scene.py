#!/usr/bin/env python3
"""从公寓布局图切出游戏用的场景素材。

做法：
  1. 取布局图（1920x1280）里公寓本体的裁切区域；
  2. 把它内部的每个房间，用「房间放大图」里对应那间的高清版本覆盖掉
     （放大图是 1024x948 的方形特写，按目标格子的宽高比居中裁一条，
      再去掉它自带的墙框，避免出现"框中框"）；
  3. 整张缩到 0.55，输出 assets/apartment.png；早餐铺单独切一张。

注意：房间放大图的文件名编号和布局图里的位置并不一致（比如 07_GLM 房间
其实是黑床哥特那间，在布局图里位于右三），所以下面按「实际内容」对应。
"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT = os.path.join(ROOT, '图像文件', '公寓', '布局图',
                      'Create_a_pixel_art_TOP_DOWN_fl_2026-10-27T13-56-49_副本.png')
ROOMS_DIR = os.path.join(ROOT, '图像文件', '公寓', '房间放大图')

APT_CROP = (373, 20, 1685, 1300)
SHOP_CROP = (30, 985, 345, 1300)
APT_SCALE = 0.55

# 楼梯间整体左右镜像（场景坐标，含上下墙；左右墙各自留在原处）。
# 电闸画在右墙上，镜像后要跟着挪到左墙——见 game.py 的 BREAKER。
STAIR_MIRROR = (298, 560, 455, 676)

# 放大图自身的外框（要去掉的墙）
INNER = (42, 38, 982, 910)

# (放大图文件, 在裁图坐标系里的目标矩形, 纵向取景 0=贴顶 0.5=居中 1=贴底)
ROOMS = [
    ('01_DeepSeek房间_副本.png', (8, 8, 397, 225), 1.00),
    ('02_客厅_副本.png',         (407, 8, 697, 225), 0.55),
    ('03_厨房与阳台_副本.png',   (707, 8, 1035, 225), 0.55),
    ('04_GPT房间_副本.png',      (8, 247, 397, 495), 0.50),
    ('05_Grok房间_副本.png',     (474, 247, 1047, 495), 0.50),
    ('06_Gemini房间_副本.png',   (8, 505, 397, 746), 0.55),
    ('07_GLM房间_副本.png',      (474, 505, 1047, 746), 0.55),
    ('08_Claude房间_副本.png',   (8, 756, 397, 992), 0.55),
    ('09_千问房间_副本.png',     (474, 756, 1047, 992), 0.55),
]


def fill_room(apt, name, rect, anchor):
    src = Image.open(os.path.join(ROOMS_DIR, name)).convert('RGB').crop(INNER)
    sw, sh = src.size
    tw, th = rect[2] - rect[0], rect[3] - rect[1]
    # 按目标宽高比横向铺满，纵向裁一条
    need_h = int(round(sw * th / tw))
    if need_h <= sh:
        top = int(round((sh - need_h) * anchor))
        src = src.crop((0, top, sw, top + need_h))
    else:
        need_w = int(round(sh * tw / th))
        left = (sw - need_w) // 2
        src = src.crop((left, 0, left + need_w, sh))
    src = src.resize((tw, th), Image.Resampling.LANCZOS)
    apt.paste(src, (rect[0], rect[1]))


def scene_rect_to_apt(rect):
    """场景坐标 -> apt（已裁切、未缩放）内部坐标。

    注意：apt 已经是 im.crop(APT_CROP) 的结果，所以这里只做平移+缩放，
    不能再加 APT_CROP 的偏移，否则会镜像到别的地方去。
    """
    x0, y0 = 200, 8        # 与 game.py 的 APT_POS 一致
    return (
        int(round((rect[0] - x0) / APT_SCALE)),
        int(round((rect[1] - y0) / APT_SCALE)),
        int(round((rect[2] - x0) / APT_SCALE)),
        int(round((rect[3] - y0) / APT_SCALE)),
    )


def mirror_region(img, rect):
    """把场景矩形里的画面左右翻转（只翻内容，不移动外面的墙）。"""
    box = scene_rect_to_apt(rect)
    part = img.crop(box).transpose(Image.FLIP_LEFT_RIGHT)
    img.paste(part, (box[0], box[1]))
    print('mirror', rect, '->', box)


def main():
    im = Image.open(LAYOUT).convert('RGB')
    apt = im.crop(APT_CROP)          # 1312 x 1280

    for name, rect, anchor in ROOMS:
        fill_room(apt, name, rect, anchor)

    # 房间贴完之后再镜像楼梯间：楼梯是布局图自带的，没有房间放大图覆盖
    mirror_region(apt, STAIR_MIRROR)

    out = apt.resize((int(apt.width * APT_SCALE), int(apt.height * APT_SCALE)),
                     Image.Resampling.LANCZOS)
    p1 = os.path.join(ROOT, 'assets', 'apartment.png')
    out.save(p1)
    print('apartment.png', out.size)

    shop = im.crop(SHOP_CROP)
    shop = shop.resize((int(shop.width * APT_SCALE), int(shop.height * APT_SCALE)),
                       Image.Resampling.LANCZOS)
    p2 = os.path.join(ROOT, 'assets', 'shop.png')
    shop.save(p2)
    print('shop.png', shop.size)

    # 调试用：未缩放的替换结果
    apt.save('/tmp/apt_patched_full.png')


if __name__ == '__main__':
    main()
