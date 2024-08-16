"""
@Author：dr34m
@Date  ：2024/7/9 9:29 
"""
import logging

from common.LNG import G
from mapper.alistMapper import getAlistById, addAlist, removeAlist, getAlistList, updateAlist
from service.alist.alistClient import AlistClient

# alist客户端列表，key为aId-{alistId},value为AlistClient
alistClientList = {}


def getClientList():
    """
    获取客户端列表
    :return:
    """
    clientList = getAlistList()
    for client in clientList:
        del client['token']
    return clientList


def getClientById(alistId):
    """
    通过id获取客户端
    :param alistId:
    :return:
    """
    key = f'aId-{alistId}'
    global alistClientList
    if key in alistClientList:
        return alistClientList[key]
    alist = getAlistById(alistId)
    client = AlistClient(alist['url'], alist['token'], alistId)
    alistClientList[key] = client
    return client


def updateClient(alist):
    """
    更新客户端
    :param alist: {
        'id': 1,
        'remark': 'remark',
        'url': 'xxx',
        'userName': 'xxx',
        'passwd': 'xxx'
    }
    """
    alistId = alist['id']
    if alist['remark'] is not None and alist['remark'].strip() == '':
        alist['remark'] = None
    if 'token' in alist:
        if alist['token'] is None:
            del alist['token']
        else:
            alist['token'] = alist['token'].strip()
            if alist['token'] == '':
                del alist['token']
    if alist['url'].endswith('/'):
        alist['url'] = alist['url'][:-1]
    alistOld = getAlistById(alistId)
    if alistOld['url'] != alist['url'] or 'token' in alist:
        if 'token' not in alist:
            # 令牌必填，防止通过修改地址为钓鱼地址的方式窃取令牌
            raise Exception(G('without_token'))
        client = AlistClient(alist['url'], alist['token'], alistId)
        alistClientList[f'aId-{alistId}'] = client
    updateAlist(alist)


def addClient(alist):
    """
    新增客户端
    :param alist: {
        'remark': 'remark',
        'url': 'xxx',
        'token': 'xxx'
    }
    """
    if alist['remark'] is not None and alist['remark'].strip() == '':
        alist['remark'] = None
    if alist['url'].endswith('/'):
        alist['url'] = alist['url'][:-1]
    try:
        client = AlistClient(alist['url'], alist['token'])
        alistId = addAlist({
            'remark': alist['remark'],
            'url': alist['url'],
            'userName': client.user,
            'token': alist['token']
        })
        client.updateAlistId(alistId)
    except Exception as e:
        logger = logging.getLogger()
        logger.error(G('add_alist_client_fail').format(str(e)))
        raise Exception(e)
    else:
        global alistClientList
        key = f'aId-{alistId}'
        alistClientList[key] = client


def removeClient(alistId):
    """
    删除客户端
    :param alistId:
    """
    key = f'aId-{alistId}'
    global alistClientList
    if key in alistClientList:
        del alistClientList[key]
    removeAlist(alistId)


def getChildPath(alistId, path):
    """
    获取子目录列表
    :param alistId:
    :param path:
    :return:
    """
    client = getClientById(alistId)
    return client.filePathList(path)
