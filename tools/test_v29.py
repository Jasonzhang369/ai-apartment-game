#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v29 自测：背包与拖拽 / 可重复购买 / 按线路定价的重置卡 / 连续派单 /
休息日按钮搬进网关 / 行走轨迹轴对齐 / 工作时不走动 / 存档字段补全。

用法：python3 tools/test_v29.py
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


def screen_of(st):
    """工位在屏幕上的点（zoom=1 时屏幕坐标 = 世界坐标）。"""
    return (int(st.px * game.SCALE), int((st.feet - 30) * game.SCALE))


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    # ------------------------------------------------ 背包与拖拽
    print('\n【背包：买到的进背包，拖到 AI 身上用】')
    g = fresh()
    g.money = 6000
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    cpu = next(x for x in game.GEAR if x['id'] == 'cpu')

    g.buy_gear(cpu)
    check('买完进背包', g.bag_count('cpu') == 1)
    check('买完不会自动拿在手上', g.held_item is None and g.drag_item is None)

    g.panel = ('bag', None)
    slot = next(r for item, r in g.bag_slots() if item == 'cpu')
    g.click_bag(slot.center)
    check('在背包里按下道具开始拖', g.drag_item == 'cpu')
    g.update_drag((slot.centerx + 30, slot.centery - 30))
    check('拖出一段距离算拖拽', g.drag_moved is True)

    before = set(ds.gear)
    g.finish_drag(screen_of(ds))
    check('松手落在 AI 身上就装上', 'cpu' in ds.gear and 'cpu' not in before)
    check('装完背包里少一件', g.bag_count('cpu') == 0)
    check('用完自动关掉背包', g.panel is None)

    # 点一下再点 AI 也能用（不拖）
    g.buy_gear(next(x for x in game.GEAR if x['id'] == 'fan'))
    g.panel = ('bag', None)
    slot = next(r for item, r in g.bag_slots() if item == 'fan')
    g.click_bag(slot.center)
    g.finish_drag(slot.center)          # 原地松手 -> 转成手持
    check('原地松手变成"手持"', g.held_item == 'fan' and g.drag_item is None)
    g.click_bag(screen_of(ds))
    check('再点 AI 就装上', 'fan' in ds.gear)
    check('手持用掉后清空', g.held_item is None)

    # 一条线最多三件
    g.money = 9000
    for gid in ('net', 'mem'):
        g.buy_gear(next(x for x in game.GEAR if x['id'] == gid))
        g.equip_gear(ds, gid)
    g.buy_gear(next(x for x in game.GEAR if x['id'] == 'cpu'))
    g.equip_gear(ds, 'cpu')
    check('装备栏满了装不上第四件', len(ds.gear) == game.MAX_GEAR)
    check('装不上的还在背包里', g.bag_count('cpu') == 1)

    # ------------------------------------------------ 可重复购买
    print('\n【道具可以重复购买】')
    g2 = fresh()
    g2.money = 10000
    money0 = g2.money
    for _ in range(3):
        g2.buy_gear(cpu)
    check('同一件装备能买三次', g2.bag_count('cpu') == 3)
    check('三次都扣了钱', abs((money0 - g2.money) - cpu['price'] * 3) < 1e-6)
    ds2 = next(s for s in g2.stations if s.m['id'] == 'DeepSeek')
    qw2 = next(s for s in g2.stations if s.m['id'] == 'Qwen')
    g2.equip_gear(ds2, 'cpu')
    g2.equip_gear(qw2, 'cpu')
    check('同一种装备能装给不同的 AI',
          'cpu' in ds2.gear and 'cpu' in qw2.gear)
    check('还剩一件在背包里', g2.bag_count('cpu') == 1)

    # 拆卸回背包
    g2.unequip_gear(ds2, 'cpu')
    check('拆下来的回到背包', g2.bag_count('cpu') == 2 and 'cpu' not in ds2.gear)
    g2.equip_gear(qw2, 'cpu')
    check('同一条线不会重复装同一件', g2.bag_count('cpu') == 2)

    # ------------------------------------------------ 重置卡
    print('\n【重置卡：按线路定价 · 可攒 · 拖给人用】')
    g3 = fresh()
    g3.money = 10000
    ds3 = next(s for s in g3.stations if s.m['id'] == 'DeepSeek')
    cl3 = next(s for s in g3.stations if s.m['id'] == 'Claude')
    ds3.unlocked = ds3.subscribed = True
    ds3.quota = 400
    give_job(g3, ds3)
    ds3.limited = True
    ds3.strain = 1.0
    ds3.quota = 5

    p_ds = game.reset_price(ds3.m)
    p_cl = game.reset_price(cl3.m)
    check('每条线的重置卡价格不同', p_ds != p_cl)
    check('贵的线路重置卡更贵', p_cl > p_ds)
    g3.buy_reset_card(ds3)
    g3.buy_reset_card(ds3)
    check('可以买多张攒着', g3.bag_count('reset:DeepSeek') == 2)
    check('没买 Claude 的卡', g3.bag_count('reset:Claude') == 0)

    g3.panel = ('bag', None)
    card_slot = next(r for item, r in g3.bag_slots() if item == 'reset:DeepSeek')
    g3.click_bag(card_slot.center)
    g3.finish_drag(screen_of(cl3))
    check('把 DeepSeek 的卡拖给 Claude 会被拒绝', g3.bag_count('reset:DeepSeek') == 2)
    check('拒绝时给提示', g3.toast is not None)

    g3.click_bag(card_slot.center)
    g3.finish_drag(screen_of(ds3))
    check('拖给本人就能用', g3.bag_count('reset:DeepSeek') == 1)
    check('限流解除', ds3.limited is False)
    check('压力清零', ds3.strain == 0.0)
    check('额度补满', ds3.quota == ds3.quota_cap())
    check('手上的活不打断', ds3.busy is not None)

    # ------------------------------------------------ 连续派单
    print('\n【服务器：连续指派】')
    g4 = fresh()
    for _ in range(3):
        t = game.Task('code')
        t.state = 'stored'
        g4.tasks.append(t)
    for s in g4.stations[:3]:
        s.unlocked = s.subscribed = True
        s.quota = 600
    qs = g4.queued_tasks()
    check('待处理有多单', len(qs) >= 2)
    g4.panel = ('server', 0)
    used = 0
    for st, card in g4.server_cards():
        if used >= 2 or not g4.queued_tasks():
            break
        if not st.ready():
            continue
        g4.click_panel(card.centerx, card.centery)
        used += 1
        check(f'派完第 {used} 单面板还开着', g4.panel and g4.panel[0] == 'server')
    check('连派两单都没关面板', used == 2 and g4.panel[0] == 'server')
    busy_n = sum(1 for s in g4.stations if s.busy)
    check('确实派出去了两单', busy_n >= 2)

    # 6 个待处理位全部可见
    g5 = fresh()
    for s in g5.stations[:3]:
        s.unlocked = s.subscribed = True
        s.quota = 600
    for _ in range(6):
        t = game.Task('code')
        t.state = 'stored'
        g5.tasks.append(t)
    check('队列里 6 单', len(g5.queued_tasks()) == 6)
    check('面板能列出 6 行', len(g5.task_rows()) == 6)

    # ------------------------------------------------ 休息日按钮
    print('\n【休息日按钮：从右栏搬进网关】')
    g6 = fresh()
    keys = [k for k, r in g6.pane_buttons()]
    check('右栏不再有 rest 按钮', 'rest' not in keys)
    check('右栏多了一个背包按钮', 'bag' in keys)
    g6.panel = ('gateway', None)
    g6.draw()
    btn = g6.gateway_rest_btn()
    check('网关面板里有休息日按钮', btn.w > 0)
    g6.click_panel(btn.centerx, btn.centery)
    check('点它能让大家休息', g6.rest_day is True)
    check('豆包不参与休息', next(s for s in g6.stations
                                 if s.m['id'] == 'Doubao').resting is False)

    log_bottom = 562 + 5 * 16 + 11
    bag_btn = dict(g6.pane_buttons())['bag']
    check('日志区不再压住按钮', log_bottom <= bag_btn.y)

    # 按钮在右栏范围内、不压 BUILD 行
    check('背包按钮在右栏里', game.PANE_X <= bag_btn.x and bag_btn.right <= game.SW)
    check('背包按钮不压 BUILD', bag_btn.bottom <= 706)

    # ------------------------------------------------ 行走轨迹
    print('\n【行走：轴对齐、不穿墙、干活不动】')
    g7 = fresh()
    for s in g7.stations:
        s.unlocked = s.subscribed = True
        s.quota = 600
    by_id = {s.m['id']: s for s in g7.stations}
    pairs = [('Claude', 'Qwen'), ('ChatGPT', 'Grok'), ('Gemini', 'GLM')]
    axis_ok, hall_ok = True, True
    for a, b in pairs:
        pa = (by_id[a].cx, by_id[a].feet)
        pb = (by_id[b].cx, by_id[b].feet)
        route = g7.walk_route(a, pa, b, pb)
        hall = g7.hall_of(a)
        for i in range(len(route) - 1):
            (x0, y0), (x1, y1) = route[i], route[i + 1]
            if abs(x0 - x1) > 0.01 and abs(y0 - y1) > 0.01:
                axis_ok = False
            n = max(2, int(max(abs(x1 - x0), abs(y1 - y0))))
            for k in range(n + 1):
                px = x0 + (x1 - x0) * k / n
                py = y0 + (y1 - y0) * k / n
                if game.CORR_L <= px <= game.CORR_R and not (hall[0] - 3 <= py <= hall[1] + 3):
                    hall_ok = False
    check('每一段路线都是横平竖直的（不斜切墙角）', axis_ok)
    check('同层路线的过道段不越界', hall_ok)

    # 干活时钉在工位不动
    st = by_id['DeepSeek']
    st.social_timer = 0.0
    job = give_job(g7, st)
    home = (st.px, st.feet)
    moved = 0
    for _ in range(200):
        g7.update(0.05)
        moved = max(moved, abs(st.px - home[0]) + abs(st.feet - home[1]))
        if job.state != 'service':
            break
    check('有活的时候一步都没动', moved < 0.6)
    check('有活的时候不会出门串门', st.social_state == 'home')

    # 串门走到一半被派活：先回家，进度不动
    st2 = by_id['GLM']
    st2.social_state = 'walk'
    st2.at_key = 'GLM'
    st2.px, st2.feet = st2.cx, st2.home_feet
    st2.social_dest_key = 'Qwen'
    st2.walk_path = g7.walk_route('GLM', (st2.px, st2.feet), 'Qwen', (620, 542))
    for _ in range(10):
        g7.update(0.05)
    pw = (st2.px, st2.feet)
    check('走在半路', abs(st2.px - st2.cx) + abs(st2.feet - st2.home_feet) > 1)
    job2 = give_job(g7, st2)
    check('派活时不瞬移', (st2.px, st2.feet) == pw)
    bad = False
    for _ in range(80):
        g7.update(0.05)
        if not st2.at_home() and job2.prog > 1e-9:
            bad = True
        if st2.at_home():
            break
    check('回家路上不干活', not bad)
    for _ in range(600):
        g7.update(0.05)
        if st2.at_home():
            break
    check('最后走到工位', st2.at_home())

    # ------------------------------------------------ 存档
    print('\n【存档：背包 / 订阅天数 / 基础设施】')
    g8 = fresh()
    g8.money = 9999
    qw8 = next(s for s in g8.stations if s.m['id'] == 'Qwen')
    g8.unlock_station(qw8)
    g8.subscribe(qw8, 2)
    g8.gw_lv = 3
    g8.breaker_lv = 4
    g8.ad_days = 1
    g8.buy_gear(cpu)
    g8.buy_reset_card(qw8)
    g8.save()

    g9 = game.Game()
    check('读档成功', g9.load() is True)
    qw9 = next(s for s in g9.stations if s.m['id'] == 'Qwen')
    check('背包存下来了', g9.bag_count('cpu') == 1 and g9.bag_count('reset:Qwen') == 1)
    check('网关等级存下来了', g9.gw_lv == 3)
    check('电闸等级存下来了', g9.breaker_lv == 4)
    check('广告天数存下来了', g9.ad_days == 1)
    check('订阅剩余天数存下来了', qw9.sub_days == 7 and qw9.subscribed)
    g9.state = 'play'
    g9.t = g9.settle_point() + 0.01
    g9.update(0.05)
    check('读档后过 24:00 订阅不会立刻到期', qw9.subscribed and qw9.sub_days == 6)

    # ------------------------------------------------ 渲染
    print('\n【商店面板：点按钮就能买】')
    g11 = fresh()
    g11.money = 5000
    g11.panel = ('gear', None)
    gb = g11.store_gear_btns()[0]
    g11.click_panel(gb[1].centerx, gb[1].centery)
    check('点装备的购买按钮能买到', g11.bag_count(gb[0]['id']) == 1)
    rm = g11.store_reset_rows()[0]
    g11.click_panel(rm[2].centerx, rm[2].centery)
    check('点重置卡的购买按钮能买到',
          g11.bag_count('reset:' + rm[0]['id']) == 1)
    check('商店面板买完不关', g11.panel == ('gear', None))

    print('\n【行走掩码：A* 绕墙】')
    import json as _json
    mask_path = '/tmp/aihub_test_mask.json'
    walls = [[30, y] for y in list(range(0, 25)) + list(range(28, 45))]
    with open(mask_path, 'w') as f:
        _json.dump(dict(cell=16, cols=60, rows=45, walls=walls), f)
    os.environ['AIHUB_WALKMASK'] = mask_path
    gm = game.Game()
    gm.state = 'play'
    check('掩码被读进来', gm.walkmask is not None and len(gm.walkmask.walls) == 42)
    route = gm.walk_route('Claude', (400, 300), 'Qwen', (600, 300))
    ok_route = bool(route) and tuple(route[0]) == (400, 300) and tuple(route[-1]) == (600, 300)
    check('起点终点对得上', ok_route)
    no_wall = True
    for i in range(len(route) - 1):
        (x0, y0), (x1, y1) = route[i], route[i + 1]
        n = max(2, int(max(abs(x1 - x0), abs(y1 - y0))))
        for k in range(n + 1):
            x = x0 + (x1 - x0) * k / n
            y = y0 + (y1 - y0) * k / n
            if not gm.walkmask.free(*gm.walkmask.cell_of(x, y)):
                no_wall = False
    check('整条路都不穿墙', no_wall)
    check('绕过了墙上的洞（y 到过 400 附近）',
          max(p[1] for p in route) > 380)
    check('有掩码时不走老的门/走道路线',
          route != gm.walk_route_doors('Claude', (400, 300), 'Qwen', (600, 300)))
    # 掩码把工位脚下涂成墙：加载时要自动清出来，否则永远开不了工
    home = next(x for x in gm.stations if x.m['id'] == 'DeepSeek')
    hc = gm.walkmask.cell_of(home.cx, home.home_feet)
    full = [[30, y] for y in list(range(0, 25)) + list(range(28, 45))] + [[hc[0], hc[1]]]
    with open(mask_path, 'w') as f:
        _json.dump(dict(cell=16, cols=60, rows=45, walls=full), f)
    gm3 = game.Game()
    gm3.state = 'play'
    ds3m = next(x for x in gm3.stations if x.m['id'] == 'DeepSeek')
    check('工位脚下的墙会被清掉', gm3.walkmask.free(*gm3.walkmask.cell_of(ds3m.cx, ds3m.home_feet)))
    check('清掉后能正常开工', ds3m.at_home() and ds3m.ready())

    # 路径必须是"横平竖直"的：角色先横后竖走，斜段会撞墙角（Qwen 上不了楼就是这个）
    route2 = gm.walk_route('Claude', (416, 540), 'SERVER', (500, 108))
    centers = route2[1:-1]          # 格心（首尾是角色实际位置）
    axis_only = all(abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01
                    for a, b in zip(centers, centers[1:]))
    check('A* 路径的中间段都是横平竖直', axis_only)

    cl = next(x for x in gm.stations if x.m['id'] == 'Claude')
    cl.px, cl.feet = 400, 300
    cl.social_state = 'walk'
    cl.social_dest_key = 'SERVER'
    cl.chat_x, cl.chat_y = 600, 300
    cl.walk_path = gm.walk_route('Claude', (400, 300), 'SERVER', (600, 300))[1:]
    stalled = False
    for _ in range(800):
        gm.step_walk(cl, 0.05)
        if cl.walk_idle > 0.5:
            stalled = True
            break
        if not cl.walk_path:
            break
    check('照着这条路真的能绕过墙（不会卡在墙角）', (not stalled) and not cl.walk_path)

    os.environ['AIHUB_WALKMASK'] = '/tmp/aihub_no_mask.json'
    gm2 = game.Game()
    check('没有掩码文件就不启用 A*', gm2.walkmask is None)

    # 有掩码时不该再受"同一段过道"的限制，不然住楼下的人永远不上楼
    open_path = '/tmp/aihub_nomask_walls.json'
    with open(open_path, 'w') as f:
        _json.dump(dict(cell=16, cols=60, rows=45, walls=[]), f)
    os.environ['AIHUB_WALKMASK'] = open_path
    gq = game.Game()
    gq.state = 'play'
    for x in gq.stations:
        x.unlocked = x.subscribed = True
        x.quota = 400
    qw = next(s for s in gq.stations if s.m['id'] == 'Qwen')
    spots = [gq.pick_spot(qw)[2] for _ in range(200)]
    check('有掩码时楼下的人也能去楼上',
          any(n in ('客厅', '厨房', '阳台') for n in spots))
    partners = {gq.pick_partner(qw) for _ in range(60)}
    partners.discard(None)
    check('有掩码时能挑到楼上的邻居', len(partners) >= 2)
    route_up = gq.walk_route('Qwen', (qw.px, qw.feet), 'SERVER', (500, 108))
    check('到楼上的路能规划出来', bool(route_up) and len(route_up) >= 2)
    os.environ['AIHUB_WALKMASK'] = '/tmp/aihub_no_mask.json'

    print('\n【标注工具】')
    sys.path.insert(0, os.path.join(ROOT, 'tools'))
    import map_editor as me
    me.PREVIEW_PATH = '/tmp/aihub_mask_preview.png'
    ed = me.Editor('/tmp/aihub_editor_test.json')
    ed.paint((5, 5))
    ed.paint((6, 5))
    ed.fill_rect((10, 10), (12, 11))
    ed.save()
    check('工具能存掩码', os.path.exists('/tmp/aihub_editor_test.json'))
    check('存的格数对', len(me.load_mask('/tmp/aihub_editor_test.json')) == 8)
    check('能出预览图', os.path.getsize(me.PREVIEW_PATH) > 1000)
    ed2 = me.Editor('/tmp/aihub_editor_test.json')
    check('能重新读回来', len(ed2.walls) == 8)
    ed2.draw()
    check('工具界面能画', True)

    # macOS 上 MOUSEBUTTONDOWN 没有 mod 字段，这里用真事件回归一下
    ed3 = me.Editor('/tmp/aihub_editor_test3.json')
    ed3.on_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 100)))
    check('鼠标事件没有 mod 字段也不崩', len(ed3.walls) == 1)
    ed3.on_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(140, 100),
                                    buttons=(1, 0, 0), rel=(40, 0)))
    check('拖动连续涂墙', len(ed3.walls) >= 2)
    ed3.on_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(140, 100)))
    hit = ed3.cell_at((100, 100))
    ed3.on_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(100, 100)))
    ed3.on_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=3, pos=(100, 100)))
    check('右键能擦掉', hit not in ed3.walls)
    ed3.on_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                    pos=(200, 200), mod=pygame.KMOD_SHIFT))
    check('Shift 走矩形模式', ed3.drag == 'rect')

    # 缩放 / 平移后，鼠标坐标换算仍然一致
    ed3.set_zoom(2.0, (480, 360))
    wx, wy = ed3.to_world((480, 360))
    check('放大后坐标换算一致',
          ed3.cell_at((480, 360)) == (int(wx // 16), int(wy // 16)))
    check('放大后视野变小', ed3.view_size()[0] < game.WW)
    ed3.cam[0] += 9999
    ed3.clamp_cam()
    check('镜头不会拖出地图', ed3.cam[0] <= game.WW)
    check('房间名都在画面内',
          all(0 <= x <= game.WW and 0 <= y <= game.WH for _, x, y in me.ROOM_LABELS))

    print('\n【v29.3 显示与串门细节】')
    g12 = fresh()
    for x in g12.stations:
        x.unlocked = x.subscribed = True
        x.quota = 500
    ds = next(x for x in g12.stations if x.m['id'] == 'DeepSeek')
    qw = next(x for x in g12.stations if x.m['id'] == 'Qwen')
    plate = g12.name_plate_pos(qw)
    bubble = g12.chat_bubble_pos(qw)
    check('名字牌挪到人右侧', plate[0] > qw.px)
    check('气泡贴着头顶（不再飘太高）', 40 < qw.feet - bubble[1] < 130)
    bw = game.text_w('测试台词', 12, True) + 14
    check('气泡不压名字牌', bubble[1] + 24 <= plate[1])
    check('名字牌贴在人右侧腰高', plate[1] == int(qw.feet) - 60)

    # 忙的人不会被拜访
    qw.busy = game.Task('code')
    partners = [g12.pick_partner(ds) for _ in range(200)]
    check('没人去找正在干活的 Qwen', all(p is not qw for p in partners))
    qw.busy = None

    # 回工位加速
    cl = next(x for x in g12.stations if x.m['id'] == 'Claude')
    cl.px, cl.feet = 300, 540
    cl.social_state = 'walk'
    cl.walk_path = [(500, 540)]
    g12.step_walk(cl, 0.05)
    d_walk = cl.px - 300
    cl.px = 300
    cl.walk_path = [(500, 540)]
    cl.social_state = 'back'
    cl.busy = game.Task('code')
    g12.step_walk(cl, 0.05)
    d_back = cl.px - 300
    check('被派活后回工位更快', d_back > d_walk * 1.5)
    check('加速幅度就是 RETURN_BOOST',
          abs(d_back / max(0.01, d_walk) - game.RETURN_BOOST) < 0.05)
    cl.busy = None

    # 聊天不重叠
    glm = next(x for x in g12.stations if x.m['id'] == 'GLM')
    glm.px, glm.feet = 600, 400
    qw.px, qw.feet = 610, 402
    g12.separate_from_others(glm)
    check('不再瞬移错开（允许原地站着聊）', glm.social_state != '' )

    # 提示条：按文字撑开 + 背包开着时浮上去
    g12.panel = None
    r = g12.toast_rect('这张是 DeepSeek 的重置卡，用不到 Claude 身上')
    check('长提示条按文字撑开', r.w > 300)
    check('提示条不出屏', r.x >= 0 and r.right <= game.WW)
    g12.panel = ('bag', None)
    check('背包开着时提示浮在背包上方',
          g12.toast_rect('DeepSeek 已重置').bottom < g12.bag_panel_rect().top)
    g12.panel = None

    print('\n【界面渲染】')
    g10 = fresh()
    g10.money = 5000
    g10.buy_gear(cpu)
    g10.buy_reset_card(next(s for s in g10.stations if s.m['id'] == 'DeepSeek'))
    g10.panel = ('bag', None)
    g10.draw()
    check('背包面板能画', True)
    g10.panel = ('gear', None)
    g10.draw()
    check('装备店面板能画', True)
    g10.panel = ('gateway', None)
    g10.draw()
    check('网关面板（带休息按钮）能画', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
