<script setup>
import { ref, watch } from "vue";
import { CircleClose } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";
import {
  bytesFromFileSize,
  FILE_SIZE_UNITS,
  fileSizeInputFromBytes,
  fileSizeMultiplier,
  MAX_FILE_SIZE,
} from "@/utils/fileSizeFilter";

const props = defineProps({
  minFileSize: {
    type: Number,
    default: null,
  },
  maxFileSize: {
    type: Number,
    default: null,
  },
});

const emit = defineEmits(["update:minFileSize", "update:maxFileSize"]);
const { t } = useI18n();

const minValue = ref(null);
const minUnit = ref("MB");
const maxValue = ref(null);
const maxUnit = ref("MB");

const inputMaximum = (unit) => Math.floor(MAX_FILE_SIZE / fileSizeMultiplier(unit));

const hydrateBoundary = (bytes, valueRef, unitRef) => {
  const input = fileSizeInputFromBytes(bytes);
  valueRef.value = input.value;
  unitRef.value = input.unit;
};

watch(
  () => props.minFileSize,
  (bytes) => {
    if (bytesFromFileSize(minValue.value, minUnit.value) !== bytes) {
      hydrateBoundary(bytes, minValue, minUnit);
    }
  },
  { immediate: true },
);

watch(
  () => props.maxFileSize,
  (bytes) => {
    if (bytesFromFileSize(maxValue.value, maxUnit.value) !== bytes) {
      hydrateBoundary(bytes, maxValue, maxUnit);
    }
  },
  { immediate: true },
);

const updateMin = () => emit("update:minFileSize", bytesFromFileSize(minValue.value, minUnit.value));
const updateMax = () => emit("update:maxFileSize", bytesFromFileSize(maxValue.value, maxUnit.value));

const clearMin = () => {
  minValue.value = null;
  emit("update:minFileSize", null);
};

const clearMax = () => {
  maxValue.value = null;
  emit("update:maxFileSize", null);
};
</script>

<template>
  <div class="file-size-filter">
    <div class="size-boundaries">
      <div class="size-boundary">
        <label class="boundary-label" for="min-file-size">{{ t("home.excludeBelow") }}</label>
        <div class="boundary-controls">
          <el-input-number
            id="min-file-size"
            v-model="minValue"
            :controls="false"
            :min="0"
            :max="inputMaximum(minUnit)"
            :placeholder="t('home.noLimit')"
            @change="updateMin"
          />
          <el-select v-model="minUnit" :aria-label="t('home.fileSizeUnit')" @change="updateMin">
            <el-option v-for="unit in FILE_SIZE_UNITS" :key="unit.value" :label="unit.value" :value="unit.value" />
          </el-select>
          <el-tooltip :content="t('home.clearSizeBoundary')">
            <el-button :icon="CircleClose" text circle :disabled="minValue === null" @click="clearMin" />
          </el-tooltip>
        </div>
      </div>

      <div class="size-boundary">
        <label class="boundary-label" for="max-file-size">{{ t("home.excludeAbove") }}</label>
        <div class="boundary-controls">
          <el-input-number
            id="max-file-size"
            v-model="maxValue"
            :controls="false"
            :min="0"
            :max="inputMaximum(maxUnit)"
            :placeholder="t('home.noLimit')"
            @change="updateMax"
          />
          <el-select v-model="maxUnit" :aria-label="t('home.fileSizeUnit')" @change="updateMax">
            <el-option v-for="unit in FILE_SIZE_UNITS" :key="unit.value" :label="unit.value" :value="unit.value" />
          </el-select>
          <el-tooltip :content="t('home.clearSizeBoundary')">
            <el-button :icon="CircleClose" text circle :disabled="maxValue === null" @click="clearMax" />
          </el-tooltip>
        </div>
      </div>
    </div>
    <div class="size-filter-tip">{{ t("home.fileSizeFilterTip") }}</div>
  </div>
</template>

<style scoped>
.file-size-filter {
  width: 100%;
  min-width: 0;
}

.size-boundaries {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.size-boundary {
  min-width: 0;
}

.boundary-label {
  display: block;
  margin-bottom: 6px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 20px;
}

.boundary-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 78px 32px;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.boundary-controls :deep(.el-input-number),
.boundary-controls :deep(.el-select) {
  width: 100%;
}

.boundary-controls :deep(.el-button) {
  width: 32px;
  height: 32px;
}

.size-filter-tip {
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 720px) {
  .size-boundaries {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }
}
</style>
