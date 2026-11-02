#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v15 新机制自测：限流改成"用得太狠才限"、DeepSeek 摸鱼煮饭、零食（冰箱已移除）。

用法：python3 tools/test_v15.py
"""
import os
import sys
from unittest import mock

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('AIHUB_SETTINGS', '/tmp/aihub_test_settings.json')
os.environ.setdefault('AIHUB_SAVE', '/tmp/aihub_test_save.json')
os.environ.setdefault('AIHUB_WALKMASK', '/tmp/aihub_no_mask.json')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402
import game  # noqa: E402

game.RENT_NOTICE_ON = False
game.INTRO_ON = False      # 自测/模拟里不弹房租窗，免得挡住自动跑

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f'  [通过] {name}')
    else:
        fail += 1
        print(f'  [失败] {name}')


class FakeTask:
    """只给 update_station_state 用的假任务（重量可控）。"""

    def __init__(self, w=120.0):
        self.w = w
        self.typ = 'code'
        self.state = 'service'
        self.fade = 0


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    g = game.Game()
    g.state = 'play'
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')

    # ---------------------------------------------------- 限流：只认"连续满负荷"
    print('\n【限流机制】')
    s = ds
    s.unlocked = s.subscribed = True
    s.busy = FakeTask(120)
    s.strain = 0.0
    s.strain_warned = False
    frames = 0
    while not s.limited and frames < 4000:
        g.update_station_state(s, 0.1)
        frames += 1
    check('连续满负荷约 55~75 秒后被限流',
          55 <= frames * 0.1 <= 75)
    check('限流后进入限流状态', s.limited is True)
    check('限流事件进了右侧事件栏',
          g.event and g.event['kind'] == 'throttle')
    s.slack = 0.0            # 别让"顺手在煮饭"叠进来（叠加的情况在 v33 里测）
    check('限流时速度只剩 20%',
          abs(s.work_factor() - 0.2) < 1e-9)

    # 限流期间压力冻在满格，不再累积也不回落
    st0 = s.strain
    for _ in range(50):
        g.update_station_state(s, 0.1)
    check('限流期间压力冻结', abs(s.strain - st0) < 1e-9)

    # 干完手头这单才解除，解除后才开始回落
    s.busy = None
    g.update_station_state(s, 0.1)
    check('手头的活干完才解除限流', s.limited is False)
    check('解除时速度复原', abs(s.work_factor() - 1.0) < 1e-9)
    strain_after = s.strain
    for _ in range(50):
        g.update_station_state(s, 0.1)
    check('解除后压力开始回落', s.strain < strain_after)

    # 纯粹的"用得太狠"才算：一直空闲绝不会被限流
    s.strain = 0.0
    s.busy = None
    s.limited = False
    for _ in range(2000):
        g.update_station_state(s, 0.1)
    check('空闲 200 秒也不会被限流', s.limited is False)

    # 随机事件不再甩限流
    kinds = set()
    with mock.patch('random.choice', side_effect=lambda seq: seq[0]):
        for _ in range(30):
            g.event = None
            g.roll_event()
            kinds.add(g.event['kind'])
    check('随机事件池里已经没有限流',
          'throttle' not in kinds and kinds <= {'burst', 'rep'})
    g.event = None
    g.burst = 0.0

    # 完成任务会清掉计时器，别留下脏状态
    check('限流压力字段存在于每条线路',
          all(hasattr(x, 'strain') for x in g.stations))

    # ---------------------------------------------------- 摸鱼
    print('\n【DeepSeek 摸鱼煮饭】')
    g2 = game.Game()
    g2.state = 'play'
    ds2 = next(s for s in g2.stations if s.m['id'] == 'DeepSeek')
    ds2.unlocked = ds2.subscribed = True
    ds2.quota = ds2.quota_cap()
    ds2.slack_cd = 0.0
    with mock.patch('random.random', return_value=0.0):
        g2.update_station_state(ds2, 0.1)
    check('空闲时开始煮大白饭', ds2.slack > 0)
    check('摸鱼时长是 1 个游戏小时',
          abs(ds2.slack - game.SLACK_SEC) < 0.3)
    check('摸鱼时不能接单', ds2.ready() is False)

    # 点它能拦下来
    rect = ds2.rect()
    g2.panel = None
    g2.handle_click((rect.centerx, rect.centery))
    check('点角色可以拦下摸鱼', ds2.slack <= 0)
    check('拦下后进入冷却', ds2.slack_cd > 0)
    check('拦下后又能接单', ds2.ready() is True)

    # 没拦住：额度被吃掉
    ds2.quota = 300
    ds2.slack = 0.05
    rep0 = g2.rep
    g2.update_station_state(ds2, 0.1)
    check('没拦住 -> 今日额度被吃掉', ds2.quota == 300 - game.SLACK_COST)
    check('没拦住 -> 声誉 -1', abs(g2.rep - (rep0 - 1)) < 1e-6)

    # 只有 DeepSeek 会摸鱼
    others = [s for s in g2.stations if s.m['id'] != 'DeepSeek']
    for s in others:
        s.unlocked = s.subscribed = True
        s.slack_cd = 0.0
    with mock.patch('random.random', return_value=0.0):
        for _ in range(20):
            for s in others:
                g2.update_station_state(s, 0.1)
    check('其他线路不会摸鱼', all(s.slack <= 0 for s in others))

    # ---------------------------------------------------- 冰箱
    print('\n【冰箱零食】')
    g3 = game.Game()
    g3.state = 'play'
    st = next(s for s in g3.stations if s.m['id'] == 'Doubao')
    st.unlocked = st.subscribed = True
    before = st.spd()
    n0 = g3.snacks
    g3.feed_snacks()
    check('发零食消耗 1 份', g3.snacks == n0 - 1)
    check('线路拿到零食 buff', st.snack > 0)
    check('吃了零食速度更快', st.spd() > before)

    g3.snacks = 0
    g3.feed_snacks()
    check('冰箱空了发不出来', g3.snacks == 0)

    g3.money = 1000.0
    g3.buy_snacks()
    check('补货扣钱加库存',
          g3.snacks == game.SNACK_BUY_N and abs(g3.money - (1000 - game.SNACK_BUY)) < 1e-6)

    snacks_before = g3.snacks
    g3.end_day()
    check('结算不再补满冰箱（零食不每天刷新）', g3.snacks == snacks_before)

    # 冰箱已经移除：点原来的位置不会再开面板
    g3.state = 'play'
    g3.panel = None
    r = game.FRIDGE_RECT
    g3.handle_click((r.centerx, r.centery))
    check('冰箱移除后点原地不再开面板', g3.panel is None)
    # 面板逻辑本身还在（零食改由补给船送），直接开面板测按钮
    g3.panel = ('fridge', None)

    # 面板按钮
    fb = g3.fridge_feed_btn()
    g3.snacks = 2
    g3.click_panel(fb.centerx, fb.centery)
    check('面板上点"发零食"生效', g3.snacks == 1)

    # 存档带上零食
    print('\n【存档】')
    g3.save()
    g4 = game.Game()
    g4.load()
    check('存档里的零食份数能读回来', g4.snacks == g3.snacks)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
