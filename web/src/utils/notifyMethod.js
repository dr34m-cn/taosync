import i18n from "@/utils/i18n";

export const notifyMethodKeys = [
  "notify.methods.custom",
  "notify.methods.serverChan",
  "notify.methods.dingTalk",
  "notify.methods.weCom",
  "notify.methods.lark",
];

export default function notifyMethod(value) {
  const key = notifyMethodKeys[value];
  return key ? i18n.global.t(key) : "--";
}
