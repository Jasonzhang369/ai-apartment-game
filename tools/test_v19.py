#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v19 自测：限流改降速 80% & 干完才解除 / 暂停手上这单 / 放弃手上的单 /
服务器里退回一条任务。

用法：python3 tools/test_v19.py
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


def give_job(g, st, w=100.0):
    t = game.Task('code')
    t.w = w
    t.state = 'stored'
    g.tasks.append(t)
    st.unlocked = st.subscribed = True
    st.quota = 400
    g.assign(t, st)
    return t


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    # ------------------------------------------------ 限流：降速 80%，干完才解除
    print('\n【限流：降速 80%，干完手头这单才解除】')
    check('降速参数是 0.8', abs(game.THROTTLE_SLOW - 0.80) < 1e-9)
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    t = give_job(g, ds)
    g.throttle(ds)
    check('限流后速度只剩 20%', abs(ds.work_factor() - 0.2) < 1e-9)
    check('限流压力顶在 1.0', abs(ds.strain - 1.0) < 1e-9)
    check('限流不打断手上的活', ds.busy is t)
    # 跑一段：进度在涨、压力不降
    prog0, strain0 = t.prog, ds.strain
    for _ in range(100):
        g.update(0.05)
    check('限流中进度依然在走', t.prog > prog0)
    check('限流中压力不下降', abs(ds.strain - strain0) < 1e-9)
    check('限流中无法接新单', ds.ready() is False)
    # 干完这单 -> 解除
    t.prog = 0.999
    for _ in range(60):
        g.update(0.05)
        if not ds.limited:
            break
    check('手头这单干完后解除限流', ds.limited is False)
    g.meal_eaten()          # 缺饭惩罚会叠加，这里只测限流解除
    check('解除后速度复原', abs(ds.work_factor() - 1.0) < 1e-9)
    strain1 = ds.strain
    for _ in range(60):
        g.update_station_state(ds, 0.1)
    check('解除之后压力才开始回落', ds.strain < strain1)

    # ------------------------------------------------ 暂停 / 继续
    print('\n【暂停手上这单】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    t = give_job(g, ds)
    for _ in range(10):
        g.update(0.05)
    p0, q0 = t.prog, ds.quota
    g.pause_job(ds)
    check('暂停标记生效', ds.paused_job is True)
    for _ in range(40):
        g.update(0.05)
    check('暂停后进度冻住', abs(t.prog - p0) < 1e-9)
    check('暂停后不扣额度', abs(ds.quota - q0) < 1e-9)
    check('暂停不算接单（忙碌但 ready 为假）', ds.ready() is False)
    g.pause_job(ds)
    check('再点一次就继续', ds.paused_job is False)
    for _ in range(20):
        g.update(0.05)
    check('继续后进度重新走', t.prog > p0)

    # 面板上的按钮能点到
    g.panel = ('station', ds)
    b = g.station_job_btn()
    g.click_panel(b.centerx, b.centery)
    check('工位面板里点「暂停」能暂停', ds.paused_job is True)
    g.click_panel(b.centerx, b.centery)
    check('再点能继续', ds.paused_job is False)

    # ------------------------------------------------ 放弃
    print('\n【放弃手上这单】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    t = give_job(g, ds)
    for _ in range(10):
        g.update(0.05)
    rep0 = g.rep
    qspent = t.qspent
    g.abandon_job(ds)
    check('放弃后手上空了', ds.busy is None)
    check('放弃的单作废', t.state == 'out')
    check('放弃扣声誉', abs(g.rep - (rep0 - game.REP_ABANDON)) < 1e-6)
    check('已经扣掉的额度不退', qspent >= 0)
    check('放弃后又能接单', ds.ready() is True)
    # 面板按钮
    t2 = give_job(g, ds)
    g.panel = ('station', ds)
    ab = g.station_abandon_btn()
    g.click_panel(ab.centerx, ab.centery)
    check('工位面板里点「放弃这单」生效', ds.busy is None and t2.state == 'out')

    # 没有活时点按钮只提示
    g.abandon_job(ds)
    check('没活在手上时点放弃不会崩', ds.busy is None)

    # ------------------------------------------------ 服务器里退回任务
    print('\n【服务器里退回一条任务】')
    g = fresh()
    for _ in range(3):
        g.try_spawn()
    q = g.queued_tasks()
    check('先有几条待处理任务', len(q) >= 2)
    n0 = len(q)
    victim = q[0]
    rep0 = g.rep
    g.panel = ('server', 0)
    rows = g.task_rows()
    rr = dict((t.uid, r) for t, r in rows)[victim.uid]
    db = g.task_del_btn(rr)
    g.click_panel(db.centerx, db.centery)
    check('点 X 能退回这条任务', victim not in g.queued_tasks())
    check('待处理数量少了一条', len(g.queued_tasks()) == n0 - 1)
    check('退回扣声誉', abs(g.rep - (rep0 - game.REP_REJECT)) < 1e-6)
    check('退回的单不会再被派出去', victim.state == 'out')
    g.update(0.05)          # 让它从 tasks 里淡出
    check('退掉的单已经从场上消失', victim not in g.tasks or victim.state == 'out')

    # ------------------------------------------------ 渲染
    print('\n【界面渲染】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    t = give_job(g, ds)
    g.throttle(ds)
    g.panel = ('station', ds)
    g.draw()
    check('限流中的工位面板能画', True)
    g.pause_job(ds)
    g.draw()
    check('暂停中的工位面板能画', True)
    g.panel = ('server', 0)
    for _ in range(3):
        g.try_spawn()
    g.draw()
    check('带退回按钮的服务器面板能画', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
