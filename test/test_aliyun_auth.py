import threading
import time
import unittest
from unittest import mock

import common.config as config_module
from service.storage.drivers.aliyun import AliyunDriveDriver
from service.storage.storageService import _prepareAliyunConfig


class Response:
    status_code = 200
    headers = {}

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class AliyunDriverAuthTest(unittest.TestCase):
    def test_service_mode_refreshes_without_client_secret(self):
        saved = []
        driver = AliyunDriveDriver(
            {
                "auth_mode": "service",
                "auth_service_url": "https://auth.example.com",
                "client_id": "public-app",
                "refresh_token": "refresh-old",
                "refresh_proof": "proof-old",
            },
            save_config=lambda config, expected_tokens=None: saved.append(config),
            refresh_lock=threading.Lock(),
        )
        driver.session.post = mock.Mock(
            return_value=Response(
                {
                    "access_token": "access-new",
                    "refresh_token": "refresh-new",
                    "refresh_proof": "proof-new",
                    "expires_in": 7200,
                }
            )
        )

        driver._refresh_access_token()

        call = driver.session.post.call_args
        self.assertEqual(
            "https://auth.example.com/v1/aliyun/token/refresh", call.args[0]
        )
        self.assertEqual(
            {"refresh_token": "refresh-old", "refresh_proof": "proof-old"},
            call.kwargs["json"],
        )
        self.assertEqual("refresh-new", driver.refresh_token)
        self.assertEqual("proof-new", driver.refresh_proof)
        self.assertGreater(driver.expires_at, time.time())
        self.assertEqual("proof-new", saved[-1]["refresh_proof"])

    def test_direct_mode_remains_supported(self):
        driver = AliyunDriveDriver(
            {
                "client_id": "app",
                "client_secret": "secret",
                "refresh_token": "refresh",
            }
        )
        self.assertEqual("direct", driver.auth_mode)


class AliyunStorageConfigTest(unittest.TestCase):
    @mock.patch(
        "service.storage.aliyunAuth._auth_server_url",
        return_value="https://auth.example.com",
    )
    def test_service_mode_uses_admin_configured_server(self, _server):
        config = _prepareAliyunConfig(
            {
                "auth_mode": "service",
                "refresh_token": "refresh",
                "refresh_proof": "proof",
            }
        )
        self.assertEqual("https://auth.example.com", config["auth_service_url"])
        self.assertEqual("", config["client_secret"])

    @mock.patch(
        "service.storage.aliyunAuth._auth_server_url",
        return_value="https://auth.example.com",
    )
    def test_service_mode_rejects_submitted_server_override(self, _server):
        with self.assertRaises(ValueError):
            _prepareAliyunConfig(
                {
                    "auth_mode": "service",
                    "auth_service_url": "https://attacker.example.com",
                    "refresh_token": "refresh",
                    "refresh_proof": "proof",
                }
            )

    def test_direct_mode_requires_complete_credentials(self):
        with self.assertRaises(ValueError):
            _prepareAliyunConfig(
                {
                    "auth_mode": "direct",
                    "client_id": "app",
                    "refresh_token": "refresh",
                }
            )


class TaoSyncConfigTest(unittest.TestCase):
    @staticmethod
    def _load_config(ini=None, env=None):
        parser = config_module.configparser.ConfigParser()
        if ini is not None:
            parser.read_string("[tao]\n" + ini)
        with mock.patch.object(config_module, "sysConfig", None), \
                mock.patch.object(config_module.os.path, "exists", return_value=ini is not None), \
                mock.patch.object(config_module, "getPasswordStr", return_value="passwd"), \
                mock.patch.object(parser, "read", return_value=[]), \
                mock.patch.object(config_module.configparser, "ConfigParser", return_value=parser), \
                mock.patch.dict(config_module.os.environ, env or {}, clear=True):
            return config_module.getConfig()

    def test_aliyun_auth_server_defaults_when_omitted_or_empty(self):
        for ini in (None, "", "aliyun_auth_server=\n", "aliyun_auth_server=   \n"):
            with self.subTest(ini=ini):
                config = self._load_config(ini)
                self.assertEqual("https://taoapi.dr34m.cn", config["server"]["aliyun_auth_server"])

    def test_aliyun_auth_server_config_file_has_priority_over_environment(self):
        for env in ({}, {"TAO_ALIYUN_AUTH_SERVER": ""},
                    {"TAO_ALIYUN_AUTH_SERVER": "https://env.example.com"}):
            with self.subTest(env=env):
                config = self._load_config(
                    "aliyun_auth_server= https://config.example.com \n", env,
                )
                self.assertEqual("https://config.example.com", config["server"]["aliyun_auth_server"])

    def test_config_file_omitted_or_empty_server_uses_environment(self):
        for ini in ("", "aliyun_auth_server=\n"):
            with self.subTest(ini=ini):
                config = self._load_config(ini, {"TAO_ALIYUN_AUTH_SERVER": "https://env.example.com"})
                self.assertEqual("https://env.example.com", config["server"]["aliyun_auth_server"])

    def test_aliyun_auth_server_environment_is_used_without_config_file(self):
        config = self._load_config(env={"TAO_ALIYUN_AUTH_SERVER": " https://env.example.com "})
        self.assertEqual("https://env.example.com", config["server"]["aliyun_auth_server"])

    def test_empty_environment_server_uses_default(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                config = self._load_config(env={"TAO_ALIYUN_AUTH_SERVER": value})
                self.assertEqual("https://taoapi.dr34m.cn", config["server"]["aliyun_auth_server"])

    def test_string_setting_preserves_percent_and_numeric_settings_remain_integers(self):
        config = self._load_config(
            "port=9000\ntask_timeout=8\naliyun_auth_server=https://config.example.com/auth%20service\n"
        )
        self.assertEqual("https://config.example.com/auth%20service", config["server"]["aliyun_auth_server"])
        self.assertEqual(9000, config["server"]["port"])
        self.assertEqual(8, config["server"]["timeout"])


if __name__ == "__main__":
    unittest.main()
