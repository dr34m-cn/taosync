import asyncio
import logging
import os
import sys
from pathlib import Path

from service.system import updateLauncher

if __name__ == '__main__' and getattr(sys, 'frozen', False):
    if sys.argv[1:2] != [updateLauncher.WORKER]:
        sys.exit(updateLauncher.supervise(updateLauncher.executable(), sys.argv[1:]))
    del sys.argv[1]

from tornado.web import Application, RequestHandler, StaticFileHandler

from common.config import getConfig
from common.LNG import G
from controller import systemController, jobController, notifyController, updateController
from service.system import onStart
from service.system.httpsListener import HttpsListener


class MainIndex(RequestHandler):
    def get(self):
        self.set_header('Cache-Control', 'no-store')
        self.render(os.path.join(frontendPath, "front/index.html"))


def make_app():
    # 以/svr/noAuth开头的请求无需鉴权，例如登录等
    return Application([
        (r"/svr/noAuth/login", systemController.Login),
        (r"/svr/user", systemController.User),
        (r"/svr/settings", systemController.Settings),
        (r"/svr/settings/https", systemController.Https),
        (r"/svr/settings/api-key", systemController.ApiKey),
        (r"/svr/settings/update", updateController.UpdateInfo),
        (r"/svr/settings/update/check", updateController.UpdateCheck),
        (r"/svr/settings/update/upload", updateController.ProgramUpload),
        (r"/svr/language", systemController.Language),
        (r"/svr/alist", jobController.Alist),
        (r"/svr/storage", jobController.Storage),
        (r"/svr/job", jobController.Job),
        (r"/svr/job/links", jobController.JobLinks),
        (r"/svr/notify", notifyController.Notify),
        (r"/(?:index\.html)?", MainIndex),
        (r"/(.*)", StaticFileHandler,
         {"path": os.path.join(frontendPath, "front")})
    ], cookie_secret=server['passwdStr'])


async def main():
    app = make_app()
    logger = logging.getLogger()
    restart = asyncio.Event()
    http = app.listen(server['port'])
    https = app.settings['https_listener'] = HttpsListener(app, http_port=int(server['port']))
    https.restore()
    if getattr(sys, 'frozen', False) and os.getenv('TAO_UPDATE_CHANNEL'):
        app.settings['restart_for_update'] = restart.set
        (Path(os.environ['TAO_UPDATE_CHANNEL']) / 'ready').touch()
    successMsg = G('running_success').format(url=f"http://127.0.0.1:{server['port']}/")
    logger.critical(successMsg)
    await restart.wait()
    http.stop()
    if https.server:
        https.server.stop()
        await https.server.close_all_connections()
    await http.close_all_connections()
    logging.shutdown()
    os._exit(updateLauncher.RESTART)  # Do not wait for idle scheduler/executor threads.


if __name__ == "__main__":
    onStart.init()
    cfg = getConfig()
    frontendPath = sys._MEIPASS if getattr(sys, 'frozen', False) else '.'
    # 后端配置
    server = cfg['server']
    asyncio.run(main())
