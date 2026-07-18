import re

from mapper import storageMapper
from mapper.alistMapper import getEngineById
from service.storage.factory import SECRET_FIELDS, createDriver, getDriverTypes
from service.storage.pathIdentity import mount_paths_overlap, virtual_paths_overlap


MOUNT_NAME_PATTERN = re.compile(r"^[^\\/:\x00-\x1f]+$")


def _requireTaoSync(engineId):
    engine = getEngineById(int(engineId))
    if engine.get("engineType") != "taosync" or engine.get("systemKey") != "taosync":
        raise ValueError("storage directories can only be managed for the TaoSync engine")
    return engine


def _cleanName(name):
    name = str(name or "").strip()
    if not name or name in (".", "..") or not MOUNT_NAME_PATTERN.match(name):
        raise ValueError("invalid storage directory name")
    return name


def _sanitized(row):
    row = dict(row)
    config = dict(row.get("config") or {})
    secret_state = {}
    for field in SECRET_FIELDS.get(row["driverType"], set()):
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

    return _prepareSftpConfig(rawConfig, old=old)


def testSftp(data):
    """Probe SFTP credentials without adding or updating a storage mount."""
    return createDriver("sftp", _sftpRequestConfig(data)).probe()


def browseSftp(data):
    """List one SFTP directory level without persisting the supplied config."""
    if "path" not in data:
        raise ValueError("SFTP browse path is required")
    return createDriver("sftp", _sftpRequestConfig(data)).browse(data["path"])


def addMount(data):
    engineId = int(data["engineId"])
    _requireTaoSync(engineId)
    name = _cleanName(data.get("name"))
    driverType = str(data.get("driverType") or "").strip().lower()
    raw_config = data.get("config") or {}
    if not isinstance(raw_config, dict):
        raise ValueError("storage configuration must be an object")
    config = (
        _prepareSftpConfig(raw_config)
        if driverType == "sftp"
        else dict(raw_config)
    )
    _validateUniqueName(engineId, name)
    config = _normalizeDriverConfig(driverType, config)
    mountId = storageMapper.addMount(
        {
            "engineId": engineId,
            "name": name,
            "driverType": driverType,
            "config": config,
            "enabled": 1,
        }
    )
    _invalidateEngine(engineId)
    return mountId


def updateMount(data):
    mountId = int(data["id"])
    old = storageMapper.getMountById(mountId)
    _requireTaoSync(old["engineId"])
    name = _cleanName(data.get("name", old["name"]))
    if name != old["name"]:
        raise ValueError("storage directory names cannot be changed; remove and recreate the directory")
    driverType = str(data.get("driverType") or old["driverType"]).strip().lower()
    if driverType != old["driverType"]:
        raise ValueError("storage driver type cannot be changed")
    raw_config = data.get("config") or {}
    if not isinstance(raw_config, dict):
        raise ValueError("storage configuration must be an object")
    if driverType == "sftp":
        config = _prepareSftpConfig(raw_config, old=old)
    else:
        config = {**old["config"], **dict(raw_config)}
        for secret in SECRET_FIELDS.get(driverType, set()):
            if not config.get(secret):
                config[secret] = old["config"].get(secret, "")
    authFields = {"client_id", "client_secret", "refresh_token", "api_url", "oauth_url"}
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
    config = _normalizeDriverConfig(driverType, config)
    storageMapper.updateMount(
        {
            "id": mountId,
            "name": name,
            "driverType": driverType,
            "config": config,
            "enabled": int(data.get("enabled", old.get("enabled", 1))),
            "authVersion": int(old.get("authVersion", 1)) + (
                1 if authChanged or driveChanged else 0
            ),
        }
    )
    _invalidateEngine(old["engineId"])


def updateMountConfig(mountId, expectedAuthVersion, config, expectedTokens=None):
    """Persist rotated cloud tokens without overwriting edited mount fields."""
    tokenFields = {"access_token", "refresh_token", "expires_at", "drive_id"}
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
