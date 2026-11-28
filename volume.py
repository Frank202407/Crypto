import time
import threading
from datetime import datetime, timedelta
from itertools import cycle
from utils import get_kline, calculate_recent_average
from notify import dingtalk_notify


# ============================================================
# 基础配置
# ============================================================

# 币种列表，走势稳定的，用于4小时K线监控
big_symbols = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT",
    "BNBUSDT", "HYPEUSDT", "CLUSDT"
]

# 币种列表，有波动的，用于15分钟K线监控
medium_symbols = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT",
    "SUIUSDT", "ADAUSDT", "LINKUSDT"
]

# K线趋势的币种列表
trend_symbols = ["BTCUSDT"]

# 直接在这里填写钉钉Webhook
webhook = "https://oapi.dingtalk.com/robot/send?access_token=75b8fc4ce4e1e72a378175408c026243f0a554f2033c6148c942346ef2cb1cb0"

# 15分钟MA7逆转观察池
watch_pool = {}
# 线程锁，避免扫描任务和观察任务同时修改观察池
watch_pool_lock = threading.Lock()

# 观察池有效期：4小时
WATCH_EXPIRE_HOURS = 4


# ============================================================
# 15分钟K线MA7的变化情况
# 获取最近已完成的15分钟K线，计算MA7。
# baseline_trend：
#     最近一次非零MA7方向，用于建立观察基准。
#     1 = 上升
#     -1 = 下降
#     0 = 无法判断
# current_trend：
#     最新相邻两次MA7的方向，用于实时判断逆转。
#     1 = 上升
#      -1 = 下降
#     0 = 持平
# ============================================================
def get_ma7_state(symbol, proxy_cycle):

    # 读取15分钟K线
    data = get_kline(symbol, "15m", 20, proxy_cycle)
    if not data or len(data) < 16:
        print(f"⚠️ {symbol} 获取MA7数据不足")
        return None
    # 15分钟K线的收盘价
    closes = [float(k[4]) for k in data]
    # 排除最新一根尚未完成的15分钟K线
    completed_closes = closes[:-1]
    if len(completed_closes) < 12:
        return None

    # 计算已完成K线对应的MA7序列
    ma7_values = []
    for i in range(6, len(completed_closes)):
        ma7 = sum(completed_closes[i - 6:i + 1]) / 7
        ma7_values.append(ma7)
    if len(ma7_values) < 2:
        return None
    ma7_previous = ma7_values[-2]
    ma7_current = ma7_values[-1]
    # 最新相邻两次MA7的方向
    difference = ma7_current - ma7_previous
    if difference > 0:
        current_trend = 1
    elif difference < 0:
        current_trend = -1
    else:
        current_trend = 0

    # 寻找最近一次非零MA7方向，建立原始趋势基准
    baseline_trend = 0
    for i in range(len(ma7_values) - 1, 0, -1):
        difference = ma7_values[i] - ma7_values[i - 1]
        if difference > 0:
            baseline_trend = 1
            break
        elif difference < 0:
            baseline_trend = -1
            break
    return {
        "ma7_previous": ma7_previous,
        "ma7_current": ma7_current,
        "baseline_trend": baseline_trend,
        "current_trend": current_trend
    }


# ============================================================
# 添加或者更新代币到观察池
# 加入或更新观察池。
# 如果代币已经存在：
# 更新最新信号时间、价格、方向和MA7基准，
# 不重复发送原有异常放量通知。
# ============================================================
def add_or_update_watch_pool(
    symbol,
    order,
    signal_price,
    proxy_cycle
):
    ma7_state = get_ma7_state(symbol, proxy_cycle)
    if ma7_state is None:
        print(f"⚠️ {symbol} 无法获取MA7基准，未加入观察池")
        return
    signal_time = datetime.now()
    new_data = {
        "signal_time": signal_time,
        "signal_price": signal_price,
        "order": order,
        "ma7_at_signal": ma7_state["ma7_current"],
        "ma7_previous_at_signal": ma7_state["ma7_previous"],
        "ma7_trend_at_signal": ma7_state["baseline_trend"]
    }
    with watch_pool_lock:
        is_new = symbol not in watch_pool
        # 新信号覆盖旧数据，重新计算4小时有效期
        watch_pool[symbol] = new_data
    if is_new:
        print(
            f"👀 {symbol} 加入MA7观察池，"
            f"方向：{order}，"
            f"MA7方向：{ma7_state['baseline_trend']}"
        )
    else:
        print(
            f"🔄 {symbol} 更新观察池信号，"
            f"方向：{order}，"
            f"重新计算4小时有效期"
        )

# 监控观察池中的代币是否出现MA7方向逆转。
def monitor_watch_pool(proxy_cycle):
    now = datetime.now()
    with watch_pool_lock:
        symbols = list(watch_pool.keys())
    for symbol in symbols:
        with watch_pool_lock:
            item = watch_pool.get(symbol)
            if item is None:
                continue
            # 复制当前观察数据，避免后续更新影响本次判断
            signal = item.copy()
        # 超过4小时没有逆转，移出观察池
        if now - signal["signal_time"] >= timedelta(
            hours=WATCH_EXPIRE_HOURS
        ):
            with watch_pool_lock:
                current = watch_pool.get(symbol)
                # 防止扫描任务刚好更新了该代币的信号
                if (
                    current is not None
                    and current["signal_time"] == signal["signal_time"]
                ):
                    del watch_pool[symbol]
                    print(
                        f"⌛ {symbol} 观察超时4小时，"
                        f"移出观察池"
                    )
            continue

        # 获取最新已完成K线的MA7
        ma7_state = get_ma7_state(symbol, proxy_cycle)
        if ma7_state is None:
            continue
        original_trend = signal["ma7_trend_at_signal"]
        current_trend = ma7_state["current_trend"]
        # 原始MA7方向不明确或最新MA7持平，暂不判断逆转
        if original_trend == 0 or current_trend == 0:
            continue

        # 判断MA7是否发生方向逆转
        is_reversal = current_trend != original_trend
        if not is_reversal:
            continue

        # 发生逆转，移出观察池
        with watch_pool_lock:
            current = watch_pool.get(symbol)
            if (
                current is None
                or current["signal_time"] != signal["signal_time"]
            ):
                continue
            del watch_pool[symbol]

        old_direction = (
            "下降" if original_trend == -1 else "上升"
        )

        new_direction = (
            "上升" if current_trend == 1 else "下降"
        )

        content = (
            f"Lucky:🚨 MA7趋势逆转信号\n"
            f"**{symbol}**\n"
            f"异常放量时间："
            f"{signal['signal_time'].strftime('%m-%d %H:%M:%S')}\n"
            f"当前时间：{now.strftime('%m-%d %H:%M:%S')}\n"
        )
        dingtalk_notify(webhook, content)
        print(f"🚨 {symbol} MA7发生方向逆转，已发送通知")


# ============================================================
# 每15分钟的第2分钟启动一次：
# 01:00、16:00、31:00、46:00。
# ============================================================
def watch_pool_scheduler(proxy_cycle):

    last_run_key = None
    while True:
        now = datetime.now()
        if (
            now.minute % 15 == 1
            and now.second < 3
        ):
            run_key = now.strftime("%Y-%m-%d %H:%M")

            if run_key != last_run_key:
                last_run_key = run_key

                # print(
                #     f"\n========== MA7观察池检查 "
                #     f"{now.strftime('%H:%M:%S')} =========="
                # )
                try:
                    monitor_watch_pool(proxy_cycle)
                except Exception as e:
                    print(f"⚠️ MA7观察池监控异常：{e}")
        time.sleep(0.2)


# ============================================================
# 启动独立的MA7观察池监控线程。
# 整个程序只需要调用一次。
# ============================================================
def start_watch_pool_monitor(proxy_cycle):
    thread = threading.Thread(
        target=watch_pool_scheduler,
        args=(proxy_cycle,),
        daemon=True
    )
    thread.start()
    print("✅ MA7观察池监控线程已启动")


# ============================================================
# 15分钟K线异常放量监控
# 原有判断逻辑保留，只增加观察池登记
# ============================================================
def volume_ma_15m(symbol, proxy_cycle):

    # 当前时间
    now = datetime.now()

    # 读取15分钟K线最新96根数据
    data = get_kline(symbol, "15m", 96, proxy_cycle)
    if not data or len(data) < 96:
        print(f"获取 {symbol} 的15分钟K线失败或数据不足96根")
        return
    # 开盘价、最高价、最低价、收盘价、成交量
    opens = [float(k[1]) for k in data]
    highs = [float(k[2]) for k in data]
    lows = [float(k[3]) for k in data]
    closes = [float(k[4]) for k in data]
    volumes = [float(k[5]) for k in data]
    # 计算成交量MA96
    volume_ma96 = calculate_recent_average(volumes, 96)
    if volume_ma96 is None or volume_ma96 <= 0:
        print(f"⚠️ {symbol} 的成交量MA96计算失败")
        return
    # 计算价格MA14
    price_ma14 = calculate_recent_average(closes, 14)
    if price_ma14 is None or price_ma14 <= 0:
        return

    # 当前15分钟K线数据
    current_volume = volumes[-1]
    current_open = opens[-1]
    current_high = highs[-1]
    current_low = lows[-1]
    current_close = closes[-1]
    # 当前成交量相对MA96的倍数
    volume_times = current_volume / volume_ma96
    # 判断方向：开盘价低于MA14为做多方向
    is_long = current_open < price_ma14

    # 当前价格极值相对MA14的偏离率
    if is_long:
        price_deviation = (
            price_ma14 - current_low
        ) / price_ma14
    else:
        price_deviation = (
            current_high - price_ma14
        ) / price_ma14


    # ========================================================
    # 极端做多行情：直接告警
    # 不经过常规开盘价、3根K线、4小时及成交量过滤
    # ========================================================
    extreme_volume = is_long and volume_times > 15
    extreme_price_deviation = (
        is_long and price_deviation > 0.08
    )
    if extreme_volume or extreme_price_deviation:
        # 判断触发原因
        reasons = []
        if extreme_volume:
            reasons.append(
                f"当前成交量达到MA96的{volume_times:.1f}倍"
            )
        if extreme_price_deviation:
            reasons.append(
                f"最低价偏离MA14达到{price_deviation:.2%}"
            )
        content = (
            f"Lucky:🚨 极端做多异常信号\n"
            f"**{symbol}**\n"
            f"{now.strftime('%H:%M:%S')} 当前15分钟\n"
            f"触发原因：{'；'.join(reasons)}\n"
            f"当前成交量：{volume_times:.1f}倍\n"
            f"最低价偏离MA14：{price_deviation:.2%}\n"
            f"当前价格：{current_close}\n"
        )
        # 直接发送异常告警
        dingtalk_notify(webhook, content)
        print(
            f"🚨 {symbol} 触发极端做多条件，"
            f"已直接发送告警"
        )
        # 登记或更新MA7观察池
        try:
            add_or_update_watch_pool(
                symbol=symbol,
                order="多单",
                signal_price=current_close,
                proxy_cycle=proxy_cycle
            )
        except Exception as e:
            print(f"⚠️ {symbol} 加入MA7观察池失败：{e}")
        # 极端条件已经处理，不再进入常规判断
        return


    # ========================================================
    # 以下为原有常规异常放量判断逻辑，保持不变
    # ========================================================

    # 默认放量倍数
    volume_multiple = 6
    # 15分钟K线开盘价偏离MA14的基准
    open_deviation_threshold = 0.01
    # 开盘价相对MA14的偏离率
    open_deviation = 0
    # 开盘价低于MA14，判断做多方向
    if is_long:
        open_deviation = (
            price_ma14 - current_open
        ) / current_open

    else:
        open_deviation = (
            current_open - price_ma14
        ) / price_ma14
        # 做空方向
        open_deviation_threshold = 0.05

    # 开盘价与MA14已经有偏离
    if open_deviation > open_deviation_threshold:

        # 放量反抽机会
        if (
            (is_long and current_open < current_close)
            or
            (not is_long and current_open > current_close)
        ):
            content = (
                f"Lucky:🚨    ** {symbol} **\n"
                f" {now.strftime('%H:%M:%S')}当前15分钟\n"
                f" {volume_times:.1f}倍放量!\n"
                f" 有反抽可能!\n"
            )

        # ------------------------------------------------
        # 当前价格极值相对MA14偏离超过3.5%
        # 最近3根15分钟K线最大成交量超过MA96的6倍
        # ------------------------------------------------
        max_volume_3 = max(volumes[-3:])
        max_volume_times_3 = max_volume_3 / volume_ma96
        price_deviation_threshold = 0.035
        if (
            price_deviation > price_deviation_threshold
            and max_volume_times_3 > volume_multiple
        ):
            print(
                f"{symbol} 满足15分钟异常放量条件，"
                f"准备检查4小时过滤"
            )

            # ------------------------------------------------
            # 当前4小时K线开盘价相对4小时MA14
            # 偏离必须超过1.5%
            # ------------------------------------------------
            data_4h = get_kline(
                symbol, "4h", 14, proxy_cycle
            )
            if not data_4h or len(data_4h) < 14:
                print(
                    f"⚠️ {symbol} 的4小时K线数据不足，"
                    f"跳过告警"
                )
                return
            opens_4h = [
                float(k[1]) for k in data_4h
            ]

            closes_4h = [
                float(k[4]) for k in data_4h
            ]
            current_open_4h = opens_4h[-1]

            # 计算4小时K线的MA14
            price_ma14_4h = calculate_recent_average(
                closes_4h, 14
            )
            if price_ma14_4h is None or price_ma14_4h <= 0:
                return
            # 4小时K线开盘价相对MA14的绝对偏离率
            deviation_4h = (
                abs(current_open_4h - price_ma14_4h)
                / price_ma14_4h
            )
            # 4小时K线开盘价偏离MA14距离太近，跳过告警
            if deviation_4h <= 0.015:
                print(
                    f"⚠️ {symbol} 当前4小时K线开盘价"
                    f"距离MA14不足1.5%，跳过告警"
                )
                return
            # ------------------------------------------------
            # 满足全部条件，准备发送通知
            # ------------------------------------------------
            # 上一个时段已经通知过，就无需重复通知
            if current_volume < volumes[-2] * 0.85:
                print(
                    f"⚠️ {symbol} 本时段成交量比上一时段小，"
                    f"不再重复通知"
                )
                return

            order = "多单"

            if not is_long:
                order = "空单"

            content = (
                f"Lucky:🚨    ** {symbol} **\n"
                f" {now.strftime('%H:%M:%S')}当前15分钟\n"
                f" 近3根最大放量: {max_volume_times_3:.1f}倍!\n"
                f" 价格极值偏离MA14: {price_deviation:.2%}\n"
                f" 4小时开盘价偏离MA14: {deviation_4h:.2%}\n"
            )

            # 原有异常放量告警
            dingtalk_notify(webhook, content)
            # 登记或更新MA7观察池
            try:
                add_or_update_watch_pool(
                    symbol=symbol,
                    order=order,
                    signal_price=current_close,
                    proxy_cycle=proxy_cycle
                )
            except Exception as e:
                print(
                    f"⚠️ {symbol} 加入MA7观察池失败：{e}"
                )



# ============================================================
# 1小时K线爆量监控
# ============================================================
def volume_ma_1h(symbol, proxy_cycle):
    volume_surge(symbol, "1h", 96, 9.5, proxy_cycle)


# ============================================================
# 4小时K线趋势监控
# ============================================================
def volume_ma_4h(symbol, proxy_cycle):

    # 读取4小时K线最新96根数据
    data = get_kline(symbol, "4h", 96, proxy_cycle)
    if not data or len(data) < 34:
        print(f"❌ {symbol} 数据不足以计算MA30")
        return
    # 去掉当前正在形成的4H K线
    completed = data[:-1]
    # 获取收盘价
    closes = [
        float(k[4])
        for k in completed
    ]

    # 计算最近4个完整周期的MA7
    ma7_list = []
    for i in range(len(closes) - 4, len(closes)):
        ma7 = sum(closes[i - 6:i + 1]) / 7
        ma7_list.append(ma7)

    # 计算最近4个完整周期的MA14
    ma14_list = []
    for i in range(len(closes) - 4, len(closes)):
        ma14 = sum(closes[i - 13:i + 1]) / 14
        ma14_list.append(ma14)

    # 计算最近4个完整周期的MA30
    ma30_list = []
    for i in range(len(closes) - 4, len(closes)):
        ma30 = sum(closes[i - 29:i + 1]) / 30
        ma30_list.append(ma30)

    # 最近4个MA
    A, B, C, D = ma7_list
    E, F, G, H = ma14_list
    aa, bb, cc, dd = ma30_list

    # ==================================================
    # 情况A：MA30逆转下跌趋势
    # aa > bb > cc < dd
    # ==================================================
    condition_a = (
        dd > cc
        and cc < bb
        and bb < aa
    )

    # ==================================================
    # 情况B：MA7逆转 + MA30持续上涨
    # ==================================================
    condition_b = (
        D > C
        and C < B
        and B < A
        and aa < bb
        and bb < cc
        and cc < dd
    )
    # 当前最新完整4H K线的均线
    current_ma30 = dd
    current_ma7 = D
    # MA7与MA30的绝对偏差
    deviation = abs(current_ma7 - current_ma30) / current_ma30
    # MA30与MA7偏差不超过1.5%
    condition_price = deviation <= 0.015
    if condition_price:
        now = datetime.now()
        if condition_a:
            content = (
                f"Lucky:🚨  {now.strftime('%H:%M:%S')} "
                f"** {symbol} **4小时K线MA30逆转下跌\n"
            )
            dingtalk_notify(webhook, content)

        # elif condition_b:
        #     content = (
        #         f"Lucky:🚨  {now.strftime('%H:%M:%S')} "
        #         f"** {symbol} **4小时K线MA7逆转下跌\n"
        #     )
        #     dingtalk_notify(webhook, content)


# ============================================================
# 判断K线是否放量异常
# ============================================================
def volume_surge(symbol, interval, period, threshold, proxy_cycle):

    now = datetime.now()
    # 读取period + 1根数据，包括当前未完成K线
    data = get_kline(symbol, interval, period + 1, proxy_cycle)
    if not data:
        print(f"获取{symbol}的{interval} K线失败或返回为空")
        return
    # 去掉最后一根未完成K线
    completed = data[:-1]
    volumes = [float(k[5]) for k in completed]

    # 计算成交量均值
    volume_ma = calculate_recent_average(volumes, period)
    if volume_ma is None:
        print(f"⚠️ {symbol}的{interval} K线数据不足{period}根，跳过计算")
        return

    # 获取最新一根完整K线的成交量
    current_volume = volumes[-1]
    # 成交量放大倍数
    volume_times = current_volume / volume_ma
    if volume_times > threshold:

        content = (
            f"Lucky:🚨    ** {symbol} **\n"
            f" {now.strftime('%H:%M:%S')}\n"
            f" 最近{interval}成交量放大{volume_times:.1f}倍！\n"
        )
        dingtalk_notify(webhook, content)


# ============================================================
# 定时执行任务
# ============================================================
def schedule_volume_check(proxy_cycle, watch_proxy_cycle):

    # 启动15分钟异常放量观察池的MA7逆转监控
    start_watch_pool_monitor(watch_proxy_cycle)
    while True:
        now = datetime.now()
        # ------------------------------------------------
        # 1小时K线监控，新的1小时15秒开始
        # -----------------------------------------------
        if now.minute == 0 and now.second == 15:
            print(
                f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} "
                f"开始检查1小时成交量..."
            )
            for symbol in big_symbols:
                volume_ma_1h(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(2)

        # ------------------------------------------------
        # 15分钟K线监控，每个刻钟结束前20秒开始
        # ------------------------------------------------
        if now.minute in [14, 29, 44, 59] and now.second == 40:
            print(
                f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} "
                f"开始检查15分钟成交量..."
            )
            for symbol in medium_symbols:
                volume_ma_15m(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(0.5)

        # ------------------------------------------------
        # 4小时K线监控，第3分钟开始
        # ------------------------------------------------
        if (
            now.hour % 4 == 0
            and now.minute == 3
            and now.second == 1
        ):
            print(
                f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} "
                f"开始检查4小时K线..."
            )
            for symbol in big_symbols:
                volume_ma_4h(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(5)

        # 完成一系列任务休眠1秒
        time.sleep(1)


# ============================================================
# 启动程序
# ============================================================
if __name__ == "__main__":

    proxy_ports = [
        42011, 42012, 42013, 42014,
        42002, 42003, 42004, 42021, 42022
    ]

    # 主监控任务使用的代理轮询器
    proxy_cycle = cycle(proxy_ports)

    # MA7观察池线程使用独立代理轮询器
    watch_proxy_cycle = cycle(proxy_ports)

    print("异常放量的定时程序已经启动...请勿关闭窗口！")

    schedule_volume_check(
        proxy_cycle,
        watch_proxy_cycle
    )
