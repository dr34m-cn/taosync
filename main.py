import asyncio
import logging
import os
import sys

from tornado.web import Application, RequestHandler, StaticFileHandler

from common import commonService, sqlInit
from common.config import CONFIG
from controller import systemController, jobController
from service.syncJob.jobService import initJob
from service.system import logJobService

# 初始化日志
commonService.setLogger()
# 后端配置
server = CONFIG['server']


class MainIndex(RequestHandler):
    def get(self):
        self.render(os.path.join(sys._MEIPASS if getattr(sys, 'frozen', False) else '.', "front/index.html"))


def make_app():
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
    # 以/svr/noAuth开头的请求无需鉴权，例如登录等
    return Application([
        (r"/svr/noAuth/login", systemController.Login),
        (r"/svr/user", systemController.User),
        (r"/svr/alist", jobController.Alist),
        (r"/svr/job", jobController.Job),
        (r"/", MainIndex),
        (r"/(.*)", StaticFileHandler,
         {"path": os.path.join(sys._MEIPASS if getattr(sys, 'frozen', False) else '.', "front")})
    ], cookie_secret=server['passwdStr'])


async def main():
    app = make_app()
    logger = logging.getLogger()
    app.listen(server['port'])
    logger.info(f"启动成功：http://0.0.0.0:%s/{server['port']}_/_Running at http://0.0.0.0:%s/{server['port']}")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
