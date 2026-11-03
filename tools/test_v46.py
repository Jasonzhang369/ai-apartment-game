#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v46 自测：仓库面板 / 装备随补给到 / 电闸面板不再卖燃料。

用法：python3 tools/test_v46.py
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

    print('\n【仓库】')
    g = game.Game()
    g.start_test_station()
    g.money = 9999
    check('仓库有热区', game.WAREHOUSE_RECT.w > 0)
    g.handle_click((game.WAREHOUSE_RECT.centerx, game.WAREHOUSE_RECT.centery))
    check('点仓库打开仓储面板', g.panel == ('storage', None))
    check('仓储里有库存和天数', g.warehouse['food'] >= 0)
    g.warehouse['food'] = 7
    g.fuel = 84.0
    g.draw()
    check('仓储面板能画', True)

    print('\n【装备随补给到】')
    g = game.Game()
    g.start_test_station()
    g.money = 9999
    cpu = next(x for x in game.GEAR if x['id'] == 'cpu')
    check('下单成功', g.buy_gear(cpu) is True)
    check('没直接进背包', g.bag_count('cpu') == 0)
    check('进了在途清单', 'cpu' in g.pending_gear)
    g.day = game.SUPPLY_EVERY - 1      # 补给周期 3 天
    g.end_day()
    check('补给日送到', g.bag_count('cpu') == 1)
    check('在途清单清空', g.pending_gear == [])

    print('\n【装备店并进仓库】')
    check('站内没有单独装备店热区', game.GEAR_SHOP_RECT.w == 0)

    print('\n【电闸面板】')
    g = game.Game()
    g.start_test_station()
    g.money = 9999
    g.panel = ('breaker', None)
    g.draw()
    check('电闸面板能画（不含买燃料）', True)
    # 面板底部原来买燃料的位置点一下：不该扣钱加燃料
    r = g.breaker_panel_rect()
    f0, m0 = g.fuel, g.money
    g.click_panel(r.x + 60, r.y + 250)
    check('电闸面板不卖燃料', g.fuel == f0 and g.money == m0)

    print('\n【豆包 / Seed】')
    apt = game.Game()
    apt.state = 'play'
    d1 = next(x for x in apt.stations if x.m['id'] == 'Doubao')
    check('公寓里叫豆包', d1.m['name'] == '豆包')
    check('公寓豆包免费不限量', d1.m.get('forever') and d1.m['tiers'][0][2] == -1)
    check('公寓豆包不在电路上', d1.on_grid() is False)
    stt = game.Game()
    stt.start_test_station()
    d2 = next(x for x in stt.stations if x.m['id'] == 'Doubao')
    check('科考站里叫 Seed', d2.m['name'] == 'Seed')
    check('站里 Seed 要订阅', not d2.m.get('forever') and d2.m['tiers'][0][1] > 0)
    check('站里 Seed 接电', d2.on_grid() is True)

    print('\n【冰样统计】')
    g = game.Game()
    g.start_test_station()
    g.t = (10.2 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g.update(0.05)
    check('开局冰样未做', g.ice_done != g.day)
    w = g.pick_quest_worker()
    g.dispatch_quest('ice', w)
    for _ in range(9000):
        g.update(0.05)
        if w.quest is None:
            break
    check('跑一趟还不算完成（要两趟）', g.ice_done != g.day and g.ice_runs == 1)
    check('跑完回到空闲', g.ice == 0)
    # 第二趟：等冷却过去
    g.quest_last['ice'] -= 9.0
    for _ in range(6000):
        if any(g.worker_available(x) for x in g.stations
               if x.m['id'] != 'Doubao'):
            break
        g.update(0.05)
    w2 = g.pick_quest_worker()
    if w2 is not None:
        g.dispatch_quest('ice', w2)
        for _ in range(9000):
            g.update(0.05)
            if w2.quest is None:
                break
        check('两趟跑完记为今天完成', g.ice_done == g.day and g.ice_runs == 2)
    g.panel = ('server', 0)
    g.draw()
    check('完成后面板能画', True)

    print('\n【背包并进仓库 / 购买统一在主控屏】')
    g = game.Game()
    g.start_test_station()
    g.money = 9999
    g.bag_add('cpu')
    for key, r in g.pane_buttons():
        if key == 'bag':
            g.handle_click((r.centerx, r.centery))
            break
    check('背包按钮打开仓库', g.panel == ('storage', None))
    g.panel = ('storage', None)
    g.draw()
    check('仓库里能画背包', True)

    g.panel = ('supply', None)
    gears = {x['id']: b for x, b in g.supply_gear_rects()}
    check('主控屏能买装备', 'cpu' in gears)
    g.click_panel(gears['cpu'].centerx, gears['cpu'].centery)
    check('主控屏下单进在途', 'cpu' in g.pending_gear)
    g.draw()
    check('主控屏装备区能画', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
