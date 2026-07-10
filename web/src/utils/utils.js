// 日期格式化
export function parseTime(time, pattern) {
  if (arguments.length === 0 || !time) {
    return null;
  }
  const format = pattern || "{y}-{m}-{d} {h}:{i}:{s}";
  let date;
  if (typeof time === "object") {
    date = time;
  } else {
    if (typeof time === "string" && /^[0-9]+$/.test(time)) {
      time = parseInt(time);
    } else if (typeof time === "string") {
      if (time.length >= 24) {
        if (time.indexOf("Z") != -1) {
          time = time
            .replace(new RegExp(/-/gm), "/")
            .replace("T", " ")
            .replace(new RegExp(/\.[\d]{9}/gm), "")
            .replace("Z", "");
          time = new Date(time).valueOf() + 28800000;
        } else {
          time = time
            .replace(new RegExp(/-/gm), "/")
            .replace("T", " ")
            .replace(new RegExp(/\.[\d]{9}/gm), "")
            .replace("+08:00", "");
        }
      } else {
        time = time
          .replace(new RegExp(/-/gm), "/")
          .replace("T", " ")
          .replace(new RegExp(/\.[\d]{3}/gm), "");
      }
    }
    if (typeof time === "number" && time.toString().length === 10) {
      time = time * 1000;
    }
    date = new Date(time);
  }
  const formatObj = {
    y: date.getFullYear(),
    m: date.getMonth() + 1,
    d: date.getDate(),
    h: date.getHours(),
    i: date.getMinutes(),
    s: date.getSeconds(),
    a: date.getDay(),
  };
  const time_str = format.replace(/{(y|m|d|h|i|s|a)+}/g, (result, key) => {
    let value = formatObj[key];
    // Note: getDay() returns 0 on Sunday
    if (key === "a") {
      return ["日", "一", "二", "三", "四", "五", "六"][value];
    }
    if (result.length > 0 && value < 10) {
      value = "0" + value;
    }
    return value || 0;
  });
  return time_str;
}

// 大小换算
export function parseSize(val) {
  if (val === null || val === undefined || Number.isNaN(Number(val))) {
    return "--";
  }
  const unitList = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  for (i = 0; i < unitList.length; i++) {
    if (val < 1024 ** (i + 1)) {
      return (val / (1024 ** i)).toFixed(2).replace(/\.?0*$/, "") + " " + unitList[i];
    }
  }
  return (val / (1024 ** (i - 1))).toFixed(2).replace(/\.?0*$/, "") + " " + unitList[i - 1];
}

export function download(res, fileName) {
  const blob = new Blob([res.data], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = window.URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();

  window.URL.revokeObjectURL(url);
}

/**
 * 参数处理，保留旧前端工具函数给需要手动拼接 query 的地方使用。
 * @param {*} params 参数
 */
export function tansParams(params) {
  let result = "";
  for (const propName of Object.keys(params)) {
    const value = params[propName];
    const part = encodeURIComponent(propName) + "=";
    if (value !== null && value !== "" && typeof value !== "undefined") {
      if (typeof value === "object") {
        for (const key of Object.keys(value)) {
          if (value[key] !== null && value[key] !== "" && typeof value[key] !== "undefined") {
            const subParams = propName + "[" + key + "]";
            const subPart = encodeURIComponent(subParams) + "=";
            result += subPart + encodeURIComponent(value[key]) + "&";
          }
        }
      } else {
        result += part + encodeURIComponent(value) + "&";
      }
    }
  }
  return result;
}

// 值与时间范围列表
export const timeList = [
  {
    label: "近7天",
    value: 0,
  },
  {
    label: "本周",
    value: 1,
  },
  {
    label: "上周",
    value: 2,
  },
  {
    label: "近31天",
    value: 3,
  },
  {
    label: "本月",
    value: 4,
  },
  {
    label: "上月",
    value: 5,
  },
  {
    label: "今年",
    value: 6,
  },
  {
    label: "去年",
    value: 7,
  },
  {
    label: "历年",
    value: 8,
  },
];

// 根据值输出时间范围
export function getRangeByVal(timeVal) {
  const now = new Date();
  let start, end;
  const setToStartOfDay = (date) =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0);
  const setToEndOfDay = (date) =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59);

  switch (timeVal) {
    // 近7天
    case 0:
      start = new Date(now);
      start.setDate(now.getDate() - 6);
      start = setToStartOfDay(start);
      end = setToEndOfDay(now);
      break;
    // 本周
    case 1: {
      const dayOfWeek = now.getDay() || 7;
      start = new Date(now);
      start.setDate(now.getDate() - dayOfWeek + 1);
      start = setToStartOfDay(start);
      end = new Date(start);
      end.setDate(start.getDate() + 6);
      end = setToEndOfDay(end);
      break;
    }
    // 上周
    case 2: {
      const day = now.getDay() || 7;
      start = new Date(now);
      start.setDate(now.getDate() - day - 6);
      start = setToStartOfDay(start);
      end = new Date(start);
      end.setDate(start.getDate() + 6);
      end = setToEndOfDay(end);
      break;
    }
    // 近31天
    case 3:
      start = new Date(now);
      start.setDate(now.getDate() - 30);
      start = setToStartOfDay(start);
      end = setToEndOfDay(now);
      break;
    // 本月
    case 4:
      start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
      end = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59);
      break;
    // 上月
    case 5:
      start = new Date(now.getFullYear(), now.getMonth() - 1, 1, 0, 0, 0);
      end = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59);
      break;
    // 今年
    case 6:
      start = new Date(now.getFullYear(), 0, 1, 0, 0, 0);
      end = new Date(now.getFullYear(), 11, 31, 23, 59, 59);
      break;
    // 去年
    case 7:
      start = new Date(now.getFullYear() - 1, 0, 1, 0, 0, 0);
      end = new Date(now.getFullYear() - 1, 11, 31, 23, 59, 59);
      break;
    // 全部
    case 8:
      start = null;
      end = null;
      break;
    default:
      return null;
  }
  return {
    startTime: start ? start.getTime() : null,
    endTime: end ? end.getTime() : null,
  };
}
