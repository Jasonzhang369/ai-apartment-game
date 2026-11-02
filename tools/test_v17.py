#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v17 自测：游戏时间显示 / DeepSeek 额度折扣 / 暂停接单 / 早餐开张提醒 /
Gemini 速度+60%&质量抖动 / 升温更快 / 限流只减速 / 飘字整块渲染。

用法：python3 tools/test_v17.py
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
    span = (h - game.HOUR_START) % 24
    g.t = game.DAY_LEN * span / game.DAY_HOURS
    game.CUR_NIGHT = g.is_night()


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    # ------------------------------------------------ 游戏时间显示
    print('\n【时长按游戏时间显示】')
    check('60 秒 = 4 小时 48 分', game.fmt_sec_game(60) == '4小时48分')
    check('30 秒会显示成小时', '小时' in game.fmt_sec_game(30))
    g = fresh()
    g.try_spawn()
    t = g.queued_tasks()[0]
    st = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    st.unlocked = st.subscribed = True
    st.quota = 400
    g.assign(t, st)
    g.panel = ('server', 0)
    g.draw()                      # 卡片上写的就是 fmt_sec_game(dur) / 忙碌 还剩 xx
    check('派单面板渲染不报错（时长已换算）', True)
    g.panel = None

    # ------------------------------------------------ DeepSeek 额度折扣
    print('\n【DeepSeek 额度 -20%】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    base = ds.quota_cost(100) * g.quota_mult(ds)
    need = g.quota_need(ds, 100)
    check('额度消耗是标称的 80%', abs(need / base - 0.80) < 0.02)
    other = next(s for s in g.stations if s.m['id'] == 'Qwen')
    check('其他线路没有折扣',
          abs(g.quota_need(other, 100) / (other.quota_cost(100) * g.quota_mult(other)) - 1) < 0.02)

    # ------------------------------------------------ 暂停接单
    print('\n【暂停接单】')
    g = fresh()
    check('开局是接单状态', g.intake is True)
    g.tasks.clear()
    g.intake = False
    for _ in range(120):
        g.update(0.05)
    check('停接后不再进新单', len(g.tasks) == 0)
    g.intake = True
    g.spawn_timer = 0.0
    g.update(0.05)
    check('恢复后马上能来单', len(g.tasks) > 0)

    keys = [k for k, r in g.pane_buttons()]
    check('右栏有暂停接单按钮', 'intake' in keys)
    bi = dict(g.pane_buttons())['intake']
    g.hud_click = None
    state0 = g.intake
    g.handle_click(bi.center)          # 点右栏按钮
    check('点按钮能切换接单状态', g.intake != state0)
    g.toggle_intake()
    check('toggle 能切回来', g.intake == state0)

    # 网关面板里也能切
    g.panel = ('gateway', None)
    bb = g.gateway_intake_btn()
    g.click_panel(bb.centerx, bb.centery)
    check('网关面板里能暂停接单', g.intake != state0)
    g.panel = None
    g.intake = True

    # ------------------------------------------------ 早餐开张提醒
    print('\n【早餐铺开张提醒】')
    g = fresh()
    g.breakfast_day = -1
    g.bf_notice_day = -1
    at_hour(g, 6.8)
    g.update(0.05)
    check('没到点不提醒', g.bf_notice_day != g.day)
    at_hour(g, 7.1)
    g.update(0.05)
    check('开张那一刻会提醒', g.bf_notice_day == g.day)
    check('提醒文案提到了早餐', g.toast and '早餐' in g.toast[0])
    # 同一天不会重复刷
    g.toast = None
    at_hour(g, 7.4)
    g.update(0.05)
    check('同一天只提醒一次', g.toast is None)

    # ------------------------------------------------ Gemini
    print('\n【Gemini：更快但质量飘】')
    gm = next(m for m in game.MODELS if m['id'] == 'Gemini')
    check('速度是原来的 1.6 倍', abs(gm['spd'] / 3.1 - 1.6) < 1e-6)
    check('带了质量抖动开关', bool(gm.get('qjitter')))
    g = fresh()
    st = next(s for s in g.stations if s.m['id'] == 'Gemini')
    st.unlocked = st.subscribed = True
    base_q = st.quality('chat')
    t = game.Task('chat')
    qs = [st.quality('chat', t) for _ in range(1)]
    ratio = qs[0] / base_q
    check('单看这一单质量降了 5%~15%', 0.849 <= ratio <= 0.951)
    t.qj = 0.85
    check('运气差时降 15%', abs(st.quality('chat', t) / base_q - 0.85) < 0.01)
    t.qj = 0.95
    check('运气好时降 5%', abs(st.quality('chat', t) / base_q - 0.95) < 0.01)
    check('同一单反复算不会跳（不闪烁）',
          abs(st.quality('chat', t) - st.quality('chat', t)) < 1e-9)

    # ------------------------------------------------ 升温 & 限流
    print('\n【升温更快 / 限流只减速】')
    check('基础升温提到 0.24', game.TEMP_RISE >= 0.24)
    check('负载升温提到 0.60', game.TEMP_LOAD >= 0.60)
    check('限流是降速 80%（只剩 20% 速度）', abs(game.THROTTLE_SLOW - 0.8) < 1e-9)
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
    g.throttle(ds)
    rep0, prog0 = g.rep, t.prog
    for _ in range(60):
        g.update(0.05)
    check('被限流时活还在走（只是慢）', t.prog > prog0)
    check('被限流不掉声誉', abs(g.rep - rep0) < 1e-6)
    check('被限流时温度在降', ds.temp <= game.TEMP_LIMIT)
    g.meal_eaten()          # 只测限流这段，别被缺饭惩罚叠加
    check('限流时 work_factor 是 0.2', abs(ds.work_factor() - 0.2) < 1e-9)
    # 干完手头这单 -> 限流自动解除
    t.prog = 0.999
    for _ in range(40):
        g.update(0.05)
        if not ds.limited:
            break
    check('手头这单干完限流就解除', ds.limited is False)
    check('解除后速度复原', abs(ds.work_factor() - 1.0) < 1e-9)

    # ------------------------------------------------ 走路动画
    print('\n【走路动画已关闭】')
    check('WALK_ON 是关的', game.WALK_ON is False)
    g = fresh()
    for _ in range(200):
        g.update(0.05)
    check('没有走路帧动画（仍是静止立绘）',
          all(not s.walking for s in g.stations))

    # ------------------------------------------------ 飘字
    print('\n【飘字用整块底渲染】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.slack = game.SLACK_SEC
    g.stop_slack(ds)
    check('拦摸鱼会弹飘字', any('抓到' in x[2] for x in g.texts))
    check('有 float_plate 画法', hasattr(g, 'float_plate'))
    g.draw()
    check('飘字渲染不报错', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
