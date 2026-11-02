#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v38 自测：科考站大厅办公 / 主控屏补给 / 仓库 / 温室 / 冰箱移除。

用法：python3 tools/test_v38.py
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


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 大厅
    print('\n【大厅】')
    g = game.Game()
    g.start_test_station()
    hall = game.STANDS_ST
    check('10 个工位都在大厅', len(hall) == 10)
    xs = sorted(set(x for x, y in hall.values()))
    ys = sorted(set(y for x, y in hall.values()))
    check('两排座位', len(ys) == 2)
    check('座位不重叠', len(xs) == 5)
    check('工位都在大厅（含场景偏移）', all(318 <= x <= 612 for x, y in hall.values()))
    # 每个工位脚下都能站
    free_ok = True
    for s in g.stations:
        c = g.walkmask.cell_of(s.px, s.feet)
        if not g.walkmask.free(*c):
            free_ok = False
    check('工位脚下都可走', free_ok)

    # ------------------------------------------------ 补给
    print('\n【主控屏补给】')
    g.money = 5000
    g.pending_supply = []
    g.warehouse = {'food': 0, 'fuel': 0, 'snack': 0}
    check('主控屏有热区', game.SUPPLY_RECT.w > 0)
    g.handle_click((game.SUPPLY_RECT.centerx, game.SUPPLY_RECT.centery))
    check('点主控屏打开补给面板', g.panel and g.panel[0] == 'supply')
    m0 = g.money
    g.buy_supply('food')
    check('下单扣钱', g.money == m0 - 120)
    check('订单进了待运清单', g.pending_supply == ['food'])
    check('船没到之前仓库是空的', g.warehouse['food'] == 0)
    g.deliver_supply()
    check('船到港后进仓库', g.warehouse['food'] == 10)
    check('待运清单清空', g.pending_supply == [])
    # 只有在补给日才自动送
    g.pending_supply = ['fuel']
    g.day = 3
    g.end_day()
    check('非补给日不送货', g.pending_supply == ['fuel'])
    g.day = 6
    g.money = 9000
    g.end_day()          # day 6 -> 7，补给日
    check('第 7 天补给船到货', g.pending_supply == [])

    # ------------------------------------------------ 仓库做饭
    print('\n【仓库食材】')
    g = game.Game()
    g.start_test_station()
    g.warehouse['food'] = 3
    before = g.warehouse['food']
    check('做饭优先掏仓库', g.take_food() and g.warehouse['food'] == before - 1)

    # ------------------------------------------------ 温室
    print('\n【温室】')
    g = game.Game()
    g.start_test_station()
    g.warehouse['food'] = 0
    g.t = (10 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g.update(0.05)
    for _ in range(3000):          # 千问要走去温室、干一会儿
        g.update(0.05)
        if g.warehouse['food'] >= 2:
            break
    check('千问有空就收 2 份', g.warehouse['food'] >= 2)
    g2 = game.Game()
    g2.start_test_station()
    g2.warehouse['food'] = 0
    qw = by_id(g2, 'Qwen')
    qw.busy = game.Task('code')
    g2.t = (10 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g2.update(0.05)
    check('千问忙就没收成', g2.warehouse['food'] == 0)

    # ------------------------------------------------ 冰箱没了
    print('\n【冰箱移除】')
    g = game.Game()
    g.state = 'play'
    check('公寓场景没有补给热区', game.SUPPLY_RECT.w == 0)
    g.draw()
    check('画一帧不报错', True)

    # ------------------------------------------------ 存档
    print('\n【存档】')
    g = game.Game()
    g.start_test_station()
    g.warehouse = {'food': 4, 'fuel': 2, 'snack': 1}
    g.pending_supply = ['fuel']
    g.slot = 4
    g.save()
    g2 = game.Game()
    g2.load(4)
    check('仓库库存进存档', g2.warehouse['food'] == 4)
    check('待运订单进存档', g2.pending_supply == ['fuel'])

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
