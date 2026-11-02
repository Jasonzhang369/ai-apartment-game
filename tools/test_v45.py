#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v45 自测：网关挪到主控右下 / 三块屏幕一个热区 / 上传去主控台。

用法：python3 tools/test_v45.py
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

    g = game.Game()
    g.start_test_station()

    print('\n【主控室】')
    x, y = game.GATEWAY
    check('网关在主控室右下', x > 500 and y > 130)
    check('网关在场景内', 0 < x < game.WW and 0 < y < game.WH)
    r = game.SUPPLY_RECT
    check('买物资和上传是同一个热区', r == game.UPLOAD_RECT)
    check('热区盖住三块屏幕（宽 > 150）', r.w > 150)
    check('热区在主控室上部', r.y < 120)

    print('\n【上传路线】')
    st = g.pick_quest_worker()
    g.dispatch_quest('ice', st)
    legs = [l[0] for l in st.quest['legs']]
    check('冰样最后一步是主控台', legs[-1] == 'CONSOLE')
    check('路线是 气闸→实验室→主控台', legs == ['BALCONY', 'LAB', 'CONSOLE'])
    g2 = game.Game()
    g2.start_test_station()
    g2.t = (10.2 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g2.quest_day = g2.day
    g2.weather = [1, 0]
    g2.update(0.05)
    st2 = g2.pick_quest_worker()
    g2.dispatch_quest('weather', st2)
    legs2 = [l[0] for l in st2.quest['legs']]
    check('气象路线是 气象室→主控台', legs2 == ['WEATHER', 'CONSOLE'])

    print('\n【科考期间不接单】')
    g3 = game.Game()
    g3.start_test_station()
    g3.t = (10.2 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g3.quest_day = g3.day
    g3.weather = [1, 0]
    g3.update(0.05)
    w = g3.pick_quest_worker()
    g3.dispatch_quest('weather', w)
    t = game.Task('chat')
    t.state = 'stored'
    t.w = 50
    g3.tasks.append(t)
    check('跑科考时派单被拒', g3.assign(t, w) is False)
    check('科考任务没被打断', w.quest is not None)

    print('\n【画一帧】')
    g.draw()
    check('主控室标注能画', True)
    # 最后一段（主控台）也能画进度条，标签不能是空
    g4 = game.Game()
    g4.start_test_station()
    g4.t = (10.2 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g4.update(0.05)
    w4 = g4.pick_quest_worker()
    g4.dispatch_quest('weather', w4)
    w4.quest['leg'] = 1
    w4.quest_t = 1.0
    g4.draw()
    check('最后一段（主控台）能画进度条', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
