import re

from common.LNG import get_context_lang
from common.directoryCache import storedListings
from common.locales import t
from service.storage.drivers.base import child_path, normalize_path
from mapper import storageMapper
from mapper.alistMapper import getEngineById
from service.storage import discoveryService
from service.storage.factory import SECRET_FIELDS, createDriver, getDriverTypes
from service.storage import mountConfig
from service.storage.pathIdentity import mount_paths_overlap, virtual_paths_overlap


MOUNT_NAME_PATTERN = re.compile(r"^[^\\/:\x00-\x1f]+$")


def _requireTaoSync(engineId):
    engine = getEngineById(int(engineId))
    if engine.get("engineType") != "taosync" or engine.get("systemKey") != "taosync":
        raise ValueError("storage directories can only be managed for the TaoSync engine")
    return engine


def _cleanName(name):
    name = str(name or "").strip().lstrip("/")
    if not name or name in (".", "..") or not MOUNT_NAME_PATTERN.match(name):
        raise ValueError("invalid storage directory name")
    return name


def _cacheDays(value):
    if type(value) is not int or not -1 <= value <= 2147483647:
        raise ValueError(t('directory_cache_days_invalid', get_context_lang()))
    return value


def _sanitized(row):
    row = dict(row)
    config = dict(row.get("config") or {})
    secret_state = {}
    fields = SECRET_FIELDS.get(row["driverType"], set())
    if row["driverType"] == "crypt" or "encryption_key" in config:
        fields = fields | {"encryption_key"}
    for field in fields:
        secret_state[field] = bool(config.get(field))
        config[field] = ""
    row["config"] = config
    row["secretState"] = secret_state
    return row


def getMountList(engineId):
    _requireTaoSync(engineId)
    return [_sanitized(row) for row in storageMapper.getMountList(int(engineId))]


def getSupportedDrivers():
    return getDriverTypes()


def cloudFileOperation(req):
    from service.engine import engineService

    _requireTaoSync(req['engineId'])
    client = engineService.getClientById(req['engineId'])
    action = req['action']
    if action == 'fileTask':
        info = client.taskInfo(req['taskId'])
        if req.get('forget') is True and info['state'] in (2, 4, 7):
            client.copyTaskDelete(req['taskId'])
        return info
    if action == 'fileCancel':
        client.copyTaskCancel(req['taskId'])
        return client.taskInfo(req['taskId'])
    if action == 'fileList':
        mount, _ = client.resolve(req['path'])
        if mount['driverType'] != 'aliyun':
            raise ValueError('cloud file management requires an Aliyun storage directory')
        return client._entries(req['path'], 0)
    if action == 'fileRename':
        task_id = client.renameFile(req['path'], req['name'])
    elif action == 'fileMove':
        task_id = client.relocateFile(req['path'], req['destination'])
    else:
        raise ValueError('unknown cloud file action')
    return {'taskId': task_id}


def engineMountPathsOverlap(engineId, firstPath, secondPath):
    engine = getEngineById(int(engineId))
    if engine.get("engineType") != "taosync" or engine.get("systemKey") != "taosync":
        return False
    mounts = storageMapper.getMountList(int(engineId))
    return mount_paths_overlap(mounts, firstPath, secondPath)


def enginePathsOverlap(engineId, firstPath, secondPath):
    engine = getEngineById(int(engineId))
    isTaoSync = (
        engine.get("engineType") == "taosync" and engine.get("systemKey") == "taosync"
    )
    if not isTaoSync:
        # An external AList's backend case semantics are unknown. Prefer the
        # conservative check that was historically used for its virtual tree.
        return virtual_paths_overlap(firstPath, secondPath, case_sensitive=False)
    return (
        virtual_paths_overlap(firstPath, secondPath, case_sensitive=True)
        or mount_paths_overlap(
            storageMapper.getMountList(int(engineId)), firstPath, secondPath
        )
    )


def _validateUniqueName(engineId, name, excludeId=None):
    for row in storageMapper.getMountList(engineId):
        if row["name"].casefold() == name.casefold() and row["id"] != excludeId:
            raise ValueError("a storage directory with the same name already exists")


def _normalizeDriverConfig(driverType, config):
    driver = createDriver(driverType, config)
    # Network credentials are verified on first browse. In particular, do not
    # rotate an Aliyun refresh token before the mount row exists and can safely
    # persist the replacement token.
    if driverType == "local":
        driver.list("/")
    return dict(getattr(driver, "config", config))


def _validateCryptTarget(engineId, config):
    from service.engine import engineService

    target = storageMapper.getMountById(config["target_mount_id"])
    if target["engineId"] != engineId or not target["enabled"] or target["driverType"] == "crypt":
        raise ValueError("crypt target must be an enabled regular mount on the same engine")
    client = engineService.getClientById(engineId)
    mount, _ = client.resolve("/" + target["name"])
    if (mount["id"] != target["id"] or mount["driverType"] != target["driverType"]
            or mountConfig.backingLocation(target["driverType"], mount["config"], runtime=True)
            != mountConfig.backingLocation(target["driverType"], target["config"], runtime=True)
            or mount["authVersion"] != target["authVersion"]):
        raise ValueError("target mount changed; reload and retry")
    driver = client.getDriver(mount)
    path = config["target_path"]
    try:
        # Walk only directories exposed by the driver. A directly addressed
        # path could otherwise traverse a link the parent's listing hides.
        parent = "/"
        for part in path.strip("/").split("/") if path != "/" else ():
            if not any(e["name"] == part and e["is_dir"] for e in driver.list(parent)):
                raise FileNotFoundError
            parent = parent.rstrip("/") + "/" + part
        driver.list(path)
    except Exception:
        raise ValueError("crypt target directory does not exist or is inaccessible") from None
    if target["driverType"] == "aliyun":
        # This read can itself refresh tokens or discover the drive ID. Accept
        # the new version only if the live driver still matches that target.
        current = storageMapper.getMountById(target["id"])
        if (current["authVersion"] != target["authVersion"]
                or mountConfig.backingLocation("aliyun", current["config"], runtime=True)
                != mountConfig.backingLocation("aliyun", target["config"], runtime=True)
                or current["config"].get("drive_id") != driver.drive_id):
            raise ValueError("target mount changed; reload and retry")
        return current
    return target


def _aliyunAuthMode(config):
    explicit = str(config.get("auth_mode") or "").strip().lower()
    if explicit:
        return explicit
    return "service" if config.get("auth_service_url") and not config.get("client_secret") else "direct"


def _aliyunEndpointIdentity(config, mode):
    """Where stored Aliyun credentials are sent; secrets may only be reused for the same target."""
    from service.storage.drivers.aliyun import AliyunDriveDriver

    apiUrl = str(config.get("api_url") or AliyunDriveDriver.API_URL).strip().rstrip("/")
    if mode == "service":
        return (apiUrl,)
    oauthUrl = str(config.get("oauth_url") or apiUrl + "/oauth/access_token").strip()
    return (str(config.get("client_id") or "").strip(), apiUrl, oauthUrl)


def _networkIdentity(driverType, config):
    """Host/port/user a stored password authenticates against (SMB/FTP)."""
    defaults = {"smb": 445, "ftp": 21}
    host = str(config.get("host") or config.get("server") or "").strip().casefold()
    try:
        port = int(config.get("port") or defaults.get(driverType, 0))
    except (TypeError, ValueError):
        port = str(config.get("port")).strip()
    username = str(config.get("username") or ("anonymous" if driverType == "ftp" else "")).strip()
    domain = str(config.get("domain") or "").strip().casefold() if driverType == "smb" else ""
    return host, port, username, domain


def _prepareAliyunConfig(rawConfig, old=None):
    oldConfig = dict((old or {}).get("config") or {})
    oldMode = _aliyunAuthMode(oldConfig) if old is not None else None
    inferredMode = (
        "service"
        if rawConfig.get("auth_service_url") and not rawConfig.get("client_secret")
        else "direct"
    )
    requestedMode = str(rawConfig.get("auth_mode") or oldMode or inferredMode).strip().lower()
    if requestedMode not in ("service", "direct"):
        raise ValueError("invalid Aliyun auth_mode")
    sameMode = old is not None and requestedMode == oldMode
    config = {**(oldConfig if sameMode else {}), **dict(rawConfig)}
    # An explicit threshold replaces the stored representation, including on legacy client edits.
    if 'rapid_upload_threshold' in rawConfig:
        config.pop('rapid_upload_min_mb', None)
    elif 'rapid_upload_min_mb' in rawConfig:
        config.pop('rapid_upload_threshold', None)
    config["auth_mode"] = requestedMode
    endpointChanged = False
    if sameMode:
        endpointChanged = _aliyunEndpointIdentity(config, requestedMode) != _aliyunEndpointIdentity(
            oldConfig, requestedMode
        )
        # The frontend deliberately masks secrets while editing a mount. Keep
        # the stored token set when the corresponding field is omitted, but
        # never forward stored secrets to a changed client_id/api_url/oauth_url.
        for field in (
            "client_secret",
            "refresh_token",
            "refresh_proof",
            "access_token",
            "expires_at",
        ):
            if rawConfig.get(field):
                continue
            if endpointChanged:
                config.pop(field, None)
            elif oldConfig.get(field):
                config[field] = oldConfig[field]
    if requestedMode == "service":
        from service.storage.aliyunAuth import _auth_server_url

        configuredServer = _auth_server_url()
        submittedServer = str(config.get("auth_service_url") or "").strip().rstrip("/")
        if submittedServer and submittedServer != configuredServer:
            raise ValueError("Aliyun authorization must use the configured public service")
        config["auth_service_url"] = configuredServer
        config["client_secret"] = ""
        if not config.get("refresh_token") or not config.get("refresh_proof"):
            if endpointChanged:
                raise ValueError("Aliyun api_url changed; scan authorization is required again")
            raise ValueError("Aliyun scan authorization is required")
    else:
        config["auth_service_url"] = ""
        config["refresh_proof"] = ""
        if not config.get("client_id") or not config.get("client_secret") or not config.get("refresh_token"):
            if endpointChanged:
                raise ValueError(
                    "Aliyun client_id, api_url or oauth_url changed; "
                    "client_secret and refresh_token must be entered again"
                )
            raise ValueError("Aliyun client_id, client_secret and refresh_token are required")
    return config


def _sftpAuthType(config):
    explicit = str(config.get("auth_type") or "").strip().lower()
    if explicit:
        return explicit
    return "private_key" if str(config.get("private_key") or "").strip() else "password"


def _sftpConnectionIdentity(config):
    try:
        port = int(config.get("port") or 22)
    except (TypeError, ValueError):
        port = config.get("port")
    return (
        str(config.get("host") or "").strip(),
        port,
        str(config.get("username") or "").strip(),
        _sftpAuthType(config),
    )


def _prepareSftpConfig(rawConfig, old=None):
    oldConfig = dict((old or {}).get("config") or {})
    config = {**oldConfig, **dict(rawConfig)}
    sameIdentity = old is not None and _sftpConnectionIdentity(
        config
    ) == _sftpConnectionIdentity(oldConfig)
    authType = _sftpAuthType(config)
    config["auth_type"] = authType
    if authType == "password":
        password = str(rawConfig.get("password") or "")
        if not password and sameIdentity:
            password = str(oldConfig.get("password") or "")
        config["password"] = password
        config["private_key"] = ""
        config["private_key_passphrase"] = ""
        if not config["password"]:
            raise ValueError("SFTP password is required for password authentication")
    elif authType == "private_key":
        privateKey = str(rawConfig.get("private_key") or "")
        if privateKey:
            # A passphrase belongs to a particular private key. Never combine a
            # newly supplied key with the previously stored key's passphrase.
            passphrase = str(rawConfig.get("private_key_passphrase") or "")
        elif sameIdentity:
            privateKey = str(oldConfig.get("private_key") or "")
            passphrase = str(
                rawConfig.get("private_key_passphrase")
                or oldConfig.get("private_key_passphrase")
                or ""
            )
        else:
            passphrase = ""
        config["private_key"] = privateKey
        config["private_key_passphrase"] = passphrase
        config["password"] = ""
        if not config["private_key"].strip():
            raise ValueError(
                "SFTP private_key is required for private key authentication"
            )
    else:
        config["password"] = ""
        config["private_key"] = ""
        config["private_key_passphrase"] = ""
    return config


def _sftpRequestConfig(data):
    engineId = int(data["engineId"])
    _requireTaoSync(engineId)
    rawConfig = data.get("config")
    if rawConfig is None:
        rawConfig = {}
    if not isinstance(rawConfig, dict):
        raise ValueError("storage configuration must be an object")

    old = None
    mountId = data.get("mountId")
    if mountId not in (None, ""):
        old = storageMapper.getMountById(int(mountId))
        if int(old["engineId"]) != engineId:
            raise ValueError("storage directory does not belong to the selected engine")
        if old["driverType"] != "sftp":
            raise ValueError("storage directory is not an SFTP mount")

    mountConfig.checkDriverFields("sftp", rawConfig)
    return _prepareSftpConfig(rawConfig, old=old)


def testSftp(data):
    """Probe SFTP credentials without adding or updating a storage mount."""
    return createDriver("sftp", _sftpRequestConfig(data)).probe()


def browseSftp(data):
    """List one SFTP directory level without persisting the supplied config."""
    if "path" not in data:
        raise ValueError("SFTP browse path is required")
    return createDriver("sftp", _sftpRequestConfig(data)).browse(data["path"])


def _folderName(name):
    if (not isinstance(name, str) or not name.strip() or name in ('.', '..')
            or '/' in name or '\\' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise ValueError(t('invalid_directory_name', get_context_lang()))
    return name


def browseAliyun(data, create=False):
    engineId = int(data["engineId"])
    _requireTaoSync(engineId)
    raw = data.get("config") or {}
    if not isinstance(raw, dict):
        raise ValueError("storage configuration must be an object")
    old = None
    if data.get("mountId") not in (None, ""):
        old = storageMapper.getMountById(int(data["mountId"]))
        if int(old["engineId"]) != engineId or old["driverType"] != "aliyun":
            raise ValueError("storage directory does not belong to the selected Aliyun engine")
    mountConfig.checkDriverFields("aliyun", raw)
    config = _prepareAliyunConfig(raw, old=old)
    authFields = ("auth_mode", "auth_service_url", "client_id", "client_secret",
                  "refresh_token", "api_url", "oauth_url")
    sameAuth = old is not None and _aliyunAuthMode(config) == _aliyunAuthMode(old["config"]) and all(
        (config.get(key) or "") == (old["config"].get(key) or "")
        for key in authFields if key != "auth_mode"
    )
    if old is not None and not sameAuth:
        for key in ("access_token", "expires_at", "drive_id"):
            config.pop(key, None)
    # Resolve the selected space independently of the saved mount root/space.
    config.pop("drive_id", None)
    config["root_folder_id"] = "root"
    callbacks = {}
    if sameAuth:
        from service.engine.taosyncClient import _get_mount_refresh_lock

        version = int(old.get("authVersion") or 1)

        def save(values, expected_tokens=None):
            values = {key: value for key, value in values.items() if key != "drive_id"}
            expected = {key: value for key, value in (expected_tokens or {}).items() if key != "drive_id"}
            result = updateMountConfig(old["id"], version, values, expectedTokens=expected)
            if isinstance(result, dict) and result.get("conflict"):
                result = {**result, "config": {key: value for key, value in
                          (result.get("config") or {}).items() if key != "drive_id"}}
            return result

        def load():
            row = dict(storageMapper.getMountById(old["id"]))
            row["config"] = {key: value for key, value in row["config"].items() if key != "drive_id"}
            return row

        callbacks = dict(save_config=save, load_config=load,
                         refresh_lock=_get_mount_refresh_lock(old["id"], version), auth_version=version)
    driver = createDriver("aliyun", config, **callbacks)
    try:
        parentId = str(data.get("parentId") or "root")
        if create:
            name = _folderName(data.get('name'))
            folder = driver.create_folder(parentId, name)
            if folder.get('exist'):
                raise FileExistsError(t('directory_name_exists', get_context_lang()))
            storedListings.cloudMkdir(driver.cache_scope(), parentId, name)
            result = {'directory': {'id': folder['file_id'], 'name': name}}
        else:
            result = {'directories': [
                {'id': item['file_id'], 'name': item.get('name') or item.get('file_name')}
                for item in driver._list_id(parentId) if item.get('type') == 'folder'
            ]}
        if not sameAuth:
            result["authorization"] = {
                key: getattr(driver, key)
                for key in ("access_token", "refresh_token", "refresh_proof", "expires_at")
            }
        return result
    finally:
        driver.session.close()


def _networkRequestConfig(data, driverType):
    engineId = int(data["engineId"])
    _requireTaoSync(engineId)
    rawConfig = data.get("config")
    if rawConfig is None:
        rawConfig = {}
    if not isinstance(rawConfig, dict):
        raise ValueError("storage configuration must be an object")

    old = None
    mountId = data.get("mountId")
    if mountId not in (None, ""):
        old = storageMapper.getMountById(int(mountId))
        if int(old["engineId"]) != engineId:
            raise ValueError("storage directory does not belong to the selected engine")
        if old["driverType"] != driverType:
            raise ValueError(t('picker_mount_type_mismatch', get_context_lang()))

    config = {**dict((old or {}).get("config") or {}), **dict(rawConfig)}
    # Passwords are masked by the frontend when an existing mount is edited.
    # Reuse the stored value only for the same host/port/user; a changed
    # target must never receive the saved password.
    if not rawConfig.get("password") and old is not None:
        if (_networkIdentity(driverType, config) == _networkIdentity(driverType, old["config"])
                and bool(config.get("tls")) == bool(old["config"].get("tls"))):
            config["password"] = old["config"].get("password", "")
        else:
            config["password"] = ""
    mountConfig.checkDriverFields(driverType, rawConfig)
    if driverType == 'smb' and config.get('share'):
        visible = discoveryService.list_smb_shares(config)
        if not any(str(item.get('name') or '').casefold() == str(config['share']).casefold() for item in visible):
            raise ValueError(t('picker_smb_share_unavailable', get_context_lang()))
    return config


def discoverSmbShares(data):
    """List shares on an SMB host without creating or updating a mount."""
    return discoveryService.list_smb_shares(_networkRequestConfig(data, 'smb'))


def remoteFolder(data, create=False):
    kind = data.get('driverType')
    if kind not in ('smb', 'ftp', 'sftp'):
        raise ValueError(t('picker_mount_type_mismatch', get_context_lang()))
    parent = data.get('path')
    if not isinstance(parent, str) or not parent.startswith('/') or normalize_path(parent) != parent:
        raise ValueError(t('picker_invalid_parent', get_context_lang()))
    name = _folderName(data.get('name')) if create else None
    config = _sftpRequestConfig(data) if kind == 'sftp' else _networkRequestConfig(data, kind)
    driver = createDriver(kind, config)
    try:
        entries = driver.list_filtered(parent, lambda child, is_dir: is_dir or child == name)
        if create:
            if any(entry['name'] == name for entry in entries):
                raise FileExistsError(t('directory_name_exists', get_context_lang()))
            path = child_path(parent, name)
            driver.mkdir(path)
            from service.engine import engineService
            engineService.getClientById(data['engineId'])._listingChange(
                {'driverType': kind, 'config': config}, path, 'directory')
            return {'directory': {'name': name, 'path': path}}
        return {'directories': [{'name': entry['name'], 'path': child_path(parent, entry['name'])}
                                for entry in entries if entry['is_dir']]}
    finally:
        if kind == 'smb':
            driver.close()


def addMount(data):
    from service.engine.engineService import validateCopyConcurrency

    engineId = int(data["engineId"])
    _requireTaoSync(engineId)
    name = _cleanName(data.get("name"))
    driverType = str(data.get("driverType") or "").strip().lower()
    raw_config = data.get("config", {})
    if not isinstance(raw_config, dict):
        raise ValueError("storage configuration must be an object")
    mountConfig.checkDriverFields(driverType, raw_config)
    _validateUniqueName(engineId, name)
    target = None
    if driverType == "crypt":
        config = mountConfig.cryptConfig(raw_config)
        target = _validateCryptTarget(engineId, config)
    elif driverType == "sftp":
        config = _prepareSftpConfig(raw_config)
    elif driverType == "aliyun":
        config = _prepareAliyunConfig(raw_config)
    else:
        config = dict(raw_config)
    mount = {
        "engineId": engineId,
        "name": name,
        "driverType": driverType,
        "config": config if target else _normalizeDriverConfig(driverType, config),
        "enabled": 1,
        "copyConcurrency": validateCopyConcurrency(data.get("copyConcurrency", 5)),
        "cacheDays": _cacheDays(data.get('cacheDays', 30)),
    }
    mountId = storageMapper.addMount(mount, target=target) if target else storageMapper.addMount(mount)
    _invalidateEngine(engineId)
    return mountId


def updateMount(data):
    from service.engine.engineService import updateMountCopyConcurrency, validateCopyConcurrency

    mountId = int(data["id"])
    old = storageMapper.getMountById(mountId)
    _requireTaoSync(old["engineId"])
    concurrency = validateCopyConcurrency(data.get("copyConcurrency", old.get("copyConcurrency", 5)))
    days = _cacheDays(data.get('cacheDays', old.get('cacheDays', 30)))
    if 'cacheDays' in data and set(data) - {'__user', '__lang'} <= {'id', 'cacheDays', 'copyConcurrency'}:
        updateMountCopyConcurrency(mountId, concurrency,
                                   persist=lambda: storageMapper.updateCachePolicy(mountId, concurrency, days))
        from service.engine import engineService
        engineService.invalidateClient(old['engineId'])
        return
    if set(data) - {"__user", "__lang"} <= {"id", "copyConcurrency"}:
        updateMountCopyConcurrency(
            mountId, concurrency,
            persist=lambda: storageMapper.updateCopyConcurrency(mountId, concurrency),
        )
        return
    name = _cleanName(data.get("name", old["name"]))
    if name != old["name"]:
        raise ValueError("storage directory names cannot be changed; remove and recreate the directory")
    driverType = str(data.get("driverType") or old["driverType"]).strip().lower()
    if driverType != old["driverType"]:
        raise ValueError("storage driver type cannot be changed")
    expectedVersion = int(old.get("configVersion", 1))
    if "configVersion" in data and data["configVersion"] != expectedVersion:
        raise ValueError("storage configuration changed; reload and retry")
    raw_config = data.get("config", {})
    if not isinstance(raw_config, dict):
        raise ValueError("storage configuration must be an object")
    mountConfig.checkDriverFields(driverType, raw_config)
    if driverType == "crypt":
        config = mountConfig.cryptConfig(raw_config, old=old["config"])
    elif driverType == "sftp":
        config = _prepareSftpConfig(raw_config, old=old)
    elif driverType == "aliyun":
        config = _prepareAliyunConfig(raw_config, old=old)
    else:
        config = {**old["config"], **dict(raw_config)}
        identityChanged = _networkIdentity(driverType, config) != _networkIdentity(
            driverType, old["config"]
        )
        for secret in SECRET_FIELDS.get(driverType, set()):
            if raw_config.get(secret):
                continue
            if identityChanged and old["config"].get(secret):
                raise ValueError(
                    "{} {} must be entered again when host, port or username changes".format(
                        driverType.upper(), secret
                    )
                )
            config[secret] = old["config"].get(secret, "")
    authFields = {
        "auth_mode", "auth_service_url", "client_id", "client_secret",
        "refresh_token", "api_url", "oauth_url"
    }
    authChanged = driverType == "aliyun" and any(
        old["config"].get(key) != config.get(key) for key in authFields
    )
    driveChanged = (
        driverType == "aliyun"
        and old["config"].get("drive_type", "resource")
        != config.get("drive_type", "resource")
    )
    if authChanged:
        for key in ("access_token", "expires_at", "drive_id"):
            config.pop(key, None)
    elif driveChanged:
        config.pop("drive_id", None)
    if driverType != "crypt":
        config = _normalizeDriverConfig(driverType, config)
    enabled = int(data.get("enabled", old.get("enabled", 1)))
    movesBacking = driverType != "crypt" and (
        enabled != 1 or mountConfig.backingLocation(driverType, config)
        != mountConfig.backingLocation(driverType, old["config"])
    )
    cloudSessionChanged = driverType == "aliyun" and any(
        (config.get(key) or "") != (old["config"].get(key) or "")
        for key in ("drive_id", "access_token", "refresh_proof")
    )
    if days != old.get('cacheDays', 30) and config == old['config'] and enabled == old.get('enabled', 1):
        updateMountCopyConcurrency(mountId, concurrency,
                                   persist=lambda: storageMapper.updateCachePolicy(mountId, concurrency, days))
        from service.engine import engineService
        engineService.invalidateClient(old['engineId'])
        return
    # Upload preferences do not change the backing storage or the directory contents.
    changedFields = {key for key in old['config'].keys() | config.keys() if old['config'].get(key) != config.get(key)}
    uploadPolicyOnly = (driverType == 'aliyun' and enabled == old.get('enabled', 1) and changedFields
                        and changedFields <= {'rapid_upload', 'rapid_upload_min_mb', 'rapid_upload_threshold'})
    storageChanged = old['config'] != config and not uploadPolicyOnly
    mount = {
        "id": mountId,
        "expectedVersion": expectedVersion,
        "expectedConcurrency": old.get("copyConcurrency", 5),
        "changesBackingLocation": movesBacking,
        "cacheDays": days,
        "resetCache": (days == 0 or old.get('cacheDays', 30) == 0 or storageChanged
                       or enabled != old.get('enabled', 1)),
        "resetDependents": storageChanged,
        "name": name,
        "driverType": driverType,
        "config": config,
        "enabled": enabled,
        "copyConcurrency": concurrency,
        "authVersion": int(old.get("authVersion", 1)) + (
            1 if authChanged or driveChanged or cloudSessionChanged else 0
        ),
    }
    updateMountCopyConcurrency(mountId, concurrency, persist=lambda: storageMapper.updateMount(mount))
    if uploadPolicyOnly:
        from service.engine import engineService
        engineService.invalidateClient(old['engineId'])
    else:
        _invalidateEngine(old["engineId"])


def updateMountConfig(mountId, expectedAuthVersion, config, expectedTokens=None):
    """Persist rotated cloud tokens without overwriting edited mount fields."""
    tokenFields = {"access_token", "refresh_token", "refresh_proof", "expires_at", "drive_id"}
    values = {key: config.get(key) for key in tokenFields if key in config}
    return storageMapper.updateMountTokens(
        int(mountId), int(expectedAuthVersion), values, expectedTokens=expectedTokens
    )


def removeMount(mountId):
    old = storageMapper.getMountById(int(mountId))
    _requireTaoSync(old["engineId"])
    storageMapper.removeMount(int(mountId))
    _invalidateEngine(old["engineId"])


def _invalidateEngine(engineId):
    # Import lazily to keep the engine and storage modules acyclic.
    from mapper import jobMapper
    from service.engine import engineService

    jobMapper.clearSourceSnapshotsByEngine(int(engineId))
    engineService.invalidateClient(int(engineId))
