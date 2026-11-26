<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  alistDelete,
  alistGet,
  alistPost,
  alistPut,
  storageDelete,
  storageAliyunAuthPoll,
  storageAliyunAuthStart,
  alistCreateDirectory,
  alistGetPath,
  storageGet,
  storageLocalBrowse,
  storagePost,
  storageSmbDiscover,
  storageSmbShares,
  storageFolder,
  storageSftpTest,
  storagePut,
} from "@/api/job";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  ArrowUp,
  Connection,
  Delete,
  Edit,
  FolderOpened,
  Hide,
  Link,
  Monitor,
  Plus,
  QuestionFilled,
  RefreshRight,
  Search,
  Setting,
  View,
} from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";
import CloudFiles from "./CloudFiles.vue";
import PathSelect from '../home/components/pathSelect.vue';

const { t } = useI18n();
const alistList = ref([]);
const getLoading = ref(false);
const deleteLoading = ref(null);
const editLoading = ref(false);
const editData = ref(null);
const editFlag = ref(false);
const editShow = ref(false);
const formRef = ref();
const concurrencyShow = ref(false);
const concurrencyLoading = ref(false);
const concurrencyData = ref({ id: null, copyConcurrency: 5 });
const concurrencyMountName = ref("");

const directoryShow = ref(false);
const cloudFilesShow = ref(false);
const cloudFilesMount = ref(null);
const directoryLoading = ref(false);
const directoryList = ref([]);
const currentEngine = ref(null);
const mountShow = ref(false);
const mountEditFlag = ref(false);
const mountLoading = ref(false);
const mountDeleteLoading = ref(null);
const mountData = ref(null);
const mountFormRef = ref();
const localBrowseShow = ref(false);
const localBrowseLoading = ref(false);
const localBrowseData = ref({ path: "", parent: null, roots: [], directories: [] });
const smbDiscoverShow = ref(false);
const smbDiscoverLoading = ref(false);
const smbDevices = ref([]);
const smbShareDiscoverShow = ref(false);
const smbShareDiscoverLoading = ref(false);
const smbShares = ref([]);
const privateKeyVisible = ref(false);
const sftpTestLoading = ref(false);
const sftpTestSignature = ref("");
const sftpTestRootPath = ref("");
const sftpDirectoryOptions = ref([]);
const sftpOriginalCredentialIdentity = ref("");
const folderPicker = ref();
const aliyunAuthLoading = ref(false);
const aliyunAuthHandle = ref("");
const aliyunAuthQrCode = ref("");
const aliyunAuthorizationUrl = ref("");
const aliyunAuthStatus = ref("idle");
const aliyunAuthExpiresIn = ref(0);
let aliyunBrowseEpoch = 0;
let aliyunApplyingBrowseResult = false;
let aliyunAuthPollTimer = null;
let localBrowseRequestId = 0;
let smbDiscoverRequestId = 0;
let smbShareDiscoverRequestId = 0;
let sftpTestRequestId = 0;
let sftpApplyingTestResult = false;

const driverTypes = ["local", "smb", "ftp", "sftp", "aliyun", "crypt"];
const driverConfigKeys = {
  crypt: ["target_mount_id", "target_path", "encryption_key", "encrypt_dir_names"],
  local: ["root_path"],
  smb: ["host", "port", "share", "root_path", "domain", "username", "password"],
  ftp: ["host", "port", "root_path", "username", "password", "passive", "tls"],
  sftp: [
    "host",
    "port",
    "username",
    "root_path",
    "timeout",
    "auth_type",
    "password",
    "private_key",
    "private_key_passphrase",
    "host_key_fingerprint",
  ],
  aliyun: [
    "auth_mode",
    "auth_service_url",
    "client_id",
    "client_secret",
    "refresh_token",
    "refresh_proof",
    "access_token",
    "expires_at",
    "drive_type",
    "root_folder_id",
    "root_folder_path",
    "remove_way",
    "rapid_upload",
  ],
};

const driverDefaults = (driverType) => {
  const defaults = {
    crypt: { target_mount_id: null, target_path: "/", encryption_key: "", encrypt_dir_names: false },
    local: {
      root_path: "",
    },
    smb: {
      host: "",
      port: 445,
      share: "",
      root_path: "",
      domain: "",
      username: "",
      password: "",
    },
    ftp: {
      host: "",
      port: 21,
      root_path: "",
      username: "",
      password: "",
      passive: true,
      tls: false,
    },
    sftp: {
      host: "",
      port: 22,
      username: "",
      root_path: "/",
      timeout: 30,
      auth_type: "password",
      password: "",
      private_key: "",
      private_key_passphrase: "",
      host_key_fingerprint: "",
    },
    aliyun: {
      auth_mode: "service",
      auth_service_url: "",
      client_id: "",
      client_secret: "",
      refresh_token: "",
      refresh_proof: "",
      access_token: "",
      expires_at: 0,
      drive_type: "resource",
      root_folder_id: "root",
      root_folder_path: "/",
      remove_way: "trash",
      rapid_upload: true,
    },
  };
  return { ...defaults[driverType] };
};

const requiredRule = (messageKey, trigger = "blur") => ({
  required: true,
  message: t(messageKey),
  trigger,
});

const portRule = (_rule, value, callback) => {
  const port = Number(value);
  if (Number.isInteger(port) && port >= 1 && port <= 65535) {
    callback();
    return;
  }
  callback(new Error(t("engine.portRule")));
};

const hostKeyFingerprintRule = (_rule, value, callback) => {
  const fingerprint = String(value || "").trim();
  if (!fingerprint || /^SHA256:[A-Za-z0-9+/]+={0,2}$/.test(fingerprint)) {
    callback();
    return;
  }
  callback(new Error(t("engine.hostKeyFingerprintRule")));
};

const sftpCredentialIdentity = (config = {}) =>
  JSON.stringify({
    host: String(config.host || "").trim(),
    port: Number(config.port || 22),
    username: String(config.username || "").trim(),
    authType: config.auth_type === "private_key" ? "private_key" : "password",
  });

const hasUsableStoredSftpSecret = (field) =>
  mountEditFlag.value &&
  Boolean(sftpOriginalCredentialIdentity.value) &&
  sftpOriginalCredentialIdentity.value === sftpCredentialIdentity(mountData.value?.config) &&
  Boolean(mountData.value?.secretState?.[field]);

const hasSftpSecret = (field) => {
  const value = mountData.value?.config?.[field];
  return Boolean(String(value || "")) || hasUsableStoredSftpSecret(field);
};

const hasUsableStoredSftpPassphrase = () =>
  !String(mountData.value?.config?.private_key || "") && hasUsableStoredSftpSecret("private_key_passphrase");

const hasStoredAliyunSecret = (field) => mountEditFlag.value && Boolean(mountData.value?.secretState?.[field]);

const aliyunAuthorized = computed(() => {
  if (mountData.value?.driverType !== "aliyun") return false;
  const config = mountData.value.config || {};
  const hasRefreshToken = Boolean(String(config.refresh_token || "")) || hasStoredAliyunSecret("refresh_token");
  if (config.auth_mode === "direct") return hasRefreshToken;
  const hasRefreshProof = Boolean(String(config.refresh_proof || "")) || hasStoredAliyunSecret("refresh_proof");
  return hasRefreshToken && hasRefreshProof;
});

const editRule = computed(() => ({
  url: [requiredRule("engine.addressRule")],
}));

const cryptLocked = computed(() => mountEditFlag.value && mountData.value?.driverType === "crypt");
const cryptTargets = computed(() => directoryList.value.filter(mount => mount.driverType !== "crypt"
  && (mount.engineId == null || mount.engineId === mountData.value?.engineId)));
const cryptTarget = computed(() => cryptTargets.value.find(mount => mount.id === mountData.value?.config.target_mount_id));

function selectCryptTarget(id) {
  if (cryptLocked.value || mountData.value?.driverType !== "crypt") return;
  mountData.value.config.target_mount_id = id;
  mountData.value.config.target_path = "/";
}

watch(
  () => {
    const config = mountData.value?.config || {};
    return [mountData.value?.id, mountData.value?.driverType, config.drive_type, config.auth_mode, config.client_id, config.client_secret, config.refresh_token, config.refresh_proof];
  },
  (values, previous) => {
    if (aliyunApplyingBrowseResult || mountData.value?.driverType !== "aliyun") return;
    if (previous && values[0] === previous[0] && values[1] === previous[1] &&
        values.slice(2).some((value, index) => value !== previous[index + 2])) {
      mountData.value.config.root_folder_id = "root";
      mountData.value.config.root_folder_path = "/";
    }
    aliyunBrowseEpoch++;
  },
  { flush: "sync" }
);

const folderRoot = computed(() => {
  const { driverType, config } = mountData.value || {};
  if (driverType === 'crypt' || driverType === 'aliyun') return { path: '/', id: 'root', label: '/' };
  const base = driverType === 'sftp' ? sftpTestRootPath.value : config?.root_path;
  const path = String(base || '/').replaceAll('\\', '/');
  const label = driverType === 'smb' && config.share ? config.share + ':' + (path.startsWith('/') ? path : '/' + path) : path;
  return { path: '/', id: 'root', label };
});

const folderReady = computed(() => {
  const { driverType, config } = mountData.value || {};
  if (driverType === 'aliyun') return aliyunAuthorized.value && (config.auth_mode !== 'direct'
    || !!(config.client_id?.trim() && (config.client_secret || hasStoredAliyunSecret('client_secret'))));
  if (driverType === 'crypt') return !!cryptTarget.value && !cryptLocked.value;
  if (driverType === 'sftp') return sftpTestReady.value && !sftpTestLoading.value;
  return ['ftp', 'smb'].includes(driverType) && !!config.host?.trim() && Number.isInteger(config.port)
    && config.port > 0 && config.port <= 65535 && (driverType !== 'smb' || !!config.share?.trim());
});

async function folderOperation(parent, name) {
  const mount = mountData.value, kind = mount.driverType;
  const childPath = label => (parent.path === '/' ? '' : parent.path) + '/' + label;
  if (kind === 'crypt') {
    const target = cryptTarget.value;
    const prefix = '/' + target.name + (parent.path === '/' ? '/' : parent.path + '/');
    if (name !== undefined) {
      await alistCreateDirectory(mount.engineId, prefix, name);
      return { label: name, path: childPath(name) };
    }
    const { data } = await alistGetPath(mount.engineId, prefix);
    return data.filter(({path}) => path && path !== '.' && path !== '..' && !/[/\\]/.test(path))
      .map(({ path }) => ({ label: path, path: childPath(path) }));
  }
  const epoch = aliyunBrowseEpoch;
  const action = (kind === 'aliyun' ? 'aliyun' : 'remote') + (name === undefined ? 'Browse' : 'Mkdir');
  const { data } = await storageFolder({ action, driverType: kind, engineId: mount.engineId,
    ...(mount.id ? { mountId: mount.id } : {}), config: { ...pickDriverConfig(kind, mount.config), ...(kind === 'sftp' ? { root_path: sftpTestRootPath.value } : {}) },
    ...(kind === 'aliyun' ? { parentId: parent.id } : { path: parent.path }), name });
  if (mount !== mountData.value || !mountShow.value || epoch !== aliyunBrowseEpoch) throw new Error('stale');
  if (data.authorization) {
    aliyunApplyingBrowseResult = true;
    try { Object.assign(mount.config, data.authorization); } finally { aliyunApplyingBrowseResult = false; }
  }
  const node = item => ({ label: item.name, path: item.path || childPath(item.name), id: item.id });
  return name === undefined ? data.directories.map(node) : node(data.directory);
}

async function openFolderPicker() {
  if (!folderReady.value) return;
  if (mountData.value.driverType === 'sftp' && !sftpConnectionTestSucceeded.value
      && !await testSftpConnection()) return;
  folderPicker.value?.show();
}

function selectFolder(path, node) {
  const { driverType, config } = mountData.value;
  if (driverType === 'aliyun') Object.assign(config, { root_folder_path: path, root_folder_id: node.id });
  else if (driverType === 'crypt') config.target_path = path;
  else {
    const base = String((driverType === 'sftp' ? sftpTestRootPath.value : config.root_path) || '/').replaceAll('\\', '/').replace(/\/+$/, '');
    config.root_path = (base + (path === '/' ? '' : path)) || '/';
    if (driverType === 'sftp' && sftpConnectionTestSucceeded.value) sftpDirectoryOptions.value.push({ value: config.root_path });
  }
}

const addRule = computed(() => ({
  url: [requiredRule("engine.addressRule")],
  token: [requiredRule("engine.tokenRule")],
}));

const mountRules = computed(() => {
  const rules = {
    name: [requiredRule("engine.mountNameRule")],
    driverType: [requiredRule("engine.driverTypeRule", "change")],
  };
  const driverType = mountData.value?.driverType;
  if (driverType === "crypt" && !cryptLocked.value) {
    rules["config.target_mount_id"] = [{ ...requiredRule("engine.cryptTargetRule", "change"),
      type: "enum", enum: cryptTargets.value.map(mount => mount.id) }];
    rules["config.target_path"] = [requiredRule("engine.cryptFolder", "change")];
    rules["config.encryption_key"] = [{ ...requiredRule("engine.cryptKeyRule"), whitespace: true }];
  }
  if (driverType === "local") {
    rules["config.root_path"] = [requiredRule("engine.rootPathRule")];
  }
  if (driverType === "smb" || driverType === "ftp" || driverType === "sftp") {
    rules["config.host"] = [requiredRule("engine.hostRule")];
  }
  if (driverType === "smb") {
    rules["config.share"] = [requiredRule("engine.shareRule")];
    rules["config.port"] = [{ validator: portRule, trigger: "change" }];
  }
  if (driverType === "aliyun") {
    if (mountData.value?.config?.auth_mode === "direct") {
      rules["config.client_id"] = [requiredRule("engine.clientIdRule")];
      if (!hasStoredAliyunSecret("client_secret")) {
        rules["config.client_secret"] = [requiredRule("engine.clientSecretRule")];
      }
      if (!hasStoredAliyunSecret("refresh_token")) {
        rules["config.refresh_token"] = [requiredRule("engine.refreshTokenRule")];
      }
    }
  }
  if (driverType === "sftp") {
    rules["config.username"] = [requiredRule("engine.usernameRule")];
    rules["config.host_key_fingerprint"] = [{ validator: hostKeyFingerprintRule, trigger: "blur" }];
    const authType = mountData.value?.config?.auth_type;
    const secretField = authType === "private_key" ? "private_key" : "password";
    const hasStoredSecret = hasUsableStoredSftpSecret(secretField);
    if (!mountEditFlag.value || !hasStoredSecret) {
      const messageKey = authType === "private_key" ? "engine.privateKeyRule" : "engine.passwordRule";
      rules[`config.${secretField}`] = [requiredRule(messageKey)];
    }
  }
  return rules;
});

const smbShareDiscoverReady = computed(() => {
  if (mountData.value?.driverType !== "smb") return false;
  const config = mountData.value.config || {};
  const port = Number(config.port);
  return Boolean(String(config.host || "").trim()) && Number.isInteger(port) && port >= 1 && port <= 65535;
});

const smbShareDiscoverSignature = computed(() => {
  if (mountData.value?.driverType !== "smb") return "";
  const config = mountData.value.config || {};
  return JSON.stringify({
    host: String(config.host || "").trim(),
    port: Number(config.port || 445),
    domain: String(config.domain || "").trim(),
    username: String(config.username || "").trim(),
    password: String(config.password || ""),
  });
});

const sftpConnectionSignature = computed(() => {
  if (mountData.value?.driverType !== "sftp") return "";
  const config = mountData.value.config || {};
  const authType = config.auth_type === "private_key" ? "private_key" : "password";
  const secretField = authType === "private_key" ? "private_key" : "password";
  const secretValue = String(config[secretField] || "");
  const passphraseValue = String(config.private_key_passphrase || "");
  const secret = secretValue ? ["input", secretValue] : hasSftpSecret(secretField) ? ["stored"] : ["missing"];
  const passphrase =
    authType !== "private_key"
      ? ["unused"]
      : passphraseValue
        ? ["input", passphraseValue]
        : hasUsableStoredSftpPassphrase()
          ? ["stored"]
          : ["missing"];
  return JSON.stringify({
    host: String(config.host || "").trim(),
    port: config.port ?? "",
    username: String(config.username || "").trim(),
    timeout: config.timeout ?? "",
    authType,
    secret,
    passphrase,
    fingerprint: String(config.host_key_fingerprint || "").trim(),
  });
});

const sftpTestReady = computed(() => {
  if (mountData.value?.driverType !== "sftp") return false;
  const config = mountData.value.config || {};
  const authType = config.auth_type === "private_key" ? "private_key" : "password";
  const secretField = authType === "private_key" ? "private_key" : "password";
  const port = Number(config.port);
  const timeout = Number(config.timeout);
  return (
    Boolean(String(config.host || "").trim()) &&
    Boolean(String(config.username || "").trim()) &&
    Number.isInteger(port) &&
    port >= 1 &&
    port <= 65535 &&
    Number.isFinite(timeout) &&
    timeout >= 1 &&
    timeout <= 300 &&
    hasSftpSecret(secretField)
  );
});

const sftpRootPath = computed(() => String(mountData.value?.config?.root_path || "").trim());

const sftpConnectionTestSucceeded = computed(
  () => Boolean(sftpTestSignature.value) && sftpTestSignature.value === sftpConnectionSignature.value
);

const sftpTestSucceeded = computed(
  () => sftpConnectionTestSucceeded.value && sftpDirectoryOptions.value.some((option) => option.value === sftpRootPath.value)
);

const resetAliyunAuth = ({ keepStatus = false } = {}) => {
  if (aliyunAuthPollTimer) {
    window.clearTimeout(aliyunAuthPollTimer);
    aliyunAuthPollTimer = null;
  }
  aliyunAuthLoading.value = false;
  aliyunAuthHandle.value = "";
  aliyunAuthQrCode.value = "";
  aliyunAuthorizationUrl.value = "";
  aliyunAuthExpiresIn.value = 0;
  if (!keepStatus) aliyunAuthStatus.value = "idle";
};

const scheduleAliyunAuthPoll = (delay = 2000) => {
  if (!aliyunAuthHandle.value || !mountShow.value) return;
  aliyunAuthPollTimer = window.setTimeout(pollAliyunAuth, delay);
};

const pollAliyunAuth = async () => {
  const handle = aliyunAuthHandle.value;
  const engineId = mountData.value?.engineId;
  if (!handle || !engineId || !mountShow.value) return;
  try {
    const res = await storageAliyunAuthPoll(engineId, handle);
    if (handle !== aliyunAuthHandle.value || !mountData.value) return;
    const data = res.data || {};
    aliyunAuthStatus.value = data.status || "pending";
    aliyunAuthExpiresIn.value = Number(data.expiresIn || 0);
    if (data.status === "authorized") {
      Object.assign(mountData.value.config, data.config || {});
      mountData.value.secretState = {
        ...(mountData.value.secretState || {}),
        refresh_token: true,
        refresh_proof: true,
        access_token: true,
      };
      resetAliyunAuth({ keepStatus: true });
      nextTick(() => mountFormRef.value?.clearValidate());
      ElMessage.success(t("engine.aliyunAuthSuccess"));
      return;
    }
    scheduleAliyunAuthPoll(2000);
  } catch {
    if (handle === aliyunAuthHandle.value) {
      resetAliyunAuth();
      aliyunAuthStatus.value = "error";
    }
  }
};

const startAliyunAuth = async () => {
  if (aliyunAuthLoading.value || !mountData.value?.engineId) return;
  resetAliyunAuth();
  aliyunAuthLoading.value = true;
  try {
    const res = await storageAliyunAuthStart(mountData.value.engineId);
    const data = res.data || {};
    aliyunAuthHandle.value = String(data.handle || "");
    aliyunAuthQrCode.value = String(data.qrCode || "");
    aliyunAuthorizationUrl.value = String(data.authorizationUrl || "");
    aliyunAuthExpiresIn.value = Number(data.expiresIn || 0);
    aliyunAuthStatus.value = "pending";
    scheduleAliyunAuthPoll(Math.max(1000, Number(data.pollInterval || 2) * 1000));
  } finally {
    aliyunAuthLoading.value = false;
  }
};

const openAliyunAuthorization = () => {
  if (aliyunAuthorizationUrl.value) {
    window.open(aliyunAuthorizationUrl.value, "_blank", "noopener,noreferrer");
  }
};

const handleAliyunAuthModeChange = () => {
  resetAliyunAuth();
  if (mountData.value?.driverType === "aliyun") {
    Object.assign(mountData.value.config, {
      auth_service_url: "",
      client_id: "",
      client_secret: "",
      refresh_token: "",
      refresh_proof: "",
      access_token: "",
      expires_at: 0,
    });
    mountData.value.secretState = {};
  }
  nextTick(() => mountFormRef.value?.clearValidate());
};

const cancelActiveSftpTest = () => {
  if (!sftpTestLoading.value) return;
  sftpTestRequestId += 1;
  sftpTestLoading.value = false;
};

watch(
  sftpConnectionSignature,
  (signature, previousSignature) => {
    if (sftpApplyingTestResult || signature === previousSignature) return;
    cancelActiveSftpTest();
    sftpTestSignature.value = "";
    sftpDirectoryOptions.value = [];
  },
  { flush: "sync" }
);

watch(
  sftpRootPath,
  (rootPath, previousRootPath) => {
    if (sftpApplyingTestResult || rootPath === previousRootPath) return;
    cancelActiveSftpTest();
  },
  { flush: "sync" }
);

const isTaoSync = (engine) => engine?.engineType === "taosync";

const engineTitle = (engine) => {
  if (isTaoSync(engine)) return engine.displayName || "TaoSync";
  return engine.userName || engine.displayName || t("engine.alist");
};

const driverLabel = (driverType) => t(`engine.drivers.${driverType}`);

const getAlistList = () => {
  getLoading.value = true;
  return alistGet()
    .then((res) => {
      alistList.value = res.data || [];
    })
    .finally(() => {
      getLoading.value = false;
    });
};

const addShow = () => {
  editFlag.value = false;
  editData.value = {
    remark: "",
    url: "",
    token: "",
  };
  editShow.value = true;
};

const editShowDialog = (row) => {
  if (isTaoSync(row)) return;
  editData.value = {
    ...row,
    token: "",
  };
  editFlag.value = true;
  editShow.value = true;
};

const openConcurrency = (row, directory = false) => {
  concurrencyData.value = { id: row.id, copyConcurrency: row.copyConcurrency || 5 };
  concurrencyMountName.value = directory ? row.name : "";
  concurrencyShow.value = true;
};

const saveConcurrency = async () => {
  concurrencyLoading.value = true;
  try {
    const directory = Boolean(concurrencyMountName.value);
    await (directory ? storagePut(concurrencyData.value) : alistPut(concurrencyData.value));
    concurrencyShow.value = false;
    await (directory ? getDirectoryList() : getAlistList());
  } finally {
    concurrencyLoading.value = false;
  }
};

const closeShow = () => {
  formRef.value?.clearValidate();
  editShow.value = false;
};

const ensureHttpPrefix = (url) => {
  if (!/^https?:\/\//i.test(url)) {
    if (url.startsWith("//")) {
      return "http:" + url;
    }
    return "http://" + url;
  }
  return url;
};

const submit = () => {
  formRef.value.validate((valid) => {
    if (!valid) return;
    const postData = {
      ...editData.value,
      url: ensureHttpPrefix(editData.value.url),
    };
    editLoading.value = true;
    const request = editFlag.value ? alistPut(postData) : alistPost(postData);
    request
      .then((res) => {
        ElMessage.success(res.msg || t("common.success"));
        closeShow();
        getAlistList();
      })
      .finally(() => {
        editLoading.value = false;
      });
  });
};

const delAlist = (alistId) => {
  ElMessageBox.confirm(t("engine.deleteConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  })
    .then(() => {
      deleteLoading.value = alistId;
      return alistDelete(alistId)
        .then((res) => {
          ElMessage.success(res.msg || t("common.success"));
          return getAlistList();
        })
        .finally(() => {
          deleteLoading.value = null;
        });
    })
    .catch(() => {});
};

const getDirectoryList = () => {
  const engineId = currentEngine.value?.id;
  if (!engineId) return Promise.resolve();
  directoryLoading.value = true;
  return storageGet(engineId)
    .then((res) => {
      if (currentEngine.value?.id !== engineId) return;
      directoryList.value = res.data || [];
      currentEngine.value.directoryCount = directoryList.value.length;
      const engine = alistList.value.find((item) => item.id === currentEngine.value.id);
      if (engine) engine.directoryCount = directoryList.value.length;
    })
    .finally(() => {
      if (currentEngine.value?.id === engineId) directoryLoading.value = false;
    });
};

const manageDirectories = (engine) => {
  currentEngine.value = engine;
  directoryList.value = [];
  directoryShow.value = true;
  getDirectoryList();
};

const resetSftpTest = () => {
  sftpTestRequestId += 1;
  sftpTestLoading.value = false;
  sftpTestSignature.value = "";
  sftpTestRootPath.value = "";
  sftpDirectoryOptions.value = [];
  sftpOriginalCredentialIdentity.value = "";
};

const addMount = () => {
  resetSftpTest();
  resetAliyunAuth();
  mountEditFlag.value = false;
  privateKeyVisible.value = false;
  mountData.value = {
    engineId: currentEngine.value.id,
    name: "",
    driverType: "local",
    copyConcurrency: 5,
    cacheDays: 30,
    config: driverDefaults("local"),
  };
  mountShow.value = true;
};

const editMount = (mount) => {
  resetSftpTest();
  resetAliyunAuth();
  mountEditFlag.value = true;
  privateKeyVisible.value = false;
  mountData.value = {
    id: mount.id,
    engineId: mount.engineId,
    name: mount.name,
    driverType: mount.driverType,
    copyConcurrency: mount.copyConcurrency || 5,
    cacheDays: mount.cacheDays ?? 30,
    secretState: { ...(mount.secretState || {}) },
    config: {
      ...driverDefaults(mount.driverType),
      ...(mount.config || {}),
      ...(mount.driverType === "crypt" ? { encryption_key: "", target_path: mount.config?.target_path } : {}),
      ...(mount.driverType === "aliyun" ? {
        auth_mode: mount.config?.auth_mode || (mount.config?.auth_service_url ? "service" : "direct"),
        root_folder_path: mount.config?.root_folder_path || (mount.config?.root_folder_id && mount.config.root_folder_id !== "root" ? "" : "/"),
      } : {}),
    },
  };
  if (mount.driverType === "aliyun") {
    aliyunAuthStatus.value = aliyunAuthorized.value ? "authorized" : "idle";
  }
  if (mount.driverType === "sftp") {
    sftpOriginalCredentialIdentity.value = sftpCredentialIdentity(mountData.value.config);
  }
  mountShow.value = true;
};

const handleDriverChange = (driverType) => {
  if (mountEditFlag.value) return;
  resetSftpTest();
  resetAliyunAuth();
  localBrowseShow.value = false;
  smbDiscoverShow.value = false;
  smbShareDiscoverShow.value = false;
  privateKeyVisible.value = false;
  mountData.value.config = driverDefaults(driverType);
  nextTick(() => mountFormRef.value?.clearValidate());
};

const handleSftpAuthChange = () => {
  resetSftpTest();
  privateKeyVisible.value = false;
  nextTick(() => mountFormRef.value?.clearValidate(["config.password", "config.private_key"]));
};

const closeMount = () => {
  resetSftpTest();
  resetAliyunAuth();
  localBrowseShow.value = false;
  smbDiscoverShow.value = false;
  smbShareDiscoverShow.value = false;
  privateKeyVisible.value = false;
  mountFormRef.value?.clearValidate();
  mountShow.value = false;
};

function pickDriverConfig(driverType, config) {
  return Object.fromEntries(driverConfigKeys[driverType].map(key => [key, config[key]]));
}

const normalizeSftpDirectories = (data, currentRoot) => {
  const options = [];
  const seen = new Set();
  const append = (path) => {
    const value = String(path || "").trim();
    if (!value || seen.has(value)) return;
    seen.add(value);
    options.push({ label: value, value });
  };

  append(data?.rootPath || currentRoot || "/");
  for (const directory of Array.isArray(data?.directories) ? data.directories : []) {
    append(typeof directory === "string" ? directory : directory?.path || directory?.value);
  }
  return options;
};

const testSftpConnection = async () => {
  if (!sftpTestReady.value || sftpTestLoading.value) return false;
  const authType = mountData.value.config.auth_type === "private_key" ? "private_key" : "password";
  const secretField = authType === "private_key" ? "private_key" : "password";
  try {
    await mountFormRef.value?.validateField([
      "config.host",
      "config.username",
      `config.${secretField}`,
      "config.host_key_fingerprint",
    ]);
  } catch {
    return false;
  }

  const requestId = ++sftpTestRequestId;
  const requestSignature = sftpConnectionSignature.value;
  const requestRootPath = sftpRootPath.value;
  const payload = {
    action: "sftpTest",
    engineId: mountData.value.engineId,
    ...(mountEditFlag.value ? { mountId: mountData.value.id } : {}),
    config: pickDriverConfig("sftp", mountData.value.config),
  };
  sftpTestLoading.value = true;
  try {
    const res = await storageSftpTest(payload);
    if (
      requestId !== sftpTestRequestId ||
      requestSignature !== sftpConnectionSignature.value ||
      requestRootPath !== sftpRootPath.value
    ) {
      return;
    }
    const data = res.data || {};
    const fingerprint = String(data.fingerprint || "").trim();
    sftpApplyingTestResult = true;
    try {
      if (!String(mountData.value.config.host_key_fingerprint || "").trim() && fingerprint) {
        mountData.value.config.host_key_fingerprint = fingerprint;
      }
      const rootPath = String(data.rootPath || "").trim();
      if (rootPath) mountData.value.config.root_path = rootPath;
      sftpTestRootPath.value = rootPath || mountData.value.config.root_path || "/";
      sftpDirectoryOptions.value = normalizeSftpDirectories(data, sftpTestRootPath.value);
      sftpTestSignature.value = sftpConnectionSignature.value;
    } finally {
      sftpApplyingTestResult = false;
    }
    nextTick(() => mountFormRef.value?.clearValidate(["config.root_path", "config.host_key_fingerprint"]));
    ElMessage.success(t("engine.sftpTestSuccess"));
    return true;
  } catch {
    if (requestId === sftpTestRequestId) {
      sftpTestSignature.value = "";
      sftpTestRootPath.value = "";
      sftpDirectoryOptions.value = [];
      return false;
    }
  } finally {
    if (requestId === sftpTestRequestId) sftpTestLoading.value = false;
  }
};

const browseLocalPath = (path) => {
  const requestId = ++localBrowseRequestId;
  localBrowseLoading.value = true;
  return storageLocalBrowse(path)
    .then((res) => {
      if (requestId !== localBrowseRequestId) return;
      const data = res.data || {};
      localBrowseData.value = {
        path: data.path || "",
        parent: data.parent || null,
        roots: Array.isArray(data.roots) ? data.roots : [],
        directories: Array.isArray(data.directories) ? data.directories : [],
      };
    })
    .finally(() => {
      if (requestId === localBrowseRequestId) localBrowseLoading.value = false;
    });
};

const openLocalBrowser = () => {
  localBrowseData.value = { path: "", parent: null, roots: [], directories: [] };
  localBrowseShow.value = true;
  browseLocalPath(mountData.value?.config?.root_path || undefined);
};

const selectLocalDirectory = () => {
  if (!localBrowseData.value.path || !mountData.value) return;
  mountData.value.config.root_path = localBrowseData.value.path;
  localBrowseShow.value = false;
  nextTick(() => mountFormRef.value?.clearValidate("config.root_path"));
};

const discoverSmbDevices = () => {
  const requestId = ++smbDiscoverRequestId;
  smbDiscoverLoading.value = true;
  return storageSmbDiscover()
    .then((res) => {
      if (requestId !== smbDiscoverRequestId) return;
      const seen = new Set();
      smbDevices.value = (Array.isArray(res.data) ? res.data : []).filter((device) => {
        const address = String(device?.address || "").trim();
        if (!address || seen.has(address)) return false;
        seen.add(address);
        return true;
      });
    })
    .finally(() => {
      if (requestId === smbDiscoverRequestId) smbDiscoverLoading.value = false;
    });
};

const openSmbDiscovery = () => {
  smbDevices.value = [];
  smbDiscoverShow.value = true;
  discoverSmbDevices();
};

const selectSmbDevice = (device) => {
  if (!mountData.value || !device?.address) return;
  mountData.value.config.host = device.address;
  smbDiscoverShow.value = false;
  nextTick(() => mountFormRef.value?.clearValidate("config.host"));
};

const smbShareConfig = () => {
  const config = mountData.value?.config || {};
  return {
    host: config.host,
    port: config.port,
    domain: config.domain,
    username: config.username,
    password: config.password,
    share: "",
  };
};

const discoverSmbShares = () => {
  if (!smbShareDiscoverReady.value || smbShareDiscoverLoading.value) return Promise.resolve();
  const requestId = ++smbShareDiscoverRequestId;
  const requestSignature = smbShareDiscoverSignature.value;
  smbShareDiscoverLoading.value = true;
  return storageSmbShares({
    engineId: mountData.value.engineId,
    ...(mountEditFlag.value ? { mountId: mountData.value.id } : {}),
    config: smbShareConfig(),
  })
    .then((res) => {
      if (requestId !== smbShareDiscoverRequestId || requestSignature !== smbShareDiscoverSignature.value) return;
      const seen = new Set();
      smbShares.value = (Array.isArray(res.data) ? res.data : []).filter((share) => {
        const name = String(typeof share === "string" ? share : share?.name || "").trim();
        const key = name.toLocaleLowerCase();
        if (!name || seen.has(key)) return false;
        seen.add(key);
        return true;
      }).map((share) => (
        typeof share === "string" ? { name: String(share).trim(), comment: "" } : {
          name: String(share?.name || "").trim(),
          comment: String(share?.comment || "").trim(),
        }
      ));
    })
    .finally(() => {
      if (requestId === smbShareDiscoverRequestId) smbShareDiscoverLoading.value = false;
    });
};

const openSmbShareDiscovery = async () => {
  if (!smbShareDiscoverReady.value) {
    try {
      await mountFormRef.value?.validateField(["config.host", "config.port"]);
    } catch {
      return;
    }
    return;
  }
  smbShares.value = [];
  smbShareDiscoverShow.value = true;
  discoverSmbShares();
};

const selectSmbShare = (share) => {
  if (!mountData.value || !share?.name) return;
  if (mountData.value.config.share !== share.name) mountData.value.config.root_path = "";
  mountData.value.config.share = share.name;
  smbShareDiscoverShow.value = false;
  nextTick(() => mountFormRef.value?.clearValidate("config.share"));
};

const mountPayload = () => {
  const policy = { copyConcurrency: mountData.value.copyConcurrency, cacheDays: mountData.value.cacheDays };
  if (cryptLocked.value) return { id: mountData.value.id, ...policy };
  return {
    ...(mountEditFlag.value ? { id: mountData.value.id } : {}),
    engineId: mountData.value.engineId,
    name: mountData.value.name.trim(),
    driverType: mountData.value.driverType,
    ...policy,
    config: pickDriverConfig(mountData.value.driverType, mountData.value.config),
  };
};

const submitMount = () => {
  if (
    mountData.value?.driverType === "aliyun" &&
    mountData.value.config?.auth_mode === "service" &&
    !aliyunAuthorized.value
  ) {
    ElMessage.warning(t("engine.aliyunAuthRequired"));
    return;
  }
  mountFormRef.value.validate((valid) => {
    if (!valid) return;
    mountLoading.value = true;
    const request = mountEditFlag.value ? storagePut(mountPayload()) : storagePost(mountPayload());
    request
      .then((res) => {
        ElMessage.success(res.msg || t("common.success"));
        closeMount();
        return getDirectoryList();
      })
      .finally(() => {
        mountLoading.value = false;
      });
  });
};

const delMount = (mount) => {
  ElMessageBox.confirm(t("engine.mountDeleteConfirm", { name: mount.name }), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  })
    .then(() => {
      mountDeleteLoading.value = mount.id;
      return storageDelete(mount.id)
        .then((res) => {
          ElMessage.success(res.msg || t("common.success"));
          return getDirectoryList();
        })
        .finally(() => {
          mountDeleteLoading.value = null;
        });
    })
    .catch(() => {});
};

const mountSummary = (mount) => {
  const config = mount.config || {};
  if (mount.driverType === "crypt") {
    const target = directoryList.value.find(item => item.id === config.target_mount_id);
    return target ? `/${target.name}${config.target_path === "/" ? "" : config.target_path || ""}` : "—";
  }
  if (mount.driverType === "local") return config.root_path || "-";
  if (mount.driverType === "smb") {
    const root = config.root_path ? `/${String(config.root_path).replace(/^[/\\]+/, "")}` : "";
    return `smb://${config.host || "-"}/${config.share || "-"}${root}`;
  }
  if (mount.driverType === "ftp") {
    const protocol = config.tls ? "ftps" : "ftp";
    const root = config.root_path ? `/${String(config.root_path).replace(/^[/\\]+/, "")}` : "";
    return `${protocol}://${config.host || "-"}:${config.port || 21}${root}`;
  }
  if (mount.driverType === "sftp") {
    const root = `/${String(config.root_path || "/").replace(/^[/\\]+/, "")}`;
    return `sftp://${config.username || "-"}@${config.host || "-"}:${config.port || 22}${root}`;
  }
  if (mount.driverType === "aliyun") {
    const root = config.root_folder_path || (config.root_folder_id && config.root_folder_id !== "root" ? t("engine.rootFolder") : "/");
    return `${t(`engine.driveTypes.${config.drive_type || "resource"}`)} ${root}`;
  }
  return "-";
};

onMounted(() => {
  getAlistList();
});

onBeforeUnmount(() => {
  resetAliyunAuth();
});
</script>

<template>
  <div class="engine">
    <div v-if="getLoading" class="loading-box content-none-data" v-loading="true">{{ $t("engine.loading") }}</div>
    <div v-else class="card-box">
      <div v-for="item in alistList" :key="item.id" class="card-item" :class="{ 'taosync-card': isTaoSync(item) }">
        <div class="card-item-top">
          <el-image :src="isTaoSync(item) ? '/logo.png' : '/alist.svg'" fit="contain" class="engine-logo" />
          <div class="engine-info">
            <div class="card-item-user">
              <span>{{ engineTitle(item) }}</span>
              <span v-if="!isTaoSync(item) && item.remark" class="card-item-remark">[{{ item.remark }}]</span>
            </div>
            <div v-if="isTaoSync(item)" class="engine-meta">
              <el-tag size="small" type="success">{{ $t("engine.internal") }}</el-tag>
              <span>{{ $t("engine.directoryCount", { count: item.directoryCount || 0 }) }}</span>
            </div>
            <div v-else class="card-item-url">{{ item.url }}</div>
          </div>
        </div>
        <div class="card-item-bottom">
          <el-button
            v-if="isTaoSync(item)"
            size="small"
            type="primary"
            :icon="FolderOpened"
            @click="manageDirectories(item)"
          >
            {{ $t("engine.directoryManagement") }}
          </el-button>
          <template v-else>
            <el-button size="small" type="primary" :icon="Edit" @click="editShowDialog(item)">{{ $t("common.edit") }}</el-button>
            <el-button
              size="small"
              type="danger"
              :icon="Delete"
              :loading="deleteLoading === item.id"
              @click="delAlist(item.id)"
            >
              {{ $t("common.delete") }}
            </el-button>
          </template>
          <el-tooltip v-if="!isTaoSync(item)" :content="$t('engine.copyConcurrency')">
            <el-button size="small" :icon="Setting" :aria-label="$t('engine.copyConcurrency')" @click="openConcurrency(item)" />
          </el-tooltip>
        </div>
      </div>
      <button type="button" class="card-item card-add" @click="addShow">
        <el-icon><Plus /></el-icon>
        <span>{{ $t("engine.addAlist") }}</span>
      </button>
    </div>

    <el-dialog v-model="concurrencyShow" :title="concurrencyMountName ? $t('engine.directoryCopyConcurrency', { name: concurrencyMountName }) : $t('engine.copyConcurrency')" width="min(420px, calc(100vw - 24px))" :append-to-body="true">
      <el-form label-position="top">
        <el-form-item :label="$t('engine.copyConcurrency')">
          <el-input-number v-model="concurrencyData.copyConcurrency" :min="1" :max="100" :precision="0" :value-on-clear="5" :controls="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="concurrencyShow = false">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" :loading="concurrencyLoading" @click="saveConcurrency">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="editShow"
      :close-on-click-modal="false"
      :title="editFlag ? $t('engine.edit') : $t('engine.add')"
      width="min(600px, calc(100vw - 24px))"
      :append-to-body="true"
    >
      <el-form v-if="editShow" ref="formRef" :model="editData" :rules="editFlag ? editRule : addRule" label-width="80px">
        <el-form-item prop="url" :label="$t('engine.address')">
          <el-input v-model="editData.url" :placeholder="$t('engine.addressPlaceholder')" />
        </el-form-item>
        <el-form-item prop="remark" :label="$t('engine.remark')">
          <el-input v-model="editData.remark" :placeholder="$t('engine.remarkPlaceholder')" />
        </el-form-item>
        <el-form-item prop="token" :label="$t('engine.token')">
          <el-input
            v-model="editData.token"
            show-password
            autocomplete="new-password"
            :placeholder="editFlag ? $t('engine.tokenPlaceholderEdit') : $t('engine.tokenPlaceholderAdd')"
            @keyup.enter="submit"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeShow">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" :loading="editLoading" @click="submit">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="directoryShow"
      class="directory-dialog"
      width="min(900px, calc(100vw - 24px))"
      :title="$t('engine.directoryManagementTitle', { name: currentEngine?.displayName || 'TaoSync' })"
      :append-to-body="true"
      :close-on-click-modal="false"
    >
      <div class="directory-toolbar">
        <span>{{ $t("engine.directoryCount", { count: directoryList.length }) }}</span>
        <el-button type="primary" :icon="Plus" @click="addMount">{{ $t("engine.addDirectory") }}</el-button>
      </div>
      <div v-loading="directoryLoading" class="directory-content">
        <el-empty v-if="!directoryLoading && directoryList.length === 0" :description="$t('engine.directoryEmpty')" />
        <div v-else class="mount-list">
          <div v-for="mount in directoryList" :key="mount.id" class="mount-item">
            <div class="mount-main">
              <div class="mount-icon"><el-icon><FolderOpened /></el-icon></div>
              <div class="mount-info">
                <div class="mount-title">
                  <strong>{{ mount.name }}</strong>
                  <el-tag size="small" effect="plain">{{ driverLabel(mount.driverType) }}</el-tag>
                  <el-tag size="small" type="info">{{ $t('engine.copyConcurrencyValue', { count: mount.copyConcurrency || 5 }) }}</el-tag>
                </div>
                <div class="mount-summary">{{ mountSummary(mount) }}</div>
              </div>
            </div>
            <div class="mount-actions" :class="{ 'has-cloud-files': mount.driverType === 'aliyun' }">
              <el-tooltip v-if="mount.driverType === 'aliyun'" :content="$t('engine.cloudFiles')">
                <el-button size="small" :icon="FolderOpened" :aria-label="$t('engine.cloudFiles')"
                  @click="cloudFilesMount = mount; cloudFilesShow = true" />
              </el-tooltip>
              <el-tooltip :content="$t('engine.copyConcurrency')">
                <el-button size="small" :icon="Setting" :aria-label="$t('engine.copyConcurrency')" @click="openConcurrency(mount, true)" />
              </el-tooltip>
              <el-button size="small" type="primary" :icon="Edit" @click="editMount(mount)">{{ $t("common.edit") }}</el-button>
              <el-button
                size="small"
                type="danger"
                :icon="Delete"
                :loading="mountDeleteLoading === mount.id"
                @click="delMount(mount)"
              >
                {{ $t("common.delete") }}
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>

    <CloudFiles v-model="cloudFilesShow" :engine-id="currentEngine?.id" :mount="cloudFilesMount" :directories="directoryList" />

    <el-dialog
      v-model="mountShow"
      class="mount-editor-dialog"
      width="min(720px, calc(100vw - 24px))"
      :title="mountEditFlag ? $t('engine.editDirectory') : $t('engine.addDirectory')"
      :append-to-body="true"
      :close-on-click-modal="false"
      @close="mountData?.driverType === 'crypt' && (mountData.config.encryption_key = '')"
    >
      <el-form
        v-if="mountData"
        ref="mountFormRef"
        :model="mountData"
        :rules="mountRules"
        :validate-on-rule-change="false"
        label-position="top"
      >
        <div class="mount-form-grid">
          <el-form-item prop="name" :label="$t('engine.mountName')">
            <el-input v-model="mountData.name" :disabled="mountEditFlag" :placeholder="$t('engine.mountNamePlaceholder')" />
          </el-form-item>
          <el-form-item prop="driverType" :label="$t('engine.driverType')">
            <el-tooltip v-if="cryptLocked" :content="$t('engine.cryptLocked')" placement="top">
              <div class="crypt-locked-control" tabindex="0">
                <el-input :model-value="driverLabel('crypt')" disabled />
              </div>
            </el-tooltip>
            <el-select v-else v-model="mountData.driverType" :disabled="mountEditFlag" @change="handleDriverChange">
              <el-option v-for="driverType in driverTypes" :key="driverType" :label="driverLabel(driverType)" :value="driverType" />
            </el-select>
          </el-form-item>

          <el-form-item prop="copyConcurrency" :label="$t('engine.copyConcurrency')">
            <el-input-number v-model="mountData.copyConcurrency" :min="1" :max="100" :precision="0" :value-on-clear="5" :controls="false" />
          </el-form-item>
          <el-form-item prop="cacheDays" :label="$t('engine.cacheDays')">
            <template #label>
              {{ $t('engine.cacheDays') }}
              <el-tooltip :content="$t('engine.cacheDaysHint')" placement="top">
                <el-button link :icon="QuestionFilled" :aria-label="$t('engine.cacheDaysHint')" />
              </el-tooltip>
            </template>
            <el-input-number v-model="mountData.cacheDays" :min="-1" :max="2147483647" :precision="0" :value-on-clear="30" :controls="false" :aria-label="$t('engine.cacheDays')" />
          </el-form-item>

          <template v-if="mountData.driverType === 'crypt'">
            <el-tooltip :disabled="!cryptLocked" :content="$t('engine.cryptLocked')" placement="top">
              <div class="mount-form-grid form-span-2" :class="{ 'crypt-locked-control': cryptLocked }" :tabindex="cryptLocked ? 0 : undefined">
                <el-form-item prop="config.target_mount_id" :label="$t('engine.cryptTarget')">
                  <el-input v-if="cryptLocked" :model-value="cryptTarget?.name || mountData.config.target_mount_id || '—'" disabled />
                  <el-select v-else :model-value="mountData.config.target_mount_id" @update:model-value="selectCryptTarget"
                    :placeholder="$t('engine.cryptTargetRule')" :no-data-text="$t('engine.cryptNoTargets')">
                    <el-option v-for="target in cryptTargets" :key="target.id" :label="target.name" :value="target.id" />
                  </el-select>
                </el-form-item>
                <el-form-item prop="config.target_path" :label="$t('engine.cryptFolder')">
                  <el-input v-if="cryptLocked" :model-value="mountData.config.target_path || '—'" disabled />
                  <el-input v-else :disabled="!folderReady" :model-value="mountData.config.target_path" readonly @click="openFolderPicker">
                  <template #append><el-button :icon="Search" :disabled="!folderReady" :title="$t('pathSelect.title')"
                    :aria-label="$t('pathSelect.title')" @click.stop="openFolderPicker" /></template>
                </el-input>
                </el-form-item>
                <el-form-item prop="config.encryption_key" :label="$t('engine.cryptKey')">
                  <el-input v-if="cryptLocked" type="password" :placeholder="$t('engine.cryptKeySaved')" disabled />
                  <el-input v-else v-model="mountData.config.encryption_key" type="password" show-password autocomplete="new-password" />
                </el-form-item>
                <el-form-item prop="config.encrypt_dir_names" :label="$t('engine.cryptDirNames')">
                  <el-switch v-model="mountData.config.encrypt_dir_names" :disabled="cryptLocked" />
                </el-form-item>
              </div>
            </el-tooltip>
            <el-alert v-if="!cryptLocked" class="form-span-2" type="warning" show-icon :closable="false" :title="$t('engine.cryptWarning')" />
            <el-alert v-if="!cryptLocked" class="form-span-2" style="margin-top: 8px" type="error" show-icon :closable="false" :title="$t('engine.cryptKeyLossWarning')" />
          </template>

          <template v-else-if="mountData.driverType === 'local'">
            <el-form-item class="form-span-2" prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.localRootPlaceholder')">
                <template #append>
                  <el-tooltip :content="$t('engine.browseLocalDirectory')" placement="top">
                    <el-button
                      :icon="FolderOpened"
                      :aria-label="$t('engine.browseLocalDirectory')"
                      @click="openLocalBrowser"
                    />
                  </el-tooltip>
                </template>
              </el-input>
            </el-form-item>
          </template>

          <template v-else-if="mountData.driverType === 'smb'">
            <el-form-item prop="config.host" :label="$t('engine.host')">
              <el-input v-model="mountData.config.host" :placeholder="$t('engine.hostPlaceholder')">
                <template #append>
                  <el-tooltip :content="$t('engine.scanSmbDevices')" placement="top">
                    <el-button
                      :icon="Search"
                      :aria-label="$t('engine.scanSmbDevices')"
                      @click="openSmbDiscovery"
                    />
                  </el-tooltip>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item prop="config.port" :label="$t('engine.port')">
              <el-input-number v-model="mountData.config.port" :min="1" :max="65535" :controls="false" />
            </el-form-item>
            <el-form-item prop="config.share" :label="$t('engine.share')">
              <el-input v-model="mountData.config.share" :placeholder="$t('engine.sharePlaceholder')">
                <template #append>
                  <el-tooltip :content="$t('engine.scanSmbShares')" placement="top">
                    <el-button
                      :icon="Search"
                      :aria-label="$t('engine.scanSmbShares')"
                      :disabled="!smbShareDiscoverReady"
                      @click="openSmbShareDiscovery"
                    />
                  </el-tooltip>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.remoteRootPlaceholder')">
                <template #append>
                  <el-button :icon="Search" :disabled="!folderReady" :title="$t('pathSelect.title')"
                    :aria-label="$t('pathSelect.title')" @click="openFolderPicker" />
                </template>
              </el-input>
            </el-form-item>
            <el-form-item prop="config.domain" :label="$t('engine.domain')">
              <el-input v-model="mountData.config.domain" :placeholder="$t('engine.optional')" />
            </el-form-item>
            <el-form-item prop="config.username" :label="$t('engine.username')">
              <el-input v-model="mountData.config.username" :placeholder="$t('engine.optional')" autocomplete="username" />
            </el-form-item>
            <el-form-item class="form-span-2" prop="config.password" :label="$t('engine.password')">
              <el-input
                v-model="mountData.config.password"
                show-password
                autocomplete="new-password"
                :placeholder="mountEditFlag ? $t('engine.secretPlaceholderEdit') : $t('engine.optional')"
              />
            </el-form-item>
          </template>

          <template v-else-if="mountData.driverType === 'ftp'">
            <el-form-item prop="config.host" :label="$t('engine.host')">
              <el-input v-model="mountData.config.host" :placeholder="$t('engine.hostPlaceholder')" />
            </el-form-item>
            <el-form-item prop="config.port" :label="$t('engine.port')">
              <el-input-number v-model="mountData.config.port" :min="1" :max="65535" :controls="false" />
            </el-form-item>
            <el-form-item prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.remoteRootPlaceholder')">
                <template #append>
                  <el-button :icon="Search" :disabled="!folderReady" :title="$t('pathSelect.title')"
                    :aria-label="$t('pathSelect.title')" @click="openFolderPicker" />
                </template>
              </el-input>
            </el-form-item>
            <el-form-item prop="config.username" :label="$t('engine.username')">
              <el-input v-model="mountData.config.username" :placeholder="$t('engine.anonymousPlaceholder')" autocomplete="username" />
            </el-form-item>
            <el-form-item class="form-span-2" prop="config.password" :label="$t('engine.password')">
              <el-input
                v-model="mountData.config.password"
                show-password
                autocomplete="new-password"
                :placeholder="mountEditFlag ? $t('engine.secretPlaceholderEdit') : $t('engine.optional')"
              />
            </el-form-item>
            <el-form-item prop="config.passive" :label="$t('engine.passiveMode')">
              <el-switch v-model="mountData.config.passive" />
            </el-form-item>
            <el-form-item prop="config.tls" :label="$t('engine.tls')">
              <el-switch v-model="mountData.config.tls" />
            </el-form-item>
          </template>

          <template v-else-if="mountData.driverType === 'sftp'">
            <el-form-item prop="config.host" :label="$t('engine.host')">
              <el-input v-model="mountData.config.host" :placeholder="$t('engine.hostPlaceholder')" />
            </el-form-item>
            <el-form-item prop="config.port" :label="$t('engine.port')">
              <el-input-number v-model="mountData.config.port" :min="1" :max="65535" :controls="false" />
            </el-form-item>
            <el-form-item prop="config.username" :label="$t('engine.username')">
              <el-input v-model="mountData.config.username" :placeholder="$t('engine.usernamePlaceholder')" autocomplete="username" />
            </el-form-item>
            <el-form-item prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.remoteRootPlaceholder')">
                <template #append>
                  <el-button :icon="Search" :disabled="!folderReady" :title="$t('pathSelect.title')"
                    :aria-label="$t('pathSelect.title')" @click="openFolderPicker" />
                </template>
              </el-input>
            </el-form-item>
            <el-form-item prop="config.auth_type" :label="$t('engine.authenticationMethod')">
              <el-radio-group class="sftp-auth-methods" v-model="mountData.config.auth_type" @change="handleSftpAuthChange">
                <el-radio-button value="password">{{ $t("engine.passwordAuthentication") }}</el-radio-button>
                <el-radio-button value="private_key">{{ $t("engine.privateKeyAuthentication") }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item prop="config.timeout" :label="$t('engine.connectionTimeout')">
              <el-input-number v-model="mountData.config.timeout" :min="1" :max="300" :controls="false" />
            </el-form-item>
            <el-form-item
              v-if="mountData.config.auth_type === 'password'"
              class="form-span-2"
              prop="config.password"
              :label="$t('engine.password')"
            >
              <el-input
                v-model="mountData.config.password"
                show-password
                autocomplete="new-password"
                :placeholder="
                  hasUsableStoredSftpSecret('password') ? $t('engine.secretPlaceholderEdit') : $t('engine.passwordPlaceholder')
                "
              />
            </el-form-item>
            <template v-else>
              <el-form-item class="form-span-2" prop="config.private_key" :label="$t('engine.privateKey')">
                <div class="sftp-private-key-field">
                  <el-input
                    v-model="mountData.config.private_key"
                    type="textarea"
                    :rows="6"
                    resize="vertical"
                    autocomplete="new-password"
                    :class="{ 'private-key-masked': !privateKeyVisible }"
                    :placeholder="
                      hasUsableStoredSftpSecret('private_key')
                        ? $t('engine.secretPlaceholderEdit')
                        : $t('engine.privateKeyPlaceholder')
                    "
                  />
                  <el-tooltip
                    :content="privateKeyVisible ? $t('engine.hidePrivateKey') : $t('engine.showPrivateKey')"
                    placement="top"
                  >
                    <el-button
                      text
                      :icon="privateKeyVisible ? Hide : View"
                      :aria-label="privateKeyVisible ? $t('engine.hidePrivateKey') : $t('engine.showPrivateKey')"
                      @click="privateKeyVisible = !privateKeyVisible"
                    />
                  </el-tooltip>
                </div>
              </el-form-item>
              <el-form-item class="form-span-2" prop="config.private_key_passphrase" :label="$t('engine.privateKeyPassphrase')">
                <el-input
                  v-model="mountData.config.private_key_passphrase"
                  show-password
                  autocomplete="new-password"
                  :placeholder="
                    hasUsableStoredSftpPassphrase()
                      ? $t('engine.secretPlaceholderEdit')
                      : $t('engine.optional')
                  "
                />
              </el-form-item>
            </template>
            <el-form-item class="form-span-2 sftp-test-form-item">
              <div class="sftp-test-actions">
                <el-button
                  type="primary"
                  plain
                  :icon="Connection"
                  :loading="sftpTestLoading"
                  :disabled="!sftpTestReady"
                  @click="testSftpConnection"
                >
                  {{ $t("engine.testSftpConnection") }}
                </el-button>
                <el-tag v-if="sftpTestSucceeded" type="success" effect="plain">{{ $t("engine.sftpConnectionTested") }}</el-tag>
              </div>
            </el-form-item>
            <el-form-item class="form-span-2" prop="config.host_key_fingerprint" :label="$t('engine.hostKeyFingerprint')">
              <el-input v-model="mountData.config.host_key_fingerprint" :placeholder="$t('engine.hostKeyFingerprintPlaceholder')" />
            </el-form-item>
          </template>

          <template v-else-if="mountData.driverType === 'aliyun'">
            <el-form-item class="form-span-2" prop="config.auth_mode" :label="$t('engine.authenticationMethod')">
              <el-radio-group
                class="aliyun-auth-methods"
                v-model="mountData.config.auth_mode"
                @change="handleAliyunAuthModeChange"
              >
                <el-radio-button value="service">{{ $t("engine.scanAuthorization") }}</el-radio-button>
                <el-radio-button value="direct">{{ $t("engine.ownApplication") }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="mountData.config.auth_mode === 'service'" class="form-span-2 aliyun-auth-form-item">
              <div class="aliyun-auth-panel">
                <div class="aliyun-auth-status">
                  <strong>{{ $t("engine.aliyunAuthorization") }}</strong>
                  <el-tag v-if="aliyunAuthorized" type="success" effect="plain">{{ $t("engine.authorized") }}</el-tag>
                  <el-tag v-else-if="aliyunAuthStatus === 'pending'" type="warning" effect="plain">
                    {{ $t("engine.waitingForScan") }}
                  </el-tag>
                  <el-tag v-else-if="aliyunAuthStatus === 'error'" type="danger" effect="plain">
                    {{ $t("engine.authorizationFailed") }}
                  </el-tag>
                  <el-tag v-else type="info" effect="plain">{{ $t("engine.notAuthorized") }}</el-tag>
                </div>
                <div v-if="aliyunAuthQrCode" class="aliyun-qr-wrap">
                  <img :src="aliyunAuthQrCode" :alt="$t('engine.aliyunQrCode')" />
                  <span>{{ $t("engine.scanWithAliyunDrive") }}</span>
                  <small v-if="aliyunAuthExpiresIn > 0">
                    {{ $t("engine.authorizationExpiresIn", { seconds: aliyunAuthExpiresIn }) }}
                  </small>
                </div>
                <div class="aliyun-auth-actions">
                  <el-button
                    type="primary"
                    plain
                    :icon="RefreshRight"
                    :loading="aliyunAuthLoading"
                    @click="startAliyunAuth"
                  >
                    {{ aliyunAuthQrCode ? $t("engine.rescanAuthorization") : $t("engine.startAuthorization") }}
                  </el-button>
                  <el-button
                    v-if="aliyunAuthorizationUrl"
                    :icon="Link"
                    @click="openAliyunAuthorization"
                  >
                    {{ $t("engine.openAuthorizationPage") }}
                  </el-button>
                </div>
              </div>
            </el-form-item>
            <template v-else>
              <el-form-item prop="config.client_id" :label="$t('engine.clientId')">
                <el-input v-model="mountData.config.client_id" />
              </el-form-item>
              <el-form-item prop="config.client_secret" :label="$t('engine.clientSecret')">
                <el-input
                  v-model="mountData.config.client_secret"
                  show-password
                  autocomplete="new-password"
                  :placeholder="mountEditFlag ? $t('engine.secretPlaceholderEdit') : ''"
                />
              </el-form-item>
              <el-form-item class="form-span-2" prop="config.refresh_token" :label="$t('engine.refreshToken')">
                <el-input
                  v-model="mountData.config.refresh_token"
                  show-password
                  autocomplete="new-password"
                  :placeholder="mountEditFlag ? $t('engine.secretPlaceholderEdit') : ''"
                />
              </el-form-item>
            </template>
            <el-form-item prop="config.drive_type" :label="$t('engine.driveType')">
              <el-select v-model="mountData.config.drive_type">
                <el-option :label="$t('engine.driveTypes.resource')" value="resource" />
                <el-option :label="$t('engine.driveTypes.default')" value="default" />
                <el-option :label="$t('engine.driveTypes.backup')" value="backup" />
              </el-select>
            </el-form-item>
            <el-form-item prop="config.root_folder_id" :label="$t('engine.rootFolder')">
              <el-input :disabled="!folderReady" :model-value="mountData.config.root_folder_path || mountData.config.root_folder_id" readonly @click="openFolderPicker">
                  <template #append><el-button :icon="Search" :disabled="!folderReady" :title="$t('pathSelect.title')"
                    :aria-label="$t('pathSelect.title')" @click.stop="openFolderPicker" /></template>
                </el-input>
            </el-form-item>
            <el-form-item prop="config.rapid_upload" :label="$t('engine.rapidUpload')">
              <el-switch v-model="mountData.config.rapid_upload" :aria-label="$t('engine.rapidUpload')" />
            </el-form-item>
            <el-form-item class="form-span-2" prop="config.remove_way" :label="$t('engine.removeWay')">
              <el-radio-group v-model="mountData.config.remove_way">
                <el-radio-button value="trash">{{ $t("engine.removeWays.trash") }}</el-radio-button>
                <el-radio-button value="delete">{{ $t("engine.removeWays.delete") }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </template>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="closeMount">{{ $t("common.cancel") }}</el-button>
        <el-button
          type="primary"
          :loading="mountLoading"
          :disabled="
            mountData?.driverType === 'aliyun' && mountData.config?.auth_mode === 'service' && !aliyunAuthorized
          "
          @click="submitMount"
        >
          {{ $t("common.confirm") }}
        </el-button>
      </template>
    </el-dialog>

    <PathSelect v-if="mountShow" :key="mountData.driverType + ':' + (mountData.config.target_mount_id || '')" ref="folderPicker"
      physical-root :root-node="folderRoot" :list-folders="folderOperation" :make-folder="folderOperation" @submit="selectFolder" />

    <el-dialog
      v-model="localBrowseShow"
      class="local-browser-dialog"
      width="min(680px, calc(100vw - 24px))"
      :title="$t('engine.localBrowserTitle')"
      :append-to-body="true"
      :close-on-click-modal="false"
    >
      <div class="local-browser-toolbar">
        <div class="local-browser-path">
          <span>{{ $t("engine.currentDirectory") }}</span>
          <strong :title="localBrowseData.path">{{ localBrowseData.path || "-" }}</strong>
        </div>
        <div class="local-browser-actions">
          <el-tooltip :content="$t('engine.parentDirectory')" placement="top">
            <el-button
              :icon="ArrowUp"
              :aria-label="$t('engine.parentDirectory')"
              :disabled="!localBrowseData.parent || localBrowseLoading"
              @click="browseLocalPath(localBrowseData.parent)"
            />
          </el-tooltip>
          <el-tooltip :content="$t('engine.refreshDirectory')" placement="top">
            <el-button
              :icon="RefreshRight"
              :aria-label="$t('engine.refreshDirectory')"
              :disabled="localBrowseLoading"
              @click="browseLocalPath(localBrowseData.path || undefined)"
            />
          </el-tooltip>
        </div>
      </div>

      <section v-if="localBrowseData.roots.length" class="local-browser-roots">
        <div class="picker-section-title">{{ $t("engine.diskRoots") }}</div>
        <div class="local-root-list">
          <el-button
            v-for="root in localBrowseData.roots"
            :key="root.path"
            :type="root.path === localBrowseData.path ? 'primary' : 'default'"
            :plain="root.path !== localBrowseData.path"
            :icon="FolderOpened"
            :disabled="localBrowseLoading"
            @click="browseLocalPath(root.path)"
          >
            {{ root.name || root.path }}
          </el-button>
        </div>
      </section>

      <section class="local-browser-directories">
        <div class="picker-section-title">{{ $t("engine.subdirectories") }}</div>
        <div v-loading="localBrowseLoading" class="picker-list-content">
          <el-empty
            v-if="!localBrowseLoading && localBrowseData.directories.length === 0"
            :description="$t('engine.noSubdirectories')"
            :image-size="72"
          />
          <div v-else class="local-directory-list">
            <button
              v-for="directory in localBrowseData.directories"
              :key="directory.path"
              type="button"
              class="local-directory-item"
              :disabled="localBrowseLoading"
              @click="browseLocalPath(directory.path)"
            >
              <el-icon><FolderOpened /></el-icon>
              <span>{{ directory.name }}</span>
            </button>
          </div>
        </div>
      </section>

      <template #footer>
        <el-button @click="localBrowseShow = false">{{ $t("common.cancel") }}</el-button>
        <el-button
          type="primary"
          :disabled="!localBrowseData.path || localBrowseLoading"
          @click="selectLocalDirectory"
        >
          {{ $t("engine.selectCurrentDirectory") }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="smbDiscoverShow"
      class="smb-discovery-dialog"
      width="min(620px, calc(100vw - 24px))"
      :title="$t('engine.smbDiscoveryTitle')"
      :append-to-body="true"
      :close-on-click-modal="false"
    >
      <div class="smb-discovery-toolbar">
        <span>{{ $t("engine.smbDiscoveryDescription") }}</span>
        <el-tooltip :content="$t('engine.refreshDevices')" placement="top">
          <el-button
            :icon="RefreshRight"
            :aria-label="$t('engine.refreshDevices')"
            :loading="smbDiscoverLoading"
            @click="discoverSmbDevices"
          />
        </el-tooltip>
      </div>
      <div v-loading="smbDiscoverLoading" class="smb-device-content">
        <el-empty
          v-if="!smbDiscoverLoading && smbDevices.length === 0"
          :description="$t('engine.noSmbDevices')"
          :image-size="80"
        />
        <div v-else class="smb-device-list">
          <button
            v-for="device in smbDevices"
            :key="device.address"
            type="button"
            class="smb-device-item"
            :disabled="smbDiscoverLoading"
            @click="selectSmbDevice(device)"
          >
            <span class="smb-device-icon"><el-icon><Monitor /></el-icon></span>
            <span class="smb-device-info">
              <strong>{{ device.name || device.address }}</strong>
              <span>{{ device.address }}</span>
            </span>
            <span class="smb-device-select">{{ $t("common.select") }}</span>
          </button>
        </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="smbShareDiscoverShow"
      class="smb-discovery-dialog"
      width="min(620px, calc(100vw - 24px))"
      :title="$t('engine.smbShareDiscoveryTitle')"
      :append-to-body="true"
      :close-on-click-modal="false"
    >
      <div class="smb-discovery-toolbar">
        <span>{{ $t("engine.smbShareDiscoveryDescription") }}</span>
        <el-tooltip :content="$t('engine.refreshShares')" placement="top">
          <el-button
            :icon="RefreshRight"
            :aria-label="$t('engine.refreshShares')"
            :loading="smbShareDiscoverLoading"
            @click="discoverSmbShares"
          />
        </el-tooltip>
      </div>
      <div v-loading="smbShareDiscoverLoading" class="smb-device-content">
        <el-empty
          v-if="!smbShareDiscoverLoading && smbShares.length === 0"
          :description="$t('engine.noSmbShares')"
          :image-size="80"
        />
        <div v-else class="smb-device-list">
          <button
            v-for="share in smbShares"
            :key="share.name"
            type="button"
            class="smb-device-item"
            :disabled="smbShareDiscoverLoading"
            @click="selectSmbShare(share)"
          >
            <span class="smb-device-icon"><el-icon><FolderOpened /></el-icon></span>
            <span class="smb-device-info">
              <strong>{{ share.name }}</strong>
              <span v-if="share.comment">{{ share.comment }}</span>
            </span>
            <span class="smb-device-select">{{ $t("common.select") }}</span>
          </button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.engine {
  box-sizing: border-box;
  width: 100%;
  height: 100%;

  .loading-box {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
  }

  .card-box {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    width: 100%;
    padding: 8px;
    box-sizing: border-box;
  }

  .card-item {
    min-height: 132px;
    margin: 8px;
    padding: 12px;
    border: 1px solid transparent;
    border-radius: 6px;
    box-sizing: border-box;
    background-color: var(--home-item-background-color);
    transition: border-color 0.2s, transform 0.2s;

    &:hover {
      border-color: var(--active-color);
      transform: translateY(-1px);
    }

    .card-item-top {
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 66px;
    }

    .engine-logo {
      flex: 0 0 auto;
      width: 60px;
      height: 60px;
    }

    .engine-info {
      min-width: 0;
      margin-left: 12px;
    }

    .card-item-user {
      display: flex;
      align-items: baseline;
      min-width: 0;
      color: var(--text-primary);
      font-size: 18px;
    }

    .card-item-remark {
      max-width: 140px;
      margin-left: 6px;
      overflow: hidden;
      color: var(--warning-color);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .card-item-url,
    .engine-meta {
      margin-top: 8px;
      color: var(--text-secondary);
      font-size: 12px;
    }

    .card-item-url {
      word-break: break-all;
    }

    .engine-meta {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .card-item-bottom {
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 24px;
      margin-top: 12px;
    }
  }

  .taosync-card {
    border-color: rgba(47, 158, 68, 0.28);
  }

  .card-add {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 132px;
    color: var(--active-color);
    font: inherit;
    font-size: 18px;
    font-weight: 700;
    cursor: pointer;

    .el-icon {
      font-size: 24px;
    }
  }
}

:global(.directory-dialog .el-dialog__body) {
  padding-top: 8px;
}

:global(.directory-dialog .directory-toolbar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 40px;
  color: var(--text-secondary);
}

:global(.directory-dialog .directory-content) {
  min-height: 220px;
  margin-top: 12px;
}

:global(.directory-dialog .mount-list) {
  display: grid;
  gap: 10px;
}

:global(.directory-dialog .mount-item) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 72px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-sizing: border-box;
  background: var(--home-item-background-color);
}

:global(.directory-dialog .mount-main) {
  display: flex;
  align-items: center;
  min-width: 0;
}

:global(.directory-dialog .mount-icon) {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 6px;
  color: var(--active-color);
  background: rgba(37, 99, 235, 0.12);
  font-size: 20px;
}

:global(.directory-dialog .mount-info) {
  min-width: 0;
  margin-left: 12px;
}

:global(.directory-dialog .mount-title) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
}

:global(.directory-dialog .mount-title strong) {
  overflow-wrap: anywhere;
}

:global(.directory-dialog .mount-summary) {
  margin-top: 7px;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.directory-dialog .mount-actions) {
  display: flex;
  flex: 0 0 auto;
}

:global(.mount-editor-dialog .mount-form-grid) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

:global(.mount-editor-dialog .form-span-2) {
  grid-column: 1 / -1;
}

:global(.mount-editor-dialog .crypt-locked-control) {
  width: 100%;
  cursor: help;
}

:global(.mount-editor-dialog .crypt-locked-control .is-disabled) {
  pointer-events: none;
}

:global(.mount-editor-dialog .el-select),
:global(.mount-editor-dialog .el-input-number) {
  width: 100%;
}

:global(.mount-editor-dialog .sftp-auth-methods) {
  display: flex;
  width: 100%;
}

:global(.mount-editor-dialog .aliyun-auth-methods) {
  display: flex;
  width: 100%;
}

:global(.mount-editor-dialog .aliyun-auth-methods .el-radio-button) {
  min-width: 0;
  flex: 1;
}

:global(.mount-editor-dialog .aliyun-auth-methods .el-radio-button__inner) {
  width: 100%;
}

:global(.mount-editor-dialog .aliyun-auth-form-item .el-form-item__content) {
  display: block;
}

:global(.mount-editor-dialog .aliyun-auth-panel) {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-sizing: border-box;
  background: var(--home-item-background-color);
}

:global(.mount-editor-dialog .aliyun-auth-status) {
  display: flex;
  min-height: 28px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

:global(.mount-editor-dialog .aliyun-qr-wrap) {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
  color: var(--text-secondary);
  text-align: center;
}

:global(.mount-editor-dialog .aliyun-qr-wrap img) {
  display: block;
  width: min(220px, 70vw);
  aspect-ratio: 1;
  border: 1px solid var(--border-color);
  background: #ffffff;
}

:global(.mount-editor-dialog .aliyun-qr-wrap small) {
  color: var(--text-muted);
}

:global(.mount-editor-dialog .aliyun-auth-actions) {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

:global(.mount-editor-dialog .aliyun-auth-actions .el-button) {
  margin: 0;
}

:global(.mount-editor-dialog .sftp-auth-methods .el-radio-button) {
  min-width: 0;
  flex: 1;
}

:global(.mount-editor-dialog .sftp-auth-methods .el-radio-button__inner) {
  width: 100%;
  padding-right: 10px;
  padding-left: 10px;
}

:global(.mount-editor-dialog .sftp-test-form-item .el-form-item__content) {
  min-height: 32px;
}

:global(.mount-editor-dialog .sftp-test-actions) {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

:global(.mount-editor-dialog .sftp-private-key-field) {
  position: relative;
  width: 100%;
}

:global(.mount-editor-dialog .sftp-private-key-field > .el-button) {
  position: absolute;
  z-index: 1;
  top: 6px;
  right: 7px;
  width: 30px;
  height: 30px;
  padding: 0;
  background: var(--home-item-background-color);
}

:global(.mount-editor-dialog .sftp-private-key-field .el-textarea__inner) {
  padding-right: 42px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
}

:global(.mount-editor-dialog .sftp-private-key-field .private-key-masked .el-textarea__inner) {
  -webkit-text-security: disc;
}

:global(.sftp-root-browser-dialog .el-tree) {
  max-height: min(58vh, 520px);
  overflow: auto;
}

:global(.sftp-root-browser-dialog .el-tree-node__content) {
  min-width: max-content;
}

:global(.local-browser-dialog .el-dialog__body),
:global(.smb-discovery-dialog .el-dialog__body) {
  padding-top: 8px;
}

:global(.local-browser-dialog .local-browser-toolbar),
:global(.smb-discovery-dialog .smb-discovery-toolbar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 40px;
}

:global(.local-browser-dialog .local-browser-path) {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: baseline;
  gap: 8px;
}

:global(.local-browser-dialog .local-browser-path > span),
:global(.smb-discovery-dialog .smb-discovery-toolbar > span) {
  flex: 0 0 auto;
  color: var(--text-secondary);
  font-size: 13px;
}

:global(.local-browser-dialog .local-browser-path > strong) {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.local-browser-dialog .local-browser-actions) {
  display: flex;
  flex: 0 0 auto;
}

:global(.local-browser-dialog .local-browser-roots),
:global(.local-browser-dialog .local-browser-directories) {
  margin-top: 16px;
}

:global(.local-browser-dialog .picker-section-title) {
  margin-bottom: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

:global(.local-browser-dialog .local-root-list) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:global(.local-browser-dialog .local-root-list .el-button) {
  margin: 0;
}

:global(.local-browser-dialog .picker-list-content),
:global(.smb-discovery-dialog .smb-device-content) {
  min-height: 220px;
  max-height: min(380px, 45vh);
  overflow-y: auto;
}

:global(.local-browser-dialog .local-directory-list),
:global(.smb-discovery-dialog .smb-device-list) {
  display: grid;
  gap: 8px;
}

:global(.local-browser-dialog .local-directory-list) {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

:global(.local-browser-dialog .local-directory-item),
:global(.smb-discovery-dialog .smb-device-item) {
  display: flex;
  width: 100%;
  min-width: 0;
  min-height: 48px;
  align-items: center;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-sizing: border-box;
  color: var(--text-primary);
  background: var(--home-item-background-color);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s;
}

:global(.local-browser-dialog .local-directory-item) {
  gap: 10px;
  padding: 10px 12px;
}

:global(.local-browser-dialog .local-directory-item:hover),
:global(.local-browser-dialog .local-directory-item:focus-visible),
:global(.smb-discovery-dialog .smb-device-item:hover),
:global(.smb-discovery-dialog .smb-device-item:focus-visible) {
  border-color: var(--active-color);
  outline: none;
}

:global(.local-browser-dialog .local-directory-item:disabled),
:global(.smb-discovery-dialog .smb-device-item:disabled) {
  cursor: not-allowed;
  opacity: 0.65;
}

:global(.local-browser-dialog .local-directory-item .el-icon) {
  flex: 0 0 auto;
  color: var(--active-color);
  font-size: 20px;
}

:global(.local-browser-dialog .local-directory-item > span) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.smb-discovery-dialog .smb-discovery-toolbar) {
  margin-bottom: 12px;
}

:global(.smb-discovery-dialog .smb-device-item) {
  gap: 12px;
  padding: 10px 12px;
}

:global(.smb-discovery-dialog .smb-device-icon) {
  display: flex;
  flex: 0 0 auto;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--active-color);
  background: rgba(37, 99, 235, 0.12);
  font-size: 20px;
}

:global(.smb-discovery-dialog .smb-device-info) {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 4px;
}

:global(.smb-discovery-dialog .smb-device-info > strong),
:global(.smb-discovery-dialog .smb-device-info > span) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.smb-discovery-dialog .smb-device-info > strong) {
  font-size: 14px;
}

:global(.smb-discovery-dialog .smb-device-info > span) {
  color: var(--text-muted);
  font-size: 12px;
}

:global(.smb-discovery-dialog .smb-device-select) {
  flex: 0 0 auto;
  color: var(--active-color);
  font-size: 13px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .engine {
    .card-box {
      grid-template-columns: minmax(0, 1fr);
      padding: 4px;
    }

    .card-item {
      min-height: 0;
      margin: 4px;
      padding: 12px;

      .card-item-top {
        justify-content: flex-start;
      }

      .engine-info {
        flex: 1;
      }

      .card-item-user {
        flex-wrap: wrap;
      }

      .card-item-remark {
        max-width: min(120px, 40vw);
      }

      .card-item-bottom {
        justify-content: flex-end;
      }
    }

    .card-add {
      min-height: 92px;
    }
  }

  :global(.directory-dialog .el-dialog__body),
  :global(.mount-editor-dialog .el-dialog__body),
  :global(.local-browser-dialog .el-dialog__body),
  :global(.smb-discovery-dialog .el-dialog__body) {
    padding: 12px;
  }

  :global(.directory-dialog .mount-item) {
    align-items: stretch;
    flex-direction: column;
    gap: 10px;
  }

  :global(.directory-dialog .mount-summary) {
    overflow-wrap: anywhere;
    white-space: normal;
  }

  :global(.directory-dialog .mount-actions) {
    display: grid;
    grid-template-columns: 32px repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  :global(.directory-dialog .mount-actions .el-button) {
    width: 100%;
    margin: 0;
  }

  :global(.directory-dialog .mount-actions.has-cloud-files) {
    grid-template-columns: repeat(2, 32px) repeat(2, minmax(0, 1fr));
  }

  :global(.mount-editor-dialog .mount-form-grid) {
    grid-template-columns: minmax(0, 1fr);
  }

  :global(.mount-editor-dialog .form-span-2) {
    grid-column: auto;
  }

  :global(.mount-editor-dialog .sftp-test-actions) {
    align-items: stretch;
    flex-direction: column;
  }

  :global(.mount-editor-dialog .sftp-test-actions .el-button) {
    width: 100%;
    margin: 0;
  }

  :global(.mount-editor-dialog .sftp-test-actions .el-tag) {
    align-self: flex-start;
  }

  :global(.mount-editor-dialog .aliyun-auth-status) {
    align-items: flex-start;
    flex-direction: column;
  }

  :global(.mount-editor-dialog .aliyun-auth-actions) {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  :global(.mount-editor-dialog .aliyun-auth-actions .el-button) {
    width: 100%;
  }

  :global(.local-browser-dialog .local-browser-toolbar) {
    align-items: stretch;
    flex-direction: column;
  }

  :global(.local-browser-dialog .local-browser-path) {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  :global(.local-browser-dialog .local-browser-path > strong) {
    width: 100%;
    overflow-wrap: anywhere;
    white-space: normal;
  }

  :global(.local-browser-dialog .local-browser-actions) {
    justify-content: flex-end;
  }

  :global(.local-browser-dialog .local-directory-list) {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 420px) {
  :global(.directory-dialog .directory-toolbar) {
    align-items: stretch;
    flex-direction: column;
  }

  :global(.smb-discovery-dialog .smb-discovery-toolbar) {
    align-items: stretch;
  }

  :global(.smb-discovery-dialog .smb-discovery-toolbar > span) {
    overflow-wrap: anywhere;
  }

  :global(.smb-discovery-dialog .smb-device-item) {
    gap: 8px;
    padding: 10px;
  }

  :global(.smb-discovery-dialog .smb-device-select) {
    display: none;
  }
}
</style>
