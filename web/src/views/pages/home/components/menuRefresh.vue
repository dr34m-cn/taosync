<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { Loading, RefreshRight } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";

const props = defineProps({
  loading: {
    type: Boolean,
    default: false,
  },
  autoRefresh: {
    type: Boolean,
    default: true,
  },
  freshInterval: {
    type: Number,
    default: 3119,
  },
  needShow: {
    type: Number,
    default: 2,
  },
  refreshText: {
    type: String,
    default: "",
  },
});
const emit = defineEmits(["getData"]);
const { t } = useI18n();
const refreshStatus = ref(true);
let timer = null;

const destroy = () => {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
};

const refreshData = () => {
  if (!props.loading) {
    emit("getData");
  }
};

const startRefresh = () => {
  destroy();
  emit("getData");
  timer = setInterval(() => {
    emit("getData");
  }, props.freshInterval);
};

const refreshChange = (val) => {
  refreshStatus.value = val;
  if (val) {
    startRefresh();
  } else {
    destroy();
  }
};

onMounted(() => {
  refreshStatus.value = props.autoRefresh;
  if (refreshStatus.value) {
    startRefresh();
  } else {
    emit("getData");
  }
});

onBeforeUnmount(() => {
  destroy();
});
</script>

<template>
  <div class="menu-refresh">
    <div class="refresh-label" v-show="needShow > 1">{{ refreshText || t("refresh.auto") }}</div>
    <el-switch v-model="refreshStatus" v-show="needShow > 1" @change="refreshChange" />
    <el-icon class="icon-btn" :class="{ spinning: loading }" @click="refreshData" v-show="needShow > 0">
      <Loading v-if="loading" />
      <RefreshRight v-else />
    </el-icon>
  </div>
</template>

<style lang="scss" scoped>
.menu-refresh {
  display: flex;
  align-items: center;

  .refresh-label {
    font-size: 15px;
    margin-right: 8px;
    color: var(--text-secondary);
  }

  .icon-btn {
    font-size: 25px;
    margin-left: 18px;
    color: var(--active-color);
    cursor: pointer;
  }

  .spinning {
    cursor: not-allowed;
    animation: rotate 1s linear infinite;
  }
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 480px) {
  .menu-refresh {
    .refresh-label {
      display: none;
    }

    .icon-btn {
      margin-left: 10px;
    }
  }
}
</style>
