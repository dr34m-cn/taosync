import { parseTime, parseSize } from "@/utils/utils";
import taskItemStatus from "@/utils/taskItemStatus";
import taskStatus from "@/utils/taskStatus";
import notifyMethod from "@/utils/notifyMethod";

const timeStampFilter = (value) => (value ? parseTime(value) : "--");

const timeFull = (value) => {
  const val = value - 1;
  return val < 10 ? "0" + val : "" + val;
};

const taskStatusFilter = (value) => (value != null ? taskStatus(value) : "--");

const sizeFilter = (val) => (val !== null && val !== undefined ? parseSize(val) : "--");

const notifyMethodFilter = (val) => (val != null ? notifyMethod(val) : "--");

const taskItemStatusFilter = (value) => (value != null ? taskItemStatus(value) : "--");

export default {
  timeStampFilter,
  timeFull,
  taskStatusFilter,
  taskItemStatusFilter,
  sizeFilter,
  notifyMethodFilter,
};
