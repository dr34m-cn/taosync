<script setup>
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Back, Clock, Delete, Link, Plus, Refresh } from '@element-plus/icons-vue';
import { addJobLink, deleteJobLinkData, getJobLinks } from '@/api/job';
import { parseTime } from '@/utils/utils';

defineProps({ size: String });
const { t } = useI18n();
const visible = ref(false), busy = ref(false), view = ref('list');
const rules = ref([]), jobs = ref([]), active = ref(null);
const page = ref(1), logs = ref({ rows: [], count: 0 });
const defaults = () => ({ source: null, targets: [], condition: 'finished', delayed: false, minutes: 5 });
const form = ref(defaults());
const names = computed(() => new Map(jobs.value.map(j => [j.id, j.remark])));
const label = id => [names.value.get(id), `#${id}`].filter(Boolean).join(' ');
const condition = value => value === 'success' ? t('jobLinks.success') : t('jobLinks.finished');
const results = { executed: 'success', skipped: 'warning', failed: 'danger' };
const valid = computed(() => form.value.source && form.value.targets.length && (!form.value.delayed ||
  (Number.isInteger(form.value.minutes) && form.value.minutes > 0 && form.value.minutes <= 2147483647)));

async function run(action) {
  if (busy.value) return;
  busy.value = true;
  try { await action(); } catch { /* request interceptor displays the error */ }
  finally { busy.value = false; }
}
async function loadRules() {
  const { data } = await getJobLinks();
  rules.value = data.rules;
  jobs.value = data.jobs;
}
function open() {
  view.value = 'list';
  visible.value = true;
  run(loadRules);
}
function newRule() {
  form.value = defaults();
  view.value = 'add';
}
function save() {
  if (!valid.value) return;
  run(async () => {
    const { source, targets, condition, delayed, minutes } = form.value;
    await addJobLink({ source, targets, condition, minutes: delayed ? minutes : 0 });
    view.value = 'list';
    ElMessage.success(t('jobLinks.added'));
    await loadRules();
  });
}
async function loadLogs(n = 1) {
  const { data } = await getJobLinks({ id: active.value.id, page: n });
  page.value = n;
  logs.value = data;
}
function showLogs(rule) {
  active.value = rule;
  logs.value = { rows: [], count: 0 };
  view.value = 'logs';
  run(() => loadLogs());
}
async function discard(action, id) {
  const message = { remove: t('jobLinks.confirmRemove'), clearLogs: t('jobLinks.confirmClear'),
    clearAllLogs: t('jobLinks.confirmClearAll') }[action];
  try { await ElMessageBox.confirm(message, t('jobLinks.confirmTitle'), { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') }); }
  catch { return; }
  run(async () => {
    await deleteJobLinkData({ action, id });
    ElMessage.success(action === 'remove' ? t('jobLinks.removed') : t('jobLinks.cleared'));
    if (view.value === 'logs') await loadLogs();
    else await loadRules();
  });
}
</script>

<template>
  <el-button type="primary" :size="size" :icon="Link" @click="open">{{ t('jobLinks.title') }}</el-button>
  <el-dialog v-model="visible" append-to-body :width="view === 'add' ? 'min(700px, 94vw)' : 'min(960px, 94vw)'" top="6vh"
    :title="{ list: t('jobLinks.title'), add: t('jobLinks.add'), logs: t('jobLinks.logs') }[view]">
    <div v-loading="busy" class="link-content" :aria-busy="busy">
      <template v-if="view === 'list'">
        <div class="toolbar">
          <el-button type="primary" :icon="Plus" @click="newRule">{{ t('jobLinks.add') }}</el-button>
          <el-button type="warning" :icon="Delete" :disabled="!rules.length" @click="discard('clearAllLogs')">{{ t('jobLinks.clearAll') }}</el-button>
        </div>
        <el-table :data="rules" row-key="id" stripe :empty-text="t('jobLinks.empty')" max-height="56vh">
          <el-table-column :label="t('jobLinks.source')" min-width="145"><template #default="{ row }">{{ label(row.source) }}</template></el-table-column>
          <el-table-column :label="t('jobLinks.condition')" width="130"><template #default="{ row }">{{ condition(row.condition) }}</template></el-table-column>
          <el-table-column :label="t('jobLinks.timing')" min-width="145"><template #default="{ row }">{{ row.minutes ? t('jobLinks.afterMinutes', { minutes: row.minutes }) : t('jobLinks.immediate') }}</template></el-table-column>
          <el-table-column :label="t('jobLinks.targets')" min-width="155"><template #default="{ row }">
            <div class="targets"><el-tag v-for="id in row.targets" :key="id" effect="plain">{{ label(id) }}</el-tag></div>
          </template></el-table-column>
          <el-table-column :label="t('common.operate')" width="190"><template #default="{ row }">
            <div class="tools"><el-button link type="primary" :icon="Clock" @click="showLogs(row)">{{ t('jobLinks.logs') }}</el-button>
              <el-button link type="danger" :icon="Delete" @click="discard('remove', row.id)">{{ t('jobLinks.remove') }}</el-button></div>
          </template></el-table-column>
        </el-table>
      </template>
      <el-form v-else-if="view === 'add'" label-position="top" @submit.prevent="save">
        <el-form-item :label="t('jobLinks.source')"><el-select v-model="form.source" filterable :placeholder="t('jobLinks.selectSource')"
          @change="id => form.targets = form.targets.filter(t => t !== id)">
          <el-option v-for="j in jobs" :key="j.id" :label="label(j.id)" :value="j.id" />
        </el-select></el-form-item>
        <el-form-item :label="t('jobLinks.condition')"><el-radio-group v-model="form.condition">
          <el-radio-button value="finished">{{ t('jobLinks.finished') }}</el-radio-button><el-radio-button value="success">{{ t('jobLinks.success') }}</el-radio-button>
        </el-radio-group></el-form-item>
        <el-form-item :label="t('jobLinks.timing')"><el-radio-group v-model="form.delayed">
          <el-radio :value="false">{{ t('jobLinks.onCompletion') }}</el-radio><el-radio :value="true">{{ t('jobLinks.wait') }}</el-radio>
        </el-radio-group>
          <div v-if="form.delayed" class="minutes"><el-input-number v-model="form.minutes" :aria-label="t('jobLinks.delayMinutes')" :min="1" :max="2147483647" :precision="0" :controls="false" /> {{ t('jobLinks.minutesUnit') }}</div>
        </el-form-item>
        <el-form-item :label="t('jobLinks.targets')"><el-select v-model="form.targets" multiple filterable :placeholder="t('jobLinks.selectTargets')">
          <el-option v-for="j in jobs" :key="j.id" :label="label(j.id)" :value="j.id" :disabled="j.id === form.source" />
        </el-select></el-form-item>
      </el-form>
      <template v-else>
        <strong>{{ label(active.source) }} · {{ condition(active.condition) }}</strong>
        <div class="toolbar log-tools"><el-button :icon="Refresh" @click="run(() => loadLogs())">{{ t('jobLinks.refresh') }}</el-button>
          <el-button type="warning" :icon="Delete" :disabled="!logs.count" @click="discard('clearLogs', active.id)">{{ t('jobLinks.clear') }}</el-button></div>
        <el-table :data="logs.rows" row-key="id" stripe :empty-text="t('jobLinks.emptyLog')" max-height="50vh">
          <el-table-column :label="t('jobLinks.dispatchedAt')" width="180"><template #default="{ row }">{{ parseTime(row.runTime) }}</template></el-table-column>
          <el-table-column :label="t('jobLinks.target')" min-width="145"><template #default="{ row }">{{ label(row.target) }}</template></el-table-column>
          <el-table-column :label="t('jobLinks.result')" width="185"><template #default="{ row }">
            <el-tag class="result-tag" :type="results[row.result]">{{ t(`jobLinks.${row.result}`) }}</el-tag>
          </template></el-table-column>
          <el-table-column :label="t('home.detail')" min-width="160"><template #default="{ row }">{{ row.detail || '—' }}</template></el-table-column>
        </el-table>
        <el-pagination v-if="logs.count > 20" small layout="prev, pager, next" :pager-count="5" :total="logs.count" :page-size="20"
          :current-page="page" @current-change="n => run(() => loadLogs(n))" />
      </template>
    </div>
    <template #footer>
      <el-button v-if="view !== 'list'" :disabled="busy" :icon="Back" @click="view = 'list'">{{ t('jobLinks.back') }}</el-button>
      <el-button v-if="view === 'add'" type="primary" :disabled="!valid" :loading="busy" @click="save">{{ t('jobLinks.save') }}</el-button>
      <el-button v-if="view === 'list'" @click="visible = false">{{ t('jobLinks.close') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.link-content { max-height: 66vh; overflow-y: auto; overflow-wrap: anywhere; }
.toolbar, .targets, .tools, .minutes { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.toolbar { margin-bottom: 12px; }
.toolbar .el-button, .tools .el-button { margin-left: 0; }
.targets .el-tag { max-width: 100%; height: auto; white-space: normal; }
.result-tag { height: auto; max-width: 100%; white-space: normal; }
.log-tools { margin-top: 12px; }
.minutes { margin-left: 8px; }
.minutes .el-input-number { width: 92px; }
.minutes :deep(input[type='number']) { appearance: textfield; }
.minutes :deep(input::-webkit-inner-spin-button), .minutes :deep(input::-webkit-outer-spin-button) { -webkit-appearance: none; margin: 0; }
.el-pagination { margin-top: 12px; }
</style>
