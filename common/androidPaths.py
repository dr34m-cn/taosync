"""Android 持久化数据根目录解析与旧数据目录迁移辅助模块（仅依赖标准库）。

python-for-android (webview bootstrap) 在每次安装新版本 APK 时，会先对
getAppRoot()（即 `<ANDROID_PRIVATE>/app`）执行 recursiveDelete 再重新解包代码，
但不会删除 `<ANDROID_PRIVATE>`（即 Context.getFilesDir()）。

将运行时 `data/` 放在 `<ANDROID_PRIVATE>/data`（位于 `files/app` 之外）
可保证同签名覆盖升级后数据库、密钥、配置与日志完整保留。
"""
import os
import shutil

SHELL_TOKEN_FILENAME = '.shell_token'
_PERSISTENT_MARKER_FILES = ('taoSync.db', 'secret.key', 'config.ini', 'https.pem')


def _is_same_or_inside(path, ancestor):
    real_path = os.path.realpath(path)
    real_ancestor = os.path.realpath(ancestor)
    try:
        return os.path.commonpath([real_path, real_ancestor]) == real_ancestor
    except ValueError:
        return False


def resolve_android_data_root(app_dir, env=None):
    """返回位于 p4a 解包目录 `files/app` 之外的持久化运行根目录。"""
    env_map = os.environ if env is None else env
    app_path = os.path.abspath(app_dir)
    android_private = (env_map.get('ANDROID_PRIVATE') or '').strip()
    if android_private:
        candidate = os.path.abspath(android_private)
        if not _is_same_or_inside(candidate, app_path):
            return candidate
    if os.path.basename(app_path) == 'app':
        parent = os.path.dirname(app_path)
        if parent and parent != app_path:
            return parent
    return app_path


def _merge_move_tree(src_dir, dst_dir):
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        if name == SHELL_TOKEN_FILENAME:
            continue
        src_item = os.path.join(src_dir, name)
        dst_item = os.path.join(dst_dir, name)
        if os.path.isdir(src_item) and not os.path.islink(src_item):
            if not os.path.exists(dst_item):
                shutil.move(src_item, dst_item)
            elif os.path.isdir(dst_item):
                _merge_move_tree(src_item, dst_item)
                try:
                    if not os.listdir(src_item):
                        os.rmdir(src_item)
                except OSError:
                    pass
        else:
            if not os.path.exists(dst_item):
                shutil.move(src_item, dst_item)


def migrate_legacy_android_data(app_dir, data_root):
    """将旧版本落在 `files/app/data` 中的运行数据一次性迁移到 `files/data`。

    若目标目录已存在持久化核心文件（如 `taoSync.db` / `secret.key`），
    绝不覆盖目标目录，直接返回 False。
    """
    app_path = os.path.abspath(app_dir)
    root_path = os.path.abspath(data_root)
    legacy_data = os.path.join(app_path, 'data')
    target_data = os.path.join(root_path, 'data')

    if os.path.realpath(legacy_data) == os.path.realpath(target_data) or not os.path.isdir(legacy_data):
        return False
    if any(os.path.exists(os.path.join(target_data, marker)) for marker in _PERSISTENT_MARKER_FILES):
        return False

    entries = [name for name in os.listdir(legacy_data) if name != SHELL_TOKEN_FILENAME]
    if not entries:
        return False

    _merge_move_tree(legacy_data, target_data)
    try:
        remaining = os.listdir(legacy_data)
        if remaining == [SHELL_TOKEN_FILENAME]:
            os.remove(os.path.join(legacy_data, SHELL_TOKEN_FILENAME))
            remaining = []
        if not remaining:
            os.rmdir(legacy_data)
    except OSError:
        pass
    return True


def prepare_android_data_root(app_dir, env=None):
    """解析持久化数据根目录，必要时迁移旧数据，并确保 `data` 与 `data/log` 存在。"""
    data_root = resolve_android_data_root(app_dir, env=env)
    os.makedirs(data_root, exist_ok=True)
    migrate_legacy_android_data(app_dir, data_root)
    os.makedirs(os.path.join(data_root, 'data', 'log'), exist_ok=True)
    return data_root
