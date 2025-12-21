import json

import requests

from common.LNG import G
from mapper import notifyMapper
from service.notify import sc


def getNotifyList(needEnable=False):
    """
    获取通知配置列表
    :param needEnable: 是否启用
    :return:
    """
    return notifyMapper.getNotifyList(needEnable)


def addNewNotify(notify):
    """
    新增通知配置
    :param notify:
    :return:
    """
    notifyMapper.addNotify(notify)


def editNotify(notify):
    """
    编辑通知配置
    :param notify:
    :return:
    """
    notifyMapper.editNotify(notify)


def updateNotifyStatus(notifyId, enable):
    """
    更新通知配置启用状态
    :param notifyId:
    :param enable:
    :return:
    """
    notifyMapper.updateNotifyStatus(notifyId, enable)


def deleteNotify(notifyId):
    """
    删除
    :param notifyId:
    :return:
    """
    notifyMapper.deleteNotify(notifyId)


def testNotify(notify):
    """
    测试通知配置
    :return:
    """
    sendNotify(notify, 'TaoSync Test',
               G('notify_test_msg'))


def sendNotify(notify, title, content, needNotSync=False):
    """
    发送通知
    :param notify: 通知配置 {'id': 1, 'enable': 1, 'method': 0, // 0-自定义；1-server酱；2-钉钉群机器人；3-企业微信应用消息；4-Lark群机器人；待扩展更多
    'params': None, 'createTime': 1732179402}
    :param title: 通知标题
    :param content: 通知内容
    :param needNotSync: 是否是无需同步
    :return:
    method: 不同方法params结构
        0: {'url': 'http://xxx.xx/api', 'method': 'POST', 'contentType': 'application/json',
            'needContent': True, 'titleName': 'title', 'contentName': 'content', 'notSendNull': False}
        1: {'sendKey': 'xxx', 'notSendNull': False}
        2: {'url': '', 'notSendNull': False}
        3: {'corpid': '', 'agentid': '', 'corpsecret': '', 'notSendNull': False}
        4: {'url': '', 'notSendNull': False}
    """
    timeout = (10, 30)
    params = json.loads(notify['params'])
    # 如果配置了不发送空消息，并且当前状态为无需同步，则不发送通知
    if 'notSendNull' in params and params['notSendNull'] and needNotSync:
        return
    if notify['method'] == 0:
        reqData = {
            params['titleName']: title
        }
        if params['needContent']:
            reqData[params['contentName']] = content
        if params['method'] == 'GET':
            r = requests.get(params['url'], params=reqData, timeout=timeout)
        elif params['method'] == 'POST' or params['method'] == 'PUT':
            if params['contentType'] == 'application/json':
                r = requests.request(params['method'], params['url'], json=reqData, timeout=timeout)
            elif params['contentType'] == 'application/x-www-form-urlencoded':
                r = requests.request(params['method'], params['url'], data=reqData, timeout=timeout)
            else:
                raise Exception("ContentType not allowed")
        else:
            raise Exception("Method not supported")
        if r.status_code != 200:
            raise Exception(r.text)
    elif notify['method'] == 1:
        # server酱
        sc.send(params['sendKey'], title, timeout, content)
    elif notify['method'] == 2:
        # 钉钉群机器人
        r = requests.post(params['url'], json={
            'msgtype': 'text',
            'text': {
                'content': f'{title}\n\n{content}'
            }
        }, timeout=timeout)
        rst = r.json()
        if rst['errcode'] != 0:
            raise Exception(rst['errmsg'])
    elif notify['method'] == 3:
        # 企业微信应用消息
        # 获取access_token
        token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={params['corpid']}&corpsecret={params['corpsecret']}"
        token_response = requests.get(token_url, timeout=timeout)
        token_data = token_response.json()
        
        if token_data['errcode'] != 0:
            raise Exception(f"获取企业微信access_token失败: {token_data['errmsg']}")
            
        access_token = token_data['access_token']
        
        # 发送消息
        send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
        message_data = {
            "touser": params.get('touser', '@all'),
            "msgtype": "text",
            "agentid": params['agentid'],
            "text": {
                "content": f"{title}\n-------------------\n{content}"
            },
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 0
        }
        
        r = requests.post(send_url, json=message_data, timeout=timeout)
        rst = r.json()
        if rst['errcode'] != 0:
            raise Exception(f"发送企业微信消息失败: {rst['errmsg']}")
    elif notify['method'] == 4:
        # Lark群机器人
        r = requests.post(params['url'], json={
            'msg_type': 'interactive',
            'card': {
                'config': {
                    'wide_screen_mode': True
                },
                'elements': [{
                    'tag': 'markdown',
                    'content': content
                }],
                'header': {
                    'template': 'blue',
                    'title': {
                        'content': title,
                        'tag': 'plain_text'
                    }
                }
            }
        }, timeout=timeout)
        rst = r.json()
        if rst['code'] != 0:
            raise Exception(f"Lark群机器人发送消息失败: {rst['msg']}")
    else:
        raise Exception("Wrong method")
