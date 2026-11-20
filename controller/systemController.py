from concurrent.futures import ThreadPoolExecutor

from tornado.concurrent import run_on_executor

from common.LNG import language
from common.config import getSettings, updateSettings
from controller.baseController import BaseHandler, handle_request, cookieName
from service.system import apiKey, userService


class Login(BaseHandler):
    # 密码哈希计算较慢，放到线程池执行，避免阻塞事件循环
    executor = ThreadPoolExecutor(2)

    @run_on_executor
    @handle_request
    def post(self, req):
        user = userService.checkPwd(None, req['passwd'], req['userName'],
                                    clientKey=self.request.remote_ip)
        self.set_session_cookie(user)
        userReturn = user.copy()
        userReturn.pop('passwd', None)
        userReturn.pop('sqlVersion', None)
        return userReturn

    @run_on_executor
    @handle_request
    def put(self, req):
        return userService.resetPasswd(req['userName'], req['key'], req.get('passwd', None))

    @handle_request
    def delete(self, req):
        self.clear_cookie(cookieName)


class User(BaseHandler):
    executor = ThreadPoolExecutor(1)

    @handle_request
    def get(self, req):
        user = req['__user']
        return user

    @run_on_executor
    @handle_request
    def put(self, req):
        if 'userName' in req:
            user = userService.editUserName(req['__user']['id'], req['userName'])
            if 'Authorization' not in self.request.headers:
                self.set_session_cookie(user)
            return {key: value for key, value in user.items() if key not in ('passwd', 'sqlVersion')}
        userService.editPasswd(req['__user']['id'], req['passwd'], req['oldPasswd'])


class Settings(BaseHandler):
    executor = ThreadPoolExecutor(1)

    @handle_request
    def get(self, req):
        return getSettings()

    @run_on_executor
    @handle_request
    def put(self, req):
        return updateSettings(req['settings'])


class ApiKey(BaseHandler):
    def set_default_headers(self):
        self.set_header('Cache-Control', 'no-store')

    @handle_request
    def get(self, req):
        return apiKey.status()

    @handle_request
    def put(self, req):
        return apiKey.change(req.get('action'), req['__user']['id'])


class Language(BaseHandler):
    @handle_request
    def get(self, req):
        return language()

    @handle_request
    def post(self, req):
        language(req['language'])
        return language()
