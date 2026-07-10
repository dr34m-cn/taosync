<script setup>
import { onMounted, ref, computed } from "vue";
import { alistDelete, alistGet, alistPost, alistPut } from "@/api/job";
import { ElMessage, ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";

const { t } = useI18n();
const alistList = ref([]);
const getLoading = ref(false);
const deleteLoading = ref(false);
const editLoading = ref(false);
const editData = ref(null);
const editFlag = ref(false);
const editShow = ref(false);
const formRef = ref();

const editRule = computed(() => ({
  url: [
    {
      required: true,
      message: t("engine.addressRule"),
      trigger: "blur",
    },
  ],
}));

const addRule = computed(() => ({
  url: [
    {
      required: true,
      message: t("engine.addressRule"),
      trigger: "blur",
    },
  ],
  token: [
    {
      required: true,
      message: t("engine.tokenRule"),
      trigger: "blur",
    },
  ],
}));

const getAlistList = () => {
  getLoading.value = true;
  alistGet()
    .then((res) => {
      alistList.value = res.data;
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
    editData.value.url = ensureHttpPrefix(editData.value.url);
    editLoading.value = true;
    const request = editFlag.value ? alistPut(editData.value) : alistPost(editData.value);
    request
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
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
  }).then(() => {
    deleteLoading.value = true;
    alistDelete(alistId)
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
        getAlistList();
      })
      .finally(() => {
        deleteLoading.value = false;
      });
  });
};

onMounted(() => {
  getAlistList();
});
</script>

<template>
  <div class="engine">
    <div class="loading-box content-none-data" v-loading="true" v-if="getLoading">{{ $t("engine.loading") }}</div>
    <div v-else class="card-box">
      <div class="card-item" v-for="item in alistList" :key="item.id">
        <div class="card-item-top">
          <el-image src="/alist.svg" fit="contain" class="engine-logo" />
          <div class="engine-info">
            <div class="card-item-user">
              {{ item.userName }}
              <div class="card-item-remark" v-if="item.remark != null">[{{ item.remark }}]</div>
            </div>
            <div class="card-item-url">{{ item.url }}</div>
          </div>
        </div>
        <div class="card-item-bottom">
          <el-button size="small" type="primary" @click="editShowDialog(item)">{{ $t("common.edit") }}</el-button>
          <el-button size="small" type="danger" :loading="deleteLoading" @click="delAlist(item.id)">{{ $t("common.delete") }}</el-button>
        </div>
      </div>
      <div class="card-item card-add" @click="addShow" v-if="!getLoading">
        <template v-if="alistList.length == 0">{{ $t("engine.empty") }}</template>
        <span v-else>{{ $t("common.add") }}</span>
      </div>
    </div>

    <el-dialog :close-on-click-modal="false" v-model="editShow" :title="editFlag ? $t('engine.edit') : $t('engine.add')" width="600px" :append-to-body="true">
      <el-form :model="editData" :rules="editFlag ? editRule : addRule" ref="formRef" v-if="editShow" label-width="80px">
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
            :placeholder="editFlag ? $t('engine.tokenPlaceholderEdit') : $t('engine.tokenPlaceholderAdd')"
            @keyup.enter="submit"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeShow">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submit" :loading="editLoading">{{ $t("common.confirm") }}</el-button>
      </template>
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
    box-sizing: border-box;
    padding: 8px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    width: 100%;
  }

  .card-item {
    background-color: var(--home-item-background-color);
    border-radius: 6px;
    border: 1px solid transparent;
    min-height: 118px;
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

    .engine-logo {
      width: 60px;
      height: 60px;
    }

    .engine-info {
      margin-left: 12px;
      min-width: 0;
    }

    .card-item-user {
      font-size: 18px;
      display: flex;
      color: var(--text-primary);
    }

    .card-item-remark {
      margin-left: 6px;
      color: var(--warning-color);
      max-width: 120px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .card-item-url {
      margin-top: 8px;
      font-size: 12px;
      color: var(--text-secondary);
      word-break: break-all;
    }

    .card-item-bottom {
      display: flex;
      align-items: center;
      justify-content: center;
      margin-top: 12px;
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
        min-width: 0;
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
      min-height: 96px;
      justify-content: center;
    }
  }
}
</style>
