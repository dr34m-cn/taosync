"""
@Author：dr34m
@Date  ：2024/8/16 14:26 
"""
import logging
import os

from common import sqlInit, commonService
from service.syncJob.jobService import initJob
from service.system import logJobService


def init():
    if not os.path.exists('data/log'):
        os.mkdir('data/log')
    # 初始化日志
    commonService.setLogger()
    logger = logging.getLogger()
    # 初始化数据库，没有则创建
    passwd = sqlInit.init_sql()
    if passwd is not None:
        msg = f"Password for admin_/_已为admin生成随机密码：{passwd}"
        print(msg, flush=True)
        logger.critical(msg)
    logger.info("初始化数据库完成_/_Initializing the database completed")
    # 启动日志文件与任务定时清理任务
    logJobService.startJob()
    # 修改异常中止状态，启动任务
    initJob()
