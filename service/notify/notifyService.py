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


def sendNotify(notify, title, content):
    """
    发送通知
    :param notify: 通知配置 {'id': 1, 'enable': 1, 'method': 0, // 0-自定义；1-server酱；待扩展更多
    'params': None, 'createTime': 1732179402}
    :param title: 通知标题
    :param content: 通知内容
    :return:
    method: 不同方法params结构
        0: {'url': 'http://xxx.xx/api', 'method': 'POST', 'contentType': 'application/json',
            'needContent': True, 'titleName': 'title', 'contentName': 'content'}
        1: {'sendKey': 'xxx'}
    """
    timeout = (5, 30)
    params = json.loads(notify['params'])
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
        r = sc.send(params['sendKey'], title, content)
        if r.status_code != 200:
            raise Exception(r.text)
        else:
            scRs = r.json()
            if scRs['code'] != 0:
                raise Exception(scRs['error'])
    else:
        raise Exception("Wrong method")
