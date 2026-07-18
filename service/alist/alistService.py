"""
@Author：dr34m
@Date  ：2024/7/9 9:29 
"""
import logging

from common.LNG import G
from mapper import jobMapper
from mapper.alistMapper import getAlistById, addAlist, removeAlist, getAlistList, updateAlist
from mapper.storageMapper import getMountList
from service.alist.alistClient import AlistClient
from service.engine import engineService

def getClientList():
    """
    获取客户端列表
    :return:
    """
    clientList = getAlistList()
    for client in clientList:
        client.pop('token', None)
        if client.get('engineType') == 'taosync':
            client['displayName'] = 'TaoSync'
            client['directoryCount'] = len(getMountList(client['id']))
        else:
            client['displayName'] = client.get('remark') or client.get('url')
    return clientList


def getClientById(alistId):
    """
    通过id获取客户端
    :param alistId:
    :return:
    """
    return engineService.getClientById(alistId)


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
    if alistOld.get('protected') == 1:
        raise Exception(G('builtin_engine_protected'))
    connectionChanged = alistOld['url'] != alist['url'] or 'token' in alist
    if connectionChanged:
        if 'token' not in alist:
            # 令牌必填，防止通过修改地址为钓鱼地址的方式窃取令牌
            raise Exception(G('without_token'))
        AlistClient(alist['url'], alist['token'], alistId)
    updateAlist(alist)
    if connectionChanged:
        jobMapper.clearSourceSnapshotsByEngine(int(alistId))
    engineService.invalidateClient(alistId)


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
        engineService.invalidateClient(alistId)


def removeClient(alistId):
    """
    删除客户端
    :param alistId:
    """
    alist = getAlistById(alistId)
    if alist.get('protected') == 1:
        raise Exception(G('builtin_engine_protected'))
    engineService.invalidateClient(alistId)
    removeAlist(alistId)


def getChildPath(alistId, path):
    """
    获取子目录列表
    :param alistId:
    :param path:
    :return:
    """
    return engineService.getChildPath(alistId, path)
