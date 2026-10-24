import requests
import re
import json
import os
import time
from bs4 import BeautifulSoup
from datetime import datetime

from notify import dingtalk_notify


# ==========================
# 配置
# ==========================

# 修改成你的钉钉机器人Webhook
WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=8a618559bef6178849439433ef9fe1e9a77a60eec9b45716acf18a1b6d4f8c05"


# 5分钟轮询
CHECK_INTERVAL = 300


CACHE_FILE = "upbit_cache.json"


UPBIT_NOTICE_URL = (
    "https://upbit.com/service_center/notice"
)


HEADERS = {
    "User-Agent":
        "Mozilla/5.0"
}



# ==========================
# 获取公告列表
# ==========================

def get_notice_list():
    try:
        response = requests.get(
            UPBIT_NOTICE_URL,
            headers=HEADERS,
            timeout=10
        )
        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )
        notices = []
        for a in soup.find_all("a"):
            title = a.get_text(
                strip=True
            )
            url = a.get(
                "href"
            )
            if not title or not url:
                continue
            if url.startswith("/"):
                url = (
                    "https://upbit.com"
                    +
                    url
                )
            notices.append(
                {
                    "title": title,
                    "url": url
                }
            )
        return notices
    
    except Exception as e:
        print(
            "获取公告失败:",
            e
        )
        return []



# ==========================
# 判断是否新币上线公告
# ==========================

def is_listing_notice(title):
    keywords = [
        "거래지원",
        "마켓 지원",
        "Trading Support",
        "Market Support",
        "상장"
    ]

    for key in keywords:
        if key.lower() in title.lower():
            return True
    return False



# ==========================
# 获取公告详情
# ==========================

def get_notice_content(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=10
        )
        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )
        return soup.get_text(
            " ",
            strip=True
        )

    except Exception as e:
        print(
            "获取详情失败:",
            e
        )
        return ""



# ==========================
# 自动解析币种 symbol
# ==========================

def parse_symbol(text):
    patterns = [
        # BTC(BTC)
        r"\(([A-Z0-9]{2,15})\)",
        # [BTC]
        r"\[([A-Z0-9]{2,15})\]",
        # Symbol: BTC
        r"Symbol\s*[:：]\s*([A-Z0-9]+)",
        # Ticker: BTC
        r"Ticker\s*[:：]\s*([A-Z0-9]+)"
    ]


    for pattern in patterns:
        result = re.findall(
            pattern,
            text
        )
        if result:
            return result[0]
    return None



# ==========================
# 自动解析交易市场
# ==========================

def parse_market(text):
    markets = []
    for market in [
        "KRW",
        "BTC",
        "USDT"
    ]:
        if market in text:
            markets.append(
                market
            )

    return markets



# ==========================
# 加载缓存
# ==========================

def load_cache():

    if os.path.exists(
        CACHE_FILE
    ):
        try:
            with open(
                CACHE_FILE,
                "r",
                encoding="utf-8"
            ) as f:
                return json.load(f)


        except:
            return []
    return []



# ==========================
# 保存缓存
# ==========================

def save_cache(cache):
    with open(
        CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            cache,
            f,
            ensure_ascii=False,
            indent=2
        )



# ==========================
# 发送通知
# ==========================

def send_alert(
        symbol,
        markets,
        title,
        url):
    message = f"""

🚨 Upbit 新币上线提醒

币种:
{symbol}

交易市场:
{",".join(markets)}

公告:
{title}

时间:
{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

链接:
{url}

"""

    dingtalk_notify(
        WEBHOOK,
        message
    )



# ==========================
# 主循环
# ==========================

def main():


    cache = load_cache()


    print("====================")
    print("Upbit监控启动")
    print("轮询周期: 5分钟")
    print("====================")


    while True:


        try:


            notices = get_notice_list()


            print(
                datetime.now(),
                "检查公告数量:",
                len(notices)
            )


            for notice in notices[:30]:


                title = notice["title"]

                url = notice["url"]



                # 过滤普通公告
                if not is_listing_notice(title):

                    continue



                # URL去重
                if url in cache:

                    continue



                print(
                    "发现新公告:",
                    title
                )


                content = get_notice_content(
                    url
                )


                full_text = (
                    title
                    +
                    " "
                    +
                    content
                )


                symbol = parse_symbol(
                    full_text
                )


                markets = parse_market(
                    full_text
                )



                if symbol:


                    send_alert(
                        symbol,
                        markets,
                        title,
                        url
                    )


                else:


                    dingtalk_notify(
                        WEBHOOK,
                        f"""
⚠️ Upbit新币公告

无法自动解析symbol

标题:
{title}

链接:
{url}
"""
                    )



                # 加入缓存
                cache.append(
                    url
                )


                # 最大200条
                cache = cache[-200:]


                save_cache(
                    cache
                )



        except Exception as e:


            print(
                "运行异常:",
                e
            )


        time.sleep(
            CHECK_INTERVAL
        )



if __name__ == "__main__":

    main()