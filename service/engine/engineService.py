import threading

from mapper.alistMapper import getEngineById
from service.alist.alistClient import AlistClient
from service.engine.taosyncClient import TaoSyncClient


clientList = {}
clientLock = threading.Lock()
engineLocks = {}
copyLimiters = {}


class CopyLimiter:
    def __init__(self, limit):
        self.limit = limit
        self.active = 0
        self.lock = threading.Lock()

    def tryAcquire(self):
        with self.lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self):
        with self.lock:
            self.active -= 1


def getCopyLimiter(engineId):
    engineId = int(engineId)
    with _getEngineLock(engineId):
        if engineId not in copyLimiters:
            engine = getEngineById(engineId)
            copyLimiters[engineId] = CopyLimiter(int(engine.get("copyConcurrency") or 5))
        return copyLimiters[engineId]


def validateCopyConcurrency(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 100:
        raise ValueError("copy concurrency must be an integer between 1 and 100")
    return int(value)


def updateCopyConcurrency(engineId, value):
    from mapper.alistMapper import updateCopyConcurrency as persist

    value = validateCopyConcurrency(value)
    engineId = int(engineId)
    limiter = getCopyLimiter(engineId)
    with limiter.lock:
        persist(engineId, value)
        limiter.limit = value


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
