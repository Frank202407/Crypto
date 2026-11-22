import time
from datetime import datetime
from utils import get_kline, calculate_recent_average
from itertools import cycle
from notify import dingtalk_notify

# 币种列表，走势稳定的
big_symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "HYPEUSDT", "CLUSDT" ]

# 币种列表，有波动的
medium_symbols = ["BTCUSDT","ETHUSDT", "XRPUSDT", "SOLUSDT", "SUIUSDT", "ADAUSDT", "LINKUSDT" ]

# K线趋势的币种列表
trend_symbols = ["BTCUSDT"]

webhook = "https://oapi.dingtalk.com/robot/send?access_token=8a618559bef6178849439433ef9fe1e9a77a60eec9b45716acf18a1b6d4f8c05"


# 15分钟K线的异常放量
def volume_ma_15m(symbol, proxy_cycle):

    # 当前时间
    now = datetime.now()

    # 读取15分钟K线最新96根数据
    data = get_kline(symbol, "15m", 96, proxy_cycle)

    if not data:
        print(f"获取 {symbol} 的15分钟K线失败或返回为空")
        return   

    # 开盘价、收盘价、成交量转换数据类型
    opens = [float(k[1]) for k in data]   # 第2列是 开盘价
    closes = [float(k[4]) for k in data]  # 第5列是 收盘价
    volumes = [float(k[5]) for k in data]  # 取成交量（K线的第6个字段）

    if not volumes:
        return

    # 计算成交量的MA96
    volume_ma96 = calculate_recent_average(volumes, 96)
    if volume_ma96 is None:
        print(f"⚠️ {symbol} 的15分钟K线数据不足96根，跳过计算")
        return

    # 以收盘价计算价格的MA14
    price_ma14 = calculate_recent_average(closes, 14)

    # 获取当前15分钟K线的成交量（即该15分钟K线的部分成交量）
    current_volume = volumes[-1]
    current_open = opens[-1]
    current_close = closes[-1]


    # 开盘价相对MA14的偏离率
    open_deviation = 0
    # 收盘价相对MA14的偏离率
    close_deviation = 0

    # 默认的放量倍数是6倍
    volume_multiple = 6    
    # 成交量放大倍数
    volume_times = current_volume / volume_ma96
    # 15分钟K线开盘价偏离MA14的基准，做多默认偏离1.1%
    open_deviation_threshold = 0.011
    # 15分钟K线收盘价格偏离MA14和成交量放大倍数的乘积的基准，越大表示反抽动能越大
    price_volume_deviation_threshold = 0.025 * volume_multiple        

    
    # 开盘价低于MA14，说明当前15分钟K线处于下跌状态
    if (current_open < price_ma14):
        open_deviation = (price_ma14 - current_open) / current_open
        close_deviation = (price_ma14 - current_close) / current_close
    else:
        open_deviation = (current_open - price_ma14) / price_ma14
        close_deviation = (current_close - price_ma14) / price_ma14
        # 做空的情况下，15分钟K线开盘价偏离MA14的基准偏离5%
        open_deviation_threshold = 0.05
        price_volume_deviation_threshold = 0.075 * volume_multiple 


    # 超级异常放量情况，15分钟K线下跌5%，成交量放大10倍
    if (open_deviation * volume_times > 0.5):
            content=f"Lucky:🚨    ** {symbol} **\n {now.strftime('%H:%M:%S')}当前15分钟\n {volume_times:.1f}倍放量!\n 涨跌幅: {open_deviation:.1%}!\n"
            dingtalk_notify(webhook, content)
            return


    # 仓位大小，量能越大，代表分歧越大，开的仓位越大
    position = volume_times * 200


    # 开盘价与MA7已经有偏离，避免刚从整理平台选择方向的情况
    if(open_deviation > open_deviation_threshold) :

        # 放量反弹机会，下跌中收盘价高于开盘价，上涨中收盘价低于开盘价 
        if( (current_open < price_ma14 and current_open < current_close ) or (current_open > price_ma14 and current_open > current_close) ):
            content=f"Lucky:🚨    ** {symbol} **\n {now.strftime('%H:%M:%S')}当前15分钟\n {volume_times:.1f}倍放量!\n 有反弹可能!\n"

        # 放量反抽机会
        if close_deviation * volume_times >  price_volume_deviation_threshold:

            print(f"{symbol} 满足告警条件，准备发送")
            # 上一个时段已经通知过，就无需重复通知
            if(current_volume < volumes[-2] * 0.85):
                print(f"⚠️ {symbol} 本时段成交量比上一时段小，不再重复通知")
                return

            order = "多单"
            if(current_open > price_ma14) :
                order = "空单"

            number = position / current_close
            content=f"Lucky:🚨    ** {symbol} **\n {now.strftime('%H:%M:%S')}当前15分钟\n {volume_times:.1f}倍放量!\n 建议{order}开仓数量为{number:.2f}!\n"
            dingtalk_notify(webhook, content)



# BTC 5分钟K线爆量的监控
def volume_ma_5m(proxy_cycle):
    volume_surge("BTCUSDT", "5m", 96, 7, proxy_cycle)

# 1小时K线爆量的监控
def volume_ma_1h(symbol, proxy_cycle):
    volume_surge(symbol, "1h", 96, 9.5, proxy_cycle)

# 出现以下两种情况都返回true：
# a、当前时间之前的4个完整4小时K线周期的MA30分别为aa、bb、cc、dd（按发生时间顺序排列），
# 必须同时满足dd>cc、cc<bb、bb<aa，也就是MA30逆转下跌趋势；
# b、当前时间之前的4个完整4小时K线周期的MA7分别为A、B、C、D，MA30分别为aa、bb、cc、dd，
# 必须同时满足D>C、C<B、B<A、aa<bb、bb<cc、cc<dd，也就是MA7逆转下跌趋势，MA30持续保持上涨趋势。
def volume_ma_4h(symbol, proxy_cycle):
    # 读取4小时K线最新96根数据
    data = get_kline(symbol, "4h", 96, proxy_cycle)
    if not data or len(data) < 34:
        print(f"❌ {symbol} 数据不足以计算MA30")
        return
    # --------------------------------------------------
    # 去掉当前正在形成的4H K线
    # --------------------------------------------------
    completed = data[:-1]

    # --------------------------------------------------
    # 获取收盘价
    # --------------------------------------------------
    closes = [
        float(k[4])
        for k in completed
    ]

    # --------------------------------------------------
    # 计算最近4个完整周期的 MA7
    #
    # 每一个MA7都使用该时点之前的7根完整K线，
    # 包含该时点K线的收盘价。
    # --------------------------------------------------
    ma7_list = []
    for i in range(len(closes) - 4, len(closes)):
        ma7 = sum(closes[i - 6:i + 1]) / 7
        ma7_list.append(ma7)

    # --------------------------------------------------
    # 计算最近4个完整周期的 MA14
    # --------------------------------------------------
    ma14_list = []
    for i in range(len(closes) - 4, len(closes)):
        ma14 = sum(closes[i - 13:i + 1]) / 14
        ma14_list.append(ma14)        

    # --------------------------------------------------
    # 计算最近4个完整周期的 MA30
    # --------------------------------------------------
    ma30_list = []
    for i in range(len(closes) - 4, len(closes)):
        ma30 = sum(closes[i - 29:i + 1]) / 30
        ma30_list.append(ma30)

    # 最近4个MA：
    #
    # A = ma_list[0]
    # B = ma_list[1]
    # C = ma_list[2]
    # D = ma_list[3]
    #
    # --------------------------------------------------
    A, B, C, D = ma7_list
    E, F, G, H = ma14_list
    aa, bb, cc, dd = ma30_list

    # ==================================================
    # 情况 A
    #
    # MA30：
    #
    # aa -> bb -> cc -> dd
    #
    # dd > cc
    # cc < bb
    # bb < aa
    #
    # 即：
    # aa > bb > cc < dd
    # ==================================================
    condition_a = (
        dd > cc
        and cc < bb
        and bb < aa
        #and (
        #    D > C
        #    or H > G
        #)        
    )  

    # ==================================================
    # 情况 B
    #
    # MA7：
    #
    # A > B > C < D
    #
    # MA30：
    #
    # aa < bb < cc < dd
    # ==================================================
    condition_b = (
        D > C
        and C < B
        and B < A
        and aa < bb
        and bb < cc
        and cc < dd
    )

    # ==========================================
    # 当前最新完整4H K线的收盘价
    # ==========================================
    # 最新MA30
    current_ma30 = dd
    # 最新MA7
    current_ma7 = D
    # MA7与MA30的绝对偏差
    deviation = abs(current_ma7 - current_ma30) / current_ma30
    # MA30与MA7偏差不超过1.5%
    condition_price = deviation <= 0.015

    # --------------------------------------------------
    # 打印结果，方便调试
    # --------------------------------------------------
    # print(f"\n========== {symbol} 4H MA趋势 ==========")
    # print(f"MA7 : {A:.2f} -> {B:.2f} -> {C:.2f} -> {D:.2f}")
    # print(f"MA30: {aa:.2f} -> {bb:.2f} -> {cc:.2f} -> {dd:.2f}")
    # print(f"情况A（MA30反转）: {condition_a}")
    # print(f"情况B（MA7反转 + MA30上涨）: {condition_b}")
    # print(f"价格偏差<=1.5%: {condition_price}")

    if(condition_price):
        # 当前时间
        now = datetime.now()
        if(condition_a):
            content=f"Lucky:🚨  {now.strftime('%H:%M:%S')}  ** {symbol} **4小时K线MA30逆转下跌\n"
            dingtalk_notify(webhook, content)
        # elif(condition_b):
        #    content=f"Lucky:🚨  {now.strftime('%H:%M:%S')}  ** {symbol} **4小时K线MA7逆转下跌\n"
        #    dingtalk_notify(webhook, content)





# 判断K线的是否放量异常
# symbol 代币的永续合约名称
# interval K线周期，如15分钟K线、1小时K线
# period  均线周期，如MA14、MA96
# threshold 触发放量新号的成交量倍数阈值
def volume_surge(symbol, interval, period, threshold, proxy_cycle):

    # 当前时间
    now = datetime.now() 
    # 读取1小时K线最新period + 1根数据，包括当前时间未完成的K线
    data = get_kline(symbol, interval, period + 1, proxy_cycle)
    if not data:
        print(f"获取{symbol}的{interval} K线失败或返回为空")
        return
     # 去掉最后一根未完成K线
    completed = data[:-1] 
    volumes = [float(k[5]) for k in completed]  # 取成交量（K线的第6个字段）
    # 计算成交量的period周期的平均值
    volume_ma = calculate_recent_average(volumes, period)
    if volume_ma is None:
        print(f"⚠️ {symbol}的{interval} K线数据不足{period}根，跳过计算")
        return
    # 获取最新一根完整K线的成交量
    current_volume = volumes[-1] 
    # 成交量放大倍数
    volume_times = current_volume / volume_ma
    # print(f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} ** {symbol} **最近{interval}成交量{current_volume:.1f}   成交量均值{volume_ma:.1f}！\n")
    if(volume_times > threshold):
       content=f"Lucky:🚨    ** {symbol} **\n {now.strftime('%H:%M:%S')}\n 最近{interval}成交量放大{volume_times:.1f}倍！\n"
       dingtalk_notify(webhook, content)




# 定时执行任务：每小时的特定时刻检查成交量
def schedule_volume_check(proxy_cycle):

    while True:

        now = datetime.now()

        # 1小时K线监控，新的1小时15秒开始
        if( now.minute == 0 and now.second == 15 ):
            print(f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} 开始检查1小时成交量...")
            for symbol in big_symbols:
                volume_ma_1h(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(2) 

        # 15分钟K线监控，每个刻钟结束前的10秒钟开始
        # 监控波动适度的主流币
        if( now.minute in [14, 29, 44, 59] and now.second == 40):
            print(f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} 开始检查15分钟成交量...")
            for symbol in medium_symbols:
                volume_ma_15m(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(0.5)

        # 4小时K线监控，第3分钟开始
        if( now.hour % 4 == 0 and now.minute == 3 and now.second == 1):
            print(f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} 开始检查4小时K线...")
            for symbol in big_symbols:
                volume_ma_4h(symbol, proxy_cycle)
                # 每个代币取完数休息，避免请求频繁被币安屏蔽
                time.sleep(5)


        # 5分钟K线监控，新的5分钟的第3秒开始
        # if now.minute in [0, 5, 20, 25, 35, 40, 50, 55] and now.second == 2:
        #    # print(f"⚡ {now.strftime('%Y-%m-%d %H:%M:%S')} 监测BTC异常放量...") 
        #    volume_ma_5m(proxy_cycle)


        # 完成一系列任务休眠1秒
        time.sleep(1) 


# 启动定时任务
if __name__ == "__main__":
    proxy_ports = [42011, 42012, 42013, 42014, 42002, 42003, 42004, 42021, 42022]
    proxy_cycle = cycle(proxy_ports)  # 轮询器

    # 测试5分钟K线监控
    # volume_ma_5m(proxy_cycle)

    # 测试15分钟K线监控
    # for symbol in medium_symbols:
    #    volume_ma_15m(symbol, proxy_cycle)

    # 测试4小时K线监控
    # for symbol in big_symbols:
    #    volume_ma_4h(symbol, proxy_cycle)
    
    print(f"异常放量的定时程序已经启动...请勿关闭窗口！")

    schedule_volume_check(proxy_cycle)

