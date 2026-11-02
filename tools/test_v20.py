#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v20 自测：三档订阅 / 重置卡 / 限流中温度冻结 / 滚轮缩放与右键拖动 / 满意度。

用法：python3 tools/test_v20.py
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


def give_job(g, st, w=100.0):
    t = game.Task('code')
    t.w = w
    t.state = 'stored'
    g.tasks.append(t)
    st.unlocked = st.subscribed = True
    st.quota = 400
    g.assign(t, st)
    return t


def main():
    pygame.init()
    pygame.display.set_mode((game.SW, game.SH))
    if os.path.exists(game.SAVE_PATH):
        os.remove(game.SAVE_PATH)

    # ------------------------------------------------ 三档订阅
    print('\n【三档订阅】')
    g = fresh()
    names = [(s.m['name'], len(s.tiers())) for s in g.stations]
    check('每条线路都有订阅档位', all(n >= 1 for _, n in names))
    check('公寓的豆包是免费一档', dict(names)['豆包'] == 1)
    check('其余线路都是三档', all(n == 3 for nm, n in names if nm != '豆包'))
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    check('DeepSeek 免费开局且已订阅基础档',
          ds.subscribed and ds.tier == 1 and ds.tier_price() == 0)
    check('基础档额度 210', ds.quota_cap() == 210)
    check('Qwen 未订阅时额度为 0',
          next(s for s in g.stations if s.m['id'] == 'Qwen').quota == 0)

    g.money = 5000
    glm = next(s for s in g.stations if s.m['id'] == 'GLM')
    g.unlock_station(glm)
    money0 = g.money
    g.subscribe(glm, 3)
    check('换到专业档', glm.tier == 3 and glm.tier_name() == '专业')
    check('专业档 ¥115/天', glm.tier_price() == 115)
    check('当场付清 7 天', abs((money0 - g.money) - 115 * game.SUB_DAYS) < 1e-6)
    check('订阅还剩 7 天', glm.sub_days == game.SUB_DAYS)
    check('日结不再扣订阅费（已预付）', g.daily_fixed()[3] == 0)
    g.subscribe(glm, 1)
    check('也能换回低档', glm.tier == 1 and glm.tier_price() == 33)

    # DeepSeek 升级大模型：和档位无关的一次性购买
    g.subscribe(ds, 3)
    check('订阅专业档不会自动变大模型', ds.is_small() and ds.blocked('vision'))
    money1 = g.money
    g.upgrade_big(ds)
    check('单独升级大模型花了钱', abs((money1 - g.money) - 1200) < 1e-6)
    check('升级后不再是��模型', not ds.is_small())
    check('升级后能接识图画图', not ds.blocked('vision') and not ds.blocked('image'))
    check('升级后质量仍低于旗舰线',
          ds.quality('chat') < next(x for x in g.stations
                                   if x.m['id'] == 'Claude').quality('chat'))
    check('升级后 DeepSeek 立绘换成小图', g.assets.sprite_id(ds) == 'DeepSeekChan')
    ds.big = False
    check('没升级的 DeepSeek 用大图', g.assets.sprite_id(ds) == 'DeepSeek')
    gpt = next(x for x in g.stations if x.m['id'] == 'ChatGPT')
    check('ChatGPT 小模型用小图（不动）', g.assets.sprite_id(gpt) == 'MiniGPT')
    gpt.big = True
    check('ChatGPT 大模型用大图（不动）', g.assets.sprite_id(gpt) == 'ChatGPT')
    gpt.big = False
    check('ChatGPT 小模型就能接识图画图',
          not gpt.blocked('vision') and not gpt.blocked('image'))

    # 旧存档迁移
    g.save()
    info = g.peek_save()
    check('存档记录的是档位', 'tier' in info['st'][0])

    # ------------------------------------------------ 重置卡
    print('\n【重置卡】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    give_job(g, ds)
    ds.temp = 88.0
    ds.limited = True
    ds.strain = 1.0
    ds.quota = 12.0
    g.money = 1000
    rep0 = g.rep
    price = game.reset_price(ds.m)
    check('买重置卡成功', g.buy_reset_card(ds) is True)
    check('扣的钱是按线路定价的', abs(g.money - (1000 - price)) < 1e-6)
    check('卡进了背包', g.bag_count('reset:DeepSeek') == 1)
    check('按线路定价：Claude 比 DeepSeek 贵',
          game.reset_price(next(s for s in g.stations if s.m['id'] == 'Claude').m) > price)
    check('用掉一张', g.use_reset_card(ds) is True)
    check('用完之后背包里没了', g.bag_count('reset:DeepSeek') == 0)
    check('温度不受重置卡影响（仍是被限流时的温度）',
          abs(ds.temp - 88.0) < 0.5)
    check('限流解除', ds.limited is False)
    check('压力清零', ds.strain == 0.0)
    check('额度补满', ds.quota == ds.quota_cap())
    check('声誉不受影响', abs(g.rep - rep0) < 1e-6)
    check('手上的活还在继续', ds.busy is not None)
    g.money = 10
    check('钱不够买不到', g.buy_reset_card(ds) is False and g.money == 10)
    check('没钱也不会凭空多出卡', g.bag_count('reset:DeepSeek') == 0)

    # ------------------------------------------------ 订阅 7 天预付
    print('\n【订阅：7 天预付，到期停工】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    g.money = 5000
    money0 = g.money
    g.subscribe(ds, 2)
    check('先付 7 天的钱', abs((money0 - g.money) - 35 * game.SUB_DAYS) < 1e-6)
    check('订阅期 7 天', ds.sub_days == game.SUB_DAYS)
    for i in range(game.SUB_DAYS - 1):
        g.end_day()
    check('还剩 1 天时仍然在跑', ds.subscribed and ds.sub_days == 1)
    g.end_day()
    check('到期后停工', ds.subscribed is False and ds.quota == 0)
    check('到期后不能再接单', ds.ready() is False)
    g.money = 10
    check('钱不够买不了 7 天', g.subscribe(ds, 2) is False and g.money == 10)

    # ------------------------------------------------ 限流中温度冻结
    print('\n【限流中温度不降】')
    g = fresh()
    ds = next(s for s in g.stations if s.m['id'] == 'DeepSeek')
    give_job(g, ds)
    ds.temp = 70.0
    g.throttle(ds)
    for _ in range(80):
        g.update(0.05)
    check('限流干活时温度保持不变', abs(ds.temp - 70.0) < 0.5)
    ds.limited = False
    ds.strain = 0.3          # 不然压力还在满格，马上又被限
    ds.temp = 70.0
    for _ in range(40):
        g.update(0.05)
    check('正常干活温度会升', ds.temp > 70.0)

    # ------------------------------------------------ 缩放与拖动
    print('\n【滚轮缩放 / 右键拖动】')
    g = fresh()
    check('默认 1.0 不缩放', g.zoom == 1.0)
    g.mouse = (300, 300)
    w_before = g.world_pos((300, 300))
    g.zoom_wheel(1)
    check('滚一下到 1.25', abs(g.zoom - 1.25) < 1e-9)
    w_after = g.world_pos((300, 300))
    check('缩放以鼠标为锚点', abs(w_before[0] - w_after[0]) < 1e-6
          and abs(w_before[1] - w_after[1]) < 1e-6)
    g.zoom_wheel(-1)
    check('缩回来', abs(g.zoom - 1.0) < 1e-9)
    g.zoom_wheel(5)             # 一次事件最多走 3 档（防快滚跳太多）
    check('快滚一次到 1.75', abs(g.zoom - 1.75) < 1e-9)
    g.zoom_wheel(5)
    check('再滚封顶 2.0', abs(g.zoom - 2.0) < 1e-9)
    g.zoom_wheel(-5)
    check('往下也最多 3 档 → 1.25', abs(g.zoom - 1.25) < 1e-9)
    g.zoom_wheel(-5)
    check('最小 1.0', abs(g.zoom - 1.0) < 1e-9)

    # 右键拖动
    g.zoom_wheel(3)
    vx0, vy0, vw, vh = g.view_box()
    g.drag_cam(120, 60)         # 往右下拖 = 看左上
    vx1, vy1, _, _ = g.view_box()
    check('拖动能移动镜头', vx1 < vx0 and vy1 < vy0)
    g.drag_cam(-99999, -99999)
    vx2, vy2, _, _ = g.view_box()
    check('镜头被夹在地图内', vx2 >= -1 and vy2 >= -1)

    # 缩放渲染
    g.zoom = 1.75
    g.draw()
    check('缩放状态下渲染不报错', True)

    # ------------------------------------------------ 满意度
    print('\n【满意度影响收入与声誉】')
    check('收入系数 = 0.40 + 星 × 0.24',
          abs(game.REV_BASE - 0.4) < 1e-9 and abs(game.REV_PER_STAR - 0.24) < 1e-9)
    check('五星收入是 1.6 倍', abs(game.REV_BASE + 5 * game.REV_PER_STAR - 1.6) < 1e-9)
    check('一星收入只有 0.64 倍', abs(game.REV_BASE + game.REV_PER_STAR - 0.64) < 1e-9)
    g = fresh()
    g.last_stars = [5, 5, 4]
    avg = sum(g.last_stars) / len(g.last_stars)
    check('平均满意度 4.7', abs(avg - 4.67) < 0.01)

    print(f'\n通过 {ok} 项，失败 {fail} 项')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
