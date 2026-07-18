import threading

from mapper.alistMapper import getEngineById
from service.alist.alistClient import AlistClient
from service.engine.taosyncClient import TaoSyncClient


clientList = {}
clientLock = threading.Lock()
engineLocks = {}


def _getEngineLock(engineId):
    with clientLock:
        lock = engineLocks.get(engineId)
        if lock is None:
            lock = threading.Lock()
            engineLocks[engineId] = lock
        return lock


def getClientById(engineId):
    engineId = int(engineId)
    with clientLock:
        client = clientList.get(engineId)
        if client is not None:
            return client
    # Network construction (AlistClient calls /api/me) is serialized only for
    # this engine, so one offline AList cannot block TaoSync or other engines.
    with _getEngineLock(engineId):
        with clientLock:
            client = clientList.get(engineId)
            if client is not None:
                return client
        engine = getEngineById(engineId)
        if engine.get("engineType") == "taosync":
            client = TaoSyncClient(engineId)
        else:
            client = AlistClient(engine["url"], engine["token"], engineId)
        with clientLock:
            clientList[engineId] = client
        return client


def invalidateClient(engineId):
    engineId = int(engineId)
    with _getEngineLock(engineId):
        with clientLock:
            clientList.pop(engineId, None)


def getChildPath(engineId, path):
    return getClientById(engineId).filePathList(path)
