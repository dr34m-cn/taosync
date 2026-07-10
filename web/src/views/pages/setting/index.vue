<script setup>
import { computed, ref } from "vue";
import { editPwd } from "@/api/user";
import { parseTime } from "@/utils/utils";
import { useAppStore } from "@/store/useAppStore";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";

const appStore = useAppStore();
const { t } = useI18n();
const resetFormRef = ref();
const resetForm = ref({
  oldPasswd: "",
  passwd: "",
  passwd2: "",
});
const loading = ref(false);

const validatePass2 = (rule, value, callback) => {
  if (value == "" || value == null) {
    callback(new Error(t("user.newPasswd2Rule")));
  } else if (value !== resetForm.value.passwd) {
    callback(new Error(t("user.newPasswd2Error")));
  } else {
    callback();
  }
};

const rules = computed(() => ({
  oldPasswd: [
    {
      required: true,
      message: t("user.oldPasswdRule"),
      trigger: "blur",
    },
  ],
  passwd: [
    {
      required: true,
      message: t("user.newPasswdRule"),
      trigger: "blur",
    },
  ],
  passwd2: [
    {
      validator: validatePass2,
      trigger: "blur",
    },
  ],
}));

const resetPasswd = () => {
  resetFormRef.value.validate((valid) => {
    if (!valid) return;
    loading.value = true;
    editPwd(resetForm.value)
      .then((res) => {
        ElMessage({
          message: res.msg || t("user.success"),
          type: "success",
        });
        resetFormRef.value.resetFields();
      })
      .finally(() => {
        loading.value = false;
      });
  });
};
</script>

<template>
  <div class="setting">
    <div class="top-box">
      <div class="top-box-title">{{ $t("setting.title") }}</div>
    </div>
    <div class="setting-panel" v-if="appStore.user">
      <div class="item">
        <div class="label">{{ $t("setting.username") }}</div>
        <div class="value">{{ appStore.user.userName }}</div>
      </div>
      <div class="item">
        <div class="label">{{ $t("common.createdAt") }}</div>
        <div class="value">{{ parseTime(appStore.user.createTime) }}</div>
      </div>
      <el-form :model="resetForm" :rules="rules" ref="resetFormRef" label-width="0">
        <el-form-item prop="oldPasswd">
          <el-input :placeholder="$t('user.oldPasswd')" show-password v-model="resetForm.oldPasswd" />
        </el-form-item>
        <el-form-item prop="passwd">
          <el-input :placeholder="$t('user.newPasswd')" show-password v-model="resetForm.passwd" />
        </el-form-item>
        <el-form-item prop="passwd2">
          <el-input :placeholder="$t('user.newPasswd2')" show-password v-model="resetForm.passwd2" @keyup.enter="resetPasswd" />
        </el-form-item>
      </el-form>
      <el-button type="primary" :loading="loading" @click="resetPasswd">{{ $t("header.setPwd") }}</el-button>
    </div>
    <div class="setting-bottom">
      <div class="setting-bottom-item">{{ $t("setting.version") }}</div>
      <div class="setting-bottom-item">
        <a href="https://github.com/dr34m-cn/taosync" target="_blank">{{ $t("setting.github") }}</a>
      </div>
      <div class="setting-bottom-item">
        <a href="https://github.com/dr34m-cn/taosync/issues" target="_blank">{{ $t("setting.issues") }}</a>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.setting {
  padding: 32px;
  font-size: 16px;
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  position: relative;

  .setting-panel {
    padding: 24px 16px;
    background-color: var(--home-item-background-color);
    border: 1px solid var(--border-color);
    width: 360px;
    box-sizing: border-box;
    border-radius: 6px;

    .el-input,
    .el-button {
      width: 328px;
    }

    .item {
      display: flex;
      margin-bottom: 16px;

      .label {
        width: 80px;
        text-align: justify;
        margin-right: 16px;
        color: var(--text-muted);
      }

      .label::after {
        display: inline-block;
        width: 100%;
        content: "";
      }
    }
  }

  .setting-bottom {
    position: absolute;
    bottom: 20px;
    left: 0;
    right: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;

    .setting-bottom-item {
      margin: 6px 16px 6px 0;

      a {
        color: var(--active-color);
      }
    }
  }
}

@media (max-width: 768px) {
  .setting {
    height: auto;
    min-height: 100%;
    padding: 20px 12px 28px;

    .setting-panel {
      width: 100%;
      padding: 20px 14px;

      .el-input,
      .el-button {
        width: 100%;
      }

      .item {
        align-items: flex-start;

        .label {
          width: 72px;
          min-width: 72px;
          margin-right: 12px;
        }

        .value {
          min-width: 0;
          overflow-wrap: anywhere;
        }
      }
    }

    .setting-bottom {
      position: static;
      margin-top: 24px;
      flex-direction: column;
      align-items: flex-start;

      .setting-bottom-item {
        margin: 6px 0;
      }
    }
  }
}
</style>
