<script setup>
import { ref, computed } from "vue";
import { logout, editPwd } from "@/api/user";
import { useAppStore } from "@/store/useAppStore";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";

const appStore = useAppStore();
const router = useRouter();
const { t } = useI18n();

const doLogout = () => {
  logout().finally(() => {
    appStore.set("user", null);
    router.replace("/login");
  });
};

const form = ref({
  oldPasswd: "",
  passwd: "",
  passwd2: "",
});
const formRef = ref();
const loading = ref(false);
const dialogShow = ref(false);

const validatePass2 = (rule, value, callback) => {
  if (value == "" || value == null) {
    callback(new Error(t("user.newPasswd2Rule")));
  } else if (value !== form.value.passwd) {
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
      trigger: ["blur", "change"],
    },
  ],
  passwd: [
    {
      required: true,
      message: t("user.newPasswdRule"),
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

const showPut = () => {
  form.value = {
    oldPasswd: "",
    passwd: "",
    passwd2: "",
  };
  dialogShow.value = true;
};

const closePut = () => {
  formRef.value?.clearValidate();
  dialogShow.value = false;
};

const submit = () => {
  formRef.value.validate((valid) => {
    if (!valid) return;
    loading.value = true;
    editPwd({
      oldPasswd: form.value.oldPasswd,
      passwd: form.value.passwd,
    })
      .then((res) => {
        ElMessage({
          message: res.msg || t("user.success"),
          type: "success",
        });
        closePut();
      })
      .finally(() => {
        loading.value = false;
      });
  });
};
</script>

<template>
  <div class="header-user-box">
    <el-dropdown v-if="$store.user" trigger="click">
      <div class="header-user">
        <el-icon>
          <Avatar />
        </el-icon>
        <span class="username">{{ $store.user.userName }}</span>
        <el-icon>
          <ArrowDown />
        </el-icon>
      </div>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item @click="showPut">{{ $t("header.setPwd") }}</el-dropdown-item>
          <el-dropdown-item @click="doLogout">{{ $t("header.logout") }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <el-dialog width="520px" :append-to-body="true" v-model="dialogShow" :title="$t('header.setPwd')">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px">
        <el-form-item prop="oldPasswd" :label="$t('user.oldPasswdLabel')">
          <el-input type="password" show-password v-model="form.oldPasswd" :placeholder="$t('user.oldPasswd')" />
        </el-form-item>
        <el-form-item prop="passwd" :label="$t('user.newPasswdLabel')">
          <el-input type="password" show-password v-model="form.passwd" :placeholder="$t('user.newPasswd')" />
        </el-form-item>
        <el-form-item prop="passwd2" :label="$t('user.newPasswd2Label')">
          <el-input type="password" show-password v-model="form.passwd2" :placeholder="$t('user.newPasswd2')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closePut">{{ $t("common.cancel") }}</el-button>
        <el-button :loading="loading" type="primary" @click="submit">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.header-user-box {
  display: flex;
  align-items: center;

  .header-user {
    display: flex;
    align-items: center;
    cursor: pointer;

    .username {
      margin: 0 4px;
      max-width: 160px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
}

@media (max-width: 768px) {
  .header-user-box {
    .header-user {
      .username {
        display: none;
      }
    }
  }
}
</style>
