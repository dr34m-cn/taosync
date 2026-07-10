import i18n from "@/utils/i18n";

export const taskStatusKeys = [
  "taskStatus.waiting",
  "taskStatus.syncing",
  "taskStatus.success",
  "taskStatus.finished",
  "taskStatus.aborted",
  "taskStatus.timeout",
  "taskStatus.createFailed",
  "taskStatus.manualAbort",
];

export default function taskStatus(value) {
  const key = taskStatusKeys[value];
  return key ? i18n.global.t(key) : "--";
}
