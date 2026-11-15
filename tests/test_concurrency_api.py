import json
from unittest.mock import patch

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from controller import baseController, jobController
from service.alist import alistService
from service.engine import engineService
from service.storage import storageService


class ConcurrencyApiTests(AsyncHTTPTestCase):
    def get_app(self):
        return Application([(r'/alist', jobController.Alist), (r'/storage', jobController.Storage)])

    def update(self, path):
        with patch.object(baseController.BaseHandler, '_get_signed_user_cookie', return_value=b'{}'), \
                patch.object(baseController, 'resolveSessionUser', return_value={'id': 1}):
            response = self.fetch(path, method='PUT', body=json.dumps({'id': 1, 'copyConcurrency': 2}),
                                  headers={'Content-Type': 'application/json', 'Accept-Language': 'en'})
        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body)['code'], 200, response.body)

    def test_external_limit_update_accepts_controller_metadata(self):
        limiter = engineService.CopyLimiter(5)
        with patch.object(engineService, 'getEngineById', return_value={'engineType': 'alist'}), \
                patch.object(engineService, 'getCopyLimiter', return_value=limiter), \
                patch('mapper.alistMapper.updateCopyConcurrency') as persist, \
                patch.object(alistService, 'updateAlist') as full_update, \
                patch.object(engineService, 'invalidateClient') as invalidate:
            self.update('/alist')
        persist.assert_called_once_with(1, 2)
        self.assertEqual(limiter.limit, 2)
        full_update.assert_not_called()
        invalidate.assert_not_called()

    def test_mount_limit_update_preserves_client_and_snapshot(self):
        limiter = engineService.CopyLimiter(5)
        with patch.object(storageService, '_requireTaoSync'), \
                patch.object(storageService.storageMapper, 'getMountById', return_value={'engineId': 1}), \
                patch.object(engineService, 'getMountCopyLimiter', return_value=limiter), \
                patch.object(storageService.storageMapper, 'updateCopyConcurrency') as persist, \
                patch.object(storageService.storageMapper, 'updateMount') as full_update, \
                patch.object(storageService, '_invalidateEngine') as invalidate:
            self.update('/storage')
        persist.assert_called_once_with(1, 2)
        self.assertEqual(limiter.limit, 2)
        full_update.assert_not_called()
        invalidate.assert_not_called()
