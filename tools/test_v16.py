#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v16 新规则自测：早餐时段 / 电闸容量与豆包脱网 / 豆包削弱 / GLM 昼夜 /
24:00 只刷额度 / 额度边干边扣会断活 / 限流与宕机打断 + 掉声誉。

用法：python3 tools/test_v16.py
"""
import os
import sys

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


def fresh():
    g = game.Game()
    g.state = 'play'
    return g


def at_hour(g, h):
    """把时间轴拨到某个整点（08:00 出发的 24 小时周期）。"""
    span = (h - game.HOUR_START) % 24
    g.t = game.DAY_LEN * span / game.DAY_HOURS
    game.CUR_NIGHT = g.is_night()


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    # ------------------------------------------------ 早餐
    print('\n【早餐铺时段】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')

    at_hour(g, 5)
    check('05:30 没营业', g.breakfast_open() is False)
    money0 = g.money
    g.buy_breakfast()
    check('没营业时买不到、也不扣钱', g.money == money0 and ds.breakfast <= 0)

    at_hour(g, 7)
    check('07:00 营业中', g.breakfast_open() is True)
    before = ds.spd()
    g.buy_breakfast()
    check('08:00 能买到早餐', ds.breakfast > 0)
    check('早餐持续 8 个游戏小时',
          abs(ds.breakfast - game.BREAKFAST_SEC) < 0.3 and game.BREAKFAST_MIN == 480)
    check('吃了早餐速度更快', ds.spd() > before)

    at_hour(g, 12)
    check('12:00 收摊', g.breakfast_open() is False)
    ds.breakfast = 0.0
    g.breakfast_day = -1
    m1 = g.money
    g.buy_breakfast()
    check('12:00 买不了（也没扣钱）', g.money == m1 and ds.breakfast == 0)

    # ------------------------------------------------ 电闸
    print('\n【电闸：初始 2 路，豆包不接入】')
    g = fresh()
    check('Lv1 电闸只有 2 路', g.breaker_cap() == 2)
    g.breaker_lv = 5
    check('Lv5 是 6 路', g.breaker_cap() == 6)
    g = fresh()
    db = next(s for s in g.stations if s.m['id'] == 'Doubao')
    check('公寓的豆包不在电路上', db.on_grid() is False)
    check('其他线路在电路上', all(s.on_grid() for s in g.stations if s is not db))

    # 让豆包和另外两条线一起干活：电闸只统计另外两条
    subs = [s for s in g.stations if s is not db][:2]
    for s in subs:
        s.unlocked = s.subscribed = True
        s.quota = 999
    g2 = g
    g2.try_spawn()
    q = g2.queued_tasks()
    # 直接伪造 busy，绕开派单细节
    for s in subs + [db]:
        s.busy = game.Task('code')
        s.busy.state = 'service'
        s.dur = 60.0
        s.prog = 0.0
    for _ in range(10):
        g2.update(0.05)
    busy_grid = sum(1 for s in g2.stations if s.busy and s.on_grid())
    check('豆包干活不占电闸容量', busy_grid == 2)
    check('豆包自己那单还在跑', db.busy is not None)

    # 跳闸只废电路上的单
    g2.trip()
    check('跳闸废掉电路上的单', all(s.busy is None for s in subs))
    check('跳闸不影响豆包的单', db.busy is not None)

    # ------------------------------------------------ 豆包削弱
    print('\n【豆包削弱】')
    m = next(x for x in game.MODELS if x['id'] == 'Doubao')
    check('豆包（Seed）速度已按官网调强', m['spd'] > 2.0)
    check('豆包（Seed）质量已按官网调强', m['q'] > 0.45)

    # ------------------------------------------------ GLM 昼夜
    print('\n【GLM 作息】')
    g = fresh()
    glm = next(s for s in g.stations if s.m['id'] == 'GLM')
    glm.unlocked = glm.subscribed = True
    base = glm.m['spd'] * game.SPEED_K   # 基准速度（含全局加速）
    at_hour(g, 12)                       # 白天
    day_spd, day_cost = glm.spd(), g.quota_need(glm, 100)
    check('白天速度是平常的 60%', abs(day_spd / base - 0.60) < 0.02)
    at_hour(g, 2)                        # 夜里 02:00
    night_spd, night_cost = glm.spd(), g.quota_need(glm, 100)
    check('夜里速度是平常的 130%', abs(night_spd / base - 1.30) < 0.02)
    check('白天额度是基准的 1.2 倍',
          abs(day_cost / (100 * game.QUOTA_REF / base) / game.GLM_DAY_QUOTA - 1) < 0.02)
    check('夜里额度是基准的 0.3 倍',
          abs(night_cost / (100 * game.QUOTA_REF / base) - 0.30) < 0.02)
    # 普通线路夜间只有半价（用没有折扣的 Qwen 验）
    qw = next(s for s in g.stations if s.m['id'] == 'Qwen')
    check('普通线路夜里额度半价',
          abs(g.quota_need(qw, 100) / (100 * game.QUOTA_REF / (qw.m['spd'] * game.SPEED_K))
              - 0.5) < 0.02)

    # ------------------------------------------------ 24:00 只刷额度
    print('\n【24:00 只刷新额度】')
    g = fresh()
    g.day = 3
    st = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    st.temp = 71.0
    st.strain = 0.85
    st.breakfast = 40.0
    st.snack = 25.0
    st.quota = 7.0
    g.end_day()
    check('额度确实刷新了', abs(st.quota - st.quota_cap()) < 1e-6)
    check('CPU 温度不重置', abs(st.temp - 71.0) < 1e-6)
    check('限流进度不重置', abs(st.strain - 0.85) < 1e-6)
    check('早餐计时不重置', abs(st.breakfast - 40.0) < 1e-6)
    check('零食计时不重置', abs(st.snack - 25.0) < 1e-6)

    # ------------------------------------------------ 额度边干边扣 + 断活
    print('\n【额度边干边扣】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.temp = game.TEMP_IDLE
    at_hour(g, 12)
    ds.quota = 400
    t = game.Task('code')
    t.w = 100.0
    t.state = 'stored'
    g.tasks.append(t)
    need = g.quota_need(ds, t.w)
    g.assign(t, ds)
    check('派单时不再一次扣光', ds.quota == 400)
    for _ in range(20):
        g.update(0.05)
    check('干活过程中额度在减少', ds.quota < 400)

    # 把额度调得很低，让它半途断掉（顺便把进度压回开头，避免刚好跑完）
    ds.quota = 12.0
    ds.prog = 0.02
    rep0 = g.rep
    ds.temp = game.TEMP_IDLE
    g.event = dict(kind='rep', name='测试屏蔽随机事件', left=1e9, desc='')  # 别让口碑 +4 干扰
    for _ in range(400):
        g.update(0.05)
        if ds.busy is None:
            break
    g.event = None
    check('额度见底后活被中断', ds.busy is None)
    check('被中断的单作废', t.state == 'out')
    check('额度归零', ds.quota == 0)
    check('声誉下降', g.rep < rep0)
    check('断了以后不能再接单', ds.ready() is False)

    # ------------------------------------------------ 限流只是减速，宕机会打断
    print('\n【限流（减速）/ 宕机（打断）】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.quota = 400
    at_hour(g, 12)
    t = game.Task('code')
    t.w = 100.0
    t.state = 'stored'
    g.tasks.append(t)
    g.assign(t, ds)
    rep0 = g.rep
    g.throttle(ds)
    check('限流不再打断手上的单', ds.busy is t and t.state == 'service')
    check('限流不扣声誉', abs(g.rep - rep0) < 1e-6)
    g.meal_eaten()                  # 排除缺饭减速，只测限流
    g.meal_done.update((7, 12, 18))  # 别在测试中途又错过一顿
    prog0, q0 = t.prog, ds.quota
    for _ in range(40):
        g.update(0.05)
    check('限流期间还在往前走（只是慢）', t.prog > prog0)
    check('限流期间进度只有平常的 20%',
          abs((t.prog - prog0) / (2.0 / max(0.5, t.dur)) - 0.2) < 0.06)
    check('限流期间额度照扣（扣得慢）', ds.quota < q0)

    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.quota = 400
    at_hour(g, 12)
    t = game.Task('code')
    t.w = 100.0
    t.state = 'stored'
    g.tasks.append(t)
    g.assign(t, ds)
    rep0 = g.rep
    g.overheat(ds)
    check('宕机把正在跑的单打断', ds.busy is None and t.state == 'out')
    check('宕机降声誉', abs(g.rep - (rep0 - game.REP_CRASH)) < 1e-6)

    # ------------------------------------------------ 摸鱼更频繁
    print('\n【摸鱼频率】')
    check('摸鱼冷却变短了', game.SLACK_GAP <= 60)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
