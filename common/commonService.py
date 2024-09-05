import datetime
import json
import logging
import sys

from common.LNG import G
from common.config import getConfig


# 日志规定
def setLogger(cusLevel=None):
    cfg = getConfig()
    level_list = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]
    level_int = cfg['server']['log_level']
    consoleLevelInt = cfg['server']['console_level']
    logger = logging.getLogger()
    if cusLevel is None:
        level = level_list[level_int]
    else:
        level = level_list[cusLevel]
    consoleLevel = level_list[consoleLevelInt]
    logger.setLevel(level=level)
    log_file = 'data/log/sys_%s.log' % (datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d'))
    handlersLen = len(logger.handlers)
    if handlersLen == 1 or handlersLen == 0:
        # 仅在起始是长度为1或0，之后均为2
        if handlersLen == 1:
            logger.removeHandler(logger.handlers[0])
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        handlerStream = logging.StreamHandler()
        handlerStream.setLevel(consoleLevel)
        handlerStream.setFormatter(formatter)
        logger.addHandler(handlerStream)
    if handlersLen > 1:
        logger.removeHandler(logger.handlers[1])
    handlerFile = logging.FileHandler(log_file, encoding='utf-8')
    handlerFile.setLevel(level)
    formatter = logging.Formatter('%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s')
    handlerFile.setFormatter(formatter)
    logger.addHandler(handlerFile)


def get_post_data(self):
    post_data = self.request.arguments
    post_data = {x: post_data.get(x)[0].decode("utf-8") for x in post_data.keys()}
    if not post_data:
        post_data = self.request.body.decode('utf-8')
        if post_data and post_data != '':
            post_data = json.loads(post_data)
        else:
            post_data = {}
    return post_data


def result_map(*dt):
    # code：200-成功，500-失败
    # 成功 ResultMap() or ResultMap(data) or ResultMap(msg, 200)
    # 失败 ResultMap(msg, 500)
    lenDt = len(dt)
    result = {
        "code": 200 if lenDt <= 1 else dt[1],
        "data": dt[0] if lenDt == 1 else None,
        "msg": G('success') if lenDt <= 1 else dt[0]
    }
    return json.dumps(result, ensure_ascii=False)
