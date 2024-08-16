"""
@Author：dr34m
@Date  ：2024/4/24 14:07 
"""
import logging
import os
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from common.LNG import G
from common.commonService import setLogger
from common.config import getConfig
from mapper.jobMapper import deleteJobTaskByRunTime

CONFIG = getConfig()
logSave = CONFIG['server']['logSave']
taskSave = CONFIG['server']['taskSave']


def logClearJob():
    if logSave > 0:
        saveLogList = []
        dayNow = int(time.time())
        for i in range(logSave):
            dateName = time.strftime('%Y-%m-%d', time.localtime(dayNow))
            saveLogList.append(f'sys_{dateName}.log')
            dayNow -= 60 * 60 * 24
        for file in os.listdir('data/log'):
            if file.endswith('.log') and file not in saveLogList:
                logger = logging.getLogger()
                try:
                    os.remove(f'data/log/{file}')
                    logger.info(G('log_del_success').format(file))
                except Exception as e:
                    logger.error(G('log_del_fail').format(file, str(e)))
                    logger.exception(e)
    if taskSave > 0:
        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deleteJobTaskByRunTime(int(midnight.timestamp()) - taskSave * 86400)


def logChangeJob():
    setLogger()


def startJob():
    logger = logging.getLogger()
    logger.info(G('log_rename_start'))
    startChangeScheduler()
    if logSave == 0:
        logger.info(G('keep_all_log'))
    if taskSave == 0:
        logger.info(G('keep_all_task'))
    if logSave > 0 or taskSave > 0:
        logger.info(G('clear_task_start'))
        startClearScheduler()


def startClearScheduler():
    logClearJob()
    scheduler = BackgroundScheduler()
    scheduler.add_job(logClearJob, 'cron', hour=0, minute=0, second=10)
    scheduler.start()


def startChangeScheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(logChangeJob, 'cron', hour=0, minute=0, second=0)
    scheduler.start()
