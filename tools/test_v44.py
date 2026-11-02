#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v44 自测：Seed 按官网定位调强 / 雪地补给车。

用法：python3 tools/test_v44.py
"""
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('AIHUB_SAVE', '/tmp/aihub_test_save.json')
os.environ.setdefault('AIHUB_WALKMASK', '/tmp/aihub_no_mask.json')
os.environ.setdefault('AIHUB_SETTINGS', '/tmp/aihub_test_settings.json')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402
import game  # noqa: E402

game.RENT_NOTICE_ON = False
game.INTRO_ON = False

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f'  [通过] {name}')
    else:
        fail += 1
        print(f'  [失败] {name}')


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    print('\n【Seed 强度】')
    m = next(x for x in game.MODELS if x['id'] == 'Doubao')
    check('Seed 已接电、需要订阅', not m.get('forever') and not m.get('nopower')
          and len(m['tiers']) >= 1 and m['tiers'][0][1] > 0)
    check('速度比原来的 1.7 快', m['spd'] > 2.0)
    check('质量比原来的 0.32 高', m['q'] > 0.45)
    check('单价比原来便宜', m['cost'] < 0.03)
    check('能吃文档类任务', 'doc' in m['tags'])
    check('还是最便宜的一条', min(x['cost'] for x in game.MODELS) == m['cost'])

    print('\n【雪地补给车】')
    g = game.Game()
    g.start_test_station()
    r = game.SUPPLY_CAR_RECT
    check('补给车有热区', r.w > 0 and r.h > 0)
    g.pending_supply = ['food', 'fuel']
    g.handle_click((r.centerx, r.centery))
    check('点补给车有提示', True)
    check('车上有货时能报数量', g.click_supply_car() is True)

    # 7 天到货
    g.warehouse['food'] = 0
    g.fuel = 0.0
    g.pending_supply = ['food', 'fuel']
    g.day = 6
    g.end_day()
    check('第 7 天补给车到货：食材 +10', g.warehouse['food'] == 10)
    check('第 7 天补给车到货：燃料 +30', g.fuel >= 30)
    check('到货后车上清空', g.pending_supply == [])

    print('\n【公寓里别乱点】')
    g2 = game.Game()
    g2.state = 'play'
    check('公寓没有补给车热区', game.SUPPLY_CAR_RECT.w == 0)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
