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
    def _config_from_ini(env_value):
        class FakeSection(dict):
            def get(self, key, fallback=None, raw=False):
                return super().get(key, fallback)

        fake_section = FakeSection(
            password="secret",
            aliyun_auth_server="https://config.example.com",
        )

        class FakeConfigParser:
            def read(self, *args, **kwargs):
                return []

            def __getitem__(self, key):
                if key != "tao":
                    raise KeyError(key)
                return fake_section

        env = {} if env_value is None else {"TAO_ALIYUN_AUTH_SERVER": env_value}
        with mock.patch.object(config_module, "sysConfig", None), \
                mock.patch.object(config_module.os.path, "exists", return_value=True), \
                mock.patch.object(config_module, "getPasswordStr", return_value="passwd"), \
                mock.patch.object(config_module.configparser, "ConfigParser", return_value=FakeConfigParser()), \
                mock.patch.dict(config_module.os.environ, env, clear=False):
            return config_module.getConfig()

    def test_aliyun_auth_server_env_overrides_config_file(self):
        config = self._config_from_ini("https://env.example.com")
        self.assertEqual("https://env.example.com", config["server"]["aliyun_auth_server"])

    def test_aliyun_auth_server_empty_env_keeps_config_file(self):
        # Docker 镜像预置 TAO_ALIYUN_AUTH_SERVER=""，空值不应覆盖 config.ini
        config = self._config_from_ini("")
        self.assertEqual("https://config.example.com", config["server"]["aliyun_auth_server"])

    def test_aliyun_auth_server_unset_env_keeps_config_file(self):
        config = self._config_from_ini(None)
        self.assertEqual("https://config.example.com", config["server"]["aliyun_auth_server"])


if __name__ == "__main__":
    unittest.main()
