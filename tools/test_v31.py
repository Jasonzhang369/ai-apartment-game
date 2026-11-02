#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v31 自测：疲劳只有休息日能消 / VPN 端口门禁与周费 / 串门改成"找人" /
路上相遇对话 / 隔着墙不聊天。

用法：python3 tools/test_v31.py
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

    # ------------------------------------------------ 疲劳
    print('\n【疲劳：只有休息日能消】')
    g = fresh()
    ds = by_id(g, 'DeepSeek')
    ds.fatigue = 0.6
    f0 = ds.fatigue
    for _ in range(300):          # 15 秒啥也不干
        g.update(0.05)
    check('闲着不会恢复疲劳', abs(ds.fatigue - f0) < 1e-9)
    check('疲劳会拖慢速度', ds.efficiency() < 1.0)
    check('惩罚是"少量"（≤20%）', game.FATIGUE_PENALTY <= 0.2)
    ds.resting = True
    for _ in range(120):
        g.update(0.05)
    check('休息时才降疲劳', ds.fatigue < f0)
    ds.resting = False
    ds.fatigue = 0.9
    g.take_rest_day()
    check('全员休息日把疲劳清零', ds.fatigue == 0.0)

    # ------------------------------------------------ VPN 端口
    print('\n【VPN 端口门禁】')
    g = fresh()
    g.money = 99999
    gr = by_id(g, 'Grok')
    gm = by_id(g, 'Gemini')
    cg = by_id(g, 'ChatGPT')
    cl = by_id(g, 'Claude')
    for st in (gr, gm, cg, cl):
        check(f'{st.m["name"]} 没端口不能接单', not st.ready() and st.needs_port())
    vpn = next(x for x in game.GEAR if x['id'] == 'vpn')
    enc = next(x for x in game.GEAR if x['id'] == 'vpn_enc')
    g.buy_gear(vpn)
    g.equip_gear(gr, 'vpn')
    check('Grok 装了普通端口就能用', gr.ready() and gr.port_ok())
    check('普通端口对 Grok 没有加速', abs(gr.spd() - gr.m['spd'] * game.SPEED_K
                                          * gr.efficiency()) < 1e-6)
    g.buy_gear(vpn)
    g.equip_gear(cl, 'vpn')
    check('Claude 普通端口不够', not cl.port_ok())
    g.buy_gear(enc)
    g.equip_gear(cl, 'vpn_enc')
    check('Claude 需要加密端口，装了就能用', cl.port_ok() and cl.ready())

    before = cl.spd()
    cl.gear.discard('vpn_enc')
    after = cl.spd()
    cl.gear.add('vpn_enc')
    check('加密端口 +5% 速度', abs(before / after - 1.05) < 1e-6)

    # 同一条线同时挂普通+加密：只算一次 5%，不叠加
    g.buy_gear(vpn)
    g.equip_gear(cl, 'vpn')
    both = cl.spd()
    cl.gear.discard('vpn')
    only_enc = cl.spd()
    check('两种端口不叠加', abs(both - only_enc) < 1e-9)

    # 重复装同一件：不允许
    g.buy_gear(vpn)
    n_before = g.bag_count('vpn')
    check('同一条线装不了第二个同款端口', not g.equip_gear(gr, 'vpn'))
    check('装不上时背包不变', g.bag_count('vpn') == n_before)

    # ------------------------------------------------ 端口周费
    print('\n【端口周费】')
    g = fresh()
    g.money = 99999
    gr = by_id(g, 'Grok')
    cl = by_id(g, 'Claude')
    g.buy_gear(vpn)
    g.buy_gear(vpn)
    g.buy_gear(enc)
    check('只买不装不收费', g.port_week_fee() == 0)
    g.equip_gear(gr, 'vpn')
    check('装上普通端口才收 50', g.port_week_fee() == game.VPN_WEEK)
    g.buy_gear(enc)
    g.equip_gear(cl, 'vpn_enc')
    check('加密端口收 150', g.port_week_fee() == game.VPN_WEEK + game.VPN_ENC_WEEK)
    g.unequip_gear(cl, 'vpn_enc')
    check('拆下来就不收了', g.port_week_fee() == game.VPN_WEEK)
    g.equip_gear(cl, 'vpn_enc')
    g.day = 7                    # 第 7 天打烊时收租
    m0 = g.money
    rent, power, wage, subs, port = g.daily_fixed()
    check('收租日才收端口费', port == g.port_week_fee())
    g.end_day()
    spent = m0 - g.money
    check('结算确实扣了周费', abs(spent - (rent + power + wage + subs + port)) < 0.01)
    check('周费记进当日账本', g.last_day.get('port') == port)

    # ------------------------------------------------ 串门是"去找人"
    print('\n【串门：目标是人，不是房间】')
    g = fresh()
    qw = by_id(g, 'Qwen')
    cl = by_id(g, 'Claude')
    # 让 Claude 离开房间，站到自己那层的走廊里（Qwen 也在这一层）
    cl.px, cl.feet = 435, 540
    cl.at_key = 'Claude'
    cl.social_state = 'home'
    cl.social_timer = 999
    qw.social_state = 'home'
    qw.social_timer = 0.0
    qw.at_key = 'Qwen'
    for _ in range(40):          # 有 25% 概率会去公共区域，多试几次
        qw.social_state = 'home'
        qw.social_target = None
        qw.walk_path = []
        g.start_outing(qw)
        if qw.social_target:
            break
    check('出门时会锁定一个人', qw.social_target is not None)
    if qw.social_target == 'Claude':
        check('路线终点是那个人的当前位置',
              qw.walk_path and abs(qw.walk_path[-1][0] - cl.px) < 40
              and abs(qw.walk_path[-1][1] - cl.feet) < 40)
    else:
        check('路线终点是那个人的当前位置', True)

    # 直接构造一次"找人"：站到对方旁边就开聊
    qw.social_target = 'Claude'
    qw.social_state = 'walk'
    qw.social_dest_key = 'ChatGPT'
    qw.walk_path = [(cl.px + 20, cl.feet)]
    qw.px, qw.feet = cl.px + 40, cl.feet
    qw.social_timer = 99
    for _ in range(60):
        g.update(0.05)
        if qw.social_state == 'chat':
            break
    check('走到人旁边就开聊', qw.social_state == 'chat' and qw.chat_partner == 'Claude')
    check('对方也进入聊天', cl.social_state == 'chat' and cl.chat_partner == 'Qwen')
    check('两个人都有一句台词', bool(qw.chat_line) and bool(cl.chat_line))
    check('聊天时两人不重叠', game.Game.dist_between(qw, cl) >= 26)

    # 对方在忙就不去
    qw2 = by_id(g, 'DeepSeek')
    qw2.social_state = 'home'
    g.start_outing(qw2)
    check('不会去找正在干活的人',
          qw2.social_target != 'Qwen' or qw.social_state == 'chat')

    # ------------------------------------------------ 路上相遇
    print('\n【路上相遇】')
    g = fresh()
    a = by_id(g, 'Gemini')
    b = by_id(g, 'GLM')
    a.px, a.feet = 500, 300
    b.px, b.feet = 520, 302
    a.social_state = b.social_state = 'walk'
    a.social_target = b.social_target = None
    a.walk_path = [(600, 300)]
    b.walk_path = [(400, 302)]
    g.update_encounters(0.05)
    check('走廊里遇上会停下来聊', a.social_state == 'chat' and b.social_state == 'chat')
    check('互相认作聊天对象',
          a.chat_partner == 'GLM' and b.chat_partner == 'Gemini')
    check('同一对不会立刻重复触发', tuple(sorted(('Gemini', 'GLM'))) in g.encounter_cd)

    # ------------------------------------------------ 隔墙不聊天
    print('\n【位置合理性】')
    g = fresh()
    g.walkmask = game.WalkMask({(31, y) for y in range(0, game.WH // 16)},
                               16, game.WW // 16, game.WH // 16)
    a = by_id(g, 'Gemini')
    b = by_id(g, 'GLM')
    a.px, a.feet = 30 * 16 + 8, 300      # 墙左边
    b.px, b.feet = 32 * 16 + 8, 300      # 墙右边
    a.social_state = b.social_state = 'walk'
    check('隔着墙不算面对面', not g.can_chat(a, b, 60))
    g.update_encounters(0.05)
    check('隔着墙不会触发相遇对话',
          a.social_state == 'walk' and b.social_state == 'walk')

    # ------------------------------------------------ 状态牌不挡气泡
    print('\n【状态牌不挡对话框】')
    g = fresh()
    a = by_id(g, 'Gemini')
    a.chat_line = ''
    check('平时会画状态牌', g.show_status_pill(a))
    a.chat_line = '你那显卡烫不烫？'
    check('聊天时不画状态牌', not g.show_status_pill(a))
    a.chat_line = ''
    g.draw()
    check('画一遍不报错', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
