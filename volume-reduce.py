import time
import requests
import threading
from datetime import datetime, timedelta
from notify import notify
from itertools import cycle
from utils import get_kline


# 币种列表
symbols = ["TIAUSDT", "SUIUSDT", "ARBUSDT", "SOLUSDT", "AAVEUSDT", "XRPUSDT", "LTCUSDT", "DOGEUSDT",  "ADAUSDT", "ETHUSDT", "BNBUSDT", "BTCUSDT"]


# 判断价格均线是否处于上升或者下降趋势
def check_ma_trend(data, period, days=3, direction="up"):
    """
    检查指定 MA 均线是否呈现连续 `days` 天的上升或下降趋势。
    :param data: K 线数据列表
    :param period: 均线周期（如 14, 30）
    :param days: 检查最近连续的天数（默认 3 天）
    :param direction: "up" 表示上升趋势，"down" 表示下降趋势
    :return: True 或 False
    """
    if len(data) < period + days:
        print(f"❌ 数据不足以计算 MA{period} 的 {days} 天趋势")
        return False

    closes = [float(k[4]) for k in data]
    ma_list = []

    start_index = -days
    end_index = 0  # 表示到最后一项

    for i in range(start_index, end_index):
        idx = len(closes) + i
        if idx - period < 0:
            print(f"❌ 索引 {idx} 数据不足以计算MA{period}")
            continue
        ma = sum(closes[idx-period:idx+1]) / period
        ma_list.append(ma) 

    if direction == "up":
        return ma_list[-3] < ma_list[-2] < ma_list[-1]
    elif direction == "down":
        return ma_list[-3] > ma_list[-2] > ma_list[-1]
    else:
        raise ValueError("direction 参数必须为 'up' 或 'down'")


# 当天成交量不足过去6天平均的50%
def is_volume_low_vs_past6(data: list) -> bool:
    """
    判断当天成交量是否低于过去6天成交量均值的50%
    :param data: K线数据，按时间升序排列（老 → 新）
    :return: True 表示当天成交量显著低；False 表示正常或高成交量
    """
    if not data or len(data) < 7:
        print("❌ 数据不足以计算过去6天成交量均量")
        return False

    volumes = [float(k[5]) for k in data]  # 成交量字段
    past6_avg = sum(volumes[-7:-1]) / 6  # 过去6天（不含当天）
    today_volume = volumes[-1]
    # print(f"今天成交量{today_volume:.1f}")
    # print(f"过去6天成交量均值{past6_avg:.1f}")
    return today_volume < 0.8 * past6_avg


# 极度缩量，代表趋势的延续
def trend(symbol, proxy_cycle):

    # 读取K线日线最新60根数据
    data = get_kline(symbol, "1d", 60, proxy_cycle)
    # 缩量调整
    if(is_volume_low_vs_past6(data)):
        print(f"{symbol}成交缩量")
        # 价格多头走势，价格的MA14和MA30同时上升
        if(check_ma_trend(data, 14, 3, "up") and check_ma_trend(data, 30, 3, "up")):
            print(f"✅ {symbol} MA14 和 MA30 都处于上升趋势")
            message=f"{symbol}\n 可开多单"
            notify(message)
        # 价格空头走势，价格的MA14和MA30同时下降
        elif(check_ma_trend(data, 14, 3, "down") and check_ma_trend(data, 30, 3, "down")):
            print(f"❌ {symbol} MA14 和 MA30 都处于下降趋势")
            message=f"{symbol}\n 可开空单"
            notify(message)


# 定时执行任务：每天7点58分30秒
def schedule_volume_check(proxy_cycle):

    while True:
        now = datetime.now()

        # 每隔一小时更新一下K线日线趋势
        if now.hour == 7 and now.minute == 58 and  now.second == 30:
            print(f"⚡ {now.strftime('%H:%M:%S')} 每天的日线趋势延续监测...")
            for symbol in symbols:
                trend(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(1)                

        time.sleep(0.3)


# 启动定时任务
if __name__ == "__main__":
    proxy_ports = [42010, 42011, 42013, 42014, 42002, 42004]
    proxy_cycle = cycle(proxy_ports)  # 轮询器
    print(f"成交缩量的定时程序已经启动...请勿关闭窗口！")
    # schedule_volume_check(proxy_cycle)
    trend("ETHUSDT", proxy_cycle)  