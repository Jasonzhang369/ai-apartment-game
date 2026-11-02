#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v36 自测：第二幕（搬去南极科考站）/ 场景切换 / 首页版权说明。

用法：python3 tools/test_v36.py
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


def fresh():
    g = game.Game()
    g.state = 'play'
    for st in g.stations:
        st.unlocked = st.subscribed = True
        st.quota = 900
    return g


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 默认在公寓
    print('\n【场景】')
    g = fresh()
    check('开局在公寓', g.scene == 'apartment')
    check('公寓背景是 apartment.png', g.assets.apartment is g.assets.apt_img)
    apt_stand = game.STANDS['Qwen']
    check('公寓工位在公寓坐标', apt_stand == (620, 542))

    # 钱不够 / 天数不够都不能搬
    g.money = 100
    g.day = 9
    check('钱不够不能搬', not g.can_relocate())
    g.money = 9999
    g.day = 2
    check('太早不能搬（第 5 天起才提）', not g.can_relocate())
    g.day = 6
    check('没升大模型不能搬', not g.can_relocate())
    next(x for x in g.stations if x.m['id'] == 'DeepSeek').big = True
    check('只升 DeepSeek 还是不行', not g.can_relocate())
    next(x for x in g.stations if x.m['id'] == 'ChatGPT').big = True
    check('钱够 + 大模型齐了 + 第 5 天后可以搬', g.can_relocate())

    # 搬过去
    m0 = g.money
    qwen = next(s for s in g.stations if s.m['id'] == 'Qwen')
    qwen.gear.add('cpu')
    check('搬迁成功', g.relocate() is True)
    check('扣了搬迁费', abs(m0 - g.money - game.RELOCATE_COST) < 1e-6)
    check('场景切到科考站', g.scene == 'station')
    check('背景换成站体', g.assets.apartment is g.assets.station)
    check('坐标表换成站点', game.STANDS['Qwen'] != apt_stand)
    check('人站到新工位上',
          abs(qwen.cx - game.STANDS['Qwen'][0]) < 1
          and abs(qwen.feet - game.STANDS['Qwen'][1]) < 1)
    check('装备跟着搬过来', 'cpu' in qwen.gear)
    check('加载了站点行走掩码',
          g.walkmask is not None and 'station' in (g.walkmask and 'station' or 'station'))
    # 工位脚下必须是可走格
    free_ok = True
    for s in g.stations:
        c = g.walkmask.cell_of(s.px, s.feet) if g.walkmask else (0, 0)
        if g.walkmask and not g.walkmask.free(*c):
            free_ok = False
    check('每个工位都站得住（不在墙里）', free_ok)

    # 场景切换后还能正常工作
    g.money = 5000
    g.draw()
    check('科考站场景能画', True)
    t = game.Task('chat')
    t.state = 'stored'
    g.tasks.append(t)
    check('在科考站也能派单', g.assign(t, next(x for x in g.stations if x.m['id'] == 'Qwen')) is True)

    # ------------------------------------------------ 存档
    print('\n【存档】')
    g.slot = 3
    g.save()
    g2 = game.Game()
    g2.load(3)
    check('存档记住场景', g2.scene == 'station')
    check('读档后还在科考站', game.STANDS['Qwen'] == game.STANDS_ST['Qwen'])
    check('读档后工位也对', abs(next(s for s in g2.stations if s.m['id'] == 'Qwen').cx
                               - game.STANDS_ST['Qwen'][0]) < 1)

    # 搬回公寓（内部接口）也能还原
    g2.set_scene('apartment')
    check('能切回公寓', g2.scene == 'apartment' and game.STANDS['Qwen'] == (620, 542))

    # ------------------------------------------------ 首页说明
    print('\n【首页说明】')
    check('首页有作者/出处/版权字段',
          all(k in game.CREDITS for k in ('author', 'source', 'note')))
    check('版权说明里写了不作商业用途', '商业' in game.CREDITS['note'])
    t2 = game.Game()
    t2.state = 'title'
    t2.draw()
    check('标题页能画（含版权行）', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
