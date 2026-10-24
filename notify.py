import requests
import winsound
import threading

# 通知到钉钉的群里面
def send_dingtalk_msg(webhook,content):  

    msg = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }

    headers = {'Content-Type': 'application/json'}
    response = requests.post(webhook, json=msg, headers=headers)  
    # print(response.text) 


# 蜂鸣器函数
def beep_for_5s():
    """持续5秒的蜂鸣声（Windows）"""
    try:
        duration = 5000   # 持续10秒（10000毫秒）
        frequency = 1000  # 1000Hz高频警报音
        winsound.Beep(frequency, duration)
    except Exception as e:
        print(f"蜂鸣失败: {e}") 

# 发出通知
def dingtalk_notify(webhook, content):

    # 电脑屏幕打印日志
    print(content)
    # 通知到手机钉钉
    send_dingtalk_msg(webhook, content)
    # 电脑声音告警
    # threading.Thread(target=beep_for_5s).start() 

if __name__ == "__main__":
    # 钉钉群通知机器人的API地址
    webhook = "https://oapi.dingtalk.com/robot/send?access_token=75b8fc4ce4e1e72a378175408c026243f0a554f2033c6148c942346ef2cb1cb0"    
    dingtalk_notify(webhook,"Alpha：通知测试")


