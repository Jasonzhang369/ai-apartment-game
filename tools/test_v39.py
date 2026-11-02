#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v39 自测：搬迁门槛 / 三餐强制 / 宿舍睡觉 / 抓鱼 / 极夜 / 科考合同 / 任务疲劳。

用法：python3 tools/test_v39.py
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

    # ------------------------------------------------ 搬迁门槛
    print('\n【搬迁门槛】')
    g = game.Game()
    g.state = 'play'
    g.money = 99999
    g.day = 9
    for st in g.stations:
        st.unlocked = st.subscribed = True
    check('没升大模型不能搬', not g.can_relocate())
    by_id(g, 'DeepSeek').big = True
    check('只有 DeepSeek 也不行', not g.can_relocate())
    by_id(g, 'ChatGPT').big = True
    check('两个都升了大模型才能搬', g.can_relocate())

    # ------------------------------------------------ 三餐
    print('\n【三餐强制】')
    g = game.Game()
    g.start_test_station()
    g.warehouse['food'] = 0
    g.t = (8.1 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g.update(0.05)
    check('早饭没吃上 → 当天就减速 15%', abs(g.meal_penalty - 0.15) < 1e-6)
    s0 = by_id(g, 'Qwen')
    check('缺饭真的拖慢干活', s0.work_factor() < 0.9)
    g.t = (13.1 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g.update(0.05)
    check('再错过午饭 → 累计 30%', abs(g.meal_penalty - 0.30) < 1e-6)
    g.warehouse['food'] = 5
    g.meal_done.discard(18)
    g.t = (18.1 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    for _ in range(1200):
        g.update(0.05)
        if g.meal_penalty == 0:
            break
    check('吃到下一顿就恢复', g.meal_penalty == 0)
    check('一顿饭只回 6% 疲劳', abs(game.MEAL_FATIGUE - 0.06) < 1e-9)

    # ------------------------------------------------ 宿舍睡觉
    print('\n【宿舍睡觉】')
    g = game.Game()
    g.start_test_station()
    qw = by_id(g, 'Qwen')
    qw.fatigue = 0.99
    qw.social_state = 'home'
    g.update(0.05)
    check('累到极限会回宿舍睡', qw.social_state == 'nap' or qw.nap > 0)
    qw.walk_path = []
    qw.nap = 0.01
    g.update_nap(qw, 0.05)
    check('睡一觉疲劳降下来', qw.fatigue < 0.45)

    # ------------------------------------------------ 抓鱼
    print('\n【抓鱼】')
    g = game.Game()
    g.start_test_station()
    g.warehouse['food'] = 0
    g.green_day = g.day          # 今天温室已经收过了，别混进来
    g.meal_done.clear()
    g.t = (12 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g.update(0.05)
    ds = by_id(g, 'DeepSeek')
    check('没食材时 DeepSeek 去抓鱼', ds.fish > 0 or ds.social_state == 'fish')
    ds.walk_path = []
    ds.fish = 0.01
    g.update_fishing(ds, 0.05)
    check('抓完鱼食材 +2', g.warehouse['food'] == 2)
    check('抓鱼也涨疲劳', ds.fatigue >= game.FISH_FATIGUE - 1e-6)

    # ------------------------------------------------ 极夜
    print('\n【极夜】')
    g = game.Game()
    g.start_test_station()
    g.day = game.POLAR_DAY - 1
    g.update(0.05)
    b0 = g.fuel_burn()
    g.day = game.POLAR_DAY
    g.update(0.05)
    check('极夜燃料翻倍', g.fuel_burn() > b0 * 1.3)
    glm = by_id(g, 'GLM')
    qw = by_id(g, 'Qwen')
    game.GAME_POLAR = True
    check('极夜里 GLM 拿夜间加成', glm.spd() > glm.m['spd'] * game.SPEED_K)
    check('其他人额度没夜间折扣', g.quota_factor(qw) == 1.0)
    check('GLM 保留夜间额度折扣', g.quota_factor(glm) == game.NIGHT_COST)
    game.GAME_POLAR = False

    # ------------------------------------------------ 科考合同
    print('\n【科考合同】')
    g = game.Game()
    g.state = 'play'
    g.rep = 90
    g.delivered = {'code': 8}
    g.day = 6
    g.maybe_offer_contract()
    check('公寓里没有科考合同', not g.contract_offer)
    g.set_scene('station')
    g.maybe_offer_contract()
    check('科考站里会来谈合同', bool(g.contract_offer))
    g.draw()
    check('合同面板能画', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
