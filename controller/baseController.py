import hmac
import json
import logging

from tornado.web import RequestHandler

from common import commonService, commonUtils
from common.LNG import G, set_context_lang
from common.config import getConfig
from service.system import apiKey, userService

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
    @property
    def session_cookie_name(self):
        # Browser cookies share a host across ports. Keep the TLS session off HTTP.
        return '__Host-tao_sync' if self.request.protocol == 'https' else cookieName

    def _get_signed_user_cookie(self):
        # 登录时和校验时必须使用同一个有效期，否则浏览器仍保留 Cookie 时，
        # 服务端会回退到 Tornado 默认的 31 天有效期。
        return self.get_signed_cookie(
            self.session_cookie_name,
            max_age_days=getConfig()['server']['expires']
        )

    def get_current_user(self):
        user = self._get_signed_user_cookie()
        return json.loads(user) if user else None

    def set_session_cookie(self, user):
        self.set_signed_cookie(self.session_cookie_name, buildSessionCookie(user),
                               expires_days=getConfig()['server']['expires'],
                               httponly=True, samesite='Lax', secure=self.request.protocol == 'https')

    def authenticated_user(self):
        if 'Authorization' in self.request.headers:
            return apiKey.resolveUser(self.request.headers['Authorization'])
        try:
            return resolveSessionUser(self.get_current_user())
        except (TypeError, ValueError):
            return None


def _unauthorized(handler, msgKey):
    handler.clear_cookie(handler.session_cookie_name, secure=handler.request.protocol == 'https')
    handler.set_header('Content-Type', 'application/json; charset=UTF-8')
    handler.write(commonService.result_map(G(msgKey), 401))


def handle_request(func):
    def wrapper(self):
        lang = self.request.headers.get("Accept-Language", None)
        set_context_lang(lang)
        trueUser = None
        if 'Authorization' in self.request.headers or not self.request.path.startswith('/svr/noAuth/'):
            trueUser = self.authenticated_user()
            if trueUser is None:
                if 'Authorization' in self.request.headers:
                    self.set_status(401)
                    self.set_header('Content-Type', 'application/json; charset=UTF-8')
                    self.write(commonService.result_map(G('api_key_invalid'), 401))
                else:
                    _unauthorized(self, 'login_expired' if self.get_cookie(self.session_cookie_name) else 'sign_in')
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
