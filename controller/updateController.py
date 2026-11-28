import asyncio
import hashlib
import json
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


def _auth_fail(handler, lang):
    if 'Authorization' in handler.request.headers:
        handler.set_status(401)
        handler.finish({'code': 401, 'data': None, 'msg': t('api_key_invalid', lang)})
    else:
        handler.clear_cookie(handler.session_cookie_name, secure=handler.request.protocol == 'https')
        key = 'login_expired' if handler.get_cookie(handler.session_cookie_name) else 'sign_in'
        handler.finish({'code': 401, 'data': None, 'msg': t(key, lang)})


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
            _auth_fail(self, lang)
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


class UpdateReleases(BaseHandler):
    releases_task = None

    async def get(self):
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        lang = self.request.headers.get('Accept-Language', 'zh_CN')
        if self.authenticated_user() is None:
            _auth_fail(self, lang)
            return
        self.releases_task = asyncio.create_task(update.get_online_releases())
        try:
            result = await self.releases_task
        except asyncio.CancelledError:
            return
        except ValueError as exc:
            if not self._finished and not self.request.connection.stream.closed():
                self.set_status(503)
                self.finish({'code': 503, 'data': None, 'msg': t(str(exc), lang)})
            return
        finally:
            self.releases_task = None
        if not self._finished and not self.request.connection.stream.closed():
            self.finish({'code': 200, 'data': result, 'msg': ''})

    def on_connection_close(self):
        super().on_connection_close()
        if self.releases_task is not None and not self.releases_task.done():
            self.releases_task.cancel()


class OnlineUpdate(BaseHandler):
    state_lock = threading.Lock()
    active_task = None
    restart_delay = 1.5
    state = {
        'id': None,
        'phase': 'idle',
        'requestedVersion': None,
        'version': None,
        'channel': None,
        'requestedSource': None,
        'source': None,
        'latencyMs': None,
        'downloadedBytes': 0,
        'totalBytes': None,
        'errorKey': None,
        'errorDetails': None,
    }

    @classmethod
    def reset(cls):
        if cls.active_task is not None and not cls.active_task.done():
            cls.active_task.cancel()
        cls.active_task = None
        with cls.state_lock:
            cls.state = {
                'id': None,
                'phase': 'idle',
                'requestedVersion': None,
                'version': None,
                'channel': None,
                'requestedSource': None,
                'source': None,
                'latencyMs': None,
                'downloadedBytes': 0,
                'totalBytes': None,
                'errorKey': None,
                'errorDetails': None,
            }

    @classmethod
    def _set_state(cls, **updates):
        with cls.state_lock:
            cls.state.update(updates)

    @classmethod
    def snapshot(cls, lang='zh_CN'):
        with cls.state_lock:
            data = dict(cls.state)
        error_key = data.pop('errorKey', None)
        error_details = data.pop('errorDetails', None)
        if data.get('source') is not None:
            src = dict(data['source'])
            if 'labels' in src:
                src['labels'] = dict(src['labels'])
            data['source'] = src
        message = ''
        if error_key:
            text = t(error_key, lang)
            message = text.format(**error_details) if error_details else text
        data['message'] = message
        return data

    def reject(self, message, code=400, **details):
        self.set_status(code)
        msg = t(message, self.request.headers.get('Accept-Language', 'zh_CN'))
        self.finish({'code': code, 'data': None, 'msg': msg.format(**details) if details else msg})

    def authenticated(self):
        return self.authenticated_user() is not None

    def get(self):
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        lang = self.request.headers.get('Accept-Language', 'zh_CN')
        if not self.authenticated():
            _auth_fail(self, lang)
            return
        self.finish({'code': 200, 'data': self.snapshot(lang), 'msg': ''})

    async def post(self):
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        lang = self.request.headers.get('Accept-Language', 'zh_CN')
        if not self.authenticated():
            _auth_fail(self, lang)
            return
        if self.request.headers.get('X-TaoSync-Update') != '1':
            return self.reject('update_headers', 403)
        if not update.supported() or 'restart_for_update' not in self.settings:
            return self.reject('update_unsupported', 409)
        try:
            body = json.loads((self.request.body or b'{}').decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return self.reject('lost_part', 400)
        if not isinstance(body, dict):
            return self.reject('lost_part', 400)
        version_choice = body.get('version', 'latest')
        source_choice = body.get('source', 'auto')
        if not isinstance(version_choice, str) or not isinstance(source_choice, str):
            return self.reject('lost_part', 400)
        if not ProgramUpload.lock.acquire(blocking=False):
            return self.reject('update_busy', 409)
        task_started = False
        try:
            catalog = await update.get_online_releases()
            selected_version, candidate_sources, is_auto_source = update.resolve_online_selection(
                catalog, version_choice, source_choice
            )
            attempt = uuid.uuid4().hex
            initial_phase = 'probing' if (is_auto_source and len(candidate_sources) > 1) else 'downloading'
            initial_source = None if initial_phase == 'probing' else candidate_sources[0]
            self._set_state(
                id=attempt,
                phase=initial_phase,
                requestedVersion=version_choice.strip() or 'latest',
                version=selected_version['version'],
                channel=selected_version['channel'],
                requestedSource=source_choice.strip() or 'auto',
                source=initial_source,
                latencyMs=None,
                downloadedBytes=0,
                totalBytes=None,
                errorKey=None,
                errorDetails=None,
            )
            restart_cb = self.settings['restart_for_update']
            OnlineUpdate.active_task = asyncio.create_task(
                self._run_update(attempt, selected_version, candidate_sources, is_auto_source, restart_cb)
            )
            task_started = True
            if not self._finished and not self.request.connection.stream.closed():
                self.finish({'code': 200, 'data': self.snapshot(lang), 'msg': ''})
        except ValueError as exc:
            message = str(exc)
            code = 503 if message == 'update_trust_unavailable' else 400
            if not self._finished and not self.request.connection.stream.closed():
                self.reject(message, code)
        finally:
            if not task_started:
                ProgramUpload.lock.release()

    def delete(self):
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Content-Type', 'application/json; charset=UTF-8')
        lang = self.request.headers.get('Accept-Language', 'zh_CN')
        if not self.authenticated():
            _auth_fail(self, lang)
            return
        if self.request.headers.get('X-TaoSync-Update') != '1':
            return self.reject('update_headers', 403)
        task = OnlineUpdate.active_task
        with OnlineUpdate.state_lock:
            phase = OnlineUpdate.state.get('phase')
        if task is not None and not task.done() and phase in ('probing', 'downloading'):
            task.cancel()
        self.finish({'code': 200, 'data': self.snapshot(lang), 'msg': ''})

    @classmethod
    async def _run_update(cls, attempt, selected_version, candidate_sources, is_auto_source, restart_cb):
        temporary = None
        committed = False
        try:
            if is_auto_source and len(candidate_sources) > 1:
                cls._set_state(phase='probing', source=None, latencyMs=None)
                chosen_source, latency_ms = await update.select_fastest_source(candidate_sources)
            else:
                chosen_source, latency_ms = candidate_sources[0], None
            cls._set_state(phase='downloading', source=chosen_source, latencyMs=latency_ms,
                           downloadedBytes=0, totalBytes=None)
            try:
                directory = Path(os.environ['TAO_UPDATE_DIR'])
                directory.mkdir(mode=0o700, exist_ok=True)
                with tempfile.NamedTemporaryFile(prefix='online-', dir=directory, delete=False) as fp:
                    temporary = Path(fp.name)
            except OSError as exc:
                raise ValueError('update_stage_failed') from exc

            def on_progress(downloaded, total):
                cls._set_state(downloadedBytes=downloaded, totalBytes=total)

            raw_digest = await update.download_package(
                chosen_source['url'], temporary, limit=update.MAX_BYTES, on_progress=on_progress
            )
            cls._set_state(phase='verifying')
            digest = await asyncio.to_thread(prepare_payload, temporary, raw_digest, update.MAX_BYTES)
            await update.verify_digest(digest, expected_version=selected_version['version'])
            jobClient.beginProgramUpdate()
            try:
                update.install_verified(temporary, digest, attempt)
                committed = True
            finally:
                if not committed:
                    jobClient.cancelProgramUpdate()
            cls._set_state(phase='restarting')
            if cls.restart_delay > 0:
                await asyncio.sleep(cls.restart_delay)
        except asyncio.CancelledError:
            if not committed:
                cls._set_state(phase='cancelled', errorKey='update_cancelled', errorDetails=None)
        except update.ArchitectureMismatch as exc:
            cls._set_state(phase='error', errorKey=str(exc), errorDetails=exc.details)
        except ValueError as exc:
            cls._set_state(phase='error', errorKey=str(exc), errorDetails=None)
        except OSError:
            cls._set_state(phase='error', errorKey='update_write_failed', errorDetails=None)
        except Exception:
            cls._set_state(phase='error', errorKey='update_download_failed', errorDetails=None)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            cls.active_task = None
            ProgramUpload.lock.release()
            if committed:
                restart_cb()


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
