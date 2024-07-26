import json
import logging

from tornado.web import RequestHandler

from common import commonService
from service.system import userService

cookieName = 'tao_sync'


class BaseHandler(RequestHandler):
    def get_current_user(self):
        return json.loads(self.get_signed_cookie(cookieName))


def handle_request(func):
    def wrapper(self):
        uri = self.request.uri
        user = self.get_signed_cookie(cookieName)
        trueUser = None
        if not uri.startswith('/svr/noAuth'):
            if user is None:
                self.clear_cookie(cookieName)
                msg = commonService.result_map("请登录_/_Please sign in", 401)
                self.write(msg)
                return
            else:
                cUser = json.loads(user)
                trueUser = userService.getUser(cUser['id'], None)
                if ('passwd' not in cUser
                        or 'userName' not in cUser
                        or trueUser['passwd'] != cUser['passwd']
                        or trueUser['userName'] != cUser['userName']):
                    msg = commonService.result_map("登录失效_/_Login failure", 401)
                    self.write(msg)
                    return
        try:
            req = commonService.get_post_data(self)
            if user:
                req['__user'] = trueUser
            msg = commonService.result_map(func(self, req))
        except Exception as e:
            msg = commonService.result_map(str(e), 500)
            logger = logging.getLogger()
            logger.exception(e)
        self.write(msg)

    return wrapper
