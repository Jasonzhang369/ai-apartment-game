#!/usr/bin/env python3
"""无头截图自检：用 dummy 视频驱动把几个界面渲染成 PNG，方便肉眼验收。

用法：
    python3 tools/shot.py                # 直接写进 screenshots/（带中文名）
    python3 tools/shot.py /tmp/out       # 写到别的目录
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

game.RENT_NOTICE_ON = False      # 自测/模拟里不弹房租窗，免得挡住自动跑

# key -> 中文文件名（写进 screenshots/ 时用）
NAMES = {
    'title': '00_标题存档.png',
    'hall': '01_公寓全景.png',
    'server': '02_派单面板.png',
    'station': '03_工位_升级额度.png',
    'gateway': '04_网关升级.png',
    'slack': '05_摸鱼与冰箱.png',
    'fridge': '06_冰箱零食面板.png',
    'breaker': '07_电闸与电路.png',
    'store': '08_装备店.png',
    'bag': '09_背包.png',
    'settings': '12_设置.png',
    'title_settings': '13_首页设置.png',
    'chat': '14_两人聊天.png',
    'cook': '15_千问做饭.png',
    'contract': '16_长期合同.png',
    'station': '17_工位面板.png',
    'relations': '18_关系面板.png',
    'server': '19_派单服务器.png',
    'station': '20_科考站.png',
    'title_credits': '21_首页说明.png',
    'test_station': '22_科考站试玩.png',
    'fuel': '23_燃料与值班.png',
}


def snap(g, out, key):
    g.draw()
    path = os.path.join(out, NAMES.get(key, f'{key}.png'))
    pygame.image.save(g.screen, path)
    print('saved', path)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'screenshots')
    os.makedirs(out, exist_ok=True)

    g = game.Game()
    snap(g, out, 'title')
    g.panel = ('settings', 'title')
    snap(g, out, 'title_settings')
    g.panel = None

    g.state = 'play'
    for _ in range(3):
        g.try_spawn()
    for _ in range(200):
        g.update(0.05)
    snap(g, out, 'hall')

    # 派两单出去，看光束与进度条
    qs = g.queued_tasks()
    used = 0
    for st in g.stations:
        if used >= min(2, len(qs)):
            break
        if st.ready():
            g.assign(qs[used], st)
            used += 1
    for _ in range(40):
        g.update(0.05)

    # 摸鱼（DeepSeek 煮大白饭）+ 冰箱库存牌
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    ds.slack = game.SLACK_SEC * 0.6
    g.snacks = 2
    snap(g, out, 'slack')
    ds.slack = 0.0

    # 派单面板
    g.try_spawn()
    if g.queued_tasks():
        g.panel = ('server', 0)
        snap(g, out, 'server')
        g.panel = None

    # 冰箱 / 网关 / 电闸 / 工位
    for key in ('fridge', 'gateway', 'breaker'):
        g.panel = (key, None)
        snap(g, out, key)
    g.panel = ('station', g.stations[1])
    snap(g, out, 'station')
    g.panel = None

    # 装备店 + 背包（v29）：买几件道具，展示背包与拖拽入口
    g.money = max(g.money, 4000)
    for gid in ('cpu', 'fan', 'net'):
        g.buy_gear(next(x for x in game.GEAR if x['id'] == gid))
    g.buy_reset_card(next(s for s in g.stations if s.m['id'] == 'DeepSeek'))
    g.buy_reset_card(next(s for s in g.stations if s.m['id'] == 'GLM'))
    g.panel = ('gear', None)
    snap(g, out, 'store')
    g.panel = ('bag', None)
    g.held_item = 'cpu'
    snap(g, out, 'bag')
    g.held_item = None
    g.panel = None

    # 两人面对面聊天（v32）
    g.state = 'play'
    a = next(x for x in g.stations if x.m['id'] == 'Gemini')
    b = next(x for x in g.stations if x.m['id'] == 'GLM')
    a.px, a.feet = 520, 408
    b.px, b.feet = 566, 408
    a.unlocked = a.subscribed = True
    b.unlocked = b.subscribed = True
    g.set_bond(a, b, 0.9)          # 关系好：中间会飘一颗心
    for x, y, line in ((a, b, '你那显卡烫不烫？'), (b, a, '还行，刚换了风扇')):
        x.social_state = 'chat'
        x.chat_partner = y.m['id']
        x.chat_line = line
        x.social_timer = 9
    snap(g, out, 'chat')
    for x in (a, b):
        x.social_state = 'home'
        x.chat_partner = None
        x.chat_line = ''

    # 千问做饭（v33）
    g.state = 'play'
    qw = next(x for x in g.stations if x.m['id'] == 'Qwen')
    qw.unlocked = qw.subscribed = True
    qw.px, qw.feet = 640, 96
    qw.social_state = 'cook'
    qw.cooking = game.MEAL_COOK_SEC * 0.6
    qw.meal_slot = 12
    snap(g, out, 'cook')
    qw.cooking = 0.0
    qw.social_state = 'home'
    qw.px, qw.feet = qw.cx, qw.home_feet

    # 长期合同报价（v33）
    g.contract_offer = dict(typ='code', days=5, need=2, reward=600, count=8)
    g.panel = ('contract', g.contract_offer)
    snap(g, out, 'contract')
    g.panel = None
    g.contract_offer = None

    # 工位面板：人缘 / 餐食加成（v33）
    g.state = 'play'
    gm = next(x for x in g.stations if x.m['id'] == 'Gemini')
    gm.unlocked = gm.subscribed = True
    gm.meal = game.MEAL_BUFF_SEC * 0.6
    g.set_bond(gm, next(x for x in g.stations if x.m['id'] == 'GLM'), 0.9)
    g.set_bond(gm, next(x for x in g.stations if x.m['id'] == 'Qwen'), 0.4)
    g.panel = ('station', gm)
    snap(g, out, 'station')
    g.panel = None

    # 关系面板（v34）
    g.state = 'play'
    gm2 = next(x for x in g.stations if x.m['id'] == 'Gemini')
    g.set_bond(gm2, next(x for x in g.stations if x.m['id'] == 'Qwen'), 0.4)
    g.set_bond(gm2, next(x for x in g.stations if x.m['id'] == 'DeepSeek'), 0.2)
    g.panel = ('relations', None)
    snap(g, out, 'relations')
    g.panel = None

    # 派单服务器 + 长期合同（v35）
    g.state = 'play'
    g.contract = dict(typ='code', left=4, need=2, today=1, reward=600)
    g.panel = ('server', 0)
    snap(g, out, 'server')
    g.contract = None
    g.panel = None

    # 科考站场景（v36）
    g.money = 9000
    g.day = 6
    for st in g.stations:
        st.unlocked = st.subscribed = True
        st.refresh_daily()
    g.relocate()
    snap(g, out, 'station')
    g.state = 'title'
    snap(g, out, 'title_credits')
    g.state = 'play'
    g.set_scene('apartment')
    g.money = 1830
    g.day = 1

    # 科考站试玩（v37）
    g2 = game.Game()
    g2.start_test_station()
    snap(g2, out, 'test_station')
    g2.panel = ('breaker', None)
    snap(g2, out, 'fuel')
    g2.panel = None

    # 设置面板（v30）
    g.state = 'play'
    g.panel = ('settings', 'game')
    snap(g, out, 'settings')
    g.panel = None
    print('done')


if __name__ == '__main__':
    main()
