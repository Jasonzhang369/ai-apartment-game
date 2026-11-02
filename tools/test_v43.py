#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v43 自测：科考任务放进服务器面板，像派单一样点任务再点人。

用法：python3 tools/test_v43.py
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


def advance(g, cond, frames=2400):
    for _ in range(frames):
        g.update(0.05)
        if cond():
            return True
    return False


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    print('\n【服务器里的科考任务】')
    g = game.Game()
    g.start_test_station()
    g.t = (10.2 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g.quest_day = g.day
    g.weather = [1, 0]                 # 手动放出一个气象任务
    g.update(0.05)
    g.panel = ('server', 0)
    btns = {k: b for k, n, o, h, b in g.quest_sel_rects()}
    check('面板里有三个科考任务', set(btns) == {'weather', 'ice', 'green'})
    check('任务条在面板里', all(g.server_panel_rect().contains(b) for b in btns.values()))

    g.click_panel(btns['weather'].centerx, btns['weather'].centery)
    check('点任务会选中', g.quest_sel == 'weather')

    cards = {st.m['id']: r for st, r in g.server_cards()}
    target = next(x for x in ('GLM', 'ChatGPT', 'Gemini', 'Kimi')
                  if g.worker_available(g.station_by_id(x)))
    g.click_panel(cards[target].centerx, cards[target].centery)
    st = g.station_by_id(target)
    check('点人就把任务派出去了', bool(st.quest) and st.quest['kind'].startswith('weather'))
    check('路线是 气象室→主控台', [l[0] for l in st.quest['legs']] == ['WEATHER', 'CONSOLE'])
    check('派出后清掉选中', g.quest_sel is None)

    g.panel = None                     # 面板开着时间会冻住，关掉才动
    check('派人去采要花时间', g.weather[0] == 2)
    check('一趟走完才拿到数据（含上传）', advance(g, lambda: g.weather[0] == 3))

    # 选中的任务在面板里能重复用
    g.panel = ('server', 0)
    btns = {k: b for k, n, o, h, b in g.quest_sel_rects()}
    g.click_panel(btns['ice'].centerx, btns['ice'].centery)
    check('切到冰样任务', g.quest_sel == 'ice')
    cards = {s.m['id']: r for s, r in g.server_cards()}
    tgt = next(x for x in ('DeepSeek', 'Qwen', 'GLM', 'ChatGPT')
               if g.worker_available(g.station_by_id(x)))
    g.click_panel(cards[tgt].centerx, cards[tgt].centery)
    check('冰样任务派人去采', g.station_by_id(tgt).quest is not None
          and g.station_by_id(tgt).quest['kind'] == 'ice')

    # ------------------------------------------------ 两种选中互斥
    print('\n【任务 / 科考任务互斥】')
    g = game.Game()
    g.start_test_station()
    g.t = (10.2 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN
    g.update(0.05)
    g.tasks.clear()
    for _ in range(2):
        t = game.Task('chat')
        t.state = 'stored'
        t.w = 60
        g.tasks.append(t)
    g.panel = ('server', 0)
    btns = {k: b for k, n, o, h, b in g.quest_sel_rects()}
    rows = g.task_rows()
    check('有派单任务可选', len(rows) >= 1)
    g.click_panel(btns['ice'].centerx, btns['ice'].centery)
    check('先选科考任务', g.quest_sel == 'ice')
    g.click_panel(rows[0][1].centerx, rows[0][1].centery)
    check('再点派单任务会取消科考任务', g.quest_sel is None)
    cards = {st.m['id']: r for st, r in g.server_cards()}
    tgt = next(x for x in ('GLM', 'Qwen', 'ChatGPT', 'Gemini')
               if g.worker_available(g.station_by_id(x)))
    g.click_panel(cards[tgt].centerx, cards[tgt].centery)
    st = g.station_by_id(tgt)
    check('这时点人派的是派单任务', st.busy is rows[0][0] and st.quest is None)

    # 反过来：选了科考任务，点人不会接派单
    g.panel = ('server', 0)
    g.green_day = -1                     # 让温室任务今天还能派
    g.click_panel(btns['green'].centerx, btns['green'].centery)
    cards = {x.m['id']: r for x, r in g.server_cards()}
    tgt2 = next(x for x in ('Kimi', 'Hunyuan', 'DeepSeek', 'Gemini')
                if g.worker_available(g.station_by_id(x)))
    g.click_panel(cards[tgt2].centerx, cards[tgt2].centery)
    st2 = g.station_by_id(tgt2)
    check('选了科考任务时点人只派任务', st2.quest is not None and st2.busy is None)

    # 关面板清选择
    g.panel = ('server', 0)
    g.quest_sel = 'ice'
    g.click_panel(g.close_btn().centerx, g.close_btn().centery)
    check('关面板清掉科考任务选择', g.quest_sel is None and g.panel is None)

    # 选中状态下也能画（之前这里解包错了会崩）
    g.panel = ('server', 0)
    g.quest_sel = 'weather'
    g.draw()
    check('选中科考任务时面板能画', True)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
