#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v32 自测：千问做饭（食材/恢复疲劳/加速/不可打断）/ 社交默契 /
长期合同 / Claude 与端口调价 / 后期节奏。

用法：python3 tools/test_v32.py
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


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 食材
    print('\n【食材包】')
    g = fresh()
    g.money = 9999
    check('开局背包里没有食材', g.bag_count(game.FOOD_ID) == 0)
    m0 = g.money
    g.buy_food()
    check('能买食材包', g.bag_count(game.FOOD_ID) == 1)
    check('扣了钱', abs((m0 - g.money) - game.FOOD_PRICE) < 1e-6)
    g.buy_food()
    check('可以囤多份', g.bag_count(game.FOOD_ID) == 2)

    # ------------------------------------------------ 千问做饭
    print('\n【千问做饭】')
    g = fresh()
    g.money = 9999
    qw = by_id(g, 'Qwen')
    g.buy_food()                # 12 点做饭：早饭窗口早过了，只做这一顿
    for st in g.stations:
        st.fatigue = 0.6
    spd_before = qw.spd()
    g.t = (12 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g.update(0.05)
    check('到 12:00 千问开始做饭', qw.cooking > 0 or qw.social_state == 'cook')
    check('做饭消耗一份食材', g.bag_count(game.FOOD_ID) == 0)
    check('做饭时不能派单', not qw.ready())
    t = game.Task('chat')
    t.state = 'stored'
    g.tasks.append(t)
    check('派单会被拒绝', g.assign(t, qw) is False)
    check('做饭不可被打断', qw.cooking > 0 or qw.social_state == 'cook')
    # 直接推到做完
    qw.walk_path = []
    qw.cooking = 0.01
    g.update_cooking(qw, 0.05)
    check('做完后全站回疲劳',
          all(abs(st.fatigue - (0.6 - game.MEAL_FATIGUE)) < 1e-6
              for st in g.stations if st.unlocked and not st.no_fatigue))
    check('做完有速度加成', qw.meal > 0)
    check('速度确实变快', qw.spd() > spd_before)

    # 没有食材就不做
    g2 = fresh()
    g2.money = 9999
    qw2 = by_id(g2, 'Qwen')
    g2.t = (12 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g2.update(0.05)
    check('没食材就不做饭', qw2.cooking <= 0)

    # 一天只做两次（午饭/晚饭）
    g3 = fresh()
    g3.money = 9999
    for _ in range(3):
        g3.buy_food()
    qw3 = by_id(g3, 'Qwen')
    g3.t = (12 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g3.update(0.05)
    slot1 = set(g3.meal_done)
    g3.t = (13 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g3.update(0.05)
    check('同一个饭点只做一次', g3.meal_done == slot1)

    # ------------------------------------------------ 默契
    print('\n【社交默契】')
    g = fresh()
    a = by_id(g, 'Gemini')
    b = by_id(g, 'GLM')
    a.px, a.feet = 500, 400
    b.px, b.feet = 540, 402
    check('一开始只有一点点初始好感', 0 <= g.bond(a, b) <= 0.11)
    g.begin_chat(a, b)
    check('聊一次涨默契', g.bond(a, b) > 0)
    for _ in range(5):
        a.social_state = b.social_state = 'home'
        g.begin_chat(a, b)
    check('默契有上限', g.bond(a, b) <= 1.0)
    a.busy = game.Task('code')
    b.busy = game.Task('code')
    g.update_bonds()
    check('两人同时干活有默契加成', a.bond_boost > 0)
    boosted = a.spd()
    a.bond_boost = 0.0
    check('默契确实提速', boosted > a.spd())
    a.busy = None
    g.update_bonds()
    check('不干活就没加成', a.bond_boost == 0.0)

    # ------------------------------------------------ 长期合同
    print('\n【长期合同】')
    g = fresh()
    g.set_scene('station')          # 科考合同只在科考站
    g.rep = 80
    g.delivered = {'code': 8}
    g.day = 4
    g.maybe_offer_contract()
    check('交付够多会有合同报价', bool(g.contract_offer))
    check('报价是个弹窗', g.panel and g.panel[0] == 'contract')
    g.draw()
    check('合同面板能画', True)
    g.accept_contract()
    check('签下合同', bool(g.contract) and g.contract['typ'] == 'code')
    check('合同期 5 天、每天 2 单',
          g.contract['left'] == 5 and g.contract['need'] == 2)

    # 合同单会优先出现，而且带标记
    g.tasks.clear()
    for _ in range(40):
        g.try_spawn()
    check('会刷出合同单', any(t.contract for t in g.tasks if t.typ == 'code'))

    # 每天考核
    g.contract['today'] = 2
    g.check_contract_end()
    check('交够了：天数 -1', g.contract['left'] == 4)
    check('计数清零', g.contract['today'] == 0)
    g.contract['today'] = 0
    rep0 = g.rep
    g.check_contract_end()
    check('没交够：合同作废', g.contract is None)
    check('违约扣声誉', g.rep < rep0)

    # 完成奖金
    g2 = fresh()
    g2.contract = dict(typ='chat', left=1, need=1, today=1, reward=600)
    m0 = g2.money
    g2.check_contract_end()
    check('完成发奖金', abs((g2.money - m0) - 600) < 1e-6)
    check('完成后合同清空', g2.contract is None)

    # ------------------------------------------------ 调价 / 后期节奏
    print('\n【调价与节奏】')
    g = fresh()
    vpn = next(x for x in game.GEAR if x['id'] == 'vpn')
    enc = next(x for x in game.GEAR if x['id'] == 'vpn_enc')
    check('VPN 端口降到 600', vpn['price'] == 600)
    check('加密端口降到 1000', enc['price'] == 1000)
    check('Claude 速度上调到 2.8', by_id(g, 'Claude').m['spd'] == 2.8)
    g.day = 30
    check('后期单量上限 1.30', abs(g.day_big() - 1.30) < 1e-9)
    g.day = 1
    check('开局不受影响', abs(g.day_big() - 1.0) < 1e-9)

    # ------------------------------------------------ 存档
    print('\n【存档带上新状态】')
    g = fresh()
    g.money = 9999
    g.buy_food()
    g.bonds[('Gemini', 'GLM')] = 0.7
    g.delivered = {'code': 5}
    g.contract = dict(typ='code', left=3, need=2, today=1, reward=600)
    g.slot = 4
    g.save()
    g2 = game.Game()
    g2.load(4)
    check('食材存下来了', g2.bag_count(game.FOOD_ID) == 1)
    check('默契存下来了', abs(g2.bonds.get(('Gemini', 'GLM'), 0) - 0.7) < 1e-6)
    check('交付计数存下来了', g2.delivered.get('code') == 5)
    check('合同存下来了', bool(g2.contract) and g2.contract['left'] == 3)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
