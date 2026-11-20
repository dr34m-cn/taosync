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


@stream_request_body
class ProgramUpload(BaseHandler):
    # Only this endpoint raises the connection's body limit. No multipart buffering.
    lock = threading.Lock()
    temporary = None
    stream = None
    owns_lock = False
    processing = False

    def reject(self, message, code=400):
        self.set_status(code)
        self.finish({'code': code, 'data': None, 'msg': t(message, self.request.headers.get('Accept-Language', 'zh_CN'))})

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
            digest = await asyncio.to_thread(prepare_payload, self.temporary, self.digest.hexdigest(), update.MAX_BYTES)
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
