import logging
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import commonUtils, config, sqlBase, sqlInit
from common import LNG, locales
from service.system import onStart


class DefaultPasswordTest(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)
        Path('data').mkdir()

        self.original_config = config.sysConfig
        self.original_language = LNG.sysLanguage
        self.original_all_lang = locales.allLang
        self.original_sys_lang = locales.sysLang

        config.sysConfig = None
        LNG.sysLanguage = None
        locales.allLang = {}
        locales.sysLang = None
        sqlBase.RUN_FLAG = False

    def tearDown(self):
        config.sysConfig = self.original_config
        LNG.sysLanguage = self.original_language
        locales.allLang = self.original_all_lang
        locales.sysLang = self.original_sys_lang
        sqlBase.RUN_FLAG = False
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _load_config(self, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=True), \
                mock.patch.object(config, 'getPasswordStr', return_value='secret-key'):
            return config.getConfig()

    def _set_runtime_config(self, password):
        db_path = str(Path(self.temp_dir.name) / 'data' / 'taoSync.db')
        config.sysConfig = {
            'db': {'dbname': db_path},
            'server': {
                'passwdStr': 'secret-key',
                'password': password,
            },
        }
        return db_path

    def _stored_admin_password(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute(
                "select passwd from user_list where userName = 'admin'"
            ).fetchone()[0]
        finally:
            conn.close()

    def test_password_defaults_to_random(self):
        cfg = self._load_config()

        self.assertEqual(cfg['server']['password'], config.DEFAULT_PASSWORD)

    def test_password_can_be_set_in_environment(self):
        cfg = self._load_config({'TAO_PASSWORD': 'manual-password'})

        self.assertEqual(cfg['server']['password'], 'manual-password')

    def test_legacy_environment_variable_is_supported(self):
        cfg = self._load_config({'TAO_PASSWD': 'legacy-password'})

        self.assertEqual(cfg['server']['password'], 'legacy-password')

    def test_new_environment_variable_has_priority_over_legacy_alias(self):
        cfg = self._load_config({
            'TAO_PASSWORD': 'new-password',
            'TAO_PASSWD': 'legacy-password',
        })

        self.assertEqual(cfg['server']['password'], 'new-password')

    def test_explicit_random_sentinel_has_priority_over_legacy_alias(self):
        cfg = self._load_config({
            'TAO_PASSWORD': config.DEFAULT_PASSWORD,
            'TAO_PASSWD': 'legacy-password',
        })

        self.assertEqual(cfg['server']['password'], config.DEFAULT_PASSWORD)

    def test_empty_environment_password_falls_back_to_random(self):
        cfg = self._load_config({'TAO_PASSWORD': '   '})

        self.assertEqual(cfg['server']['password'], config.DEFAULT_PASSWORD)

    def test_manual_password_survives_an_invalid_numeric_environment_value(self):
        with self.assertLogs(level=logging.ERROR):
            cfg = self._load_config({
                'TAO_PASSWORD': 'manual-password',
                'TAO_PORT': 'invalid-port',
            })

        self.assertEqual(cfg['server']['password'], 'manual-password')

    def test_config_file_password_has_priority_and_preserves_percent(self):
        Path('data/config.ini').write_text(
            '[tao]\npassword=manual%password\n',
            encoding='utf-8',
        )

        cfg = self._load_config({'TAO_PASSWORD': 'environment-password'})

        self.assertEqual(cfg['server']['password'], 'manual%password')

    def test_empty_config_file_password_falls_back_to_random(self):
        Path('data/config.ini').write_text(
            '[tao]\npassword=\n',
            encoding='utf-8',
        )

        cfg = self._load_config()

        self.assertEqual(cfg['server']['password'], config.DEFAULT_PASSWORD)

    def test_malformed_config_does_not_leak_password_in_error_log(self):
        Path('data/config.ini').write_text(
            'password=manual-secret\n',
            encoding='utf-8',
        )

        with self.assertLogs(level=logging.ERROR) as captured:
            cfg = self._load_config()

        output = '\n'.join(captured.output)
        self.assertEqual(cfg['server']['password'], config.DEFAULT_PASSWORD)
        self.assertNotIn('manual-secret', output)

    def test_random_setting_keeps_original_generation_logic(self):
        db_path = self._set_runtime_config(config.DEFAULT_PASSWORD)

        with mock.patch.object(
                commonUtils, 'generatePasswd', return_value='generated-password'
        ) as generate_password:
            password = sqlInit.init_sql()

        self.assertEqual(password, 'generated-password')
        generate_password.assert_called_once_with()
        self.assertEqual(
            self._stored_admin_password(db_path),
            commonUtils.passwd2md5('generated-password'),
        )

    def test_manual_setting_is_used_without_random_generation(self):
        db_path = self._set_runtime_config('manual-password')

        with mock.patch.object(commonUtils, 'generatePasswd') as generate_password:
            password = sqlInit.init_sql()

        self.assertEqual(password, 'manual-password')
        generate_password.assert_not_called()
        self.assertEqual(
            self._stored_admin_password(db_path),
            commonUtils.passwd2md5('manual-password'),
        )

    def test_existing_database_password_is_not_overwritten(self):
        db_path = self._set_runtime_config('first-password')
        self.assertEqual(sqlInit.init_sql(), 'first-password')
        stored_password = self._stored_admin_password(db_path)

        config.sysConfig['server']['password'] = 'second-password'
        self.assertIsNone(sqlInit.init_sql())

        self.assertEqual(self._stored_admin_password(db_path), stored_password)

    def test_manual_password_log_does_not_expose_the_password(self):
        self._set_runtime_config('manual-password')

        with mock.patch.object(
                onStart.sqlInit, 'init_sql', return_value='manual-password'
        ), mock.patch.object(onStart.commonService, 'setLogger'), \
                mock.patch.object(onStart.logJobService, 'startJob'), \
                mock.patch.object(onStart, 'initJob'), \
                self.assertLogs(level=logging.CRITICAL) as captured:
            onStart.init()

        output = '\n'.join(captured.output)
        self.assertIn('已使用手动设定的密码。', output)
        self.assertNotIn('manual-password', output)

    def test_random_password_log_keeps_generated_password(self):
        self._set_runtime_config(config.DEFAULT_PASSWORD)

        with mock.patch.object(
                onStart.sqlInit, 'init_sql', return_value='generated-password'
        ), mock.patch.object(onStart.commonService, 'setLogger'), \
                mock.patch.object(onStart.logJobService, 'startJob'), \
                mock.patch.object(onStart, 'initJob'), \
                self.assertLogs(level=logging.CRITICAL) as captured:
            onStart.init()

        self.assertIn('generated-password', '\n'.join(captured.output))


if __name__ == '__main__':
    unittest.main()
