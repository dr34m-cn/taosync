import { onBeforeUnmount, ref } from "vue";
import { useRoute } from "vue-router";
import { jobGetTaskItem, jobPut } from "@/api/job";

export function useTaskDetail() {
  const { taskId } = useRoute().query;
  const params = ref({ taskId: Array.isArray(taskId) ? taskId[0] : taskId, pageSize: 10, pageNum: 1,
    status: null, type: null, rapidUpload: "all" });
  const taskItemData = ref({ dataList: [], count: 0 });
  const loading = ref(false);
  let latestRequest = 0;
  let pollTimer;
  let disposed = false;
  const submitting = ref(new Set());

  const getTaskItemList = async (background = false) => {
    if (disposed) return;
    clearTimeout(pollTimer);
    const query = { ...params.value };
    if (query.taskId == null) return;
    if (query.status == null || query.status === "") delete query.status;
    if (query.type == null || query.type === "") delete query.type;
    if (query.rapidUpload !== 1) delete query.rapidUpload;
    const request = ++latestRequest;
    loading.value = !background;
    try {
      const { data } = await jobGetTaskItem(query);
      if (request !== latestRequest) return;
      data.dataList.forEach((item) => { item.progress = Math.min(parseInt(item.progress || 0), 100); });
      taskItemData.value = data;
    } finally {
      if (request === latestRequest) {
        loading.value = false;
        if (taskItemData.value.dataList.some(row => row.retry && row.retry.status < 2)) {
          pollTimer = setTimeout(() => getTaskItemList(true).catch(() => {}), 1200);
        }
      }
    }
  };
  const filterChange = () => {
    params.value.pageNum = 1;
    return getTaskItemList();
  };
  const retryFile = async (row) => {
    if (submitting.value.has(row.id)) return;
    submitting.value.add(row.id);
    try {
      const { data } = await jobPut({ action: 'retryFile', taskId: params.value.taskId, itemId: row.id });
      row.retry = { id: data.id, status: 0, queued: true };
    } finally {
      try {
        await getTaskItemList(true);
      } finally {
        submitting.value.delete(row.id);
      }
    }
  };
  onBeforeUnmount(() => {
    disposed = true;
    ++latestRequest;
    clearTimeout(pollTimer);
  });
  return { params, taskItemData, loading, getTaskItemList, filterChange, submitting, retryFile };
}
