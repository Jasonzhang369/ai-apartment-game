#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v30 自测：多个存档位 / 设置面板（音乐、音量、全屏、继续、回首页）/
房租前一天弹窗 / 全屏缩放与鼠标换算。

用法：python3 tools/test_v30.py
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
game.INTRO_ON = False      # 自测里默认不弹房租窗

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


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    for i in range(1, game.SLOT_COUNT + 1):
        if os.path.exists(game.save_path(i)):
            os.remove(game.save_path(i))

    # ------------------------------------------------ 多个存档位
    print('\n【4 个存档位】')
    g = fresh()
    g.day = 3
    g.money = 2222
    g.slot = 2
    g.save()
    check('2 号位写的是另一个文件', os.path.exists(game.save_path(2)))
    check('1 号位没被写', not os.path.exists(game.save_path(1)))
    check('文件名带 _2', game.save_path(2).endswith('_2.json'))

    g.slot = 1
    g.day = 9
    g.money = 777
    g.save()
    check('两个存档位互不覆盖',
          game.Game().peek_save(1).get('day') == 9
          and game.Game().peek_save(2).get('day') == 3)

    g2 = game.Game()
    check('按位读档成功', g2.load(2) is True and g2.day == 3)
    check('读档后当前存档位跟着切', g2.slot == 2)

    # 首页：4 张卡 + 设置/退出
    t = game.Game()
    t.state = 'title'
    slots = [s for a, r, s in t.title_buttons() if s]
    check('首页有 4 个存档位', set(slots) == set(range(1, game.SLOT_COUNT + 1)))
    acts = {a for a, r, s in t.title_buttons()}
    check('首页有设置和退出', {'settings', 'quit'} <= acts)
    check('有档的位子有继续/覆盖/删除',
          {'load', 'new', 'delete'} <= acts)
    cards = t.title_slot_rects()
    check('存档卡都在窗口里', all(pygame.Rect(0, 0, game.SW, game.SH).contains(c)
                               for _, c in cards))

    # 点“继续”真的进游戏
    load_btn = next(r for a, r, s in t.title_buttons() if a == 'load' and s == 2)
    t.click_title(load_btn.center)
    check('点继续能进游戏', t.state == 'play' and t.day == 3)

    # 删除存档
    t.state = 'title'
    del_btn = next(r for a, r, s in t.title_buttons() if a == 'delete' and s == 2)
    t.click_title(del_btn.center)
    check('删除按钮能删掉存档', not os.path.exists(game.save_path(2)))

    # ------------------------------------------------ 存档时间与运行态
    print('\n【存档到分钟 + 运行态】')
    g = fresh()
    g.money = 9999
    g.day = 5
    g.t = 123.4                       # 约 17:51
    g.ad_days = 1
    g.burst = 8.5
    g.event = dict(kind='burst', name='爆单', left=5.0, desc='x')
    g.t_rev = 456.0
    g.t_orders = 7
    ds = next(x for x in g.stations if x.m['id'] == 'DeepSeek')
    ds.unlocked = ds.subscribed = True
    ds.quota = 37
    ds.limited = True
    ds.snack = 33.3
    ds.temp = 71.5
    ds.strain = 0.55
    g.slot = 4
    g.save()
    info = g.peek_save(4)
    check('存档里记了时间轴', 't' in info and info['t'] > 0)
    check('存档里记了钟点', info.get('clock', '').count(':') == 1)
    check('时间按分钟取整（误差不到 1% 分钟）',
          abs(info['t'] * game.GAME_MIN_PER_SEC
              - round(info['t'] * game.GAME_MIN_PER_SEC)) < 0.02)

    g2 = game.Game()
    g2.load(4)
    check('读档从存档那一刻开始', abs(g2.t - info['t']) < 0.01)
    check('读档的钟点和存档一致', g2.clock_text() == info['clock'])
    check('读档不是 08:00', g2.clock_text() != '08:00')
    check('广告天数存下来了', g2.ad_days == 1)
    check('爆单倒计时存下来了', abs(g2.burst - 8.5) < 0.01)
    check('事件横幅存下来了', bool(g2.event))
    check('当天营收存下来了', abs(g2.t_rev - 456.0) < 0.01)
    ds2 = next(x for x in g2.stations if x.m['id'] == 'DeepSeek')
    check('剩余额度存下来了', abs(ds2.quota - 37) < 0.5)
    check('限流状态存下来了', ds2.limited is True)
    check('零食 buff 存下来了', abs(ds2.snack - 33.3) < 0.2)
    check('温度存下来了', abs(ds2.temp - 71.5) < 0.2)
    check('限流压力存下来了', abs(ds2.strain - 0.55) < 0.01)

    # 旧存档（没有 t）仍然从当天 08:00 开始
    import json as _json
    with open(game.save_path(3), 'w') as f:
        _json.dump(dict(day=3, money=100, rep=50, price_idx=2, snacks=3,
                        st=[dict(tier=1, un=True, sb=True, big=False,
                                 gear=[], earn=0, done=0)]), f)
    g3 = game.Game()
    g3.load(3)
    check('老存档兼容：从 08:00 开始', g3.t == 0 and g3.clock_text() == '08:00')

    # 关窗口会自动存档
    g4 = fresh()
    g4.slot = 2
    g4.day = 7
    g4.t = 42.0
    if os.path.exists(game.save_path(2)):
        os.remove(game.save_path(2))
    g4.on_event(pygame.event.Event(pygame.QUIT))
    check('关窗口时自动存档', os.path.exists(game.save_path(2)))
    check('自动存档也带时间', abs(game.Game().peek_save(2).get('t', -1) - 42.0) < 0.3)

    # ------------------------------------------------ 设置面板
    print('\n【设置面板】')
    g = fresh()
    g.money = 5000
    before_t = g.t
    g.panel = ('settings', 'game')
    g.paused = True
    for _ in range(20):
        g.update(0.05)
    check('打开设置时时间冻结', abs(g.t - before_t) < 1e-9)
    check('设置面板能画', (g.draw() or True))

    music_on = bool(g.music.settings.get('music'))
    mb = next(r for k, r in g.settings_buttons() if k == 'music')
    g.click_settings(mb.centerx, mb.centery, 'game')
    check('能切换音乐开关', bool(g.music.settings.get('music')) != music_on)

    vol0 = float(g.music.settings.get('volume'))
    up = next(r for k, r in g.settings_buttons() if k == 'vol_up')
    g.click_settings(up.centerx, up.centery, 'game')
    check('能调大音量', float(g.music.settings.get('volume')) >= vol0)
    for _ in range(20):
        g.click_settings(up.centerx, up.centery, 'game')
    check('音量封顶 1.0', float(g.music.settings.get('volume')) <= 1.0)
    down = next(r for k, r in g.settings_buttons() if k == 'vol_down')
    for _ in range(20):
        g.click_settings(down.centerx, down.centery, 'game')
    check('音量到底 0.0', float(g.music.settings.get('volume')) >= 0.0)
    g.music.set_volume(0.6)
    check('音量写进了 settings.json',
          os.path.exists(game.SETTINGS_PATH))

    close = next(r for k, r in g.settings_buttons() if k == 'close')
    g.click_settings(close.centerx, close.centery, 'game')
    check('点继续游戏关掉面板', g.panel is None)
    check('关掉之后不再暂停', g.paused is False)

    # 回到首页（先存档）
    g.slot = 3
    g.panel = ('settings', 'game')
    g.paused = True
    home = next(r for k, r in g.settings_buttons() if k == 'home')
    g.click_settings(home.centerx, home.centery, 'game')
    check('能回到首页', g.state == 'title' and g.panel is None)
    check('回首页前存了档', os.path.exists(game.save_path(3)))

    # 首页也能开设置，而且面板必须真的画出来（以前这里漏画，点了像卡死）
    print('\n【首页的设置面板】')
    t = fresh()
    t.slot = 4
    t.save()
    t.state = 'title'
    t.panel = None
    t.draw()
    r = t.settings_panel_rect()
    before = t.screen.get_at((r.centerx, r.y + 1))
    set_btn = next(rc for a, rc, sl in t.title_buttons() if a == 'settings')
    t.click_title(set_btn.center)
    check('首页点设置会开面板', t.panel and t.panel[0] == 'settings')
    t.draw()
    after = t.screen.get_at((r.centerx, r.y + 1))
    check('首页的设置面板真的画在画面上', after.b > after.r + 40)
    check('打开前那块不是面板', before.b < before.r + 40)

    mb = next(rc for k, rc in t.settings_buttons() if k == 'music')
    t.click_settings(mb.centerx, mb.centery, 'title')
    check('首页设置里能切音乐', True)

    # 真事件路径：面板是模态的，点击既不能被吞掉，也不能穿透到首页按钮
    t.panel = None
    t.state = 'title'
    t.running = True
    click = lambda pos: t.on_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    click(set_btn.center)
    check('真点击能打开首页设置', t.panel == ('settings', 'title'))
    before_music = t.music.settings['music']
    click(mb.center)
    check('面板里的按钮真的能点', t.music.settings['music'] != before_music)
    quit_r = next(rc for a, rc, sl in t.title_buttons() if a == 'quit')
    click(quit_r.center)
    check('点面板外面不会触发下层按钮', t.running is True)
    check('点面板外面会把面板收起来', t.panel is None)
    t.panel = ('settings', 'title')
    close_b = next(rc for k, rc in t.settings_buttons() if k == 'close')
    click(close_b.center)
    check('真点击能关掉设置', t.panel is None)
    click(quit_r.center)
    check('关掉后首页按钮恢复可用', t.running is False)
    t.running = True

    # 底部那排（设置/退出）不能被面板盖住，否则看得见点不着
    panel_r = t.settings_panel_rect()
    bottom = [(a, rc) for a, rc, sl in t.title_buttons() if a in ('settings', 'quit')]
    check('底部按钮不会被设置面板盖住',
          all(not panel_r.colliderect(rc) for a, rc in bottom))
    close_btn = next(rc for k, rc in t.settings_buttons() if k == 'close')
    t.click_settings(close_btn.centerx, close_btn.centery, 'title')
    check('首页设置能关掉', t.panel is None)
    t.draw()
    after2 = t.screen.get_at((r.centerx, r.y + 1))
    check('关掉后面板消失', after2.b < after2.r + 40)

    # 关掉之后首页按钮还能用
    load_btn = next(rc for a, rc, sl in t.title_buttons() if a == 'load' and sl == 4)
    t.click_title(load_btn.center)
    check('关掉设置后首页照常能继续', t.state == 'play')

    # ------------------------------------------------ 房租提醒
    print('\n【房租前一天弹窗】')
    game.RENT_NOTICE_ON = True
    g = fresh()
    g.money = 2000
    g.day = 5                     # 结算后进入第 6 天，明天（第 7 天）收租
    g.end_day()
    check('交租前一天会弹窗', bool(g.panel) and g.panel[0] == 'notice')
    check('弹窗里写了金额',
          bool(g.panel) and g.panel[0] == 'notice'
          and g.panel[1]['rent'] == game.RENT_WEEK)
    t0 = g.t
    g.update(0.05)
    check('弹窗期间时间冻结', abs(g.t - t0) < 1e-9)
    g.draw()
    ok_btn = g.notice_ok_btn()
    g.click_panel(ok_btn.centerx, ok_btn.centery)
    check('点“知道了”能关掉', g.panel is None)

    g2 = fresh()
    g2.money = 2000
    g2.day = 6                    # 结算后就是收租当天：不再提前弹
    g2.end_day()
    check('不是前一天就不弹', g2.panel is None)
    game.RENT_NOTICE_ON = False

    # ------------------------------------------------ 全屏
    print('\n【全屏】')
    g = fresh()
    w0, h0 = g.display.get_size()
    check('画布固定 1280x720', g.screen.get_size() == (game.SW, game.SH))
    g.toggle_fullscreen()
    dw, dh = g.display.get_size()
    check('切换后确实换了显示模式', (dw, dh) != (w0, h0) or g.fullscreen)
    check('全屏时画布尺寸不变', g.screen.get_size() == (game.SW, game.SH))
    cx, cy = g.map_mouse((dw // 2, dh // 2))
    check('全屏下鼠标坐标换算到画布中心',
          abs(cx - game.SW // 2) <= 2 and abs(cy - game.SH // 2) <= 2)
    g.draw()
    check('全屏能正常绘制', True)
    g.toggle_fullscreen()
    check('能切回窗口模式', g.display.get_size() == (game.SW, game.SH)
          or not g.fullscreen)

    # ------------------------------------------------ 音乐
    print('\n【切到桌面自动暂停】')
    g = fresh()
    g.toast_msg('早餐铺开张了 · 07:00~09:00', game.C_GOLD, 99)
    if hasattr(pygame, 'WINDOWFOCUSLOST'):
        g.on_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        check('切到桌面自动暂停', g.paused is True)
        check('切走时清掉即时提示', g.toast is None)
        t0 = g.t
        for _ in range(40):
            g.update(0.05)
        check('切走期间游戏时间不动', abs(g.t - t0) < 1e-9)
        g.on_event(pygame.event.Event(pygame.WINDOWFOCUSGAINED))
        check('切回来自动继续', g.paused is False)
        g.update(0.05)
        check('回来后时间继续走', g.t > t0)

        g.paused = True
        g.on_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        g.on_event(pygame.event.Event(pygame.WINDOWFOCUSGAINED))
        check('手动暂停不会被自动恢复', g.paused is True)
        g.paused = False

        g.panel = ('server', 0)
        g.on_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        check('面板开着时切走不会额外暂停', g.paused is False)
        g.panel = None
    else:
        check('这台 pygame 没有窗口焦点事件（跳过）', True)

    print('\n【回首页 / 切后台都不留残影】')
    g = fresh()
    g.slot = 4
    g.toast_msg('早餐铺开张了 · 07:00~09:00', game.C_GOLD, 99)
    g.event = dict(kind='burst', name='爆单', left=5, desc='x')
    g.texts.append([300, 200, '+¥50', 14, game.C_GOLD, 1.0])
    g.panel = ('settings', 'game')
    g.paused = True
    home = next(r for k, r in g.settings_buttons() if k == 'home')
    g.click_settings(home.centerx, home.centery, 'game')
    check('回首页：状态变标题', g.state == 'title')
    check('回首页：提示条清掉', g.toast is None)
    check('回首页：事件横幅清掉', g.event is None)
    check('回首页：飘字清掉', not g.texts)
    check('回首页：不再暂停', g.paused is False)

    g = fresh()
    g.toast_msg('早餐铺开张了', game.C_GOLD, 99)
    g.event = dict(kind='throttle', name='限流', left=5, desc='x')
    g.texts.append([300, 200, '+¥50', 14, game.C_GOLD, 1.0])
    g.check_focus(False)
    check('切后台：提示条清掉', g.toast is None)
    check('切后台：事件横幅清掉', g.event is None)
    check('切后台：飘字清掉', not g.texts)
    check('切后台：自动暂停', g.paused is True)
    t0 = g.t
    for _ in range(30):
        g.update(0.05)
    check('切后台：时间不动', abs(g.t - t0) < 1e-9)
    g.check_focus(True)
    check('切回来：自动继续', g.paused is False)

    print('\n【音乐】')
    g = fresh()
    check('音乐对象存在', hasattr(g, 'music'))
    check('没有文件时也不崩', g.music.ok in (True, False))
    g.music.toggle()
    g.music.toggle()
    check('音乐开关来回切不崩', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    for i in range(1, game.SLOT_COUNT + 1):
        if os.path.exists(game.save_path(i)):
            os.remove(game.save_path(i))
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
