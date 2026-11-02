#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v41 自测：做饭改成整点前后半小时的窗口，两张地图都生效，同一顿不重复触发。

用法：python3 tools/test_v41.py
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


def make(scene):
    g = game.Game()
    g.state = 'play'
    for st in g.stations:
        st.unlocked = st.subscribed = True
        st.quota = 900
    if scene == 'station':
        g.start_test_station()
    g.money = 9999
    g.warehouse['food'] = 10
    return g


def at(g, hour):
    g.t = (hour - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN


def meal_state(g):
    qw = next(s for s in g.stations if s.m['id'] == 'Qwen')
    return qw.cooking, qw.social_state


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    for scene in ('apartment', 'station'):
        print(f'\n【{scene}】')
        # 11:36 —— 窗口内，提前做饭
        g = make(scene)
        at(g, 11.6)
        g.update(0.05)
        cooking, state = meal_state(g)
        check(f'{scene}: 11:36 就开始做午饭', cooking > 0 or state == 'cook')
        check(f'{scene}: 这顿记下了', 12 in g.meal_done)

        # 同一窗口不再触发第二次
        qw = next(s for s in g.stations if s.m['id'] == 'Qwen')
        qw.cooking = 0.0
        qw.social_state = 'home'
        g.update(0.05)
        check(f'{scene}: 同一顿不会做第二次', qw.social_state != 'cook')

        # 12:42 —— 窗口过了，不做，记“没赶上”
        g2 = make(scene)
        at(g2, 12.7)
        for _ in range(3):
            g2.update(0.05)
        qw2 = next(s for s in g2.stations if s.m['id'] == 'Qwen')
        check(f'{scene}: 12:42 不再补做', qw2.cooking == 0 and qw2.social_state != 'cook')
        check(f'{scene}: 窗口过了记为没赶上', 12 in g2.meal_done and g2.meals_today == 0)

        # 6:40 早饭窗口
        g3 = make(scene)
        f0 = g3.warehouse['food']
        at(g3, 6.7)
        if scene == 'apartment':
            g3.buy_breakfast()          # 公寓早饭去早餐铺买
            check('apartment: 6:40 买早饭算一顿', g3.meals_today == 1)
            check('apartment: 早饭不消耗仓库食材', g3.warehouse['food'] == f0)
        else:
            g3.update(0.05)
            check(f'{scene}: 6:40 吃早饭',
                  g3.meals_today == 1 and g3.warehouse['food'] == f0 - 1)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
