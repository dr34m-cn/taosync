import datetime
import json
import logging
import os

from common.config import getConfig

CONFIG = getConfig()
level_int = CONFIG['server']['logLevel']


# 日志规定
def setLogger(cusLevel=None):
    if not os.path.exists('data/log'):
        os.mkdir('data/log')
    level_list = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]
    logger = logging.getLogger()
    if cusLevel is None:
        level = level_list[level_int]
    else:
        level = level_list[cusLevel]
    logger.setLevel(level=level)
    log_file = 'data/log/sys_%s.log' % (datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d'))
    if len(logger.handlers) > 1:
        logger.removeHandler(logger.handlers[1])
    handler = logging.FileHandler(log_file, encoding='utf-8')
    handler.setLevel(level)
    formatter = logging.Formatter('%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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
        "msg": "操作成功" if lenDt <= 1 else dt[0]
    }
    return json.dumps(result, ensure_ascii=False)
