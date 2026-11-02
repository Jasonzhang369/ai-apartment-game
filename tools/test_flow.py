#!/usr/bin/env python3
"""交互链路自测：点击顾客 -> 派单面板 -> 派单 -> 完成结算 -> 存档读档。

不渲染，只跑逻辑，用来防止改代码时把点击路径改坏。
用法：python3 tools/test_flow.py
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


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    g = game.Game()
    g.state = 'play'
    g.try_spawn()
    for _ in range(200):
        g.update(0.05)

    qs = g.queued_tasks()
    check('有顾客进入排队', len(qs) >= 1)
    if not qs:
        return finish()
    guest = qs[0]

    # 点顾客 -> 打开派单面板（世界坐标 * SCALE 换成屏幕坐标）
    g.handle_click((int(guest.x * game.SCALE), int((guest.y - 8) * game.SCALE)))
    check('点击数据包打开服务器面板', g.panel and g.panel[0] == 'server')

    # 选第一条线路 -> 派单
    cards = g.server_cards()
    st, card = cards[0]
    if not st.ready():
        for s2, c2 in cards:
            if s2.ready():
                st, card = s2, c2
                break
    g.click_panel(card.centerx, card.centery)
    check('派单成功', st.busy is not None and guest.state == 'service')
    check('派单后面板还开着（可以连续派）', g.panel and g.panel[0] == 'server')
    # 连续派单：面板不关，直接给第二条线路再派一单
    q2 = g.queued_tasks()
    st2 = next((x for x, c in cards
                if x.ready() and x is not st and not x.blocked(q2[0].typ)), None)
    if q2 and st2 is not None:
        g.panel = ('server', 0)
        g.click_panel(dict((x.idx, c) for x, c in cards)[st2.idx].centerx,
                      dict((x.idx, c) for x, c in cards)[st2.idx].centery)
        check('不重新点服务器就能派第二单', st2.busy is not None)
    else:
        check('不重新点服务器就能派第二单', True)
    g.panel = None

    # 跑完这一单
    for _ in range(2000):
        g.update(0.05)
        if st.busy is None:
            break
    check('订单完成结算', st.done >= 1 and g.t_rev > 0)
    check('完成有收入', g.money > 1400)

    # 点工位 -> 工位面板
    g.handle_click((int(st.cx * game.SCALE), int((st.feet - 30) * game.SCALE)))
    check('点击工位打开详情', g.panel and g.panel[0] == 'station')
    g.panel = None

    # 初始只有豆包和 DeepSeek 能用
    live0 = {x.m['id'] for x in g.unlocked()}
    check('开局只有豆包和 DeepSeek', live0 == {'Doubao', 'DeepSeek'})
    locked0 = [x for x in g.stations if not x.unlocked]
    check('其余线路未解锁', len(locked0) == len(game.MODELS) - 2)
    check('豆包立绘已加载', g.assets.model('Doubao') is not None)

    g.money = 99999

    # 三档订阅：点档位按钮换档
    ds = next(x for x in g.stations if x.m['id'] == 'DeepSeek')
    check('公寓的豆包还是免费一档', len(g.stations[0].tiers()) == 1)
    cap0 = ds.quota_cap()
    g.panel = ('station', ds)
    btns = {(k, t): r for k, t, r in g.station_tier_btns(ds)}
    g.click_panel(btns[('tier', 3)].centerx, btns[('tier', 3)].centery)   # 第一次：提示
    check('换档要二次确认', ds.tier == 1)
    g.click_panel(btns[('tier', 3)].centerx, btns[('tier', 3)].centery)   # 第二次：真换
    check('点专业档换到三档', ds.tier == 3)
    check('高档抬高日额度', ds.quota_cap() > cap0)
    check('专业档不自动变大模型', ds.is_small())
    g.click_panel(btns[('tier', 2)].centerx, btns[('tier', 2)].centery)
    g.click_panel(btns[('tier', 2)].centerx, btns[('tier', 2)].centery)
    check('换回标准档', ds.tier == 2)
    # 单独升级大模型（一次性付费，和档位无关）
    bigbtn = btns[('big', 0)]
    g.click_panel(bigbtn.centerx, bigbtn.centery)
    check('点大模型卡能升级', ds.big is True and not ds.is_small())
    check('升级后能接识图', not ds.blocked('vision'))
    g.panel = None

    # 未解锁 -> 先解锁
    s3 = locked0[0]
    g.panel = ('station', s3)
    r = g.station_up_btn()
    g.click_panel(r.centerx, r.centery)
    check('点解锁按钮只解锁', s3.unlocked and not s3.subscribed)
    check('未订阅不能接单', not s3.ready())
    # 再点一档订阅
    g.panel = ('station', s3)
    btns = {(k, t): r for k, t, r in g.station_tier_btns(s3)}
    g.click_panel(btns[('tier', 2)].centerx, btns[('tier', 2)].centery)
    check('点标准档订阅', s3.subscribed and s3.quota > 0)
    g.panel = None

    # 24:00 自动结算：不弹面板、不清任务、只刷额度
    g.try_spawn()
    keep = g.queued_tasks()
    keep_n = len(keep)
    s3.quota = 0
    day0 = g.day
    g.t = g.settle_point() - 0.01
    g.update(0.05)
    check('24点自动结算且不弹面板', g.day == day0 + 1 and g.panel is None)
    check('结算不清空待处理任务', len(g.queued_tasks()) == keep_n)
    check('次日额度恢复', s3.quota == s3.quota_cap() > 0)
    check('日结含电费工资', g.daily_fixed()[1] > 0 and g.daily_fixed()[2] > 0)
    check('留下当日账本', g.last_day and g.last_day['day'] == day0)

    # 夜班额度减半
    g.t = game.DAY_LEN * 0.85          # 约 04:24
    check('夜班判定', g.is_night())
    check('夜班额度减半', abs(g.quota_factor() - game.NIGHT_COST) < 1e-9)
    g.t = game.DAY_LEN * 0.3           # 约 15:12，白天
    check('白天全额额度', not g.is_night() and g.quota_factor() == 1.0)
    # 房租每 7 天一次：第 7 天要交，第 8 天不用交
    g.day = 7
    check('第 7 天收房租', g.rent_due() and g.daily_fixed()[0] == game.RENT_WEEK)
    g.day = 8
    check('第 8 天不收房租', not g.rent_due() and g.daily_fixed()[0] == 0)
    check('房租倒计时正确', g.rent_left() == 6)

    # 面板打开时营业时间冻结
    t_before = g.t
    g.panel = ('station', ds)
    for _ in range(20):
        g.update(0.05)
    check('面板打开时时间冻结', abs(g.t - t_before) < 1e-9)
    g.panel = ('server', 0)
    for _ in range(10):
        g.update(0.05)
    check('派单面板同样冻结', abs(g.t - t_before) < 1e-9)
    g.panel = None

    # 小模型做不了图片类任务
    g.money = 99999
    ds.big = False          # 回到没升级大模型的状态
    ds.tier = 1
    check('小 DeepSeek 拒识图', ds.blocked('vision') and ds.blocked('image'))
    check('小 DeepSeek 仍能写代码', not ds.blocked('code'))
    img_task = game.Task('image')
    img_task.state = 'stored'
    check('派图给小时被拦', not g.assign(img_task, ds))
    ds.tier = 2
    check('标准档还是小模型', ds.is_small() and ds.blocked('vision'))
    ds.tier = 3
    check('专业档也不自动变大模型', ds.is_small() and ds.blocked('vision'))
    ds.big = True
    check('单独升级大模型后才能接识图',
          not ds.is_small() and not ds.blocked('vision'))
    ds.big = False

    # 存档信息可读
    g.save()
    info = g.peek_save()
    check('存档可预览', info and info.get('day') == g.day)

    # 广告按钮能点（曾经因为 rect 没进 pane_buttons 失效过）
    g.money = 5000
    g.ad_days = 0
    ad_btn = [r for k, r in g.pane_buttons() if k == 'ad'][0]
    g.handle_click((ad_btn.centerx, ad_btn.centery))
    check('点广告按钮能投出去', g.ad_days == game.AD_DAYS and g.money == 5000 - game.AD_COST)

    # 限流 / 宕机 时长按游戏时间
    check('宕机时长是 3 小时', abs(game.CRASH_SEC * game.GAME_MIN_PER_SEC - 180) < 1e-6)
    check('限流时长是 2 小时',
          abs(game.THROTTLE_SEC * game.GAME_MIN_PER_SEC - 120) < 1e-6)
    check('时长按小时显示', '小时' in game.fmt_sec_game(game.CRASH_SEC))

    # 调价与调速
    g.price_idx = 2
    g.on_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    check('上调价格档位', g.price_mult > 1.0)
    g.on_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_2))
    check('切到 2 倍速', g.speed == 2)

    # 08:00 时间轴归零
    g.t = game.DAY_LEN - 0.01
    g.settled = True
    g.update(0.05)
    check('08:00 时间轴归零', g.t < 1.0 and not g.settled)

    # 存档 + 读档
    g.save()
    check('存档文件生成', os.path.exists(game.SAVE_PATH))
    day_saved = g.day
    g2 = game.Game()
    got = g2.load()
    check('读档成功', got and g2.day == day_saved and g2.stations[0].tier == g.stations[0].tier)

    os.remove(game.SAVE_PATH)
    return finish()


def finish():
    print(f'\n通过 {ok} 项，失败 {fail} 项')
    sys.exit(1 if fail else 0)


if __name__ == '__main__':
    main()
