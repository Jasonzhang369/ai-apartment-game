#!/usr/bin/env python3
"""自动化平衡测试：模拟一个"还算会玩"的玩家跑完 30 天，打印每日账本。

用来检查数值曲线是否合理、有没有运行时崩坏。不渲染画面。

用法：python3 tools/sim.py
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

DT = 0.05


def best_station(g, guest):
    best, best_net = None, -1e9
    for st in g.stations:
        if not st.ready() or st.blocked(guest.typ):
            continue
        q = st.quality(guest.typ)
        match = guest.typ in st.m['tags']
        star = g.rate_est(q, match)
        rev = guest.budget * g.price_mult * (game.REV_BASE + star * game.REV_PER_STAR)
        cost = guest.w * st.unit_cost()
        net = rev - cost
        # 略微偏好快线路（同净利时少占机位）
        score = net + (5.0 / (guest.w / st.spd()))
        if score > best_net:
            best, best_net = st, score
    return best


def ensure_port(g, st):
    """需要出口端口的线路：没有就买/装一个。"""
    need = st.m.get('need')
    if not need or st.port_ok():
        return None
    gid = 'vpn_enc' if need == 'vpn_enc' else 'vpn'
    if g.bag_count(gid) > 0:
        g.equip_gear(st, gid)
        return f'{st.m["name"]} 装端口'
    gear = next(x for x in game.GEAR if x['id'] == gid)
    if g.money >= gear['price'] + 400:
        g.buy_gear(gear)
        g.equip_gear(st, gid)
        return f'{st.m["name"]} 买 {gid}'
    return None


def strategy(g):
    """结算后花钱：先换高档订阅，再补线路，再升网关，最后广告。"""
    # 0) 有长期合同报价就签（模拟玩家会接）
    if getattr(g, 'contract_offer', None):
        g.accept_contract()
        return '签长期合同'
    # 0.5) 千问做饭要食材：常备 2 份
    if g.bag_count(game.FOOD_ID) < 2 and g.money > game.FOOD_PRICE * 6:
        g.buy_food()
        return '买食材'
    # 0.6) 先保证已订阅的线路有出口端口，否则等于白买
    for st in g.stations:
        if st.subscribed and not st.port_ok():
            act = ensure_port(g, st)
            if act:
                return act
    # 1) 先补线路（扩容最要紧：电闸容量有限，线路太少接不下单）
    live = [x for x in g.stations if x.subscribed]
    if len(live) < 5:
        for st in sorted(g.stations, key=lambda x: x.m.get('unlock', 0)):
            if st.subscribed:
                continue
            cost = 0 if st.unlocked else st.m.get('unlock', 0)
            ts = st.tiers()
            sub7 = ts[min(1, len(ts) - 1)][1] * game.SUB_DAYS
            if g.money >= cost + sub7 + 400:
                if not st.unlocked:
                    g.unlock_station(st)
                    return f'解锁 {st.m["name"]}'
                g.subscribe(st, 2)
                return f'订阅 {st.m["name"]} 标准档 7 天'
            break

    # 2) 有富余就把主要线路升到标准/专业档（额度是瓶颈）
    for st in sorted(g.stations, key=lambda x: -x.quota_cap() if x.quota_cap() > 0 else 0):
        if not st.subscribed or len(st.tiers()) < 2 or st.tier >= len(st.tiers()):
            continue
        nxt = st.tier + 1
        cost = st.tiers()[nxt - 1][1] * game.SUB_DAYS    # 一次买 7 天，当场付清
        # 专业档很贵：只有钱特别充裕时才上
        if nxt >= 3 and g.money < 3000:
            continue
        if g.money >= cost * 1.6:
            g.subscribe(st, nxt)
            return f'{st.m["name"]} 换{st.tier_name()}档'

    # 3) 网关：更大的单、更快的来单
    if g.gw_lv < 5 and g.money > 1600 + g.gw_up_cost():
        g.money -= g.gw_up_cost()
        g.gw_lv += 1
        return f'网关 Lv{g.gw_lv}'

    # 3.5) 快到期的订阅先续上（别让线路停工）
    for st in g.stations:
        if (st.subscribed and not st.forever and st.sub_days <= 1
                and len(st.tiers()) >= 2):
            cost = st.tiers()[st.tier - 1][1] * game.SUB_DAYS
            if g.money >= cost * 2:
                g.subscribe(st, st.tier)
                return f'{st.m["name"]} 续费'

    # 3.6) 快烧的线买散热扇（一次性装备，永久降热）
    for st in g.stations:
        if (st.subscribed and not st.has_gear('fan')
                and st.temp > game.TEMP_LIMIT * 0.7 and g.money > 3000):
            g.buy_gear(next(x for x in game.GEAR if x['id'] == 'fan'))
            g.equip_gear(st)
            return f'{st.m["name"]} 买散热扇'

    # 4) 全员休息日：大家都累了就全班一起休一天
    live = [st for st in g.stations if st.subscribed and not st.no_fatigue]
    if live and not g.rest_day:
        tired = sum(1 for st in live if st.fatigue > 0.55)
        if tired >= max(1, len(live) // 2) and not any(st.jobs() for st in live):
            g.take_rest_day()
            return '全员休息一天'

    # 5) 一次性升级大模型（DeepSeek / ChatGPT）
    for st in g.stations:
        if st.has_big() and not st.big and g.money > 5000:
            g.upgrade_big(st)
            return f'{st.m["name"]} 升级大模型'

    # 6) 广告
    if g.ad_days == 0 and g.money > 900:
        g.buy_ad()
        return '投广告'
    return None


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    g = game.Game()
    g.state = 'play'
    g.price_idx = 2

    last_day = g.day
    frames = 0
    max_frames = int((game.TOTAL_DAYS + 2) * game.DAY_LEN / DT)
    while frames < max_frames:
        g.update(DT)
        frames += 1
        if g.state == 'over':
            break
        # 派单（不超过电闸容量，否则会跳闸）
        busy = sum(1 for st in g.stations if st.busy)
        cap = g.breaker_cap()
        # 只派能立刻上手的：手上的活别压太多单，否则会超时撤单
        for guest in g.queued_tasks():
            if busy >= cap:
                break
            st = best_station(g, guest)
            if not st:
                continue
            # 别把线压满：留点余量，否则单子都堵在队列里等着超时
            if len(st.jobs()) >= 1 and busy + 1 >= cap:
                continue
            if g.assign(guest, st):
                busy += 1
        # 队列快满了就让网关少吐单（否则全是撤单）
        if len(g.queued_tasks()) >= len(game.TASK_SLOTS):
            g.spawn_timer = max(g.spawn_timer, 6.0)
        # 24:00 自动结算：拿 last_day 打账本
        if g.day != last_day:
            d = g.last_day or {}
            act = strategy(g)
            print(f'第 {d.get("day", 0):2d} 天 | 营收 {d.get("rev", 0):6.0f} | '
                  f'净利 {d.get("net", 0):6.0f} | 资金 {g.money:7.0f} | '
                  f'声誉 {g.rep:5.1f} | 单 {d.get("orders", 0):2d} | '
                  f'超时 {d.get("expired", 0):2d} | 过热 {d.get("crashes", 0)} | '
                  f'在线 {len(g.unlocked())} | {act or ""}')
            last_day = g.day

    print()
    if g.state == 'over' and g.panel and g.panel[0] == 'over':
        d = g.panel[1]
        print('结局:', '破产' if d['bankrupt'] else '撑满 30 天',
              f'第 {d["day"]} 天，资金 {d["money"]:.0f}，声誉 {g.rep:.1f}')
    lv = ' '.join(f'{s.m["name"]}:{s.tier_name()}' for s in g.unlocked())
    print('在线线路:', lv)
    print('总接单:', sum(s.done for s in g.stations))


if __name__ == '__main__':
    main()
