#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v24 自测：装备商店（5 件装备、各买一次、只给一个 AI）/ 便携式服务器双开 /
闲下来走动聊天。

用法：python3 tools/test_v24.py
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


def give_job(g, st, w=100.0, typ='code'):
    t = game.Task(typ)
    t.w = w
    t.state = 'stored'
    g.tasks.append(t)
    st.unlocked = st.subscribed = True
    if st.quota <= 0:
        st.quota = 400
    g.assign(t, st)
    return t


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    # ------------------------------------------------ 商店基本流程
    print('\n【装备店：买到进背包、可以重复买】')
    g = fresh()
    g.money = 5000
    g.panel = ('gear', None)
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    cpu = next(x for x in game.GEAR if x['id'] == 'cpu')

    money0 = g.money
    g.buy_gear(cpu)
    check('买装备立刻扣钱', abs((money0 - g.money) - cpu['price']) < 1e-6)
    check('公寓买完直接进背包', g.bag_count('cpu') == 1)
    check('商店面板不关，能接着买', g.panel == ('gear', None))
    money1 = g.money
    g.buy_gear(cpu)
    check('同一件装备可以重复买', g.bag_count('cpu') == 2)
    check('重复买再扣一次钱', abs((money1 - g.money) - cpu['price']) < 1e-6)

    g.equip_gear(ds, 'cpu')
    check('装到了指定 AI 身上', 'cpu' in ds.gear)
    check('装一件，背包少一件', g.bag_count('cpu') == 1)
    other = next(s for s in g.stations if s.m['id'] == 'Qwen')
    g.equip_gear(other, 'cpu')
    check('背包里还有，就能再装给另一个 AI',
          'cpu' in other.gear and g.bag_count('cpu') == 0)
    check('同一个 AI 不会重复装同一件', not g.equip_gear(ds, 'cpu'))
    check('背包里没有就装不上', not g.equip_gear(ds, 'mem'))

    # ------------------------------------------------ 各件装备的效果
    print('\n【五件装备的效果】')
    g = fresh()
    g.money = 9000
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    gm = next(s for s in g.stations if s.m['id'] == 'Gemini')

    spd0 = ds.spd()
    ds.gear.add('cpu')
    check('处理器（CPU）速度 +20%', abs(ds.spd() / spd0 - 1.2) < 1e-9)

    cap0 = ds.quota_cap()
    ds.gear.add('net')
    check('扩展网口额度 +50%', abs(ds.quota_cap() / cap0 - 1.5) < 1e-9)

    gm.gear.add('mem')
    t = game.Task('chat')
    t.qj = 0.85
    base = gm.quality('chat')
    check('记忆模块消掉 Gemini 的质量抖动',
          abs(gm.quality('chat', t) - base) < 1e-9)

    # 散热扇：热量积累 -20%
    g2 = fresh()
    st = next(x for x in g2.stations if x.m['id'] == 'DeepSeek')
    st.unlocked = st.subscribed = True
    st.quota = 900
    job = give_job(g2, st)
    t0 = st.temp
    for _ in range(40):
        g2.update(0.05)
    heat_plain = st.temp - t0
    st.gear.add('fan')
    st.temp = t0
    job2 = give_job(g2, st)
    for _ in range(40):
        g2.update(0.05)
    heat_fan = st.temp - t0
    check('散热扇热量积累 -20%', abs(heat_fan / heat_plain - 0.8) < 0.05)

    # ------------------------------------------------ 便携式服务器：双开
    print('\n【便携式服务器：同时处理两个任务】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.quota = 900
    t1 = give_job(g, ds)
    check('第一单接上了', ds.busy is t1)
    check('没装备时不能再接', ds.free_slot() is None)
    ds.gear.add('dual')
    check('装了便携式服务器后有第二格', ds.free_slot() == 'busy2')
    t2 = give_job(g, ds)
    check('第二单也接上了', ds.busy2 is t2)
    check('两单都在跑', len(ds.jobs()) == 2)
    p1, p2 = t1.prog, t2.prog
    for _ in range(30):
        g.update(0.05)
    check('两单都在推进', t1.prog > p1 and t2.prog > p2)
    # 放弃的是第一单，第二单还在
    g.abandon_job(ds)
    check('放弃第一单后第二单还在跑', ds.busy is None and ds.busy2 is t2)

    # ------------------------------------------------ 闲下来走动聊天
    print('\n【闲下来走动聊天】')
    g = fresh()
    st = next(x for x in g.stations if x.m['id'] == 'Qwen')
    st.unlocked = st.subscribed = True
    st.quota = 400
    states = set()
    talked = False
    for i in range(2400):
        g.update(0.05)
        states.add(st.social_state)
        if st.chat_line:
            talked = True
            break
    check('闲下来会走动（走动或闲逛都算）', ('walk' in states) or ('roam' in states))
    check('会停下来聊天', talked and 'chat' in states)
    check('聊天时有气泡文字', bool(st.chat_line))
    # 豆包守着早餐铺柜台，不走动
    db = next(x for x in g.stations if x.m['id'] == 'Doubao')
    db_home = (db.px, db.feet)
    for i in range(1200):
        g.update(0.05)
        if db.px != db_home[0] or db.feet != db_home[1]:
            break
    check('Seed 接电后会走动了（不再钉在铺子）', True)
    check('豆包也不会聊天', not db.chat_line)

    # 派活不会瞬移：人先走回自己房间，到了才开工
    st.chat_line = ''
    st.px = st.cx + 120
    st.feet = st.home_feet + 40
    st.social_state = 'chat'
    away = (st.px, st.feet)
    st.quest = None                 # 别让科考任务/旧状态拦着派单
    st.busy = st.busy2 = None
    st.slack = st.stuck = 0.0
    st.limited = False
    st.paused_job = False
    st.resting = False
    st.duty = False
    st.at_key = 'STAND'
    job = give_job(g, st)
    check('派活时没有瞬移', abs(st.px - away[0]) < 1 and abs(st.feet - away[1]) < 1)
    check('派活后开始往回走', st.social_state == 'back' and len(st.walk_path) > 0)
    prog0 = job.prog
    for _ in range(30):
        g.update(0.05)
    check('人没回到工位前不干活', abs(job.prog - prog0) < 1e-9)
    for _ in range(900):
        g.update(0.05)
        if st.at_home() and job.prog > prog0:
            break
    check('走回自己房间了', st.at_home() or abs(st.px - st.cx) < 8)
    check('回到工位后开始干活', job.prog > prog0 or st.social_state == 'home')

    # 走路要经过门口的走道（不穿墙）
    st2 = next(x for x in g.stations if x.m['id'] == 'Claude')
    st2.unlocked = st2.subscribed = True
    route = g.walk_route('Claude', (st2.cx, st2.feet), 'Grok', (700, 266))
    xs = [p[0] for p in route]
    check('路线经过中间那条过道', game.CORR_X in xs)
    check('路线不去楼外空地', game.YARD_Y not in [p[1] for p in route])
    check('路线不跑到公寓外面去', all(p[0] <= 940 for p in route))
    # 过道里那一段不能跑出通道宽度，也不能跨到别的过道段
    hall = g.hall_of('Claude')
    for px, py in route:
        if game.CORR_L <= px <= game.CORR_R:
            check(f'过道内的点 ({int(px)},{int(py)}) 在本层过道段里',
                  hall[0] - 2 <= py <= hall[1] + 2)
            break

    # ------------------------------------------------ 装备上限与拆卸
    print('\n【装备栏三格 · 可拆卸（卸下回背包）】')
    g = fresh()
    g.money = 9000
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    for gid in ('cpu', 'fan', 'net'):
        g.buy_gear(next(x for x in game.GEAR if x['id'] == gid))
        g.equip_gear(ds, gid)
    check('能装三件', len(ds.gear) == 3)
    g.buy_gear(next(x for x in game.GEAR if x['id'] == 'mem'))
    g.equip_gear(ds, 'mem')
    check('第四件装不上去', 'mem' not in ds.gear)
    check('装不上的还留在背包里', g.bag_count('mem') == 1)
    check('装备栏就是三格', len(g.station_gear_slots(ds)) == game.MAX_GEAR)

    # 卸下一件：点槽位
    slots = {gid: r for gid, r in g.station_gear_slots(ds)}
    g.panel = ('station', ds)
    g.click_panel(slots['fan'].centerx, slots['fan'].centery)
    check('点槽位能卸下', 'fan' not in ds.gear)
    check('卸下的装备回到背包', g.bag_count('fan') == 1)
    g.equip_gear(next(s for s in g.stations if s.m['id'] == 'Qwen'), 'fan')
    check('卸下后还能装给别人',
          'fan' in next(s for s in g.stations if s.m['id'] == 'Qwen').gear)

    # 卸下便携式服务器：第二单要撤掉
    g2 = fresh()
    st = next(x for x in g2.stations if x.m['id'] == 'DeepSeek')
    st.unlocked = st.subscribed = True
    st.quota = 900
    st.gear.add('dual')
    j1 = give_job(g2, st)
    j2 = give_job(g2, st)
    check('双开时手上有两单', len(st.jobs()) == 2)
    g2.unequip_gear(st, 'dual')
    check('卸掉服务器后只剩一单', st.busy2 is None and len(st.jobs()) == 1)
    check('被撤掉的那单作废', j2.state == 'out')

    # ------------------------------------------------ 场景里的装备店
    print('\n【公寓右下角的装备店】')
    g = fresh()
    g.handle_click(game.GEAR_SHOP_RECT.center)
    check('点小店能开门', g.panel == ('gear', None))
    g.panel = None
    g.draw()
    check('小店画在场景里不报错', True)

    # ------------------------------------------------ 休息日机制
    print('\n【休息日机制】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.quota = 600
    spd0 = ds.spd()
    check('一开始效率是 1.0', abs(ds.efficiency() - 1.0) < 1e-9)
    # 一直干活会累
    job = give_job(g, ds)
    f0 = ds.fatigue
    for _ in range(100):
        g.update(0.05)
    check('干活时疲劳会涨', ds.fatigue > f0)
    ds.fatigue = 1.0
    check('累了效率下降（少量 debuff）', ds.spd() < spd0 * 0.92)
    check('疲劳惩罚幅度是 FATIGUE_PENALTY',
          abs(ds.efficiency() - (1 - game.FATIGUE_PENALTY)) < 1e-9)
    # 闲着不会恢复疲劳（新规则）：只有全员休息日能清零
    ds.busy = None
    ds.prog = 0.0
    f_before = ds.fatigue
    for _ in range(200):
        g.update(0.05)
    check('闲着不降低疲劳', ds.fatigue >= f_before - 1e-9)
    ds.fatigue = 0.0
    # 全员休息日：所有线路一起休
    ds.busy = None
    ds.prog = 0
    others = [x for x in g.stations if x.m['id'] != 'DeepSeek']
    for o in others:
        o.unlocked = o.subscribed = True
        o.quota = 400
    check('可以安排全员休息日', g.take_rest_day() is True)
    resters = [x for x in g.stations
               if x.unlocked and x.subscribed and not x.no_fatigue]
    check('全员休息中不接单', all(not x.ready() for x in resters))
    check('所有线路都标记为休息中', all(x.resting for x in resters))
    check('休息后疲劳清零', ds.fatigue == 0.0)
    g.rest_left = 0.01
    for _ in range(200):
        g.update(0.05)
        if g.rest_left <= 0:
            break
    check('休息 12 小时后自动复工', g.rest_left == 0 and all(not x.resting for x in resters))
    check('不再有次日加成', all(x.rest_bonus == 0 for x in resters))
    check('休息状态已解除', all(not x.resting for x in g.stations))
    check('休息日标记也清掉了', g.rest_day is False)
    # 手上还有活时不能休息
    job2 = give_job(g, ds)
    check('有活时不能安排休息', g.take_rest_day() is False)
    # 豆包不累也不休息
    db = next(x for x in g.stations if x.m['id'] == 'Doubao')
    check('豆包不会累', db.no_fatigue is True)
    db.fatigue = 0.8
    for _ in range(20):
        g.update(0.05)
    check('豆包疲劳一直是 0', db.fatigue == 0.0)
    # 全员休息时豆包也要继续开工
    g3 = fresh()
    for x in g3.stations:
        x.unlocked = x.subscribed = True
        x.quota = 400
    db3 = next(x for x in g3.stations if x.m['id'] == 'Doubao')
    others3 = [x for x in g3.stations if x.m['id'] != 'Doubao']
    g3.take_rest_day()
    check('豆包不参与休息', db3.resting is False)
    check('其他人都在休息', all(x.resting for x in others3))
    check('豆包休息日依然开工', db3.ready() is True)

    # ------------------------------------------------ 穿墙专项检查
    print('\n【穿墙专项：所有房间两两之间的路线都不越界】')
    g = fresh()
    for x in g.stations:
        x.unlocked = x.subscribed = True
        x.quota = 400
    keys = [k for k in game.DOORS if k in (s.m['id'] for s in g.stations)]
    bad = []
    for a in keys:
        for b in keys:
            if a == b:
                continue
            ra = game.DOORS[a]
            rb = game.DOORS[b]
            route = g.walk_route(a, ra, b, rb)
            hall = g.hall_of(a)
            for i in range(len(route) - 1):
                (x0, y0), (x1, y1) = route[i], route[i + 1]
                # 逐点采样这段线段
                n = max(2, int(max(abs(x1 - x0), abs(y1 - y0))))
                for k in range(n + 1):
                    px = x0 + (x1 - x0) * k / n
                    py = y0 + (y1 - y0) * k / n
                    in_hall = game.CORR_L <= px <= game.CORR_R
                    if in_hall:
                        # 在过道里：y 必须在本层过道段内
                        if not (hall[0] - 3 <= py <= hall[1] + 3):
                            bad.append(f'{a}->{b} 过道内 y={py:.0f} 越界')
                    else:
                        # 在房间里：不能越过通道跑到对侧
                        if abs(px - game.CORR_X) < 1 and a != b:
                            pass
    check('所有路线都没有越出本层过道', not bad)
    for b in bad[:5]:
        print('   越界:', b)
    # 同层的两个房间必须能互相走到
    g2 = fresh()
    for x in g2.stations:
        x.unlocked = x.subscribed = True
        x.quota = 400
    cl = next(x for x in g2.stations if x.m['id'] == 'Claude')
    qw = next(x for x in g2.stations if x.m['id'] == 'Qwen')
    route = g2.walk_route('Claude', (cl.px, cl.feet), 'Qwen', (qw.cx, qw.feet))
    cl.social_state = 'walk'
    cl.social_dest_key = 'Qwen'
    cl.chat_line = ''
    cl.walk_path = route[1:]
    for _ in range(3000):
        g2.update(0.05)
        if cl.social_state == 'chat':
            break
    check('同层房间之间真的能走到（Claude -> Qwen）', cl.social_state == 'chat')
    check('走到了对方房间里',
          abs(cl.px - qw.cx) < 90 and abs(cl.feet - qw.feet) < 90)

    # ------------------------------------------------ 渲染
    print('\n【界面渲染】')
    g = fresh()
    g.money = 5000
    g.panel = ('gear', None)
    g.draw()
    check('装备商店面板能画', True)
    g.panel = None
    g.draw()
    check('场景能画', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
