<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import {
  alistDelete,
  alistGet,
  alistPost,
  alistPut,
  storageDelete,
  storageGet,
  storageLocalBrowse,
  storagePost,
  storageSmbDiscover,
  storageSftpBrowse,
  storageSftpTest,
  storagePut,
} from "@/api/job";
import { ElMessage, ElMessageBox } from "element-plus";
import { ArrowUp, Connection, Delete, Edit, FolderOpened, Hide, Monitor, Plus, RefreshRight, Search, View } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
const alistList = ref([]);
const getLoading = ref(false);
const deleteLoading = ref(null);
const editLoading = ref(false);
const editData = ref(null);
const editFlag = ref(false);
const editShow = ref(false);
const formRef = ref();

const directoryShow = ref(false);
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
const privateKeyVisible = ref(false);
const sftpTestLoading = ref(false);
const sftpTestSignature = ref("");
const sftpTestRootPath = ref("");
const sftpDirectoryOptions = ref([]);
const sftpOriginalCredentialIdentity = ref("");
const sftpRootBrowserShow = ref(false);
const sftpRootBrowserBase = ref("/");
const sftpRootBrowserSelection = ref(null);
const sftpRootTreeKey = ref(0);
let localBrowseRequestId = 0;
let smbDiscoverRequestId = 0;
let sftpTestRequestId = 0;
let sftpRootBrowseEpoch = 0;
let sftpApplyingTestResult = false;

const sftpTreeProps = {
  label: "name",
  children: "children",
  isLeaf: "leaf",
};

const driverTypes = ["local", "smb", "ftp", "sftp", "aliyun"];
const driverConfigKeys = {
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
  aliyun: ["client_id", "client_secret", "refresh_token", "drive_type", "root_folder_id", "remove_way"],
};

const driverDefaults = (driverType) => {
  const defaults = {
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
      client_id: "",
      client_secret: "",
      refresh_token: "",
      drive_type: "resource",
      root_folder_id: "root",
      remove_way: "trash",
    },
  };
  return { ...defaults[driverType] };
};

const requiredRule = (messageKey, trigger = "blur") => ({
  required: true,
  message: t(messageKey),
  trigger,
});

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

const editRule = computed(() => ({
  url: [requiredRule("engine.addressRule")],
}));

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
  if (driverType === "local") {
    rules["config.root_path"] = [requiredRule("engine.rootPathRule")];
  }
  if (driverType === "smb" || driverType === "ftp" || driverType === "sftp") {
    rules["config.host"] = [requiredRule("engine.hostRule")];
  }
  if (driverType === "smb") {
    rules["config.share"] = [requiredRule("engine.shareRule")];
  }
  if (driverType === "aliyun") {
    rules["config.client_id"] = [requiredRule("engine.clientIdRule")];
    if (!mountEditFlag.value) {
      rules["config.client_secret"] = [requiredRule("engine.clientSecretRule")];
      rules["config.refresh_token"] = [requiredRule("engine.refreshTokenRule")];
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

const resetSftpRootBrowser = () => {
  sftpRootBrowseEpoch += 1;
  sftpRootBrowserSelection.value = null;
};

const closeSftpRootBrowser = () => {
  sftpRootBrowserShow.value = false;
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
    sftpTestRootPath.value = "";
    sftpDirectoryOptions.value = [];
    sftpRootBrowserShow.value = false;
    resetSftpRootBrowser();
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
  if (!currentEngine.value) return Promise.resolve();
  directoryLoading.value = true;
  return storageGet(currentEngine.value.id)
    .then((res) => {
      directoryList.value = res.data || [];
      currentEngine.value.directoryCount = directoryList.value.length;
      const engine = alistList.value.find((item) => item.id === currentEngine.value.id);
      if (engine) engine.directoryCount = directoryList.value.length;
    })
    .finally(() => {
      directoryLoading.value = false;
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
  sftpRootBrowserShow.value = false;
  resetSftpRootBrowser();
};

const addMount = () => {
  resetSftpTest();
  mountEditFlag.value = false;
  privateKeyVisible.value = false;
  mountData.value = {
    engineId: currentEngine.value.id,
    name: "",
    driverType: "local",
    config: driverDefaults("local"),
  };
  mountShow.value = true;
};

const editMount = (mount) => {
  resetSftpTest();
  mountEditFlag.value = true;
  privateKeyVisible.value = false;
  mountData.value = {
    id: mount.id,
    engineId: mount.engineId,
    name: mount.name,
    driverType: mount.driverType,
    secretState: { ...(mount.secretState || {}) },
    config: {
      ...driverDefaults(mount.driverType),
      ...(mount.config || {}),
    },
  };
  if (mount.driverType === "sftp") {
    sftpOriginalCredentialIdentity.value = sftpCredentialIdentity(mountData.value.config);
  }
  mountShow.value = true;
};

const handleDriverChange = (driverType) => {
  resetSftpTest();
  localBrowseShow.value = false;
  smbDiscoverShow.value = false;
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
  localBrowseShow.value = false;
  smbDiscoverShow.value = false;
  privateKeyVisible.value = false;
  mountFormRef.value?.clearValidate();
  mountShow.value = false;
};

const sftpTestConfig = () => {
  const config = {};
  for (const key of driverConfigKeys.sftp) {
    config[key] = mountData.value?.config?.[key];
  }
  return config;
};

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

const mergeSftpDirectoryOptions = (data, currentRoot) => {
  const byPath = new Map(sftpDirectoryOptions.value.map((option) => [option.value, option]));
  for (const option of normalizeSftpDirectories(data, currentRoot)) {
    byPath.set(option.value, option);
  }
  sftpDirectoryOptions.value = [...byPath.values()];
};

const sftpBrowsePayload = (path) => ({
  action: "sftpBrowse",
  engineId: mountData.value.engineId,
  ...(mountEditFlag.value ? { mountId: mountData.value.id } : {}),
  path,
  config: {
    ...sftpTestConfig(),
    root_path: sftpTestRootPath.value,
  },
});

const normalizeSftpTreeNodes = (data, requestedPath) => {
  const currentPath = String(data?.path || requestedPath || "").trim();
  const seen = new Set();
  return (Array.isArray(data?.directories) ? data.directories : []).reduce((nodes, directory) => {
    const path = String(typeof directory === "string" ? directory : directory?.path || "").trim();
    if (!path || path === currentPath || seen.has(path)) return nodes;
    seen.add(path);
    const fallbackName = path.split("/").filter(Boolean).pop() || "/";
    nodes.push({
      name: String(typeof directory === "string" ? fallbackName : directory?.name || fallbackName),
      path,
      leaf: Boolean(typeof directory === "object" && directory?.leaf),
    });
    return nodes;
  }, []);
};

const loadSftpRootNode = async (node, resolve) => {
  const requestEpoch = sftpRootBrowseEpoch;
  const requestTestId = sftpTestRequestId;
  const requestSignature = sftpConnectionSignature.value;
  const requestTestRootPath = sftpTestRootPath.value;
  const requestBrowseBase = sftpRootBrowserBase.value;
  const requestRootPath = sftpRootPath.value;
  const path = node.level === 0 ? sftpRootBrowserBase.value : String(node.data?.path || "").trim();
  if (!path || !sftpConnectionTestSucceeded.value) {
    resolve([]);
    return;
  }

  try {
    const res = await storageSftpBrowse(sftpBrowsePayload(path));
    if (
      requestEpoch !== sftpRootBrowseEpoch ||
      requestTestId !== sftpTestRequestId ||
      requestSignature !== sftpConnectionSignature.value ||
      requestTestRootPath !== sftpTestRootPath.value ||
      requestBrowseBase !== sftpRootBrowserBase.value ||
      requestRootPath !== sftpRootPath.value ||
      !sftpRootBrowserShow.value
    ) {
      resolve([]);
      return;
    }
    const data = res.data || {};
    mergeSftpDirectoryOptions({ rootPath: data.path || path, directories: data.directories }, path);
    resolve(normalizeSftpTreeNodes(data, path));
  } catch {
    resolve([]);
  }
};

const openSftpRootBrowser = () => {
  if (!sftpConnectionTestSucceeded.value || !sftpTestRootPath.value) return;
  resetSftpRootBrowser();
  sftpRootBrowserBase.value = sftpTestRootPath.value;
  sftpRootTreeKey.value += 1;
  sftpRootBrowserShow.value = true;
};

const selectSftpRootNode = (directory) => {
  sftpRootBrowserSelection.value = directory?.path || null;
};

const confirmSftpRootDirectory = () => {
  if (!sftpRootBrowserSelection.value || !mountData.value) return;
  const selectedPath = sftpRootBrowserSelection.value;
  closeSftpRootBrowser();
  mountData.value.config.root_path = selectedPath;
  nextTick(() => mountFormRef.value?.clearValidate("config.root_path"));
};

const testSftpConnection = async () => {
  if (!sftpTestReady.value || sftpTestLoading.value) return;
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
    return;
  }

  const requestId = ++sftpTestRequestId;
  const requestSignature = sftpConnectionSignature.value;
  const requestRootPath = sftpRootPath.value;
  const payload = {
    action: "sftpTest",
    engineId: mountData.value.engineId,
    ...(mountEditFlag.value ? { mountId: mountData.value.id } : {}),
    config: sftpTestConfig(),
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
      sftpTestRootPath.value = rootPath || sftpRootPath.value || "/";
      sftpDirectoryOptions.value = normalizeSftpDirectories(data, mountData.value.config.root_path);
      sftpTestSignature.value = sftpConnectionSignature.value;
    } finally {
      sftpApplyingTestResult = false;
    }
    nextTick(() => mountFormRef.value?.clearValidate(["config.root_path", "config.host_key_fingerprint"]));
    ElMessage.success(t("engine.sftpTestSuccess"));
  } catch {
    if (requestId === sftpTestRequestId) {
      sftpTestSignature.value = "";
      sftpTestRootPath.value = "";
      sftpDirectoryOptions.value = [];
      sftpRootBrowserShow.value = false;
      resetSftpRootBrowser();
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

const mountPayload = () => {
  const config = {};
  for (const key of driverConfigKeys[mountData.value.driverType]) {
    config[key] = mountData.value.config[key];
  }
  return {
    ...(mountEditFlag.value ? { id: mountData.value.id } : {}),
    engineId: mountData.value.engineId,
    name: mountData.value.name.trim(),
    driverType: mountData.value.driverType,
    config,
  };
};

const submitMount = () => {
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
    return `${t(`engine.driveTypes.${config.drive_type || "resource"}`)} / ${config.root_folder_id || "root"}`;
  }
  return "-";
};

onMounted(() => {
  getAlistList();
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
        </div>
      </div>
      <button type="button" class="card-item card-add" @click="addShow">
        <el-icon><Plus /></el-icon>
        <span>{{ $t("engine.addAlist") }}</span>
      </button>
    </div>

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
                </div>
                <div class="mount-summary">{{ mountSummary(mount) }}</div>
              </div>
            </div>
            <div class="mount-actions">
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

    <el-dialog
      v-model="mountShow"
      class="mount-editor-dialog"
      width="min(720px, calc(100vw - 24px))"
      :title="mountEditFlag ? $t('engine.editDirectory') : $t('engine.addDirectory')"
      :append-to-body="true"
      :close-on-click-modal="false"
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
            <el-select v-model="mountData.driverType" :disabled="mountEditFlag" @change="handleDriverChange">
              <el-option v-for="driverType in driverTypes" :key="driverType" :label="driverLabel(driverType)" :value="driverType" />
            </el-select>
          </el-form-item>

          <template v-if="mountData.driverType === 'local'">
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
                    <el-button :icon="Search" :aria-label="$t('engine.scanSmbDevices')" @click="openSmbDiscovery" />
                  </el-tooltip>
                </template>
              </el-input>
            </el-form-item>
            <el-form-item prop="config.port" :label="$t('engine.port')">
              <el-input-number v-model="mountData.config.port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item prop="config.share" :label="$t('engine.share')">
              <el-input v-model="mountData.config.share" :placeholder="$t('engine.sharePlaceholder')" />
            </el-form-item>
            <el-form-item prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.remoteRootPlaceholder')" />
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
              <el-input-number v-model="mountData.config.port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.remoteRootPlaceholder')" />
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
              <el-input-number v-model="mountData.config.port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item prop="config.username" :label="$t('engine.username')">
              <el-input v-model="mountData.config.username" :placeholder="$t('engine.usernamePlaceholder')" autocomplete="username" />
            </el-form-item>
            <el-form-item prop="config.root_path" :label="$t('engine.rootPath')">
              <el-input v-model="mountData.config.root_path" :placeholder="$t('engine.sftpRootSelectPlaceholder')">
                <template v-if="sftpConnectionTestSucceeded" #append>
                  <el-tooltip :content="$t('pathSelect.title')" placement="top">
                    <el-button
                      :icon="FolderOpened"
                      :aria-label="$t('pathSelect.title')"
                      @click="openSftpRootBrowser"
                    />
                  </el-tooltip>
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
              <el-input-number v-model="mountData.config.timeout" :min="1" :max="300" controls-position="right" />
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
            <el-form-item prop="config.drive_type" :label="$t('engine.driveType')">
              <el-select v-model="mountData.config.drive_type">
                <el-option :label="$t('engine.driveTypes.resource')" value="resource" />
                <el-option :label="$t('engine.driveTypes.default')" value="default" />
                <el-option :label="$t('engine.driveTypes.backup')" value="backup" />
              </el-select>
            </el-form-item>
            <el-form-item prop="config.root_folder_id" :label="$t('engine.rootFolderId')">
              <el-input v-model="mountData.config.root_folder_id" placeholder="root" />
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
        <el-button type="primary" :loading="mountLoading" @click="submitMount">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="sftpRootBrowserShow"
      class="sftp-root-browser-dialog"
      top="8vh"
      width="min(520px, calc(100vw - 24px))"
      :title="$t('pathSelect.title')"
      :append-to-body="true"
      :close-on-click-modal="false"
      @close="resetSftpRootBrowser"
    >
      <el-tree
        v-if="sftpRootBrowserShow"
        :key="sftpRootTreeKey"
        :props="sftpTreeProps"
        :load="loadSftpRootNode"
        lazy
        highlight-current
        check-on-click-node
        @node-click="selectSftpRootNode"
      />
      <template #footer>
        <el-button @click="closeSftpRootBrowser">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" :disabled="sftpRootBrowserSelection == null" @click="confirmSftpRootDirectory">
          {{ sftpRootBrowserSelection == null ? $t("pathSelect.selectFirst") : $t("common.confirm") }}
        </el-button>
      </template>
    </el-dialog>

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
  align-items: center;
  gap: 8px;
  color: var(--text-primary);
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

:global(.mount-editor-dialog .el-select),
:global(.mount-editor-dialog .el-input-number) {
  width: 100%;
}

:global(.mount-editor-dialog .sftp-auth-methods) {
  display: flex;
  width: 100%;
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
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  :global(.directory-dialog .mount-actions .el-button) {
    width: 100%;
    margin: 0;
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
