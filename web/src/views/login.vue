<script setup>
import { ref, computed, onMounted } from "vue";
import logo from "@/views/components/logo.vue";
import lightDark from "./components/lightDark.vue";
import locale from "./components/locale.vue";
import { login, resetPwd } from "@/api/user";
import { useI18n } from "vue-i18n";
import { User, Lock, Key } from "@element-plus/icons-vue";
import Motion from "@/utils/motion";
import { useAppStore } from "@/store/useAppStore";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import Cookies from "js-cookie";

const { t } = useI18n();
const appStore = useAppStore();
const router = useRouter();

const params = ref({
  userName: "",
  passwd: "",
});
const loginFormRef = ref();
const loading = ref(false);

const rules = computed(() => ({
  userName: [
    {
      required: true,
      message: t("login.userNameRule"),
      trigger: ["blur", "change"],
    },
  ],
  passwd: [
    {
      required: true,
      message: t("login.passwdRule"),
      trigger: ["blur", "change"],
    },
  ],
}));

const doLogin = () => {
  loginFormRef.value.validate((valid) => {
    if (!valid) return;
    Cookies.remove(appStore.cookieName);
    loading.value = true;
    login(params.value)
      .then((res) => {
        appStore.set("user", res.data);
        router.replace("/home");
      })
      .finally(() => {
        loading.value = false;
      });
  });
};

const resetShow = ref(false);
const resetFormRef = ref();
const resetForm = ref({
  userName: "",
  key: "",
  passwd: "",
  passwd2: "",
});

const validatePass2 = (rule, value, callback) => {
  if (value == "" || value == null) {
    callback(new Error(t("login.newPasswd2Rule")));
  } else if (value !== resetForm.value.passwd) {
    callback(new Error(t("login.newPasswd2Error")));
  } else {
    callback();
  }
};

const resetRules = computed(() => ({
  userName: [
    {
      required: true,
      message: t("login.userNameRule"),
      trigger: ["blur", "change"],
    },
  ],
  key: [
    {
      required: true,
      message: t("login.keyRule"),
      trigger: ["blur", "change"],
    },
  ],
  passwd: [
    {
      required: true,
      message: t("login.newPasswd"),
      trigger: ["blur", "change"],
    },
  ],
  passwd2: [
    {
      validator: validatePass2,
      trigger: ["blur", "change"],
    },
  ],
}));

const showReset = () => {
  resetShow.value = true;
};

const closeReset = () => {
  resetFormRef.value?.clearValidate();
  resetForm.value = {
    userName: "",
    key: "",
    passwd: "",
    passwd2: "",
  };
  resetShow.value = false;
};

const submitReset = () => {
  resetFormRef.value.validate((valid) => {
    if (!valid) return;
    loading.value = true;
    resetPwd(resetForm.value)
      .then(() => {
        closeReset();
        ElMessage({
          message: t("login.resetSuccess"),
          type: "success",
        });
      })
      .finally(() => {
        loading.value = false;
      });
  });
};

onMounted(() => {
  appStore.set("user", null);
});
</script>

<template>
  <div class="login">
    <div class="login-box">
      <div class="login-header">
        <Motion>
          <locale class="locale" />
        </Motion>
        <Motion>
          <lightDark />
        </Motion>
      </div>
      <Motion :delay="100">
        <logo class="logo" />
      </Motion>
      <Motion :delay="130">
        <div class="login-title">{{ $t("login.title") }}</div>
      </Motion>
      <el-form ref="loginFormRef" :model="params" :rules="rules" label-width="0">
        <Motion :delay="150">
          <el-form-item prop="userName">
            <el-input :prefix-icon="User" v-model="params.userName" :placeholder="$t('login.userName')" />
          </el-form-item>
        </Motion>
        <Motion :delay="200">
          <el-form-item prop="passwd">
            <el-input
              :prefix-icon="Lock"
              type="password"
              show-password
              v-model="params.passwd"
              :placeholder="$t('login.passwd')"
              @keyup.enter="doLogin"
            />
          </el-form-item>
        </Motion>
        <Motion :delay="230">
          <div class="forgot" @click="showReset">{{ $t("login.forgot") }}</div>
        </Motion>
        <Motion :delay="260">
          <el-form-item>
            <el-button :loading="loading" @click="doLogin" type="primary">
              {{ $t("login.loginBtn") }}
            </el-button>
          </el-form-item>
        </Motion>
      </el-form>
    </div>

    <el-dialog width="560px" :append-to-body="true" v-model="resetShow" :title="$t('login.resetTitle')">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="110px">
        <el-form-item prop="userName" :label="$t('login.userNameLabel')">
          <el-input :prefix-icon="User" v-model="resetForm.userName" :placeholder="$t('login.userName')" />
        </el-form-item>
        <el-form-item prop="key" :label="$t('login.key')">
          <el-input :prefix-icon="Key" v-model="resetForm.key" :placeholder="$t('login.keyPlaceholder')" />
        </el-form-item>
        <el-form-item prop="passwd" :label="$t('user.newPasswdLabel')">
          <el-input type="password" show-password v-model="resetForm.passwd" :placeholder="$t('login.newPasswd')" />
        </el-form-item>
        <el-form-item prop="passwd2" :label="$t('user.newPasswd2Label')">
          <el-input type="password" show-password v-model="resetForm.passwd2" :placeholder="$t('login.newPasswd2')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeReset">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submitReset" :loading="loading">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.login {
  position: fixed;
  inset: 0;
  padding: 16px;
  display: flex;
  align-items: center;
  background: url("@/assets/img/login-bg.jpg") no-repeat center;
  background-size: cover;

  .login-box {
    position: relative;
    box-sizing: border-box;
    width: 520px;
    margin-left: 8%;
    background-color: var(--app-login-background-color);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    align-items: center;
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.28);

    .login-header {
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      box-sizing: border-box;
      padding: 28px 30px 12px;

      .locale {
        margin-right: 16px;
      }
    }

    .logo {
      margin: 18px 40px 10px;
    }

    .login-title {
      margin: 28px 0 8px;
      font-size: 22px;
      font-weight: 700;
      color: var(--text-primary);
    }

    .forgot {
      width: 400px;
      margin: -12px 37px 0;
      text-align: right;
      color: var(--active-color);
      cursor: pointer;
    }

    :deep(.el-input) {
      font-size: 18px;

      .el-input__inner {
        height: 42px;
        font-size: 18px;
      }
    }

    :deep(.el-form-item) {
      margin: 28px 37px;

      .el-form-item__error {
        font-size: 14px;
      }
    }

    :deep(.el-button) {
      margin: 16px 0 28px;
      font-size: 18px;
      padding: 20px;
      width: 400px;
    }
  }
}

@media (max-width: 768px) {
  .login {
    justify-content: center;
    padding: 12px;

    .login-box {
      width: 100%;
      max-width: 520px;
      margin-left: 0;

      .login-header {
        padding: 18px 20px 8px;
      }

      .logo {
        margin: 10px 20px 6px;
      }

      .login-title {
        margin: 20px 0 4px;
        font-size: 20px;
      }

      .forgot {
        width: auto;
        margin: -8px 20px 0;
      }

      :deep(.el-form) {
        width: 100%;
      }

      :deep(.el-form-item) {
        margin: 22px 20px;
      }

      :deep(.el-button) {
        width: 100%;
        margin: 10px 0 22px;
      }
    }
  }
}
</style>
