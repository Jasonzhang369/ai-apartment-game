#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v35 自测：初始好感矩阵 / 好感涨得慢 / 合不来不搭话 /
午饭晚饭回疲劳变少 / 服务器随时能开且能看到合同。

用法：python3 tools/test_v35.py
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


def fresh():
    g = game.Game()
    g.state = 'play'
    for st in g.stations:
        st.unlocked = st.subscribed = True
        st.quota = 900
    return g


def by_id(g, mid):
    return next(s for s in g.stations if s.m['id'] == mid)


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 初始好感
    print('\n【初始好感】')
    g = fresh()
    cg, gr, cl, ds = by_id(g, 'ChatGPT'), by_id(g, 'Grok'), by_id(g, 'Claude'), by_id(g, 'DeepSeek')
    check('ChatGPT 和 Grok 是 -50', abs(g.bond(cg, gr) + 0.50) < 1e-9)
    check('Claude 和 ChatGPT 是 20', abs(g.bond(cl, cg) - 0.20) < 1e-9)
    check('Claude 和 DeepSeek 是 50', abs(g.bond(cl, ds) - 0.50) < 1e-9)
    fixed = {tuple(sorted(k)) for k in game.INIT_BONDS}
    special = {'DeepSeek', 'Claude', 'ChatGPT', 'Grok'}
    others = [v for k, v in g.bonds.items()
              if k not in fixed and not (special & set(k))]
    check('其它组合初始 0~10%（DeepSeek/Claude 与 GPT/Grok 单独规则）', all(0 <= v <= 0.10 for v in others))
    n = len(g.stations)
    check('每对都有初始好感', len(g.bonds) == n * (n - 1) // 2)

    # 合不来：不主动搭话
    gm, gl = by_id(g, 'Gemini'), by_id(g, 'GLM')
    g.set_bond(cg, gr, -0.5)
    cg.px, cg.feet = 500, 400
    gr.px, gr.feet = 530, 402
    check('好感为负不算面对面', not g.can_chat(cg, gr, 60))
    cg.social_state = gr.social_state = 'walk'
    g.update_encounters(0.05)
    check('路上遇到也不搭话', cg.social_state == 'walk' and gr.social_state == 'walk')
    check('不会专门去找合不来的人',
          all(g.pick_partner(gr) is not cg for _ in range(30)))
    check('关系面板会列出负数', any(v < 0 for a, b, v in g.relation_rows(30)))

    # 好感涨得慢
    g = fresh()
    g.set_bond(gm, gl, 0.2)
    g.begin_chat(gm, gl)
    check('聊一次只涨 10%', abs(g.bond(gm, gl) - 0.30) < 1e-9)

    # ------------------------------------------------ 午饭晚饭
    print('\n【午饭晚饭】')
    check('回疲劳降到 6%', abs(game.MEAL_FATIGUE - 0.06) < 1e-9)
    check('加速不变', abs(game.MEAL_BUFF - 0.08) < 1e-9)
    g = fresh()
    g.money = 9999
    qw = by_id(g, 'Qwen')
    g.buy_food()
    for st in g.stations:
        st.fatigue = 0.6
    g.t = (12 - game.HOUR_START) / game.DAY_HOURS * game.DAY_LEN + 0.2
    g.update(0.05)
    qw.walk_path = []
    qw.cooking = 0.01
    g.update_cooking(qw, 0.05)
    check('公寓吃一顿回 20%（6% 是科考站规则）',
          all(abs(st.fatigue - 0.4) < 1e-6 for st in g.stations
              if st.unlocked and not st.no_fatigue))

    # ------------------------------------------------ 服务器随时能开
    print('\n【服务器】')
    g = fresh()
    g.tasks.clear()
    g.handle_click((game.SERVER[0], game.SERVER[1]))
    check('没任务也能点开服务器', g.panel is not None and g.panel[0] == 'server')
    g.draw()
    check('没任务的服务器能画', True)
    g.contract = dict(typ='code', left=4, need=2, today=1, reward=600)
    g.draw()
    check('服务器里能看到合同', True)
    # 合同信息块不压任务行
    r = g.server_panel_rect()
    rows_bottom = r.y + 84 + 2 * 74 + 66
    check('合同块在任务行下面', rows_bottom <= r.y + 330)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
