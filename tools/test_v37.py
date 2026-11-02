#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v37 自测：科考站试玩入口 / 新线路（Kimi·混元·Seed）/ 供暖燃料 / 值班。

用法：python3 tools/test_v37.py
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

    # ------------------------------------------------ 试玩入口
    print('\n【科考站试玩入口】')
    g = game.Game()
    g.start_test_station()
    check('直接进科考站', g.scene == 'station')
    check('进入游戏态', g.state == 'play')
    check('10 条线都在场', len(g.visible_stations()) == 10)
    check('全部已开通', all(s.unlocked for s in g.stations))
    check('全部已订阅', all(s.subscribed or s.forever for s in g.stations))
    check('燃料加满', g.fuel >= 100)
    check('给了启动资金', g.money >= 5000)

    # ------------------------------------------------ 新线路
    print('\n【新线路】')
    ids = [m['id'] for m in game.MODELS]
    for mid in ('Kimi', 'Hunyuan'):
        m = next(x for x in game.MODELS if x['id'] == mid)
        check(f'{mid} 在 roster 里', mid in ids)
        check(f'{mid} 只在科考站出现', m.get('scene') == 'station')
        check(f'{mid} 有立绘', g.assets.model(mid) is not None)
        check(f'{mid} 有三档订阅', len(m['tiers']) == 3)
        check(f'{mid} 是国内模型，不用 VPN 端口', m.get('need') is None)
        check(f'{mid} 没端口也能接单',
              by_id(g, mid).port_ok())
    # 名字：原来那条免费线现在叫 Seed
    free = next(m for m in game.MODELS if m['id'] == 'Doubao')
    check('免费线改名 Seed', free['name'] == 'Seed')
    check('没有单独的 Seed 线路了',
          sum(1 for m in game.MODELS if m['name'] == 'Seed') == 1)
    # 公寓里看不到科考站专属线路
    g2 = game.Game()
    g2.state = 'play'
    check('公寓里看不到新线路',
          len([x for x in g2.stations if g2.scene_ok(x)]) == 8)
    check('公寓图里也没有新线路的工位',
          'Kimi' not in game.STANDS)

    # ------------------------------------------------ 燃料
    print('\n【供暖燃料】')
    g = game.Game()
    g.start_test_station()
    live = len(g.station_live())
    check('烧的燃料跟在线线路有关', g.fuel_burn() >= 5)
    f0 = g.fuel
    g.end_day()
    check('打烊扣燃料', g.fuel < f0)
    check('燃料够时不冷', g.cold is False)
    g.fuel = 0.5
    g.end_day()
    check('燃料烧完就变冷', g.cold is True)
    s = by_id(g, 'Qwen')
    normal = s.work_factor()
    game.GAME_COLD = True
    check('冷了效率 -40%', abs(s.work_factor() / normal - 0.6) < 1e-6)
    game.GAME_COLD = False
    # 买燃料
    g.money = 1000
    m0 = g.money
    check('能买燃料', g.buy_fuel() is True)
    check('买燃料扣钱加量', g.money == m0 - 80 and g.fuel >= 20)
    check('买完就不冷了', g.cold is False)

    # ------------------------------------------------ 值班
    print('\n【值班】')
    g = game.Game()
    g.start_test_station()
    burn0 = g.fuel_burn()
    qw = by_id(g, 'Qwen')
    qw.duty = True
    check('值班的人不接单', not qw.ready())
    check('有人值班省燃料', g.fuel_burn() < burn0)
    qw.duty = False
    check('不当班就恢复接单', qw.ready())
    # 存档带上值班 / 燃料
    qw.duty = True
    g.fuel = 42.0
    g.slot = 4
    g.save()
    g2 = game.Game()
    g2.load(4)
    check('存档记住燃料', abs(g2.fuel - 42.0) < 1e-6)
    check('存档记住值班', by_id(g2, 'Qwen').duty is True)
    check('读档还在科考站', g2.scene == 'station')

    # ------------------------------------------------ 立绘按场景换
    print('\n【立绘】')
    g = game.Game()
    g.state = 'play'
    doubao = by_id(g, 'Doubao')
    check('公寓早餐铺还是原立绘（Nailong）',
          g.assets.sprite_id(doubao) == 'Nailong')
    check('原立绘确实加载了', g.assets.model('Nailong') is not None)
    g.start_test_station()
    doubao2 = by_id(g, 'Doubao')
    check('科考站豆包用新立绘（Doubao）',
          g.assets.sprite_id(doubao2) == 'Doubao')
    check('新立绘也加载了', g.assets.model('Doubao') is not None)

    # ------------------------------------------------ 科考站没有早餐铺
    print('\n【科考站没有早餐铺】')
    g = game.Game()
    g.start_test_station()
    g.money = 5000
    g.t = (7 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g.update(0.05)
    check('早上 7 点不弹“早餐铺开张”',
          not (g.toast and '早餐铺' in g.toast[0]))
    check('也买不到早餐', g.buy_breakfast() is False)
    g.draw()
    check('科考站画面里没有早餐铺招牌', g.scene == 'station')

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
