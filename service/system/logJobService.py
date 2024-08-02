"""
@Author：dr34m
@Date  ：2024/4/24 14:07 
"""
import logging
import os
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

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
                    os.remove(f'log/{file}')
                    logger.info(f"日志文件{file}已被成功删除_/_"
                                f"The log file {file} has been successfully deleted")
                except Exception as e:
                    logger.error(f"日志文件{file}删除失败，原因为：{str(e)}_/_"
                                 f"Failed to delete log file {file}, reason: {str(e)}")
                    logger.exception(e)
    if taskSave > 0:
        now = datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deleteJobTaskByRunTime(int(midnight.timestamp()) - taskSave * 86400)


def logChangeJob():
    setLogger()


def startJob():
    logger = logging.getLogger()
    logger.info("日志定时更名任务启动成功_/_The log scheduled renaming task was started successfully")
    startChangeScheduler()
    if logSave == 0:
        logger.info("日志保留时间为0，将保留所有日志_/_The log retention time is 0, all logs will be retained.")
    if taskSave == 0:
        logger.info("任务保留时间为0，将保留所有任务_/_The task retention time is 0, all tasks will be retained.")
    if logSave > 0 or taskSave > 0:
        logger.info("定时清理任务启动成功_/_The scheduled cleanup task was started successfully")
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
