import asyncio
import hashlib
import os
import tempfile
import threading
import uuid
from pathlib import Path

from tornado.web import stream_request_body

from common.locales import t
from controller.baseController import BaseHandler, handle_request
from service.syncJob import jobClient
from service.system import programUpdate as update
from service.system.updatePackage import prepare_payload


class UpdateInfo(BaseHandler):
    @handle_request
    def get(self, req):
        self.set_header('Cache-Control', 'no-store')
        return update.info()


class UpdateCheck(BaseHandler):
    check_task = None

    async def get(self):
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        lang = self.request.headers.get('Accept-Language', 'zh_CN')
        if self.authenticated_user() is None:
            if 'Authorization' in self.request.headers:
                self.set_status(401)
                self.finish({'code': 401, 'data': None, 'msg': t('api_key_invalid', lang)})
            else:
                self.clear_cookie(self.session_cookie_name, secure=self.request.protocol == 'https')
                key = 'login_expired' if self.get_cookie(self.session_cookie_name) else 'sign_in'
                self.finish({'code': 401, 'data': None, 'msg': t(key, lang)})
            return
        self.check_task = asyncio.create_task(update.check_latest_version())
        try:
            result = await self.check_task
        except asyncio.CancelledError:
            return
        finally:
            self.check_task = None
        if not self._finished and not self.request.connection.stream.closed():
            self.finish({'code': 200, 'data': result, 'msg': ''})

    def on_connection_close(self):
        super().on_connection_close()
        if self.check_task is not None and not self.check_task.done():
            self.check_task.cancel()


@stream_request_body
class ProgramUpload(BaseHandler):
    # Only this endpoint raises the connection's body limit. No multipart buffering.
    lock = threading.Lock()
    temporary = None
    stream = None
    owns_lock = False
    processing = False

    def reject(self, message, code=400, **details):
        self.set_status(code)
        msg = t(message, self.request.headers.get('Accept-Language', 'zh_CN'))
        self.finish({'code': code, 'data': None, 'msg': msg.format(**details) if details else msg})

    def authenticated(self):
        return self.authenticated_user() is not None

    def prepare(self):
        headers = self.request.headers
        if self.request.method != 'POST':
            return self.reject('update_method', 405)
        if not self.authenticated():
            return self.reject('sign_in', 401)
        # Browsers cannot send this custom header cross-origin without an approved preflight.
        if headers.get('X-TaoSync-Update') != '1' or headers.get('Content-Type') != 'application/octet-stream':
            return self.reject('update_headers', 403)
        if not update.supported() or 'restart_for_update' not in self.settings:
            return self.reject('update_unsupported', 409)
        length = headers.get('Content-Length', '')
        if not length.isdigit() or not 0 < int(length) <= update.MAX_BYTES:
            return self.reject('update_size', 413)
        if not self.lock.acquire(blocking=False):
            return self.reject('update_busy', 409)
        self.owns_lock = True
        self.request.connection.set_max_body_size(update.MAX_BYTES)
        self.request.connection.set_body_timeout(600)
        try:
            directory = Path(os.environ['TAO_UPDATE_DIR'])
            directory.mkdir(mode=0o700, exist_ok=True)
            self.stream = tempfile.NamedTemporaryFile(prefix='upload-', dir=directory, delete=False)
            self.temporary = Path(self.stream.name)
            self.digest = hashlib.sha256()
        except OSError:
            self.reject('update_stage_failed', 507)

    def data_received(self, chunk):
        if self._finished:
            return
        try:
            self.stream.write(chunk)
            self.digest.update(chunk)
        except OSError:
            self.reject('update_write_failed', 507)

    async def post(self):
        if self._finished:
            return
        self.processing = True
        committed = False
        try:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
            raw_digest = self.digest.hexdigest()
            try:
                digest = await asyncio.to_thread(prepare_payload, self.temporary, raw_digest, update.MAX_BYTES)
            except ValueError as exc:
                if str(exc) in ('update_size', 'update_archive_limit'):
                    raise
                # An APK is a registered Android artifact and also a ZIP without a desktop executable.
                await update.verify_digest(raw_digest)
                raise
            await update.verify_digest(digest)
            if self.request.connection.stream.closed():
                return
            if not self.authenticated():
                return self.reject('login_expired', 401)
            attempt = uuid.uuid4().hex
            # Check and freeze manual/scheduled starts as a single operation.
            jobClient.beginProgramUpdate()
            try:
                update.install_verified(self.temporary, digest, attempt)
                committed = True
            finally:
                if not committed:
                    jobClient.cancelProgramUpdate()
            await self.finish({'code': 200, 'data': {'id': attempt}, 'msg': ''})
        except update.ArchitectureMismatch as exc:
            if not self._finished:
                self.reject(str(exc), **exc.details)
        except ValueError as exc:
            if not self._finished:
                message = str(exc)
                self.reject(message, 413 if message in ('update_size', 'update_archive_limit') else 400)
        except OSError:
            if not self._finished:
                self.reject('update_write_failed', 507)
        finally:
            self.cleanup()
            if committed:
                self.settings['restart_for_update']()

    def cleanup(self):
        try:
            if self.stream:
                self.stream.close()
            if self.temporary:
                self.temporary.unlink(missing_ok=True)
        finally:
            if self.owns_lock:
                self.owns_lock = False
                self.lock.release()

    def on_connection_close(self):
        super().on_connection_close()
        if not self.processing:
            self.cleanup()

    def on_finish(self):
        if not self.processing:
            self.cleanup()
