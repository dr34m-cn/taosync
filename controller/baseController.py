import hmac
import json
import logging

from tornado.web import RequestHandler

from common import commonService, commonUtils
from common.LNG import G, set_context_lang
from common.config import getConfig
from service.system import userService

cookieName = 'tao_sync'


def buildSessionCookie(user):
    """Cookie 中只保存用户标识与会话版本，不再包含密码摘要。"""
    return json.dumps({
        'id': user['id'],
        'userName': user['userName'],
        'sv': commonUtils.sessionVersion(user),
    })


def resolveSessionUser(cookieUser):
    """校验 Cookie 对应的用户，失败返回 None（旧版含密码摘要的 Cookie 需重新登录）。"""
    if not isinstance(cookieUser, dict) or 'id' not in cookieUser or 'sv' not in cookieUser:
        return None
    try:
        trueUser = userService.getUser(cookieUser['id'], None)
    except Exception:
        return None
    if (not trueUser
            or trueUser['userName'] != cookieUser.get('userName')
            or not hmac.compare_digest(str(cookieUser['sv']), commonUtils.sessionVersion(trueUser))):
        return None
    return trueUser


class BaseHandler(RequestHandler):
    def _get_signed_user_cookie(self):
        # 登录时和校验时必须使用同一个有效期，否则浏览器仍保留 Cookie 时，
        # 服务端会回退到 Tornado 默认的 31 天有效期。
        return self.get_signed_cookie(
            cookieName,
            max_age_days=getConfig()['server']['expires']
        )

    def get_current_user(self):
        user = self._get_signed_user_cookie()
        return json.loads(user) if user else None

    def set_session_cookie(self, user):
        self.set_signed_cookie(cookieName, buildSessionCookie(user),
                               expires_days=getConfig()['server']['expires'],
                               httponly=True, samesite='Lax')


def _unauthorized(handler, msgKey):
    handler.clear_cookie(cookieName)
    handler.set_header('Content-Type', 'application/json; charset=UTF-8')
    handler.write(commonService.result_map(G(msgKey), 401))


def handle_request(func):
    def wrapper(self):
        uri = self.request.uri
        lang = self.request.headers.get("Accept-Language", None)
        set_context_lang(lang)
        user = self._get_signed_user_cookie()
        trueUser = None
        if not uri.startswith('/svr/noAuth'):
            if user is None:
                _unauthorized(self, 'sign_in')
                return
            try:
                cUser = json.loads(user)
            except (TypeError, ValueError):
                cUser = None
            trueUser = resolveSessionUser(cUser)
            if trueUser is None:
                _unauthorized(self, 'login_expired')
                return
        try:
            req = commonService.get_post_data(self)
            req['__lang'] = set_context_lang(lang)
            if trueUser:
                req['__user'] = trueUser.copy()
                req['__user'].pop('passwd', None)
                req['__user'].pop('sqlVersion', None)
            msg = commonService.result_map(func(self, req))
        except Exception as e:
            msg = commonService.result_map(str(e), 500)
            logger = logging.getLogger()
            logger.exception(e)
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        self.write(msg)

    return wrapper
