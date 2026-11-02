#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v40 自测：多人协作大单（关系门槛 / 最多三人 / 进度叠加 / 完成清理）。

用法：python3 tools/test_v40.py
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


def by_id(g, mid):
    return next(s for s in g.stations if s.m['id'] == mid)


def crew_task(g, w=60):
    t = game.Task('chat')
    t.state = 'stored'
    t.multi = True
    t.w = w
    g.tasks.append(t)
    return t


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 大单
    print('\n【协作大单】')
    g = game.Game()
    g.start_test_station()
    g.tasks.clear()
    for _ in range(6):
        g.try_spawn()
    check('科考站的单子都是协作单', all(t.multi for t in g.tasks))
    check('单子更大（最小工作量 > 30）', min(t.w for t in g.tasks) > 30)
    iv_station = g.spawn_interval()
    g.set_scene('apartment')
    check('科考站出单更慢', g.spawn_interval() < iv_station)

    # ------------------------------------------------ 关系门槛
    print('\n【关系门槛】')
    g = game.Game()
    g.start_test_station()
    a, b, c, d = by_id(g, 'Qwen'), by_id(g, 'GLM'), by_id(g, 'DeepSeek'), by_id(g, 'Gemini')
    t = crew_task(g)
    check('第一个人可以先开干', g.assign(t, a) is True)
    check('关系不好加不进来（bond < 0.5）',
          all(g.bond(a, x) < 0.5 for x in (b, c, d)) and g.assign(t, b) is False)
    g.set_bond(a, b, 0.7)
    check('关系够就能加入', g.assign(t, b) is True)
    check('协作人数记下来了', sorted(t.crew) == sorted(['Qwen', 'GLM']))

    # ------------------------------------------------ 最多三人
    print('\n【最多三人】')
    g.set_bond(a, c, 0.8)
    g.set_bond(b, c, 0.8)
    check('第三个人能进', g.assign(t, c) is True)
    check('三个人了', len(t.crew) == 3)
    g.set_bond(a, d, 0.9)
    g.set_bond(b, d, 0.9)
    g.set_bond(c, d, 0.9)
    check('第四个人被拒', g.assign(t, d) is False)
    check('还是三个人', len(t.crew) == 3)

    # ------------------------------------------------ 进度叠加
    print('\n【进度叠加】')
    g1 = game.Game()
    g1.start_test_station()
    t1 = crew_task(g1, w=200)
    g1.assign(t1, by_id(g1, 'Qwen'))
    for _ in range(10):
        g1.update(0.05)
    solo = t1.prog

    g3 = game.Game()
    g3.start_test_station()
    t3 = crew_task(g3, w=200)
    trio = [by_id(g3, x) for x in ('Qwen', 'GLM', 'DeepSeek')]
    for x in trio:
        for y in trio:
            if x is not y:
                g3.set_bond(x, y, 0.9)
    for x in trio:
        g3.assign(t3, x)
    for _ in range(10):
        g3.update(0.05)
    check('三个人一起干更快', t3.prog > solo * 2.0)

    # ------------------------------------------------ 完成 / 放弃
    print('\n【完成与放弃】')
    for _ in range(400):
        g3.update(0.05)
        if t3.state != 'service':
            break
    check('单子完成', t3.state == 'out')
    check('完成时清掉所有人的工位', all(x.busy is not t3 for x in trio))
    check('协作名单清空', t3.crew == [])

    g4 = game.Game()
    g4.start_test_station()
    q4, l4 = by_id(g4, 'Qwen'), by_id(g4, 'GLM')
    g4.set_bond(q4, l4, 0.9)
    t2 = crew_task(g4)
    g4.assign(t2, q4)
    g4.assign(t2, l4)
    g4.abandon_job(q4)
    check('有人放弃后，剩下的人继续', t2.state == 'service' and t2.crew == ['GLM'])

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
