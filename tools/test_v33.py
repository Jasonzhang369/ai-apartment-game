#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v33 自测：气泡贴头且两人不重叠 / 关系可见 / 大肥鱼干活时煮饭占一路电、效率 -90%。

用法：python3 tools/test_v33.py
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


def by_id(g, mid):
    return next(s for s in g.stations if s.m['id'] == mid)


def bubble_rect(g, s, text):
    bx, by = g.chat_bubble_pos(s)
    w = game.text_w(text, 12, True) + 14
    h = game.font(12, True).get_height() + 6
    return pygame.Rect(bx - w // 2, by, w, h)


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 聊天气泡
    print('\n【聊天气泡】')
    g = fresh()
    a = by_id(g, 'Gemini')
    b = by_id(g, 'GLM')
    a.px, a.feet = 520, 408
    b.px, b.feet = 565, 408
    a.chat_partner, b.chat_partner = 'GLM', 'Gemini'
    la, lb = '你那显卡烫不烫？', '还行，刚换了风扇'
    ra = bubble_rect(g, a, la)
    rb = bubble_rect(g, b, lb)
    check('气泡贴着人物（离脚不超过 140px）', 40 < a.feet - ra.y < 140)
    check('两个气泡不重叠', not ra.colliderect(rb))
    plate = g.name_plate_pos(a)
    check('气泡不压名字牌', ra.bottom <= plate[1])
    # 单人（没对象）时居中
    a.chat_partner = None
    solo = bubble_rect(g, a, la)
    check('单人气泡居中在头顶', abs(solo.centerx - a.px) <= 2)

    # ------------------------------------------------ 关系可见
    print('\n【关系可见】')
    g = fresh()
    a = by_id(g, 'Gemini')
    b = by_id(g, 'GLM')
    a.px, a.feet = 520, 408
    b.px, b.feet = 560, 410
    check('一开始没有关系线', g.bond_pairs() == [])
    g.set_bond(a, b, 0.8)
    pairs = g.bond_pairs()
    check('关系够好会出现一对', len(pairs) == 1)
    check('关系值带出来了', abs(pairs[0][2] - 0.8) < 1e-6)
    check('工位面板能看到最熟的人',
          g.top_bonds(a, 2) and g.top_bonds(a, 2)[0][0] == 'GLM')
    g.draw()
    check('画关系心形不报错', True)
    # 离太远就不画
    b.px = a.px + 600
    check('离太远不画', g.bond_pairs() == [])

    # ------------------------------------------------ 大肥鱼煮饭
    print('\n【大肥鱼：干活时煮饭】')
    g = fresh()
    ds = by_id(g, 'DeepSeek')
    t = game.Task('code')
    ds.busy = t
    base = ds.work_factor()
    check('正常干活是满速', abs(base - 1.0) < 1e-9)
    g.start_slack(ds)
    check('干活时也能开始煮饭', ds.slack > 0)
    check('煮饭时效率只剩一成', abs(ds.work_factor() - 0.1) < 1e-9)
    check('煮饭时不能接新单', not ds.ready())
    load0 = g.grid_load()
    check('锅会多占一路电', load0 == 2)          # 1 路干活 + 1 路煮饭
    ds.busy = None
    check('不干活光煮饭也占一路', g.grid_load() == 1)
    g.stop_slack(ds)
    check('拦住之后不再占电', g.grid_load() == 0)
    check('拦住之后恢复满速', abs(ds.work_factor() - 1.0) < 1e-9)

    # 限流 + 煮饭会叠乘
    ds.busy = game.Task('code')
    ds.limited = True
    ds.slack = game.SLACK_SEC
    check('限流和煮饭叠乘（0.2 × 0.1）', abs(ds.work_factor() - 0.02) < 1e-9)
    ds.limited = False
    ds.slack = 0.0

    # 电闸：路数算上锅就会跳闸
    g = fresh()
    for st in g.stations:
        if st.m['id'] != 'DeepSeek':
            st.subscribed = False
    g.breaker_lv = 1                     # 容量 2
    ds = by_id(g, 'DeepSeek')
    ds.busy = game.Task('code')
    check('容量 2：1 路干活没问题', g.grid_load() <= g.breaker_cap())
    ds.slack = game.SLACK_SEC
    check('加上锅正好 2 路', g.grid_load() == 2)

    # ------------------------------------------------ 存档
    print('\n【存档】')
    g = fresh()
    g.set_bond(a, b, 0.6)
    g.slot = 3
    g.save()
    g2 = game.Game()
    g2.load(3)
    check('关系存下来了', abs(g2.bond(by_id(g2, 'Gemini'), by_id(g2, 'GLM')) - 0.6) < 1e-6)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
