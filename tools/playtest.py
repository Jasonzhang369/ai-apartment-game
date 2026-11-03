#!/usr/bin/env python3
"""自动试玩：跑 N 天，按策略经营，定期截图，输出报告数据。

用法：
  python3 tools/playtest.py --days 60 --strategy steady --shots 5
策略：steady（稳健）/ expand（扩张）/ idle（摆烂）
截图写到 /tmp/play（用完可删）。
"""
import argparse, os, sys, time, json

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ['AIHUB_SAVE'] = '/tmp/playtest_save.json'
os.environ['AIHUB_SETTINGS'] = '/tmp/playtest_settings.json'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pygame, game                      # noqa: E402

game.INTRO_ON = False
game.RENT_NOTICE_ON = False

ORDER = ['Qwen', 'GLM', 'Grok', 'Gemini', 'ChatGPT', 'Claude', 'Kimi', 'Hunyuan']


def policy(g, strategy, tick):
    """每 tick 次循环执行一次的经营策略。"""
    g.auto_dispatch = strategy != 'idle'
    if strategy == 'idle':
        return
    live = 4 if strategy == 'steady' else len(ORDER)
    for sid in ORDER[:live]:
        st = g.station_by_id(sid)
        if st and not st.unlocked and g.money > st.m.get('unlock', 0) + (900 if strategy == 'steady' else 400):
            g.unlock_station(st)
            break
    for st in g.stations:
        if st.unlocked and not st.subscribed and g.money > (600 if strategy == 'steady' else 250):
            g.pick_tier(st, 0)
            break
    if g.rewards:
        g.claim_rewards()
    for sid in ('DeepSeek', 'ChatGPT'):
        st = g.station_by_id(sid)
        if st and st.has_big() and not st.big and g.money > 2200:
            g.upgrade_big(st)
            break
    if g.scene == 'apartment' and g.can_relocate() and strategy == 'expand':
        g.relocate()
    if g.scene == 'station' and g.warehouse['food'] < 4 and g.money > 400:
        g.pending_supply += ['food']
    if g.loan > 0 and g.money > g.loan * 1.6:
        g.repay_loan()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=60)
    ap.add_argument('--strategy', default='steady')
    ap.add_argument('--shots', type=int, default=5)
    ap.add_argument('--speed', type=float, default=1.0)
    args = ap.parse_args()
    outdir = '/tmp/play'
    os.makedirs(outdir, exist_ok=True)
    pygame.init(); pygame.display.set_mode((game.SW, game.SH))
    g = game.Game(); g.state = 'play'
    g.money = 2200; g.rep = 40
    rows = []; t0 = time.time(); shot_days = set(range(args.shots, args.days + 1, args.shots))
    try:
        while g.day <= args.days and time.time() - t0 < 180:
            for _ in range(30):
                g.update(args.speed)
            policy(g, args.strategy, 0)
            if g.panel:
                g.click_panel(640, 360)
            if g.day in shot_days:
                shot_days.discard(g.day)
                g.draw(); pygame.image.save(g.screen, f'{outdir}/d{g.day:02d}.png')
            if g.state != 'play':
                break
    except Exception:
        import traceback; traceback.print_exc()
    print(json.dumps(dict(days=g.day, scene=g.scene, money=round(g.money),
                          loan=round(g.loan), rep=round(g.rep),
                          worth=round(g.net_worth()), sec=round(time.time() - t0, 1)),
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
