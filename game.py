#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《AI 中转站》—— 像素风模拟经营

你接手一间夹在写字楼夹层里的 "AI 中转站"：上游是一排不同的大模型线路，
下游是排队等着用的人。你负责派单、控成本、提价、扩线，撑过 30 天。

美术规格：所有角色素材统一 64x64 RGBA 像素图。
  assets/models/<名字>.png   八位模型接线员（已接入）
  assets/guests/guest_XX.png 顾客（待接入，放进去就自动生效；
                             没有素材时用虚线占位框）

运行：
    python3 game.py
"""

import glob
import json
import math
import os
import random
import sys

import pygame

# ---------------------------------------------------------------- 基础常量
WW, WH = 960, 720          # 场景画布（与窗口同尺度，公寓按 0.55 缩放进这里）
SCALE = 1
SW, SH = 1280, 720                # 窗口 1280x720：左边 960 场景 + 右边 320 信息栏
PANE_X = 960                      # 右侧信息栏起点

FPS = 60
DAY_LEN = 300.0            # 1x 速度下一个营业日的秒数（5 分钟 = 24 小时）
AD_COST = 220              # 投一次广告的价格
AD_DAYS = 2                # 广告持续几天
AD_BOOST = 0.62            # 广告期间来单间隔乘以这个（越小越多单）
HOUR_START, HOUR_END = 8, 24   # 一天从 08:00 开到次日 08:00，24:00 结账
DAY_HOURS = 24
NIGHT_START, NIGHT_END = 23, 8   # 夜班时段：额度消耗打对折
NIGHT_COST = 0.5
TOTAL_DAYS = 45
QUOTA_MIN = 30             # 额度低于这个数就算"今天跑不动了"
QUOTA_REF = 3.9            # 算力基准：活越重、算力越低，扣的额度越多（跟着 SPEED_K 一起抬，单子成本不变）

# ---- AI 核心温度 ----
TEMP_IDLE = 36.0           # 待机温度（空闲会降到这儿）
TEMP_LIMIT = 96.0          # 到这个温度就烧了
TEMP_RISE = 0.24           # 跑活时基础升温（°C/秒）
TEMP_LOAD = 0.60           # 负载额外升温：任务越重、机器越慢，涨得越快
TEMP_COOL = 3.40           # 空闲降温（°C/秒），两单之间的空档能散掉不少热
GAME_MIN_PER_SEC = (DAY_HOURS * 60) / DAY_LEN   # 1 现实秒 = 多少游戏分钟

# 限流 / 宕机 的持续时间，按游戏时间定
THROTTLE_MIN = 120         # （旧参数，现在限流不再按时间解除）
CRASH_MIN = 180            # 过热宕机 3 小时

# ---- 上游限流：只有一条线连续满负荷太久才会被限流 ----
STRAIN_FULL = 95.0         # 连续满负荷多少秒后招来限流（约 7.6 个游戏小时）
STRAIN_DECAY = 55.0        # 空闲时压力回落到 0 需要的秒数（越大凉得越慢）
STRAIN_WARN = 0.70         # 到这条线就提示"上游开始盯你了"
STRAIN_RESET = 0.42        # 限流结束后的残留，避免刚解封又立刻被限

# ---- 摸鱼：DeepSeek 会偷偷去煮大白饭 ----
SLACK_MIN = 60             # 摸鱼多久（游戏分钟），超时就真把饭煮好了
SLACK_SEC = SLACK_MIN / GAME_MIN_PER_SEC
SLACK_COST = 40            # 被抓包前煮成的代价：今日额度
SLACK_GAP = 55.0           # 两次摸鱼之间至少隔多久（秒）

# ---- 豆包早餐：只在早上 7:00~9:00 卖，吃完顶 8 个游戏小时 ----
BREAKFAST_FROM = 6      # 6:00 开摊
BREAKFAST_TO = 8        # 8:00 收摊
BREAKFAST_SPD = 0.10       # 早餐加成
BREAKFAST_MIN = 480        # 8 个游戏小时
BREAKFAST_SEC = BREAKFAST_MIN / GAME_MIN_PER_SEC
BREAKFAST_COST = 36

# ---- GLM 的作息：白天摸、晚上猛 ----
GLM_DAY_SPD = 0.60         # 白天 09:00~23:00 效率只有平常的 60%
GLM_NIGHT_SPD = 1.30       # 夜里比平常快 30%
GLM_DAY_QUOTA = 1.20       # 白天同样的活多吃 20% 额度
GLM_NIGHT_QUOTA = 0.60     # 夜间原本就是 0.5 倍，再降 40% -> 0.3 倍

# ---- 被打断的代价（声誉）----
REP_QUOTA = 1.5            # 干活干到限额断了
REP_ABANDON = 1.0          # 主动放弃手上这单
REP_REJECT = 1.0           # 从服务器里退回一条待处理任务
REP_THROTTLE = 0.0         # 限流现在只减速、不打断（保留常量避免旧引用报错）
REP_CRASH = 2.5            # 过热宕机
REP_EXPIRE = 1.2           # 任务等太久被撤单（一次扣这么多太狠，一天几次声誉就没了）
REP_TRIP = 2.5             # 跳闸
THROTTLE_SPD = 0.0         # （旧参数，保留避免旧引用报错）
THROTTLE_SLOW = 0.80       # 被限流时掉多少速度：0.8 = 只剩 20% 速度
THROTTLE_PCT = int(round((1 - THROTTLE_SLOW) * 100))   # 限流后剩下的速度百分比（20）

CUR_NIGHT = False
CUR_SCENE = 'apartment'      # 当前场景（立绘按场景切换用）
GAME_COLD = False            # 科考站燃料断了（全局，影响所有线路的干活速度）
BOND_FROZEN = {'ChatGPT', 'Grok'}   # 只有这一对的亲密不涨
GAME_MEAL_PENALTY = 0.0      # 缺饭导致的减速（全局）
GAME_POLAR = False           # 极夜（全局）

# 同一台机器在不同场景可以换立绘：豆包在公寓是早餐铺老板（Nailong），
# 到了科考站才用新立绘
SCENE_SPRITE = {
    'Doubao': {'apartment': 'Nailong'},
}          # 当前是不是夜班（Game.update 每帧刷新，GLM 的作息要用）

# 窗口被切走 / 最小化的事件（拿不到就退化成空元组）
AWAY_EVENTS = tuple(getattr(pygame, n) for n in
                    ('WINDOWFOCUSLOST', 'WINDOWMINIMIZED',
                     'APP_WILLENTERBACKGROUND') if hasattr(pygame, n))
BACK_EVENTS = tuple(getattr(pygame, n) for n in
                    ('WINDOWFOCUSGAINED', 'WINDOWRESTORED',
                     'APP_DIDENTERFOREGROUND') if hasattr(pygame, n))

# ---- 角色在自己的房间里来回踱步（GLM 有行走帧）。现在先全部关掉 ----
WALK_ON = False            # 改成 True 就恢复踱步动画

# ---- 冰箱小零食 ----
SNACK_STOCK = 3            # 开局冰箱里有几份零食（用完要自己买，不再每天补）
SNACK_SPD = 0.12           # 吃了零食的速度加成
SNACK_MIN = 240            # 一份零食顶多久（游戏分钟 = 4 小时）
SNACK_SEC = SNACK_MIN / GAME_MIN_PER_SEC
SNACK_BUY = 70             # 补货 2 份的价格
SNACK_BUY_N = 2
THROTTLE_SEC = THROTTLE_MIN / GAME_MIN_PER_SEC
CRASH_SEC = CRASH_MIN / GAME_MIN_PER_SEC
RENT_WEEK = 840            # 公寓房租：每 7 天收一次（≈ 120/天）
RENT_EVERY = 7             # 收租间隔（天）
POWER_PER = 4              # 每条已订阅线路每天电费
WAGE_PER_LV = 3            # 每条线路每级每天工资
# ---- 千问做饭：中午 12:00 / 晚上 18:00，空闲才做 ----
MEAL_SLOTS = (7, 12, 18)       # 三餐：早饭 7 点，午饭晚饭千问做
MEAL_COOK_MIN = 30             # 做一顿饭要多久（游戏分钟）
MEAL_COOK_SEC = MEAL_COOK_MIN / GAME_MIN_PER_SEC
MEAL_FATIGUE = 0.06            # 吃一顿只回一点疲劳（主要靠睡觉）

# 开场就有的"初始好感"（-1~1）：没列出来的两两随机 0~10%
INIT_BONDS = {
    ('ChatGPT', 'Grok'): -0.50,
    ('ChatGPT', 'Claude'): 0.20,
    ('Claude', 'DeepSeek'): 0.50,
}
BOND_GAIN = 0.10               # 聊一次涨多少默契
MEAL_BUFF = 0.08               # 全站速度加成
MEAL_BUFF_MIN = 240            # 加成持续（游戏分钟 = 4 小时）
MEAL_BUFF_SEC = MEAL_BUFF_MIN / GAME_MIN_PER_SEC
FOOD_PRICE = 60                # 一份食材包
FOOD_ID = 'food'

VPN_WEEK = 50              # 每个 VPN 端口每周的线路费
VPN_ENC_WEEK = 150         # 每个加密端口的周费

ROOT = os.path.dirname(os.path.abspath(__file__))
# 存档路径：默认在游戏目录；自测/模拟可以用 AIHUB_SAVE 指到临时文件，不碰玩家的存档
SAVE_PATH = os.environ.get('AIHUB_SAVE') or os.path.join(ROOT, 'save.json')
SLOT_COUNT = 4                     # 首页的存档位数量
RENT_NOTICE_ON = True              # 房租前一天的弹窗（自测/模拟里关掉）
SETTINGS_PATH = os.environ.get('AIHUB_SETTINGS') or os.path.join(ROOT, 'settings.json')
MUSIC_DIR = os.path.join(ROOT, 'assets', 'music')
MUSIC_EXTS = ('.mp3', '.ogg', '.wav', '.flac', '.m4a')


def save_path(slot=1):
    """某个存档位的文件路径：1 号位沿用 save.json，其他位是 save_2.json …"""
    if slot <= 1:
        return SAVE_PATH
    base, ext = os.path.splitext(SAVE_PATH)
    return f'{base}_{int(slot)}{ext}'


def load_settings():
    d = dict(music=1, volume=0.6, fullscreen=0)
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            d.update(json.load(f) or {})
    except (OSError, ValueError):
        pass
    return dict(music=1 if d.get('music', 1) else 0,
                volume=max(0.0, min(1.0, float(d.get('volume', 0.6)))),
                fullscreen=1 if d.get('fullscreen') else 0)


def save_settings(d):
    try:
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f)
    except OSError:
        pass


def find_music():
    """找背景音乐：优先名字里带 大肥鱼 / let me go / fish 的，否则用目录里第一首。"""
    if not os.path.isdir(MUSIC_DIR):
        return None
    files = []
    for fn in sorted(os.listdir(MUSIC_DIR)):
        if fn.startswith('._') or fn.startswith('.'):
            continue
        if fn.lower().endswith(MUSIC_EXTS):
            files.append(os.path.join(MUSIC_DIR, fn))
    if not files:
        return None
    for fp in files:
        low = os.path.basename(fp).lower()
        if '大肥鱼' in low or ('let' in low and 'go' in low) or 'fish' in low:
            return fp
    return files[0]

CJK_CANDIDATES = [
    # macOS
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/Supplemental/Songti.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
    # Windows
    'C:/Windows/Fonts/msyh.ttc',        # 微软雅黑
    'C:/Windows/Fonts/msyhbd.ttc',
    'C:/Windows/Fonts/simhei.ttf',      # 黑体
    'C:/Windows/Fonts/simsun.ttc',      # 宋体
    'C:/Windows/Fonts/Deng.ttf',        # 等线
    # Linux
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
]

# ---------------------------------------------------------------- 配色
C_BG = (18, 18, 28)
C_WALL = (26, 27, 42)
C_WALL2 = (33, 35, 54)
C_FLOOR = (23, 24, 36)
C_FLOOR_L = (30, 32, 48)
C_LINE = (44, 48, 70)
C_TEXT = (226, 230, 242)
C_DIM = (140, 148, 172)
C_GOLD = (255, 206, 106)
C_GREEN = (108, 224, 158)
C_RED = (255, 108, 118)
C_BLUE = (116, 186, 255)
C_PURPLE = (176, 152, 255)

# ---------------------------------------------------------------- 需求类型
TYPES = {
    'chat':   dict(name='闲聊对话', sym='...', color=(122, 200, 255), w=(26, 58),  budget=(11, 24)),
    'code':   dict(name='写代码',   sym='</>', color=(140, 232, 158), w=(58, 112), budget=(33, 68)),
    'image':  dict(name='画图',     sym='###', color=(255, 168, 212), w=(62, 124), budget=(43, 88)),
    'reason': dict(name='逻辑推理', sym='???', color=(255, 204, 118), w=(52, 104), budget=(26, 56)),
    'doc':    dict(name='长文写作', sym='===', color=(186, 176, 255), w=(62, 118), budget=(24, 53)),
    'vision': dict(name='看图识图', sym='[o]', color=(132, 230, 218), w=(38, 84),  budget=(19, 44)),
}
TYPE_KEYS = list(TYPES.keys())

# ---------------------------------------------------------------- 线路数据
# spd 单位/秒；q 基础质量；cost 每单位上游采购价；tags 专长领域
# tiers = 三档订阅：(档位名, 每天价格, 当天额度)。额度 -1 = 无限
# 价格参考 2026 年真实月费（$20 档 ≈ ¥145/月，国内 Coding Plan ¥40~200/月），
# 按游戏里一条线一天能赚 ¥150~250 的尺度压到"每天几块到两百多"。
MODELS = [
    dict(id='Doubao', name='Seed', sprite='Doubao', spd=2.6, q=0.55, cost=0.016,
         tags=['chat', 'doc'], color=(240, 196, 132), unlock=0, reset=0,
         no_fatigue=True,
         tiers=[('基础', 15, 120), ('标准', 28, 260)],
         blurb='豆包 Seed 1.6：256k 长上下文、便宜大碗；现在要接电、也要订阅'),
    dict(id='DeepSeek', name='DeepSeek', spd=3.2, q=0.820, cost=0.085,
         tags=['reason', 'code'], color=(96, 168, 255), unlock=0, reset=150,
         tiers=[('基础', 0, 210), ('标准', 35, 540), ('专业', 60, 1140)],
         low='DeepSeekChan', swap_sprite=True, big_price=700,
         small_block=('image', 'vision'), qdisc=0.80,
         blurb='初始线路，额度消耗比标称少 20%；还能单独升级成大模型'),
    dict(id='Qwen', name='Qwen', spd=3.0, q=0.800, cost=0.095,
         tags=['chat', 'doc', 'code'], color=(128, 142, 255), unlock=700, reset=160,
         tiers=[('基础', 30, 230), ('标准', 60, 575), ('专业', 105, 1215)],
         blurb='中文顺，多面手'),
    dict(id='GLM', name='GLM', spd=2.9, q=0.805, cost=0.100,
         tags=['chat', 'code', 'vision'], color=(158, 158, 196), unlock=850, reset=170,
         tiers=[('基础', 33, 235), ('标准', 65, 610), ('专业', 115, 1280)],
         rhythm=True, blurb='作息颠倒：白天 60% 效率，夜里 130%'),
    dict(id='Grok', name='Grok', spd=3.4, q=0.795, cost=0.145,
         tags=['chat', 'reason'], color=(232, 192, 122), unlock=1100, reset=180, need='vpn',
         tiers=[('基础', 40, 210), ('标准', 75, 540), ('专业', 130, 1150)],
         blurb='反应快，嘴也快'),
    dict(id='Gemini', name='Gemini', spd=4.96, q=0.850, cost=0.135,
         tags=['vision', 'image', 'doc'], color=(152, 192, 255), unlock=1400, reset=210, need='vpn',
         tiers=[('基础', 42, 215), ('标准', 85, 610), ('专业', 150, 1295)],
         qjitter=(0.85, 0.95), blurb='快得多（速度 ×1.6），但每单质量会飘 5%~15%'),
    dict(id='ChatGPT', name='ChatGPT', spd=3.0, q=0.880, cost=0.160,
         tags=['chat', 'image', 'vision'], color=(122, 222, 182), unlock=1700, reset=230, need='vpn',
         tiers=[('基础', 50, 225), ('标准', 100, 690), ('专业', 175, 1440)],
         low='MiniGPT', big_price=1600,
         blurb='旗舰线，还能单独升级成成年龙娘'),
    dict(id='Claude', name='Claude', spd=2.8, q=0.930, cost=0.175,
         tags=['doc', 'code'], color=(234, 152, 112), unlock=2200, reset=260, need='vpn_enc',
         tiers=[('基础', 55, 200), ('标准', 105, 590), ('专业', 185, 1250)],
         blurb='写得最好，额度最紧'),
    dict(id='Kimi', name='Kimi', spd=3.15, q=0.822, cost=0.100,
         tags=['doc', 'code', 'chat'], color=(150, 176, 220), unlock=1200, reset=190,
         scene='station',
         tiers=[('基础', 38, 240), ('标准', 72, 620), ('专业', 125, 1300)],
         blurb='超长上下文，长文档和代码都稳（科考站专属）'),
    dict(id='Hunyuan', name='混元', spd=3.0, q=0.790, cost=0.090,
         tags=['chat', 'vision', 'image'], color=(120, 200, 190), unlock=1300,
         reset=200, scene='station',
         tiers=[('基础', 35, 235), ('标准', 68, 600), ('专业', 118, 1270)],
         blurb='国产多模态，看图识图便宜（科考站专属）'),
]  

BUILD = 'v54.6 · 2026-11-01'

# 首页底部的作者 / 出处 / 版权声明（按需改这几行）
CREDITS = dict(
    author='Jasonzhang369',
    source='github.com/Jasonzhang369/ai-apartment-game',
    art='形象来源：bilibili @ZipZipPipe @这个刀子真甜 @邦多利素世 等',
    idea='灵感来源：bilibili @冬冰 ·「AI 中转站公寓」系列 /「去南极散热」系列',
    note='仅供学习交流 · 不作商业用途 · 素材版权归各自原作者，如有侵权请联系删除',
)

# ---- 整体节奏 ----
SPEED_K = 1.30             # 全员干活速度倍率

# ---- 重置卡 ----
RESET_CARD = 150           # 一张重置卡的价格
SUB_DAYS = 7               # 订阅一次买 7 天，当场付清
# ---- 疲劳与休息日 ----
FATIGUE_FULL = 240.0       # 连着干多少秒就累满（一条线不停手）
FATIGUE_RECOVER = 45.0      # （旧参数，保留避免旧引用；现在闲置不回血）
FATIGUE_PENALTY = 0.15      # 累到头最多慢多少（少量 debuff）
REST_BONUS = 0.25           # 休息一天之后，效率提升多少

# ---- 满意度对收益 / 声誉的影响 ----
REV_BASE = 0.40            # 收入系数：base + star * per_star
REV_PER_STAR = 0.24
REP_PER_STAR = 0.40        # 每单声誉变化 = (star - 2.6) * REP_PER_STAR

# ---- 装备商店（每件装备只能买一次，只能装给一个 AI）----
GEAR = [
    dict(id='cpu', name='处理器（CPU）', price=600,
         desc='这条 AI 干活速度 +20%'),
    dict(id='fan', name='散热扇', price=450,
         desc='这条 AI 热量积累 -20%'),
    dict(id='dual', name='便携式服务器', price=1200,
         desc='这条 AI 能同时处理两个任务'),
    dict(id='mem', name='记忆模块', price=900,
         desc='这条 AI 不再有质量抖动（Gemini 那种）'),
    dict(id='net', name='扩展网口', price=800,
         desc='这条 AI 每天额度 +50%'),
    dict(id='vpn', name='VPN 端口', price=600,
         desc='Grok / ChatGPT / Gemini 能用；每周 ¥50'),
    dict(id='vpn_enc', name='加密 VPN 端口', price=1000,
         desc='Claude 必需；其余线路可用且速度 +5%；每周 ¥150'),
]

GEAR_SHOP_RECT = pygame.Rect(802, 556, 136, 108)   # 装备店（公寓墙外右下角的小店）

# ---- 走道与门：串门要走房门和走廊，不能穿墙 ----
# 公寓正中有一条竖向的方砖过道（世界 x 418~452），它被三段门框分成三段过道，
# 每段正对着一层房间：左列（ChatGPT/Gemini/Claude）的门开在过道左边，
# 右列（Grok/GLM/Qwen）的门开在过道右边。
# 所以上下两层之间是不通的——串门只能先走进本层的过道，再从对门进另一侧的房间。
CORR_X = 435              # 过道中心
CORR_L, CORR_R = 424, 446  # 过道左右边界（角色只能在这个范围内上下走）
# 门口点：站在通道边线再往房间那侧一点，这样"进房间"这一步由房间段接管
DOOR_L, DOOR_R = 416, 454  # 左列房间的门 / 右列房间的门
SOCIAL_SPD = 46.0          # 串门走路的速度（像素/秒）
RETURN_BOOST = 1.9         # 在外面被派了活：赶回工位的速度倍率
YARD_Y = 690               # 楼外空地：不再使用（不许穿墙去楼外）

# 几段过道（世界 y 的范围）：房间在对应段上才能过去。
# 顶层那排（DeepSeek / 客厅 / 厨房 / 阳台）共用最上面这一段。
HALLS = [(80, 150), (235, 273), (374, 412), (513, 552)]

# 每个房间的门口点（脚底坐标）——都在对应过道的边上，门朝过道开
DOORS = {
    'DeepSeek': (435, 130),    # 最上层：门开在顶部横廊那一排
    'ChatGPT':  (DOOR_L, 268),   # 第 1 段过道，左侧
    'Gemini':   (DOOR_L, 404),   # 第 2 段过道，左侧
    'Claude':   (DOOR_L, 540),   # 第 3 段过道，左侧
    'Grok':     (DOOR_R, 266),   # 第 1 段过道，右侧
    'GLM':      (DOOR_R, 408),   # 第 2 段过道，右侧
    'Qwen':     (DOOR_R, 542),   # 第 3 段过道，右侧
    # 上方的客厅 / 厨房 / 阳台：在顶部那排房间里
    'SERVER':   (435, 130),
    'KITCHEN':  (620, 100),
    'BALCONY':  (760, 100),
}
# 房间内部可以站的点（进门后往里走一点，避免贴着门框）
INSIDE = {
    'DeepSeek': (330, 118), 'ChatGPT': (300, 268), 'Gemini': (372, 404),
    'Claude': (330, 540), 'Grok': (700, 266), 'GLM': (660, 408),
    'Qwen': (620, 542),
}
# 可以去串门的地方（不总去客厅）。这些点都在上方那排房间里，
# 从中间通道顶端的横廊走过去。
SPOTS = [
    ('客厅', (500, 108)),
    ('厨房', (640, 96)),
    ('阳台', (850, 92)),
]
MAX_GEAR = 3                                      # 一条线最多挂三件装备

# ---- 背包：买到的道具都先进背包，用的时候从背包拖到 AI 身上 ----
RESET_PREFIX = 'reset:'          # 重置卡 item id = 'reset:<线路 id>'
BAG_KIND_GEAR, BAG_KIND_RESET = 'gear', 'reset'
BAG_SLOTS = 15                  # 背包一屏 15 格（7 装备 + 食材 + 7 种重置卡）


def reset_price(m):
    """这条线路的重置卡单价（每人不一）。"""
    return int(m.get('reset', RESET_CARD))


def bag_item_info(item):
    """背包格子的展示信息：(种类, 名称, 短名, 颜色, 线路 dict 或 None)。"""
    if item == FOOD_ID:
        return ('food', '食材包', '食材', (238, 196, 128), None)
    if item.startswith(RESET_PREFIX):
        mid = item[len(RESET_PREFIX):]
        m = next((x for x in MODELS if x['id'] == mid), None)
        if m:
            return (BAG_KIND_RESET, f'{m["name"]} 重置卡', m['name'], m['color'], m)
        return (BAG_KIND_RESET, '重置卡', '重置卡', C_GOLD, None)
    g = next((x for x in GEAR if x['id'] == item), None)
    if g:
        return (BAG_KIND_GEAR, g['name'], g['name'], (250, 214, 140), None)
    return (BAG_KIND_GEAR, str(item), str(item), C_DIM, None)


def draw_card_icon(surf, color, x, y, size=28):
    """重置卡的小图标：一张卡片 + 线路色 + 右下角的重置箭头。"""
    s = max(10, int(size))
    pygame.draw.rect(surf, (34, 32, 46), (x, y, s, s), border_radius=3)
    pygame.draw.rect(surf, (86, 80, 104), (x, y, s, s), 1, border_radius=3)
    card = pygame.Rect(x + int(s * 0.22), y + int(s * 0.14), int(s * 0.56), int(s * 0.72))
    pygame.draw.rect(surf, (26, 24, 34), card, border_radius=2)
    pygame.draw.rect(surf, color, card, 1, border_radius=2)
    for i in range(3):
        yy = card.y + int(card.h * (0.28 + i * 0.2))
        pygame.draw.rect(surf, color, (card.x + 3, yy, card.w - 6, max(1, s // 18)))
    r = max(3, int(s * 0.17))
    cx, cy = x + int(s * 0.76), y + int(s * 0.77)
    pygame.draw.circle(surf, color, (cx, cy), r, 1)
    pygame.draw.polygon(surf, color, [(cx + r, cy - 2), (cx + r, cy + 2), (cx + r + 3, cy)])


def draw_bag_item_icon(surf, item, x, y, size=28):
    """按道具种类画图标（装备走装备图，重置卡走卡面，食材画个碗）。"""
    kind, name, short, col, model = bag_item_info(item)
    if kind == BAG_KIND_RESET:
        draw_card_icon(surf, col, x, y, size)
    elif kind == 'food':
        s_ = max(10, int(size))
        pygame.draw.rect(surf, (34, 32, 46), (x, y, s_, s_), border_radius=3)
        pygame.draw.rect(surf, (86, 80, 104), (x, y, s_, s_), 1, border_radius=3)
        cx, cy = x + s_ // 2, y + int(s_ * 0.62)
        pygame.draw.circle(surf, (222, 216, 200), (cx, cy), int(s_ * 0.30))
        pygame.draw.circle(surf, (250, 248, 240), (cx, cy), int(s_ * 0.22))
        pygame.draw.rect(surf, col, (cx - int(s_ * 0.30), cy - int(s_ * 0.34),
                                     int(s_ * 0.60), max(2, int(s_ * 0.10))))
    else:
        draw_gear_icon(surf, item, x, y, size)


def draw_gear_icon(surf, gid, x, y, size=28):
    """画一张装备小图（像素风，跟场景里的其他图标一个调子）。"""
    s = max(10, int(size))
    pygame.draw.rect(surf, (48, 44, 58), (x, y, s, s), border_radius=3)
    pygame.draw.rect(surf, (92, 84, 108), (x, y, s, s), 1, border_radius=3)
    u = s / 16.0

    def rc(cx, cy, cw, ch, col):
        pygame.draw.rect(surf, col, (x + cx * u, y + cy * u,
                                     max(1, cw * u), max(1, ch * u)))

    if gid == 'cpu':                      # 处理器：芯片 + 针脚
        rc(4, 4, 8, 8, (58, 96, 78))
        rc(5, 5, 6, 6, (86, 136, 110))
        for i in range(4):
            rc(4 + i * 2.2, 2, 1.2, 2, (238, 208, 130))
            rc(4 + i * 2.2, 12, 1.2, 2, (238, 208, 130))
            rc(2, 4 + i * 2.2, 2, 1.2, (238, 208, 130))
            rc(12, 4 + i * 2.2, 2, 1.2, (238, 208, 130))
    elif gid == 'fan':                    # 散热扇：外框 + 四片扇叶
        pygame.draw.circle(surf, (70, 78, 96),
                           (int(x + s / 2), int(y + s / 2)), int(6.6 * u))
        pygame.draw.circle(surf, (132, 150, 180),
                           (int(x + s / 2), int(y + s / 2)), int(6.6 * u), 1)
        pygame.draw.circle(surf, (150, 220, 236),
                           (int(x + s / 2), int(y + s / 2)), int(1.6 * u))
        pygame.draw.line(surf, (150, 220, 236),
                         (x + 8 * u, y + 8 * u), (x + 8 * u, y + 2.4 * u), 2)
        pygame.draw.line(surf, (150, 220, 236),
                         (x + 8 * u, y + 8 * u), (x + 13.6 * u, y + 8 * u), 2)
        pygame.draw.line(surf, (150, 220, 236),
                         (x + 8 * u, y + 8 * u), (x + 8 * u, y + 13.6 * u), 2)
        pygame.draw.line(surf, (150, 220, 236),
                         (x + 8 * u, y + 8 * u), (x + 2.4 * u, y + 8 * u), 2)
    elif gid == 'dual':                   # 便携式服务器：两台小机柜
        for k in (0, 1):
            bx = 2.2 + k * 7.0
            rc(bx, 3, 4.4, 10, (60, 66, 88))
            rc(bx + 0.6, 3.6, 3.2, 8.8, (88, 96, 124))
            for j in range(3):
                rc(bx + 1.0, 4.4 + j * 2.6, 2.4, 1.4, (64, 70, 92))
            rc(bx + 2.6, 11.4, 1.0, 1.0,
               (120, 230, 170) if (k + int(pygame.time.get_ticks() // 500)) % 2 else (70, 90, 90))
    elif gid == 'mem':                    # 记忆模块：内存条
        rc(2, 5, 12, 6, (56, 64, 88))
        rc(3, 6, 3, 4, (110, 130, 180))
        rc(7, 6, 3, 4, (110, 130, 180))
        for i in range(6):
            rc(2.4 + i * 1.9, 11, 1.2, 2.2, (238, 208, 130))
        rc(2, 4, 12, 1, (78, 90, 130))
    elif gid == 'net':                    # 扩展网口：一排网口
        rc(2, 4, 12, 8, (58, 66, 88))
        for i in range(4):
            rc(3.0 + i * 2.6, 5.4, 2.0, 3.2, (30, 34, 46))
            rc(3.4 + i * 2.6, 6.0, 1.2, 2.0, (238, 208, 130))
        rc(6, 12, 4, 2, (110, 150, 200))
    else:
        rc(4, 4, 8, 8, (110, 110, 130))


# ---- 闲下来的人凑到客厅服务器那儿聊天 ----
CHAT_LINES = [
    '今天单子有点多啊',
    '你那显卡烫不烫？',
    '我刚把额度用光了',
    '被上游限流顶住了',
    '晚上一起干活？',
    '这单给的价还行',
    '我刚升级了模型',
    '别摸鱼了，被盯着呢',
    '客户又催了',
    '续上咖啡，继续',
    '今天的饭真香',
    '客厅信号满格',
]

# 被搭话的人的回应（两句都显示，像真的在聊）
CHAT_REPLIES = [
    '嗯，是有点忙',
    '可不是嘛',
    '等我跑完这单',
    '你说得对',
    '哈哈，我也是',
    '先喝口水',
    '别说了，又要超时了',
    '晚上再说',
    '我这边还行',
    '主机风扇在叫',
]

# ---- 相机 ----
ZOOM_STEPS = [1.0, 1.25, 1.5, 1.75, 2.0]

PRICE_STEPS = [0.70, 0.85, 1.00, 1.15, 1.30, 1.50]
INIT_UNLOCK = 4

# ---- 场景布局（俯视公寓；改户型只动这一段）----
APT_POS = (200, 8)                    # 公寓背景图在场景里的位置
APT_SIZE = (721, 704)                 # assets/apartment.png 的尺寸（布局图 x0.55）
SHOP_POS = (10, 466)                  # 屋外的豆包早餐铺
SHOP_RECT = pygame.Rect(10, 470, 173, 168)

# 八个工位（世界坐标 = 布局图站位 x0.55 + APT_POS，脚底点）
STANDS = {
    'DeepSeek': (330, 120),           # 左上：水泥墙小房间（零食堆）
    'ChatGPT':  (300, 268),           # 左二：RGB 机箱房
    'Grok':     (700, 266),           # 右二：星空墙 + 豆袋沙发
    'Gemini':   (372, 404),           # 左三：暖黄串灯房
    'GLM':      (660, 408),           # 右三：黑床纱帐房
    'Claude':   (330, 540),           # 左四：满墙书架房
    'Qwen':     (620, 542),           # 右四：中式红木床房
    'Doubao':   (96, 590),            # 楼外早餐铺柜台后
}

# 客厅的派单服务器（客厅图里那台带绿色指示灯的机柜）
SERVER = (558, 88)

# ================= 第二幕：南极科考站 =================
# 同一个引擎，只换一套"坐标表"：工位 / 门口 / 房间内点 / 公共区 /
# 服务器 / 网关 / 待处理位 / 电闸 / 冰箱 / 商店 / 背景图 / 掩码
# 所有人都在大厅的长条桌边上班（上排 5 个、下排 5 个）
STANDS_ST = {
    'Doubao': (240, 536), 'DeepSeek': (295, 536), 'Qwen': (350, 536),
    'GLM': (405, 536), 'Grok': (460, 536),
    'Gemini': (240, 612), 'ChatGPT': (295, 612), 'Claude': (350, 612),
    'Kimi': (405, 612), 'Hunyuan': (460, 612),
}
DOORS_ST = {
    'Doubao': (340, 470), 'DeepSeek': (340, 470), 'Qwen': (340, 470),
    'GLM': (340, 470), 'Grok': (340, 470), 'Gemini': (340, 470),
    'ChatGPT': (340, 470), 'Claude': (340, 470), 'Kimi': (340, 470),
    'Hunyuan': (340, 470),
    'SERVER': (359, 222), 'KITCHEN': (359, 246), 'BALCONY': (370, 700),
}
INSIDE_ST = {
    'Doubao': (244, 546), 'DeepSeek': (299, 546), 'Qwen': (354, 546),
    'GLM': (409, 546), 'Grok': (464, 546),
    'Gemini': (244, 602), 'ChatGPT': (299, 602), 'Claude': (354, 602),
    'Kimi': (409, 602), 'Hunyuan': (464, 602),
}
SPOTS_ST = [
    ('客厅', (400, 186)),      # 主控通信
    ('厨房', (300, 404)),      # 食堂
    ('阳台', (370, 700)),      # 气闸外的观景台
]
HALLS_ST = [(216, 252), (440, 476)]
SERVER_ST = (330, 182)        # 主控室下方三台机柜中间那台（再往下一点）
GATEWAY_ST = (438, 180)
CONSOLE_RECT_ST = pygame.Rect(280, 54, 184, 62)  # 主控台三块屏幕：点它买物资
SUPPLY_RECT_ST = CONSOLE_RECT_ST.copy()          # 买物资也走这里
WEATHER_RECT_ST = pygame.Rect(62, 44, 180, 156)  # 整个气象室都能点：采数据
LAB_RECT_ST = pygame.Rect(60, 492, 142, 156)     # 整个实验室都能点：化验冰样
GREEN_RECT_ST = pygame.Rect(60, 268, 182, 156)   # 整个温室都能点：看收成/喂照顾
WEATHER_POINT = (150, 130)      # 去气象室采集站哪儿
LAB_POINT = (120, 570)          # 实验室化验站哪儿
AIRLOCK_POINT = (370, 680)      # 气闸外采冰样
UPLOAD_POINT = (372, 112)       # 主控台前（三块屏幕）
GREEN_POINT = (150, 340)        # 温室里干活的位置
COOK_POINT_ST = (300, 402)      # 科考站：食堂灶台前
AIRLOCK_RECT_ST = pygame.Rect(318, 656, 104, 36) # 气闸：出去采冰样
UPLOAD_RECT_ST = CONSOLE_RECT_ST.copy()          # 上传也走主控台
SUPPLY_CAR_RECT_ST = pygame.Rect(586, 606, 104, 76)  # 右下角的雪地补给车
SUPPLY_RECT = SUPPLY_RECT_ST.copy()             # 当前场景的点击热区
TASK_SLOTS_ST = [(340, 150), (366, 158), (392, 150),
                 (340, 176), (366, 182), (392, 176)]
BREAKER_ST = (520, 190)
FRIDGE_ST = (300, 430)
DORM_SPOT = (600, 380)          # 宿舍里睡觉的位置
FRIDGE_RECT_ST = pygame.Rect(270, 380, 34, 64)
WAREHOUSE_RECT_ST = pygame.Rect(500, 488, 152, 164)  # 仓库：点它看库存 + 装备店
GEAR_SHOP_RECT_ST = pygame.Rect(0, 0, 0, 0)          # 装备店并进仓库了
SHOP_RECT_ST = pygame.Rect(10, 470, 173, 168)
APT_POS_ST = (112, 0)                 # station.png 720x704 摆在场景中间（16 的整数倍）
STATION_MASK = os.path.join(ROOT, 'assets', 'walkmask_station.json')
SUPPLY_EVERY = 3             # 补给每 3 天到一次
RELOCATE_COST = 2500
RELOCATE_DAY = 5                  # 攒够这么多钱才能搬去南极
POLAR_DAY = 12
QUEST_COOLDOWN = 8.0          # 同一种科考任务至少隔 8 小时
INTRO_ON = True               # 第一次进科考站弹玩法说明（测试里会关掉）                        # 第几天开始极夜
POLAR_FUEL = 1.6                      # 极夜燃料消耗倍率
FISH_FATIGUE = 0.12                   # 抓鱼加的疲劳

# 站点坐标是"图内坐标"，进场景要加上底图位置
_SO = (APT_POS_ST[0], APT_POS_ST[1])


def _soff(pt):
    return (pt[0] + _SO[0], pt[1] + _SO[1])


STANDS_ST = {k: _soff(v) for k, v in STANDS_ST.items()}
DOORS_ST = {k: _soff(v) for k, v in DOORS_ST.items()}
INSIDE_ST = {k: _soff(v) for k, v in INSIDE_ST.items()}
SPOTS_ST = [(n, _soff(p)) for n, p in SPOTS_ST]
HALLS_ST = [(a + _SO[1], b + _SO[1]) for a, b in HALLS_ST]
SERVER_ST = _soff(SERVER_ST)
GATEWAY_ST = _soff(GATEWAY_ST)
TASK_SLOTS_ST = [_soff(p) for p in TASK_SLOTS_ST]
BREAKER_ST = _soff(BREAKER_ST)
FRIDGE_ST = _soff(FRIDGE_ST)
DORM_SPOT = _soff(DORM_SPOT)
FRIDGE_RECT_ST = FRIDGE_RECT_ST.move(*_SO)
GEAR_SHOP_RECT_ST = GEAR_SHOP_RECT_ST.move(*_SO)


def apply_scene_geo(scene):
    """切换场景 = 换一套坐标常量（引擎里所有位置都读这些全局量）。"""
    # 豆包在公寓还是老样子（免费、守铺子）；科考站那条才叫 Seed（接电、要订阅）
    for m in MODELS:
        if m['id'] != 'Doubao':
            continue
        if scene == 'station':
            m['name'] = 'Seed'
            m['tiers'] = [('基础', 15, 120), ('标准', 28, 260)]
            m.pop('forever', None)
            m.pop('nopower', None)
        else:
            m['name'] = '豆包'
            m['tiers'] = [('免费', 0, -1)]
            m['forever'] = True
            m['nopower'] = True
    global STANDS, DOORS, INSIDE, SPOTS, HALLS, SERVER, GATEWAY, TASK_SLOTS
    global BREAKER, FRIDGE, FRIDGE_RECT, GEAR_SHOP_RECT, SHOP_RECT, APT_POS, SUPPLY_RECT
    global DORM_SPOT, WEATHER_RECT, LAB_RECT, AIRLOCK_RECT, UPLOAD_RECT, GREEN_RECT
    global WEATHER_POINT, LAB_POINT, AIRLOCK_POINT, UPLOAD_POINT, GREEN_POINT
    global COOK_POINT, SUPPLY_CAR_RECT, WAREHOUSE_RECT
    if scene == 'station':
        STANDS, DOORS, INSIDE, SPOTS = STANDS_ST, DOORS_ST, INSIDE_ST, SPOTS_ST
        HALLS, SERVER, GATEWAY = HALLS_ST, SERVER_ST, GATEWAY_ST
        TASK_SLOTS, BREAKER, FRIDGE = TASK_SLOTS_ST, BREAKER_ST, FRIDGE_ST
        FRIDGE_RECT = FRIDGE_RECT_ST.copy()
        SUPPLY_RECT = SUPPLY_RECT_ST.move(*_SO)
        DORM_SPOT = _soff((600, 380))
        WEATHER_RECT = WEATHER_RECT_ST.move(*_SO)
        LAB_RECT = LAB_RECT_ST.move(*_SO)
        GREEN_RECT = GREEN_RECT_ST.move(*_SO)
        WEATHER_POINT = _soff(WEATHER_POINT)
        LAB_POINT = _soff(LAB_POINT)
        AIRLOCK_POINT = _soff(AIRLOCK_POINT)
        UPLOAD_POINT = _soff(UPLOAD_POINT)
        GREEN_POINT = _soff(GREEN_POINT)
        COOK_POINT = _soff(COOK_POINT_ST)
        SUPPLY_CAR_RECT = SUPPLY_CAR_RECT_ST.move(*_SO)
        WAREHOUSE_RECT = WAREHOUSE_RECT_ST.move(*_SO)
        AIRLOCK_RECT = AIRLOCK_RECT_ST.move(*_SO)
        UPLOAD_RECT = UPLOAD_RECT_ST.move(*_SO)
        GEAR_SHOP_RECT, SHOP_RECT, APT_POS = GEAR_SHOP_RECT_ST, SHOP_RECT_ST, APT_POS_ST
    else:
        STANDS = dict(STANDS_APT)
        DOORS = dict(DOORS_APT)
        INSIDE = dict(INSIDE_APT)
        SPOTS = list(SPOTS_APT)
        HALLS = list(HALLS_APT)
        SERVER, GATEWAY = SERVER_APT, GATEWAY_APT
        TASK_SLOTS = list(TASK_SLOTS_APT)
        BREAKER, FRIDGE = BREAKER_APT, FRIDGE_APT
        FRIDGE_RECT = FRIDGE_RECT_APT.copy()
        SUPPLY_RECT = pygame.Rect(0, 0, 0, 0)
        DORM_SPOT = (600, 380)
        WEATHER_RECT = pygame.Rect(0, 0, 0, 0)
        LAB_RECT = pygame.Rect(0, 0, 0, 0)
        GREEN_RECT = pygame.Rect(0, 0, 0, 0)
        WEATHER_POINT = (150, 130)
        LAB_POINT = (120, 570)
        AIRLOCK_POINT = (370, 680)
        UPLOAD_POINT = (330, 175)
        GREEN_POINT = (150, 340)
        AIRLOCK_RECT = pygame.Rect(0, 0, 0, 0)
        UPLOAD_RECT = pygame.Rect(0, 0, 0, 0)
        GEAR_SHOP_RECT = GEAR_SHOP_RECT_APT.copy()
        SHOP_RECT = SHOP_RECT_APT.copy()
        APT_POS = APT_POS_APT
        COOK_POINT = (620, 100)
        SUPPLY_CAR_RECT = pygame.Rect(0, 0, 0, 0)
        WAREHOUSE_RECT = pygame.Rect(0, 0, 0, 0)


GATEWAY = (262, 627)                  # 门厅里的网络网关：任务从这儿涌进来
# 客厅服务器旁的待处理位（6 个，排成两排）
TASK_SLOTS = [(474, 108), (500, 120), (526, 108),
               (474, 140), (500, 148), (526, 140)]
# 楼梯间的电闸：楼梯间在 assets 里已经左右镜像过（见 tools/gen_scene.py 的 STAIR_MIRROR），
# 电闸原来挂在右墙 (436,590)，镜像后跟着挪到左墙：x = 298 + 455 - 436 = 317
BREAKER = (317, 590)

# 厨房那台双门冰箱（零食都在里面）
FRIDGE = (688, 90)                                    # 脚底基准点（世界坐标）
FRIDGE_RECT = pygame.Rect(671, 28, 34, 64)            # 点击热区

# 公寓这套坐标先存一份：切到科考站时要用它还原
STANDS_APT = dict(STANDS)
DOORS_APT = dict(DOORS)
INSIDE_APT = dict(INSIDE)
SPOTS_APT = list(SPOTS)
HALLS_APT = list(HALLS)
SERVER_APT = SERVER
GATEWAY_APT = GATEWAY
TASK_SLOTS_APT = list(TASK_SLOTS)
BREAKER_APT = BREAKER
FRIDGE_APT = FRIDGE
FRIDGE_RECT_APT = FRIDGE_RECT.copy()
GEAR_SHOP_RECT_APT = GEAR_SHOP_RECT.copy()
SHOP_RECT_APT = SHOP_RECT.copy()
APT_POS_APT = APT_POS

# ---------------------------------------------------------------- 全局字体
FONTS, _TCACHE = {}, {}
_CJK = next((p for p in CJK_CANDIDATES if os.path.exists(p)), None)


def font(size, bold=False):
    k = (size, bold)
    if k not in FONTS:
        if _CJK:
            f = pygame.font.Font(_CJK, size)
        else:
            f = pygame.font.SysFont('microsoftyahei,simhei,pingfang,notosanscjk', size)
        f.set_bold(bold)
        FONTS[k] = f
    return FONTS[k]


def txt(surf, s, x, y, size=16, color=C_TEXT, anchor='topleft', bold=False):
    """带缓存渲染文字（screen 坐标）。"""
    if not s:
        return None
    k = (s, size, color, bold)
    img = _TCACHE.get(k)
    if img is None:
        img = font(size, bold).render(str(s), True, color)
        if len(_TCACHE) > 3000:
            _TCACHE.clear()
        _TCACHE[k] = img
    r = img.get_rect(**{anchor: (x, y)})
    surf.blit(img, r)
    return r


def fmt_sec_game(sec):
    """把现实秒换算成游戏时间显示。"""
    m = int(round(max(0.0, sec) * GAME_MIN_PER_SEC))
    return f'{m // 60}小时{m % 60:02d}分' if m >= 60 else f'{m}分钟'


def fmt_wait(task):
    """把"还能等多久"换算成游戏时间，例如 1小时12分。"""
    left = max(0.0, task.patience - task.wait) * GAME_MIN_PER_SEC
    m = int(round(left))
    return f'{m // 60}小时{m % 60:02d}分' if m >= 60 else f'{m}分'


def text_w(s, size=12, bold=False):
    """真实渲染宽度：font.size() 对中文字宽估得偏窄，会裁掉底衬。"""
    return font(size, bold).render(str(s), True, (255, 255, 255)).get_width()


def _brighten(c, k=1.55):
    return tuple(min(255, int(v * k)) for v in c[:3])


def alpha_rect(surf, rect, color, radius=0):
    s = pygame.Surface((max(1, rect.w), max(1, rect.h)), pygame.SRCALPHA)
    pygame.draw.rect(s, color, s.get_rect(), border_radius=radius)
    surf.blit(s, rect.topleft)


def aacircle(surf, color, pos, r):
    """带抗锯齿的实心圆（在 2x 画布上更顺滑）。"""
    pygame.draw.circle(surf, color, pos, r)


# ---------------------------------------------------------------- 素材
def load_img(path):
    return pygame.image.load(path).convert_alpha()


class Assets:
    def __init__(self):
        self.models = {}
        mdir = os.path.join(ROOT, 'assets', 'models')
        for m in MODELS:
            extra = tuple(SCENE_SPRITE.get(m['id'], {}).values())
            for mid in (m['id'], m.get('low'), m.get('sprite')) + extra:
                if not mid:
                    continue
                p = os.path.join(mdir, f'{mid}.png')
                if os.path.exists(p):
                    self.models[mid] = load_img(p)
        # 顾客素材：用户后续放入 assets/guests/*.png（64x64）即自动生效
        self.tasks = []
        gdir = os.path.join(ROOT, 'assets', 'guests')
        for p in sorted(glob.glob(os.path.join(gdir, '*.png'))):
            if os.path.basename(p).startswith('_'):
                continue
            try:
                self.tasks.append(load_img(p))
            except pygame.error:
                pass
        self.apartment = None
        self.shop = None
        for key, fn in (('apartment', 'apartment.png'), ('shop', 'shop.png')):
            fp = os.path.join(ROOT, 'assets', fn)
            if os.path.exists(fp):
                setattr(self, key, load_img(fp))
        self.apt_img = self.apartment            # 公寓原图（切场景时要还原）
        self.station = None
        fp = os.path.join(ROOT, 'assets', 'station.png')
        if os.path.exists(fp):
            self.station = load_img(fp)
        # 行走帧：<id>_walk1.png ...（侧面）
        self.walk = {}
        for m in MODELS:
            fr = []
            for i in range(1, 9):
                fp = os.path.join(mdir, f'{m["id"]}_walk{i}.png')
                if not os.path.exists(fp):
                    break
                fr.append(load_img(fp))
            if fr:
                self.walk[m['id']] = self._align_frames(fr)
        self._scaled = {}

    @staticmethod
    def _align_frames(frames):
        """把行走帧的水平重心对齐，避免逐帧左右抖动（看起来像抽搐）。
        用上半身（头/躯干）的重心，裙摆和手臂的摆动不参与计算。"""
        try:
            import numpy as np
        except ImportError:
            return frames
        centers = []
        for f in frames:
            a = pygame.surfarray.array_alpha(f)
            ys, xs = np.nonzero(a > 24)
            if len(xs) == 0:
                centers.append(f.get_width() / 2.0)
                continue
            sel = ys < f.get_height() * 0.55
            if sel.sum() > 12:
                xs = xs[sel]
            centers.append(float(xs.mean()))
        target = sum(centers) / len(centers)
        out = []
        for f, c in zip(frames, centers):
            dx = int(round(target - c))
            if dx == 0:
                out.append(f)
                continue
            n = pygame.Surface(f.get_size(), pygame.SRCALPHA)
            n.blit(f, (dx, 0))
            out.append(n)
        return out

    def model(self, mid):
        return self.models.get(mid)

    @staticmethod
    def sprite_id(st):
        """立绘选择：DeepSeek 按玩家要求对调（小模型用大图、大模型用小图），
        ChatGPT 保持原样（小模型小图、大模型大图）。"""
        main = SCENE_SPRITE.get(st.m['id'], {}).get(CUR_SCENE) \
            or st.m.get('sprite', st.m['id'])
        low = st.m.get('low')
        if not low:
            return main
        if st.m.get('swap_sprite'):
            return low if st.big else main
        return main if st.big else low

    def guest(self, i):
        if not self.tasks:
            return None
        return self.tasks[i % len(self.tasks)]

    def scaled(self, img, size):
        if img is None:
            return None
        k = (id(img), size)
        s = self._scaled.get(k)
        if s is None:
            s = pygame.transform.scale(img, (size, size))
            self._scaled[k] = s
        return s


# ---------------------------------------------------------------- 实体
class Station:
    """一条上游线路 + 一个工位。"""

    def __init__(self, m, idx):
        self.m = m
        self.idx = idx
        self.col, self.row = idx % 3, idx // 3
        self.tier = 1               # 订阅档位 1/2/3
        self.big = False            # 是否已单独升级成大模型
        self.gear = set()           # 装在这条线上的装备 id
        self.unlocked = m.get('unlock', 0) == 0        # 已解锁（装机）
        self.subscribed = m.get('unlock', 0) == 0      # 开局自带的线路默认已订阅
        self.forever = m.get('forever', False)   # 永久免费线路（豆包），不会到期
        self.no_fatigue = m.get('no_fatigue', False)  # 不累的（豆包：它守着铺子不干活）
        self.sub_days = (9999 if self.forever else
                         (SUB_DAYS if self.subscribed else 0))   # 预付订阅还剩几天
        self.quota = self.quota_cap() if self.subscribed else 0
        self.busy = None            # 正在服务的第 1 单
        self.busy2 = None           # 第 2 单（只有装了"便携式服务器"才有）
        self.prog = 0.0
        self.dur = 1.0
        self.limited = False        # 被上游限流中（速度只剩 20%，干完手头这单才解除）
        self.paused_job = False     # 玩家手动暂停了手上这单
        self.strain = 0.0           # 连续满负荷的"被盯上"进度 0~1，满了就限流
        self.strain_warned = False  # 这一轮是否已经提醒过
        self.slack = 0.0            # 摸鱼剩余秒（DeepSeek 煮大白饭）
        self.slack_cd = random.uniform(20.0, 70.0)   # 距离下次摸鱼的冷却
        self.snack = 0.0            # 零食加速剩余秒
        self.stuck = 0.0            # 宕机剩余秒
        self.shock = 0.0            # 上游涨价剩余秒
        self.cooldown = 0.0         # 重启冷却
        self.total_earn = 0.0
        self.done = 0
        self.flash = 0.0
        self.breakfast = 0.0        # 早餐加速剩余秒（8 个游戏小时）
        self.temp = TEMP_IDLE       # 核心温度：跑活升温，空闲降温，超过上限就宕机
        self.quota_pending = False  # 兼容旧存档留着的字段（现在不再使用）
        self.fatigue = 0.0          # 疲劳 0~1：连轴转会累，效率下降
        self.resting = False        # 今天休假（不接单，攒精力）
        self.rest_bonus = 0.0       # 休息过之后的一段时间效率加成

        pos = STANDS.get(m['id'])
        if pos:
            self.cx, self.feet = pos
        else:
            self.cx, self.feet = 400, 300
        self.px = float(self.cx)
        self.dir = 1
        self.anim_t = 0.0
        self.frame_i = 0
        self.walking = False            # 有行走帧时会在房间空地上踱步
        self.home_feet = self.feet      # 自己房间里的脚底位置（社交走开后要回来）
        self.social_state = 'home'      # home / walk / chat / back
        self.social_timer = random.uniform(18.0, 45.0)
        self.chat_line = ''             # 正在聊的那句话
        self.chat_x = float(self.cx)
        self.chat_y = float(self.feet)
        self.walk_path = []        # 要走的一串路点（门口、走道、目的地）
        self.social_dest = ''      # 这趟串门去哪儿
        self.at_key = m['id']      # 现在人在哪个房间（找最近的门口用）
        self.social_dest_key = m['id']
        self.walk_wait = random.uniform(1.0, 5.0)
        self.walk_span = random.uniform(1.5, 3.5)
        self.stop_blend = 0.0           # 刚停下时的过渡时间（避免姿势突跳）
        self.walk_idle = 0.0            # 走路卡住的秒数（看门狗用）
        self.walk_retry = 0             # 卡住后重新规划了几次
        self.duty = False               # 值班：维持科考站运转（不接单，省燃料）
        self.nap = 0.0                  # 在宿舍睡觉的剩余秒
        self.fish = 0.0                 # 出去抓鱼的剩余秒
        self.quest = None               # 正在做的科考任务：dict(kind=...)
        self.quest_t = 0.0              # 任务剩余秒
        self.quest_walk = 0.0           # 走了多久（兜底用）
        self.cooking = 0.0              # 正在做饭的剩余秒（做饭时不能被派单）
        self.meal = 0.0                 # 吃过饭的加速剩余秒
        self.meal_slot = 0              # 这一顿是午饭(12)还是晚饭(18)
        self.bond_boost = 0.0           # 和同事的默契加成（由 Game 每帧算）
        self.social_target = None       # 正在去找谁（station id）
        self.chat_partner = None        # 正在跟谁聊（station id）
        self.repath_t = 0.0             # 追人时多久重新规划一次

    # --- 派生属性 ---
    def tiers(self):
        return self.m.get('tiers', [('免费', 0, -1)])

    def tier_name(self):
        ts = self.tiers()
        return ts[min(self.tier, len(ts)) - 1][0]

    def is_small(self):
        """还没单独升级大模型：能力打折、接不了识图画图。"""
        return bool(self.m.get('low')) and not self.big

    def has_big(self):
        """这条线能不能单独升级成大模型。"""
        return bool(self.m.get('low')) and bool(self.m.get('big_price'))

    def has_tiers(self):
        return len(self.tiers()) > 1

    def blocked(self, typ):
        """小模型（还没换大模型）接不了的活，比如 DeepSeek 小不会画图识图。"""
        return self.is_small() and typ in self.m.get('small_block', ())

    def tier_price(self):
        """当前档位的每天订阅费。"""
        ts = self.tiers()
        return ts[min(self.tier, len(ts)) - 1][1]

    def quota_cap(self):
        """当天额度上限（-1 = 无限）。"""
        ts = self.tiers()
        cap = ts[min(self.tier, len(ts)) - 1][2]
        if cap >= 0 and self.has_gear('net'):
            cap = int(cap * 1.5)           # 扩展网口
        return cap

    def refresh_daily(self):
        """每天开门重置额度。"""
        self.quota = self.quota_cap() if self.subscribed else 0

    def on_grid(self):
        """豆包（Seed）在公寓守着铺子不接电，但在科考站是正常工位。"""
        return not self.m.get('nopower') or CUR_SCENE == 'station'

    def efficiency(self):
        """当前效率：累了会慢，休息过会快。"""
        return (1.0 - FATIGUE_PENALTY * self.fatigue) * (1.0 + self.rest_bonus)

    def spd(self, rhythm=True):
        v = self.m['spd'] * SPEED_K * self.efficiency()
        if self.has_gear('cpu'):
            v *= 1.20                     # 处理器（CPU）
        if self.has_gear('vpn_enc'):
            v *= 1.05                     # 加密 VPN 端口（同一条线只算一次）

        if self.breakfast > 0:
            v *= (1.0 + BREAKFAST_SPD)
        if self.meal > 0:
            v *= (1.0 + MEAL_BUFF)        # 千问做的饭
        v *= (1.0 + self.bond_boost)      # 和同事的默契
        if self.snack > 0:
            v *= (1.0 + SNACK_SPD)
        if self.m.get('rhythm') and rhythm:    # GLM 的作息（极夜=常夜）
            night = CUR_NIGHT or GAME_POLAR
            v *= GLM_NIGHT_SPD if night else GLM_DAY_SPD
        if self.is_small():
            v *= 0.75
        return v

    def quality(self, typ, task=None):
        if self.is_small():
            q = self.m['q'] * 0.85
        else:
            q = self.m['q']
        if typ in self.m['tags']:
            q += 0.11
        if task is not None and self.m.get('qjitter') and not self.has_gear('mem'):
            q *= getattr(task, 'qj', 0.90)     # Gemini：每单质量飘 5%~15%（记忆模块能消掉）
        return min(1.04, q)

    def qmean(self):
        """面板展示用的平均质量系数（带抖动的线路取中值）。"""
        j = self.m.get('qjitter')
        return (j[0] + j[1]) / 2 if j else 1.0

    def unit_cost(self):
        c = self.m['cost']
        if self.shock > 0:
            c *= 1.6
        return c

    def quota_cost(self, w):
        """这一单要吃多少额度：算力（速度）越低，同样的活越费额度。
        算额度时用"不带作息"的速度，GLM 的昼夜差异由 Game.quota_mult() 乘上去。"""
        return max(1, int(round(w * QUOTA_REF / max(1.0, self.spd(rhythm=False)))))

    def has_quota(self, w=QUOTA_MIN):
        return self.quota < 0 or self.quota >= w

    def jobs(self):
        """这条线手上正在跑的活（一到两单）。"""
        return [j for j in (self.busy, self.busy2) if j is not None]

    def free_slot(self):
        """还能不能再接一单：'busy' / 'busy2' / None。"""
        if self.busy is None:
            return 'busy'
        if self.busy2 is None and self.has_gear('dual'):
            return 'busy2'
        return None

    def has_gear(self, gid):
        return gid in self.gear

    def port_ok(self):
        """这条线要的出口端口装没装。

        need='vpn'     → VPN 或加密端口都行
        need='vpn_enc' → 必须加密端口（Claude）
        """
        need = self.m.get('need')
        if not need:
            return True
        if need == 'vpn_enc':
            return self.has_gear('vpn_enc')
        return self.has_gear('vpn') or self.has_gear('vpn_enc')

    def needs_port(self):
        return not self.port_ok()

    def at_home(self):
        """是否已经站在自己工位上（没在串门）。"""
        return (self.social_state == 'home'
                and abs(self.px - self.cx) < 8 and abs(self.feet - self.home_feet) < 8)

    def main_job(self):
        """主要那单（第二格在的时候用第二格兜底）。"""
        return self.busy if self.busy is not None else self.busy2

    def work_factor(self):
        """干活速度系数：被限流时剩 20%；一边煮大白饭时再慢 90%；站内没暖气再慢 40%。"""
        f = 1.0 - THROTTLE_SLOW if self.limited else 1.0
        if GAME_COLD:
            f *= 0.60
        if GAME_MEAL_PENALTY:
            f *= (1.0 - GAME_MEAL_PENALTY)   # 缺饭：当天就慢，吃到下一顿才恢复
        if self.slack > 0:
            f *= 0.10          # 心思全在锅上，效率只剩一成
        return f

    def ready(self):
        """被限流的线不接新单（等手头这单干完自动解除）；休假中也不接。"""
        return (self.unlocked and self.subscribed and not self.resting
                and self.cooking <= 0
                and not self.duty
                and self.port_ok()
                and self.free_slot() is not None
                and self.slack <= 0
                and self.has_quota()
                and not self.limited and self.stuck <= 0 and self.cooldown <= 0)

    def rect(self):
        return pygame.Rect(self.px - 32, self.feet - 70, 64, 78)


class Task:
    """一条从网上发来的 AI 任务请求。它不是一个走上门的人，
    而是从网关涌进来的一颗数据包：飞进待处理区悬浮、等被派单、
    处理完再飞回去。"""

    seq = 0

    def __init__(self, typ):
        Task.seq += 1
        self.uid = Task.seq
        info = TYPES[typ]
        self.typ = typ
        self.w = random.uniform(*info['w'])
        self.budget = random.uniform(*info['budget'])
        # 用户等得了多久：45 分钟 ~ 2.5 小时（游戏时间）
        # 别太短——队列只有 3 个位置，稍一忙不过来就撤单，声誉会一路崩
        self.patience_min = random.uniform(55, 165)
        self.patience = self.patience_min / GAME_MIN_PER_SEC
        self.wait = 0.0
        self.state = 'in'          # in 飞入 / queue 悬浮待处理 / service 处理中 / out 飞回
        self.slot = -1
        self.qj = random.uniform(0.85, 0.95)   # 这一单的质量运气（Gemini 会吃这个）
        self.contract = False      # 是不是长期合同派来的单
        self.multi = False         # 大单：需要多人协作
        self.crew = []             # 正在做这单的线路 id
        self.station = None
        self.dur = 1.0
        self.prog = 0.0
        self.qcost = 0.0            # 这一单总共要吃多少额度
        self.qspent = 0.0           # 这一单已经吃掉多少额度
        self.x, self.y = float(GATEWAY[0]), float(GATEWAY[1])
        # 目标就是客厅服务器（往里塞一点，让人看不出是排队位）
        self.tx = SERVER[0] + random.uniform(-7, 7)
        self.ty = SERVER[1] + random.uniform(-5, 5)
        self.bob = random.uniform(0, 6.28)
        self.fade = 255
        self.spawn_t = 0.0

    def move_to(self, x, y):
        self.tx, self.ty = x, y

    def update(self, dt):
        self.spawn_t += dt
        dx, dy = self.tx - self.x, self.ty - self.y
        d = math.hypot(dx, dy)
        if d > 0.6:
            # 数据包飞得快，带一点缓入
            v = min(300.0 * dt, d)
            self.x += dx / d * v
            self.y += dy / d * v + (0 if d < 40 else 0)
            return False
        self.x, self.y = self.tx, self.ty
        return True

    def mood(self):
        if self.state != 'queue':
            return 1.0
        return max(0.0, 1.0 - self.wait / self.patience)


# ---------------------------------------------------------------- 背景音乐
class Sfx:
    """极简音效：用正弦/方波现场合成，不依赖素材文件。"""

    def __init__(self):
        self.ok = False
        self.sounds = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(22050, -16, 1, 512)
            self._build()
            self.ok = True
        except Exception:
            self.ok = False

    def _tone(self, freq, ms, vol=0.25, kind='sin'):
        import array, math
        rate = 22050
        n = int(rate * ms / 1000)
        buf = array.array('h')
        for i in range(n):
            t = i / rate
            env = min(1.0, i / 80) * max(0.0, 1.0 - i / n)
            if kind == 'square':
                v = 1.0 if math.sin(2 * math.pi * freq * t) > 0 else -1.0
            else:
                v = math.sin(2 * math.pi * freq * t)
            buf.append(int(max(-1, min(1, v)) * env * vol * 32767))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _build(self):
        self.sounds = dict(
            click=self._tone(660, 45, 0.18),
            ok=self._tone(880, 90, 0.22),
            coin=self._tone(1180, 120, 0.22),
            fail=self._tone(180, 180, 0.25, 'square'),
            meal=self._tone(520, 140, 0.20),
        )

    def play(self, name):
        if not self.ok:
            return
        try:
            snd = self.sounds.get(name)
            if snd is not None:
                snd.play()
        except Exception:
            pass


class Music:
    """背景音乐：assets/music/ 里放一首就自动循环播放。

    macOS 的 mixer 初始化可能失败（没声卡/无权限），这里全部 try 掉，
    失败就静音运行，不影响游戏。
    """

    def __init__(self, settings):
        self.settings = settings
        self.ok = False
        self.track = ''
        self.path = find_music()
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
            self.ok = pygame.mixer.get_init() is not None
        except pygame.error:
            self.ok = False
        if not (self.ok and self.path):
            return
        try:
            pygame.mixer.music.load(self.path)
            self.track = os.path.basename(self.path)
        except pygame.error:
            self.ok = False
            return
        self.apply(play=True)

    def apply(self, play=False):
        if not self.ok:
            return
        try:
            pygame.mixer.music.set_volume(float(self.settings.get('volume', 0.6)))
        except pygame.error:
            pass
        try:
            if self.settings.get('music'):
                if play or not pygame.mixer.music.get_busy():
                    pygame.mixer.music.play(-1)
                else:
                    pygame.mixer.music.unpause()
            else:
                pygame.mixer.music.pause()
        except pygame.error:
            pass

    def toggle(self):
        self.settings['music'] = 0 if self.settings.get('music') else 1
        save_settings(self.settings)
        self.apply()

    def set_volume(self, v):
        self.settings['volume'] = max(0.0, min(1.0, float(v)))
        save_settings(self.settings)
        self.apply()

    def bump(self, delta):
        steps = round(self.settings.get('volume', 0.6) * 10 + delta)
        self.set_volume(max(0, min(10, steps)) / 10.0)

    def pause(self):
        """切到桌面时把音乐也停下（回来再续上）。"""
        if not self.ok:
            return
        try:
            pygame.mixer.music.pause()
        except pygame.error:
            pass

    def resume(self):
        if not self.ok or not self.settings.get('music'):
            return
        try:
            pygame.mixer.music.unpause()
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.play(-1)
        except pygame.error:
            pass


# ---------------------------------------------------------------- 行走掩码
WALKMASK_PATH = os.path.join(ROOT, 'assets', 'walkmask.json')


def walkmask_path():
    """掩码路径：默认 assets/walkmask.json，自测可以用 AIHUB_WALKMASK 指到别处。"""
    return os.environ.get('AIHUB_WALKMASK') or WALKMASK_PATH


class WalkMask:
    """用 tools/map_editor.py 画出来的行走网格：哪些格子是墙。

    有掩码时，串门/回家直接在这张网格上跑 A*；没有掩码就退回原来的
    「门口 + 走道」路线（walk_route_doors 的老逻辑）。
    """

    def __init__(self, walls, cell=16, cols=60, rows=45):
        self.walls = set(walls)
        self.cell = cell
        self.cols = cols
        self.rows = rows

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            return cls({(int(x), int(y)) for x, y in d.get('walls', [])},
                       int(d.get('cell', 16)), int(d.get('cols', 60)),
                       int(d.get('rows', 45)))
        except (OSError, ValueError, TypeError):
            return None

    def free(self, cx, cy):
        return (0 <= cx < self.cols and 0 <= cy < self.rows
                and (cx, cy) not in self.walls)

    def unblock_cell(self, cx, cy):
        """把一格及其四邻清成可走（工位/网关/电闸脚下必须能站人）。"""
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            self.walls.discard((cx + dx, cy + dy))

    def cell_of(self, px, py):
        return (int(px // self.cell), int(py // self.cell))

    def center(self, cx, cy):
        return (cx * self.cell + self.cell / 2.0,
                cy * self.cell + self.cell / 2.0)

    def nearest_free(self, cx, cy, radius=3):
        """站在墙格里时，找最近的空格当起点/终点。"""
        if self.free(cx, cy):
            return (cx, cy)
        best, bd = None, 1e9
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                nx, ny = cx + dx, cy + dy
                if self.free(nx, ny):
                    d = dx * dx + dy * dy
                    if d < bd:
                        best, bd = (nx, ny), d
        return best

    def astar(self, start, goal):
        """在格子上找一条四邻路径，返回格子列表（含首尾）。"""
        import heapq
        start = self.nearest_free(*start)
        goal = self.nearest_free(*goal)
        if start is None or goal is None:
            return None
        if start == goal:
            return [start]
        openq = [(0.0, 0.0, start)]
        came = {start: None}
        cost = {start: 0.0}
        while openq:
            _, g, cur = heapq.heappop(openq)
            if cur == goal:
                path = []
                while cur is not None:
                    path.append(cur)
                    cur = came[cur]
                return path[::-1]
            if g > cost.get(cur, 1e9) + 1e-9:
                continue
            cx, cy = cur
            for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if not self.free(nx, ny):
                    continue
                ng = g + 1.0
                if ng < cost.get((nx, ny), 1e9):
                    cost[(nx, ny)] = ng
                    came[(nx, ny)] = cur
                    h = abs(nx - goal[0]) + abs(ny - goal[1])
                    heapq.heappush(openq, (ng + h, ng, (nx, ny)))
        return None

    def _seg_clear(self, a, b):
        """一条直线段是否全程落在可走格里。"""
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 4))
        for i in range(n + 1):
            x = a[0] + (b[0] - a[0]) * i / n
            y = a[1] + (b[1] - a[1]) * i / n
            if not self.free(*self.cell_of(x, y)):
                return False
        return True

    def clear_line(self, a, b):
        """a→b 能不能直接连。

        角色实际是"先横后竖"（撞墙再试"先竖后横"）走的，所以光看斜线不够：
        斜线不穿墙不代表那个 L 形不撞墙。这里要求两条 L 里至少有一条通。
        """
        if not self._seg_clear(a, b):
            return False
        lx, ly = (b[0], a[1]), (a[0], b[1])
        first = self._seg_clear(a, lx) and self._seg_clear(lx, b)
        second = self._seg_clear(a, ly) and self._seg_clear(ly, b)
        return first or second

    def route(self, start_px, goal_px):
        """像素坐标进、像素路点出（首尾就是起点和终点）。"""
        cells = self.astar(self.cell_of(*start_px), self.cell_of(*goal_px))
        if not cells:
            return None
        pts = [self.center(cx, cy) for cx, cy in cells]
        goal_free = self.free(*self.cell_of(*goal_px))
        # 只合并"同方向"的连续格心：跨格拉直线会把折线拉成穿墙的斜段
        # （角色是先横后竖走的，斜线不穿墙不代表 L 形不撞墙）
        simp = [pts[0]]
        for k in range(1, len(pts) - 1):
            ax, ay = simp[-1]
            bx, by = pts[k]
            cx2, cy2 = pts[k + 1]
            if (bx - ax) * (cy2 - by) == (by - ay) * (cx2 - bx):
                continue
            simp.append(pts[k])
        if len(pts) > 1:
            simp.append(pts[-1])
        out = [tuple(start_px)] + simp
        out.append(tuple(goal_px) if goal_free else pts[-1])
        return out



# ---------------------------------------------------------------- 游戏主体
class Game:
    def __init__(self):
        os.environ.setdefault('SDL_VIDEO_CENTERED', '1')
        pygame.init()
        pygame.display.set_caption('AI 中转站  ·  像素经营')
        self.settings = load_settings()
        self.fullscreen = bool(self.settings.get('fullscreen'))
        # 真正的窗口叫 display；所有绘制都画在固定 1280x720 的 canvas 上，
        # 最后整张缩放到窗口（全屏时等比放大、上下留黑边），这样任何分辨率都不会被裁。
        self.display = pygame.display.set_mode((SW, SH))
        self.screen = pygame.Surface((SW, SH)).convert()
        self.slot = 1                 # 当前存档位（1~SLOT_COUNT）
        self.away_paused = False      # 是不是因为切到桌面而自动暂停的
        self.frame_i = 0              # 主循环帧计数（启动时跳过焦点检查）
        self.music = Music(self.settings)
        self.sfx = Sfx()
        if self.fullscreen:
            self.apply_display()
        icon = os.path.join(ROOT, 'assets', 'models', 'DeepSeek.png')
        if os.path.exists(icon):
            try:
                pygame.display.set_icon(pygame.image.load(icon))
            except pygame.error:
                pass
        self.world = pygame.Surface((WW, WH)).convert()
        self.fx = pygame.Surface((WW, WH), pygame.SRCALPHA)
        self.clock = pygame.time.Clock()
        self.assets = Assets()
        global CUR_SCENE
        apply_scene_geo('apartment')                      # 新开一局先回到公寓坐标
        CUR_SCENE = 'apartment'
        self.scene = 'apartment'                          # apartment / station
        COOK_POINT = (620, 100)
        self.walkmask = WalkMask.load(walkmask_path())   # 没有掩码就是 None（用老路线）
        self.running = True
        self.state = 'title'        # title / play / over
        self.panel = None           # ('assign', guest) ('station', st) ('summary', d) ('over', d)
        self.mouse = (0, 0)
        self.zoom = 1.0             # 场景缩放（滚轮）
        self.cam = [WW / 2.0, WH / 2.0]   # 镜头中心（世界坐标）
        self.drag = None            # 右键拖动时的起始位置
        self.paused = False
        self.speed = 1
        self.hover_guest = None
        self.hover_station = None
        self.texts = []
        self.particles = []
        self.toast = None           # (text, life, color)
        self.has_save = any(os.path.exists(save_path(i)) for i in range(1, SLOT_COUNT + 1))
        self.breakfast_day = -1     # 哪一天买过早餐（当天只能买一次）
        self.reset()

    # ------------------------------------------------ 显示 / 存档位
    # ------------------------------------------------ 场景（公寓 / 科考站）
    def set_scene(self, name, place=True):
        """切场景：换坐标表、换背景、换掩码，必要时把人重新摆好。"""
        global CUR_SCENE
        self.scene = 'station' if name == 'station' else 'apartment'
        CUR_SCENE = self.scene
        apply_scene_geo(self.scene)
        self.assets.apartment = (self.assets.station
                                 if self.scene == 'station' and self.assets.station
                                 else self.assets.apt_img)
        path = STATION_MASK if self.scene == 'station' else walkmask_path()
        self.walkmask = WalkMask.load(path) if os.path.exists(path) else None
        if self.scene == 'apartment' and not self.seen_apt_intro and INTRO_ON:
            self.seen_apt_intro = True
            self.panel = ('intro', 'apt')
        if self.scene == 'station' and INTRO_ON and not self.seen_station_intro:
            self.seen_station_intro = True
            self.show_comic([3], to_intro=True)
        if self.scene == 'station' and not self.seen_station_intro and INTRO_ON:
            self.seen_station_intro = True
            self.panel = ('intro', None)
        if self.walkmask:
            for p in list(STANDS.values()) + list(DOORS.values()):
                self.walkmask.unblock_cell(*self.walkmask.cell_of(p[0], p[1]))
            for p in (GATEWAY, BREAKER, SERVER):
                self.walkmask.unblock_cell(*self.walkmask.cell_of(p[0], p[1]))
        if place:
            for st in self.stations:
                pos = STANDS.get(st.m['id'], (400, 300))
                st.cx, st.feet = pos
                st.px = float(pos[0])
                st.dir = 1
                st.home_feet = pos[1]
                st.at_key = st.m['id']
                st.social_state = 'home'
                st.walk_path = []
                st.social_target = None
                st.chat_partner = None
                st.chat_line = ''
                st.social_timer = random.uniform(6.0, 18.0)

    def big_ready(self):
        ds = self.station_by_id('DeepSeek')
        cg = self.station_by_id('ChatGPT')
        return bool(ds and ds.big and cg and cg.big)

    def can_relocate(self):
        return (self.scene == 'apartment' and self.money >= RELOCATE_COST
                and self.day >= RELOCATE_DAY and self.big_ready()
                and self.day >= getattr(self, 'relocate_snooze', 0))

    def relocate(self):
        """搬去南极：扣搬迁费、换场景，人和订阅都带过去。"""
        if not self.can_relocate():
            return False
        self.money -= RELOCATE_COST
        if self.rewards:                 # 公寓没领的奖励，搬迁时直接算给你，别卡住南极目标
            self.claim_rewards()
        self.set_scene('station')
        self.toast_msg('搬进了南极科考站 · 新机房已通电', C_GOLD, 4.0)
        self.log(f'搬到南极科考站，搬迁费 ¥{RELOCATE_COST}', C_GOLD)
        self.log('房子退了，8 条线路和装备都装箱运过来了', (180, 190, 210))
        self.panel = ('stage', self.stage_stats())   # 公寓阶段结算
        if not INTRO_ON:
            self.panel = None
        self.save()
        return True

    def apply_display(self):
        try:
            if self.fullscreen:
                self.display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.display = pygame.display.set_mode((SW, SH))
        except pygame.error:
            self.fullscreen = False
            self.settings['fullscreen'] = 0
            save_settings(self.settings)
            self.display = pygame.display.set_mode((SW, SH))

    def present(self):
        """把 1280x720 的画布等比贴到窗口上（全屏时居中留黑边）。"""
        dw, dh = self.display.get_size()
        if (dw, dh) == (SW, SH):
            self.display.blit(self.screen, (0, 0))
        else:
            k = min(dw / SW, dh / SH)
            w, h = max(1, int(SW * k)), max(1, int(SH * k))
            self.display.fill((0, 0, 0))
            self.display.blit(pygame.transform.smoothscale(self.screen, (w, h)),
                              ((dw - w) // 2, (dh - h) // 2))
        pygame.display.flip()

    def map_mouse(self, pos):
        """窗口坐标 -> 画布坐标（窗口不是 1280x720 时要换算）。"""
        dw, dh = self.display.get_size()
        if (dw, dh) == (SW, SH):
            return (int(pos[0]), int(pos[1]))
        k = min(dw / SW, dh / SH)
        ox, oy = (dw - SW * k) / 2.0, (dh - SH * k) / 2.0
        return (int((pos[0] - ox) / k), int((pos[1] - oy) / k))

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.settings['fullscreen'] = 1 if self.fullscreen else 0
        save_settings(self.settings)
        self.apply_display()
        self.toast_msg('全屏：开（F11 切回）' if self.fullscreen else '全屏：关',
                       C_BLUE, 1.8)

    def window_active(self):
        """窗口现在是不是在前台。

        事件（WINDOWFOCUSLOST）在某些 macOS/全屏组合下不一定送到，所以
        主循环里每帧再主动问一次键盘焦点，双保险。
        """
        try:
            return bool(pygame.key.get_focused())
        except pygame.error:
            return True

    def check_focus(self, active=None):
        if active is None:
            active = self.window_active()
        if self.state != 'play':
            return
        if not active and not self.paused and not self.panel:
            self.set_away(True)
        elif active and self.away_paused:
            self.set_away(False)

    def go_title(self):
        """回首页：把游戏里所有临时提示清干净（标题页没有 update，留着就永远不走）。"""
        self.state = 'title'
        self.panel = None
        self.paused = False
        self.away_paused = False
        self.toast = None
        self.event = None
        self.texts.clear()
        self.particles.clear()

    def set_away(self, away):
        """窗口切到后台 / 最小化时的处理。

        系统会把后台进程降频，游戏时间还在慢慢走，提示条按帧计时就会出现
        "回到桌面十分钟，回来'早餐铺开业'还挂着"。所以直接暂停整局，
        并把已经弹出的即时提示清掉，回来干干净净。
        """
        if away:
            if self.state == 'play' and not self.paused and not self.panel:
                self.paused = True
                self.away_paused = True
            # 人不在，屏幕上的临时提示全清掉：回来不该还挂着"早餐铺开业"
            self.toast = None
            self.event = None
            self.texts.clear()
            self.particles.clear()
            self.music.pause()
        else:
            if self.away_paused:
                self.away_paused = False
                self.paused = False
            self.toast = None
            self.music.resume()

    @staticmethod
    def save_exists(slot=1):
        return os.path.exists(save_path(slot))

    # ------------------------------------------------ 初始化 / 重置
    def reset(self):
        global CUR_NIGHT
        CUR_NIGHT = False
        self.day = 1
        self.money = 1500.0
        self.rep = 26.0
        self.t_rev = 0.0
        self.t_cost = 0.0
        self.price_idx = 2
        self.stations = [Station(m, i) for i, m in enumerate(MODELS)]
        self.tasks = []
        self.t = 0.0                # 当日秒（一个周期 = 08:00 → 次日 08:00）
        self.settled = False        # 这一轮 24:00 结过账没
        self.last_net = 0.0         # 上一日净利
        self.last_day = None        # 上一日账本
        self.t_orders = 0           # 当日接单数
        self.t_expired = 0          # 当日超时数
        self.t_trips = 0            # 当日跳闸数
        self.t_crashes = 0          # 当日过热宕机数
        self.t_throttles = 0        # 当日被限流数
        self.t_abandon = 0          # 当日主动放弃的单
        self.t_reject = 0           # 当日退回的单
        self.t_reset_cards = 0      # 当日买的重置卡
        self.snacks = SNACK_STOCK   # 冰箱里的零食份数
        self.spawn_timer = 2.0
        self.logs = []
        self.particles.clear()
        self.texts.clear()
        self.event = None           # dict(kind, name, left)
        self.burst = 0.0
        self.history = []
        self.last_stars = []
        self.breakfast_day = -1
        self.breaker_lv = 1
        self.gw_lv = 1
        self.ad_days = 0
        self.tripped = 0.0
        self.overload_t = 0.0
        self.t_quota_break = 0
        self.intake = True          # 网关是否接新单
        self.rest_day = False       # 今天全员休息（所有线路一起休）
        self.bag = {}               # 背包：道具 id -> 数量（装备 'cpu'... / 重置卡 'reset:<线路>'）
        self.held_item = None       # 点起来的道具（等一个 AI 接）
        self.drag_item = None       # 正在拖拽的道具
        self.drag_pos = (0, 0)
        self.drag_start = (0, 0)
        self.drag_moved = False
        self.bf_notice_day = -1     # 今天有没有提示过早餐铺开张
        self.pending_tier = None    # 换档二次确认用的状态
        self.encounter_cd = {}      # 路上相遇的冷却：(id_a,id_b) -> 秒
        self.meal_done = set()      # 今天已经做过的饭点
        self.bonds = {}             # (id_a,id_b) -> 好感 -1~1
        self.delivered = {}         # 类型 -> 累计交付单数
        self.contract = None        # 长期合同
        self.contract_offer = None  # 待确认的合同报价
        self.relations_back = None  # 关系面板从哪来（关掉回哪）
        self.relocate_snooze = 0    # "再等等"之后隔几天再提搬迁
        self.fuel = 0.0             # 科考站供暖燃料
        self.warehouse = {'food': 0, 'fuel': 0, 'snack': 0}   # 仓库库存
        self.pending_supply = []    # 已下单、等补给船送来的物资
        self.meals_today = 0        # 今天吃了几顿（三餐强制）
        self.meal_nag = set()       # 已经提醒过的饭点（别刷屏）
        self.quest_day = 0
        self.weather = [0, 0]       # 0 未发布 / 1 待接 / 2 进行中 / 3 已完成
        self.weather_at = [10.0, 16.0]   # 今天两趟的发布时刻（随机）
        self.quest_sel = None       # 服务器里选中的科考任务
        self.auto_dispatch = False  # 自动派单开关
        self.seen_station_intro = False   # 第一次进科考站弹说明
        self.seen_apt_intro = False       # 第一次进游戏弹公寓说明
        self.main_step = 0                # 主线进度
        self.rewards = []                 # 待领取的主线奖励
        self.comic_list = []              # 本次要放的漫画帧
        self.comic_i = 0
        self.pending_intro = False        # 放完漫画接指南
        self.comic2_done = False          # 「越做越大」放过没
        self.comic3_done = False          # 「一张船票」放过没
        self.south_step = 0               # 南极阶段主线进度
        self.south_weather = 0            # 南极累计完成的气象任务
        self.south_ice = 0                # 南极累计完成的冰样任务
        self.south_days = 0               # 在南极撑过的天数
        self.weather_ev = None            # 当前随机事件 (kind, 结束天)
        self.loan = 0.0                   # 银行欠款
        self.ach_seen = set()             # 已解锁成就（只用于弹提示）
        self.cutscene = None              # 新线路搬进来的演出
        self.rest_left = 0.0              # 剩余休息小时
        self.daily_goals = []             # 今日小目标
        self.goals_done = 0               # 今天完成了几个
        self.story_seen = False           # 开场序章看过没
        self.pending_gear = []      # 已下单、随补给到货的装备
        self.ice = 0                # 0 空闲 / 1 流程进行中
        self.ice_done = -1          # 最近一次冰样完成的日子（统计用）
        self.quest_last = {}        # 每种科考任务上次开始的时刻（小时）
        self.ice_runs = 0           # 今天跑了几趟冰样
        self.meal_penalty = 0.0     # 缺饭减速：当天生效，吃到下一顿才恢复
        self.meal_missed = 0        # 连续错过的顿数
        self.cold = False           # 燃料断了：站内偏冷
        if getattr(self, 'stations', None):
            self.init_bonds()
        self.meal_day = 0           # 上面这个集合是哪一天的
        self.rent_notice_on = True  # 房租前一天弹窗（自测/模拟里关掉）
        self.panel = None
        self.paused = False
        self.speed = 1
        if self.walkmask is not None:
            # 掩码可能把工位脚下涂成墙：那 AI 就永远"走不到工位"、永远不开工。
            # 这里把工位、网关、电闸脚下清出来，保证这些点一定站得住人。
            for st in self.stations:
                self.walkmask.unblock_cell(*self.walkmask.cell_of(st.cx, st.home_feet))
            for x, y in (GATEWAY, BREAKER):
                self.walkmask.unblock_cell(*self.walkmask.cell_of(x, y))

        self.log('开张了。先看看网关那边压了多少单。', C_BLUE)

    # ------------------------------------------------ 工具
    @property
    def price_mult(self):
        return PRICE_STEPS[self.price_idx]

    def log(self, s, color=C_DIM):
        self.logs.append((s, color))
        if len(self.logs) > 40:
            self.logs.pop(0)

    def toast_msg(self, s, color=C_GOLD, life=2.6):
        self.toast = [s, life, color]

    def queued_tasks(self):
        return sorted([g for g in self.tasks if g.state in ('in', 'stored')],
                      key=lambda g: g.uid)

    def unlocked(self):
        """能接单的线路（已解锁 + 已订阅）。"""
        return [s for s in self.stations if s.unlocked and s.subscribed]

    def rent_due(self):
        """今天打烊要不要给房东交房租。"""
        return self.day % RENT_EVERY == 0

    def rent_left(self):
        """距离下次收租还有几天（0 = 今天）。"""
        if self.rent_due():
            return 0
        return RENT_EVERY - self.day % RENT_EVERY

    def owned_gear_count(self, gid):
        """这件装备一共有几件（背包里 + 装在身上的）。"""
        n = self.bag_count(gid)
        n += sum(1 for st in self.stations if gid in st.gear)
        return n

    def port_week_fee(self):
        """VPN 端口的周费：只算**装在线路上**的，躺在背包里不收费。"""
        n_vpn = sum(1 for st in self.stations if 'vpn' in st.gear)
        n_enc = sum(1 for st in self.stations if 'vpn_enc' in st.gear)
        return VPN_WEEK * n_vpn + VPN_ENC_WEEK * n_enc

    def daily_fixed(self):
        """当天要扣的房租 / 电费 / 工资 / 端口周费（订阅是 7 天预付的，当天不再扣）。"""
        live = [st for st in self.stations if st.subscribed]
        power = POWER_PER * len(live)
        wage = sum(WAGE_PER_LV * st.tier for st in live)
        subs = 0
        rent = RENT_WEEK if (self.rent_due() and self.scene == 'apartment') else 0
        port = self.port_week_fee() if self.rent_due() else 0
        return rent, power, wage, subs, port

    def sub_soon(self):
        """最近一条要到期的订阅还剩几天（0 = 都没订阅）。"""
        days = [st.sub_days for st in self.stations if st.subscribed and st.sub_days > 0]
        return min(days) if days else 0

    def net_worth(self):
        v = self.money
        for st in self.stations:
            if st.unlocked:
                v += st.m.get('unlock', 0) * 0.5
            if st.subscribed:
                v += st.tier_price() * max(1, st.sub_days) * 0.8   # 预付还没用完的价值
        return v

    def hour_f(self):
        """当前是几点（浮点，0~24）。"""
        return (HOUR_START + DAY_HOURS * min(1.0, self.t / DAY_LEN)) % 24

    def clock_text(self):
        h = self.hour_f()
        hh = int(h)
        return f'{hh:02d}:{int((h - hh) * 60):02d}'

    def is_night(self):
        """23:00 ~ 次日 08:00：算力便宜，接单只扣一半额度。"""
        h = self.hour_f()
        return h >= NIGHT_START or h < NIGHT_END

    def quota_factor(self, st=None):
        if GAME_POLAR:
            # 极夜：GLM 照拿夜间折扣，其他人没有
            if st is not None and st.m.get('rhythm'):
                return NIGHT_COST
            return 1.0
        return NIGHT_COST if self.is_night() else 1.0

    def quota_mult(self, st):
        """这条线路这一单的额度倍率（夜间半价 + GLM 作息；极夜按夜算）。"""
        night = self.is_night() or (GAME_POLAR and bool(st.m.get('rhythm')))
        f = self.quota_factor(st)
        if st.m.get('rhythm'):
            return f * GLM_NIGHT_QUOTA if night else GLM_DAY_QUOTA
        return f

    def quota_need(self, st, w):
        """这一单实际要吃多少额度（含夜间/GLM 作息/线路自己的折扣）。"""
        base = st.quota_cost(w) * self.quota_mult(st)
        return max(1, int(round(base * st.m.get('qdisc', 1.0))))

    # ------------------------------------------------ 存档
    def clock_at(self, t):
        """把时间轴上的秒数换成 "HH:MM"（存档里也存一份，方便看）。"""
        h = (HOUR_START + DAY_HOURS * min(1.0, max(0.0, t) / DAY_LEN)) % 24
        return f'{int(h):02d}:{int((h - int(h)) * 60):02d}'

    def save(self):
        self.has_save = True
        # 时间轴按「游戏分钟」取整：存到分钟，读档从原地继续
        t_save = round(round(self.t * GAME_MIN_PER_SEC) / GAME_MIN_PER_SEC, 3)
        data = dict(
            v=2,
            day=self.day,
            t=t_save,
            clock=self.clock_at(t_save),
            settled=self.settled,
            money=self.money, rep=self.rep, price_idx=self.price_idx,
            snacks=self.snacks, bag=self.bag,
            gw_lv=self.gw_lv, breaker_lv=self.breaker_lv, ad_days=self.ad_days,
            intake=self.intake, rest_day=self.rest_day,
            burst=round(self.burst, 2),
            event=self.event,
            last_day=self.last_day,
            last_stars=self.last_stars[-12:],
            breakfast_day=self.breakfast_day,
            main_step=self.main_step, rewards=self.rewards,
            south_step=self.south_step, south_weather=self.south_weather,
            south_ice=self.south_ice, south_days=self.south_days,
            loan=round(self.loan, 1), weather_ev=self.weather_ev,
            ach=sorted(self.ach_seen),
            comic2=self.comic2_done, comic3=self.comic3_done,
            ice_runs=self.ice_runs, ice_done=self.ice_done,
            weather=self.weather, and_weather_at=self.weather_at,
            quest_last={k: round(v, 2) for k, v in self.quest_last.items()},
            rest_left=round(self.rest_left, 2),
            bf_notice_day=self.bf_notice_day,
            meal_day=self.meal_day, meal_done=sorted(self.meal_done),
            fuel=round(self.fuel, 1), cold=bool(self.cold),
            warehouse=self.warehouse, pending=list(self.pending_supply),
            duty=[st.m['id'] for st in self.stations if st.duty],
            bonds=[[a, b, round(v, 3)] for (a, b), v in self.bonds.items()],
            delivered=self.delivered, contract=self.contract,
            today=dict(rev=self.t_rev, cost=self.t_cost, orders=self.t_orders,
                       expired=self.t_expired, trips=self.t_trips,
                       crashes=self.t_crashes, throttles=self.t_throttles,
                       abandon=self.t_abandon, reject=self.t_reject,
                       reset=self.t_reset_cards, qbreak=self.t_quota_break),
            st=[dict(tier=s.tier, un=s.unlocked, sb=s.subscribed, sd=s.sub_days,
                     big=s.big, gear=sorted(s.gear),
                     earn=s.total_earn, done=s.done,
                     quota=round(s.quota, 1),
                     temp=round(s.temp, 2), strain=round(s.strain, 3),
                     fat=round(s.fatigue, 3), rb=round(s.rest_bonus, 3),
                     snack=round(s.snack, 1), breakfast=round(s.breakfast, 1),
                     cook=round(s.cooking, 1), meal=round(s.meal, 1),
                     mslot=s.meal_slot,
                     slack=round(s.slack, 1), stuck=round(s.stuck, 1),
                     limited=bool(s.limited), paused=bool(s.paused_job),
                     resting=bool(s.resting), warn=bool(s.strain_warned))
                for s in self.stations],
            history=self.history, scene=self.scene)
        try:
            with open(save_path(self.slot), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError:
            pass

    def peek_save(self, slot=1):
        """只看一眼存档（标题界面用），不改变当前局。"""
        try:
            with open(save_path(slot)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def load(self, slot=1):
        try:
            with open(save_path(slot)) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        self.slot = slot
        self.reset()
        self.day = d.get('day', 1)
        self.money = d.get('money', 1400.0)
        self.rep = d.get('rep', 38.0)
        self.price_idx = d.get('price_idx', 2)
        self.snacks = d.get('snacks', SNACK_STOCK)
        self.history = d.get('history', [])
        self.bag = {k: int(v) for k, v in d.get('bag', {}).items() if int(v) > 0}
        # 旧存档没有背包：把「买了还没装」的装备补进背包，别让它们凭空消失
        for gid, owner in d.get('gear_owner', {}).items():
            if owner is None:
                self.bag[gid] = self.bag.get(gid, 0) + 1
        self.gw_lv = max(1, min(5, d.get('gw_lv', 1)))
        self.breaker_lv = max(1, min(5, d.get('breaker_lv', 1)))
        self.ad_days = max(0, d.get('ad_days', 0))
        # ---- v2：当天的时间轴与运行态（老存档没有这些，按 08:00 全新一天处理） ----
        self.t = max(0.0, min(DAY_LEN - 0.01, float(d.get('t', 0.0))))
        self.settled = bool(d.get('settled', self.t >= self.settle_point()))
        self.intake = bool(d.get('intake', True))
        self.rest_day = bool(d.get('rest_day', False))
        self.burst = max(0.0, float(d.get('burst', 0.0)))
        ev = d.get('event')
        self.event = ev if isinstance(ev, dict) else None
        ld = d.get('last_day')
        self.last_day = ld if isinstance(ld, dict) else None
        self.last_stars = [int(x) for x in (d.get('last_stars') or [])][-12:]
        self.breakfast_day = int(d.get('breakfast_day', -1))
        self.main_step = int(d.get('main_step', 0))
        self.south_step = int(d.get('south_step', 0))
        self.south_weather = int(d.get('south_weather', 0))
        self.south_ice = int(d.get('south_ice', 0))
        self.south_days = int(d.get('south_days', 0))
        self.loan = float(d.get('loan', 0.0))
        ev = d.get('weather_ev')
        self.weather_ev = tuple(ev) if isinstance(ev, (list, tuple)) and len(ev) == 2 else None
        self.ach_seen = set(d.get('ach') or [])
        self.rewards = [tuple(x) for x in (d.get('rewards') or [])]
        self.comic2_done = bool(d.get('comic2', False))
        self.comic3_done = bool(d.get('comic3', False))
        self.ice_runs = int(d.get('ice_runs', 0))
        self.ice_done = int(d.get('ice_done', -1))
        self.weather = list(d.get('weather') or [0, 0])[:2]
        self.weather_at = list(d.get('and_weather_at') or [10.0, 16.0])[:2]
        self.quest_last = {k: float(v) for k, v in (d.get('quest_last') or {}).items()}
        self.rest_left = float(d.get('rest_left', 0.0))
        self.bf_notice_day = int(d.get('bf_notice_day', -1))
        self.fuel = float(d.get('fuel', 0.0))
        self.cold = bool(d.get('cold', False))
        wh = d.get('warehouse') or {}
        self.warehouse = {k: int(wh.get(k, 0)) for k in ('food', 'fuel', 'snack')}
        self.pending_supply = list(d.get('pending') or [])
        duty = set(d.get('duty') or [])
        for st in self.stations:
            st.duty = st.m['id'] in duty
        self.meal_day = int(d.get('meal_day', 0))
        self.meal_done = set(int(x) for x in (d.get('meal_done') or []))
        self.bonds = {(str(a), str(b)): float(v)
                      for a, b, v in (d.get('bonds') or [])}
        self.init_bonds(keep=True)     # 老存档没记过的组合补初始好感
        self.delivered = {str(k): int(v) for k, v in (d.get('delivered') or {}).items()}
        c = d.get('contract')
        self.contract = c if isinstance(c, dict) else None
        today = d.get('today') or {}
        self.t_rev = float(today.get('rev', 0.0))
        self.t_cost = float(today.get('cost', 0.0))
        self.t_orders = int(today.get('orders', 0))
        self.t_expired = int(today.get('expired', 0))
        self.t_trips = int(today.get('trips', 0))
        self.t_crashes = int(today.get('crashes', 0))
        self.t_throttles = int(today.get('throttles', 0))
        self.t_abandon = int(today.get('abandon', 0))
        self.t_reject = int(today.get('reject', 0))
        self.t_reset_cards = int(today.get('reset', 0))
        self.t_quota_break = int(today.get('qbreak', 0))
        for s, sd in zip(self.stations, d.get('st', [])):
            # 旧存档（lv 1~5）迁移到三档：Lv5 -> 3，Lv3~4 -> 2，其余 -> 1
            if 'tier' in sd:
                s.tier = sd.get('tier', 1)
            else:
                lv = sd.get('lv', 1)
                s.tier = 3 if lv >= 5 else (2 if lv >= 3 else 1)
            s.tier = max(1, min(s.tier, len(s.tiers())))
            s.unlocked = sd.get('un', False)
            s.subscribed = sd.get('sb', False)
            # 订阅剩余天数也要存回来：老档没这一项就按「刚买 7 天」补，别当晚就到期
            if 'sd' in sd:
                s.sub_days = int(sd.get('sd', SUB_DAYS))
            elif s.subscribed:
                s.sub_days = 9999 if s.forever else SUB_DAYS
            s.big = sd.get('big', False)
            s.gear = set(sd.get('gear', []))
            s.total_earn = sd.get('earn', 0.0)
            s.done = sd.get('done', 0)
            s.temp = float(sd.get('temp', TEMP_IDLE))
            s.strain = max(0.0, min(1.2, float(sd.get('strain', 0.0))))
            s.fatigue = max(0.0, min(1.0, float(sd.get('fat', 0.0))))
            s.rest_bonus = max(0.0, float(sd.get('rb', 0.0)))
            # ---- v2：额度和各种计时 / 状态 ----
            if 'quota' in sd and s.subscribed:
                cap = s.quota_cap()
                q = float(sd.get('quota', cap))
                s.quota = q if cap < 0 else max(0.0, min(q, cap))
            else:
                s.refresh_daily()          # 老存档：额度按当天补满
            s.snack = max(0.0, float(sd.get('snack', 0.0)))
            s.breakfast = max(0.0, float(sd.get('breakfast', 0.0)))
            s.cooking = max(0.0, float(sd.get('cook', 0.0)))
            s.meal = max(0.0, float(sd.get('meal', 0.0)))
            s.meal_slot = int(sd.get('mslot', 0))
            s.slack = max(0.0, float(sd.get('slack', 0.0)))
            s.stuck = max(0.0, float(sd.get('stuck', 0.0)))
            s.limited = bool(sd.get('limited', False))
            s.paused_job = bool(sd.get('paused', False))
            s.resting = bool(sd.get('resting', False))
            s.strain_warned = bool(sd.get('warn', False))
        self.set_scene(d.get('scene', 'apartment'), place=True)
        self.log('读档成功，继续营业。', C_BLUE)
        return True

    # ------------------------------------------------ 任务
    def spawn_interval(self):
        iv = self._spawn_interval()
        return iv * 1.7 if self.scene == 'station' else iv

    def _spawn_interval(self):
        rep_k = 0.72 + self.rep / 100 * 0.85
        line_k = 0.80 + 0.05 * len(self.unlocked())
        price_k = 1.30 - (self.price_mult - 0.70) * 0.58
        iv = 36.0 / max(0.25, rep_k * line_k * price_k) / self.gw_speed()
        if self.ad_days > 0:
            iv *= AD_BOOST
        if self.burst > 0:
            iv *= 0.55
        return max(4.0, iv)

    def day_big(self):
        """越到后期，用户甩过来的活越大（工作量更高，也更值钱）。

        幅度控制在 1.45 倍以内——涨太多的话线路产能跟不上，
        大量单子会排队超时，声誉会一路崩。
        """
        return min(1.30, 1.0 + 0.012 * (self.day - 1))

    def try_spawn(self):
        # 队列满了就别再吐单：硬塞进去的单只会排队等到超时撤单，
        # 队列越长撤单越多，声誉一路崩。等有空位了自然会再来。
        if len(self.queued_tasks()) >= len(TASK_SLOTS):
            return
        if self.contract and random.random() < 0.40:
            typ = self.contract['typ']       # 长期合同：优先给这种活
        else:
            typ = random.choices(TYPE_KEYS,
                                 weights=[24, 20, 13, 15, 16, 12])[0]
        t = Task(typ)
        big = self.gw_big() * self.day_big()
        if self.day >= 8 and random.random() < 0.14:
            big *= 1.40           # 偶尔来一个特大工程
            self.log('网关送来一个特大单，工作量爆表', (255, 214, 152))
        t.w *= big
        t.budget *= big
        if self.scene == 'station':
            # 科考站：活少但单子大，得几个人一起干
            t.multi = True
            t.w *= 2.3
            t.budget *= 2.2
            t.patience_min *= 2.2
            t.patience = t.patience_min / GAME_MIN_PER_SEC
        # 声誉高的站子更常接到舍得花钱的用户
        t.budget *= 0.86 + self.rep / 100 * 0.40
        if self.contract and typ == self.contract['typ']:
            t.budget *= 1.15                 # 长期合同：单价 +15%
            t.contract = True
        self.tasks.append(t)
        self.arrange_queue()
        # 网关吐包特效
        for _ in range(5):
            self.particles.append(dict(
                x=GATEWAY[0] + random.uniform(-6, 6), y=GATEWAY[1] + random.uniform(-6, 6),
                vx=random.uniform(-30, 30), vy=random.uniform(-46, -14),
                life=random.uniform(0.25, 0.5), color=TYPES[typ]['color']))

    def arrange_queue(self):
        """单子现在统一进服务器，不再需要排队位。"""
        return

    def abort_job(self, st, t):
        """把手上某一单作废（放弃 / 宕机 / 跳闸都走这里）。协作单只摘掉自己。"""
        if st.busy is t:
            st.busy = None
        elif st.busy2 is t:
            st.busy2 = None
        st.prog = 0.0
        if t.multi and st.m['id'] in t.crew and t.state == 'service':
            t.crew.remove(st.m['id'])
            if t.crew:
                return          # 其他人还在做，这一单不废
        t.crew = []
        t.qcost = 0.0
        t.qspent = 0.0
        t.state = 'out'
        t.fade = 0

    # ------------------------------------------------ 背包
    def bag_count(self, item):
        return int(self.bag.get(item, 0))

    def bag_add(self, item, n=1):
        self.bag[item] = self.bag_count(item) + n

    def bag_take(self, item, n=1):
        c = self.bag_count(item)
        if c < n:
            return False
        if c == n:
            self.bag.pop(item, None)
        else:
            self.bag[item] = c - n
        return True

    def bag_list(self):
        """背包里的东西：装备在前（按 GEAR 顺序），重置卡在后（按线路顺序）。"""
        gear_order = {g['id']: i for i, g in enumerate(GEAR)}
        model_order = {m['id']: i for i, m in enumerate(MODELS)}
        out = []
        for item, n in self.bag.items():
            if n <= 0:
                continue
            if item.startswith(RESET_PREFIX):
                mid = item[len(RESET_PREFIX):]
                key = (1, model_order.get(mid, 99))
            else:
                key = (0, gear_order.get(item, 99))
            out.append((item, n, key))
        out.sort(key=lambda x: x[2])
        return [(item, n) for item, n, _ in out]

    def bag_total(self):
        return sum(v for v in self.bag.values() if v > 0)

    # ------------------------------------------------ 商店 / 装备
    def store_panel_rect(self):
        return pygame.Rect(30, SH // 2 - 270, 860, 540)

    def store_gear_btns(self):
        r = self.store_panel_rect()
        out = []
        for i, g in enumerate(GEAR):
            y = r.y + 100 + i * 44
            out.append((g, pygame.Rect(r.x + 330, y + 6, 92, 26)))
        return out

    def store_food_btn(self):
        r = self.store_panel_rect()
        y = r.y + 100 + len(GEAR) * 44
        return pygame.Rect(r.x + 330, y + 6, 92, 26)

    def store_reset_rows(self):
        """能买重置卡的线路（豆包这种永久的不用）。"""
        r = self.store_panel_rect()
        out = []
        for m in MODELS:
            if reset_price(m) <= 0:
                continue
            y = r.y + 116 + len(out) * 46
            out.append((m, pygame.Rect(r.x + 466, y - 2, 246, 42),
                        pygame.Rect(r.right - 26 - 112, y + 5, 112, 32)))
        return out

    def buy_gear(self, g):
        """买一件装备：直接进背包，可以重复买。"""
        if self.money < g['price']:
            self.toast_msg(f'钱不够（要 ¥{g["price"]}）', C_RED)
            return False
        self.money -= g['price']
        if self.scene == 'station':
            # 科考站没有现货店：下单，随下一批补给车到
            self.pending_gear.append(g['id'])
            left = max(0, SUPPLY_EVERY - self.day % SUPPLY_EVERY) if self.day % SUPPLY_EVERY else 0
            self.log(f'订了 {g["name"]}（¥{g["price"]}），随下批补给到（{left} 天后）', C_GOLD)
            self.toast_msg(f'{g["name"]} 已下单 · {left} 天后随补给到', C_GOLD, 2.6)
        else:
            self.bag_add(g['id'])
            self.log(f'买了 {g["name"]}（¥{g["price"]}），放进背包了', C_GOLD)
            self.toast_msg(f'{g["name"]} 放进背包 · 拖到 AI 身上装上', C_GOLD, 2.4)
        return True

    def buy_food(self):
        """买一份食材包：千问做一顿饭要用 1 份。"""
        if self.money < FOOD_PRICE:
            self.toast_msg(f'钱不够买食材（¥{FOOD_PRICE}）', C_RED)
            return False
        self.money -= FOOD_PRICE
        self.bag_add(FOOD_ID)
        self.log(f'买了一份食材（¥{FOOD_PRICE}），放进背包了', C_GOLD)
        self.toast_msg(f'食材包放进背包（还够做 {self.bag_count(FOOD_ID)} 顿）', C_GOLD, 2.2)
        return True

    def buy_reset_card(self, st):
        """买一张这条线的重置卡：价格每条线不同，买完进背包，可以攒着。"""
        price = reset_price(st.m)
        if price <= 0:
            self.toast_msg(f'{st.m["name"]} 不需要重置卡', C_DIM)
            return False
        if self.money < price:
            self.toast_msg(f'钱不够买 {st.m["name"]} 的重置卡（¥{price}）', C_RED)
            return False
        self.money -= price
        self.bag_add(RESET_PREFIX + st.m['id'])
        self.log(f'买了 {st.m["name"]} 的重置卡（¥{price}），放进背包了', C_GOLD)
        self.toast_msg(f'{st.m["name"]} 重置卡放进背包（¥{price}）', C_GOLD, 2.4)
        return True

    def use_reset_card(self, st):
        """用掉一张这条线的重置卡：解限流、压力清零、额度补满、宕机清掉。
        温度不归它管——那是散热的事。"""
        item = RESET_PREFIX + st.m['id']
        if not st.subscribed:
            self.toast_msg(f'{st.m["name"]} 还没订阅，用不上重置卡', C_DIM)
            return False
        if not self.bag_take(item):
            self.toast_msg(f'背包里没有 {st.m["name"]} 的重置卡', C_DIM)
            return False
        self.t_reset_cards += 1
        st.limited = False
        st.paused_job = False
        st.strain = 0.0
        st.strain_warned = False
        st.stuck = 0.0
        st.cooldown = 0.0
        st.refresh_daily()
        self.log(f'给 {st.m["name"]} 用了一张重置卡：限流解除、额度补满', C_GOLD)
        self.toast_msg(f'{st.m["name"]} 已重置', C_GREEN, 2.2)
        return True

    def apply_item(self, item, st):
        """把背包里的一个道具用到某个 AI 身上（拖过去 / 点两下都走这里）。"""
        if item is None:
            return False
        if not st.unlocked:
            self.toast_msg(f'{st.m["name"]} 还没解锁，先把它装进公寓', C_DIM)
            return False
        kind, name, short, col, model = bag_item_info(item)
        if kind == BAG_KIND_RESET:
            mid = item[len(RESET_PREFIX):]
            if mid != st.m['id']:
                self.toast_msg(f'这张是 {short} 的重置卡，用不到 {st.m["name"]} 身上', C_RED)
                return False
            return self.use_reset_card(st)
        return self.equip_gear(st, item)

    def unequip_gear(self, st, gid):
        """把一件装备卸下来：卸下来的回背包，可以再装给别人。"""
        if gid not in st.gear:
            return False
        g = next((x for x in GEAR if x['id'] == gid), None)
        name = g['name'] if g else gid
        st.gear.discard(gid)
        if gid == 'dual' and st.busy2 is not None:
            # 没这台服务器就放不下第二单了
            self.abort_job(st, st.busy2)
            st.busy2 = None
        if gid == 'net':
            st.quota = min(st.quota, st.quota_cap()) if st.quota >= 0 else -1
        self.bag_add(gid)
        self.log(f'{st.m["name"]} 把{name}卸回了背包', (206, 172, 120))
        self.toast_msg(f'{st.m["name"]} 卸下 {name} · 已回背包', (236, 200, 140), 2.2)
        return True

    def equip_gear(self, st, gid=None):
        """把背包里的一件装备装到某个 AI 身上（一条线最多三件）。"""
        gid = gid or self.held_item
        if gid is None:
            return False
        g = next((x for x in GEAR if x['id'] == gid), None)
        if g is None:
            return False
        if gid in st.gear:
            self.toast_msg(f'{st.m["name"]} 已经装着这个了', C_DIM)
            return False
        if len(st.gear) >= MAX_GEAR:
            self.toast_msg(f'{st.m["name"]} 的装备栏满了（最多 {MAX_GEAR} 件）', C_RED)
            return False
        if not self.bag_take(gid):
            self.toast_msg(f'背包里没有{g["name"]}', C_DIM)
            return False
        st.gear.add(gid)
        self.held_item = None
        st.refresh_daily()          # 扩展网口：额度上限变了要跟着补
        self.log(f'{g["name"]} 装到了 {st.m["name"]} 身上：{g["desc"]}', C_GOLD)
        self.toast_msg(f'{st.m["name"]} 装上了 {g["name"]}', C_GREEN, 2.4)
        return True

    def draw_held_item(self):
        """手上（拖着或拿着）的道具：跟着鼠标，并对准的 AI 描个绿框。"""
        item = self.drag_item or self.held_item
        if not item:
            return
        s = self.screen
        mx, my = self.mouse
        st = self.station_at((mx, my))
        if st is not None:
            x, y, w, h = st.rect()
            if self.zoom > 1.001:
                vx, vy, vw, vh = self.view_box()
                sx, sy = (x - vx) * WW / vw, (y - vy) * WH / vh
                sw, sh = w * WW / vw, h * WH / vh
            else:
                sx, sy, sw, sh = x, y, w, h
            pygame.draw.rect(s, (140, 230, 180), (sx, sy, sw, sh), 2, border_radius=8)
            txt(s, st.m['name'], sx + sw / 2, sy - 15, 11, (160, 240, 200), 'midtop')
        draw_bag_item_icon(s, item, mx - 20, my - 20, 40)
        if not self.drag_item:
            txt(s, '放在一个 AI 身上', mx + 24, my - 6, 11, (250, 224, 170))

    # ------------------------------------------------ 设置面板
    def settings_panel_rect(self):
        return pygame.Rect(SW // 2 - 260, SH // 2 - 210, 520, 420)

    def settings_buttons(self):
        r = self.settings_panel_rect()
        out = [
            ('music', pygame.Rect(r.x + 330, r.y + 84, 130, 36)),
            ('vol_down', pygame.Rect(r.x + 120, r.y + 146, 40, 34)),
            ('vol_up', pygame.Rect(r.x + 430, r.y + 146, 40, 34)),
            ('fullscreen', pygame.Rect(r.x + 330, r.y + 200, 130, 36)),
        ]
        mode = self.panel[1] if self.panel and self.panel[0] == 'settings' else 'game'
        if mode == 'game':
            out.append(('close', pygame.Rect(r.centerx - 230, r.bottom - 70, 210, 44)))
            out.append(('home', pygame.Rect(r.centerx + 20, r.bottom - 70, 210, 44)))
        else:
            out.append(('close', pygame.Rect(r.centerx - 105, r.bottom - 70, 210, 44)))
        return out

    def click_settings(self, mx, my, mode):
        for key, rect in self.settings_buttons():
            if not rect.collidepoint(mx, my):
                continue
            if key == 'music':
                self.music.toggle()
            elif key == 'vol_down':
                self.music.bump(-1)
            elif key == 'vol_up':
                self.music.bump(1)
            elif key == 'fullscreen':
                self.toggle_fullscreen()
            elif key == 'close':
                self.panel = None
                self.paused = False
            elif key == 'home':
                if not getattr(self, 'test_mode', False):
                    self.save()             # 回首页前先存一下，别丢进度（试玩不写档）
                self.go_title()
            return
        # 点在面板外面：把这个模态面板收起来（不穿透到底下的按钮）
        if not self.settings_panel_rect().collidepoint(mx, my):
            self.panel = None
            self.paused = False

    def draw_settings_panel(self, mode):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 190))
        r = self.settings_panel_rect()
        alpha_rect(s, r, (18, 20, 30, 250), 10)
        pygame.draw.rect(s, (120, 150, 200), r, 2, border_radius=10)
        txt(s, '设置', r.x + 26, r.y + 18, 24, C_TEXT, bold=True)
        txt(s, '打开设置时，游戏自动暂停' if mode == 'game' else '声音与画面',
            r.x + 26, r.y + 52, 12, (140, 148, 172))

        # 音乐开关
        on = bool(self.music.settings.get('music'))
        txt(s, '背景音乐', r.x + 26, r.y + 94, 15, C_TEXT)
        mb = [b for k, b in self.settings_buttons() if k == 'music'][0]
        hov = mb.collidepoint(self.mouse)
        alpha_rect(s, mb, (34, 52, 40) if on and not hov else
                   ((40, 60, 46) if on else ((40, 32, 34) if hov else (30, 26, 30))), 6)
        pygame.draw.rect(s, (130, 210, 160) if on else (190, 120, 120), mb, 2, border_radius=6)
        txt(s, '开' if on else '关', mb.centerx, mb.y + 8, 17,
            (196, 240, 210) if on else (240, 180, 180), 'midtop', bold=True)

        # 音量
        vol = float(self.music.settings.get('volume', 0.6))
        txt(s, '音量', r.x + 26, r.y + 154, 15, C_TEXT)
        vb = [b for k, b in self.settings_buttons() if k == 'vol_down'][0]
        vu = [b for k, b in self.settings_buttons() if k == 'vol_up'][0]
        for b, label in ((vb, '−'), (vu, '+')):
            h = b.collidepoint(self.mouse)
            alpha_rect(s, b, (44, 40, 30) if h else (30, 28, 24), 5)
            pygame.draw.rect(s, (200, 180, 120), b, 1, border_radius=5)
            txt(s, label, b.centerx, b.y + 4, 20, (250, 232, 180), 'midtop', bold=True)
        bar = pygame.Rect(r.x + 172, r.y + 162, 246, 12)
        pygame.draw.rect(s, (34, 36, 50), bar)
        for i in range(10):
            seg = pygame.Rect(bar.x + 2 + i * 24, bar.y + 2, 20, bar.h - 4)
            lit = (i + 1) <= int(round(vol * 10))
            pygame.draw.rect(s, (150, 210, 170) if lit else (50, 54, 68), seg)
        txt(s, f'{int(round(vol * 100))}%', r.x + 430 - 6, r.y + 152, 12,
            (160, 200, 180), 'topright')

        # 全屏
        fb = [b for k, b in self.settings_buttons() if k == 'fullscreen'][0]
        txt(s, '全屏', r.x + 26, r.y + 210, 15, C_TEXT)
        hovf = fb.collidepoint(self.mouse)
        alpha_rect(s, fb, (34, 46, 62) if self.fullscreen else ((36, 40, 54) if hovf else (26, 30, 42)), 6)
        pygame.draw.rect(s, (140, 180, 240) if self.fullscreen else (90, 100, 130),
                         fb, 2, border_radius=6)
        txt(s, '开' if self.fullscreen else '关', fb.centerx, fb.y + 8, 17,
            C_TEXT if self.fullscreen else (176, 186, 208), 'midtop', bold=True)
        txt(s, '也可以直接按 F11', r.x + 26, r.y + 244, 11, (120, 128, 152))

        # 曲目
        if self.music.ok:
            txt(s, f'正在放：{self.music.track}', r.centerx, r.y + 286, 12,
                (150, 220, 180), 'midtop')
        elif self.music.path:
            txt(s, f'音乐加载失败：{os.path.basename(self.music.path)}',
                r.centerx, r.y + 286, 12, (230, 160, 150), 'midtop')
        else:
            txt(s, '没找到音乐：把 mp3 放进 assets/music/ 就行（文件名随便）',
                r.centerx, r.y + 286, 12, (200, 180, 130), 'midtop')

        for key, b in self.settings_buttons():
            if key not in ('close', 'home'):
                continue
            h = b.collidepoint(self.mouse)
            if key == 'close':
                alpha_rect(s, b, (44, 62, 96) if h else (28, 40, 66), 6)
                pygame.draw.rect(s, (130, 176, 240), b, 2, border_radius=6)
                txt(s, '继续游戏' if mode == 'game' else '关闭', b.centerx, b.y + 12,
                    18, C_TEXT, 'midtop', bold=True)
            else:
                alpha_rect(s, b, (52, 44, 34) if h else (32, 28, 24), 6)
                pygame.draw.rect(s, (190, 160, 110), b, 1, border_radius=6)
                txt(s, '回到首页（会先存档）', b.centerx, b.y + 12, 16,
                    (236, 208, 156), 'midtop', bold=True)

    # ------------------------------------------------ 关系面板
    def relations_panel_rect(self):
        return pygame.Rect(180, SH // 2 - 270, 720, 540)

    def relations_buttons(self):
        r = self.relations_panel_rect()
        return [('close', pygame.Rect(r.centerx - 90, r.bottom - 62, 180, 42))]

    def relation_rows(self, limit=12):
        """所有聊出过关系的组合，按默契从高到低。"""
        st = [x for x in self.stations if x.unlocked]
        rows = []
        for i in range(len(st)):
            for j in range(i + 1, len(st)):
                a, b = st[i], st[j]
                v = self.bond(a, b)
                if v >= 0.2 or v < 0:
                    rows.append((a, b, v))
        rows.sort(key=lambda x: -x[2])
        return rows[:limit]

    def open_relations(self, back=None):
        self.relations_back = back
        self.panel = ('relations', None)

    def close_relations(self):
        back = getattr(self, 'relations_back', None)
        self.relations_back = None
        self.panel = back

    def relations_matrix_rects(self):
        """矩阵单元格：10x10。"""
        r = self.relations_panel_rect()
        st = [x for x in self.stations if x.unlocked]
        n = len(st)
        cw = min(52, int((r.w - 130) / max(1, n)))
        ch = min(34, int((r.h - 150) / max(1, n)))
        x0, y0 = r.x + 100, r.y + 100
        out = []
        for i in range(n):
            for j in range(n):
                out.append((st[i], st[j], pygame.Rect(x0 + j * cw, y0 + i * ch, cw - 2, ch - 2)))
        return out

    def draw_relations_panel(self, data=None):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 185))
        r = self.relations_panel_rect()
        alpha_rect(s, r, (22, 20, 30, 248), 10)
        pygame.draw.rect(s, (208, 142, 172), r, 2, border_radius=10)
        txt(s, '人缘关系', r.centerx, r.y + 16, 22, (246, 202, 220), 'midtop', bold=True)
        txt(s, '颜色越红越亲近、越蓝越疏远；同一对只显示一次（上三角），鼠标悬停看具体数值',
            r.centerx, r.y + 46, 11, (168, 152, 174), 'midtop')

        st = [x for x in self.stations if x.unlocked]
        if len(st) < 2:
            txt(s, '至少要两条线路在营，才有人际关系', r.centerx, r.y + 200, 14,
                (140, 134, 152), 'midtop')
        # 行列名字
        cw = min(52, int((r.w - 130) / max(1, len(st))))
        ch = min(34, int((r.h - 150) / max(1, len(st))))
        x0, y0 = r.x + 100, r.y + 100
        for i, a in enumerate(st):
            txt(s, a.m['name'][:5], x0 - 8, y0 + i * ch + ch // 2, 9, (186, 176, 198),
                'midright')
            txt(s, a.m['name'][:5], x0 + i * cw + cw // 2, y0 - 10, 9, (186, 176, 198),
                'midbottom')
        hov_cell = None
        idx = {x.m['id']: k for k, x in enumerate(st)}
        for a, b, box in self.relations_matrix_rects():
            i, j = idx[a.m['id']], idx[b.m['id']]
            if i == j:
                pygame.draw.rect(s, (30, 26, 36), box)
                continue
            if j < i:
                continue                       # 只画上三角
            v = self.bond(a, b)
            if v >= 0:
                col = (int(60 + 150 * v), int(64 + 40 * v), int(90 + 30 * v))
            else:
                col = (70, int(80 + 40 * -v), int(110 + 60 * -v))
            pygame.draw.rect(s, col, box, border_radius=3)
            if box.collidepoint(self.mouse):
                hov_cell = (a, b, v, box)
        if hov_cell:
            a, b, v, box = hov_cell
            pygame.draw.rect(s, (250, 236, 250), box, 2, border_radius=3)
            txt(s, f'{a.m["name"]} ↔ {b.m["name"]}：{int(round(v * 100))}%',
                r.centerx, r.bottom - 46, 13, (250, 240, 250), 'midtop', bold=True)
        else:
            txt(s, '悬停任意格子查看数值 · Esc 关闭', r.centerx, r.bottom - 46, 11,
                (140, 132, 152), 'midtop')
        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (90, 104, 134), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

    def draw_relocate_panel(self, d):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 195))
        r = self.relocate_panel_rect()
        alpha_rect(s, r, (16, 26, 30, 250), 10)
        pygame.draw.rect(s, (120, 200, 210), r, 2, border_radius=10)
        txt(s, '南极数据中心 · 邀请', r.centerx, r.y + 22, 24, (170, 236, 240),
            'midtop', bold=True)
        txt(s, f'你攒到了 ¥{int(d["cost"]):,}。上游问你要不要去南极驻站——',
            r.centerx, r.y + 66, 13, C_TEXT, 'midtop')
        txt(s, '那里散热免费、电价便宜，就是补给要靠船。', r.centerx, r.y + 88, 13,
            (170, 180, 200), 'midtop')
        txt(s, '搬过去会带走：资金 · 8 条线路（剩余订阅） · 背包与装备 · 关系和合同',
            r.centerx, r.y + 126, 12, (150, 220, 190), 'midtop')
        txt(s, '留下：公寓的房租合同（终止）· 电闸等级（新站要重买）',
            r.centerx, r.y + 148, 12, (220, 170, 150), 'midtop')
        conds = [
            (f'攒够 ¥{RELOCATE_COST:,}', self.money >= RELOCATE_COST),
            (f'第 {RELOCATE_DAY} 天以后', self.day >= RELOCATE_DAY),
            ('DeepSeek 与 GPT 都是大模型', self.big_ready()),
            ('全部线路解锁', all(x.unlocked for x in self.stations)),
        ]
        for i, (label, ok) in enumerate(conds):
            txt(s, ('✓ ' if ok else '✗ ') + label, r.x + 60 + (i % 2) * 340,
                r.y + 186 + (i // 2) * 24, 12,
                (150, 220, 170) if ok else (214, 130, 130))
        txt(s, f'搬迁费 ¥{int(d["cost"]):,}', r.centerx, r.y + 250, 15, C_GOLD,
            'midtop', bold=True)
        for key, b in self.relocate_buttons():
            hov = b.collidepoint(self.mouse)
            if key == 'go':
                alpha_rect(s, b, (36, 62, 58) if hov else (24, 44, 42), 6)
                pygame.draw.rect(s, (130, 220, 190), b, 2, border_radius=6)
                txt(s, '搬过去', b.centerx, b.centery, 16, (190, 245, 220), 'center',
                    bold=True)
            else:
                alpha_rect(s, b, (40, 40, 48) if hov else (28, 28, 34), 6)
                pygame.draw.rect(s, (110, 118, 134), b, 1, border_radius=6)
                txt(s, '再等等', b.centerx, b.centery, 15, (190, 196, 210), 'center')

    # ------------------------------------------------ 长期合同
    def contract_panel_rect(self):
        return pygame.Rect(SW // 2 - 280, SH // 2 - 170, 560, 340)

    def contract_buttons(self):
        r = self.contract_panel_rect()
        return [('accept', pygame.Rect(r.centerx - 240, r.bottom - 64, 220, 44)),
                ('reject', pygame.Rect(r.centerx + 20, r.bottom - 64, 220, 44))]

    def draw_contract_panel(self, o):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 195))
        r = self.contract_panel_rect()
        alpha_rect(s, r, (18, 24, 30, 250), 10)
        pygame.draw.rect(s, (120, 200, 210), r, 2, border_radius=10)
        name = TYPES[o['typ']]['name']
        txt(s, '南极科考合同', r.centerx, r.y + 22, 26, (170, 236, 240),
            'midtop', bold=True)
        txt(s, f'科考队想包下你的「{name}」产能：', r.centerx, r.y + 66, 14,
            C_TEXT, 'midtop')
        txt(s, f'每天至少交 {o["need"]} 单，连续 {o["days"]} 天',
            r.centerx, r.y + 92, 18, C_GOLD, 'midtop', bold=True)
        txt(s, f'合同单单价 +15%　·　完成奖金 ¥{o["reward"]}',
            r.centerx, r.y + 126, 14, (150, 220, 190), 'midtop')
        txt(s, f'违约（某天没交够）：声誉 -3，合同作废',
            r.centerx, r.y + 152, 12, (220, 150, 140), 'midtop')
        txt(s, f'你累计已经交付了 {o.get("count", 0)} 单{name}，所以他们找上门了。',
            r.centerx, r.y + 186, 12, (140, 150, 172), 'midtop')
        for key, b in self.contract_buttons():
            h = b.collidepoint(self.mouse)
            if key == 'accept':
                alpha_rect(s, b, (36, 62, 58) if h else (24, 44, 42), 6)
                pygame.draw.rect(s, (130, 220, 190), b, 2, border_radius=6)
                txt(s, '签', b.centerx, b.y + 11, 19, (190, 245, 220), 'midtop', bold=True)
            else:
                alpha_rect(s, b, (56, 40, 42) if h else (34, 28, 30), 6)
                pygame.draw.rect(s, (180, 120, 120), b, 1, border_radius=6)
                txt(s, '再想想', b.centerx, b.y + 12, 16, (226, 176, 176), 'midtop')

    # ------------------------------------------------ 房租提醒
    def notice_panel_rect(self):
        return pygame.Rect(SW // 2 - 280, SH // 2 - 150, 560, 300)

    def notice_ok_btn(self):
        r = self.notice_panel_rect()
        return pygame.Rect(r.centerx - 100, r.bottom - 64, 200, 44)

    def draw_notice(self, d):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 195))
        r = self.notice_panel_rect()
        alpha_rect(s, r, (26, 22, 18, 250), 10)
        pygame.draw.rect(s, (232, 190, 120), r, 2, border_radius=10)
        txt(s, '房东明天来收租', r.centerx, r.y + 26, 26, (255, 220, 160),
            'midtop', bold=True)
        rent = d.get('rent', RENT_WEEK)
        money = d.get('money', self.money)
        txt(s, f'明天（第 {d.get("day", self.day) + 1} 天）打烊时，要交房租 ¥{rent:,}。',
            r.centerx, r.y + 84, 15, C_TEXT, 'midtop')
        left = money - rent
        txt(s, f'现在账上 ¥{money:,.0f}，交完还剩 ¥{left:,.0f}。',
            r.centerx, r.y + 114, 15,
            (150, 220, 170) if left >= 0 else C_RED, 'midtop')
        txt(s, '别把钱全砸进解锁和订阅里。', r.centerx, r.y + 152, 13,
            (190, 170, 140), 'midtop')
        b = self.notice_ok_btn()
        h = b.collidepoint(self.mouse)
        alpha_rect(s, b, (58, 48, 30) if h else (40, 34, 24), 6)
        pygame.draw.rect(s, (236, 200, 130), b, 2, border_radius=6)
        txt(s, '知道了', b.centerx, b.y + 12, 18, (255, 236, 200), 'midtop', bold=True)

    LOAN_RATE = 0.02          # 每天 2% 利息
    LOAN_CAP = 5000

    def borrow(self, amount):
        if self.loan + amount > self.LOAN_CAP:
            self.toast_msg(f'最多能借 ¥{self.LOAN_CAP:,}', C_DIM)
            return False
        self.loan += amount
        self.money += amount
        self.log(f'向银行借了 ¥{amount:,}（每天 {int(self.LOAN_RATE * 100)}% 利息）', C_GOLD)
        self.toast_msg(f'银行放款 ¥{amount:,}', C_GOLD, 2.4)
        return True

    def repay_loan(self):
        if self.loan <= 0:
            self.toast_msg('没有欠款', C_DIM)
            return False
        pay = min(self.loan, max(0.0, self.money))
        if pay <= 0:
            self.toast_msg('没钱还', C_RED)
            return False
        self.money -= pay
        self.loan -= pay
        self.log(f'还了银行 ¥{pay:,.0f}，还欠 ¥{self.loan:,.0f}', (150, 210, 170))
        self.toast_msg(f'还款 ¥{pay:,.0f}', (150, 210, 170), 2.2)
        return True

    def loan_buttons(self):
        r = self.storage_rect()
        return [('b1000', pygame.Rect(r.x + 30, r.bottom - 92, 120, 30)),
                ('b3000', pygame.Rect(r.x + 160, r.bottom - 92, 120, 30)),
                ('repay', pygame.Rect(r.x + 290, r.bottom - 92, 120, 30))]

    def storage_rect(self):
        return pygame.Rect(250, 96, 680, 540)

    def gear_buy_rects(self):
        r = self.storage_rect()
        out = []
        for i, g in enumerate(GEAR):
            out.append((g, pygame.Rect(r.right - 148, r.y + 220 + i * 42, 120, 26)))
        return out

    GUIDE = {
        'apt': [
            ('公寓 · 怎么赚钱', [
                '网关吐单 → 点服务器选单 → 点人派出去；跑完自动结算。',
                '星越多赚得越多；声誉越高来单越好。',
                '额度是每天刷新的，额度见底这单会断。',
                '订阅买 7 天；服务器右上角可开「自动派单」，会按专长和额度挑人。',
                '深夜额度半价但速度慢（GLM 反过来：夜里又快又便宜）。',
                'Grok / Gemini / ChatGPT / Claude 要装 VPN 端口才接单，记得去主控屏或工位面板买。',
            ]),
            ('公寓 · 要盯的东西', [
                '电闸容量：同时开工超过容量 9 秒就跳闸，在跑的单全废。',
                '温度：跑太狠会过热，需要散热扇；宕机要点一下才恢复。',
                '租金每 10 天收一次；工资和电费每天结算。',
                '早餐铺 6:00~8:00 开：买早餐算一顿（+10% 速度）。',
                '缺一顿饭当天全员减速 15%，吃到下一顿才恢复。',
            ]),
            ('公寓 · 成长路线', [
                '攒钱解锁线路（5 条触发第二幕）→ 升大模型 → 凑齐条件搬南极。',
                '装备和补给都在主控屏 / 装备面板下单，随补给车到；背包在仓库里，点道具再点 AI 装上。',
                '搬去南极要：¥5000 + 第 5 天 + 两个大模型 + 所有线路都解锁。',
                '主线奖励要手动领：左上角「领取 +¥X」按钮；每日目标全达成 +¥200。',
            ]),
        ],
        'station': [
            ('科考站 · 派单', [
                '服务器选单再点人（或开自动派单）；科考站是大单，2~3 人协作、进度叠加。',
                '协作要求队里每个人默契 ≥50%；人越多占的电闸容量越多。',
                '正跑科考任务的人不能接派单；做饭、抓鱼、睡觉、值班也接不了。',
                '没有任务时点人 = 看他的面板，不会被拒绝。',
            ]),
            ('科考站 · 科考任务', [
                '气象：每天 2 趟，发布时刻随机（8~20 点），做完一趟才出下一趟。',
                '冰样：每天 2 趟，不隔时间，但要等上一趟跑完才能接下一趟。',
                '温室：每天 1 次；只有千问能收 2 份食材，别人去不产食材。',
                '同一种任务两次之间至少隔 8 小时（冰样除外）。',
                '任务都是一条龙：气象室→主控台；气闸→实验室→主控台。',
            ]),
            ('科考站 · 活下去', [
                '供暖：每天烧燃料，极夜（第 12 天起）×1.6；断电会冷，效率大跌。',
                '值班：留人不接单，每人每天省 3 单位燃料（最多算 2 人）。',
                '配电柜：升级容量，避免协作大单跳闸。',
                '三餐 6:30/11:30/17:30 开窗；早饭 7 点；缺饭当天减速，吃到下一顿恢复。',
                '物资和装备都在主控屏下单，随补给车 3 天到一次。',
            ]),
            ('科考站 · 人和状态', [
                '疲劳：干活会累，到 85% 会自己回宿舍睡；做饭、抓鱼、照顾温室也涨。',
                'DeepSeek 没食材会去气闸外抓鱼（+2 食材）。',
                '闲着的人会到处逛（温室/食堂/宿舍/门口），不会一直堆在大厅。',
                '所有线路都要订阅；Seed 在站内也要接电、要订阅。',
            ]),
        ],
    }

    def intro_rect(self):
        return pygame.Rect(176, 70, 760, 580)

    def draw_intro_panel(self, which=None):
        s = self.screen
        which = which or ('station' if self.scene == 'station' else 'apt')
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 195))
        r = self.intro_rect()
        alpha_rect(s, r, (16, 22, 30, 250), 10)
        pygame.draw.rect(s, (130, 200, 230), r, 2, border_radius=10)
        title = '南极科考站 · 玩法指南' if which == 'station' else '公寓 · 玩法指南'
        txt(s, title, r.centerx, r.y + 18, 22, (176, 232, 240), 'midtop', bold=True)
        left, right = self.GUIDE[which][:2], self.GUIDE[which][2:]
        for col, blocks in enumerate((left, right)):
            bx = r.x + 30 + col * 370
            y = r.y + 62
            for head, lines in blocks:
                txt(s, head, bx, y, 15, (240, 210, 140), bold=True)
                y += 24
                for ln in lines:
                    txt(s, '· ' + ln, bx, y, 11, (185, 196, 214))
                    y += 36
                y += 14
        txt(s, '点任意位置开始 · 之后随时点右上角「指南」再看', r.centerx,
            r.bottom - 30, 12, (150, 160, 182), 'midtop')

    COMIC = [
        ('第 1 幕 · 深夜', '第一笔订单进来了。\n屏幕的光照着一张还没睡的脸。'),
        ('第 2 幕 · 越做越大', '机柜一台台叠起来，\n走廊里开始有人走动。'),
        ('第 3 幕 · 一张船票', '上游发来邀请：\n「南极数据中心，来不来？」'),
        ('第 4 幕 · 南极', '雪原尽头亮着灯。\n你带着全部家当，推开了那扇门。'),
    ]

    def comic_rect(self):
        return pygame.Rect(120, 90, 820, 540)

    def show_comic(self, frames, to_intro=False):
        self.comic_list = list(frames)
        self.comic_i = 0
        self.pending_intro = to_intro
        self.panel = ('comic', self.comic_list[0])

    def stage_stats(self):
        hist = getattr(self, 'history', []) or []
        rev = sum(h.get('rev', 0) for h in hist)
        net = sum(h.get('net', 0) for h in hist)
        orders = sum(getattr(st, 'done', 0) for st in self.stations)
        money = self.net_worth()
        score = money + self.rep * 60 + self.main_step * 250
        if score >= 19000:
            grade, word = 'S', '公寓阶段打得很漂亮'
        elif score >= 14000:
            grade, word = 'A', '稳扎稳打，盘子铺开了'
        elif score >= 9000:
            grade, word = 'B', '活下来了，还有得赚'
        else:
            grade, word = 'C', '勉强维持，但撑到了南极'
        return dict(days=self.day, rev=rev, net=net, orders=orders,
                    worth=money, rep=self.rep, grade=grade, word=word)

    def draw_stage_panel(self, d):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 200))
        r = pygame.Rect(SW // 2 - 300, SH // 2 - 200, 600, 400)
        alpha_rect(s, r, (18, 22, 30, 250), 10)
        pygame.draw.rect(s, (150, 210, 220), r, 2, border_radius=10)
        txt(s, '公寓阶段 · 结算', r.centerx, r.y + 26, 22, (176, 232, 240),
            'midtop', bold=True)
        txt(s, d['word'], r.centerx, r.y + 58, 13, (160, 170, 190), 'midtop')
        txt(s, d['grade'], r.centerx, r.y + 84, 72, C_GOLD, 'midtop', bold=True)
        rows = [
            ('经营天数', f"{d['days']} 天"),
            ('成交单数', f"{d['orders']} 单"),
            ('累计营收', f"¥{d['rev']:,.0f}"),
            ('累计净利', f"¥{d['net']:,.0f}"),
            ('净资产', f"¥{d['worth']:,.0f}"),
            ('声誉', f"{d['rep']:.0f}"),
        ]
        y = r.y + 190
        for i, (k, v) in enumerate(rows):
            col = i % 2
            yy = y + (i // 2) * 34
            txt(s, k, r.x + 70 + col * 260, yy, 12, (140, 148, 170))
            txt(s, v, r.x + 160 + col * 260, yy - 2, 15, (226, 232, 246), bold=True)
        txt(s, '点击进入南极科考站', r.centerx, r.bottom - 44, 13, (150, 200, 210),
            'midtop', bold=True)

    def comic_image(self, idx):
        """如果放了 assets/comic/panel{n}.png 就用它，否则退回程序画的简笔画。"""
        for ext in ('png', 'jpg'):
            path = os.path.join(ROOT, 'assets', 'comic', f'panel{idx + 1}.{ext}')
            if os.path.exists(path):
                img = pygame.image.load(path).convert()
                fw = self.comic_rect().w - 80
                k = fw / img.get_width()
                return pygame.transform.smoothscale(img, (fw, int(img.get_height() * k)))
        return None

    def draw_comic(self, idx):
        s = self.screen
        idx = max(0, min(len(self.COMIC) - 1, idx if isinstance(idx, int) else 0))
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (3, 4, 8, 235))
        r = self.comic_rect()
        # 画面：有图片就用图片，否则退回渐变天空 + 简笔画
        art = self.comic_image(idx)
        if art is not None:
            box = pygame.Rect(r.x + 40, r.y + 44, r.w - 80, r.h - 128)
            k = min(box.w / art.get_width(), box.h / art.get_height())
            aw = max(1, int(art.get_width() * k))
            ah = max(1, int(art.get_height() * k))
            if (aw, ah) != art.get_size():
                art = pygame.transform.smoothscale(art, (aw, ah))
            frame = pygame.Rect(box.centerx - aw // 2, box.centery - ah // 2, aw, ah)
            s.blit(art, frame.topleft)
        else:
            frame = pygame.Rect(r.x + 40, r.y + 60, r.w - 80, 300)
            for i in range(frame.h):
                t = i / max(1, frame.h - 1)
                col = (int(10 + 30 * t), int(14 + 26 * t), int(30 + 40 * t))
                pygame.draw.line(s, col, (frame.x, frame.y + i),
                                 (frame.right, frame.y + i))
            if idx == 0:
                pygame.draw.rect(s, (18, 20, 30), (frame.x + 120, frame.y + 190, 300, 70))
                pygame.draw.rect(s, (90, 150, 200), (frame.x + 150, frame.y + 120, 120, 80))
                pygame.draw.circle(s, (24, 26, 38), (frame.x + 250, frame.y + 236), 34)
                pygame.draw.circle(s, (60, 80, 110), (frame.x + 330, frame.y + 210), 26)
            elif idx == 1:
                for i in range(4):
                    pygame.draw.rect(s, (30, 34, 46),
                                     (frame.x + 90 + i * 90, frame.y + 120 + i * 8, 70, 150))
                    pygame.draw.circle(s, (120, 220, 170),
                                       (frame.x + 100 + i * 90, frame.y + 140 + i * 8), 3)
                pygame.draw.circle(s, (24, 26, 38), (frame.x + 560, frame.y + 232), 34)
            elif idx == 2:
                pygame.draw.rect(s, (26, 30, 40), (frame.x + 120, frame.y + 170, 420, 110))
                for i in range(3):
                    pygame.draw.rect(s, (200, 226, 240),
                                     (frame.x + 150 + i * 120, frame.y + 140, 90, 34))
                pygame.draw.circle(s, (24, 26, 38), (frame.x + 620, frame.y + 214), 32)
            else:
                for i in range(frame.w):
                    t = i / frame.w
                    pygame.draw.line(s, (30 + int(30 * t), 40 + int(30 * t), 60 + int(40 * t)),
                                     (frame.x + i, frame.y + 240), (frame.x + i, frame.bottom))
                pygame.draw.rect(s, (46, 52, 66), (frame.x + 250, frame.y + 150, 90, 90))
                pygame.draw.rect(s, (120, 200, 220), (frame.x + 262, frame.y + 162, 24, 18))
                pygame.draw.rect(s, (120, 200, 220), (frame.x + 296, frame.y + 162, 24, 18))
                pygame.draw.circle(s, (24, 26, 38), (frame.x + 420, frame.y + 214), 26)
        pygame.draw.rect(s, (200, 214, 230), frame, 3)
        head, body = self.COMIC[idx]
        txt(s, head, r.centerx, r.y + 18, 20, (240, 216, 150), 'midtop', bold=True)
        for i, ln in enumerate(body.split('\n')):
            txt(s, ln, r.centerx, frame.bottom + 18 + i * 26, 15,
                (220, 228, 240), 'midtop')
        n = len(self.COMIC)
        txt(s, f'{idx + 1}/{n} · 点一下继续', r.centerx, r.bottom - 14, 12,
            (150, 160, 182), 'midtop')

    def draw_storage_panel(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 185))
        r = self.storage_rect()
        alpha_rect(s, r, (18, 22, 30, 248), 10)
        pygame.draw.rect(s, (196, 170, 120), r, 2, border_radius=10)
        txt(s, '仓库 · 库存与背包', r.x + 28, r.y + 20, 24, (240, 212, 150), bold=True)
        left = max(0, SUPPLY_EVERY - self.day % SUPPLY_EVERY) if self.day % SUPPLY_EVERY else 0
        txt(s, f'下一批补给 {left} 天后', r.right - 28, r.y + 26, 12,
            (170, 180, 200), 'topright')

        # 库存 + 还能用多久
        burn = max(0.1, self.fuel_burn()) if self.scene == 'station' else 0.0
        rows = [
            ('食材', f"{int(self.warehouse['food'])} 份",
             f"按每天 3 顿算还能用 {self.warehouse['food'] / 3.0:.1f} 天", (150, 220, 160)),
            ('供暖燃料', f'{int(self.fuel)} 单位',
             (f'每天烧 {burn:.0f}，还能用 {self.fuel / burn:.1f} 天' if burn
              else '公寓不烧燃料'), (240, 200, 130)),
            ('零食', f'{int(self.snacks)} 份', '每条线吃 1 份，够用一阵', (200, 180, 240)),
        ]
        y = r.y + 66
        for name, val, days, col in rows:
            txt(s, name, r.x + 30, y, 14, (150, 156, 176))
            txt(s, val, r.x + 130, y, 16, col, bold=True)
            txt(s, days, r.x + 240, y + 2, 12, (140, 150, 170))
            y += 34

        if self.pending_supply or self.pending_gear:
            n = len(self.pending_supply) + len(self.pending_gear)
            txt(s, f'在途：{n} 件（{left} 天后随补给到）', r.x + 30, y + 2, 12,
                (200, 210, 160))

        # 背包（并进仓库）
        txt(s, '背包（点一下拿起来，再点 AI 装上）', r.x + 30, r.y + 176, 18,
            (200, 210, 235), bold=True)
        items = self.bag_list()
        if not items:
            txt(s, '背包是空的 · 去主控屏下单，补给车送到', r.x + 34, r.y + 208, 12,
                (130, 138, 160))
        for i, (item, cnt) in enumerate(items[:8]):
            box = pygame.Rect(r.x + 30 + i * 78, r.y + 204, 70, 78)
            alpha_rect(s, box, (26, 30, 42), 6)
            pygame.draw.rect(s, (60, 68, 92), box, 1, border_radius=6)
            kind, name, short, col, model = bag_item_info(item)
            draw_bag_item_icon(s, item, box.x + 15, box.y + 12, 38)
            txt(s, f'×{cnt}', box.right - 5, box.y + 4, 10,
                (250, 230, 180), 'topright', bold=True)
            txt(s, short[:6], box.centerx, box.bottom - 16, 8, col, 'midtop')

        for key, b in self.loan_buttons():
            hov = b.collidepoint(self.mouse)
            alpha_rect(s, b, (44, 40, 26) if hov else (28, 26, 20), 5)
            pygame.draw.rect(s, (200, 176, 120), b, 1, border_radius=5)
            label = {'b1000': '借 ¥1,000', 'b3000': '借 ¥3,000',
                     'repay': '还款'}[key]
            txt(s, label, b.centerx, b.centery, 12, (240, 220, 170), 'center', bold=True)
        txt(s, f'银行欠款 ¥{self.loan:,.0f} · 每天 {int(self.LOAN_RATE * 100)}% 利息',
            r.x + 30, r.bottom - 116, 11,
            C_RED if self.loan > 0 else (150, 160, 180))
        txt(s, '购买都在主控屏下单；装备是耐用品，装上一直生效。',
            r.centerx, r.bottom - 30, 11, (120, 128, 148), 'midtop')
        cb = self.close_btn(r)
        alpha_rect(s, cb, (40, 44, 58), 6)
        txt(s, 'X', cb.centerx, cb.centery, 16, C_TEXT, 'center', bold=True)

    def storage_bag_boxes(self):
        r = self.storage_rect()
        return [pygame.Rect(r.x + 30 + i * 78, r.y + 204, 70, 78) for i in range(8)]

    def living_point(self):
        """客厅集合点（公寓是客厅，站里是食堂）。"""
        if self.scene == 'station':
            return (330, 380)
        return (500, 108)          # 公寓客厅（沙发前）

    def start_unlock_cutscene(self, st):
        """新人搬进来：先进客厅，其他人放下手里的活来欢迎，欢迎完再复工。"""
        if self.scene == 'station':
            door = DOORS.get('BALCONY') or (st.px, st.feet)
        else:
            door = (392, 655)            # 公寓大门（楼梯口那扇门）
        st.px, st.feet = float(door[0]), float(door[1])
        st.at_key = 'BALCONY'
        lx, ly = self.living_point()
        st.walk_path = self.walk_route(st.at_key, (st.px, st.feet), 'LIVING', (lx, ly))
        st.social_state = 'walk'
        mates = []
        for o in self.visible_stations():
            if o is st or o.cooking > 0 or o.resting or o.no_fatigue:
                continue          # 做饭/休息的不打扰；豆包守铺子不在屋里
            route = self.walk_route(o.at_key, (o.px, o.feet), 'LIVING', (lx, ly))
            if not route:
                continue          # 走不到客厅的就不叫了
            o.social_state = 'walk'
            o.chat_line = ''
            o.slack = 0.0         # 摸鱼被抓回来
            o.walk_path = route
            mates.append(o.m['id'])
        self.cutscene = dict(sid=st.m['id'], mates=mates, phase='gather', t=22.0, line=0.0)
        self.panel = None          # 关掉面板，不然时间冻结、演出不会动

    def update_cutscene(self, dt):
        """新人进屋：客厅集合 → 打招呼 → 各自走回去，结束才恢复时间。"""
        c = self.cutscene
        st = self.station_by_id(c['sid'])
        if st is None:
            self.cutscene = None
            return
        lx, ly = self.living_point()
        crew = [st] + [self.station_by_id(x) for x in c['mates']]
        crew = [x for x in crew if x is not None]
        for p in crew:
            if p.walk_path:
                self.step_walk(p, dt * 1.8)     # 演出里走快点，别让人干等
        c['t'] -= dt
        if c['phase'] == 'gather':
            arrived = [p for p in crew
                       if (abs(p.px - lx) < 90 and abs(p.feet - ly) < 70)]
            newcomer_ok = st in arrived
            ready = len(arrived) == len(crew)
            if c['t'] <= 0 and not newcomer_ok:
                c['t'] = 0.0            # 新人自己都没走到：别硬开场
                for p in crew:
                    p.chat_line = ''
                    p.walk_path = []
                    p.at_key = p.m['id']
                    p.social_state = 'home'
                self.cutscene = None
                self.toast_msg(f'{st.m["name"]} 搬进来了', C_GREEN, 2.2)
                return
            if ready or (c['t'] <= 0 and newcomer_ok):
                c['mates'] = [p.m['id'] for p in arrived if p is not st]
                crew2 = [p for p in crew if p in arrived]
                c['phase'] = 'greet'
                c['t'] = 2.2
                for p in crew2:
                    p.walk_path = []
                    p.social_state = 'chat'
                    p.chat_line = (f'大家好，我是 {st.m["name"]}' if p is st
                                   else f'欢迎你，{st.m["name"]}')
                # 没到的人直接放回自己房间（不瞬移到客厅）
                for p in crew:
                    if p not in arrived:
                        p.walk_path = []
                        p.at_key = p.m['id']
                        p.social_state = 'home'
        elif c['phase'] == 'greet':
            if c['t'] <= 0:
                for p in crew:
                    p.chat_line = ''
                    key = tuple(sorted((st.m['id'], p.m['id'])))
                    if p is not st and set(key) != BOND_FROZEN:
                        self.bonds[key] = max(self.bonds.get(key, 0.0), 0.35)
                    p.walk_path = self.walk_route(p.at_key, (p.px, p.feet),
                                                  p.m['id'],
                                                  (float(p.cx), float(p.home_feet)))
                c['phase'] = 'disperse'
                c['t'] = 9.0
        else:
            if all(not p.walk_path for p in crew) or c['t'] <= 0:
                for p in crew:
                    p.at_key = p.m['id']
                    p.social_state = 'home'
                    p.social_timer = random.uniform(6.0, 14.0)
                self.cutscene = None
                self.toast_msg(f'{st.m["name"]} 搬进来了 · 大家都来打了招呼', C_GREEN, 2.6)

    def click_storage(self, mx, my):
        for key, b in self.loan_buttons():
            if b.collidepoint(mx, my):
                if key == 'b1000':
                    self.borrow(1000)
                elif key == 'b3000':
                    self.borrow(3000)
                else:
                    self.repay_loan()
                return
        if self.close_btn(self.storage_rect()).collidepoint(mx, my):
            self.panel = None
            return
        items = self.bag_list()
        for i, box in enumerate(self.storage_bag_boxes()):
            if not box.collidepoint(mx, my) or i >= len(items):
                continue
            item = items[i][0]
            self.held_item = item
            self.drag_item = item
            self.drag_moved = False
            self.panel = None
            self.toast_msg('拿着了 · 再点一个 AI 装上（右键/Esc 放下）', (250, 224, 170), 2.8)
            return

    def draw_gear_panel(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 185))
        r = self.store_panel_rect()
        alpha_rect(s, r, (22, 20, 28, 248), 10)
        pygame.draw.rect(s, (236, 206, 130), r, 2, border_radius=10)

        txt(s, '装备店', r.x + 26, r.y + 16, 24, C_TEXT, bold=True)
        txt(s, '买到的道具都进背包，可以重复买；关掉这扇门，把背包里的东西拖到 AI 身上用',
            r.x + 26, r.y + 50, 12, (150, 158, 182))

        mx, my = self.mouse
        # ---------------- 左：装备 ----------------
        txt(s, '装备 · 每件都能重复买', r.x + 26, r.y + 82, 13, (236, 206, 130), bold=True)
        for g, btn in self.store_gear_btns():
            y = btn.y - 6
            have = self.bag_count(g['id'])
            draw_gear_icon(s, g['id'], r.x + 26, y + 1, 30)
            txt(s, g['name'], r.x + 66, y - 1, 12, C_TEXT, bold=True)
            txt(s, g['desc'], r.x + 66, y + 13, 9, (140, 148, 172))
            if have:
                txt(s, f'背包 ×{have}', r.x + 240, y, 9, (150, 220, 180))
            hov = btn.collidepoint(mx, my)
            can = self.money >= g['price']
            alpha_rect(s, btn, (46, 38, 24) if (hov and can) else (30, 27, 20), 5)
            pygame.draw.rect(s, (236, 206, 130) if can else (96, 88, 70), btn,
                             1, border_radius=5)
            txt(s, f'买 ¥{g["price"]}', btn.centerx, btn.y + 5, 11,
                (250, 224, 170) if can else (130, 126, 112), 'midtop', bold=True)

        # 食材（千问做饭用）
        fb = self.store_food_btn()
        have_food = self.bag_count(FOOD_ID)
        fy = fb.y - 6
        draw_bag_item_icon(s, FOOD_ID, r.x + 26, fy + 1, 30)
        txt(s, '食材包', r.x + 66, fy - 1, 12, C_TEXT, bold=True)
        txt(s, '千问做午饭/晚饭要用，一顿 1 份', r.x + 66, fy + 13, 9, (140, 148, 172))
        if have_food:
            txt(s, f'背包 ×{have_food}', r.x + 240, fy, 9, (150, 220, 180))
        hovf = fb.collidepoint(mx, my)
        canf = self.money >= FOOD_PRICE
        alpha_rect(s, fb, (46, 38, 24) if (hovf and canf) else (30, 27, 20), 5)
        pygame.draw.rect(s, (236, 206, 130) if canf else (96, 88, 70), fb, 1, border_radius=5)
        txt(s, f'买 ¥{FOOD_PRICE}', fb.centerx, fb.y + 5, 11,
            (250, 224, 170) if canf else (130, 126, 112), 'midtop', bold=True)

        # 分隔
        pygame.draw.line(s, (52, 46, 40), (r.x + 424, r.y + 80), (r.x + 424, r.bottom - 86))

        # ---------------- 右：重置卡（按线路定价）----------------
        txt(s, '重置卡 · 每条线价格不同', r.x + 470, r.y + 82, 13, (236, 206, 130), bold=True)
        txt(s, '解限流 · 清压力 · 补满额度（不降温）',
            r.x + 470, r.y + 100, 11, (132, 140, 164))
        for m, row, btn in self.store_reset_rows():
            item = RESET_PREFIX + m['id']
            have = self.bag_count(item)
            hov = btn.collidepoint(mx, my)
            can = self.money >= reset_price(m)
            alpha_rect(s, row, (32, 30, 38) if row.collidepoint(mx, my) else (26, 24, 32), 5)
            draw_card_icon(s, m['color'], r.x + 470, row.y + 7, 26)
            txt(s, m['name'], r.x + 504, row.y + 4, 13, m['color'], bold=True)
            info = f'¥{reset_price(m)}'
            if have:
                info += f'　背包 ×{have}'
            txt(s, info, r.x + 504, row.y + 21, 10,
                (150, 220, 180) if have else (140, 148, 172))
            alpha_rect(s, btn, (44, 36, 24) if (hov and can) else (30, 27, 20), 5)
            pygame.draw.rect(s, (236, 206, 130) if can else (96, 88, 70), btn,
                             1, border_radius=5)
            txt(s, f'买 ¥{reset_price(m)}', btn.centerx, btn.y + 8, 12,
                (250, 224, 170) if can else (130, 126, 112), 'midtop', bold=True)

        # ---------------- 底栏 ----------------
        pygame.draw.line(s, (52, 46, 40), (r.x + 26, r.bottom - 74), (r.right - 26, r.bottom - 74))
        txt(s, f'余额 ¥{self.money:,.0f}', r.x + 26, r.bottom - 62, 14, C_GOLD, bold=True)
        txt(s, f'背包里 {self.bag_total()} 件道具', r.x + 180, r.bottom - 60, 12,
            (150, 158, 182))
        txt(s, '提示：点「背包」按钮打开背包，把道具按住拖到房间里那个 AI 身上就能用。',
            r.x + 26, r.bottom - 34, 12, (140, 148, 172))

        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (120, 108, 80), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, (226, 214, 196), 'midtop', bold=True)

    # ------------------------------------------------ 背包面板（拖到 AI 身上用）
    def bag_panel_rect(self):
        return pygame.Rect(8, 574, 920, 140)

    def bag_close_btn(self):
        r = self.bag_panel_rect()
        return pygame.Rect(r.right - 28, r.y + 6, 20, 20)

    def bag_slots(self):
        """背包格子：[(item 或 None, rect), ...]，一屏 12 格
        （5 件装备 + 7 种重置卡刚好放得下，不会有点不到的道具）。"""
        r = self.bag_panel_rect()
        items = self.bag_list()
        out = []
        for i in range(BAG_SLOTS):
            sx = r.x + 8 + i * 62
            sy = r.y + 28
            item = items[i][0] if i < len(items) else None
            out.append((item, pygame.Rect(sx, sy, 60, 100)))
        return out

    def station_at(self, pos):
        """屏幕坐标下点到了哪个工位（世界坐标判定）。"""
        wx, wy = self.world_pos(pos)
        pad = 14 if self.held_item else 0     # 手上拿着道具时判定放宽，好点中
        for st in self.visible_stations():
            if st.rect().inflate(pad, pad).collidepoint(wx, wy):
                return st
        return None

    def click_bag(self, pos):
        """背包面板里的点击：拿起道具 / 点 AI 使用 / 关面板。"""
        if self.bag_close_btn().collidepoint(pos):
            self.panel = None
            self.held_item = None
            return
        for item, slot in self.bag_slots():
            if item and slot.collidepoint(pos) and self.bag_count(item) > 0:
                self.drag_item = item
                self.drag_start = pos
                self.drag_pos = pos
                self.drag_moved = False
                return
        st = self.station_at(pos)
        if st is not None:
            if self.held_item:
                if self.apply_item(self.held_item, st):
                    self.held_item = None
                    self.panel = None
            else:
                self.panel = ('station', st)
            return
        self.held_item = None

    def update_drag(self, pos):
        if not self.drag_item:
            return
        self.drag_pos = pos
        dx = pos[0] - self.drag_start[0]
        dy = pos[1] - self.drag_start[1]
        if dx * dx + dy * dy > 36:
            self.drag_moved = True

    def finish_drag(self, pos):
        """松手：落在 AI 身上就用掉，没怎么动就转成"手持"等下一次点击。"""
        item = self.drag_item
        if not item:
            return
        self.drag_item = None
        st = self.station_at(pos)
        if st is not None:
            if self.apply_item(item, st):
                self.panel = None
                self.held_item = None
            return
        if not self.drag_moved:
            self.held_item = item
            self.toast_msg('拿着了 · 再点一个 AI 把它用上去（Esc 放下）', (250, 224, 170), 2.8)

    def draw_bag_panel(self):
        s = self.screen
        r = self.bag_panel_rect()
        alpha_rect(s, r, (16, 18, 28, 238), 10)
        pygame.draw.rect(s, (120, 140, 180), r, 2, border_radius=10)
        txt(s, '背包', r.x + 12, r.y + 5, 14, C_TEXT, bold=True)
        txt(s, '按住拖到 AI 身上使用 · 装备最多 3 件/人 · 重置卡只对本人有效',
            r.x + 56, r.y + 7, 11, (138, 148, 174))

        mx, my = self.mouse
        items = self.bag_list()
        if not items:
            txt(s, '背包是空的 · 去右下角的装备店买点东西', r.centerx, r.y + 62, 13,
                (120, 128, 150), 'midtop')
        else:
            txt(s, f'{self.bag_total()} 件', r.right - 34, r.y + 7, 11, (150, 158, 186),
                'topright')
        for item, slot in self.bag_slots():
            hov = slot.collidepoint(mx, my)
            alpha_rect(s, slot, (30, 34, 48) if hov else (22, 25, 36), 6)
            pygame.draw.rect(s, (110, 120, 150) if hov else (52, 58, 78), slot,
                             1, border_radius=6)
            if not item:
                continue
            kind, name, short, col, model = bag_item_info(item)
            draw_bag_item_icon(s, item, slot.x + 10, slot.y + 8, 40)
            n = self.bag_count(item)
            txt(s, f'×{n}', slot.right - 6, slot.y + 5, 11, (250, 230, 180),
                'topright', bold=True)
            txt(s, short[:7], slot.centerx, slot.y + 58, 8, col, 'midtop')
            txt(s, '重置卡' if kind == BAG_KIND_RESET else '装备',
                slot.centerx, slot.y + 78, 8, (110, 118, 140), 'midtop')

        # 悬停提示
        for item, slot in self.bag_slots():
            if item and slot.collidepoint(mx, my):
                kind, name, short, col, model = bag_item_info(item)
                if kind == BAG_KIND_RESET:
                    tip = f'{name} · ¥{reset_price(model)} · 只能用在 {short} 身上'
                else:
                    g = next((x for x in GEAR if x['id'] == item), None)
                    tip = f'{name} · {g["desc"] if g else ""}'
                txt(s, tip, r.x + 880, r.y + 7, 10, (226, 214, 180), 'topright')
                break

        cb = self.bag_close_btn()
        alpha_rect(s, cb, (56, 34, 38) if cb.collidepoint(mx, my) else (34, 26, 30), 4)
        pygame.draw.rect(s, (150, 100, 106), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 2, 12, (226, 190, 190), 'midtop', bold=True)

    def delete_task(self, t):
        """从服务器里退回一条待处理任务（玩家不想接的单）。"""
        if t.state not in ('in', 'stored'):
            return False
        t.state = 'out'
        t.fade = 0
        self.t_reject += 1
        self.rep = max(0.0, self.rep - REP_REJECT)
        self.log(f'退回一条{TYPES[t.typ]["name"]}任务，声誉 -{REP_REJECT}', (206, 172, 120))
        self.toast_msg(f'退回一条{TYPES[t.typ]["name"]}', (236, 200, 140), 1.8)
        return True

    def assign(self, g, st):
        if self.tripped > 0:
            return False
        joining = (g.state == 'service' and g.multi)
        if joining:
            if len(g.crew) >= 3:
                self.toast_msg('这单最多 3 个人一起做', C_DIM)
                return False
            if st.m['id'] in g.crew:
                self.toast_msg(f'{st.m["name"]} 已经在做这单了', C_DIM)
                return False
            mates = [self.station_by_id(x) for x in g.crew]
            mates = [m for m in mates if m is not None]
            weak = [m.m['name'] for m in mates if self.bond(st, m) < 0.5]
            if weak:
                self.toast_msg(f'{st.m["name"]} 和 {"、".join(weak)} 还不够熟，没法协作', C_RED, 2.6)
                return False
            if not st.ready():
                return False
        elif not st.ready() or g.state not in ('in', 'stored'):
            return False
        qcost = self.quota_need(st, g.w)
        if not st.has_quota():
            self.toast_msg(f'{st.m["name"]} 今天额度用完了', C_RED)
            return False
        if st.cooking > 0:
            self.toast_msg(f'{st.m["name"]} 正在做饭，这半小时不接单', C_DIM)
            return False
        if st.needs_port():
            need_enc = st.m.get('need') == 'vpn_enc'
            self.toast_msg(f'{st.m["name"]} 需要先装{"加密 " if need_enc else ""}VPN 端口', C_RED)
            return False
        if st.blocked(g.typ):
            self.toast_msg(f'{st.m["name"]} 的小模型做不了{TYPES[g.typ]["name"]}', C_RED)
            return False
        slot = st.free_slot()
        if slot is None:
            return False
        if st.quest or st.social_state == 'quest':
            self.toast_msg(f'{st.m["name"]} 正在跑科考任务，等它回来再接单', C_DIM, 2.4)
            return False
        if not joining:
            g.state = 'service'
            g.station = st
            g.prog = 0.0
            g.crew = [st.m['id']]
            g.dur = max(2.0, g.w / st.spd())
        else:
            g.crew.append(st.m['id'])   # 加入协作：进度、额度都沿用这单的
        if not joining:
            # 额度是边干边扣的：扣到见底就断（见 update_station_state）
            g.qcost = float(qcost) if st.quota > 0 else 0.0
            g.qspent = 0.0
        if slot == 'busy':
            st.busy = g
        else:
            st.busy2 = g
        st.prog = 0.0
        st.dur = g.dur
        st.flash = 0.3
        if not st.at_home():
            # 人在外面串门：先走回自己房间，到了再开工（不瞬移）
            st.chat_line = ''
            st.social_state = 'back'
            st.walk_path = self.walk_route(st.at_key, (st.px, st.feet), st.m['id'],
                                           (float(st.cx), float(st.home_feet)))
            self.log(f'{st.m["name"]} 正在赶回工位，开工要等他到', (200, 200, 150))
        else:
            st.chat_line = ''
        # 面板开着就继续派下一单：连续指派，不用再点一次服务器
        if self.panel and self.panel[0] == 'server':
            self.panel = ('server', 0)
        return True

    def station_pos(self, st):
        return (st.cx, st.feet - 46)

    @staticmethod
    def rate(q, match):
        """用户打分：1~5 星。质量是主因，专长对上有加分，剩下的是运气。"""
        score = 1.0 + q * 3.2 + (0.55 if match else 0.0) + random.uniform(-0.45, 0.45)
        return max(1, min(5, int(round(score))))

    @staticmethod
    def rate_est(q, match):
        """派单前的预估星级（去掉随机项）。"""
        score = 1.0 + q * 3.2 + (0.55 if match else 0.0)
        return max(1, min(5, int(round(score))))

    def complete(self, st, g=None):
        g = g if g is not None else st.busy
        if g is None:
            return
        q = st.quality(g.typ, g)
        match = g.typ in st.m['tags']
        star = self.rate(q, match)
        rev = g.budget * self.price_mult * (REV_BASE + star * REV_PER_STAR)
        cost = g.w * st.unit_cost()
        if self.event_kind() == 'spike':
            cost *= 1.25                     # 上游涨价事件
        net = rev - cost
        self.money += net
        self.t_rev += rev
        self.t_cost += cost
        gain = (star - 2.6) * REP_PER_STAR * max(0.12, 1.0 - self.rep / 130.0)
        self.rep = max(8.0, min(100.0, self.rep + gain))
        self.last_stars.append(star)
        if len(self.last_stars) > 12:
            self.last_stars.pop(0)
        for mate in self.stations:
            if mate.busy is g:
                mate.busy = None
                mate.prog = 0.0
            elif mate.busy2 is g:
                mate.busy2 = None
                mate.prog = 0.0
        g.crew = []
        st.prog = 0.0
        # 把这一单剩下的额度结清（按秒扣会有零头）
        if st.quota >= 0 and g.qcost > 0:
            st.quota = max(0.0, st.quota - max(0.0, g.qcost - g.qspent))
        g.qcost = 0.0
        g.qspent = 0.0
        st.done += 1
        st.total_earn += net
        self.delivered[g.typ] = self.delivered.get(g.typ, 0) + 1
        if self.contract and self.contract['typ'] == g.typ:
            self.contract['today'] += 1
        self.t_orders += 1
        st.flash = 0.6
        g.state = 'out'
        g.station = None
        g.fade = 0
        # 特效
        try:
            self.sfx.play('coin')
        except Exception:
            pass
        self.texts.append([st.cx, st.feet - 58, f'+{net:.0f}', 14, C_GOLD, 1.1])
        for _ in range(10):
            self.particles.append(dict(
                x=st.cx + random.uniform(-10, 10), y=st.feet - 40,
                vx=random.uniform(-26, 26), vy=random.uniform(-52, -18),
                life=random.uniform(0.5, 1.0), color=(255, 210, 122)))
        name = TYPES[g.typ]['name']
        flag = '（专长）' if g.typ in st.m['tags'] else ''
        stars = '★' * star + '☆' * (5 - star)
        self.log(f'{st.m["name"]} 交付 {name}{flag} {stars} ¥{net:.0f}',
                 C_GREEN if star >= 3 else (C_GOLD if star == 2 else C_RED))
        self.arrange_queue()

    def overheat(self, st):
        """算力压力长时间顶满：烧了。正在跑的单作废，扣声誉。"""
        st.heat = 0.0
        st.stuck = CRASH_SEC
        self.t_crashes += 1
        st.pressure = 0.0
        for t in list(st.jobs()):
            self.abort_job(st, t)
        killed = 0
        if st.busy:
            t = st.busy
            st.busy = None
            st.prog = 0.0
            st.qcost = 0.0
            st.qspent = 0.0
            t.state = 'out'
            t.fade = 0
            killed = 1
        self.rep = max(0.0, self.rep - REP_CRASH)
        self.event = dict(kind='crash', name=f'{st.m["name"]} 算力过热', left=12.0,
                          desc=f'满负荷太久烧了，{fmt_sec_game(CRASH_SEC)}后自动重启')
        self.log(f'{st.m["name"]} 算力过热宕机：' +
                 ('1 单作废，' if killed else '') + f'声誉 -{REP_CRASH}', C_RED)
        self.toast_msg(f'{st.m["name"]} 过热宕机', C_RED, 3.0)

    def task_expire(self, g):
        g.state = 'out'
        g.fade = 0
        self.t_expired += 1
        self.rep = max(0.0, self.rep - REP_EXPIRE)
        self.log(f'一条任务等太久被用户撤单，声誉 -{REP_EXPIRE}', C_RED)
        self.arrange_queue()

    # ------------------------------------------------ 事件
    def unlock_station(self, st):
        """先把它装进公寓：一次性解锁费。"""
        cost = st.m.get('unlock', 0)
        if cost <= 0:
            st.unlocked = True
            return True
        if self.money < cost:
            self.toast_msg('钱不够解锁这条线路', C_RED)
            return False
        self.money -= cost
        st.unlocked = True
        if INTRO_ON:
            self.start_unlock_cutscene(st)
        self.log(f'给 {st.m["name"]} 装好了机器，解锁费 ¥{cost}', C_GOLD)
        self.toast_msg(f'{st.m["name"]} 已解锁，可以订阅了', C_GREEN)
        return True

    def subscribe(self, st):
        """开通订阅：当场不付钱，订阅费在每天 24:00 结算时扣。"""
        if not st.unlocked:
            if not self.unlock_station(st):
                return False
        if st.subscribed:
            return True
        st.subscribed = True
        st.refresh_daily()
        fee = st.m.get('sub', 0)
        if fee:
            self.log(f'订阅 {st.m["name"]}：每天 ¥{fee}，结算时扣', C_GOLD)
            self.toast_msg(f'{st.m["name"]} 已开通 · 每天 ¥{fee}', C_GREEN)
        else:
            self.log(f'{st.m["name"]} 免费开通', C_GREEN)
            self.toast_msg(f'{st.m["name"]} 已开通', C_GREEN)
        return True

    def toggle_intake(self):
        """网关接不接新单：停了就不再吐新任务，已有的单还能派、还能做完。"""
        self.intake = not self.intake
        if self.intake:
            self.log('网关恢复接单，新单继续进来', C_GREEN)
            self.toast_msg('恢复接单', C_GREEN, 1.8)
        else:
            self.spawn_timer = 0.6
            self.log('暂停接单：网关不再收新单，先把积压的做完', (240, 200, 130))
            self.toast_msg('已暂停接单', (240, 200, 130), 2.2)

    def pick_tier(self, st, tier):
        """点档位卡：换档要二次确认（同档位则是续费）。"""
        ts = st.tiers()
        tier = max(1, min(tier, len(ts)))
        if st.subscribed and st.sub_days > 0 and st.tier != tier:
            key = (id(st), tier)
            if getattr(self, 'pending_tier', None) != key:
                self.pending_tier = key
                self.toast_msg(f'当前还剩 {st.sub_days} 天，再点一次才换档',
                               (236, 200, 140), 2.8)
                return
        self.pending_tier = None
        self.subscribe(st, tier)

    def subscribe(self, st, tier=1):
        """订阅 = 先付 7 天的钱，当场扣掉，额度按档位发到手。"""
        if not st.unlocked:
            if not self.unlock_station(st):
                return False
        ts = st.tiers()
        tier = max(1, min(tier, len(ts)))
        name, fee, cap = ts[tier - 1]
        total = fee * SUB_DAYS
        if total > 0 and self.money < total:
            self.toast_msg(f'钱不够买 {SUB_DAYS} 天的{name}档（¥{total}）', C_RED)
            return False
        renew = st.subscribed and st.tier == tier and st.sub_days > 0
        self.money -= total
        st.tier = tier
        st.subscribed = True
        st.sub_days = st.sub_days + SUB_DAYS if renew else SUB_DAYS
        st.paused_job = False
        if not renew:
            st.refresh_daily()      # 换档才补额度；续费只加天数，不动额度
        big = '，换上了大模型' if (st.m.get('swap_tier') == tier) else ''
        cap_txt = '不限量' if cap < 0 else f'{cap}/天'
        if renew:
            self.log(f'{st.m["name"]} 续费 {SUB_DAYS} 天{name}档：¥{total}，'
                     f'还剩 {st.sub_days} 天', C_GOLD)
            self.toast_msg(f'{st.m["name"]} 续费 {SUB_DAYS} 天 · 还剩 {st.sub_days} 天', C_GOLD)
        elif fee:
            self.log(f'{st.m["name"]} 买 {SUB_DAYS} 天{name}档：¥{total}，'
                     f'额度 {cap_txt}{big}', C_GOLD)
            self.toast_msg(f'{st.m["name"]} · {name}档 {SUB_DAYS}天 ¥{total}', C_GOLD)
        else:
            self.log(f'{st.m["name"]} {name}档免费开 {SUB_DAYS} 天，额度 {cap_txt}{big}',
                     C_GREEN)
            self.toast_msg(f'{st.m["name"]} · {name}档', C_GREEN)
        return True

    def upgrade_big(self, st):
        """单独升级成大模型：一次性付费，和订阅档位无关。"""
        if not st.has_big():
            self.toast_msg('这条线路没有大模型版本', C_DIM)
            return False
        if st.big:
            self.toast_msg(f'{st.m["name"]} 已经是大模型了', C_DIM)
            return False
        cost = st.m.get('big_price', 0)
        if self.money < cost:
            self.toast_msg(f'钱不够升级大模型（¥{cost}）', C_RED)
            return False
        self.money -= cost
        st.big = True
        self.log(f'{st.m["name"]} 一次性升级成大模型（¥{cost}）：能接识图和画图了，'
                 f'但质量还是比不了旗舰线', C_GOLD)
        self.toast_msg(f'{st.m["name"]} 升级成大模型', C_GOLD, 2.6)
        return True

    def take_rest_day(self):
        """全员休息日：所有线路今天一起休，明天一起满血回归。"""
        if self.rest_day:
            self.toast_msg('今天已经是全员休息日了', C_DIM)
            return False
        busy = [st for st in self.stations if st.jobs() and not st.no_fatigue]
        if busy:
            self.toast_msg(f'{busy[0].m["name"]} 手上还有活，干完再休息', C_RED)
            return False
        self.rest_day = True
        self.rest_left = 12.0          # 休息 12 小时（游戏时间）
        for st in self.stations:
            # 豆包不休息：它守着屋外的早餐铺，是永远开工的兜底线
            if st.no_fatigue:
                st.resting = False
                continue
            st.resting = True
            st.fatigue = 0.0
            st.social_state = 'home'
            st.chat_line = ''
        self.log('全员休息 12 小时：到点自动复工', (150, 220, 180))
        self.toast_msg('全员休息 12 小时', (170, 226, 190), 2.6)
        return True

    def buy_ad(self):
        if self.money < AD_COST:
            self.toast_msg('钱不够投广告', C_RED)
            return
        self.money -= AD_COST
        self.ad_days = AD_DAYS
        self.log(f'挂了 {AD_DAYS} 天的推广，单子会多一些', C_GOLD)
        self.toast_msg(f'广告上线，{AD_DAYS} 天内来单更密', C_GOLD)

    def gw_big(self):
        """网关能接多大的单：升级后单子更大、票子更厚。"""
        return 0.72 + 0.12 * (self.gw_lv - 1)

    def gw_speed(self):
        """出单速度倍率。"""
        return 1.0 + 0.12 * (self.gw_lv - 1)

    def gw_up_cost(self):
        return int(380 * (self.gw_lv ** 1.15))

    def grid_load(self):
        """现在同时占着电路的"路"数：干活的线路 + 正在煮饭的锅。"""
        busy = sum(1 for st in self.stations if st.busy and st.on_grid())
        pots = sum(1 for st in self.stations if st.slack > 0 and st.on_grid())
        return busy + pots

    def breaker_cap(self):
        """电闸能同时带几路：Lv1 只有 2 路。豆包不在电路上，不占。"""
        return 1 + self.breaker_lv

    def breaker_up_cost(self):
        return int(520 * (self.breaker_lv ** 1.4))

    def trip(self):
        try:
            self.sfx.play('fail')
        except Exception:
            pass
        """过载太久：跳闸。电路上的活全废，豆包自己那台照跑。"""
        self.tripped = 5.0
        self.overload_t = 0.0
        self.t_trips += 1
        killed = 0
        for st in self.stations:
            if st.busy and st.on_grid():
                t = st.busy
                st.busy = None
                st.prog = 0.0
                t.qcost = 0.0
                t.qspent = 0.0
                t.state = 'out'
                t.fade = 0
                killed += 1
        self.rep = max(0.0, self.rep - REP_TRIP)
        self.log(f'用电过载跳闸！{killed} 单白跑，声誉 -{REP_TRIP}', C_RED)
        self.toast_msg('跳闸了！先停一停', C_RED, 3.0)
        self.arrange_queue()

    def breakfast_open(self):
        """早餐铺跟着早饭窗口开：06:30~08:00。"""
        return BREAKFAST_FROM <= self.hour_f() < BREAKFAST_TO

    def buy_breakfast(self):
        if self.scene == 'station':
            self.toast_msg('科考站没有早餐铺，去食堂找千问吧', C_DIM)
            return False
        if not self.breakfast_open():
            self.toast_msg(f'早餐铺只在 {BREAKFAST_FROM:02d}:00~{BREAKFAST_TO:02d}:00 开',
                           C_DIM, 2.4)
            return
        if self.breakfast_day == self.day:
            self.toast_msg('今天的早餐已经买过了', C_DIM)
            return
        if self.money < BREAKFAST_COST:
            self.toast_msg('钱不够买早餐', C_RED)
            return
        self.money -= BREAKFAST_COST
        if self.breakfast_day != self.day:
            self.meals_today += 1
            self.meal_eaten()
        self.breakfast_day = self.day
        for st in self.stations:
            if st.unlocked and st.subscribed:
                st.breakfast = BREAKFAST_SEC
        self.log(f'从楼下 Seed 那儿拎回早餐，全员 +10% 速度（{fmt_sec_game(BREAKFAST_SEC)}）',
                 (232, 190, 120))
        self.toast_msg(f'早餐到岗 · 全员 +10%（{fmt_sec_game(BREAKFAST_SEC)}）',
                       (232, 190, 120))
        self.panel = None

    def social_event(self):
        """每天小概率发生一次人际小事：合得来的一起吃夜宵，合不来的拌嘴。"""
        if random.random() > 0.35:
            return
        live = [x for x in self.stations if x.unlocked and not x.no_fatigue]
        if len(live) < 2:
            return
        a, b = random.sample(live, 2)
        key = tuple(sorted((a.m['id'], b.m['id'])))
        if key == ('ChatGPT', 'Grok'):
            return
        v = self.bonds.get(key, 0.0)
        if v >= 0.6:
            self.bonds[key] = min(1.0, v + 0.04)
            self.log(f'{a.m["name"]} 和 {b.m["name"]} 一起吃了顿夜宵，关系更近了', (238, 170, 190))
        elif v <= 0.15:
            self.bonds[key] = max(-1.0, v - 0.05)
            self.log(f'{a.m["name"]} 和 {b.m["name"]} 因为排班拌了几句嘴', (210, 150, 150))

    def roll_event(self):
        if self.event:
            return
        # 限流不再随机发生，改成"用得太狠"才触发（见 update_station_state）
        pool = ['burst', 'wordofmouth']
        kind = random.choice(pool)
        if kind == 'burst':
            self.burst = 24.0
            self.event = dict(kind=kind, name='突发爆单', left=24.0,
                              desc='客流量翻倍，撑住！')
            self.log('爆单了！客流量翻倍', C_GOLD)
        else:
            self.rep = min(100.0, self.rep + 4)
            self.event = dict(kind='rep', name='口碑传播', left=4.0,
                              desc='有人在群里夸了你，声誉 +4')
            self.log('有人在群里夸了你，声誉 +4', C_GREEN)
            return
        self.toast_msg(self.event['name'], C_GOLD)

    # ------------------------------------------------ 更新
    def update(self, dt):
        if self.paused:
            # 暂停时连粒子/提示条也冻住（之前只靠主循环不调用 update，
            # 直接被调用时仍会推进，失焦暂停就形同虚设）
            return
        real_dt = dt
        dt *= self.speed
        # 任何面板打开都暂停营业：计时、进度、耐心全部停住
        if self.panel:
            dt = 0.0
        # 昼夜随时同步（面板打开时时间冻结，但 GLM 的作息读数也要对）
        global CUR_NIGHT, GAME_COLD, GAME_MEAL_PENALTY, GAME_POLAR
        CUR_NIGHT = self.is_night()
        GAME_COLD = bool(self.cold and self.scene == 'station')
        GAME_MEAL_PENALTY = float(self.meal_penalty or 0.0)
        self.polar = bool(self.scene == 'station' and self.day >= POLAR_DAY)
        GAME_POLAR = self.polar

        if self.toast:
            self.toast[1] -= real_dt * self.speed
            if self.toast[1] <= 0:
                self.toast = None

        # 特效
        for p in self.particles:
            p['x'] += p['vx'] * dt
            p['y'] += p['vy'] * dt
            p['vy'] += 90 * dt
            p['life'] -= dt
        self.particles = [p for p in self.particles if p['life'] > 0]
        for fx in self.texts:
            fx[1] -= 22 * dt
            fx[5] -= dt
        self.texts = [fx for fx in self.texts if fx[5] > 0]

        if self.state != 'play' or dt <= 0:
            return
        if INTRO_ON and not self.seen_apt_intro and self.scene == 'apartment':
            self.seen_apt_intro = True
            self.panel = ('intro', 'apt')

        if self.cutscene:
            # 演出期间时间暂停：这一段在 self.t += dt 之前，所以什么都不用减
            self.update_cutscene(dt)
            for _s in self.stations:
                self.update_station_anim(_s, dt)
            return
        self.t += dt
        # 工位计时
        for s in self.stations:
            self.update_station_state(s, dt)
            self.update_social(s, dt)
            if s.paused_job:
                continue
            if s.jobs() and not s.at_home():
                continue        # 人还没回到工位，先不开工
            for g in list(s.jobs()):
                dp = dt * s.work_factor() / max(0.5, g.dur)   # 限流时这里只有 20%
                self.burn_quota(s, g, dp)
                if g.state != 'service':     # 额度见底，活断了
                    continue
                g.prog += dp
                if g.prog >= 1.0:
                    self.complete(s, g)

        if self.rest_left > 0:
            self.rest_left -= dt * 24.0 / DAY_LEN
            if self.rest_left <= 0:
                self.rest_left = 0.0
                self.rest_day = False
                for st in self.stations:
                    st.resting = False
                self.log('休息结束，全员复工', (150, 220, 180))
                self.toast_msg('休息结束 · 复工', (170, 226, 190), 2.4)
        if not self.daily_goals:
            self.build_daily_goals()
        self.check_daily_goals()
        self.update_main_quest()
        self.check_achievements()
        self.update_south_quest()
        if INTRO_ON and self.state == 'play' and not self.panel:
            if (not self.comic2_done and self.scene == 'apartment'
                    and self.day <= 12
                    and sum(1 for x in self.stations if x.unlocked) >= 5):
                self.comic2_done = True
                self.show_comic([1])
            elif (not self.comic3_done and self.scene == 'apartment'
                  and self.can_relocate()):
                self.comic3_done = True
                self.show_comic([2])
        if self.auto_dispatch:
            self.auto_assign()
        self.update_meals(dt)
        self.update_greenhouse(dt)
        self.update_quests(dt)
        self.update_bonds()
        self.update_encounters(dt)
        self.tripped = max(0.0, self.tripped - dt)
        busy_n = self.grid_load()
        if self.tripped <= 0 and busy_n > self.breaker_cap():
            self.overload_t += dt
            if self.overload_t >= 9.0:
                self.trip()
        else:
            self.overload_t = max(0.0, self.overload_t - dt * 1.2)

        for st in self.stations:
            self.update_station_anim(st, dt)

        self.burst = max(0.0, self.burst - dt)

        # 网关吐单：队列越满，来单间隔越长（避免排队超时撤单）
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            if self.intake:
                self.try_spawn()
            iv = self.spawn_interval()
            qn = len(self.queued_tasks())
            if qn:
                iv *= 1.0 + 1.25 * qn / max(1, len(TASK_SLOTS))   # 队列越满，吐单越慢
            self.spawn_timer = iv

        # 早餐铺开张提醒（每天只在开张那一刻报一次；科考站没有早餐铺）
        if (self.scene == 'apartment' and self.breakfast_open()
                and self.bf_notice_day != self.day
                and self.breakfast_day != self.day):
            self.bf_notice_day = self.day
            self.log('楼下早餐铺开张了，06:30~08:00 能买', (240, 200, 130))
            self.toast_msg('早餐铺开张了 · 06:30~08:00', (255, 214, 152), 3.0)

        for g in list(self.tasks):
            g.bob += dt * 3
            if g.state == 'in':
                if g.update(dt):
                    g.state = 'stored'      # 进了服务器就不在场景里画了
            elif g.state == 'stored':
                g.wait += dt
                if g.wait >= g.patience:
                    self.task_expire(g)
                    self.tasks.remove(g)
            elif g.state == 'out':
                g.fade -= dt * 400
                if g.fade <= 0:
                    self.tasks.remove(g)

        # 事件
        if self.event:
            self.event['left'] -= dt
            if self.event['left'] <= 0:
                if self.event['kind'] == 'burst':
                    self.burst = 0.0
                self.event = None
        elif self.t > 8 and random.random() < dt * 0.040:
            self.roll_event()

        # 24:00 结账（不打断手上的活，也不清待处理任务）
        if not self.settled and self.t >= self.settle_point():
            self.settled = True
            self.end_day()
            if self.state == 'over':
                return
        # 次日 08:00：时间轴归零，进入新的一天
        if self.t >= DAY_LEN:
            self.t -= DAY_LEN
            self.settled = False

    def update_station_state(self, s, dt):
        """每条线的状态计时：限流压力 / 摸鱼 / 零食 / 到期复位。"""
        s.snack = max(0.0, s.snack - dt)
        s.meal = max(0.0, s.meal - dt)
        s.breakfast = max(0.0, s.breakfast - dt)
        s.flash = max(0.0, s.flash - dt)
        s.cooldown = max(0.0, s.cooldown - dt)
        s.shock = max(0.0, s.shock - dt)
        if s.stuck > 0:
            s.stuck = max(0.0, s.stuck - dt)

        # ---- 上游限流：限流中压力冻结；等手上这单干完才解除、再开始回落 ----
        if s.limited:
            if s.busy is None:
                s.limited = False
                s.paused_job = False
                s.strain = STRAIN_RESET      # 留一点余温，避免刚解除又被限
                s.strain_warned = False
                self.log(f'{s.m["name"]} 手头的活干完了，限流解除、速度复原', C_GREEN)
                self.toast_msg(f'{s.m["name"]} 限流解除', C_GREEN, 2.0)
            # 限流期间 strain 不动，等解除了再走下面的回落
        elif s.jobs() and not s.paused_job:
            j = s.main_job()
            load = min(1.0, (j.w / 120.0) * (3.6 / max(1.6, s.spd())))
            s.strain = min(1.2, s.strain + dt * (0.70 + 0.60 * load) / STRAIN_FULL)
            if s.strain >= STRAIN_WARN and not s.strain_warned:
                s.strain_warned = True
                self.log(f'{s.m["name"]} 连轴转太久了，上游开始盯人', C_GOLD)
                self.toast_msg(f'{s.m["name"]} 快被限流了，让它歇会儿', C_GOLD, 2.4)
            if s.strain >= 1.0:
                self.throttle(s)
        else:
            s.strain = max(0.0, s.strain - dt / STRAIN_DECAY)
            if s.strain < STRAIN_WARN * 0.6:
                s.strain_warned = False

        # ---- 疲劳：一直干活会累，闲着（或休假）会缓过来 ----
        # 豆包不累：它守着屋外的早餐铺，不在公寓里上班
        if s.no_fatigue:
            s.fatigue = 0.0
        else:
            working = bool(s.jobs()) and not s.paused_job
            if working:
                rate = dt / FATIGUE_FULL
                if GAME_POLAR:
                    rate *= 0.45 if s.m.get('rhythm') else 1.35
                s.fatigue = min(1.0, s.fatigue + rate)
            elif s.resting:
                s.fatigue = max(0.0, s.fatigue - dt / 20.0)
            # 闲着不会恢复疲劳：只有"全员休息日"才能把疲惫清掉。

        # ---- 摸鱼：DeepSeek 偷偷煮大白饭 ----
        if s.slack > 0:
            s.slack = max(0.0, s.slack - dt)
            if s.slack <= 0:
                self.slack_done(s)
        elif (s.m['id'] == 'DeepSeek' and s.unlocked and s.subscribed
              and s.stuck <= 0 and not s.limited and not s.resting
              and s.cooldown <= 0 and s.social_state == 'home'):
            s.slack_cd = max(0.0, s.slack_cd - dt)
            if s.slack_cd <= 0 and random.random() < dt * 0.032:
                self.start_slack(s)

    def hall_of(self, key):
        """某个房间所在的那一段过道（世界 y 的范围）。"""
        dy = DOORS.get(key, DOORS['SERVER'])[1]
        best = HALLS[0]
        bd = 1e9
        for lo, hi in HALLS:
            d = 0 if lo <= dy <= hi else min(abs(dy - lo), abs(dy - hi))
            if d < bd:
                bd, best = d, (lo, hi)
        return best

    def walk_route(self, from_key, from_pt, to_key, to_pt):
        """规划一条路线。有行走掩码就走 A*，否则走房门 + 过道的老路线。"""
        if self.walkmask is not None:
            pts = self.walkmask.route(from_pt, to_pt)
            if pts:
                return pts
        return self.walk_route_doors(from_key, from_pt, to_key, to_pt)

    def walk_route_doors(self, from_key, from_pt, to_key, to_pt):
        """规划一条只走房门和过道的路线，横平竖直，不斜切墙角。

        过道是公寓正中那条竖道，被门框分成几段，每段只通一层：
        左列房间的门开在过道左边，右列房间的门开在过道右边。
        路线固定是：房间内 → 自己房门 → 过道 → 沿过道上下 → 对门 → 目标房间。
        每一段要么纯横、要么纯竖，所以不会出现"斜着穿墙"的轨迹。
        """
        fx, fy = float(from_pt[0]), float(from_pt[1])
        tx, ty = float(to_pt[0]), float(to_pt[1])
        if from_key == to_key:
            if CORR_L <= fx <= CORR_R:
                # at_key 还是旧房间、人其实在过道里：先回自己的门再进屋，别斜穿墙
                dd = DOORS.get(to_key, DOORS['SERVER'])
                return [(fx, fy), (float(dd[0]), fy), (tx, ty)]
            return [(fx, fy), (tx, ty)]          # 同一个房间，直接过去
        in_hall = CORR_L <= fx <= CORR_R
        sd = DOORS.get(from_key, DOORS['SERVER'])
        dd = DOORS.get(to_key, DOORS['SERVER'])
        pts = [(fx, fy)]
        if not in_hall:
            pts.append((float(sd[0]), float(sd[1])))        # 1. 走到自己房门
            pts.append((float(CORR_X), float(sd[1])))       # 2. 迈步进过道
        else:
            pts.append((float(CORR_X), fy))                 # 已经在过道里了
        if self.same_hall(from_key, to_key):
            lo, hi = self.hall_of(from_key)
            # 3. 沿过道上下对齐目标门（夹在本段过道内，不越段）
            ny = max(lo + 3.0, min(hi - 3.0, float(dd[1])))
            pts.append((float(CORR_X), ny))
            pts.append((float(dd[0]), ny))                  # 4. 横穿到对门
            pts.append((tx, ty))                            # 5. 进目标房间
        else:
            # 不同段：过道被门框隔断，段与段之间不通。
            # 正常不会出现（pick_social_dest 已限制同层），这里只走到本段中间兜底。
            lo, hi = self.hall_of(from_key)
            pts.append((float(CORR_X), (lo + hi) / 2.0))
        return pts

    def clamp_walk(self, s, nx, ny):
        """把下一步的位置夹在"可走区域"里，绝不让角色穿进墙里。

        - 在过道里：x 锁在通道宽度内，y 锁在本段过道内；
        - 过道 ↔ 房间那一步是横向过门，y 保持不变；
        - 在房间里：不能越过通道中心跑到对侧房间去。
        """
        if self.walkmask is not None:
            # 有掩码就以掩码为准：下一步落在墙格里就不许动
            if not self.walkmask.free(*self.walkmask.cell_of(nx, ny)):
                return s.px, s.feet
            return nx, ny
        tgt = s.walk_path[0] if s.walk_path else (nx, ny)
        in_hall = CORR_L <= s.px <= CORR_R
        tgt_in_hall = CORR_L <= tgt[0] <= CORR_R
        if in_hall and tgt_in_hall:
            nx = max(CORR_L, min(CORR_R, nx))
            lo, hi = self.hall_of(s.at_key)
            ny = max(lo - 1.0, min(hi + 1.0, ny))
        elif in_hall != tgt_in_hall:
            ny = s.feet          # 只走横的，从门里穿过去
        else:
            if s.px < CORR_X:
                nx = min(nx, CORR_X + 2.0)
            else:
                nx = max(nx, CORR_X - 2.0)
        return nx, ny

    def _walk_axis(self, s, dx, dy, step, horizontal_first):
        """在某个轴上挪一步；这个方向被墙挡住就返回 None。"""
        if horizontal_first == (abs(dx) >= 1.2):
            d = min(abs(dx), step)
            nx, ny = s.px + d * (1 if dx > 0 else -1), s.feet
        else:
            d = min(abs(dy), step)
            nx, ny = s.px, s.feet + d * (1 if dy > 0 else -1)
        nx, ny = self.clamp_walk(s, nx, ny)
        moved = math.hypot(nx - s.px, ny - s.feet)
        if moved < 0.01:
            return None
        if abs(nx - s.px) > 0.01:
            s.dir = 1 if nx > s.px else -1
        s.px, s.feet = nx, ny
        return moved

    def step_walk(self, s, dt):
        """沿着路点往前走：先横后竖；横的撞墙就改先竖（贴墙角时不至于卡死）。"""
        # 人在外面被派了活：回家这一段走快点，别让单子干等
        boost = RETURN_BOOST if (s.social_state == 'back' and s.jobs()) else 1.0
        step = SOCIAL_SPD * boost * dt
        while s.walk_path:
            tx, ty = s.walk_path[0]
            dx, dy = tx - s.px, ty - s.feet
            if abs(dx) < 1.2 and abs(dy) < 1.2:
                s.px, s.feet = float(tx), float(ty)
                s.walk_path.pop(0)
                continue
            moved = self._walk_axis(s, dx, dy, step, True)
            if moved is None:
                moved = self._walk_axis(s, dx, dy, step, False)
            if moved is None:
                s.walk_idle += dt   # 两个方向都被墙挡住（看门狗会兜底）
                return
            s.walk_idle = 0.0
            step -= moved
            if step <= 1e-9:        # 浮点余量要吃掉，否则下一步位移是 0 会被误判成到达
                return
        # 走到了
        if s.social_state == 'walk':
            if s.social_target:
                # 去找人：走到了还没碰上（人挪窝了），别自己对着空气聊天，重新规划
                mate = self.station_by_id(s.social_target)
                if mate is not None and self.can_chat(s, mate, 48):
                    s.at_key = mate.at_key
                    self.begin_chat(s, mate)
                else:
                    s.repath_t = 0.0
            else:
                s.social_state = 'chat'
                s.at_key = s.social_dest_key
                s.chat_line = random.choice(CHAT_LINES)
                s.social_timer = random.uniform(2.5, 5.0)
                self.separate_from_others(s)
        elif s.social_state == 'back':
            s.social_state = 'home'
            s.at_key = s.m['id']
            s.social_timer = random.uniform(25.0, 55.0)
            if abs(s.px - s.cx) < 3 and abs(s.feet - s.home_feet) < 3:
                s.px, s.feet = float(s.cx), float(s.home_feet)   # 到门口对齐一下

    def same_hall(self, k1, k2):
        """两个地方是否在同一条过道上（过道被门框分段，段与段之间不通）。"""
        return self.hall_of(k1) == self.hall_of(k2)

    def too_close(self, pt, me, dist=34.0):
        """这个点是不是离别人太近（别站人身上）。"""
        for o in self.stations:
            if o is me or not o.unlocked:
                continue
            if abs(o.px - pt[0]) < dist and abs(o.feet - pt[1]) < dist * 0.75:
                return True
        return False

    def separate_from_others(self, s):
        """刚停下聊天时，和旁边的人错开，别叠在一起。"""
        for o in self.stations:
            if o is s or not o.unlocked:
                continue

    def station_by_id(self, sid):
        for x in self.stations:
            if x.m['id'] == sid:
                return x
        return None

    @staticmethod
    def dist_between(a, b):
        return math.hypot(a.px - b.px, a.feet - b.feet)

    def can_chat(self, a, b, dist=46.0):
        """两个人是不是"面对面"：够近，而且中间没隔着墙。"""
        if a is b or not b.unlocked:
            return False
        if self.bond(a, b) < 0:
            return False          # 合不来的两个人不会主动搭话
        if self.dist_between(a, b) > dist:
            return False
        if self.walkmask is not None:
            ca = self.walkmask.cell_of(a.px, a.feet)
            cb = self.walkmask.cell_of(b.px, b.feet)
            if self.walkmask.free(*ca) and self.walkmask.free(*cb):
                if not self.walkmask.clear_line((a.px, a.feet), (b.px, b.feet)):
                    return False
        return True

    def pick_partner(self, s):
        """挑一个可以搭话的人（有活的、休假的、摸鱼的不打扰）。"""
        masked = self.walkmask is not None
        cands = []
        for o in self.stations:
            if o is s or not (o.unlocked and o.subscribed and o.on_grid()):
                continue
            if o.jobs() or o.resting or o.slack > 0 or o.stuck > 0:
                continue
            if self.bond(s, o) < 0:
                continue          # 不喜欢的人不专门去找
            if not masked and not self.same_hall(s.m['id'], o.at_key):
                continue      # 没掩码只能同层；要看他现在实际在哪一层
            if masked and self.walkmask.route((s.px, s.feet), (o.px, o.feet)) is None:
                continue
            cands.append(o)
        if not cands:
            return None
        weights = [1.0 / (self.dist_between(s, o) + 60.0) for o in cands]
        r = random.uniform(0.0, sum(weights))
        acc = 0.0
        for o, w in zip(cands, weights):
            acc += w
            if r <= acc:
                return o
        return cands[-1]

    def pick_spot(self, s):
        """去客厅 / 厨房 / 阳台这种公共区域（没人可找时的备选）。"""
        masked = self.walkmask is not None

        def snap(pt):
            if not masked:
                return pt
            nf = self.walkmask.nearest_free(*self.walkmask.cell_of(*pt))
            return self.walkmask.center(*nf) if nf else pt

        cands = []
        for name, (px, py) in SPOTS:
            key = {'客厅': 'SERVER', '厨房': 'KITCHEN', '阳台': 'BALCONY'}[name]
            pt = snap((px + random.uniform(-16, 16), py + random.uniform(-4, 4)))
            if masked:
                if self.walkmask.route((s.px, s.feet), pt) is None:
                    continue
                if self.too_close(pt, s, 34):
                    continue
            elif not self.same_hall(s.m['id'], key):
                continue
            cands.append((key, pt, name))
        if not cands:
            d = DOORS.get(s.m['id'], DOORS['SERVER'])
            return s.m['id'], (d[0] + (8 if d[0] < CORR_X else -8), d[1]), '自己门口'
        return random.choice(cands)

    # ------------------------------------------------ 千问做饭
    def take_food(self, n=1):
        """做饭拿食材：先掏仓库，再掏背包。"""
        if self.warehouse.get('food', 0) >= n:
            self.warehouse['food'] -= n
            return True
        return self.bag_take(FOOD_ID)

    def pick_quest_worker(self):
        """找一个有空的人去跑科考任务。"""
        for st in self.visible_stations():
            if self.worker_available(st):
                return st
        return None

    def start_quest_worker(self, kind, legs, who=None):
        """legs = [(目的地 key, 坐标, 分钟, 疲劳), ...]：一路走完再结算。"""
        st = who or self.pick_quest_worker()
        if st is None:
            self.toast_msg('所有人都没空，等他们闲下来再点', C_DIM)
            return False
        if st.quest or st.social_state == 'quest':
            return False
        key, pt, minutes, fatigue = legs[0]
        if st.social_state in ('chat', 'roam', 'walk'):
            st.social_state = 'home'
            st.chat_line = ''
            st.chat_partner = None
            st.roam_t = 0.0
        st.quest = dict(kind=kind, legs=legs, leg=0, fatigue=0.0)
        st.quest_t = minutes / GAME_MIN_PER_SEC
        st.quest_walk = 0.0
        st.social_state = 'quest'
        st.chat_line = ''
        st.chat_partner = None
        st.social_target = None
        st.walk_path = self.walk_route(st.at_key, (st.px, st.feet), key, pt)
        self.log(f'{st.m["name"]} 去跑科考任务（{kind}）', (170, 210, 230))
        return True

    def quest_progress(self, s):
        """科考任务完成到哪一步（0~1），用来画进度条。"""
        q = s.quest
        if not q:
            return 0.0
        legs = q.get('legs') or []
        if not legs:
            return 0.0
        total = max(1, len(legs))
        done = q.get('leg', 0)
        cur = 0.0
        if done < total:
            need = legs[done][2] / GAME_MIN_PER_SEC
            if need > 0:
                cur = 1.0 - max(0.0, s.quest_t) / need
        return min(1.0, (done + max(0.0, cur)) / total)

    def update_quest_worker(self, s, dt):
        q = s.quest or {}
        legs = q.get('legs') or []
        # 先走过去，到了才开始计时；走太久（路不通）就兜底直接干
        if s.walk_path:
            self.step_walk(s, dt)
            self.life_watchdog(s, dt)
            s.quest_walk = getattr(s, 'quest_walk', 0.0) + dt
            if s.quest_walk < 12.0:
                return
            s.quest_walk = 0.0
        s.quest_t = max(0.0, s.quest_t - dt)
        if s.quest_t > 0:
            return
        # 这一段干完了
        leg = q.get('leg', 0)
        if leg < len(legs):
            s.fatigue = min(1.0, s.fatigue + legs[leg][3])
        leg += 1
        if leg < len(legs):
            q['leg'] = leg
            key, pt, minutes, fatigue = legs[leg]
            s.quest_t = minutes / GAME_MIN_PER_SEC
            s.quest_walk = 0.0
            s.walk_path = self.walk_route(s.at_key, (s.px, s.feet), key, pt)
            s.at_key = key
            self.log(f'{s.m["name"]} 赶往下一站（{key}）', (150, 200, 220))
            return
        # 全部走完：结算
        kind = q.get('kind')
        s.quest = None
        s.quest_t = 0.0
        self.finish_quest(kind, worker=s)
        self.walk_home(s)
        s.social_timer = random.uniform(8, 20)

    def finish_quest(self, kind, worker=None):
        if kind and kind.startswith('weather:'):
            idx = int(kind.split(':')[1])
            self.weather[idx] = 3
            self.money += 60
            self.rep = min(100.0, self.rep + 0.3)
            self.south_weather += 1
            self.log(f'第 {idx + 1} 趟气象数据上传成功 · ¥60', C_GOLD)
            self.toast_msg('气象数据上传 +¥60', C_GOLD, 2.4)
        elif kind == 'ice':
            self.ice = 0
            if self.ice_runs >= 2:
                self.ice_done = self.day
            self.money += 300
            self.rep = min(100.0, self.rep + 2.0)
            self.south_ice += 1
            self.log('冰样结果上传成功 · 奖金 ¥300，声誉 +2', C_GOLD)
            self.toast_msg('冰样上传成功 · ¥300', C_GOLD, 3.0)
        elif kind == 'green':
            if worker is not None and worker.m['id'] == 'Qwen':
                self.warehouse['food'] += 2
                self.log('千问照顾温室，收成 +2 食材', (150, 220, 160))
            elif worker is not None:
                self.log(f'{worker.m["name"]} 去温室帮了把手，但它不认得作物，没收成',
                         (190, 180, 150))

    def update_quests(self, dt):
        """科考站任务链：气象一天两趟、时间随机；冰样随时可做但要等上一趟。"""
        if self.scene != 'station':
            return
        if self.quest_day != self.day:
            self.quest_day = self.day
            self.weather = [0, 0]
            self.ice_runs = 0
            # 每天随机两个发布点（8~20 点之间），两次至少隔 3 小时
            a = random.uniform(8.0, 15.0)
            b = random.uniform(a + 3.0, 20.0)
            self.weather_at = [a, b]
        busy = any(w in (1, 2) for w in self.weather)     # 还有没做完的
        if not busy:
            hour = self.hour_f()
            for i in range(2):
                if self.weather[i] == 0 and hour >= self.weather_at[i]:
                    self.weather[i] = 1
                    self.log(f'气象数据发布（第 {i + 1} 趟）· 去气象室采一趟',
                             (150, 210, 230))
                    self.toast_msg('新的气象任务来了', (150, 210, 230), 2.4)
                    break

    def field_fatigue(self, amount):
        """采数据 / 化验这类外勤：给一条在线线路加疲劳。"""
        st = self.station_by_id('DeepSeek')
        if st is None or not (st.unlocked and st.subscribed):
            st = next((x for x in self.stations
                       if x.unlocked and x.subscribed), None)
        if st is not None:
            st.fatigue = min(1.0, st.fatigue + amount)

    def quest_day_end(self):
        """打烊结算气象任务：没交的有惩罚。"""
        if self.scene != 'station':
            return
        miss = sum(1 for w in self.weather if w in (1, 2))
        if miss:
            self.rep = max(0.0, self.rep - 1.0 * miss)
            self.money -= 60 * miss
            self.log(f'气象数据有 {miss} 趟没交：声誉 -{miss}，罚 ¥{60 * miss}', C_RED)
            self.toast_msg(f'气象数据没交够 · 声誉 -{miss}', C_RED, 3.0)

    def update_greenhouse(self, dt):
        """温室每天收一次：千问有空去照顾才有收成。"""
        if self.scene != 'station':
            return
        if getattr(self, 'green_day', -1) == self.day or self.hour_f() < 10:
            return
        self.green_day = self.day
        qw = self.station_by_id('Qwen')
        if (qw and qw.unlocked and qw.subscribed and not qw.jobs()
                and not qw.resting):
            if self.start_quest_worker('green',
                                       [('GREEN', GREEN_POINT, 30, 0.06)], who=qw):
                self.green_day = self.day
        else:
            self.log('千问今天没空去温室，没有收成', (190, 160, 150))

    def meal_eaten(self):
        """吃到一顿：之前缺饭的惩罚立刻清掉。"""
        global GAME_MEAL_PENALTY
        self.meal_missed = 0
        self.meal_penalty = 0.0
        GAME_MEAL_PENALTY = 0.0

    def meal_missed_one(self):
        """错过一顿：当场开始减速，持续到下一顿。"""
        global GAME_MEAL_PENALTY
        self.meal_missed = min(3, self.meal_missed + 1)
        self.meal_penalty = min(0.45, 0.15 * self.meal_missed)
        GAME_MEAL_PENALTY = self.meal_penalty
        self.log(f'这顿没吃上 · 全员效率 -{int(self.meal_penalty * 100)}%（吃到下一顿恢复）',
                 (220, 150, 140))

    def update_meals(self, dt):
        """饭点前后半小时内，千问有空就去做饭；同一顿只触发一次。

        - 窗口 = 整点 ±30 分钟（7:30~8:30 / 11:30~12:30 / 17:30~18:30）
        - 窗口内什么时候有空什么时候做，做过就不再做第二次
        - 窗口过了还没吃上，记一顿“没赶上”
        """
        if self.day != self.meal_day:
            self.meal_day = self.day
            self.meal_done.clear()
            self.meal_nag.clear()
            self.meals_today = 0
        qw = self.station_by_id('Qwen')
        hour = self.hour_f()
        for slot in MEAL_SLOTS:
            if slot in self.meal_done:
                continue
            lo, hi = slot - 0.5, slot + 0.5
            if hour < lo:
                continue
            if hour > hi:
                self.meal_done.add(slot)          # 窗口过了，这顿没了
                if slot not in self.meal_nag:
                    self.meal_nag.add(slot)
                    self.meal_missed_one()
                continue
            if slot == 7:
                if self.scene == 'apartment':
                    # 公寓：早饭去早餐铺买，不做饭
                    if self.breakfast_day == self.day:
                        self.meal_done.add(slot)
                    elif slot not in self.meal_nag:
                        self.meal_nag.add(slot)
                        self.log('还没买早饭（楼下早餐铺 7~9 点）', (220, 200, 150))
                    continue
                # 科考站：仓库里有食材就自己吃
                if self.take_food():
                    self.meal_done.add(slot)
                    self.meals_today += 1
                    self.meal_eaten()
                    self.log('早饭吃过了', (200, 220, 190))
                elif slot not in self.meal_nag:
                    self.meal_nag.add(slot)
                    self.log('早饭还没食材，再等等', (220, 160, 140))
                continue
            if qw is None or not (qw.unlocked and qw.subscribed):
                continue
            if qw.cooking > 0 or qw.jobs() or qw.resting or qw.stuck > 0 or qw.slack > 0:
                continue          # 千问忙着，窗口内再等机会
            if not self.take_food():
                if slot not in self.meal_nag:
                    self.meal_nag.add(slot)
                    self.toast_msg('没食材了 · DeepSeek 出去抓鱼', (240, 200, 140), 2.6)
                    self.log('厨房没食材，DeepSeek 抄网兜去冰窟窿了', (200, 180, 140))
                self.start_fishing()
                continue
            self.start_cooking(qw, slot)
            self.meal_done.add(slot)              # 这顿开始做了，窗口内不再触发

    def start_cooking(self, s, slot):
        s.cooking = MEAL_COOK_SEC
        s.meal_slot = slot
        s.social_state = 'cook'
        s.chat_line = ''
        s.chat_partner = None
        s.social_target = None
        kx, ky = COOK_POINT
        s.walk_path = self.walk_route(s.at_key, (s.px, s.feet), 'KITCHEN', (kx, ky))
        meal = '午饭' if slot == 12 else '晚饭'
        self.log(f'千问去厨房做{meal}了（这一顿不能派单）', (240, 200, 140))
        self.toast_msg(f'千问去做{meal}了 · 这半小时别派他', (240, 200, 140), 2.4)

    def update_cooking(self, s, dt):
        """做饭：先走到厨房，再倒计时；做完给全站开饭。"""
        if s.walk_path:
            self.step_walk(s, dt)
            return
        if s.cooking > 0:
            s.cooking = max(0.0, s.cooking - dt)
            if s.cooking <= 0:
                self.finish_meal(s)

    def finish_meal(self, s):
        meal = '午饭' if s.meal_slot == 12 else '晚饭'
        n = 0
        for st in self.stations:
            if st.unlocked and st.subscribed:
                heal = MEAL_FATIGUE if self.scene == 'station' else 0.20
                st.fatigue = max(0.0, st.fatigue - heal)
                st.meal = MEAL_BUFF_SEC
                st.bond_boost = st.bond_boost
                n += 1
        self.meals_today += 1
        self.meal_eaten()
        self.texts.append([s.px, s.feet - 42, '开饭！', 13, C_GOLD, 1.8])
        pct = int((MEAL_FATIGUE if self.scene == 'station' else 0.20) * 100)
        self.log(f'千问的{meal}做好了：{n} 条线疲劳 -{pct}%、'
                 f'速度 +{int(MEAL_BUFF * 100)}%（{fmt_sec_game(MEAL_BUFF_SEC)}）',
                 C_GOLD)
        try:
            self.sfx.play('meal')
        except Exception:
            pass
        self.toast_msg(f'{meal}好了 · 全站疲劳 -{pct}% / '
                       f'速度 +{int(MEAL_BUFF * 100)}%', C_GOLD, 3.0)
        self.walk_home(s)
        s.social_timer = random.uniform(20.0, 40.0)

    def start_fishing(self):
        """没食材时：DeepSeek 去气闸外凿冰抓鱼（只有科考站，公寓没有冰窟窿）。"""
        if self.scene != 'station':
            return False
        ds = self.station_by_id('DeepSeek')
        if ds is None or not (ds.unlocked and ds.subscribed):
            return False
        if ds.fish > 0 or ds.social_state == 'fish' or ds.jobs():
            return False
        ds.fish = 30 / GAME_MIN_PER_SEC
        ds.social_state = 'fish'
        ds.chat_line = ''
        ds.chat_partner = None
        ds.social_target = None
        ds.walk_path = self.walk_route(ds.at_key, (ds.px, ds.feet), 'BALCONY',
                                       (370, 700))
        self.log('DeepSeek 出去抓鱼了', (150, 210, 220))
        return True

    def update_fishing(self, s, dt):
        if s.walk_path:
            self.step_walk(s, dt)
            return
        s.fish = max(0.0, s.fish - dt)
        if s.fish <= 0:
            self.warehouse['food'] += 2
            s.fatigue = min(1.0, s.fatigue + FISH_FATIGUE)
            self.log('DeepSeek 拎回来 2 条鱼（食材 +2）', (150, 220, 200))
            self.toast_msg('抓到鱼了 · 食材 +2', (150, 220, 200), 2.4)
            self.walk_home(s)

    def start_nap(self, s):
        s.nap = 40 / GAME_MIN_PER_SEC
        s.social_state = 'nap'
        s.chat_line = ''
        s.chat_partner = None
        s.walk_path = self.walk_route(s.at_key, (s.px, s.feet), 'DORM', DORM_SPOT)
        self.log(f'{s.m["name"]} 累到不行，回宿舍躺一会儿', (200, 190, 220))

    def update_nap(self, s, dt):
        if s.walk_path:
            self.step_walk(s, dt)
            return
        s.nap = max(0.0, s.nap - dt)
        if s.nap <= 0:
            s.fatigue = max(0.0, s.fatigue - 0.6)
            self.texts.append([s.px, s.feet - 40, '睡醒了', 12, (170, 210, 230), 1.4])
            self.walk_home(s)
            s.social_timer = random.uniform(10, 25)

    def start_outing(self, s):
        """出门：优先去找某个人，没人可找就去公共区域。"""
        mate = self.pick_partner(s)
        if mate is not None and random.random() < 0.75:
            route = self.walk_route(s.at_key, (s.px, s.feet), mate.at_key,
                                    (mate.px, mate.feet))
            # 路线得真的够得着那个人（老的门/走道逻辑跨层是走不通的）
            reach = (route and len(route) > 1
                     and math.hypot(route[-1][0] - mate.px,
                                    route[-1][1] - mate.feet) < 44)
            if reach:
                s.social_target = mate.m['id']
                s.social_dest = mate.m['name'] + ' 那里'
                s.social_dest_key = mate.at_key
                s.chat_x, s.chat_y = mate.px, mate.feet
                s.walk_path = route[1:]
                s.walk_idle = 0.0
                s.walk_retry = 0
                s.repath_t = 0.5
                s.social_state = 'walk'
                return
        key, pt, name = self.pick_spot(s)
        route = self.walk_route(s.at_key, (s.px, s.feet), key, pt)
        if not route or len(route) < 2:
            s.social_timer = random.uniform(10.0, 20.0)
            return
        s.social_target = None
        s.social_dest = name
        s.social_dest_key = key
        s.chat_x, s.chat_y = pt
        s.walk_path = route[1:]
        s.walk_idle = 0.0
        s.walk_retry = 0
        s.social_state = 'walk'

    def walk_home(self, s):
        s.social_state = 'back'
        s.social_target = None
        s.chat_partner = None
        s.chat_line = ''
        s.walk_path = self.walk_route(s.at_key, (s.px, s.feet), s.m['id'],
                                      (float(s.cx), float(s.home_feet)))
        s.walk_idle = 0.0
        if not s.walk_path:                 # 实在没路可走（被放在死角）：归位
            s.px, s.feet = float(s.cx), float(s.home_feet)
            s.at_key = s.m['id']
            s.social_state = 'home'

    def begin_chat(self, a, b):
        """两个人停下来聊天：两句对话都显示，位置自动错开。"""
        if a is b or a.social_state == 'chat' and b.social_state == 'chat':
            return
        if a.jobs() or b.jobs():
            return
        dur = random.uniform(4.0, 7.0)
        key = tuple(sorted((a.m['id'], b.m['id'])))
        if set(key) != BOND_FROZEN:             # 只有 GPT↔Grok 这一对不涨
            self.bonds[key] = min(1.0, self.bonds.get(key, 0.0) + BOND_GAIN)
        for x, y, line in ((a, b, random.choice(CHAT_LINES)),
                           (b, a, random.choice(CHAT_REPLIES))):
            x.social_state = 'chat'
            x.chat_partner = y.m['id']
            x.chat_line = line
            x.social_timer = dur
            x.walk_path = []
            x.social_target = None
            x.chat_x, x.chat_y = y.px, y.feet
            x.walk_idle = 0.0
        self.separate_from_others(a)
        self.separate_from_others(b)

    def update_chat(self, s, dt):
        mate = self.station_by_id(s.chat_partner) if s.chat_partner else None
        if mate is not None:
            if (mate.jobs() or mate.social_state != 'chat'
                    or not self.can_chat(s, mate, 96)):
                s.chat_partner = None
                s.chat_line = ''
                self.walk_home(s)
                return
        s.social_timer -= dt
        if s.social_timer <= 0:
            s.chat_partner = None
            s.chat_line = ''
            self.walk_home(s)
            s.social_timer = random.uniform(25.0, 55.0)

    def update_walk(self, s, dt):
        """走路：如果是去找人，边追边重新规划；够近就开聊。"""
        if s.social_state == 'walk' and s.social_target:
            mate = self.station_by_id(s.social_target)
            if (mate is None or mate.jobs() or mate.resting
                    or mate.slack > 0 or mate.stuck > 0):
                self.walk_home(s)
                self.step_walk(s, dt)
                return
            if self.can_chat(s, mate, 46):
                self.begin_chat(s, mate)
                return
            s.repath_t -= dt
            if s.repath_t <= 0 or not s.walk_path:
                s.repath_t = 0.4
                route = self.walk_route(s.at_key, (s.px, s.feet),
                                        mate.at_key, (mate.px, mate.feet))
                if route and len(route) > 1:
                    s.walk_path = route[1:]
        self.step_walk(s, dt)
        self.life_watchdog(s, dt)

    def init_bonds(self, keep=False):
        """铺初始好感：默认随机 0~10%，几对有名有姓的单独设定。

        keep=True 时只补缺失的（读老存档用），不覆盖已经聊出来的关系。
        """
        def put(key, v):
            if keep and key in self.bonds:
                return
            self.bonds[key] = v

        st = self.stations
        WARM = {'DeepSeek', 'Claude'}          # 这俩待人亲和，起始关系高
        COLD_PAIR = {'ChatGPT', 'Grok'}        # 只有这俩互相看不顺眼
        for i in range(len(st)):
            for j in range(i + 1, len(st)):
                a, b = st[i], st[j]
                ids = {a.m['id'], b.m['id']}
                if ids == COLD_PAIR:
                    v = -0.50
                elif ids & WARM:
                    v = round(random.uniform(0.28, 0.40), 3)
                else:
                    v = round(random.uniform(0.0, 0.10), 3)
                put(tuple(sorted((a.m['id'], b.m['id']))), v)
        for pair, v in INIT_BONDS.items():
            put(tuple(sorted(pair)), float(v))

    def bond(self, a, b):
        return self.bonds.get(tuple(sorted((a.m['id'], b.m['id']))), 0.0)

    def set_bond(self, a, b, v):
        """写关系（键统一排序，避免 a,b / b,a 存成两份）。"""
        self.bonds[tuple(sorted((a.m['id'], b.m['id'])))] = max(-1.0, min(1.0, float(v)))

    def bond_pairs(self, least=0.5, dist=180.0):
        """关系够好的两个人（而且都在场、离得不太远），用来画心形连线。"""
        out = []
        st = [x for x in self.stations if x.unlocked and x.on_grid()]
        for i in range(len(st)):
            for j in range(i + 1, len(st)):
                a, b = st[i], st[j]
                v = self.bond(a, b)
                if v < least:
                    continue
                if math.hypot(a.px - b.px, a.feet - b.feet) > dist:
                    continue
                if self.walkmask is not None and not self.walkmask.clear_line(
                        (a.px, a.feet), (b.px, b.feet)):
                    continue          # 隔墙不画关系线
                out.append((a, b, v))
        return out

    def top_bonds(self, s, n=2):
        """这个人关系最好的几个同事：[(名字, 0~1)]。"""
        rows = []
        for o in self.stations:
            if o is s:
                continue
            v = self.bond(s, o)
            if v >= 0.2:
                rows.append((o.m['name'], v))
        rows.sort(key=lambda r: -r[1])
        return rows[:n]

    def update_bonds(self):
        """两个关系好的人同时在干活，会互相搭把手（最多 +6%）。"""
        for s in self.stations:
            if not (s.unlocked and s.subscribed and s.jobs()):
                s.bond_boost = 0.0
                continue
            n = sum(1 for o in self.stations
                    if o is not s and o.jobs() and self.bond(s, o) >= 0.5)
            s.bond_boost = min(0.06, 0.03 * n)

    def update_encounters(self, dt):
        """两个人在走廊/房间里迎面遇上，也会停下来聊两句。"""
        for k in list(self.encounter_cd):
            self.encounter_cd[k] -= dt
            if self.encounter_cd[k] <= 0:
                del self.encounter_cd[k]
        walkers = [x for x in self.stations
                   if x.social_state == 'walk' and x.unlocked and x.subscribed
                   and not x.jobs() and x.slack <= 0 and x.stuck <= 0]
        for i in range(len(walkers)):
            for j in range(i + 1, len(walkers)):
                a, b = walkers[i], walkers[j]
                key = tuple(sorted((a.m['id'], b.m['id'])))
                if key in self.encounter_cd:
                    continue
                if self.can_chat(a, b, 34):
                    self.encounter_cd[key] = 45.0
                    self.begin_chat(a, b)

    def life_watchdog(self, s, dt):
        """走了两秒还没挪动：重新判定一次，实在走不通就放弃这趟。"""
        if s.social_state not in ('walk', 'back') or s.walk_idle < 2.0:
            return
        s.walk_idle = 0.0
        if s.social_state == 'back':
            dest_key, dest_pt = s.m['id'], (float(s.cx), float(s.home_feet))
        else:
            mate = self.station_by_id(s.social_target) if s.social_target else None
            if mate is not None:
                dest_key, dest_pt = mate.at_key, (mate.px, mate.feet)
            else:
                dest_key, dest_pt = s.social_dest_key, (s.chat_x, s.chat_y)
        retry = getattr(s, 'walk_retry', 0)
        if retry < 2:
            newp = self.walk_route(s.at_key, (s.px, s.feet), dest_key, dest_pt)
            if newp and len(newp) > 1:
                s.walk_path = newp[1:]
                s.walk_retry = retry + 1
                return
        s.walk_retry = 0
        s.walk_path = []
        s.social_state = 'home'
        s.at_key = s.m['id']
        s.social_target = None
        s.chat_partner = None
        s.chat_line = ''
        s.social_timer = random.uniform(20.0, 45.0)

    def update_social(self, s, dt):
        """闲下来的人会出门找人聊天；手上有活就先回工位。"""
        if not s.on_grid():
            return
        if s.cooking > 0 or s.social_state == 'cook':
            # 做饭算一件"不能被派单打断"的任务：先走完这段
            self.update_cooking(s, dt)
            return
        if s.fish > 0 or s.social_state == 'fish':
            self.update_fishing(s, dt)
            return
        if s.nap > 0 or s.social_state == 'nap':
            self.update_nap(s, dt)
            return
        if s.quest or s.social_state == 'quest':
            self.update_quest_worker(s, dt)
            return
        # 累到快满：回宿舍睡一觉
        if (s.fatigue >= 0.72 and not s.jobs() and s.social_state in ('home', 'roam')
                and s.nap <= 0 and self.scene == 'station'):
            self.start_nap(s)
            self.update_nap(s, dt)
            return
        if not (s.unlocked and s.subscribed):
            if s.social_state in ('walk', 'back', 'chat'):
                if s.social_state != 'back' or not s.walk_path:
                    self.walk_home(s)
                self.step_walk(s, dt)
                self.life_watchdog(s, dt)
            return
        if s.resting:
            return
        if s.jobs():
            if s.social_state != 'home':
                if s.social_state != 'back' or not s.walk_path:
                    self.walk_home(s)
                self.step_walk(s, dt)
                self.life_watchdog(s, dt)
            return
        if s.slack > 0 or s.stuck > 0 or s.limited or s.paused_job:
            return
        if s.social_state == 'chat':
            self.update_chat(s, dt)
            return
        if s.social_state in ('walk', 'back'):
            self.update_walk(s, dt)
            return
        if s.social_state == 'roam':
            self.update_roam(s, dt)
            return
        # 闲着：过一会儿出门
        s.social_timer -= dt
        if s.social_timer <= 0:
            out = sum(1 for x in self.stations
                      if x.social_state in ('walk', 'chat'))
            if out >= 2:
                s.social_timer = random.uniform(8.0, 18.0)
                return
            if random.random() < 0.40:
                self.start_roam(s)     # 随便逛逛：温室、食堂、宿舍、门外
            else:
                self.start_outing(s)

    ROAM_KEYS = ('BALCONY', 'GREEN', 'KITCHEN', 'DORM', 'CORRIDOR_A')

    def start_roam(self, s):
        """闲着到处走走：别都堆在大厅。"""
        keys = [k for k in self.ROAM_KEYS if k in DOORS]
        if s.m['id'] == 'DeepSeek' and 'BALCONY' in DOORS:
            key = 'BALCONY'                 # DeepSeek 爱去门口抓鱼
        elif keys:
            key = random.choice(keys)
        else:
            key = 'BALCONY'
        pt = DOORS.get(key, (s.px, s.feet))
        s.social_state = 'roam'
        s.roam_t = random.uniform(4.0, 9.0)
        s.walk_path = self.walk_route(s.at_key, (s.px, s.feet), key, pt)

    def update_roam(self, s, dt):
        if s.walk_path:
            self.step_walk(s, dt)
            self.life_watchdog(s, dt)
            return
        s.roam_t = getattr(s, 'roam_t', 0.0) - dt
        if s.roam_t <= 0:
            self.walk_home(s)
            s.social_state = 'home'
            s.social_timer = random.uniform(10.0, 26.0)

    def burn_quota(self, s, g, dp):
        """干活的同时按进度扣额度：这是"工作时达到限额"的来源。
        dp = 这一帧推进了多少进度（0~1），限流时它更小，额度也扣得更慢。"""
        if s.quota < 0 or g.qcost <= 0:
            return
        d = g.qcost * dp
        s.quota -= d
        g.qspent += d
        if s.quota <= 0:
            s.quota = 0.0
            self.quota_break(s, g)

    def quota_break(self, s, t=None):
        """干到一半额度见底：这单直接作废，声誉掉。"""
        t = t if t is not None else s.busy
        if t is None:
            return
        if s.busy is t:
            s.busy = None
        elif s.busy2 is t:
            s.busy2 = None
        s.prog = 0.0
        t.qcost = 0.0
        t.qspent = 0.0
        s.quota = 0.0
        if t is not None:
            t.state = 'out'
            t.fade = 0
        self.t_quota_break += 1
        self.rep = max(0.0, self.rep - REP_QUOTA)
        self.event = dict(kind='quota', name=f'{s.m["name"]} 额度见底',
                          left=8.0, desc=f'活干到一半断了，声誉 -{REP_QUOTA}')
        self.log(f'{s.m["name"]} 干活到一半额度见底，这单作废，声誉 -{REP_QUOTA}', C_RED)
        self.toast_msg(f'{s.m["name"]} 额度见底，活断了', C_RED, 2.8)
        self.arrange_queue()

    def throttle(self, s):
        """连续满负荷 --> 上游限流：干活速度掉 80%，要等手上这单干完才解除。"""
        s.limited = True
        s.strain = 1.0              # 顶着上限冻住，解除后才开始回落
        s.strain_warned = True
        self.t_throttles += 1
        self.event = dict(kind='throttle', name=f'{s.m["name"]} 被限流',
                          left=12.0, desc=f'速度 -{int(THROTTLE_SLOW * 100)}%，干完这单才解除')
        self.log(f'{s.m["name"]} 被上游限流：速度 -{int(THROTTLE_SLOW * 100)}%，'
                 f'干完手头这单才恢复', C_RED)
        self.toast_msg(f'{s.m["name"]} 被限流，速度掉到 {THROTTLE_PCT}%',
                       C_RED, 2.6)

    def pause_job(self, s):
        """暂停 / 继续手上这单。"""
        if not s.jobs():
            self.toast_msg('手上没有在跑的活', C_DIM)
            return
        s.paused_job = not s.paused_job
        if s.paused_job:
            self.log(f'{s.m["name"]} 这单先按下暂停，进度冻住', (200, 200, 150))
            self.toast_msg(f'{s.m["name"]} 暂停中', (236, 220, 150), 2.0)
        else:
            self.log(f'{s.m["name"]} 继续干', C_GREEN)
            self.toast_msg(f'{s.m["name"]} 继续', C_GREEN, 1.8)

    def abandon_job(self, s):
        """放弃手上这单：作废、钱收不到、声誉掉一点。"""
        if not s.jobs():
            self.toast_msg('手上没有在跑的活', C_DIM)
            return
        t = s.busy if s.busy is not None else s.busy2
        self.abort_job(s, t)
        s.paused_job = False
        self.t_abandon += 1
        self.rep = max(0.0, self.rep - REP_ABANDON)
        self.event = dict(kind='quota', name=f'{s.m["name"]} 放弃了一单',
                          left=8.0, desc=f'声誉 -{REP_ABANDON}')
        self.log(f'{s.m["name"]} 放弃手上的单子，声誉 -{REP_ABANDON}', C_RED)
        self.toast_msg(f'{s.m["name"]} 这单放弃了', C_RED, 2.4)
        self.arrange_queue()

    def start_slack(self, s):
        """摸鱼开始：跑去厨房煮一锅大白饭，玩家得点它一下。"""
        s.slack = SLACK_SEC
        s.walking = False
        self.log(f'{s.m["name"]} 溜去煮大白饭了，点它拦下', (232, 190, 120))
        self.toast_msg(f'{s.m["name"]} 在煮大白饭，快点它', (232, 190, 120), 2.8)

    def stop_slack(self, s):
        """玩家点中正在摸鱼的角色：拦下来，饭没煮成。"""
        s.slack = 0.0
        s.slack_cd = SLACK_GAP
        self.texts.append([s.cx + 6, s.feet - 46, '抓到了！', 12, (150, 230, 190), 1.2])
        self.log(f'{s.m["name"]} 被抓回工位，饭没煮成', C_GREEN)
        self.toast_msg(f'拦住了 {s.m["name"]} 的摸鱼', C_GREEN, 1.8)
        for _ in range(6):
            self.particles.append(dict(
                x=s.px + random.uniform(-8, 8), y=s.feet - 34,
                vx=random.uniform(-22, 22), vy=random.uniform(-40, -14),
                life=random.uniform(0.3, 0.6), color=(150, 230, 190)))

    def slack_done(self, s):
        """没拦住：一锅大白饭煮好了，额度被吃掉、声誉掉一点。"""
        s.slack_cd = SLACK_GAP
        cost = 0
        if s.quota > 0:
            cost = int(min(s.quota, SLACK_COST))
            s.quota = max(0.0, s.quota - cost)
        self.rep = max(0.0, self.rep - 1.0)
        self.log(f'{s.m["name"]} 把大白饭煮好了，额度 -{cost}，声誉 -1', C_RED)
        self.toast_msg('一锅大白饭煮好了，额度被吃掉', C_RED, 2.6)
        for _ in range(10):
            self.particles.append(dict(
                x=s.px + random.uniform(-10, 10), y=s.feet - 30,
                vx=random.uniform(-16, 16), vy=random.uniform(-46, -18),
                life=random.uniform(0.5, 1.0), color=(240, 236, 226)))

    def feed_snacks(self):
        """从冰箱里拿一份零食发给全员：一段时间内全都手快一些。"""
        if self.snacks <= 0:
            self.toast_msg('冰箱空了，明天再补或者花钱买', C_DIM)
            return
        self.snacks -= 1
        n = 0
        for st in self.stations:
            if st.unlocked and st.subscribed:
                st.snack = SNACK_SEC
                n += 1
        self.log(f'给 {n} 条线路发了零食，速度 +{int(SNACK_SPD * 100)}%',
                 (232, 190, 120))
        self.toast_msg(f'零食发下去了 · 全员 +{int(SNACK_SPD * 100)}%', (232, 190, 120))
        self.panel = None

    def buy_snacks(self):
        """花钱给冰箱补货。"""
        if self.money < SNACK_BUY:
            self.toast_msg('钱不够补货', C_RED)
            return
        self.money -= SNACK_BUY
        self.snacks += SNACK_BUY_N
        self.log(f'给冰箱补了 {SNACK_BUY_N} 份零食，花了 ¥{SNACK_BUY}', C_GOLD)
        self.toast_msg(f'冰箱补货 +{SNACK_BUY_N}', C_GOLD)

    def settle_point(self):
        """24:00 在当天时间轴上的位置（占比）。"""
        return DAY_LEN * ((24 - HOUR_START) / DAY_HOURS)

    def end_day(self):
        """24:00 结账：扣房租 / 电费 / 工资，刷新每日额度，天数 +1。

        手上的活不停、待处理的任务也不清空——只是额度换成新的。
        """
        rent, power, wage, subs, port = self.daily_fixed()
        fixed = rent + power + wage + subs + port
        net = self.t_rev - self.t_cost - fixed
        self.money += -fixed
        self.history.append(dict(day=self.day, rev=self.t_rev, net=net))
        self.last_net = net
        self.last_day = dict(day=self.day, rev=self.t_rev, cost=self.t_cost,
                             rent=rent, power=power, wage=wage, subs=subs, port=port,
                             net=net, orders=self.t_orders, expired=self.t_expired,
                             crashes=self.t_crashes, trips=self.t_trips)

        if rent:
            self.log(f'房东来收租：{RENT_EVERY} 天房租 ¥{rent}，已付', C_GOLD)
        if port:
            n_vpn = sum(1 for st in self.stations if 'vpn' in st.gear)
            n_enc = sum(1 for st in self.stations if 'vpn_enc' in st.gear)
            self.log(f'VPN 端口周费 ¥{port}（{n_vpn} 个普通 / {n_enc} 个加密），已付',
                     C_GOLD)
        self.log(f'第 {self.day} 天结算 ¥{net:+.0f}，额度已刷新', C_BLUE)
        self.toast_msg(f'第 {self.day} 天结算 {net:+.0f}', C_GOLD if net >= 0 else C_RED, 3.2)

        if self.weather_ev and self.day > self.weather_ev[1]:
            name = self.EVENTS[self.weather_ev[0]][0]
            self.weather_ev = None
            for st in self.stations:
                st.limited = False
            self.log(f'{name}过去了，一切恢复正常', (150, 210, 170))
        self.social_event()
        if self.loan > 0:
            interest = self.loan * self.LOAN_RATE
            self.loan += interest
            self.money -= interest
            self.log(f'银行利息 {interest:,.0f}（欠 ¥{self.loan:,.0f}）', (210, 170, 140))
        self.burn_fuel()
        self.quest_day_end()
        if self.scene == 'station' and self.meals_today >= 3:
            self.log('三餐都吃了，状态不错', (150, 210, 170))
        self.check_contract_end()
        self.day += 1
        if self.scene == 'station':
            self.south_days += 1
            self.roll_event()
        self.build_daily_goals()
        if self.day % SUPPLY_EVERY == 0:
            self.deliver_supply()      # 补给：每 7 天来一次（装备也随车到）
        self.t_rev = 0.0
        self.t_cost = 0.0
        self.t_orders = 0
        self.t_expired = 0
        self.t_trips = 0
        self.t_crashes = 0
        self.t_throttles = 0
        self.t_quota_break = 0
        self.t_abandon = 0
        self.t_reject = 0
        self.t_reset_cards = 0
        self.ad_days = max(0, self.ad_days - 1)   # 零食不再每天刷新，用完得自己补货
        self.burst = 0.0
        self.event = None
        for st in self.stations:
            # 24:00 只换额度：温度、限流压力、各种 buff 计时都不重置
            st.refresh_daily()
            if st.resting:
                st.resting = False
                st.fatigue = 0.0
                st.rest_bonus = 0.0
            elif not st.no_fatigue:
                st.rest_bonus = max(0.0, st.rest_bonus * 0.4)
            # 订阅是 7 天预付的：每天减一天，到期就停工（豆包这种永久免费的不算）
            if st.subscribed and not st.forever:
                st.sub_days -= 1
                if st.sub_days <= 0:
                    st.sub_days = 0
                    st.subscribed = False
                    st.quota = 0
                    self.log(f'{st.m["name"]} 的订阅到期了，这台机器停工了', (226, 160, 130))
        self.rest_day = False
        self.save()

        if self.money < -400:
            self.state = 'over'
            self.panel = ('over', dict(bankrupt=True, day=self.day, money=self.money))
        elif self.day > TOTAL_DAYS:
            self.state = 'over'
            self.panel = ('over', dict(bankrupt=False, day=TOTAL_DAYS,
                                       money=self.money))
        elif self.rent_left() == 1 and RENT_NOTICE_ON and getattr(self, 'rent_notice_on', True):
            # 明天打烊就要交房租：弹个窗提醒，别把钱全砸进解锁/订阅
            self.panel = ('notice', dict(day=self.day, rent=RENT_WEEK,
                                         money=self.money))
            self.log(f'提醒：明天（第 {self.day + 1} 天）要交房租 ¥{RENT_WEEK}', C_GOLD)

        # 没有结算弹窗时：先看能不能搬去南极，再看长期合同
        if self.state == 'play' and not self.panel and self.can_relocate():
            self.panel = ('relocate', dict(cost=RELOCATE_COST))
        if self.state == 'play' and not self.panel:
            self.maybe_offer_contract()

    def supply_panel_rect(self):
        return pygame.Rect(20, 60, 640, 600)

    def supply_items(self):
        return [
            ('food', '食材 ×10', 120, '千问做饭用'),
            ('fuel', '燃料 ×30', 150, '供暖 / 发电'),
            ('snack', '零食 ×5', 90, '冰箱没了，直接记到零食库存'),
        ]

    def supply_gear_rects(self):
        r = self.supply_panel_rect()
        out = []
        for i, g in enumerate(GEAR):
            out.append((g, pygame.Rect(r.right - 150, r.y + 292 + i * 38, 120, 28)))
        return out

    def supply_buttons(self):
        r = self.supply_panel_rect()
        out = []
        for i, (kind, name, price, note) in enumerate(self.supply_items()):
            out.append((kind, name, price, note,
                        pygame.Rect(r.right - 150, r.y + 100 + i * 50, 120, 32)))
        out.append(('close', '', 0, '', pygame.Rect(r.centerx - 80, r.bottom - 56, 160, 40)))
        return out

    def next_supply_day(self):
        """下一次补给车靠岸的日子（3 天一趟）。"""
        return max(1, ((self.day - 1) // SUPPLY_EVERY + 1) * SUPPLY_EVERY)

    def buy_supply(self, kind):
        item = next((x for x in self.supply_items() if x[0] == kind), None)
        if not item:
            return
        _, name, price, _ = item
        if self.money < price:
            self.toast_msg('钱不够下这单', C_RED)
            return
        self.money -= price
        self.pending_supply.append(kind)
        self.log(f'下单：{name}（¥{price}），补给船第 {self.next_supply_day()} 天送到', C_GOLD)
        self.toast_msg(f'{name} 已下单 · 等补给船', C_GOLD, 2.2)

    def deliver_supply(self):
        """雪地补给车靠岸：把订单搬进仓库。"""
        if not self.pending_supply and not self.pending_gear:
            return
        got = self.pending_supply[:]
        self.pending_supply = []
        for kind in got:
            if kind == 'food':
                self.warehouse['food'] += 10
            elif kind == 'fuel':
                self.fuel += 30
            elif kind == 'snack':
                self.snacks += 5
        n_gear = len(self.pending_gear)
        for gid in self.pending_gear:
            self.bag_add(gid)
        self.pending_gear = []
        self.log(f'雪地补给车靠岸：{len(got)} 箱物资、{n_gear} 件装备入库', C_GOLD)
        self.toast_msg('补给车到了 · 物资和装备已入库', C_GOLD, 3.0)

    def draw_supply_panel(self, data=None):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 185))
        r = self.supply_panel_rect()
        alpha_rect(s, r, (18, 24, 34, 248), 10)
        pygame.draw.rect(s, (120, 190, 210), r, 2, border_radius=10)
        txt(s, '主控屏 · 物资补给', r.centerx, r.y + 20, 22, (176, 232, 240),
            'midtop', bold=True)
        txt(s, f'下单后等补给船：下一次靠岸是第 {self.next_supply_day()} 天'
               + (f'（还有 {self.next_supply_day() - self.day} 天）' if self.next_supply_day() > self.day else '（今天）'),
            r.centerx, r.y + 52, 12, (150, 162, 186), 'midtop')
        txt(s, f'仓库：食材 {self.warehouse["food"]} · 燃料 {int(self.fuel)} · 零食 {self.snacks}',
            r.centerx, r.y + 70, 11, (130, 190, 170), 'midtop')
        txt(s, '装备（下单后随下一批补给到）', r.x + 34, r.y + 258, 16,
            (220, 200, 160), bold=True)
        for g, gb in self.supply_gear_rects():
            can = self.money >= g['price']
            hov = gb.collidepoint(self.mouse)
            alpha_rect(s, gb, (46, 44, 30) if hov and can else (26, 26, 24), 5)
            pygame.draw.rect(s, (236, 210, 150) if can else (80, 76, 66), gb, 1,
                             border_radius=5)
            n = self.pending_gear.count(g['id'])
            txt(s, f'下单 ×{n}' if n else '下单', gb.centerx, gb.centery, 12,
                (250, 230, 180) if can else (130, 126, 116), 'center', bold=True)
            txt(s, g['name'], r.x + 34, gb.y + 1, 13, C_TEXT, bold=True)
            txt(s, f"¥{g['price']} · {g['desc']}", r.x + 34, gb.y + 16, 10,
                (136, 144, 166))
        for kind, name, price, note, b in self.supply_buttons():
            if kind == 'close':
                hov = b.collidepoint(self.mouse)
                alpha_rect(s, b, (40, 44, 54) if hov else (28, 30, 38), 6)
                pygame.draw.rect(s, (110, 118, 134), b, 1, border_radius=6)
                txt(s, '关闭', b.centerx, b.centery, 14, (190, 196, 210), 'center')
                continue
            can = self.money >= price
            hov = b.collidepoint(self.mouse)
            alpha_rect(s, b, (46, 38, 24) if hov and can else (28, 26, 20), 6)
            pygame.draw.rect(s, (236, 206, 130) if can else (86, 80, 66), b, 1,
                             border_radius=6)
            txt(s, f'¥{price}', b.centerx, b.centery, 13,
                (250, 224, 170) if can else (140, 134, 120), 'center', bold=True)
            txt(s, name, r.x + 34, b.y + 3, 15, C_TEXT, bold=True)
            txt(s, note, r.x + 34, b.y + 22, 10, (130, 138, 160))
            pend = self.pending_supply.count(kind)
            if pend:
                txt(s, f'已下单 ×{pend}', b.x - 90, b.y + 10, 10, (150, 220, 190))

    def station_live(self):
        return [st for st in self.stations
                if st.unlocked and st.subscribed and self.scene_ok(st)]

    def fuel_burn(self):
        """今天要烧多少燃料：开工的线路越多越费；有人值班能省一截；极夜翻倍。"""
        live = len(self.station_live())
        duty = sum(1 for st in self.stations if getattr(st, 'duty', False))
        burn = max(2.0, 5.0 + 1.6 * live - 3.0 * min(2, duty))
        if getattr(self, 'polar', False):
            burn *= POLAR_FUEL
        if self.event_kind() == 'blizzard':
            burn *= 1.25
        return burn

    def burn_fuel(self):
        if self.scene != 'station':
            return
        burn = self.fuel_burn()
        if self.fuel >= burn:
            self.fuel -= burn
        else:
            self.fuel = 0.0
        was = self.cold
        self.cold = self.fuel <= 0.0
        if self.cold and not was:
            self.log('燃料烧完了：站里开始变冷，全部线路效率 -40%', C_RED)
            self.toast_msg('燃料耗尽 · 站里变冷了（去发电舱买燃料）', C_RED, 3.2)

    def buy_fuel(self, units=20, price=80):
        if self.money < price:
            self.toast_msg(f'钱不够（燃料 {units} 单位 ¥{price}）', C_RED)
            return False
        self.money -= price
        self.fuel += units
        self.cold = False
        self.log(f'补给：买了 {units} 单位燃料（¥{price}）', C_GOLD)
        self.toast_msg(f'燃料 +{units}（现在 {int(self.fuel)}）', C_GOLD, 2.2)
        return True

    def check_contract_end(self):
        """每天打烊考核长期合同：没交够就作废。"""
        c = self.contract
        if not c:
            return
        if c['today'] < c['need']:
            self.rep = max(0.0, self.rep - 3.0)
            self.log(f'长期合同违约：{TYPES[c["typ"]]["name"]} 今天只交了 '
                     f'{c["today"]}/{c["need"]} 单，合同作废，声誉 -3', C_RED)
            self.toast_msg('长期合同没完成，作废了', C_RED, 3.0)
            self.contract = None
            return
        c['left'] -= 1
        c['today'] = 0
        if c['left'] <= 0:
            self.money += c['reward']
            self.log(f'长期合同完成！奖金 ¥{c["reward"]}', C_GOLD)
            self.toast_msg(f'长期合同完成 · 奖金 ¥{c["reward"]}', C_GOLD, 3.2)
            self.contract = None

    def maybe_offer_contract(self):
        """科考站专属：交付够多、声誉够高，会有人来谈南极科考合同。"""
        if self.scene != 'station':
            return
        if self.contract or self.contract_offer or self.day <= 3:
            return
        if self.rep < 60 or not self.delivered:
            return
        typ, cnt = max(self.delivered.items(), key=lambda kv: kv[1])
        if cnt < 6:
            return
        self.contract_offer = dict(typ=typ, days=5, need=2, reward=600, count=cnt)
        self.panel = ('contract', self.contract_offer)

    def accept_contract(self):
        o = self.contract_offer
        if not o:
            return
        self.contract = dict(typ=o['typ'], left=o['days'], need=o['need'],
                             today=0, reward=o['reward'])
        self.contract_offer = None
        self.panel = None
        name = TYPES[o['typ']]['name']
        self.log(f'签下长期合同：每天交 {o["need"]} 单{name}，共 {o["days"]} 天，'
                 f'单价 +15%，完成奖 ¥{o["reward"]}', C_GOLD)
        self.toast_msg(f'签了{name}长期合同 · 每天 {o["need"]} 单', C_GOLD, 3.0)

    def drop_contract_offer(self):
        self.contract_offer = None
        self.panel = None

    def next_day(self):
        """手动跨天（调试 / 测试用）。正常流程由 update 在 24:00 触发。"""
        self.t = 0.0
        self.settled = False
        self.panel = None

    # ------------------------------------------------ 相机 / 坐标
    def view_box(self):
        """当前视野在世界坐标里的矩形 (x, y, w, h)，并把镜头夹在画面内。"""
        if self.zoom <= 1.001:
            return (0.0, 0.0, float(WW), float(WH))
        vw, vh = WW / self.zoom, WH / self.zoom
        cx = max(vw / 2, min(WW - vw / 2, self.cam[0]))
        cy = max(vh / 2, min(WH - vh / 2, self.cam[1]))
        self.cam[0], self.cam[1] = cx, cy
        return (cx - vw / 2, cy - vh / 2, vw, vh)

    def world_pos(self, pos):
        mx, my = pos
        if self.zoom <= 1.001:
            return (mx / SCALE, my / SCALE)
        vx, vy, vw, vh = self.view_box()
        return (vx + mx * vw / WW, vy + my * vh / WH)

    def zoom_wheel(self, dy):
        """滚轮缩放：以鼠标所在的世界点为锚点；dy 可带格数（快滚多走几档）。"""
        if not dy:
            return
        steps = max(-3, min(3, int(dy)))
        for _ in range(abs(steps)):
            i = min(range(len(ZOOM_STEPS)), key=lambda k: abs(ZOOM_STEPS[k] - self.zoom))
            i = max(0, min(len(ZOOM_STEPS) - 1, i + (1 if dy > 0 else -1)))
            new = ZOOM_STEPS[i]
            if abs(new - self.zoom) < 1e-6:
                break
            before = self.world_pos(self.mouse)
            self.zoom = new
            after = self.world_pos(self.mouse)
            self.cam[0] += before[0] - after[0]
            self.cam[1] += before[1] - after[1]

    def drag_cam(self, dx, dy):
        """右键拖动镜头。"""
        if self.zoom <= 1.001:
            return
        vx, vy, vw, vh = self.view_box()
        self.cam[0] -= dx * vw / WW
        self.cam[1] -= dy * vh / WH

    def handle_click(self, pos):
        mx, my = pos
        if self.panel:
            if self.panel[0] == 'bag':
                self.click_bag(pos)
                return
            self.click_panel(mx, my)
            return
        # 右侧信息栏按钮
        if self.rewards and self.reward_btn().collidepoint(mx, my):
            self.claim_rewards()
            return
        for key, r in self.pane_buttons():
            if r.collidepoint(mx, my):
                if key == 'price_up':
                    self.price_idx = min(len(PRICE_STEPS) - 1, self.price_idx + 1)
                elif key == 'price_down':
                    self.price_idx = max(0, self.price_idx - 1)
                elif key == 'speed':
                    self.speed = {1: 2, 2: 3, 3: 1}.get(self.speed, 1)
                elif key == 'pause':
                    self.paused = not self.paused
                elif key == 'ad':
                    self.buy_ad()
                elif key == 'intake':
                    self.toggle_intake()
                elif key == 'bag':
                    self.panel = ('storage', None)   # 背包并进仓库了
                    self.held_item = None
                elif key == 'ach':
                    self.panel = ('achieve', None)
                elif key == 'guide':
                    self.panel = ('intro', 'station' if self.scene == 'station' else 'apt')
                elif key == 'settings':
                    self.paused = True          # 设置面板一开，整局暂停
                    self.panel = ('settings', 'game')
                return
        if self.state != 'play':
            return
        if self.held_item is not None:
            hit = self.station_at(pos)
            if hit is None:
                self.toast_msg('拿着道具 · 点一个 AI 装上（右键 / Esc 放下）',
                               (250, 224, 170), 2.4)
                return
            if self.apply_item(self.held_item, hit):
                self.held_item = None
                self.drag_item = None
            return
        wx, wy = self.world_pos(pos)
        # 工位（没解锁的线路：整间房都能点开面板）
        for s in self.stations:
            hit = s.rect() if s.unlocked else s.rect().inflate(70, 50)
            if hit.collidepoint(wx, wy):
                if self.held_item is not None:
                    if self.apply_item(self.held_item, s):
                        self.held_item = None
                    return
                if s.slack > 0:
                    self.stop_slack(s)      # 抓到摸鱼：按回工位
                    return
                if s.stuck > 0 and s.cooldown <= 0:
                    s.stuck = 0.0
                    s.cooldown = 2.0
                    self.toast_msg(f'{s.m["name"]} 重启中…', C_BLUE)
                    return
                self.panel = ('station', s)
                return
        # 门厅的网络网关
        if pygame.Rect(GATEWAY[0] - 24, GATEWAY[1] - 44, 48, 56).collidepoint(wx, wy):
            self.panel = ('gateway', None)
            return
        # 厨房的冰箱（零食）
        # 公寓右下角的装备店
        if GEAR_SHOP_RECT.inflate(16, 16).collidepoint(wx, wy):
            self.panel = ('gear', None)
            return
        # 楼梯间的电闸
        if pygame.Rect(BREAKER[0] - 18, BREAKER[1] - 36, 36, 46).collidepoint(wx, wy):
            self.panel = ('breaker', None)
            return
        # 科考站任务点
        if self.scene == 'station':
            if WEATHER_RECT.inflate(10, 10).collidepoint(wx, wy):
                self.click_weather()
                return
            if LAB_RECT.inflate(10, 10).collidepoint(wx, wy):
                self.click_lab()
                return
            if GREEN_RECT.inflate(10, 10).collidepoint(wx, wy):
                self.click_greenhouse()
                return
            if AIRLOCK_RECT.inflate(10, 10).collidepoint(wx, wy):
                self.click_ice()
                return
            if SUPPLY_CAR_RECT.inflate(8, 8).collidepoint(wx, wy):
                self.click_supply_car()
                return
            if WAREHOUSE_RECT.collidepoint(wx, wy):
                self.panel = ('storage', None)
                return
        # 主控室的大屏：下单买物资
        if self.scene == 'station' and SUPPLY_RECT.inflate(8, 8).collidepoint(wx, wy):
            self.panel = ('supply', None)
            return
        # 客厅的派单服务器
        if pygame.Rect(SERVER[0] - 26, SERVER[1] - 46, 52, 72).collidepoint(wx, wy):
            self.quest_sel = None
            self.panel = ('server', 0)      # 没单也能点开（看合同/状态）
            return
        # 屋外的早餐铺
        if self.scene != 'station' and SHOP_RECT.inflate(16, 16).collidepoint(wx, wy):
            self.panel = ('shop', None)
            return
        # 待处理的网上任务（点数据包）
        for t in self.tasks:
            if t.state not in ('in', 'queue'):
                continue
            box = pygame.Rect(t.x - 18, t.y - 24, 36, 44)
            if box.collidepoint(wx, wy):
                if not self.unlocked():
                    return
                idx = self.queued_tasks().index(t) if t in self.queued_tasks() else 0
                self.panel = ('server', idx)
                return

    def click_panel(self, mx, my):
        kind, data = self.panel
        if kind == 'achieve':
            self.panel = None
            return
        if kind == 'stage':
            self.panel = None
            if INTRO_ON and self.scene == 'station':
                self.show_comic([3], to_intro=True)
            return
        if kind == 'comic':
            self.comic_i += 1
            if self.comic_i < len(self.comic_list):
                self.panel = ('comic', self.comic_list[self.comic_i])
            else:
                self.panel = None
                if self.pending_intro:
                    self.panel = ('intro', self.scene if self.scene == 'station' else 'apt')
                self.pending_intro = False
                self.comic_list = []
                self.story_seen = True
            return
        if kind == 'intro':
            self.panel = None
            return
        if kind == 'storage':
            self.click_storage(mx, my)
            return
        if kind == 'server':
            if self.close_btn().collidepoint(mx, my):
                self.panel = None
                self.quest_sel = None
                return
            if self.auto_btn().collidepoint(mx, my):
                self.auto_dispatch = not self.auto_dispatch
                self.toast_msg('自动派单已开' if self.auto_dispatch else '自动派单已关',
                               C_GREEN if self.auto_dispatch else C_DIM, 2.0)
                return
            # 选任务 / 退回任务
            for i, (t, r) in enumerate(self.task_rows()):
                if t.state in ('in', 'stored') and self.task_del_btn(r).collidepoint(mx, my):
                    self.delete_task(t)
                    self.panel = ('server', 0)
                    return
                if r.collidepoint(mx, my):
                    self.quest_sel = None      # 选派单任务时，取消科考任务
                    self.panel = ('server', i)
                    return
            # 先点科考任务，再点人
            if self.scene == 'station':
                for key, name, ok, hint, b in self.quest_sel_rects():
                    if b.collidepoint(mx, my):
                        self.quest_sel = None if self.quest_sel == key else key
                        self.panel = ('server', -1)   # 不再指向某个派单任务
                        return
            # 派给某条线路 / 拉人进协作单
            q = self.server_tasks()
            sel = data if isinstance(data, int) else 0
            if not (0 <= sel < len(q)) and not self.quest_sel:
                for st, r in self.server_cards():
                    if r.collidepoint(mx, my):
                        self.panel = ('station', st)   # 没选单就看看这个人
                        return
                return
            for st, r in self.server_cards():
                if r.collidepoint(mx, my):
                    if self.quest_sel:
                        self.dispatch_quest(self.quest_sel, st)
                        return
                    if not st.ready():
                        self.toast_msg('这条线路现在接不了单', C_RED)
                    elif self.tripped > 0:
                        self.toast_msg('跳闸了，等电闸恢复', C_RED)
                    elif 0 <= sel < len(q):
                        self.assign(q[sel], st)
                    return
        elif kind == 'station':
            st = data
            if self.close_btn(self.station_panel_rect()).collidepoint(mx, my):
                self.panel = None
                return
            if st.busy and self.station_job_btn().collidepoint(mx, my):
                self.pause_job(st)
                return
            if st.busy and self.station_abandon_btn().collidepoint(mx, my):
                self.abandon_job(st)
                return
            if (self.scene == 'station' and st.unlocked
                    and self.station_duty_btn().collidepoint(mx, my)):
                st.duty = not st.duty
                self.toast_msg(f'{st.m["name"]} {"开始值班" if st.duty else "回到派单队列"}',
                               (150, 220, 190), 1.8)
                return
            if self.station_relations_btn().collidepoint(mx, my):
                self.open_relations(('station', st))
                return
            for gid, sr in self.station_gear_slots(st):
                if sr.collidepoint(mx, my) and gid:
                    self.unequip_gear(st, gid)
                    return

            if not st.unlocked:
                if self.station_up_btn().collidepoint(mx, my):
                    self.unlock_station(st)
                return
            if st.subscribed and self.station_reset_btn().collidepoint(mx, my):
                item = RESET_PREFIX + st.m['id']
                if self.bag_count(item):
                    self.use_reset_card(st)
                else:
                    self.toast_msg(f'背包里没有它的重置卡 · 去装备店买（¥{reset_price(st.m)}）',
                                   (236, 200, 140), 2.6)
                    self.panel = ('gear', None)
                return
            if st.has_tiers():
                for kind, tier, btn in self.station_tier_btns(st):
                    if btn.collidepoint(mx, my):
                        if kind == 'big':
                            self.upgrade_big(st)
                        else:
                            self.pick_tier(st, tier)
                        return
        elif kind == 'gear':
            if self.close_btn(self.store_panel_rect()).collidepoint(mx, my):
                self.panel = None
                return
            if self.store_food_btn().collidepoint(mx, my):
                self.buy_food()
                return
            for g, btn in self.store_gear_btns():
                if btn.collidepoint(mx, my):
                    self.buy_gear(g)
                    return
            for m, row, btn in self.store_reset_rows():
                if btn.collidepoint(mx, my):
                    self.buy_reset_card(next(x for x in self.stations
                                             if x.m['id'] == m['id']))
                    return
        elif kind == 'gateway':
            if self.close_btn(self.gateway_panel_rect()).collidepoint(mx, my):
                self.panel = None
                return
            if self.gateway_intake_btn().collidepoint(mx, my):
                self.toggle_intake()
                return
            if self.gateway_rest_btn().collidepoint(mx, my):
                self.take_rest_day()
                return
            if self.gateway_up_btn().collidepoint(mx, my):
                c = self.gw_up_cost()
                if self.gw_lv >= 5:
                    self.toast_msg('网关已经是最高规格', C_DIM)
                elif self.money >= c:
                    self.money -= c
                    self.gw_lv += 1
                    self.log(f'网关升到 Lv{self.gw_lv}：单子更大、来单更快', C_GREEN)
                    self.toast_msg(f'网关 Lv{self.gw_lv}', C_GOLD)
                else:
                    self.toast_msg('钱不够换网关', C_RED)
            return
        elif kind == 'fridge':
            if self.close_btn(self.fridge_panel_rect()).collidepoint(mx, my):
                self.panel = None
                return
            if self.fridge_feed_btn().collidepoint(mx, my):
                self.feed_snacks()
            elif self.fridge_buy_btn().collidepoint(mx, my):
                self.buy_snacks()
            return
        elif kind == 'breaker':
            if self.close_btn(self.breaker_panel_rect()).collidepoint(mx, my):
                self.panel = None
                return
            if self.breaker_up_btn().collidepoint(mx, my):
                c = self.breaker_up_cost()
                if self.breaker_lv >= 5:
                    self.toast_msg('电闸已经是最大容量', C_DIM)
                elif self.money >= c:
                    self.money -= c
                    self.breaker_lv += 1
                    self.log(f'电闸升到 Lv{self.breaker_lv}，能同时带 {self.breaker_cap()} 路', C_GREEN)
                    self.toast_msg(f'电闸 Lv{self.breaker_lv}', C_GOLD)
                else:
                    self.toast_msg('钱不够换电闸', C_RED)
            return
        elif kind == 'shop':
            if self.close_btn(self.shop_panel_rect()).collidepoint(mx, my):
                self.panel = None
                return
            if self.shop_buy_btn().collidepoint(mx, my):
                self.buy_breakfast()
            return
        elif kind == 'relations':
            if self.close_btn(self.relations_panel_rect()).collidepoint(mx, my):
                self.close_relations()
                return
            for key, b in self.relations_buttons():
                if b.collidepoint(mx, my):
                    self.close_relations()
                    return
            if not self.relations_panel_rect().collidepoint(mx, my):
                self.close_relations()
            return
        elif kind == 'supply':
            for g, gb in self.supply_gear_rects():
                if gb.collidepoint(mx, my):
                    self.buy_gear(g)
                    return
            for k, name, price, note, b in self.supply_buttons():
                if b.collidepoint(mx, my):
                    if k == 'close':
                        self.panel = None
                    else:
                        self.buy_supply(k)
                    return
            if not self.supply_panel_rect().collidepoint(mx, my):
                self.panel = None
            return
        elif kind == 'relocate':
            for key, b in self.relocate_buttons():
                if b.collidepoint(mx, my):
                    if key == 'go':
                        self.relocate()
                    else:
                        self.relocate_snooze = self.day + 5
                        self.panel = None
                    return
        elif kind == 'contract':
            for key, b in self.contract_buttons():
                if b.collidepoint(mx, my):
                    if key == 'accept':
                        self.accept_contract()
                    else:
                        self.drop_contract_offer()
                    return
        elif kind == 'settings':
            self.click_settings(mx, my, data)
        elif kind == 'notice':
            b = self.notice_ok_btn()
            if b.collidepoint(mx, my):
                self.panel = None
        elif kind == 'summary':
            self.next_day()
        elif kind == 'over':
            self.go_title()
            self.has_save = any(os.path.exists(save_path(i)) for i in range(1, SLOT_COUNT + 1))

    # ------------------------------------------------ 面板布局
    def server_panel_rect(self):
        # 右边留出 320px 任务栏，面板最多到 940
        w, h = 900, 566
        return pygame.Rect(20, (SH - h) // 2, w, h)

    def station_panel_rect(self):
        return pygame.Rect(150, SH // 2 - 320, 760, 640)

    def station_gear_slots(self, st):
        """左侧装备栏的三格：[(gid 或 None, rect), ...]。"""
        r = self.station_panel_rect()
        owned = sorted(st.gear)
        out = []
        for i in range(MAX_GEAR):
            gid = owned[i] if i < len(owned) else None
            out.append((gid, pygame.Rect(r.x + 28 + i * 102, r.y + 334, 92, 102)))
        return out

    def close_btn(self, rect=None):
        r = rect or self.server_panel_rect()
        return pygame.Rect(r.right - 48, r.top + 14, 32, 32)

    def quest_ready(self, key):
        """冷却（同任务 8 小时）和每日次数是否还允许。"""
        last = self.quest_last.get(key)
        if last is not None and (self.hour_f() - last) % 24 < QUEST_COOLDOWN:
            return False
        if key == 'ice' and self.ice_runs >= 2:
            return False
        return True

    def auto_btn(self):
        r = self.server_panel_rect()
        return pygame.Rect(r.right - 190, r.y + 14, 164, 26)

    def auto_assign(self):
        """自动派单：按“专长匹配 → 质量高 → 额度够”挑最合适的人，不按列表顺序硬塞。"""
        for t in list(self.queued_tasks()):
            best, best_score = None, -1e9
            for st in self.visible_stations():
                if not st.ready() or st.blocked(t.typ) or st.needs_port():
                    continue
                need = self.quota_need(st, t.w)
                if st.quota >= 0 and st.quota < need * 1.15:
                    continue                      # 别把人干到断额度
                score = st.m['q'] * 100 + st.spd() * 3
                if t.typ in st.m['tags']:
                    score += 120                  # 专长优先
                if st.jobs():
                    score -= 80                   # 已经有一单在手的往后排
                if st.m['id'] == 'Doubao':
                    score -= 60                   # 免费线最后考虑
                if score > best_score:
                    best, best_score = st, score
            if best is not None:
                self.assign(t, best)
                if t.multi:
                    for _ in range(2):      # 大单尽量凑满 3 人
                        mate = next((x for x in self.visible_stations()
                                     if x not in (best,)
                                     and x.m['id'] not in t.crew
                                     and self.worker_available(x)
                                     and not x.blocked(t.typ) and not x.needs_port()),
                                    None)
                        if mate is None or not self.assign(t, mate):
                            break

    def quest_actions(self):
        """服务器里能派的三个科考任务：(key, 名字, 能不能派, 说明)。"""
        return [
            ('weather', '气象采集',
             any(x == 1 for x in self.weather) and self.quest_ready('weather'),
             '采数据 → 回主控台上传（每天 2 趟，间隔 8 小时）'),
            ('ice', '冰样任务', self.ice == 0 and self.quest_ready('ice'),
             '采冰样 → 化验 → 上传（每天 2 趟，做完一趟才能接下一趟）'),
            ('green', '温室照料',
             getattr(self, 'green_day', -1) != self.day and self.quest_ready('green'),
             '千问去温室收食材（每天 1 次）'),
        ]

    def quest_sel_rects(self):
        r = self.server_panel_rect()
        out = []
        for i, (key, name, ok, hint) in enumerate(self.quest_actions()):
            out.append((key, name, ok, hint,
                        pygame.Rect(r.x + 26 + i * 132, r.y + 300, 124, 26)))
        return out

    def busy_reason(self, st):
        """这条线现在为什么不能接活（给提示用）。"""
        if not st.unlocked:
            return '还没解锁'
        if not st.subscribed:
            return '未订阅'
        if st.resting:
            return '在休息'
        if st.duty:
            return '在值班'
        if st.cooking > 0:
            return '正在做饭'
        if st.fish > 0:
            return '出去抓鱼了'
        if st.nap > 0:
            return '在宿舍睡觉'
        if st.quest or st.social_state == 'quest':
            return '正在跑科考任务'
        if st.jobs():
            return '手上有活'
        if st.free_slot() is None:
            return '两个工位都占着'
        if not st.has_quota():
            return '今天额度用完了'
        if st.limited:
            return '被限流了'
        if st.stuck > 0:
            return '宕机了'
        return '现在没空'

    def worker_available(self, st):
        return (st.on_grid() and st.unlocked and st.subscribed
                and not st.jobs() and not st.resting and not st.duty
                and st.cooking <= 0 and st.fish <= 0 and st.nap <= 0
                and not st.quest
                and st.social_state not in ('quest', 'cook', 'fish', 'nap')
                and st.slack <= 0 and st.stuck <= 0)

    def dispatch_quest(self, key, st):
        """把科考任务派给某个人；任务是一条完整路线，不用一步步点。"""
        if not self.worker_available(st):
            self.toast_msg(f'{st.m["name"]} {self.busy_reason(st)}', C_DIM)
            return
        last = self.quest_last.get(key)
        if key != 'ice' and last is not None:
            gap = (self.hour_f() - last) % 24
            if gap < QUEST_COOLDOWN:
                left = QUEST_COOLDOWN - gap
                self.toast_msg(f'这项任务刚做过，还要等 {left:.1f} 小时', C_DIM, 2.4)
                return
        if key == 'ice' and self.ice != 0:
            self.toast_msg('上一趟冰样还没跑完', C_DIM)
            return
        if key == 'ice' and self.ice_runs >= 2:
            self.toast_msg('今天冰样已经跑满 2 趟了', C_DIM)
            return
        if key == 'weather':
            idx = next((i for i, w in enumerate(self.weather) if w == 1), None)
            if idx is None:
                self.toast_msg('现在没有要采的气象数据', C_DIM)
                return
            self.weather[idx] = 2
            ok = self.start_quest_worker(
                f'weather:{idx}',
                [('WEATHER', WEATHER_POINT, 30, 0.04),
                 ('CONSOLE', UPLOAD_POINT, 15, 0.0)], who=st)
        elif key == 'ice':
            if self.ice != 0:
                self.toast_msg('冰样已经在流程里了', C_DIM)
                return
            ok = self.start_quest_worker(
                'ice',
                [('BALCONY', AIRLOCK_POINT, 30, 0.06),
                 ('LAB', LAB_POINT, 40, 0.10),
                 ('CONSOLE', UPLOAD_POINT, 15, 0.0)], who=st)
            if ok:
                self.ice = 1
        elif key == 'green':
            if getattr(self, 'green_day', -1) == self.day:
                self.toast_msg('今天温室已经收过了', C_DIM)
                return
            ok = self.start_quest_worker('green', [('GREEN', GREEN_POINT, 30, 0.06)],
                                         who=st)
            if ok:
                self.green_day = self.day
        else:
            ok = False
        if ok:
            self.quest_last[key] = self.hour_f()
            if key == 'ice':
                self.ice_runs += 1
            self.quest_sel = None
            self.toast_msg(f'{st.m["name"]} 已安排 · 选完关面板一起出发', C_GOLD, 2.2)

    def click_weather(self):
        idx = next((i for i, w in enumerate(self.weather) if w == 1), None)
        if idx is None:
            self.toast_msg('现在没有要采的气象数据', C_DIM)
            return False
        st = self.pick_quest_worker()
        if st is None:
            self.toast_msg('所有人都没空，等他们闲下来再点', C_DIM)
            return False
        self.dispatch_quest('weather', st)
        return True

    def click_ice(self):
        if self.ice != 0:
            self.toast_msg('冰样已经在流程里了', C_DIM)
            return False
        st = self.pick_quest_worker()
        if st is None:
            self.toast_msg('所有人都没空，等他们闲下来再点', C_DIM)
            return False
        self.dispatch_quest('ice', st)
        return bool(st.quest)

    def click_lab(self):
        self.toast_msg('冰样任务是一条龙：气闸采样 → 实验室化验 → 主控室上传', (170, 210, 230), 2.4)
        return False

    def click_upload(self):
        self.toast_msg('上传已经包含在任务路线里了，不用单独点', C_DIM, 2.2)
        return False

    def click_supply_car(self):
        """右下角的雪地补给车：看订单和下一趟。"""
        if self.scene != 'station':
            return False
        left = max(0, SUPPLY_EVERY - self.day % SUPPLY_EVERY) if self.day % SUPPLY_EVERY else 0
        n = len(self.pending_supply)
        if n:
            self.toast_msg(f'补给车：车上 {n} 件货，下次靠岸 {left} 天后', (200, 220, 180), 3.0)
        else:
            self.toast_msg(f'补给车闲置中 · 下次补给 {left} 天后（主控台可以先下单）',
                           (180, 200, 180), 3.0)
        return True

    def click_greenhouse(self):
        if self.green_day == self.day:
            self.toast_msg(f'今天温室已经收过了 · 仓库食材 {self.warehouse["food"]}',
                           (150, 220, 160), 2.2)
            return True
        qw = self.station_by_id('Qwen')
        if qw is None or not (qw.unlocked and qw.subscribed):
            self.toast_msg('千问还没上线，没人照顾温室', C_DIM)
            return False
        self.dispatch_quest('green', qw)
        return True

    def server_tasks(self):
        """面板左边能选的任务：待处理的 + 已经在做的协作单（方便再加人）。"""
        q = self.queued_tasks()
        svc = [t for t in self.tasks if t.state == 'service' and t.multi]
        return q + svc

    def task_rows(self):
        """服务器面板左边的任务行：两列三行，6 个位置全部可见可点。"""
        r = self.server_panel_rect()
        out = []
        for i, t in enumerate(self.server_tasks()[:6]):
            c, rw = i % 2, i // 2
            out.append((t, pygame.Rect(r.x + 26 + c * 198, r.y + 84 + rw * 74, 188, 66)))
        return out

    @staticmethod
    def task_del_btn(rr):
        """任务行右上角的「退回」小按钮。"""
        return pygame.Rect(rr.right - 26, rr.y + 4, 20, 20)

    def scene_ok(self, st):
        """这条线在当前场景里出不出现（Kimi/混元/Seed 只在科考站）。"""
        want = st.m.get('scene')
        return want is None or want == self.scene

    def visible_stations(self):
        return [st for st in self.stations if self.scene_ok(st) and st.unlocked]

    def server_cards(self):
        """右边各条线路的卡片（2 列，最多 12 张）。"""
        r = self.server_panel_rect()
        out = []
        cw, ch = 196, 102
        for i, st in enumerate(self.visible_stations()):
            c, rw = i % 2, i // 2
            out.append((st, pygame.Rect(r.x + 440 + c * 210, r.y + 80 + rw * 108, cw, ch)))
        return out


    def breaker_panel_rect(self):
        return pygame.Rect(SW // 2 - 230, SH // 2 - 190, 460, 380)

    def fuel_buy_btn(self):
        r = self.breaker_panel_rect()
        return pygame.Rect(r.x + 28, r.y + 234, 220, 38)

    def breaker_up_btn(self):
        r = self.breaker_panel_rect()
        return pygame.Rect(r.centerx - 110, r.y + 308, 220, 44)

    def draw_breaker_panel(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 175))
        r = self.breaker_panel_rect()
        alpha_rect(s, r, (20, 22, 32, 248), 10)
        pygame.draw.rect(s, (120, 132, 158), r, 2, border_radius=10)

        busy = self.grid_load()
        cap = self.breaker_cap()
        over = self.overload_t > 0.1

        txt(s, '配电柜' if self.scene == 'station' else '楼梯间电闸',
            r.x + 28, r.y + 22, 24, C_TEXT, bold=True)
        txt(s, f'Lv{self.breaker_lv} / 5', r.x + 166, r.y + 32, 14, (150, 158, 182))

        txt(s, '同时开工', r.x + 28, r.y + 78, 13, (130, 138, 162))
        txt(s, f'{busy} 路', r.x + 28, r.y + 96, 30, C_RED if busy > cap else C_GREEN, bold=True)
        txt(s, '容量', r.x + 168, r.y + 78, 13, (130, 138, 162))
        txt(s, f'{cap} 路', r.x + 168, r.y + 96, 30, C_TEXT, bold=True)

        # 负载条
        bar = pygame.Rect(r.x + 28, r.y + 146, r.w - 56, 12)
        pygame.draw.rect(s, (34, 38, 54), bar)
        for i in range(cap):
            seg = pygame.Rect(bar.x + 2 + i * (bar.w - 4) // cap, bar.y + 2,
                              (bar.w - 4) // cap - 3, bar.h - 4)
            pygame.draw.rect(s, (120, 220, 180) if i < busy else (44, 50, 62), seg)

        if over:
            txt(s, f'过载中！{max(0, 9 - self.overload_t):.1f} 秒后跳闸',
                r.centerx, r.y + 166, 14, C_RED, 'midtop', bold=True)
        elif self.tripped > 0:
            txt(s, f'已跳闸，{self.tripped:.1f} 秒后恢复', r.centerx, r.y + 166, 14,
                C_RED, 'midtop', bold=True)
        else:
            txt(s, '同时开工超过容量并持续 9 秒就会跳闸，电路上的单全废。',
                r.centerx, r.y + 166, 12, (128, 136, 160), 'midtop')
        txt(s, '每条接电的线路占 1 路容量；Seed 现在也接电了。',
            r.centerx, r.y + 184, 11, (110, 118, 142), 'midtop')

        txt(s, f'换一套更大的电闸：¥{self.breaker_up_cost():,}', r.centerx, r.y + 292, 13,
            C_GOLD if self.breaker_lv < 5 else (110, 116, 138), 'midtop')

        btn = self.breaker_up_btn()
        can = self.breaker_lv < 5 and self.money >= self.breaker_up_cost()
        col = (150, 200, 236) if can else (64, 68, 84)
        hov = btn.collidepoint(self.mouse)
        alpha_rect(s, btn, (30, 44, 60) if hov and can else (24, 30, 42), 6)
        pygame.draw.rect(s, col, btn, 2, border_radius=6)
        txt(s, '已经最大容量' if self.breaker_lv >= 5 else '升级电闸',
            btn.centerx, btn.y + 11, 17, C_TEXT if can else (124, 128, 146), 'midtop', bold=True)

        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (90, 104, 134), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

    def gateway_panel_rect(self):
        return pygame.Rect(SW // 2 - 240, SH // 2 - 206, 480, 412)

    def gateway_up_btn(self):
        r = self.gateway_panel_rect()
        return pygame.Rect(r.x + 26, r.bottom - 122, 190, 44)

    def gateway_intake_btn(self):
        r = self.gateway_panel_rect()
        return pygame.Rect(r.right - 216, r.bottom - 122, 190, 44)

    def gateway_rest_btn(self):
        """全员休息日放在网关里：和接单开关一样，都是"全站"级别的操作。"""
        r = self.gateway_panel_rect()
        return pygame.Rect(r.x + 26, r.bottom - 64, r.w - 52, 44)

    def draw_gateway_panel(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 175))
        r = self.gateway_panel_rect()
        alpha_rect(s, r, (18, 22, 34, 248), 10)
        pygame.draw.rect(s, (104, 156, 214), r, 2, border_radius=10)

        txt(s, '网络网关', r.x + 28, r.y + 22, 24, C_TEXT, bold=True)
        txt(s, f'Lv{self.gw_lv} / 5', r.x + 150, r.y + 32, 14, (150, 158, 182))

        big = self.gw_big()
        spd = self.gw_speed()
        iv = self.spawn_interval()
        rows = [
            ('出单速度', f'×{spd:.2f}', f'约 {fmt_sec_game(iv)}一单'),
            ('单量上限', f'×{big:.2f}', f'单子最大 {124 * big:.0f} 工作量'),
        ]
        for i, (k, v, note) in enumerate(rows):
            yy = r.y + 80 + i * 40
            txt(s, k, r.x + 28, yy, 13, (132, 140, 166))
            txt(s, v, r.x + 128, yy - 3, 20, C_BLUE, bold=True)
            txt(s, note, r.x + 250, yy + 2, 12, (120, 128, 152))

        txt(s, '升级网关：能接更大的单（工作量更大、出价更高），', r.centerx, r.y + 176, 12,
            (140, 148, 172), 'midtop')
        txt(s, '来单间隔也会缩短。升级不影响线路本身的额度。', r.centerx, r.y + 196, 12,
            (140, 148, 172), 'midtop')

        c = self.gw_up_cost()
        can = self.gw_lv < 5 and self.money >= c
        if self.gw_lv >= 5:
            label = '已满级'
        else:
            label = f'升级 Lv{self.gw_lv + 1} · ¥{c:,}'
        btn = self.gateway_up_btn()
        hov = btn.collidepoint(self.mouse)
        alpha_rect(s, btn, (32, 44, 62) if hov and can else (24, 30, 42), 6)
        pygame.draw.rect(s, (150, 200, 236) if can else (64, 68, 84), btn, 2, border_radius=6)
        txt(s, label, btn.centerx, btn.y + 11, 15, C_TEXT if can else (124, 128, 146),
            'midtop', bold=True)

        # 接单开关
        bb = self.gateway_intake_btn()
        hov2 = bb.collidepoint(self.mouse)
        if self.intake:
            alpha_rect(s, bb, (30, 42, 34) if hov2 else (22, 30, 26), 6)
            pygame.draw.rect(s, (120, 190, 150), bb, 2, border_radius=6)
            txt(s, '暂停接单', bb.centerx, bb.y + 11, 15, (186, 232, 200), 'midtop', bold=True)
        else:
            alpha_rect(s, bb, (52, 32, 32) if hov2 else (34, 24, 24), 6)
            pygame.draw.rect(s, (232, 130, 126), bb, 2, border_radius=6)
            txt(s, '恢复接单', bb.centerx, bb.y + 11, 15, (255, 176, 168), 'midtop', bold=True)

        # 全员休息日（原来在右栏，和日志叠在一起，搬到这里）
        rb = self.gateway_rest_btn()
        hov3 = rb.collidepoint(self.mouse)
        busy_any = any(st.jobs() and not st.no_fatigue for st in self.stations)
        if self.rest_day:
            alpha_rect(s, rb, (32, 40, 34) if hov3 else (24, 30, 26), 6)
            pygame.draw.rect(s, (128, 190, 150), rb, 2, border_radius=6)
            txt(s, f'全员休息中 · 还剩 {self.rest_left:.1f} 小时（到点自动复工）',
                rb.centerx, rb.y + 11, 15, (170, 226, 190), 'midtop', bold=True)
        else:
            alpha_rect(s, rb, (46, 38, 24) if hov3 and not busy_any else (30, 27, 20), 6)
            pygame.draw.rect(s, (236, 206, 130) if not busy_any else (110, 100, 76), rb,
                             2, border_radius=6)
            txt(s, f'全员休息日（明天全员效率 +{int(REST_BONUS * 100)}%）',
                rb.centerx, rb.y + 11, 15,
                (250, 224, 170) if not busy_any else (150, 140, 116), 'midtop', bold=True)
        txt(s, '手上还有活的时候不能休息；Seed 不参与休息。', r.centerx, rb.y - 18, 11,
            (120, 128, 152), 'midtop')

        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (90, 104, 134), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

    def shop_panel_rect(self):
        return pygame.Rect(SW // 2 - 260, SH // 2 - 170, 520, 340)

    def shop_buy_btn(self):
        r = self.shop_panel_rect()
        return pygame.Rect(r.centerx - 110, r.bottom - 66, 220, 46)

    def draw_shop_panel(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 170))
        r = self.shop_panel_rect()
        alpha_rect(s, r, (30, 24, 20, 246), 10)
        pygame.draw.rect(s, (232, 190, 120), r, 2, border_radius=10)

        img = self.assets.model('Nailong')
        if img:
            s.blit(self.assets.scaled(img, 112), (r.x + 36, r.y + 40))

        txt(s, 'Seed 早餐铺', r.x + 172, r.y + 34, 26, (255, 226, 176), bold=True)
        txt(s, '“早上七点就起来蒸包子了，过九点就收摊。”', r.x + 172, r.y + 72, 14, (196, 176, 150))
        txt(s, '给已开通的线路带早餐：8 小时内速度 +10%。',
            r.x + 172, r.y + 104, 14, (208, 200, 186))
        txt(s, f'价格 ¥{BREAKFAST_COST}   （余额 ¥{self.money:,.0f}）',
            r.x + 172, r.y + 132, 14, (232, 190, 120))

        bought = self.breakfast_day == self.day
        open_now = self.breakfast_open()
        if bought:
            hint, hc = '今天的早餐已经买过了，明天早上再来。', (150, 146, 138)
        elif open_now:
            hint, hc = f'营业中 · 现在 {self.clock_text()}，抓紧', (255, 214, 152)
        else:
            hint, hc = (f'收摊了 · 只做 {BREAKFAST_FROM:02d}:00~{BREAKFAST_TO:02d}:00'
                        f'（现在 {self.clock_text()}）'), (168, 138, 120)
        txt(s, hint, r.centerx, r.y + 180, 13, hc, 'midtop')

        btn = self.shop_buy_btn()
        can = (not bought) and open_now and self.money >= BREAKFAST_COST
        col = (232, 190, 120) if can else (70, 66, 60)
        hover = btn.collidepoint(self.mouse)
        alpha_rect(s, btn, (60, 46, 32) if hover and can else (44, 36, 28), 6)
        pygame.draw.rect(s, col, btn, 2, border_radius=6)
        if bought:
            label = '买过了'
        elif not open_now:
            label = '没营业'
        else:
            label = f'买早餐  ¥{BREAKFAST_COST}'
        txt(s, label, btn.centerx, btn.y + 12, 18,
            (255, 236, 200) if can else (130, 126, 118), 'midtop', bold=True)

        cb = self.close_btn(r)
        pygame.draw.rect(s, (52, 44, 36), cb, border_radius=4)
        pygame.draw.rect(s, (120, 100, 80), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, (226, 214, 196), 'midtop', bold=True)

    def fridge_panel_rect(self):
        return pygame.Rect(SW // 2 - 250, SH // 2 - 176, 500, 352)

    def fridge_feed_btn(self):
        r = self.fridge_panel_rect()
        return pygame.Rect(r.x + 26, r.bottom - 72, 212, 46)

    def fridge_buy_btn(self):
        r = self.fridge_panel_rect()
        return pygame.Rect(r.right - 238, r.bottom - 72, 212, 46)

    def draw_fridge_panel(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 170))
        r = self.fridge_panel_rect()
        alpha_rect(s, r, (20, 26, 34, 248), 10)
        pygame.draw.rect(s, (140, 214, 210), r, 2, border_radius=10)

        txt(s, '冰箱', r.x + 26, r.y + 20, 24, C_TEXT, bold=True)
        txt(s, '冷冻层里塞着大家的小零食', r.x + 96, r.y + 30, 12, (140, 156, 176))
        txt(s, f'{self.snacks} 份', r.right - 26, r.y + 18, 22,
            (150, 226, 210) if self.snacks else (120, 128, 148), 'topright', bold=True)

        # 零食小图标
        for i in range(max(SNACK_STOCK, self.snacks)):
            bx = r.x + 28 + i * 30
            by = r.y + 62
            on = i < self.snacks
            col = (240, 206, 130) if on else (44, 50, 62)
            pygame.draw.rect(s, (26, 32, 44), (bx, by, 22, 26), border_radius=3)
            pygame.draw.rect(s, col, (bx, by, 22, 26), 1, border_radius=3)
            pygame.draw.rect(s, col, (bx + 3, by + 3, 16, 7))
            if on:
                pygame.draw.rect(s, (196, 152, 96), (bx + 8, by + 14, 6, 8))

        txt(s, f'发一次：全员处理速度 +{int(SNACK_SPD * 100)}%，'
               f'持续 {fmt_sec_game(SNACK_SEC)}', r.x + 26, r.y + 100, 14, (204, 226, 226))
        txt(s, '冰箱里的零食不会自动补，用完得自己花钱买（随时可用）。',
            r.x + 26, r.y + 122, 12, (132, 146, 168))

        # 当前吃到零食的线路
        hot = [st for st in self.stations if st.snack > 0]
        if hot:
            names = ' / '.join(st.m['name'] for st in hot[:4])
            more = f' 等 {len(hot)} 条' if len(hot) > 4 else ''
            txt(s, f'正在啃零食：{names}{more}', r.x + 26, r.y + 150, 12, (240, 200, 130))
        else:
            txt(s, '现在没人手里有零食。', r.x + 26, r.y + 150, 12, (110, 120, 142))

        txt(s, '同一条线路重复吃只会刷新时间，不会叠加。',
            r.centerx, r.y + 196, 12, (124, 138, 160), 'midtop')
        txt(s, f'余额 ¥{self.money:,.0f}', r.centerx, r.y + 176, 12, (150, 158, 182),
            'midtop')

        fb = self.fridge_feed_btn()
        can = self.snacks > 0
        hov = fb.collidepoint(self.mouse)
        alpha_rect(s, fb, (34, 54, 52) if hov and can else (24, 32, 36), 6)
        pygame.draw.rect(s, (140, 214, 210) if can else (62, 68, 80), fb, 2, border_radius=6)
        txt(s, '发零食 · 用 1 份' if can else '冰箱空了', fb.centerx, fb.y + 12, 17,
            (216, 244, 240) if can else (120, 126, 140), 'midtop', bold=True)

        bb = self.fridge_buy_btn()
        can2 = self.money >= SNACK_BUY
        hov2 = bb.collidepoint(self.mouse)
        alpha_rect(s, bb, (48, 42, 30) if hov2 and can2 else (32, 30, 26), 6)
        pygame.draw.rect(s, (232, 190, 120) if can2 else (70, 66, 60), bb, 2, border_radius=6)
        txt(s, f'补货 {SNACK_BUY_N} 份 · ¥{SNACK_BUY}', bb.centerx, bb.y + 12, 17,
            (255, 236, 200) if can2 else (130, 126, 118), 'midtop', bold=True)

        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (90, 104, 134), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

    def station_up_btn(self):
        r = self.station_panel_rect()
        return pygame.Rect(r.centerx - 150, r.bottom - 120, 300, 46)

    def station_tier_btns(self, st):
        """订阅档位卡（能升级大模型的线路多一张卡）。
        返回 [(kind, tier, rect)]，kind = 'tier' 或 'big'。"""
        r = self.station_panel_rect()
        n = len(st.tiers())                      # 有几档就画几张
        slots = n + (1 if st.has_big() else 0)
        w, gap = (128, 10) if slots > 3 else (172, 12)
        total = slots * w + (slots - 1) * gap
        x0 = r.centerx - total // 2
        out = []
        for i in range(n):
            out.append(('tier', i + 1,
                        pygame.Rect(x0 + i * (w + gap), r.bottom - 70, w, 50)))
        if st.has_big():
            out.append(('big', 0,
                        pygame.Rect(x0 + n * (w + gap), r.bottom - 70, w, 50)))
        return out

    def station_reset_btn(self):
        r = self.station_panel_rect()
        return pygame.Rect(r.x + 28, r.y + 448, 300, 32)

    def station_duty_btn(self):
        r = self.station_panel_rect()
        return pygame.Rect(r.x + 372, r.y + 92, 190, 28)

    def station_relations_btn(self):
        """工位面板右栏的「人缘关系」入口：打开单独的关系面板。"""
        r = self.station_panel_rect()
        return pygame.Rect(r.x + 372, r.y + 372, r.right - 28 - (r.x + 372), 44)

    def station_job_btn(self):
        """工位面板里「暂停 / 继续」手上这单。"""
        r = self.station_panel_rect()
        return pygame.Rect(r.x + 28, r.y + 270, 108, 32)

    def station_abandon_btn(self):
        """工位面板里「放弃这单」。"""
        r = self.station_panel_rect()
        return pygame.Rect(r.x + 146, r.y + 270, 108, 32)

    # ------------------------------------------------ 主循环
    def run(self):
        while self.running:
            dt = min(0.05, self.clock.tick(FPS) / 1000.0)
            for ev in pygame.event.get():
                self.on_event(ev)
            self.mouse = self.map_mouse(pygame.mouse.get_pos())
            self.frame_i += 1
            if self.frame_i > 30:            # 启动头几帧窗口可能还没拿到焦点
                self.check_focus()
            if self.state == 'play' and not self.paused:
                self.update(dt)
            elif self.panel and self.panel[0] == 'summary':
                pass
            self.draw()
        pygame.quit()

    def on_event(self, ev):
        if ev.type in AWAY_EVENTS:
            self.set_away(True)
            return
        if ev.type in BACK_EVENTS:
            self.set_away(False)
            return
        if ev.type == pygame.QUIT:
            if self.state == 'play':
                if not getattr(self, 'test_mode', False):
                    self.save()      # 关窗口也存一下（试玩不写档）
            self.running = False
        elif ev.type == pygame.KEYDOWN:
            k = ev.key
            if k == pygame.K_ESCAPE:
                if self.held_item:
                    self.held_item = None
                    self.toast_msg('放下了手里的道具', C_DIM, 1.6)
                elif self.panel:
                    if self.panel[0] == 'settings':
                        self.paused = False
                    if self.panel[0] == 'relations':
                        self.close_relations()
                    else:
                        if self.panel[0] == 'server':
                            self.quest_sel = None
                        self.panel = None
                elif self.state == 'play':
                    self.paused = not self.paused
            elif k == pygame.K_r and self.state != 'play':
                self.reset()
                self.state = 'play'
            elif k in (pygame.K_1, pygame.K_2, pygame.K_3):
                self.speed = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3}[k]
            elif k == pygame.K_SPACE:
                self.paused = not self.paused
            elif k in (pygame.K_UP, pygame.K_RIGHT, pygame.K_EQUALS):
                self.price_idx = min(len(PRICE_STEPS) - 1, self.price_idx + 1)
            elif k in (pygame.K_DOWN, pygame.K_LEFT, pygame.K_MINUS):
                self.price_idx = max(0, self.price_idx - 1)
            elif k == pygame.K_F11:
                self.toggle_fullscreen()
            elif k == pygame.K_s and self.state == 'play':
                self.save()
                self.has_save = True
                self.toast_msg('已存档', C_GREEN, 1.8)
            elif pygame.K_a <= k <= pygame.K_i and self.state == 'play' and not self.panel:
                i = k - pygame.K_a
                if i < len(self.stations):
                    self.panel = ('station', self.stations[i])
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            pos = self.map_mouse(ev.pos)
            if self.panel:
                # 面板是模态的：标题页也先交给面板，别穿透到底下的首页按钮
                self.handle_click(pos)
            elif self.state == 'title':
                self.click_title(pos)
            else:
                self.handle_click(pos)
        elif ev.type == pygame.MOUSEWHEEL:
            if self.state == 'play' and not self.panel:
                self.zoom_wheel(ev.y)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3:
            if self.state == 'play' and not self.panel:
                self.drag = self.map_mouse(ev.pos)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 3:
            self.drag = None
        elif ev.type == pygame.MOUSEMOTION:
            pos = self.map_mouse(ev.pos)
            if self.drag_item:
                self.update_drag(pos)
            if self.drag:
                dx = pos[0] - self.drag[0]
                dy = pos[1] - self.drag[1]
                self.drag = pos
                self.drag_cam(dx, dy)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            if self.drag_item:
                self.finish_drag(self.map_mouse(ev.pos))

    def title_slot_rects(self):
        """首页的 4 个存档位：2 列 2 行。"""
        out = []
        w, h = 540, 116
        for i in range(SLOT_COUNT):
            col, row = i % 2, i // 2
            out.append((i + 1, pygame.Rect(70 + col * (w + 40),
                                           268 + row * (h + 22), w, h)))
        return out

    def title_buttons(self):
        """[(action, rect, slot)]：load / new / delete 每格一套，另有 settings / quit。"""
        out = []
        for slot, card in self.title_slot_rects():
            info = self.peek_save(slot)
            bx = card.right - 116
            if info:
                out.append(('load', pygame.Rect(bx, card.y + 14, 100, 30), slot))
                out.append(('new', pygame.Rect(bx, card.y + 50, 100, 26), slot))
                out.append(('delete', pygame.Rect(bx, card.y + 82, 100, 22), slot))
            else:
                out.append(('new', pygame.Rect(bx, card.y + 30, 100, 34), slot))
        by = 596                     # 放在存档卡下面，设置面板（到 570）盖不到
        out.append(('settings', pygame.Rect(SW // 2 - 310, by, 190, 44), 0))
        out.append(('test', pygame.Rect(SW // 2 - 95, by, 190, 44), 0))
        out.append(('quit', pygame.Rect(SW // 2 + 120, by, 190, 44), 0))
        return out

    def start_test_station(self):
        """试玩入口：直接开一局科考站，线路全开、燃料满。"""
        self.reset()
        self.test_mode = True            # 试玩模式：不覆盖正式存档
        self.money = 8000
        self.day = 1
        self.set_scene('station')
        for st in self.stations:
            st.unlocked = True
            st.subscribed = True
            st.tier = 2
            st.sub_days = SUB_DAYS
            st.refresh_daily()
        self.breaker_lv = 4          # 协作要占好几路电，试玩给足
        self.fuel = 120.0
        self.cold = False
        self.state = 'play'
        self.panel = ('intro', 'station') if INTRO_ON else None   # 第一次进站先讲玩法
        self.seen_station_intro = True
        self.paused = False
        self.log('科考站试玩：全部线路已开通，燃料加满', C_GOLD)
        self.toast_msg('科考站试玩模式 · 不用攒钱', C_GOLD, 2.6)

    def click_title(self, pos):
        for action, r, slot in self.title_buttons():
            if not r.collidepoint(pos):
                continue
            if action == 'test':
                self.start_test_station()
                return
            if action == 'new':
                if self.save_exists(slot):
                    try:
                        os.remove(save_path(slot))
                    except OSError:
                        pass
                self.reset()
                self.slot = slot
                self.state = 'play'
                if INTRO_ON:                     # 第 1 幕：深夜第一单
                    self.show_comic([0], to_intro=True)
                    self.seen_apt_intro = True
            elif action == 'load':
                if self.load(slot):
                    self.state = 'play'
                else:
                    self.reset()
                    self.slot = slot
                    self.state = 'play'
            elif action == 'delete':
                try:
                    os.remove(save_path(slot))
                except OSError:
                    pass
                self.has_save = any(os.path.exists(save_path(i))
                                    for i in range(1, SLOT_COUNT + 1))
            elif action == 'settings':
                self.panel = ('settings', 'title')
            elif action == 'quit':
                self.running = False
            return

    # ================================================ 绘制
    def blit_world(self):
        """把 world 画到屏幕上；zoom > 1 时只画视野那一块并放大。"""
        if self.zoom <= 1.001:
            self.screen.blit(self.world, (0, 0))
            return
        vx, vy, vw, vh = self.view_box()
        src = pygame.Rect(int(round(vx)), int(round(vy)),
                          max(1, int(round(vw))), max(1, int(round(vh))))
        src = src.clip(pygame.Rect(0, 0, WW, WH))
        if src.w < 4 or src.h < 4:
            self.screen.blit(self.world, (0, 0))
            return
        scaled = pygame.transform.scale(self.world.subsurface(src), (WW, WH))
        self.screen.blit(scaled, (0, 0))

    def draw(self):
        self.texts_frame = []
        if self.state == 'title':
            self.draw_title()
            # 标题页也可能开面板（设置）：以前这里直接跳过了面板，
            # 点了"设置"看起来像卡死——面板盖在标题上，但根本没画出来。
            if self.panel:
                self.draw_panel()
        else:
            self.draw_world()
            self.blit_world()
            paused_view = self.paused and not self.panel
            if not (paused_view or self.panel):
                self.flush_world_texts()
            self.draw_world_goal()
            self.draw_log()
            if self.panel:
                self.draw_panel()
            if self.state == 'play' and (self.drag_item or self.held_item):
                self.draw_held_item()
            if paused_view:
                self.draw_pause()
            if self.toast:
                self.draw_toast()
        if self.state != 'title':
            self.draw_hud()
        self.present()

    # ---- 世界文字（世界坐标 -> 放大后 screen 绘制，保证清晰） ----
    def wt(self, x, y, s, size=11, color=C_TEXT, align='center'):
        self.texts_frame.append((x, y, s, size, color, align))

    def pill(self, x, y, text, size=10, color=C_TEXT, bg=(9, 10, 17), pad=6):
        """状态小牌：底 + 边框 + 文字一次渲染成一张图再贴，跟名字牌同款机制。"""
        lab = font(size, True).render(str(text), True, color)
        pw, ph = lab.get_width() + pad * 2, lab.get_height() + 6
        surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(surf, (*bg[:3], 238), surf.get_rect(), border_radius=4)
        pygame.draw.rect(surf, color, surf.get_rect(), 1, border_radius=4)
        surf.blit(lab, (pad, 3))
        self.world.blit(surf, (int(x - pw / 2), int(y)))

    def flush_world_texts(self):
        for x, y, s, size, color, align in self.texts_frame:
            anchor = {'center': 'midtop', 'left': 'topleft', 'right': 'topright'}[align]
            txt(self.screen, s, int(x * SCALE), int(y * SCALE), size, color, anchor)

    def float_plate(self, x, y, text, size=12, color=C_GOLD, a=1.0):
        """场景里的临时飘字：和名字牌一样整块渲染（底 + 边框 + 字），整体淡出。"""
        a = max(0.0, min(1.0, a))
        lab = font(size, True).render(str(text), True, color)
        pw, ph = lab.get_width() + 12, lab.get_height() + 5
        surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(surf, (9, 10, 17, int(215 * a)), surf.get_rect(), border_radius=5)
        pygame.draw.rect(surf, (*color[:3], int(200 * a)), surf.get_rect(), 1, border_radius=5)
        lab.set_alpha(int(255 * a))
        surf.blit(lab, (6, 2))
        self.world.blit(surf, (int(x - pw / 2), int(y)))

    # ---------------------------------------------------- 场景
    def update_station_anim(self, s, dt):
        """让有行走帧的角色在房间空地上来回踱步；忙起来就站定。"""
        sid = self.assets.sprite_id(s)
        frames = self.assets.walk.get(sid)
        can = (frames and s.unlocked and s.busy is None
               and not s.limited and s.stuck <= 0 and s.slack <= 0)
        # 算力压力：忙的时候按任务重量爬升，闲下来回落。
        # 被限流时温度冻结（既不升也不降，换档/重置卡才能降温）；手动暂停才算休息。
        if s.limited:
            pass
        elif s.jobs() and not s.paused_job:
            j = s.main_job()
            load = min(1.0, (j.w / 120.0) * (3.6 / max(1.6, s.spd())))
            heat = (TEMP_RISE + TEMP_LOAD * load) * dt
            if s.has_gear('fan'):
                heat *= 0.80          # 散热扇：热量积累 -20%
            s.temp += heat
        else:
            s.temp -= TEMP_COOL * dt
        s.temp = max(TEMP_IDLE, s.temp)
        if s.temp >= TEMP_LIMIT and s.jobs():
            self.overheat(s)

        if s.stop_blend > 0:
            s.stop_blend = max(0.0, s.stop_blend - dt)
        if not WALK_ON:                 # 先都不动：站着就好
            s.walking = False
            s.stop_blend = 0.0
            # 闲下来去客厅聊天的人不在房间里，别把他拽回工位
            if s.social_state == 'home' and abs(s.px - s.cx) > 0.8:
                d = s.cx - s.px
                s.px += max(-2.0, min(2.0, d * min(1.0, dt * 4.0)))   # 慢慢挪，不瞬移
            return
        if not can:
            s.walking = False
            # 忙起来或者下线时慢慢走回自己的位置，不要瞬移
            if abs(s.px - s.cx) > 0.8:
                d = s.cx - s.px
                s.px += max(-2.0, min(2.0, d * min(1.0, dt * 4.0)))   # 慢慢挪，不瞬移
            return
        if not s.walking:
            s.walk_wait -= dt
            if s.walk_wait <= 0:
                s.walking = True
                s.dir = random.choice((-1, 1))
                s.anim_t = 0.0
                s.walk_span = random.uniform(1.8, 3.6)
            return
        s.px += s.dir * 24.0 * dt
        s.anim_t += dt
        s.frame_i = int(s.anim_t * 6) % len(frames)
        if s.px < s.cx - 18:
            s.px, s.dir = s.cx - 18, 1
        elif s.px > s.cx + 18:
            s.px, s.dir = s.cx + 18, -1
        s.walk_span -= dt
        if s.walk_span <= 0:
            s.walking = False
            s.stop_blend = 0.28
            s.walk_wait = random.uniform(2.5, 7.0)

    def draw_world(self):
        w = self.world
        self.draw_ground()
        if self.assets.apartment:
            w.blit(self.assets.apartment, APT_POS)
        if self.assets.shop and self.scene != 'station':
            w.blit(self.assets.shop, SHOP_POS)
        self.draw_gateway()
        self.draw_server()
        self.draw_breaker()
        self.draw_shop_sign()
        self.draw_gear_shop()
        self.draw_task_zone()
        # 角色：靠下的后画，形成前后遮挡
        for st in sorted(self.visible_stations(), key=lambda x: x.feet):
            self.draw_station(st)
        self.draw_bonds()
        self.draw_beams()
        for t in self.tasks:
            if t.state == 'in':
                self.draw_task(t)
        # 粒子
        for p in self.particles:
            a = max(0, min(255, int(255 * p['life'])))
            pygame.draw.circle(self.fx, (*p['color'], a), (int(p['x']), int(p['y'])), 2)
        w.blit(self.fx, (0, 0))
        self.fx.fill((0, 0, 0, 0))
        # 飘字（整块底 + 文字，和名字牌同一套画法，保证看得见）
        for tx in self.texts:
            x, y, s_, size, color, life = tx
            self.float_plate(x, y, s_, size, color, max(0.0, min(1.0, life)))

    def draw_ground(self):
        """公寓外面的地坪（深色，衬托公寓）。"""
        w = self.world
        w.fill((33, 29, 24))
        for y in range(0, WH, 24):
            pygame.draw.line(w, (37, 33, 27), (0, y), (WW, y))
        for x in range(0, WW, 24):
            pygame.draw.line(w, (37, 33, 27), (x, 0), (x, WH))
        # 早餐铺门前的暖光（科考站没有早餐铺）
        if self.scene == 'station':
            return
        srf = pygame.Surface((260, 260), pygame.SRCALPHA)
        for rr, aa in ((120, 10), (80, 14), (46, 20)):
            pygame.draw.circle(srf, (255, 216, 156, aa), (130, 130), rr)
        w.blit(srf, (SHOP_POS[0] - 44, SHOP_POS[1] - 44))

    def draw_server(self):
        """客厅里那台派单服务器：背景图里已经有了，这里只做高亮和标签。"""
        w = self.world
        x, y = SERVER
        tt = pygame.time.get_ticks()
        for i, rr in enumerate((26, 20, 14)):
            a = 26 + 14 * i + int(9 * math.sin(tt / 320 + i))
            srf = pygame.Surface((rr * 2, rr * 2), pygame.SRCALPHA)
            pygame.draw.circle(srf, (120, 240, 190, a), (rr, rr), rr, 1)
            w.blit(srf, (x - rr, y - rr))
        # 上下浮动的指示箭头
        off = int(math.sin(tt / 380) * 2)
        pygame.draw.polygon(w, (150, 236, 200),
                            [(x - 4, y - 34 + off), (x + 4, y - 34 + off), (x, y - 28 + off)])
        # 待处理单数角标
        n = len(self.queued_tasks())
        if n:
            self.pill(x + 18, y - 50, str(n), 10, (170, 255, 220), bg=(16, 26, 24), pad=6)


    def draw_shop_keeper(self):
        """早餐铺柜台后的豆包。"""
        img = self.assets.model('Nailong')
        if not img:
            return
        x = SHOP_POS[0] + 82
        y = SHOP_POS[1] + 128
        bob = int(math.sin(pygame.time.get_ticks() / 520) * 1.5)
        self.world.blit(img, (x - img.get_width() // 2, y - img.get_height() + bob))
        self.pill(x, y + 4, 'Seed', 10, (255, 214, 150), bg=(24, 18, 12), pad=6)

    def draw_breaker(self):
        """楼梯间的电闸：过载时会闪红。"""
        w = self.world
        x, y = BREAKER
        box = pygame.Rect(x - 13, y - 30, 26, 32)
        pygame.draw.rect(w, (52, 54, 62), box, border_radius=2)
        pygame.draw.rect(w, (96, 100, 112), box, 1, border_radius=2)
        pygame.draw.rect(w, (34, 36, 44), (box.x + 3, box.y + 3, box.w - 6, 8))
        # 闸刀
        pygame.draw.rect(w, (150, 154, 166), (box.centerx - 2, box.y + 4, 4, 6))
        hot = self.overload_t > 0.1 or self.tripped > 0
        tt = pygame.time.get_ticks()
        if hot:
            on = (tt // 120) % 2 == 0
            led = (255, 90, 80) if on else (90, 40, 40)
        else:
            led = (110, 230, 170)
        pygame.draw.rect(w, led, (box.centerx - 2, box.y + 15, 4, 4))
        # 负载刻度
        cap = self.breaker_cap()
        busy = self.grid_load()
        for i in range(cap):
            c = (120, 220, 180) if i < busy else (44, 52, 52)
            pygame.draw.rect(w, c, (box.x + 4 + i * 5, box.y + 22, 3, 4))
        # 名字牌：和角色名字同一套渲染（整块 Surface 贴图，不用世界文字队列）
        nm = '配电柜' if self.scene == 'station' else '电闸'
        self.pill(x, y + 4, f'{nm} Lv{self.breaker_lv} · {cap}路', 11,
                  (255, 150, 140) if hot else (196, 204, 220),
                  bg=(9, 10, 17), pad=6)

    def draw_gateway(self):
        """门厅里的网络网关：网上发来的任务从这台机器涌进站。"""
        w = self.world
        gx, gy = GATEWAY
        r = pygame.Rect(gx - 15, gy - 22, 30, 22)
        pygame.draw.rect(w, (24, 28, 42), r, border_radius=3)
        pygame.draw.rect(w, (58, 86, 130), r, 1, border_radius=3)
        pygame.draw.line(w, (74, 100, 146), (gx - 9, gy - 22), (gx - 11, gy - 32), 1)
        pygame.draw.line(w, (74, 100, 146), (gx + 9, gy - 22), (gx + 7, gy - 32), 1)
        pygame.draw.rect(w, (130, 180, 236), (gx - 12, gy - 33, 2, 2))
        pygame.draw.rect(w, (130, 180, 236), (gx + 6, gy - 33, 2, 2))
        tt = pygame.time.get_ticks()
        for i in range(5):
            on = (tt // 140 + i) % 4 < 2
            if not self.intake:                       # 停接：灯全暗下来
                c = (58, 40, 40) if i < self.gw_lv else (46, 42, 40)
            else:
                c = (110, 232, 172) if on and i < self.gw_lv else (
                    (36, 58, 54) if i < self.gw_lv else (52, 46, 40))
            pygame.draw.rect(w, c, (r.x + 4 + i * 5, r.y + 6, 3, 3))
        if self.intake:
            self.pill(gx, gy + 4, f'网络网关 Lv{self.gw_lv}', 10, (168, 202, 238),
                      bg=(9, 12, 20), pad=6)
        else:
            self.pill(gx, gy + 4, f'网关 Lv{self.gw_lv} · 停接', 10, (238, 150, 140),
                      bg=(22, 12, 12), pad=6)

    def draw_task_zone(self):
        return


    def draw_station(self, s):
        """角色站在自己房间的空地上；串门时用行走帧，干活时钉在工位不动。"""
        w = self.world
        feet = s.feet
        sid = self.assets.sprite_id(s)
        frames = self.assets.walk.get(sid)
        # 串门途中（有行走帧的角色）：跑 4 帧循环，看起来是在走而不是滑
        social_walk = (s.social_state in ('walk', 'back') and frames
                       and s.unlocked)
        walking = (WALK_ON and getattr(s, 'walking', False) and frames and s.unlocked
                   and not s.jobs()) or social_walk

        if walking:
            if social_walk:
                fi = int(pygame.time.get_ticks() / 105) % len(frames)
            else:
                fi = s.frame_i % len(frames)
            fr = frames[fi]
            # 这套行走帧本身是朝左的：往右走才需要翻
            if s.dir > 0:
                fr = pygame.transform.flip(fr, True, False)
            w.blit(fr, (int(s.px) - 32, feet - fr.get_height() + 1))
        elif WALK_ON and s.unlocked and frames and s.stop_blend > 0 and not s.jobs():
            fr = frames[0]
            if s.dir > 0:
                fr = pygame.transform.flip(fr, True, False)
            w.blit(fr, (int(s.px) - 32, feet - fr.get_height() + 1))
        else:
            img = self.assets.model(sid)
            if img and self.scene == 'station':
                img = self.assets.scaled(img, 48)   # 站内人小一号，地图显大
            if img:
                bob = int(math.sin(pygame.time.get_ticks() / 420 + s.idx) * 1.2)
                if s.social_state in ('walk', 'back'):
                    bob += int(math.sin(pygame.time.get_ticks() / 110 + s.idx) * 2.0)
                dx = int(s.px) - img.get_width() // 2
                dy = feet - img.get_height() + 1 + bob
                if s.unlocked:
                    w.blit(img, (dx, dy))
                else:
                    tmp = img.copy()
                    tmp.fill((96, 98, 118, 255), special_flags=pygame.BLEND_RGBA_MULT)
                    w.blit(tmp, (dx, dy))

        # 影子
        pygame.draw.ellipse(w, (0, 0, 0, 46), (int(s.px) - 10, feet - 6, 20, 5))

        # 聊天气泡：放在脑袋上方（贴着屏幕顶就往下压一点）
        if s.chat_line:
            bx, by = self.chat_bubble_pos(s)
            self.pill(bx, by, s.chat_line, 12, (232, 238, 250),
                      bg=(22, 24, 36), pad=7)

        # 摸鱼：脚边支起一口电饭锅
        if s.slack > 0 or s.cooking > 0:
            self.draw_rice_pot(int(s.px) - 30, feet - 1)

        # 名字牌：小一点、贴在人右侧（不再顶在头上挡聊天气泡）
        nm = f"{s.m['name']}·小" if s.is_small() else s.m['name']
        col = (255, 255, 255) if s.subscribed else (178, 182, 200)
        edge = s.m['color'] if s.subscribed else (96, 100, 116)
        lab = font(11, True).render(nm, True, col)
        pw, ph = lab.get_width() + 13, 16
        px_, py_ = self.name_plate_pos(s)
        py_ += (s.idx % 2) * 9          # 奇数位下移，减少重叠
        plate = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(plate, (8, 9, 15, 232), plate.get_rect(), border_radius=4)
        pygame.draw.rect(plate, edge, plate.get_rect(), 1, border_radius=4)
        pygame.draw.rect(plate, edge, (3, 3, 2, ph - 6))
        plate.blit(lab, (8, (ph - lab.get_height()) // 2))
        w.blit(plate, (px_, py_))

        # 名字牌下沿一条细线：上游限流压力（跑太狠会变红，满了就被限流）
        if s.subscribed and s.strain > 0.04:
            f = min(1.0, s.strain)
            lx = px_ + 4
            lw = max(8, pw - 8)
            ly = py_ + ph + 1
            pygame.draw.rect(w, (18, 16, 20), (lx, ly, lw, 2))
            lc = C_RED if f >= STRAIN_WARN else (236, 186, 96)
            pygame.draw.rect(w, lc, (lx, ly, max(1, int(lw * f)), 2))

        # 入场演出：头顶气泡
        if self.cutscene and self.cutscene.get('phase') == 'greet':
            for p in [self.station_by_id(self.cutscene['sid'])] + \
                     [self.station_by_id(x) for x in self.cutscene['mates']]:
                if p is not None and p.chat_line:
                    self.pill(p.px, p.feet - 92, p.chat_line, 9, (250, 246, 230),
                              bg=(18, 20, 28), pad=6)

        # 主控室标注
        if self.scene == 'station':
            self.pill(472, 198, '主控室', 10, (160, 215, 235), bg=(10, 16, 22), pad=6)

        # 科考任务：头顶一条进度条 + 目的地
        if s.quest:
            self.draw_quest_bar(s, feet)

        # 头顶：处理进度 / 异常状态（二选一）
        # 正在聊天时不画这些状态牌：它们会压在气泡上，聊天优先
        if not self.show_status_pill(s):
            pass
        elif s.cooking > 0:
            self.pill(s.px, feet - 84, f'做饭中 {fmt_sec_game(s.cooking)}', 10,
                      (244, 206, 140), bg=(30, 22, 10), pad=6)
        elif s.slack > 0:
            self.pill(s.px, feet - 84, f'煮大白饭 {fmt_sec_game(s.slack)} · 点它', 9,
                      (244, 196, 120), bg=(26, 18, 8), pad=5)
        elif s.stuck > 0:
            self.pill(s.px, feet - 84, f'宕机 {fmt_sec_game(s.stuck)}', 10, C_RED)
        elif not s.has_quota():
            self.pill(s.px, feet - 84, '今日额度空', 10, C_RED)
        elif s.paused_job and s.busy:
            self.pill(s.px, feet - 84, '已暂停 · 点面板继续', 9, (236, 220, 150),
                      bg=(26, 24, 10), pad=6)
        elif s.limited:
            self.pill(s.px, feet - 84, f'限流 · 速度{THROTTLE_PCT}%', 9,
                      (240, 130, 110), bg=(26, 12, 12), pad=6)
        elif (s.fatigue > 0.60 and not s.jobs()
              and s is self.tiredest()):
            self.pill(s.px, feet - 84, '有点累了 · 该歇会儿', 9,
                      (236, 200, 130), bg=(28, 24, 12), pad=6)
        elif s.jobs():
            bw, bh = 44, 5
            bx = int(s.px) - bw // 2
            by = feet - 74
            pygame.draw.rect(w, (16, 18, 28), (bx - 1, by - 1, bw + 2, bh + 2))
            hot = s.temp > TEMP_LIMIT * 0.82
            col = (150, 150, 160) if s.paused_job else (C_RED if hot else s.m['color'])
            pygame.draw.rect(w, C_RED if hot else (74, 84, 112),
                             (bx - 1, by - 1, bw + 2, bh + 2), 1)
            j = s.main_job()
            pygame.draw.rect(w, col,
                             (bx, by, max(1, int(bw * min(1, j.prog))), bh))
            if s.busy2 is not None:      # 第二单：下面再来一条细的
                by2 = by + bh + 2
                pygame.draw.rect(w, (74, 84, 112), (bx - 1, by2 - 1, bw + 2, 4))
                pygame.draw.rect(w, s.m['color'],
                                 (bx, by2, max(1, int(bw * min(1, s.busy2.prog))), 2))

        # 脚下两条：上 = 今日额度，下 = 算力压力
        if s.subscribed:
            bx = int(s.px) - 20
            qcap = s.quota_cap()
            if qcap < 0:
                qfrac, qcol = 1.0, (110, 196, 152)
            else:
                qfrac = max(0.0, min(1.0, s.quota / max(1, qcap)))
                qcol = (C_GREEN if qfrac > 0.5 else
                        (C_GOLD if qfrac > 0.2 else C_RED))
            pygame.draw.rect(w, (10, 12, 20), (bx - 1, feet + 1, 42, 6))
            pygame.draw.rect(w, (12, 14, 22), (bx, feet + 2, 40, 4))
            pygame.draw.rect(w, qcol, (bx, feet + 2, max(1, int(40 * qfrac)), 4))
            # 核心温度
            pr = max(0.0, min(1.0, (s.temp - TEMP_IDLE) / (TEMP_LIMIT - TEMP_IDLE)))
            pcol = ((118, 176, 226) if pr < 0.5 else
                    ((240, 202, 120) if pr < 0.8 else C_RED))
            pygame.draw.rect(w, (10, 12, 20), (bx - 1, feet + 7, 42, 6))
            pygame.draw.rect(w, (12, 14, 22), (bx, feet + 8, 40, 4))
            pygame.draw.rect(w, pcol, (bx, feet + 8, max(1, int(40 * pr)), 4))

        if s.breakfast > 0:
            self.pill(s.px - 26, feet - 44, '早餐', 9, (240, 200, 130))
        if s.snack > 0:
            self.pill(s.px + 26, feet - 44, '零食', 9, (150, 226, 210), bg=(9, 16, 18))

    @staticmethod
    def show_status_pill(s):
        """头顶那些状态牌（额度空/限流/宕机/暂停…）要不要画。

        聊天时一律不画——它们和气泡抢同一块地方，会把对话框挡住。
        """
        return bool(s.subscribed and not s.chat_line)

    @staticmethod
    def name_plate_pos(s):
        """名字牌左上角（世界坐标）：贴在角色右侧、齐胸口，避开头顶的气泡。"""
        return (int(s.px) + 22, int(s.feet) - 60)

    def chat_bubble_pos(self, s):
        """聊天气泡的锚点（世界坐标，水平居中）：贴着头顶，而且两个人不会叠在一起。

        - 离头顶近：feet-96（原来 -150 飘太高）；
        - 朝"背对同伴"的方向平移，两边各让开一点；
        - 名字小的那个再抬高一点，万一还是很近也不会糊成一团。
        """
        mate = self.station_by_id(s.chat_partner) if s.chat_partner else None
        shift = 0
        lift = 0
        if mate is not None and mate is not s:
            shift = -44 if mate.px >= s.px else 44
            if s.m['id'] > mate.m['id']:
                lift = -22
        return (int(s.px) + shift, max(2, int(s.feet) - 96 + lift))

    def draw_heart(self, x, y, r=4.5, col=(240, 122, 152)):
        w = self.world
        pygame.draw.circle(w, col, (int(x - r * 0.52), int(y - r * 0.35)), int(r * 0.62))
        pygame.draw.circle(w, col, (int(x + r * 0.52), int(y - r * 0.35)), int(r * 0.62))
        pygame.draw.polygon(w, col, [(x - r * 1.06, y - r * 0.06),
                                     (x + r * 1.06, y - r * 0.06),
                                     (x, y + r * 1.25)])

    def draw_bonds(self):
        """关系好的两个人中间飘一颗小心：只画最强的 3 对，避免满屏爱心。"""
        pairs = sorted(self.bond_pairs(0.5, 190.0), key=lambda x: -x[2])
        top = pairs[:3]
        hov = self.hover_station
        if hov is not None:
            extra = [p for p in pairs[3:] if hov in (p[0], p[1])][:2]
            top = top + extra
        for a, b, v in top:
            mx = (a.px + b.px) / 2
            my = min(a.feet, b.feet) - 44 - math.sin(pygame.time.get_ticks() / 420.0) * 2
            size = 3.6 + 2.6 * v
            self.draw_heart(mx, my, size, (240, 118, 148) if v >= 0.8 else (214, 128, 160))
            if v >= 0.8:
                self.draw_heart(mx, my - 11, size * 0.6, (250, 166, 186))

    def tiredest(self):
        cand = [x for x in self.stations if x.unlocked and x.fatigue > 0.60 and not x.jobs()]
        return max(cand, key=lambda x: x.fatigue) if cand else None

    def draw_quest_bar(self, s, feet):
        """科考任务的进度条：不占额度、不升温，只占人。"""
        w = self.world
        prog = self.quest_progress(s)
        bx, bw = int(s.px) - 36, 72
        y = feet - 104
        pygame.draw.rect(w, (10, 14, 18), (bx - 2, y - 2, bw + 4, 10))
        pygame.draw.rect(w, (14, 20, 24), (bx, y, bw, 6))
        pygame.draw.rect(w, (120, 220, 190), (bx, y, max(1, int(bw * prog)), 6))
        pygame.draw.rect(w, (70, 110, 105), (bx, y, bw, 6), 1)
        names = {'WEATHER': '气象室', 'LAB': '实验室', 'BALCONY': '气闸',
                 'SERVER': '服务器', 'CONSOLE': '主控台', 'GREEN': '温室'}
        legs = (s.quest or {}).get('legs') or []
        leg = (s.quest or {}).get('leg', 0)
        dest = names.get(legs[leg][0], '') if leg < len(legs) else ''
        self.pill(s.px, y - 20, f'科考 · {dest}', 9, (160, 235, 210),
                  bg=(10, 20, 18), pad=5)

    def draw_rice_pot(self, x, y):
        """一口正在煮大白饭的小电饭锅（摸鱼证据）。"""
        w = self.world
        tt = pygame.time.get_ticks()
        pygame.draw.ellipse(w, (0, 0, 0, 46), (x - 12, y - 3, 24, 6))
        body = pygame.Rect(x - 12, y - 16, 24, 15)
        pygame.draw.rect(w, (228, 226, 214), body, border_radius=4)
        pygame.draw.rect(w, (150, 148, 140), body, 1, border_radius=4)
        # 米饭
        pygame.draw.rect(w, (254, 253, 248), (x - 9, y - 16, 18, 5), border_radius=2)
        # 半掀的锅盖
        pygame.draw.rect(w, (198, 196, 186), (x - 12, y - 21, 19, 4), border_radius=2)
        pygame.draw.rect(w, (146, 144, 136), (x - 12, y - 21, 19, 4), 1, border_radius=2)
        # 指示灯
        lit = (tt // 420) % 2 == 0
        pygame.draw.rect(w, (255, 120, 88) if lit else (150, 92, 82), (x + 5, y - 12, 4, 3))
        # 蒸汽
        for i in range(3):
            ph = ((tt / 900.0) + i * 0.33) % 1.0
            sy = y - 23 - ph * 20
            a = int(180 * (1 - ph))
            r = 2 + int(2.5 * ph)
            srf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(srf, (250, 250, 246, a), (r + 1, r + 1), r)
            w.blit(srf, (x - 6 + i * 5 - r, int(sy) - r))

    def draw_gear_shop(self):
        if GEAR_SHOP_RECT.w <= 0:
            return
        """公寓右下角的装备店（俯视小屋，点它开门）。"""
        w = self.world
        r = GEAR_SHOP_RECT
        hov = r.collidepoint(self.mouse[0], self.mouse[1]) if self.zoom <= 1.001 else False
        # 地板
        pygame.draw.rect(w, (40, 36, 48), r)
        pygame.draw.rect(w, (86, 74, 58), r, 2)
        # 上墙 + 条纹屋檐
        wall = pygame.Rect(r.x, r.y, r.w, 30)
        pygame.draw.rect(w, (58, 48, 64), wall)
        for i in range(0, r.w, 12):
            pygame.draw.rect(w, (76, 64, 84) if (i // 12) % 2 == 0 else (64, 54, 72),
                             (r.x + i, r.y, 12, 6))
        # 柜台
        pygame.draw.rect(w, (112, 88, 64), (r.x + 10, r.y + 38, r.w - 20, 14))
        pygame.draw.rect(w, (144, 116, 84), (r.x + 10, r.y + 38, r.w - 20, 3))
        # 货架 + 三件商品
        for i, gid in enumerate(('cpu', 'fan', 'net')):
            draw_gear_icon(w, gid, r.x + 14 + i * 44, r.y + 60, 34)
        # 门口的地垫
        pygame.draw.rect(w, (72, 58, 52), (r.x + 40, r.bottom - 12, r.w - 80, 8))
        # 招牌
        col = (255, 232, 170) if hov else (236, 206, 130)
        self.pill(r.centerx, r.y - 26, '装备店', 12, col, bg=(26, 22, 18), pad=7)
        if hov:
            pygame.draw.rect(w, (236, 206, 130), r, 2)

    def draw_shop_sign(self):
        """早餐铺门口的小招牌：只在 07:00~09:00 营业（科考站没有早餐铺）。"""
        if self.scene == 'station':
            return
        x = SHOP_RECT.centerx
        y = SHOP_RECT.bottom + 6
        hours = f'早点 {BREAKFAST_FROM:02d}:00-{BREAKFAST_TO:02d}:00'
        if self.breakfast_open():
            self.pill(x, y, f'{hours} · 营业中', 9, (255, 214, 152),
                      bg=(28, 20, 12), pad=5)
        else:
            self.pill(x, y, f'{hours} · 收摊了', 9, (152, 138, 126),
                      bg=(20, 17, 14), pad=5)

    def draw_fridge(self):
        """厨房那台冰箱：冷气 + 库存小牌，点它给 AI 发零食。"""
        w = self.world
        rect = FRIDGE_RECT
        tt = pygame.time.get_ticks()
        a = 12 + int(7 * math.sin(tt / 700))
        on = self.snacks > 0
        srf = pygame.Surface((rect.w + 24, rect.h + 18), pygame.SRCALPHA)
        pygame.draw.rect(srf, (150, 232, 226, a if on else a // 2), srf.get_rect(),
                         border_radius=8)
        w.blit(srf, (rect.x - 12, rect.y - 5))
        col = (150, 226, 210) if on else (96, 108, 118)
        pygame.draw.rect(w, col, rect, 1, border_radius=3)
        self.pill(rect.centerx, rect.bottom + 2, f'冰箱 {self.snacks}份', 9, col,
                  bg=(9, 14, 16), pad=5)


    def draw_beams(self):
        for s in self.stations:
            for job in s.jobs():
                self.draw_beam_to(s)

    def draw_beam_to(self, s):
        """从客厅服务器拉一条光缆到这条线（有两单时画两条）。"""
        ax, ay = SERVER[0], SERVER[1]
        bx, by = s.px, s.feet - 30
        accent = s.m['color']
        steps = 28
        bright = _brighten(accent, 1.7)
        prev = None
        for i in range(steps + 1):
            u = i / steps
            x = ax + (bx - ax) * u
            y = ay + (by - ay) * u - math.sin(u * math.pi) * 22
            a = int(42 + 96 * math.sin(u * math.pi))
            pygame.draw.circle(self.fx, (*accent, a // 3), (int(x), int(y)), 3)
            if prev:
                pygame.draw.line(self.fx, (*accent, a), prev, (x, y), 3)
                pygame.draw.line(self.fx, (*bright, min(255, a + 30)), prev, (x, y), 1)
            prev = (x, y)
        u = (pygame.time.get_ticks() / 800) % 1.0
        x = ax + (bx - ax) * u
        y = ay + (by - ay) * u - math.sin(u * math.pi) * 22
        pygame.draw.circle(self.fx, (*accent, 235), (int(x), int(y)), 2)

    def draw_task(self, t):
        """任务 = 悬浮的数据包，不是人。"""
        w = self.world
        info = TYPES[t.typ]
        col = info['color']
        bob = math.sin(t.bob) * 3 if t.state in ('queue', 'in') else 0
        x, y = int(t.x), int(t.y + bob)

        alpha = 1.0
        body = tuple(int(c * alpha) for c in (18, 21, 34))
        edge = tuple(int(c * alpha) for c in col)

        # 地面影子
        pygame.draw.ellipse(w, (13, 15, 24), (x - 8, int(t.y) + 7, 16, 5))
        # 悬浮光柱
        if t.state != 'out':
            pygame.draw.line(self.fx, (*col, 30), (x, y + 6), (x, int(t.y) + 8), 1)

        s_ = 20
        box = pygame.Rect(x - s_ // 2, y - s_ // 2 - 4, s_, s_)
        pygame.draw.rect(w, body, box)
        glow = pygame.Surface((s_, s_), pygame.SRCALPHA)
        pygame.draw.rect(glow, (*col, int(74 * alpha)), glow.get_rect(), border_radius=4)
        w.blit(glow, box.topleft)
        pygame.draw.rect(w, edge, box, 1, border_radius=4)

        # 四角提亮，像一颗在发光的数据块
        for cx_, cy_ in ((box.x, box.y), (box.right - 3, box.y),
                         (box.x, box.bottom - 3), (box.right - 3, box.bottom - 3)):
            pygame.draw.rect(w, edge, (cx_, cy_, 3, 1))
            pygame.draw.rect(w, edge, (cx_, cy_, 1, 3))

        # 需求符号 / 报价（直接画进 world，跟着镜头一起缩放）
        lab = font(7, True).render(info['sym'], True, _brighten(col))
        w.blit(lab, (x - lab.get_width() // 2, y - 12))
        lab2 = font(7, True).render(f'¥{t.budget:.0f}', True,
                                    (int(198 * alpha), int(206 * alpha), int(226 * alpha)))
        w.blit(lab2, (x - lab2.get_width() // 2, y + 7))
        # 耐心条
        if t.state in ('in', 'queue'):
            m = t.mood()
            c2 = C_GREEN if m > 0.55 else (C_GOLD if m > 0.3 else C_RED)
            pygame.draw.rect(w, (34, 28, 34), (x - 9, y - 18, 18, 2))
            pygame.draw.rect(w, c2, (x - 9, y - 18, max(1, int(18 * m)), 2))
        elif t.state == 'service':
            # 处理中：数据块外圈脉冲
            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 140)
            pygame.draw.rect(w, edge, box.inflate(4, 4),
                             max(0, int(pulse * 2)), border_radius=5)

    # ---------------------------------------------------- HUD
    def pane_buttons(self):
        """右侧信息栏上可点的按钮。"""
        x = PANE_X + 16
        return [
            ('price_down', pygame.Rect(x + 218, 200, 32, 26)),
            ('price_up', pygame.Rect(x + 254, 200, 32, 26)),
            ('speed', pygame.Rect(x + 148, 232, 140, 28)),
            ('pause', pygame.Rect(x, 232, 140, 28)),
            ('ad', pygame.Rect(x, 266, 140, 28)),
            ('intake', pygame.Rect(x + 148, 266, 140, 28)),
            ('bag', pygame.Rect(x, 656, 288, 26)),
            ('settings', pygame.Rect(x + 244, 10, 44, 22)),
            ('guide', pygame.Rect(x + 190, 10, 50, 22)),
            ('ach', pygame.Rect(x + 136, 10, 50, 22)),
        ]

    MAIN = [
        ('开张', '解锁第 3 条线路', 300, 0.5),
        ('换脑', '把 DeepSeek 升级成大模型', 500, 1.0),
        ('再换脑', '把 GPT 升级成大模型', 800, 1.0),
        ('凑齐队伍', '解锁全部线路', 1200, 2.0),
        ('搬家', '攒够 ¥5000 搬迁费', 0, 0.0),
        ('南极第一课', '在科考站完成一次气象 2/2', 800, 1.5),
        ('三十天', '撑到第 30 天', 0, 0.0),
    ]

    def main_done(self, step):
        if step == 0:
            return sum(1 for x in self.stations if x.unlocked) >= 3
        if step == 1:
            ds = self.station_by_id('DeepSeek')
            return bool(ds and ds.big)
        if step == 2:
            cg = self.station_by_id('ChatGPT')
            return bool(cg and cg.big)
        if step == 3:
            return all(x.unlocked for x in self.stations)
        if step == 4:
            return self.money >= RELOCATE_COST
        if step == 5:
            return (self.scene == 'station'
                    and sum(1 for w in self.weather if w == 3) >= 2)
        if step == 6:
            return self.day >= TOTAL_DAYS
        return True

    SOUTH = [
        ('安顿下来', '在南极完成 2 次气象任务', 600, 1.0),
        ('采样循环', '完成 3 次冰样任务', 900, 1.0),
        ('过冬', '在南极撑过 10 天', 1200, 2.0),
        ('全速运转', '在线线路全部是大模型或已升满', 1500, 2.0),
    ]

    def south_done(self, step):
        if step == 0:
            return self.south_weather >= 2
        if step == 1:
            return self.south_ice >= 3
        if step == 2:
            return self.south_days >= 10
        if step == 3:
            live = [x for x in self.stations if x.unlocked and x.subscribed]
            return bool(live) and all((x.big or not x.has_big()) for x in live)
        return True

    def update_south_quest(self):
        """南极阶段主线：只在科考站推进，绝不与公寓主线混。"""
        if self.scene != 'station' or self.rewards:
            return
        while self.south_step < len(self.SOUTH) and self.south_done(self.south_step):
            _, title, money, rep = self.SOUTH[self.south_step]
            self.south_step += 1
            if money or rep:
                self.rewards.append((title, money, rep))
            self.log(f'南极目标完成：{title} · 奖励待领取', C_GOLD)
            self.toast_msg(f'南极目标完成：{title} · 点「领取」', C_GOLD, 3.2)
            break

    EVENTS = {
        'blizzard': ('暴风雪', '取暖烧得更凶（燃料 +25%），持续 2 天'),
        'spike': ('上游涨价', '上游成本 +25%，持续 2 天'),
        'fault': ('设备故障', '一条线路被限流，2 天后自愈'),
    }

    def roll_event(self):
        """每 4 天左右掷一次随机事件（只在科考站）。"""
        if self.scene != 'station' or self.weather_ev:
            return
        if self.day < 3 or random.random() > 0.45:
            return
        kind = random.choice(list(self.EVENTS))
        self.weather_ev = (kind, self.day + 2)
        name, desc = self.EVENTS[kind]
        if kind == 'fault':
            live = [x for x in self.stations if x.unlocked and x.subscribed and not x.no_fatigue]
            if live:
                random.choice(live).limited = True
        self.log(f'突发：{name} · {desc}', (236, 170, 120))
        self.toast_msg(f'突发：{name} · {desc}', (236, 170, 120), 3.2)

    def event_kind(self):
        if not self.weather_ev:
            return None
        kind, until = self.weather_ev
        return kind if self.day <= until else None

    ACHIEVEMENTS = [
        ('first', '第一单', '完成 1 单', lambda g: sum(x.done for x in g.stations) >= 1),
        ('hundred', '百单', '累计完成 100 单', lambda g: sum(x.done for x in g.stations) >= 100),
        ('rich', '小富', '净资产 ≥ ¥20,000', lambda g: g.net_worth() >= 20000),
        ('rep90', '口碑', '声誉 ≥ 90', lambda g: g.rep >= 90),
        ('all_lines', '全员到齐', '10 条线路全部解锁', lambda g: all(x.unlocked for x in g.stations)),
        ('big', '大模型', 'DeepSeek 与 GPT 都是大模型',
         lambda g: bool(g.station_by_id('DeepSeek') and g.station_by_id('DeepSeek').big
                        and g.station_by_id('ChatGPT') and g.station_by_id('ChatGPT').big)),
        ('south', '南极', '搬进南极科考站', lambda g: g.scene == 'station'),
        ('weather2', '气象站', '南极累计完成 2 次气象', lambda g: g.south_weather >= 2),
        ('ice3', '冰芯', '南极累计完成 3 次冰样', lambda g: g.south_ice >= 3),
        ('winter', '越冬', '在南极撑过 10 天', lambda g: g.south_days >= 10),
    ]

    def achievements(self):
        return [(aid, name, desc, bool(fn(self))) for aid, name, desc, fn in self.ACHIEVEMENTS]

    def check_achievements(self):
        for aid, name, desc, ok in self.achievements():
            if ok and aid not in self.ach_seen:
                self.ach_seen.add(aid)
                self.log(f'成就解锁：{name} —— {desc}', (250, 214, 140))
                self.toast_msg(f'成就解锁 · {name}', (250, 214, 140), 2.8)

    def draw_achievements_panel(self, data=None):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 185))
        r = pygame.Rect(200, 90, 700, 540)
        alpha_rect(s, r, (20, 22, 30, 248), 10)
        pygame.draw.rect(s, (214, 186, 120), r, 2, border_radius=10)
        rows = self.achievements()
        got = sum(1 for *_, ok in rows if ok)
        txt(s, '成就墙', r.centerx, r.y + 20, 22, (246, 222, 156), 'midtop', bold=True)
        txt(s, f'{got} / {len(rows)}', r.centerx, r.y + 50, 12, (170, 160, 140), 'midtop')
        y = r.y + 84
        for aid, name, desc, ok in rows:
            col = (240, 214, 150) if ok else (110, 116, 132)
            txt(s, ('★ ' if ok else '☆ ') + name, r.x + 40, y, 15, col, bold=True)
            txt(s, desc, r.x + 210, y + 2, 12,
                (190, 190, 200) if ok else (110, 114, 126))
            y += 40
        txt(s, '点任意位置关闭', r.centerx, r.bottom - 30, 11, (140, 130, 150), 'midtop')
        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

    def south_goal_text(self):
        if self.south_step >= len(self.SOUTH):
            return '南极阶段目标全部完成'
        _, title, money, _ = self.SOUTH[self.south_step]
        return title + (f'（奖励 ¥{money}）' if money else '')

    def update_main_quest(self):
        if self.rewards:                  # 还有没领的奖励：先别推进下一条
            return
        while self.main_step < len(self.MAIN) and self.main_done(self.main_step):
            name, title, money, rep = self.MAIN[self.main_step]
            self.main_step += 1
            if money or rep:
                self.rewards.append((title, money, rep))
            self.log(f'主线完成：{title} · 奖励待领取', C_GOLD)
            self.toast_msg(f'主线完成：{title} · 记得点「领取」', C_GOLD, 3.2)
            break                       # 一次只推进一步，领完再出下一条

    def claim_rewards(self):
        if not self.rewards:
            return False
        got = 0
        for title, money, rep in self.rewards:
            self.money += money
            self.rep = min(100.0, self.rep + rep)
            got += money
        n = len(self.rewards)
        self.rewards = []
        self.log(f'领取主线奖励：{n} 项 · ¥{got}', C_GOLD)
        self.toast_msg(f'领取 {n} 项主线奖励 · +¥{got}', C_GOLD, 2.8)
        return True

    def reward_btn(self):
        return pygame.Rect(184, 44, 82, 21)

    def main_goal_text(self):
        if self.main_step >= len(self.MAIN):
            return '主线全部完成 · 冲高利润吧'
        name, title, money, rep = self.MAIN[self.main_step]
        return title + (f'（奖励 ¥{money}）' if money else '')

    def build_daily_goals(self):
        """每天 2~3 个小目标。"""
        if self.scene == 'station':
            self.daily_goals = [
                ('交 4 单', lambda: self.t_orders >= 4),
                ('不跳闸', lambda: self.t_trips == 0),
                ('三餐齐全', lambda: self.meals_today >= 3),
                ('气象 2/2', lambda: sum(1 for w in self.weather if w == 3) >= 2),
            ]
        else:
            self.daily_goals = [
                ('交 6 单', lambda: self.t_orders >= 6),
                ('零超时', lambda: self.t_expired == 0),
                ('零跳闸', lambda: self.t_trips == 0),
            ]
        self.goals_done = 0

    def check_daily_goals(self):
        done = sum(1 for _, fn in self.daily_goals if fn())
        if done > self.goals_done:
            self.goals_done = done
            if done == len(self.daily_goals) and self.daily_goals:
                self.money += 200
                self.rep = min(100.0, self.rep + 1.0)
                self.toast_msg('今日目标全达成 · +¥200', C_GOLD, 3.0)
                self.log('今天的每日目标全达成了 · +¥200 · 声誉 +1', C_GOLD)

    def next_unlock(self):
        for st in self.stations:
            if not st.unlocked:
                return st, st.m.get('unlock', 0)
        return None, 0

    def current_goal(self):
        """给玩家一条当前该干什么的指引。"""
        if self.scene == 'station':
            return '南极目标：' + self.south_goal_text()
        return '主线：' + self.main_goal_text()

    def _old_goal_unused(self):
        if self.scene == 'station':
            wd = sum(1 for w in self.weather if w == 3)
            if wd < 2:
                return f'完成气象 {wd}/2：主控屏点「气象采集」，再点一个人'
            if self.ice_done != self.day:
                return '跑一趟冰样：主控屏点「冰样任务」，再点一个人'
            if getattr(self, 'green_day', -1) != self.day:
                return '安排温室：主控屏点「温室照料」，派千问'
            if self.fuel < self.fuel_burn() * 2:
                return '燃料不够两天了：主控屏订燃料（随补给到）'
            return '把大单派起来，攒钱撑到第 30 天'
        unlocked = [x for x in self.stations if x.unlocked]
        if len(unlocked) < 3:
            return '解锁第 3 条线路（点右下角工位 / 工位面板）'
        if not self.big_ready():
            return '把 DeepSeek 和 GPT 升级成大模型（工位面板）'
        if not all(x.unlocked for x in self.stations):
            return '解锁剩下的线路，凑齐搬站条件'
        if self.money < RELOCATE_COST:
            return f'攒搬迁费 ¥{RELOCATE_COST:,}（现在 ¥{self.money:,.0f}）'
        return '可以搬去南极科考站了：点右栏的搬迁入口'

    def draw_world_goal(self):
        """左上角：主线目标 + 领取奖励。"""
        w = self.screen
        box = pygame.Rect(6, 6, 262, 72)
        alpha_rect(w, box, (10, 14, 22, 200), 6)
        pygame.draw.rect(w, (90, 140, 170), box, 1, border_radius=6)
        txt(w, '主线目标', box.x + 10, box.y + 5, 9, (140, 180, 200))
        txt(w, self.main_goal_text(), box.x + 10, box.y + 18, 11,
            (200, 226, 236), bold=True)
        rb = self.reward_btn()
        if self.rewards:
            hov = rb.collidepoint(self.mouse)
            alpha_rect(w, rb, (72, 60, 28) if hov else (44, 36, 18), 5)
            pygame.draw.rect(w, C_GOLD, rb, 2, border_radius=5)
            got = sum(m for _, m, _ in self.rewards)
            txt(w, f'领取 +¥{got}', rb.centerx, rb.centery, 11,
                (252, 232, 172), 'center', bold=True)
        else:
            txt(w, f'今日目标 {self.goals_done}/{len(self.daily_goals)}',
                box.right - 10, box.y + 5, 9, (140, 170, 190), 'topright')

    def draw_hud(self):
        s = self.screen
        P = PANE_X
        pygame.draw.rect(s, (13, 14, 21), (P, 0, SW - P, SH))
        pygame.draw.line(s, (48, 52, 72), (P, 0), (P, SH), 2)
        x = P + 16
        R = x + 288                      # 右边界

        # --- 天数 / 时间 ---
        txt(s, f'第 {self.day:02d}', x, 10, 20, C_TEXT, bold=True)
        txt(s, f'/ {TOTAL_DAYS} 天', x + 62, 18, 11, C_DIM)
        txt(s, self.clock_text(), x, 34, 28, C_BLUE, bold=True)

        night = self.is_night()
        tag = '夜班 · 额度半价' if night else ('已暂停' if self.paused else
                                          ('爆单中' if self.burst > 0 else '营业中'))
        tag_c = (C_PURPLE if night else
                 (C_DIM if self.paused else (C_GOLD if self.burst > 0 else C_DIM)))
        txt(s, tag, x + 96, 46, 12, tag_c)
        if self.rest_left > 0:
            txt(s, f'休息中 · 还剩 {self.rest_left:.1f} 小时', x, 62, 11,
                (170, 226, 190), bold=True)

        # 成就
        ab = dict(self.pane_buttons())['ach']
        hov_ab = ab.collidepoint(self.mouse)
        alpha_rect(s, ab, (38, 42, 60) if hov_ab else (24, 28, 42), 4)
        pygame.draw.rect(s, (110, 126, 168) if hov_ab else (70, 80, 110), ab, 1, border_radius=4)
        txt(s, '成就', ab.centerx, ab.y + 3, 11, (200, 200, 220) if hov_ab else (176, 186, 208), 'midtop')

        # 指南
        gb = dict(self.pane_buttons())['guide']
        hov_gb = gb.collidepoint(self.mouse)
        alpha_rect(s, gb, (38, 42, 60) if hov_gb else (24, 28, 42), 4)
        pygame.draw.rect(s, (110, 126, 168) if hov_gb else (70, 80, 110), gb, 1,
                         border_radius=4)
        txt(s, '指南', gb.centerx, gb.y + 3, 11,
            C_TEXT if hov_gb else (176, 186, 208), 'midtop')

        # 设置（点开时整局暂停）
        sb = dict(self.pane_buttons())['settings']
        hov_sb = sb.collidepoint(self.mouse)
        alpha_rect(s, sb, (38, 42, 60) if hov_sb else (24, 28, 42), 4)
        pygame.draw.rect(s, (110, 126, 168) if hov_sb else (70, 80, 110), sb, 1,
                         border_radius=4)
        txt(s, '设置', sb.centerx, sb.y + 3, 11,
            C_TEXT if hov_sb else (176, 186, 208), 'midtop')

        bar = pygame.Rect(x, 66, 288, 7)
        pygame.draw.rect(s, (36, 40, 60), bar)
        pygame.draw.rect(s, (96, 150, 230),
                         (bar.x, bar.y, int(bar.w * min(1, self.t / DAY_LEN)), bar.h))
        # 24:00 的结算刻度
        mx = bar.x + int(bar.w * (self.settle_point() / DAY_LEN))
        pygame.draw.line(s, C_GOLD, (mx, bar.y - 2), (mx, bar.bottom + 2), 2)
        txt(s, '08:00', x, 76, 9, (86, 94, 118))
        txt(s, '24:00', mx, 76, 9, (188, 166, 108), 'midtop')
        txt(s, '08:00', R, 76, 9, (86, 94, 118), 'topright')

        # --- 资金 / 营收 / 声誉 ---
        pygame.draw.line(s, (40, 44, 62), (x, 96), (R, 96))
        txt(s, '资金', x, 102, 11, C_DIM)
        txt(s, f'¥{self.money:,.0f}', x, 114, 28,
            C_GOLD if self.money >= 0 else C_RED, bold=True)

        txt(s, '今日营收', x, 152, 11, C_DIM)
        txt(s, f'+¥{self.t_rev:,.0f}', x + 56, 149, 14, C_GREEN)
        live = self.t_rev - self.t_cost
        txt(s, '毛利', x + 178, 152, 11, C_DIM)
        txt(s, f'{live:+,.0f}', x + 208, 149, 14, C_GREEN if live >= 0 else C_RED)

        txt(s, '声誉', x, 176, 11, C_DIM)
        rr = pygame.Rect(x + 34, 180, 218, 6)
        pygame.draw.rect(s, (36, 40, 60), rr)
        pygame.draw.rect(s, C_PURPLE, (rr.x, rr.y, int(rr.w * self.rep / 100), rr.h))
        txt(s, f'{self.rep:.0f}', R, 172, 13, C_PURPLE, 'topright', bold=True)
        # 用户满意度（近 12 单的平均星级）：影响每一单的收入和声誉涨跌
        if self.last_stars:
            avg = sum(self.last_stars) / len(self.last_stars)
            stars = max(1, min(5, int(round(avg))))
            txt(s, f'满意度 {"★" * stars}{"☆" * (5 - stars)} {avg:.1f}（近 {len(self.last_stars)} 单）',
                x, 188, 9, (206, 190, 132))

        # --- 定价 / 速度 ---
        pygame.draw.line(s, (40, 44, 62), (x, 198), (R, 198))
        txt(s, '定价', x, 206, 11, C_DIM)
        txt(s, f'×{self.price_mult:.2f}', x + 38, 201, 18, C_GOLD, bold=True)
        iv = self.spawn_interval()
        est = (REV_BASE + 3 * REV_PER_STAR) * 1.1 * self.price_mult * 0.85
        txt(s, f'{iv:.0f}秒/单 · 均单 ¥{est:.0f}', x + 104, 207, 9, (110, 130, 152))

        mx_, my_ = self.mouse
        for (key, r), label in zip(self.pane_buttons()[:4],
                                   ('-', '+', f'{self.speed}x 速度',
                                    '继续' if self.paused else '暂停')):
            hov = r.collidepoint(mx_, my_)
            alpha_rect(s, r, (34, 40, 58) if hov else (26, 30, 44), 4)
            pygame.draw.rect(s, (86, 108, 154) if hov else (58, 66, 92), r, 1,
                             border_radius=4)
            txt(s, label, r.centerx, r.centery, 14 if key == 'speed' else 15,
                C_TEXT if hov else (188, 196, 216), 'center', bold=(key != 'speed'))

        # --- 广告 / 暂停接单 ---
        ba = self.pane_buttons()[4][1]
        hov = ba.collidepoint(mx_, my_)
        ad_on = self.ad_days > 0
        alpha_rect(s, ba, (46, 38, 26) if hov else (32, 28, 22), 5)
        pygame.draw.rect(s, (232, 190, 120) if not ad_on else (120, 150, 130),
                         ba, 1, border_radius=5)
        if ad_on:
            txt(s, f'广告中 · 剩 {self.ad_days} 天', ba.centerx, ba.y + 7, 13,
                (150, 220, 180), 'midtop', bold=True)
        else:
            txt(s, f'投广告 ¥{AD_COST}', ba.centerx, ba.y + 7, 13,
                (240, 206, 150), 'midtop', bold=True)

        bi = self.pane_buttons()[5][1]
        hov = bi.collidepoint(mx_, my_)
        if self.intake:
            alpha_rect(s, bi, (32, 40, 34) if hov else (24, 30, 26), 5)
            pygame.draw.rect(s, (128, 190, 150), bi, 1, border_radius=5)
            txt(s, '接单中·点停', bi.centerx, bi.y + 7, 13, (170, 226, 190),
                'midtop', bold=True)
        else:
            alpha_rect(s, bi, (54, 34, 34) if hov else (38, 26, 26), 5)
            pygame.draw.rect(s, (232, 130, 126), bi, 1, border_radius=5)
            txt(s, '已停接·恢复', bi.centerx, bi.y + 7, 13, (255, 168, 160),
                'midtop', bold=True)

        # --- 背包：买到的道具都在这里，拖到 AI 身上用 ---
        bb = self.pane_buttons()[6][1]
        hov = bb.collidepoint(mx_, my_)
        n_bag = self.bag_total()
        alpha_rect(s, bb, (40, 44, 62) if hov else (26, 30, 44), 5)
        pygame.draw.rect(s, (140, 168, 220) if hov else (86, 104, 146), bb, 1, border_radius=5)
        txt(s, '背包', bb.x + 16, bb.y + 6, 13, C_TEXT, 'topleft', bold=True)
        txt(s, f'{n_bag} 件道具 · 拖到 AI 身上用' if n_bag else '空格子 · 去装备店买',
            bb.x + 68, bb.y + 7, 11,
            (170, 200, 244) if n_bag else (110, 120, 146))



        # --- 每日结算 ---
        pygame.draw.line(s, (40, 44, 62), (x, 302), (R, 302))
        rent, power, wage, subs, port = self.daily_fixed()
        left = self.rent_left()
        txt(s, '每日结算', x, 308, 12, (150, 158, 184), bold=True)
        if self.last_day:
            ln = self.last_day['net']
            txt(s, f'昨日 {ln:+,.0f}', R, 308, 11,
                C_GREEN if ln >= 0 else C_RED, 'topright')
        else:
            txt(s, '24:00 自动结算', R, 308, 10, (96, 104, 128), 'topright')

        fixed = rent + power + wage + subs
        net_live = self.t_rev - self.t_cost - fixed
        soon = self.sub_soon()
        srows = [
            ('营业收入', f'+{self.t_rev:,.0f}', C_GREEN),
            ('上游成本', f'-{self.t_cost:,.0f}', (214, 138, 134)),
            ('订阅 · 7天预付', f'{soon} 天后到期' if soon else '没有在跑的订阅',
             (110, 118, 142) if soon > 1 else ((236, 170, 130) if soon else (110, 118, 142))),
            ('电费 · 工资 · 端口', f'-{power + wage + port:,.0f}', (214, 138, 134)),
            ('公寓房租', f'-{rent:,.0f}' if rent else '今天免',
             (214, 138, 134) if rent else (110, 118, 142)),
        ]
        for i, (k, v, c) in enumerate(srows):
            yy = 324 + i * 15
            txt(s, k, x, yy, 11, (132, 140, 166))
            txt(s, v, R, yy, 11, c, 'topright')
        pygame.draw.line(s, (40, 44, 62), (x, 404), (R, 404))
        txt(s, '净利', x, 406, 12, (150, 158, 184))
        txt(s, f'{net_live:+,.0f}', R, 402, 19,
            C_GOLD if net_live >= 0 else C_RED, 'topright', bold=True)
        txt(s, f'{self.t_orders} 单 · 超时 {self.t_expired} · 过热 {self.t_crashes}'
               f' · 断额 {self.t_quota_break}',
            x, 428, 10, (104, 112, 138))

        # --- 站况 ---
        pygame.draw.line(s, (40, 44, 62), (x, 444), (R, 444))
        busy_n = self.grid_load()
        cap = self.breaker_cap()
        rows = [
            ('待处理任务', f'{len(self.queued_tasks())} / {len(TASK_SLOTS)}', C_TEXT),
            ('线路 · 用电', f'{len(self.unlocked())} / {len(self.stations)} · {busy_n}/{cap}',
             C_RED if busy_n > cap else C_TEXT),
            ('供暖燃料' if self.scene == 'station' else '房租 / 零食',
             (f'{int(self.fuel)} 单位 · 每天 {self.fuel_burn():.0f} · 饭 {self.meals_today}/3'
              if self.scene == 'station' else
              (f'今天¥{RENT_WEEK}' if left == 0 else f'{left}天¥{RENT_WEEK}')
              + f' · {self.snacks}份'),
             (C_RED if self.cold else C_GOLD) if self.scene == 'station' else
             (C_GOLD if left == 0 else (150, 158, 186))),
        ]
        for i, (k, v, col) in enumerate(rows):
            yy = 450 + i * 18
            txt(s, k, x, yy, 11, (132, 140, 166))
            txt(s, v, R, yy, 11, col, 'topright', bold=True)
        if busy_n > cap and self.tripped <= 0:
            txt(s, f'过载 {self.overload_t:.1f}/9s', R, 450 + 2 * 18, 11, C_RED,
                'topright', bold=True)

        # 事件（一行）
        y2 = 508
        if self.event:
            e = self.event
            col = C_GOLD if e['kind'] == 'burst' else (
                C_RED if e['kind'] in ('throttle', 'crash', 'pricehike') else C_GREEN)
            txt(s, e['name'], x, y2, 12, col, bold=True)
            txt(s, e['desc'], x, y2 + 14, 10, (160, 168, 190))
        elif self.contract:
            c = self.contract
            txt(s, f'长期合同 · {TYPES[c["typ"]]["name"]} {c["today"]}/{c["need"]} 单',
                x, y2, 12, (150, 220, 210), bold=True)
            txt(s, f'还剩 {c["left"]} 天 · 完成奖 ¥{c["reward"]}', x, y2 + 14, 10,
                (140, 160, 180))
        elif (self.scene == 'apartment' and self.money >= RELOCATE_COST
              and not self.big_ready()):
            txt(s, '想搬去南极：先把 DeepSeek 和 GPT 升到大模型', x, y2, 11,
                (150, 200, 230), bold=True)
            txt(s, '（工位面板里一次性升级）', x, y2 + 14, 10, (120, 150, 180))
        elif self.cold and self.scene == 'station':
            txt(s, '站内偏冷 · 全部线路 -40%', x, y2, 12, C_RED, bold=True)
            txt(s, '去发电舱买燃料', x, y2 + 14, 10, (200, 150, 140))
        elif self.scene == 'station':
            wd = sum(1 for w in self.weather if w == 3)
            if self.ice:
                ice_txt = f'进行中 {self.ice_runs}/2'
            else:
                ice_txt = f'{min(2, self.ice_runs)}/2'
            txt(s, f'气象 {wd}/2 · 冰样 {ice_txt}', x, y2, 12, (150, 205, 225), bold=True)
            txt(s, '目标：' + self.current_goal(), x, y2 + 14, 10, (150, 180, 190))
            txt(s, f'今日目标 {self.goals_done}/{len(self.daily_goals)}',
                x + 288, y2 + 14, 9, (150, 180, 190), 'topright')
        else:
            txt(s, '当前目标', x, y2 - 2, 9, (120, 150, 170))
            txt(s, self.current_goal(), x, y2 + 12, 12, (190, 214, 226), bold=True)
            if self.daily_goals:
                txt(s, f'今日目标 {self.goals_done}/{len(self.daily_goals)}',
                    x + 288, y2 - 2, 9, (150, 180, 190), 'topright')

        # --- 日志 ---
        pygame.draw.line(s, (40, 44, 62), (x, 542), (R, 542))
        txt(s, '日志', x, 546, 11, (110, 118, 142))
        for i, (line, col) in enumerate(self.logs[-6:]):
            txt(s, line, x, 562 + i * 16, 10, col)
        txt(s, f'滚轮缩放 ×{self.zoom:.2f} · 右键拖动看房间 · 点服务器接单 · S 存档',
            x, 690, 9, (86, 96, 120))
        txt(s, f'BUILD {BUILD}', R, 708, 9, (58, 64, 84), 'topright')

    def draw_log(self):
        pass


    def draw_pause(self):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, WW, SH), (6, 7, 12, 132))
        txt(s, '已暂停', WW // 2, SH // 2 - 20, 34, C_TEXT, 'midtop', bold=True)
        txt(s, '按空格继续', WW // 2, SH // 2 + 30, 16, C_DIM, 'midtop')

    def toast_rect(self, text):
        """提示条的位置和宽度：按文字实际宽度撑开，背包开着就浮在它上面。"""
        w = max(200, min(WW - 24, text_w(text, 15, True) + 36))
        h = 34
        if self.panel and self.panel[0] == 'bag':
            y = self.bag_panel_rect().top - h - 10
        elif self.panel:
            y = 4           # 面板开着时浮到顶部，别压住面板底部的按钮
        else:
            y = SH - 78
        return pygame.Rect(WW // 2 - w // 2, y, w, h)

    def draw_toast(self):
        if not self.toast:
            return
        text, life, col = self.toast
        a = min(1.0, life)
        r = self.toast_rect(text)
        r.y += int((1 - a) * 8)
        alpha_rect(self.screen, r, (10, 11, 17, int(238 * a)), 6)
        pygame.draw.rect(self.screen, col, r, 2, border_radius=6)
        txt(self.screen, text, r.centerx, r.y + 9, 15, col, 'midtop', bold=True)

    # ---------------------------------------------------- 面板
    def draw_panel(self):
        kind, data = self.panel
        if kind == 'server':
            self.draw_server_panel(data if isinstance(data, int) else 0)
        elif kind == 'station':
            self.draw_station_panel(data)
        elif kind == 'summary':
            self.draw_summary(data)
        elif kind == 'over':
            self.draw_over(data)
        elif kind == 'shop':
            self.draw_shop_panel()
        elif kind == 'fridge':
            self.draw_fridge_panel()
        elif kind == 'breaker':
            self.draw_breaker_panel()
        elif kind == 'gateway':
            self.draw_gateway_panel()
        elif kind == 'achieve':
            self.draw_achievements_panel(data)
        elif kind == 'stage':
            self.draw_stage_panel(data)
        elif kind == 'comic':
            self.draw_comic(data)
        elif kind == 'intro':
            self.draw_intro_panel(data)
        elif kind == 'storage':
            self.draw_storage_panel()
        elif kind == 'gear':
            self.draw_gear_panel()
        elif kind == 'bag':
            self.draw_bag_panel()
        elif kind == 'settings':
            self.draw_settings_panel(data)
        elif kind == 'relations':
            self.draw_relations_panel(data)
        elif kind == 'supply':
            self.draw_supply_panel(data)
        elif kind == 'relocate':
            self.draw_relocate_panel(data)
        elif kind == 'contract':
            self.draw_contract_panel(data)
        elif kind == 'notice':
            self.draw_notice(data)

    def draw_server_panel(self, sel):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 175))
        r = self.server_panel_rect()
        alpha_rect(s, r, (16, 18, 29, 248), 10)
        pygame.draw.rect(s, (84, 116, 172), r, 2, border_radius=10)

        q = self.queued_tasks()
        st_list = self.server_tasks()
        if self.quest_sel:
            sel = -1                      # 正在选科考任务，派单行不高亮
        elif st_list:
            sel = max(0, min(sel, len(st_list) - 1))
        else:
            sel = 0

        txt(s, '派单服务器', r.x + 26, r.y + 14, 22, C_TEXT, bold=True)
        ab = self.auto_btn()
        hov_a = ab.collidepoint(self.mouse)
        on = self.auto_dispatch
        alpha_rect(s, ab, (30, 54, 40) if on else ((38, 42, 56) if hov_a else (24, 28, 40)), 6)
        pygame.draw.rect(s, (140, 220, 170) if on else (80, 92, 120), ab, 2, border_radius=6)
        txt(s, '自动派单：开' if on else '自动派单：关', ab.centerx, ab.centery, 13,
            (190, 250, 200) if on else (186, 194, 216), 'center', bold=True)
        txt(s, f'待处理 {len(q)} 单　·　选任务 → 点人 → 接着派下一单（面板不关）',
            r.x + 152, r.y + 24, 12, (142, 152, 178))

        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (90, 104, 134), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

        # ---------------- 左：待处理任务 ----------------
        txt(s, '待处理任务（右上角 X 退回这条）', r.x + 26, r.y + 56, 12, (116, 126, 152))
        rows = self.task_rows()
        if not rows:
            txt(s, '网关暂时没单，喝口水。', r.x + 26, r.y + 110, 14, (108, 116, 138))
        mx, my = self.mouse
        for i, (t, rr) in enumerate(rows):
            info = TYPES[t.typ]
            on = (i == sel)
            hov = rr.collidepoint(mx, my)
            alpha_rect(s, rr, (34, 40, 58) if on else ((28, 32, 46) if hov else (22, 25, 36)),
                       6)
            running = t.state == 'service'
            pygame.draw.rect(s, (120, 220, 180) if running else
                             (info['color'] if on else (56, 62, 84)), rr,
                             2 if (on or running) else 1, border_radius=6)
            if running:
                txt(s, f'协作中 {len(t.crew)}/3', rr.right - 12, rr.y + 6, 9,
                    (150, 230, 200), 'topright', bold=True)
            # 类型色条
            pygame.draw.rect(s, info['color'], (rr.x, rr.y + 6, 4, rr.h - 12))
            txt(s, info['name'], rr.x + 12, rr.y + 6, 14, info['color'] if on else (196, 202, 220),
                bold=True)
            txt(s, f'{t.w:.0f} 工作量 · ¥{t.budget:.0f}',
                rr.x + 12, rr.y + 26, 10, (156, 164, 188))
            # 耐心
            m = t.mood()
            col = C_GREEN if m > 0.55 else (C_GOLD if m > 0.3 else C_RED)
            bar = pygame.Rect(rr.x + 12, rr.y + 50, 104, 5)
            pygame.draw.rect(s, (34, 30, 34), bar)
            pygame.draw.rect(s, col, (bar.x, bar.y, int(bar.w * m), bar.h))
            txt(s, fmt_wait(t), rr.right - 34, rr.y + 43, 10, col, 'topright')
            # 退回按钮
            db = self.task_del_btn(rr)
            dh = db.collidepoint(mx, my)
            alpha_rect(s, db, (62, 30, 32) if dh else (30, 24, 28), 4)
            pygame.draw.rect(s, (214, 132, 126) if dh else (86, 66, 68), db, 1, border_radius=4)
            txt(s, 'X', db.centerx, db.y + 3, 13, (250, 176, 168) if dh else (150, 122, 118),
                'midtop', bold=True)

        # ---------------- 右：八条线路 ----------------
        txt(s, '接给谁', r.x + 448, r.y + 56, 12, (116, 126, 152))
        if self.quest_sel:
            qname = next((x[1] for x in self.quest_actions()
                          if x[0] == self.quest_sel), '')
            txt(s, f'已选：{qname} · 点右边的人派出', r.x + 520, r.y + 56, 12,
                (170, 245, 220), bold=True)
        me = st_list[sel] if (0 <= sel < len(st_list)) else None
        for st, card in self.server_cards():
            self.draw_server_card(st, card, me, card.collidepoint(mx, my))

        # ---------------- 左下：科考任务（和派单一样派出去）
        if self.scene == 'station':
            wd = sum(1 for x in self.weather if x == 3)
            if self.ice:
                ice_txt = f'进行中 {self.ice_runs}/2'
            else:
                ice_txt = f'{min(2, self.ice_runs)}/2'
            gtxt = '已收' if getattr(self, 'green_day', -1) == self.day else '未做'
            txt(s, f'科考任务（今日：气象 {wd}/2 · 冰样 {ice_txt} · 温室 {gtxt}）',
                r.x + 26, r.y + 282, 10, (130, 180, 190))
            for key, name, ok, hint, b in self.quest_sel_rects():
                on = (self.quest_sel == key)
                hov = b.collidepoint(mx, my)
                bg = (46, 92, 84) if on else ((26, 40, 42) if hov and ok else (22, 27, 30))
                alpha_rect(s, b, bg, 5)
                pygame.draw.rect(s, (150, 245, 220) if on else
                                 ((86, 150, 140) if ok else (60, 64, 70)), b,
                                 2 if on else 1, border_radius=5)
                txt(s, ('✓ ' if on else '') + name, b.centerx, b.y + 6, 11,
                    (210, 255, 235) if on else
                    ((180, 245, 220) if ok else (110, 116, 126)), 'midtop', bold=True)
        # ---------------- 下一条线路预览
        nxt, ncost = self.next_unlock()
        if nxt is not None:
            txt(s, f'下一条线路：{nxt.m["name"]} · 解锁 ¥{ncost:,}',
                r.x + 26, r.y + 486, 12, (200, 214, 160), bold=True)
            txt(s, f'（攒够钱点它就能装进站里）', r.x + 26, r.y + 504, 10,
                (130, 140, 158))
        # ---------------- 左下：长期合同（签了就一直在）
        c = self.contract
        box = pygame.Rect(r.x + 26, r.y + 336, 400, 144)
        alpha_rect(s, box, (24, 22, 30, 210), 8)
        pygame.draw.rect(s, (150, 120, 140) if c else (58, 54, 68), box, 1, border_radius=8)
        txt(s, '长期合同', box.x + 14, box.y + 10, 13, (240, 202, 216), bold=True)
        if c:
            name = TYPES[c['typ']]['name']
            done = c['today']
            need = c['need']
            col = (150, 220, 180) if done >= need else (236, 200, 130)
            txt(s, f'{name} · 今天 {done}/{need} 单', box.x + 14, box.y + 36, 16, col,
                bold=True)
            txt(s, f'还剩 {c["left"]} 天 · 完成奖 ¥{c["reward"]} · 单价 +15%',
                box.x + 14, box.y + 62, 11, (160, 168, 190))
            txt(s, '交够就续一天；某天没交够，合同作废、声誉 -3',
                box.x + 14, box.y + 82, 10, (130, 136, 158))
        elif self.contract_offer:
            txt(s, '有一份报价等你确认（结算时弹出来的那个）', box.x + 14, box.y + 36,
                12, (236, 200, 130))
            txt(s, '关掉面板后在右栏事件区也能看到', box.x + 14, box.y + 58, 10,
                (130, 136, 158))
        else:
            txt(s, '还没有长期合同', box.x + 14, box.y + 36, 12, (150, 156, 178))
            txt(s, '同一类活累计交付 6 单、声誉 60 以上，打烊后会有人来谈',
                box.x + 14, box.y + 58, 10, (130, 136, 158))
            txt(s, '（每天 2 单 × 5 天，单价 +15%，完成奖 ¥600）',
                box.x + 14, box.y + 76, 10, (130, 136, 158))

        # 连续派单容易一口气排太多路：这里提前把电闸容量亮出来
        busy_n = self.grid_load()
        cap = self.breaker_cap()
        mid = r.x + 430 + (r.right - 26 - (r.x + 430)) // 2
        if busy_n > cap:
            txt(s, f'同时开工 {busy_n} 路 > 电闸 {cap} 路 · 撑 9 秒就跳闸',
                mid, r.bottom - 46, 12, C_RED, 'midtop', bold=True)
        elif busy_n == cap:
            txt(s, f'电闸已经带满（{busy_n}/{cap} 路），再派就要过载了',
                mid, r.bottom - 46, 11, C_GOLD, 'midtop')
        txt(s, '质量决定用户评价，评价决定这一单能收多少。',
            mid, r.bottom - 26, 12, (104, 112, 136), 'midtop')

    def draw_server_card(self, st, card, task, hover):
        s = self.screen
        ok = st.ready() and self.tripped <= 0
        if task is not None and task.multi and st.m['id'] not in task.crew:
            mates = [self.station_by_id(x) for x in task.crew]
            mates = [m for m in mates if m is not None]
            if any(self.bond(st, m) < 0.5 for m in mates):
                ok = False           # 关系不够，没法加入这单
        accent = st.m['color']
        bg = (24, 28, 42) if ok else (19, 21, 30)
        if hover and ok:
            bg = (32, 38, 56)
        alpha_rect(s, card, (*bg, 246), 8)
        pygame.draw.rect(s, accent if ok else (52, 56, 74), card,
                         2 if hover and ok else 1, border_radius=8)

        sid = self.assets.sprite_id(st)
        img = self.assets.model(sid)
        thumb = self.assets.scaled(img, 44)
        if thumb:
            s.blit(thumb, (card.x + 8, card.y + 8))
        else:
            pygame.draw.rect(s, (40, 44, 62), (card.x + 8, card.y + 8, 44, 44))

        name_col = accent if ok else (108, 112, 132)
        txt(s, st.m['name'], card.x + 58, card.y + 5, 15, name_col, bold=True)
        if task is not None and task.multi:
            if st.m['id'] in task.crew:
                tag, tcol = '协作中', (150, 230, 200)
            elif len(task.crew) >= 3:
                tag, tcol = '人满了', (236, 200, 130)
            else:
                mates = [self.station_by_id(x) for x in task.crew]
                mates = [m for m in mates if m is not None]
                if all(self.bond(st, m) >= 0.5 for m in mates):
                    tag, tcol = '可加入', (150, 220, 200)
                else:
                    tag, tcol = '关系不够', (214, 130, 130)
            txt(s, tag, card.right - 8, card.y + 40, 9, tcol, 'topright', bold=True)

        if st.subscribed:
            txt(s, f'{st.tier_name()} · ¥{st.tier_price()}/天',
                card.x + 58, card.y + 24, 10, (146, 152, 174))
        elif st.has_tiers():
            txt(s, '未订阅 · 3 档可选', card.x + 58, card.y + 24, 10, (112, 120, 142))
        else:
            txt(s, '固定配置', card.x + 58, card.y + 24, 10, (112, 120, 142))
        if st.m.get('rhythm'):
            night = self.is_night()
            txt(s, '夜班 130%' if night else '白班 60%',
                card.right - 48, card.y + 24, 9,
                C_PURPLE if night else (120, 124, 148))
        if not st.on_grid():
            txt(s, '不走电闸', card.right - 48, card.y + 24, 9, (140, 170, 150))

        if task is not None:
            match = task.typ in st.m['tags']
            if match:
                mr = pygame.Rect(card.right - 44, card.y + 6, 38, 13)
                alpha_rect(s, mr, (34, 60, 44, 255), 3)
                txt(s, '专长', mr.centerx, mr.y + 1, 8, C_GREEN, 'midtop')

            qv = st.quality(task.typ, task)
            dur = task.w / st.spd()
            stars = self.rate_est(qv, match)
            txt(s, fmt_sec_game(dur), card.x + 58, card.y + 42, 11, (176, 184, 204))
            txt(s, '★' * stars + '☆' * (5 - stars), card.x + 58, card.y + 62, 13,
                C_GOLD if stars >= 4 else ((196, 190, 150) if stars == 3 else (200, 130, 130)))
            if st.quota >= 0:
                qcost = self.quota_need(st, task.w)
                qcol = C_RED if st.quota < qcost else (150, 200, 170)
                txt(s, f'{int(st.quota)}/{st.quota_cap()}', card.right - 8, card.y + 62, 9,
                    qcol, 'topright')
        else:
            txt(s, '先选任务', card.x + 58, card.y + 48, 11, (104, 112, 136))

        if not st.unlocked:
            self.card_mask(card, f'解锁 ¥{st.m.get("unlock", 0)}')
        elif not st.subscribed:
            self.card_mask(card, '未订阅 · 点开选档' if st.has_tiers() else '未订阅')
        elif st.cooking > 0:
            self.card_mask(card, f'做饭中 {fmt_sec_game(st.cooking)}')
        elif st.needs_port():
            self.card_mask(card, '需要加密 VPN 端口' if st.m.get('need') == 'vpn_enc'
                           else '需要 VPN 端口')
        elif st.slack > 0:
            self.card_mask(card, f'煮饭摸鱼中 {fmt_sec_game(st.slack)}')
        elif not st.has_quota():
            self.card_mask(card, '今日额度用完')
        elif task is not None and st.blocked(task.typ):
            self.card_mask(card, '小模型做不了')
        elif task is not None and st.quota >= 0 and self.quota_need(st, task.w) > st.quota:
            pct = int(100 * st.quota / max(1, self.quota_need(st, task.w)))
            self.card_mask(card, f'额度只够 {pct}% · 会断')
        elif self.tripped > 0:
            self.card_mask(card, '停电中')
        elif st.stuck > 0:
            self.card_mask(card, f'宕机 {fmt_sec_game(st.stuck)}')
        elif st.jobs() and st.paused_job:
            j = st.main_job()
            self.card_mask(card, f'已暂停 {int(j.prog * 100)}%')
        elif st.jobs():
            f = max(0.1, st.work_factor())
            left = max([(1 - j.prog) * j.dur / f for j in st.jobs()])
            tail = ' · 限流中' if st.limited else ''
            two = ' ×2' if st.busy2 is not None else ''
            self.card_mask(card, f'忙碌 还剩 {fmt_sec_game(left)}{two}{tail}')

    def card_mask(self, card, label):
        alpha_rect(self.screen, card, (10, 11, 18, 118), 8)
        tag = pygame.Rect(card.x, card.bottom - 26, card.w, 22)
        txt(self.screen, label, tag.centerx, tag.y, 13, (196, 200, 218), 'midtop', bold=True)

    def draw_station_panel(self, st):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 170))
        r = self.station_panel_rect()
        alpha_rect(s, r, (18, 20, 32, 246), 10)
        pygame.draw.rect(s, st.m['color'], r, 2, border_radius=10)

        L = r.x + 28                 # 左栏
        LW = 300
        RX = r.x + 372               # 右栏
        RW = r.right - 28 - RX

        # ---------------- 头部：立绘 + 名字 + 状态 ----------------
        img = self.assets.model(self.assets.sprite_id(st))
        if img:
            s.blit(self.assets.scaled(img, 108), (L, r.y + 24))
        else:
            pygame.draw.rect(s, (40, 44, 62), (L, r.y + 24, 108, 108))

        tx = L + 128
        txt(s, st.m['name'], tx, r.y + 22, 26, st.m['color'], bold=True)
        txt(s, st.m['blurb'], tx, r.y + 56, 12, (150, 158, 180))
        if st.forever:
            txt(s, '免费永久 · 额度不限 · 不用订阅', tx, r.y + 76, 12, C_TEXT)
        elif st.subscribed:
            txt(s, f'{st.tier_name()}档 · 还剩 {st.sub_days} 天 · '
                   f'额度 {"不限" if st.quota_cap() < 0 else st.quota_cap()}',
                tx, r.y + 76, 12, C_TEXT)
        elif st.has_tiers():
            txt(s, '三档订阅可选 · 点下面选一档', tx, r.y + 76, 12, (128, 136, 160))
        else:
            txt(s, '免费线路', tx, r.y + 76, 12, (128, 136, 160))
        if st.m['tags']:
            tags = ' / '.join(TYPES[t]['name'] for t in st.m['tags'])
            txt(s, f'专长：{tags}', tx, r.y + 96, 12, (140, 168, 210))

        # 状态行
        if not st.unlocked:
            state, sc = '未解锁', (198, 160, 140)
        elif not st.subscribed:
            state, sc = '未订阅 · 不接单', (198, 160, 140)
        elif st.cooking > 0:
            state, sc = (f'做饭中 · 还剩 {fmt_sec_game(st.cooking)}（不接单）',
                         (240, 200, 140))
        elif st.needs_port():
            need_enc = st.m.get('need') == 'vpn_enc'
            state, sc = ('没装加密 VPN 端口 · 接不了单' if need_enc
                         else '没装 VPN 端口 · 接不了单'), C_RED
        elif st.slack > 0:
            state, sc = '溜去煮大白饭了 · 点它按回工位', (240, 196, 120)
        elif st.is_small():
            state = '小模型 · 速度 -25% / 质量 -15%'
            blk = st.m.get('small_block', ())
            if blk:
                state += ' · 不接' + '/'.join(TYPES[t]['name'] for t in blk)
            sc = C_GOLD
        elif st.has_big():
            state = '大模型 · 速度 +33% / 质量 +18% · 能接识图画图（但比不了旗舰线）'
            sc = C_GREEN
        elif st.forever:
            state, sc = '免费额度无限 · 永久有效', C_GREEN
        else:
            state, sc = '在线', C_GREEN
        if st.m.get('rhythm'):
            if self.is_night():
                state += f' · 夜班 速度 ×{GLM_NIGHT_SPD:.2f} / 额度 ×{GLM_NIGHT_QUOTA * NIGHT_COST:.2f}'
            else:
                state += f' · 白班 速度 ×{GLM_DAY_SPD:.2f} / 额度 ×{GLM_DAY_QUOTA:.2f}'
        if not st.on_grid():
            state += ' · 不走电闸'
        txt(s, state, tx, r.y + 118, 12, sc)
        pygame.draw.line(s, (46, 52, 74), (L, r.y + 146), (r.right - 28, r.y + 146))

        # ---------------- 左栏：今日额度 ----------------
        txt(s, '今日额度', L, r.y + 162, 11, (120, 128, 152))
        cap = st.quota_cap()
        if not st.subscribed:
            txt(s, '—', L, r.y + 178, 28, (110, 118, 140), bold=True)
            txt(s, f'/ {cap}', L + 34, r.y + 190, 13, (120, 128, 150))
        elif cap < 0:
            txt(s, '不限量', L, r.y + 180, 24, (150, 220, 180), bold=True)
        else:
            qcol = C_RED if st.quota < QUOTA_MIN else (
                C_TEXT if st.quota > cap * 0.3 else C_GOLD)
            val = str(int(st.quota))
            txt(s, val, L, r.y + 178, 28, qcol, bold=True)
            vw = text_w(val, 28, True)
            txt(s, f'/ {cap}', L + vw + 8, r.y + 190, 13, (140, 148, 172))
        bar = pygame.Rect(L, r.y + 216, LW, 9)
        pygame.draw.rect(s, (34, 38, 54), bar)
        if st.subscribed and cap > 0:
            pct = max(0.0, min(1.0, st.quota / max(1, cap)))
            pygame.draw.rect(s, C_GREEN if pct > 0.3 else C_GOLD,
                             (bar.x, bar.y, int(bar.w * pct), bar.h))
        if not st.subscribed:
            quota_hint = '还没开通订阅'
        elif cap < 0:
            quota_hint = '免费线路，随便跑'
        else:
            quota_hint = '边干边扣 · 扣到见底这单会断'
        txt(s, quota_hint, L, r.y + 232, 10, (106, 114, 136))

        # ---------------- 左栏：手上这单 ----------------
        jobs = st.jobs()
        if jobs:
            bits = [f'{TYPES[t.typ]["name"]} {int(min(1.0, t.prog) * 100)}%'
                    for t in jobs]
            head = '手上：' + ' + '.join(bits)
            if not st.at_home():
                head += ' · 正在赶回工位'
            elif st.limited:
                head += f' · 限流中（速度 {THROTTLE_PCT}%）'
            elif st.paused_job:
                head += ' · 已暂停'
            txt(s, head, L, r.y + 256, 11,
                (240, 150, 140) if st.limited else (170, 176, 198))
            b1 = self.station_job_btn()
            on = st.paused_job
            hov1 = b1.collidepoint(self.mouse)
            alpha_rect(s, b1, (44, 40, 24) if hov1 else (28, 28, 20), 5)
            pygame.draw.rect(s, (236, 214, 130) if on else (150, 150, 110), b1, 1,
                             border_radius=5)
            txt(s, '继续' if on else '暂停', b1.centerx, b1.centery, 13,
                (255, 240, 190) if on else (206, 206, 176), 'center', bold=True)
            b2 = self.station_abandon_btn()
            hov2 = b2.collidepoint(self.mouse)
            alpha_rect(s, b2, (52, 28, 28) if hov2 else (34, 22, 22), 5)
            pygame.draw.rect(s, (220, 130, 126), b2, 1, border_radius=5)
            txt(s, '放弃这单', b2.centerx, b2.centery, 12, (255, 170, 162),
                'center', bold=True)

        # ---------------- 左栏：装备栏 ----------------
        txt(s, f'装备栏 {len(st.gear)}/{MAX_GEAR} · 点一下卸回背包',
            L, r.y + 316, 10, (150, 158, 182))
        for gid, sr in self.station_gear_slots(st):
            hov = sr.collidepoint(self.mouse)
            alpha_rect(s, sr, (52, 46, 30) if (hov and gid) else
                       ((30, 30, 40) if gid else (24, 26, 34)), 6)
            pygame.draw.rect(s, (236, 206, 130) if gid else (64, 68, 86), sr,
                             2 if (hov and gid) else 1, border_radius=6)
            if gid:
                g = next((x for x in GEAR if x['id'] == gid), None)
                draw_gear_icon(s, gid, sr.centerx - 22, sr.y + 10, 44)
                gname = (g['name'] if g else gid)
                gname = gname.split('（')[0].split('(')[0]
                txt(s, gname[:5], sr.centerx, sr.y + 60, 11,
                    (250, 224, 170), 'midtop')
                txt(s, '卸下', sr.centerx, sr.y + 78, 10,
                    (255, 190, 160) if hov else (150, 140, 132), 'midtop')
            else:
                txt(s, '空', sr.centerx, sr.centery - 8, 13, (92, 98, 118), 'midtop')

        # ---------------- 左栏：重置卡 + 疲劳 ----------------
        if st.subscribed:
            rb = self.station_reset_btn()
            n_card = self.bag_count(RESET_PREFIX + st.m['id'])
            can_r = n_card > 0
            hovr = rb.collidepoint(self.mouse)
            alpha_rect(s, rb, (44, 38, 24) if hovr and can_r else (28, 26, 20), 5)
            pygame.draw.rect(s, (232, 196, 120) if can_r else (78, 72, 58), rb, 1,
                             border_radius=5)
            label = (f'用重置卡（背包 ×{n_card}）' if can_r
                     else f'重置卡：去装备店买 ¥{reset_price(st.m)}')
            txt(s, label, rb.centerx, rb.centery, 10,
                (250, 224, 170) if can_r else (150, 142, 118), 'center', bold=True)

            fcol = ((150, 210, 170) if st.fatigue < 0.4 else
                    ((236, 200, 130) if st.fatigue < 0.75 else C_RED))
            txt(s, '疲劳', L, r.y + 492, 11, (120, 128, 152))
            fbar = pygame.Rect(L + 36, r.y + 496, 200, 8)
            pygame.draw.rect(s, (34, 38, 54), fbar)
            pygame.draw.rect(s, fcol, (fbar.x, fbar.y, int(fbar.w * st.fatigue), fbar.h))
            txt(s, f'{int(st.fatigue * 100)}%', fbar.right + 10, r.y + 490, 11, fcol)
            if st.resting:
                txt(s, '全员休息中', L + 36, r.y + 510, 10, (150, 210, 170))
            elif st.no_fatigue:
                txt(s, '不会累', L + 36, r.y + 510, 10, (130, 140, 164))
            else:
                txt(s, '累了就轮休（只有休息日能清零）', L + 36, r.y + 510, 10,
                    (110, 118, 142))

        # ---------------- 右栏：数据 ----------------
        rows = [
            ('处理速度', f'{st.spd():.2f} 单位/秒', C_TEXT),
            ('基础质量', f'{st.quality("chat") * st.qmean() * 100:.0f}'
                        + ('±' if st.m.get('qjitter') else ''), C_TEXT),
            ('每单消耗', f'{self.quota_need(st, 85)} 额度 / 100 工作量', C_TEXT),
            ('累计接单', f'{st.done} 单', C_TEXT),
            ('累计净利', f'¥{st.total_earn:,.0f}', C_TEXT),
        ]
        if st.meal > 0:
            rows.append(('餐食加成', f'+{int(MEAL_BUFF * 100)}% · {fmt_sec_game(st.meal)}',
                         (240, 200, 140)))
        if st.m.get('need'):
            if st.has_gear('vpn_enc'):
                port_txt, port_col = '加密', (150, 220, 190)
            elif st.has_gear('vpn'):
                port_txt, port_col = '普通', (150, 200, 230)
            else:
                port_txt, port_col = '缺', C_RED
            rows.append(('出口端口', port_txt, port_col))
        if st.subscribed:
            hp = (st.temp - TEMP_IDLE) / (TEMP_LIMIT - TEMP_IDLE)
            hcol = C_RED if hp > 0.8 else (C_GOLD if hp > 0.5 else (150, 200, 160))
            rows.append(('核心温度', f'{st.temp:.0f}°C / {TEMP_LIMIT:.0f}°C', hcol))
        if st.gear:
            names = '、'.join(next((x['name'] for x in GEAR if x['id'] == gid), gid)
                             for gid in sorted(st.gear))
            rows.append(('装备', names, (250, 214, 140)))
        if st.subscribed:
            eff = st.efficiency()
            ecol = (150, 220, 180) if eff >= 1.0 else (
                (236, 200, 130) if eff >= 0.85 else C_RED)
            rows.append(('当前效率', f'×{eff:.2f}', ecol))
        for i, (k, v, col_) in enumerate(rows):
            yy = r.y + 162 + i * 24
            txt(s, k, RX, yy, 11, (120, 128, 152))
            txt(s, v, r.right - 28, yy, 12, col_, 'topright', bold=(i == 0))

        # 值班开关（科考站维持运转）
        if self.scene == 'station' and st.unlocked:
            db = self.station_duty_btn()
            on = st.duty
            hovd = db.collidepoint(self.mouse)
            alpha_rect(s, db, (30, 50, 44) if on else ((30, 34, 44) if hovd else (24, 28, 36)), 5)
            pygame.draw.rect(s, (130, 220, 186) if on else (86, 92, 108), db, 1,
                             border_radius=5)
            txt(s, ('值班中 · 省燃料 / 不接单' if on else '安排值班（省燃料 · 不接单）'),
                db.centerx, db.centery, 10,
                (170, 240, 206) if on else (170, 178, 194), 'center', bold=True)

        # 关系入口（单独面板）
        rbtn = self.station_relations_btn()
        hov_rel = rbtn.collidepoint(self.mouse)
        alpha_rect(s, rbtn, (44, 30, 40) if hov_rel else (28, 22, 30), 6)
        pygame.draw.rect(s, (214, 140, 170), rbtn, 1, border_radius=6)
        best = self.top_bonds(st, 1)
        who = f' · 最熟 {best[0][0]} {int(best[0][1] * 100)}' if best else ' · 还没跟谁聊过'
        txt(s, f'人缘关系{who}', rbtn.centerx, rbtn.centery, 12, (246, 200, 216),
            'center', bold=True)

        # ---------------- 底部：解锁 / 三档订阅 ----------------
        if not st.unlocked:
            cost = st.m.get('unlock', 0)
            can = self.money >= cost
            txt(s, '解锁后它才会出现在派单列表里，再挑一档订阅才能开工',
                r.centerx, r.y + 530, 11, (132, 140, 164), 'midtop')
            btn = self.station_up_btn()
            col = st.m['color'] if can else (64, 68, 84)
            hov = btn.collidepoint(self.mouse)
            alpha_rect(s, btn, (34, 44, 60) if hov and can else (24, 30, 42), 6)
            pygame.draw.rect(s, col, btn, 2, border_radius=6)
            txt(s, f'解锁 · ¥{cost:,}', btn.centerx, btn.y + 13, 16,
                C_TEXT if can else (124, 128, 146), 'midtop', bold=True)
        elif st.has_tiers():
            hint = ('点一档买 7 天：当场付清，24:00 每天扣一天'
                    if st.subscribed else '挑一档买 7 天：当场付清，到期前都能用')
            txt(s, hint, r.centerx, r.y + 530, 11, (132, 140, 164), 'midtop')
            mx, my = self.mouse
            for kind, tier, btn in self.station_tier_btns(st):
                hov = btn.collidepoint(mx, my)
                if kind == 'big':
                    cost = st.m.get('big_price', 0)
                    on = st.big
                    bg = (52, 44, 26) if on else ((38, 34, 24) if hov else (28, 26, 20))
                    alpha_rect(s, btn, bg, 6)
                    pygame.draw.rect(s, (236, 206, 120) if on else (96, 86, 60), btn,
                                     2 if on else 1, border_radius=6)
                    txt(s, '已是大模型' if on else f'大模型 ¥{cost:,}',
                        btn.centerx, btn.y + 8, 13,
                        (255, 232, 170) if on else (222, 210, 170), 'midtop', bold=True)
                    unlocks_img = bool(st.m.get('small_block'))
                    if on:
                        sub = '解锁识图画图' if unlocks_img else '速度 +33% 质量 +18%'
                    else:
                        sub = '解锁识图画图' if unlocks_img else '一次性升级'
                    txt(s, sub, btn.centerx, btn.y + 28, 11,
                        (190, 220, 170) if on else (150, 140, 118), 'midtop')
                    continue
                name, fee, qcap = st.tiers()[tier - 1]
                on = st.subscribed and st.tier == tier
                bg = (38, 46, 66) if on else ((30, 36, 50) if hov else (22, 26, 38))
                alpha_rect(s, btn, bg, 6)
                pygame.draw.rect(s, st.m['color'] if on else (58, 66, 92), btn,
                                 2 if on else 1, border_radius=6)
                fee_txt = f'¥{fee * SUB_DAYS} / {SUB_DAYS}天' if fee else '免费'
                title = f'{name} · {fee_txt}'
                if on:
                    title = (f'{name} · 续费 ¥{fee * SUB_DAYS}' if fee
                             else f'{name} · 免费续 {SUB_DAYS} 天')
                txt(s, title, btn.centerx, btn.y + 7, 14,
                    C_TEXT if on or hov else (186, 194, 216), 'midtop', bold=True)
                q_txt = '额度不限' if qcap < 0 else f'额度 {qcap}/天'
                if on:
                    q_txt += f' · 还剩 {st.sub_days} 天'
                txt(s, q_txt, btn.centerx, btn.y + 28, 11,
                    (150, 200, 170) if on else (126, 134, 158), 'midtop')
        else:
            txt(s, '免费线路，不用订阅、额度无限、不会到期',
                r.centerx, r.y + 530, 11, (132, 140, 164), 'midtop')

        cb = self.close_btn(r)
        pygame.draw.rect(s, (40, 44, 62), cb, border_radius=4)
        pygame.draw.rect(s, (90, 104, 134), cb, 1, border_radius=4)
        txt(s, 'X', cb.centerx, cb.y + 7, 16, C_TEXT, 'midtop', bold=True)

    def draw_summary(self, d):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 190))
        r = pygame.Rect(SW // 2 - 300, SH // 2 - 230, 600, 460)
        alpha_rect(s, r, (18, 20, 32, 248), 10)
        pygame.draw.rect(s, (86, 112, 168), r, 2, border_radius=10)
        txt(s, f'第 {d["day"]} 天 · 打烊结算', r.centerx, r.y + 26, 26, C_TEXT, 'midtop', bold=True)

        rent_txt = f'-{d["rent"]:,.0f}' if d['rent'] else '今天不用交'
        rows = [
            ('营业收入', f'+{d["rev"]:,.0f}', C_GREEN),
            ('上游成本', f'-{d["cost"]:,.0f}', (224, 136, 132)),
            ('公寓房租', rent_txt,
             (224, 136, 132) if d['rent'] else (120, 128, 150)),
            ('电费', f'-{d["power"]:,.0f}', (224, 136, 132)),
            ('线路工资', f'-{d["wage"]:,.0f}', (224, 136, 132)),
        ]
        for i, (k, v, c) in enumerate(rows):
            yy = r.y + 76 + i * 30
            txt(s, k, r.x + 60, yy, 15, (150, 158, 180))
            txt(s, v, r.right - 60, yy, 16, c, 'topright')

        pygame.draw.line(s, (52, 58, 82), (r.x + 50, r.y + 232), (r.right - 50, r.y + 232))
        txt(s, '当日净利', r.x + 60, r.y + 240, 18, C_TEXT, bold=True)
        col = C_GOLD if d['net'] >= 0 else C_RED
        txt(s, f'{d["net"]:+,.0f}', r.right - 60, r.y + 234, 30, col, 'topright', bold=True)

        txt(s, f'今日接单 {d.get("orders", 0)} 单 · 平均客单 '
               f'¥{d["rev"] / max(1, d.get("orders", 1)):.0f}',
            r.x + 60, r.y + 288, 14, (150, 158, 180))
        txt(s, f'结余 ¥{self.money:,.0f}', r.x + 60, r.y + 316, 15, C_DIM)
        txt(s, f'声誉 {self.rep:.0f}', r.right - 60, r.y + 316, 15, C_PURPLE, 'topright')

        btn = pygame.Rect(r.centerx - 120, r.bottom - 76, 240, 48)
        hover = btn.collidepoint(self.mouse)
        alpha_rect(s, btn, (34, 56, 96) if hover else (26, 40, 68), 6)
        pygame.draw.rect(s, (110, 156, 232), btn, 2, border_radius=6)
        txt(s, f'开门营业 · 第 {self.day + 1} 天', btn.centerx, btn.y + 13, 18, C_TEXT,
            'midtop', bold=True)

    def draw_over(self, d):
        s = self.screen
        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (4, 5, 10, 210))
        r = pygame.Rect(SW // 2 - 320, SH // 2 - 220, 640, 440)
        alpha_rect(s, r, (18, 20, 32, 250), 10)
        if d['bankrupt']:
            pygame.draw.rect(s, C_RED, r, 2, border_radius=10)
            txt(s, '资金链断了', r.centerx, r.y + 40, 34, C_RED, 'midtop', bold=True)
            txt(s, f'撑到第 {d["day"]} 天，账上 ¥{d["money"]:,.0f}',
                r.centerx, r.y + 96, 16, (190, 196, 214), 'midtop')
            txt(s, '上游要现结，房东也不等人。', r.centerx, r.y + 130, 15, C_DIM, 'midtop')
        else:
            money = self.net_worth()
            score = money + self.rep * 60 + self.main_step * 250
            if score >= 19000:
                grade, gc, word = 'S', C_GOLD, '中转站一条街都知道了你'
            elif score >= 14000:
                grade, gc, word = 'A', C_GREEN, '稳扎稳打，盘子铺开了'
            elif score >= 9000:
                grade, gc, word = 'B', C_BLUE, '活下来了，还有得赚'
            else:
                grade, gc, word = 'C', C_DIM, '勉强维持，没赔掉底裤'
            txt(s, '三十天结束', r.centerx, r.y + 34, 20, C_DIM, 'midtop')
            txt(s, grade, r.centerx, r.y + 66, 96, gc, 'midtop', bold=True)
            txt(s, word, r.centerx, r.y + 176, 18, C_TEXT, 'midtop')
            txt(s, f'净资产 ¥{money:,.0f}   声誉 {self.rep:.0f}   主线 {self.main_step}/{len(self.MAIN)}',
                r.centerx, r.y + 214, 16, (172, 180, 202), 'midtop')
            peak = max([h['rev'] for h in self.history], default=0)
            total = sum(st.done for st in self.stations)
            txt(s, f'总接单 {total} 单   最高单日营收 ¥{peak:,.0f}   在线线路 '
                   f'{len(self.unlocked())}/{len(MODELS)}',
                r.centerx, r.y + 248, 14, (128, 136, 160), 'midtop')

        btn = pygame.Rect(r.centerx - 120, r.bottom - 76, 240, 48)
        hover = btn.collidepoint(self.mouse)
        alpha_rect(s, btn, (46, 40, 34) if hover else (32, 28, 24), 6)
        pygame.draw.rect(s, C_GOLD, btn, 2, border_radius=6)
        txt(s, '回到标题', btn.centerx, btn.y + 13, 18, C_TEXT, 'midtop', bold=True)

    # ---------------------------------------------------- 标题
    def draw_title(self):
        s = self.screen
        w = self.world
        w.fill(C_BG)
        pygame.draw.rect(w, C_WALL, (0, 0, WW, WH))
        # 缓慢漂浮的像素星点
        for i in range(46):
            x = (i * 137 + pygame.time.get_ticks() // 90) % WW
            y = (i * 71) % WH
            c = 40 + (i * 13) % 50
            pygame.draw.rect(w, (c, c + 6, c + 22), (x, y, 1, 1))
        # 值班角色剪影，压在最下面当底纹
        n = len(self.stations)
        x0 = (WW - n * 68) // 2
        for i, st in enumerate(self.stations):
            img = self.assets.model(st.m['id'])
            if not img:
                continue
            dim = img.copy()
            dim.fill((64, 70, 92, 255), special_flags=pygame.BLEND_RGBA_MULT)
            w.blit(dim, (x0 + i * 68, 716 - img.get_height()))
        s.blit(pygame.transform.scale(w, (SW, SH)), (0, 0))
        self.flush_world_texts()

        alpha_rect(s, pygame.Rect(0, 0, SW, SH), (8, 9, 16, 120))
        txt(s, 'AI 中转站', SW // 2, 92, 76, C_TEXT, 'midtop', bold=True)
        txt(s, 'A I   T R A N S I T   H U B', SW // 2, 180, 18, (110, 150, 210), 'midtop')
        txt(s, '网上接单，站里跑算了——八个模型接线员，一间夹层里的小生意。',
            SW // 2, 218, 16, (150, 158, 180), 'midtop')

        # ---------------- 4 个存档位 ----------------
        for slot, card in self.title_slot_rects():
            info = self.peek_save(slot)
            hov = card.collidepoint(self.mouse)
            alpha_rect(s, card, (24, 29, 44, 232) if info else (18, 20, 30, 205), 8)
            pygame.draw.rect(s, (96, 122, 172) if hov else
                             ((72, 88, 126) if info else (52, 58, 78)),
                             card, 2 if hov else 1, border_radius=8)
            txt(s, f'存档 {slot}', card.x + 18, card.y + 12, 12, (132, 142, 168))
            if not info:
                txt(s, '空存档位', card.x + 18, card.y + 38, 22, (118, 126, 148),
                    bold=True)
                txt(s, '点右边「新开」在这里开一局', card.x + 18, card.y + 74, 12,
                    (96, 104, 126))
                continue
            day = info.get('day', 1)
            st = info.get('st', [])
            live = sum(1 for x in st if x.get('sb'))
            clock = info.get('clock') or ''
            txt(s, f'第 {day} 天', card.x + 18, card.y + 32, 24, C_BLUE, bold=True)
            txt(s, f'¥{info.get("money", 0):,.0f}', card.x + 150, card.y + 38, 17,
                C_GOLD, bold=True)
            txt(s, f'声誉 {info.get("rep", 0):.0f}', card.x + 300, card.y + 40, 14,
                C_PURPLE)
            txt(s, f'在线 {live} / {len(self.visible_stations())} · 网关 Lv{info.get("gw_lv", 1)}'
                   + (f' · {clock} 存档' if clock else ''),
                card.x + 18, card.y + 72, 12, (138, 148, 174))
            try:
                import datetime
                mt = datetime.datetime.fromtimestamp(os.path.getmtime(save_path(slot)))
                txt(s, mt.strftime('%m-%d %H:%M'), card.x + 18, card.y + 92, 11,
                    (104, 112, 138))
            except (OSError, ValueError):
                pass

        # ---------------- 按钮 ----------------
        labels = {'load': '继续', 'new': '新开', 'delete': '删除',
                  'settings': '设置', 'quit': '退出', 'test': '科考站试玩'}
        for action, r, slot in self.title_buttons():
            hover = r.collidepoint(self.mouse)
            if action == 'load':
                alpha_rect(s, r, (52, 72, 112) if hover else (32, 46, 76), 5)
                pygame.draw.rect(s, (140, 184, 248), r, 2, border_radius=5)
                col = C_TEXT
            elif action == 'new':
                info = self.peek_save(slot)
                alpha_rect(s, r, (40, 60, 48) if hover else (24, 36, 30), 5)
                pygame.draw.rect(s, (120, 190, 150), r, 1, border_radius=5)
                col = (186, 232, 200)
                if info:
                    labels['new'] = '覆盖新开'
            elif action == 'delete':
                alpha_rect(s, r, (74, 40, 44) if hover else (40, 28, 32), 5)
                pygame.draw.rect(s, (176, 104, 110), r, 1, border_radius=5)
                col = (236, 168, 172)
            elif action == 'settings':
                alpha_rect(s, r, (40, 46, 66) if hover else (26, 30, 44), 6)
                pygame.draw.rect(s, (128, 174, 244) if hover else (74, 88, 120), r,
                                 2, border_radius=6)
                col = C_TEXT
            else:
                alpha_rect(s, r, (44, 40, 36) if hover else (28, 26, 24), 6)
                pygame.draw.rect(s, (120, 110, 96), r, 2, border_radius=6)
                col = (200, 192, 180)
            big = action in ('load', 'settings', 'quit')
            txt(s, labels[action], r.centerx, r.centery, 18 if big else 13,
                col, 'center', bold=big)

        # ---------------- 底栏：作者 / 出处 / 版权 ----------------
        alpha_rect(s, pygame.Rect(0, SH - 74, SW, 74), (6, 8, 14, 200), 0)
        txt(s, f'作者：{CREDITS["author"]}     ·     出处：{CREDITS["source"]}',
            SW // 2, SH - 70, 9, (146, 156, 180), 'midtop')
        txt(s, CREDITS['art'], SW // 2, SH - 57, 9, (146, 156, 180), 'midtop')
        txt(s, CREDITS['idea'], SW // 2, SH - 44, 9, (146, 156, 180), 'midtop')
        txt(s, CREDITS['note'], SW // 2, SH - 31, 8, (120, 130, 152), 'midtop')
        music = ('♪ ' + self.music.track) if (self.music.ok and self.music.track) else '♪ 无音乐'
        txt(s, f'{music}    ·    设置里可以调音量和全屏    ·    F11 全屏',
            SW // 2, SH - 16, 9, (104, 112, 136), 'midtop')


def main():
    Game().run()


if __name__ == '__main__':
    main()
