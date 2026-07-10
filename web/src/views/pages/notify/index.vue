<script setup>
import { computed, onMounted, ref } from "vue";
import { delNotify, getNotifyList, postAddNotify, putEditNotify, putEnableNotify } from "@/api/notify";
import notifyMethod, { notifyMethodKeys } from "@/utils/notifyMethod";
import { ElMessage, ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
const notifyMethodLength = notifyMethodKeys.length;
const dataList = ref([]);
const loading = ref(false);
const deleteLoading = ref(false);
const editLoading = ref(false);
const tstLoading = ref(false);
const enableLoading = ref(false);
const editData = ref(null);
const editFlag = ref(false);
const editShow = ref(false);
const formRef = ref();

const editRule = computed(() => [
  {
    params: {
      url: [{ type: "string", required: true, message: t("notify.requestUrl"), trigger: "blur" }],
      titleName: [{ type: "string", required: true, message: t("notify.titleName"), trigger: "blur" }],
      contentName: [{ type: "string", required: true, message: t("notify.contentName"), trigger: "blur" }],
    },
  },
  {
    params: {
      sendKey: [{ type: "string", required: true, message: t("notify.sendKey"), trigger: "blur" }],
    },
  },
  {
    params: {
      url: [{ type: "string", required: true, message: t("notify.webhook"), trigger: "blur" }],
    },
  },
  {
    params: {
      corpid: [{ type: "string", required: true, message: t("notify.corpid"), trigger: "blur" }],
      agentid: [{ type: "string", required: true, message: t("notify.agentid"), trigger: "blur" }],
      corpsecret: [{ type: "string", required: true, message: t("notify.corpsecret"), trigger: "blur" }],
      touser: [{ type: "string", required: false, trigger: "blur" }],
    },
  },
  {
    params: {
      url: [{ type: "string", required: true, message: t("notify.webhook"), trigger: "blur" }],
    },
  },
]);

const getData = () => {
  loading.value = true;
  getNotifyList()
    .then((res) => {
      dataList.value = res.data;
    })
    .finally(() => {
      loading.value = false;
    });
};

const addShow = () => {
  editFlag.value = false;
  editData.value = {
    enable: 1,
    method: 1,
    params: {
      sendKey: "",
      notSendNull: false,
    },
  };
  editShow.value = true;
};

const editShowDialog = (row) => {
  const nextEditData = JSON.parse(JSON.stringify(row));
  nextEditData.params = JSON.parse(nextEditData.params);
  if (!Object.hasOwn(nextEditData.params, "notSendNull")) {
    nextEditData.params.notSendNull = false;
  }
  editData.value = nextEditData;
  editFlag.value = true;
  editShow.value = true;
};

const methodChange = (val) => {
  if (val === 0) {
    editData.value.params = {
      url: "",
      method: "POST",
      contentType: "application/json",
      needContent: true,
      titleName: "title",
      contentName: "content",
      notSendNull: false,
    };
  } else if (val === 1) {
    editData.value.params = {
      sendKey: "",
      notSendNull: false,
    };
  } else if (val === 2) {
    editData.value.params = {
      url: "",
      notSendNull: false,
    };
  } else if (val === 3) {
    editData.value.params = {
      corpid: "",
      agentid: "",
      corpsecret: "",
      touser: "@all",
      notSendNull: false,
    };
  } else if (val === 4) {
    editData.value.params = {
      url: "",
      notSendNull: false,
    };
  }
  setTimeout(() => {
    formRef.value?.clearValidate();
  });
};

const closeShow = () => {
  formRef.value?.clearValidate();
  editShow.value = false;
};

const enableNotify = (notifyId, enable) => {
  enableLoading.value = true;
  putEnableNotify(notifyId, enable)
    .then((res) => {
      ElMessage({
        message: res.msg,
        type: "success",
      });
      getData();
    })
    .finally(() => {
      enableLoading.value = false;
    });
};

const submit = () => {
  formRef.value.validate((valid) => {
    if (!valid) return;
    const dt = JSON.parse(JSON.stringify(editData.value));
    dt.params = JSON.stringify(dt.params);
    editLoading.value = true;
    const request = editFlag.value ? putEditNotify(dt) : postAddNotify(dt);
    request
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
        closeShow();
        getData();
      })
      .finally(() => {
        editLoading.value = false;
      });
  });
};

const tstCuTrueDo = (item) => {
  tstLoading.value = true;
  const it = JSON.parse(JSON.stringify(item));
  if (typeof it.params === "object" && it.params !== null) {
    it.params = JSON.stringify(it.params);
  }
  delete it.enable;
  postAddNotify(it)
    .then(() => {
      ElMessage({
        message: t("notify.testSent"),
        type: "success",
      });
    })
    .finally(() => {
      tstLoading.value = false;
    });
};

const tstCu = (item = null) => {
  if (item == null) {
    formRef.value.validate((valid) => {
      if (valid) {
        tstCuTrueDo(editData.value);
      }
    });
  } else {
    tstCuTrueDo(item);
  }
};

const delCu = (id) => {
  ElMessageBox.confirm(t("notify.deleteConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(() => {
    deleteLoading.value = true;
    delNotify(id)
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
        getData();
      })
      .finally(() => {
        deleteLoading.value = false;
      });
  });
};

onMounted(() => {
  getData();
});
</script>

<template>
  <div class="notify">
    <div class="loading-box content-none-data" v-loading="true" v-if="loading">{{ $t("notify.loading") }}</div>
    <div v-else class="card-box">
      <div class="card-item" v-for="item in dataList" :key="item.id">
        <div class="card-item-top">
          <el-image :src="`/notify/${item.method}.png`" fit="contain" class="notify-logo" />
          <div class="notify-info">
            <div class="card-item-user">{{ notifyMethod(item.method) }}</div>
            <div :class="`card-item-enable enable-${item.enable == 1 ? 'enable' : 'disable'}`">
              {{ item.enable == 1 ? $t("notify.enabled") : $t("notify.disabled") }}
            </div>
          </div>
        </div>
        <div class="card-item-bottom">
          <el-button size="small" type="primary" @click="editShowDialog(item)">{{ $t("common.edit") }}</el-button>
          <el-button size="small" type="success" v-if="item.enable == 0" :loading="enableLoading" @click="enableNotify(item.id, 1)">
            {{ $t("common.enable") }}
          </el-button>
          <el-button size="small" type="warning" v-else :loading="enableLoading" @click="enableNotify(item.id, 0)">
            {{ $t("common.disable") }}
          </el-button>
          <el-button size="small" type="primary" :loading="tstLoading" @click="tstCu(item)">{{ $t("common.test") }}</el-button>
          <el-button size="small" type="danger" :loading="deleteLoading" @click="delCu(item.id)">{{ $t("common.delete") }}</el-button>
        </div>
      </div>
      <div class="card-item card-add" @click="addShow" v-if="!loading">
        <template v-if="dataList.length == 0">{{ $t("notify.empty") }}</template>
        <span v-else>{{ $t("common.add") }}</span>
      </div>
    </div>

    <el-dialog :close-on-click-modal="false" top="6vh" v-model="editShow" :title="editFlag ? $t('notify.edit') : $t('notify.add')" width="700px" :append-to-body="true">
      <el-form :model="editData" :rules="editRule[editData.method]" ref="formRef" v-if="editShow" label-width="110px">
        <el-form-item prop="enable" :label="$t('common.enabled')">
          <el-switch v-model="editData.enable" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item prop="method" :label="$t('notify.method')" class="notify-method-form-item">
          <el-select v-model="editData.method" @change="methodChange" style="width: 100%">
            <el-option :key="meItem - 1" :value="meItem - 1" :label="notifyMethod(meItem - 1)" v-for="meItem in notifyMethodLength" />
          </el-select>
          <i18n-t v-if="editData.method == 1" keypath="notify.serverChanTip" tag="div" class="tip-box">
            <template #serverChanT>
              <a href="https://sct.ftqq.com/r/15503" target="_blank" rel="noopener noreferrer">{{ $t("notify.serverChanT") }}</a>
            </template>
            <template #serverChan3>
              <a href="https://sc3.ft07.com/" target="_blank" rel="noopener noreferrer">{{ $t("notify.serverChan3") }}</a>
            </template>
          </i18n-t>
          <i18n-t v-else-if="editData.method == 2" keypath="notify.dingTalkTip" tag="div" class="tip-box">
            <template #configGuide>
              <a href="https://open.dingtalk.com/document/orgapp/custom-bot-creation-and-installation" target="_blank" rel="noopener noreferrer">
                {{ $t("notify.configGuide") }}
              </a>
            </template>
          </i18n-t>
          <i18n-t v-else-if="editData.method == 3" keypath="notify.weComTip" tag="div" class="tip-box">
            <template #configGuide>
              <a href="https://sct.ftqq.com/forward" target="_blank" rel="noopener noreferrer">{{ $t("notify.configGuide") }}</a>
            </template>
          </i18n-t>
          <i18n-t v-else-if="editData.method == 4" keypath="notify.larkTip" tag="div" class="tip-box">
            <template #configGuide>
              <a href="https://open.larksuite.com/document/client-docs/bot-v3/add-custom-bot" target="_blank" rel="noopener noreferrer">
                {{ $t("notify.configGuide") }}
              </a>
            </template>
          </i18n-t>
        </el-form-item>
        <template v-if="editData.method == 0">
          <el-form-item prop="params.url" :label="$t('notify.requestUrl')">
            <el-input v-model="editData.params.url" :placeholder="$t('notify.requestUrl')" />
          </el-form-item>
          <el-form-item prop="params.method" :label="$t('notify.requestMethod')">
            <el-select v-model="editData.params.method" style="width: 100%">
              <el-option key="POST" value="POST" label="POST" />
              <el-option key="PUT" value="PUT" label="PUT" />
              <el-option key="GET" value="GET" label="GET" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editData.params.method != 'GET'" prop="params.contentType" :label="$t('notify.contentType')">
            <el-select v-model="editData.params.contentType" style="width: 100%">
              <el-option key="application/json" value="application/json" label="application/json" />
              <el-option key="application/x-www-form-urlencoded" value="application/x-www-form-urlencoded" label="application/x-www-form-urlencoded" />
            </el-select>
          </el-form-item>
          <el-form-item prop="params.titleName" :label="$t('notify.titleName')">
            <el-input v-model="editData.params.titleName" :placeholder="$t('notify.titleName')" />
          </el-form-item>
          <el-form-item prop="params.needContent" :label="$t('notify.needContent')">
            <el-select v-model="editData.params.needContent" style="width: 100%">
              <el-option :key="true" :value="true" :label="$t('notify.need')" />
              <el-option :key="false" :value="false" :label="$t('notify.notNeed')" />
            </el-select>
          </el-form-item>
          <el-form-item prop="params.contentName" v-if="editData.params.needContent" :label="$t('notify.contentName')">
            <el-input v-model="editData.params.contentName" :placeholder="$t('notify.contentName')" />
          </el-form-item>
        </template>
        <template v-else-if="editData.method == 1">
          <el-form-item prop="params.sendKey" :label="$t('notify.sendKey')">
            <el-input v-model="editData.params.sendKey" :placeholder="$t('notify.sendKey')" />
          </el-form-item>
        </template>
        <template v-else-if="editData.method == 2">
          <el-form-item prop="params.url" :label="$t('notify.webhook')">
            <el-input v-model="editData.params.url" placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxxx" />
          </el-form-item>
        </template>
        <template v-else-if="editData.method == 3">
          <el-form-item prop="params.corpid" :label="$t('notify.corpid')">
            <el-input v-model="editData.params.corpid" :placeholder="$t('notify.corpid')" />
          </el-form-item>
          <el-form-item prop="params.agentid" :label="$t('notify.agentid')">
            <el-input v-model="editData.params.agentid" :placeholder="$t('notify.agentid')" />
          </el-form-item>
          <el-form-item prop="params.corpsecret" :label="$t('notify.corpsecret')">
            <el-input v-model="editData.params.corpsecret" :placeholder="$t('notify.corpsecret')" type="password" />
          </el-form-item>
          <el-form-item prop="params.touser" :label="$t('notify.touser')">
            <el-input v-model="editData.params.touser" :placeholder="$t('notify.touserPlaceholder')" />
          </el-form-item>
        </template>
        <template v-else-if="editData.method == 4">
          <el-form-item prop="params.url" :label="$t('notify.webhook')">
            <el-input v-model="editData.params.url" placeholder="https://open.larksuite.com/open-apis/bot/v2/hook/xxxxxxxxxx" />
          </el-form-item>
        </template>
        <el-form-item prop="params.notSendNull" :label="$t('notify.notSendNull')">
          <el-switch v-model="editData.params.notSendNull" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeShow">{{ $t("common.cancel") }}</el-button>
        <el-button type="success" :loading="tstLoading" @click="tstCu()">{{ $t("common.test") }}</el-button>
        <el-button type="primary" @click="submit" :loading="editLoading">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.notify {
  box-sizing: border-box;
  width: 100%;
  height: 100%;

  .loading-box {
    box-sizing: border-box;
    width: 100%;
    height: 100%;
  }

  .card-box {
    box-sizing: border-box;
    padding: 8px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(390px, 1fr));
    width: 100%;
  }

  .card-item {
    background-color: var(--home-item-background-color);
    border-radius: 6px;
    border: 1px solid transparent;
    min-height: 120px;
    margin: 8px;
    padding: 10px;
    box-sizing: border-box;
    transition: border-color 0.2s, transform 0.2s;

    &:hover {
      border-color: var(--active-color);
      transform: translateY(-1px);
    }

    .card-item-top {
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .notify-logo {
      width: 60px;
      height: 60px;
    }

    .notify-info {
      margin-left: 12px;
    }

    .card-item-user {
      font-size: 18px;
      color: var(--text-primary);
    }

    .card-item-enable {
      margin-top: 6px;
      font-weight: 700;
    }

    .enable-enable {
      color: var(--success-color);
    }

    .enable-disable {
      color: var(--fail-color);
    }

    .card-item-bottom {
      display: flex;
      align-items: center;
      justify-content: center;
      margin-top: 12px;
      flex-wrap: wrap;
      gap: 6px;
    }
  }

  .card-add {
    font-size: 26px;
    cursor: pointer;
    display: flex;
    justify-content: center;
    align-items: center;
    color: var(--active-color);
    font-weight: 700;
  }

}

.notify-method-form-item {
  :deep(.el-form-item__content) {
    display: block;
  }
}

.tip-box {
  margin-top: 6px;
  line-height: 1.5;
  color: var(--text-muted);

  a {
    color: var(--active-color);

    &:hover {
      opacity: 0.8;
    }
  }
}

@media (max-width: 768px) {
  .notify {
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

      .notify-info {
        min-width: 0;
      }

      .card-item-bottom {
        justify-content: flex-start;
      }
    }

    .card-add {
      min-height: 96px;
      justify-content: center;
    }
  }

  .tip-box {
    font-size: 13px;
  }
}
</style>
