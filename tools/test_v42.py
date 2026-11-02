#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v42 自测：公寓早饭去早餐铺买 / 气象两趟 / 冰样三步 / 任务疲劳。

用法：python3 tools/test_v42.py
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


def at(g, hour):
    g.t = (hour - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 早饭
    print('\n【早饭】')
    g = game.Game()
    g.state = 'play'
    for st in g.stations:
        st.unlocked = st.subscribed = True
        st.quota = 900
    g.money = 9000
    g.warehouse['food'] = 5
    at(g, 6.7)
    g.update(0.05)
    check('公寓早饭不自己吃', g.warehouse['food'] == 5 and g.meals_today == 0)
    g.buy_breakfast()
    check('公寓早饭靠早餐铺：买一份算一顿', g.meals_today == 1)
    at(g, 8.1)
    g.update(0.05)
    check('窗口过了，早饭这顿结掉', 7 in g.meal_done)

    g2 = game.Game()
    g2.start_test_station()
    g2.warehouse['food'] = 5
    at(g2, 6.7)
    g2.update(0.05)
    check('科考站早饭还是自己吃', g2.warehouse['food'] == 4 and g2.meals_today == 1)

    # ------------------------------------------------ 气象（AI 去跑）
    print('\n【气象两趟】')
    def advance(g, cond, frames=3000):
        for _ in range(frames):
            g.update(0.05)
            if cond():
                return True
        return False

    g = game.Game()
    g.start_test_station()
    g.quest_day = g.day                 # 别让当天重置把时间改回随机
    g.weather = [0, 0]
    g.weather_at = [9.0, 9.5]           # 固定发布时间方便测试
    at(g, 8.5)
    g.update(0.05)
    check('发布时间没到就没有任务', g.weather == [0, 0])
    at(g, 9.1)
    g.update(0.05)
    check('到点发布第一趟', g.weather[0] == 1)
    check('派 AI 去采集', g.click_weather() is True)
    check('采集要花时间（不是秒完成）', g.weather[0] == 2)
    check('一趟走完（采集+上传）才拿到数据', advance(g, lambda: g.weather[0] == 3))
    check('第一趟已记完成', g.weather[0] == 3)

    at(g, 9.6)
    g.update(0.05)
    check('第一趟做完才发布第二趟', g.weather[1] == 1)
    rep0, m0 = g.rep, g.money
    g.quest_day_end()
    check('没交的气象要罚', g.rep < rep0 and g.money < m0)

    # ------------------------------------------------ 冰样（AI 去跑）
    print('\n【冰样主线】')
    g = game.Game()
    g.start_test_station()
    m0 = g.money
    check('派 AI 去采冰样', g.click_ice() is True)
    check('冰样进流程了', g.ice == 1)
    check('三步走完（采样→化验→上传）', advance(g, lambda: g.ice == 0))
    check('冰样奖金 ¥300', g.money >= m0 + 300)

    # ------------------------------------------------ 点房间也能用
    print('\n【点房间】')
    g = game.Game()
    g.start_test_station()
    g.warehouse['food'] = 0
    at(g, 10.2)
    g.update(0.05)
    def wait_idle(g, frames=3000):
        for _ in range(frames):
            if any(g.worker_available(x) for x in g.visible_stations()):
                return True
            g.update(0.05)
        return False

    wait_idle(g)
    g.quest_day = g.day
    g.weather = [1, 0]                  # 手动放出一个气象任务来测点击
    wait_idle(g)
    g.handle_click((game.WEATHER_RECT.centerx, game.WEATHER_RECT.centery))
    check('点气象室就派人去采', advance(g, lambda: g.weather[0] == 3))
    check('有人闲下来再派采冰', wait_idle(g))
    g.handle_click((game.AIRLOCK_RECT.centerx, game.AIRLOCK_RECT.centery))
    check('点气闸派人采冰（一路到上传）', advance(g, lambda: g.ice == 0))
    check('点实验室只提示流程', g.click_lab() is False)
    g.meal_done.update((8, 12, 18))     # 别让做饭把食材吃掉
    at(g, 9.5)                          # 9 点半：自动温室还没触发，手动点才会派
    g.warehouse['food'] = 0
    g.green_day = -1                    # 强制再派一次温室
    g.quest_last.pop('green', None)     # 清掉温室冷却
    qw = g.station_by_id('Qwen')
    qw.social_state = 'home'            # 直接让千问在工位待命，别被闲逛干扰
    qw.walk_path = []
    qw.nap = 0.0
    qw.quest = None
    qw.cooking = 0.0
    ok_green = False
    for _try in range(4):               # 偶尔被闲逛/做饭打断，重试几次
        g.green_day = -1
        g.quest_last.pop('green', None)
        qw.social_state = 'home'
        qw.walk_path = []
        qw.cooking = 0.0
        qw.quest = None
        g.panel = None
        g.click_greenhouse()
        if qw.quest is not None:
            ok_green = advance(g, lambda: g.warehouse['food'] >= 2)
            break
    check('点温室派人照顾', ok_green)
    g.panel = None
    g.handle_click((game.SERVER[0], game.SERVER[1]))
    check('点服务器能打开面板', g.panel is not None)
    check('服务器挪到主控室下半部分', game.SERVER[1] > 160)

    # ------------------------------------------------ 界面
    print('\n【界面】')
    g = game.Game()
    g.start_test_station()
    g.draw()
    check('站内 HUD 能画（含任务进度）', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
