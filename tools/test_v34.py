#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v34 自测：角色面板放大重排 / 关系面板独立。

用法：python3 tools/test_v34.py
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


def zero_bonds(g):
    """把初始好感清零，方便断言"只有我设置的那几对"。"""
    for k in list(g.bonds):
        g.bonds[k] = 0.0


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))

    # ------------------------------------------------ 角色面板
    print('\n【角色面板】')
    g = fresh()
    ds = by_id(g, 'DeepSeek')
    r = g.station_panel_rect()
    check('面板放大了（760×640）', (r.w, r.h) == (760, 640))
    check('面板没超出画面', r.x >= 0 and r.y >= 0 and r.right <= game.SW and r.bottom <= game.SH)
    check('装备栏还是三格', len(g.station_gear_slots(ds)) == game.MAX_GEAR)
    for gid, sr in g.station_gear_slots(ds):
        check('装备格在面板里', r.contains(sr)) if gid is None else None
    check('重置卡按钮在面板内', r.contains(g.station_reset_btn()))
    check('暂停/放弃按钮在面板内',
          r.contains(g.station_job_btn()) and r.contains(g.station_abandon_btn()))
    tiers = g.station_tier_btns(ds)
    check('订阅卡都在面板内', all(r.contains(b) for _, _, b in tiers))
    check('订阅卡不互相压', all(not tiers[i][2].colliderect(tiers[i + 1][2])
                                for i in range(len(tiers) - 1)))
    # 右栏数据行（最多 9 行，24px）不会顶到关系按钮
    rows_bottom = r.y + 162 + 8 * 24 + 14
    check('数据行和关系按钮不重叠', rows_bottom <= g.station_relations_btn().y)

    # 点「人缘关系」→ 打开独立面板
    g.panel = ('station', ds)
    btn = g.station_relations_btn()
    g.click_panel(btn.centerx, btn.centery)
    check('点关系按钮打开关系面板',
          g.panel is not None and g.panel[0] == 'relations')
    check('记住从哪来的', g.relations_back == ('station', ds))
    g.draw()
    check('关系面板能画', True)

    # 关闭回工位面板
    close = g.relations_buttons()[0][1]
    g.click_panel(close.centerx, close.centery)
    check('关闭后回到工位面板',
          g.panel is not None and g.panel[0] == 'station' and g.panel[1] is ds)

    # ------------------------------------------------ 关系数据
    print('\n【关系内容】')
    zero_bonds(g)
    gm = by_id(g, 'Gemini')
    gl = by_id(g, 'GLM')
    qw = by_id(g, 'Qwen')
    g.set_bond(gm, gl, 0.9)
    g.set_bond(gm, qw, 0.3)
    rows = g.relation_rows()
    check('只列出有关系的组合', len(rows) == 2)
    check('按默契从高到低', rows[0][2] >= rows[1][2])
    check('关系面板里能看到名字对', {rows[0][0].m['id'], rows[0][1].m['id']} == {'Gemini', 'GLM'})
    check('没聊过的人不在列表里', all('DeepSeek' not in (a.m['id'], b.m['id'])
                                      for a, b, v in rows))
    g.panel = ('relations', None)
    g.draw()
    check('有内容时也能画', True)

    # 空状态
    g2 = fresh()
    zero_bonds(g2)
    check('没聊过天时是空列表', g2.relation_rows() == [])
    g2.panel = ('relations', None)
    g2.draw()
    check('空状态能画', True)

    # ESC 关闭关系面板
    g3 = fresh()
    gm3 = by_id(g3, 'Gemini')
    g3.panel = ('station', gm3)
    g3.click_panel(g3.station_relations_btn().centerx, g3.station_relations_btn().centery)
    g3.on_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0,
                                   unicode='', scancode=0))
    check('ESC 也回到工位面板', g3.panel and g3.panel[0] == 'station')

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
