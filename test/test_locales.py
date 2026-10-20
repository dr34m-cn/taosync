import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import locales


class LocalesPathTest(unittest.TestCase):
    def test_loads_locales_from_pyinstaller_directory(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bundle_path = temp_path / 'bundle'
            working_path = temp_path / 'working'
            locales_path = bundle_path / 'locales'
            locales_path.mkdir(parents=True)
            working_path.mkdir()
            (locales_path / 'zh_CN.yaml').write_text('success: success-zh\n', encoding='utf-8')
            (locales_path / 'en.yaml').write_text('success: success-en\n', encoding='utf-8')

            try:
                os.chdir(working_path)
                with mock.patch.object(sys, '_MEIPASS', str(bundle_path), create=True):
                    locales.initLang()
                    self.assertEqual(locales.t('success', 'zh_CN'), 'success-zh')
                    self.assertEqual(locales.t('success', 'en'), 'success-en')
            finally:
                os.chdir(original_cwd)


if __name__ == '__main__':
    unittest.main()
