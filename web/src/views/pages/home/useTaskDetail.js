import { ref } from "vue";
import { useRoute } from "vue-router";
import { jobGetTaskItem } from "@/api/job";

export function useTaskDetail() {
  const { taskId } = useRoute().query;
  const params = ref({ taskId: Array.isArray(taskId) ? taskId[0] : taskId, pageSize: 10, pageNum: 1,
    status: null, type: null, rapidUpload: "all" });
  const taskItemData = ref({ dataList: [], count: 0 });
  const loading = ref(false);
  let latestRequest = 0;

  const getTaskItemList = async () => {
    const query = { ...params.value };
    if (query.taskId == null) return;
    if (query.status == null || query.status === "") delete query.status;
    if (query.type == null || query.type === "") delete query.type;
    if (query.rapidUpload !== 1) delete query.rapidUpload;
    const request = ++latestRequest;
    loading.value = true;
    try {
      const { data } = await jobGetTaskItem(query);
      if (request !== latestRequest) return;
      data.dataList.forEach((item) => { item.progress = Math.min(parseInt(item.progress || 0), 100); });
      taskItemData.value = data;
    } finally {
      if (request === latestRequest) loading.value = false;
    }
  };
  const filterChange = () => {
    params.value.pageNum = 1;
    return getTaskItemList();
  };
  return { params, taskItemData, loading, getTaskItemList, filterChange };
}
