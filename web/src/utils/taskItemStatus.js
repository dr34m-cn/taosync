import i18n from "@/utils/i18n";

export const taskItemStatusKeys = [
  "taskItemStatus.waiting",
  "taskItemStatus.running",
  "taskItemStatus.success",
  "taskItemStatus.canceling",
  "taskItemStatus.canceled",
  "taskItemStatus.retryError",
  "taskItemStatus.failing",
  "taskItemStatus.failed",
  "taskItemStatus.waitRetry",
  "taskItemStatus.beforeRetry",
];

export default function taskItemStatus(value) {
  const key = taskItemStatusKeys[value];
  return key ? i18n.global.t(key) : "--";
}
