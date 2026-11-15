import i18n from "@/utils/i18n";

export const notifyMethodKeys = [
  "notify.methods.custom",
  "notify.methods.serverChan",
  "notify.methods.dingTalk",
  "notify.methods.weCom",
  "notify.methods.lark",
  "notify.methods.advancedCustom",
  "notify.methods.bark",
  "notify.methods.pushPlus",
  "notify.methods.pushDeer",
];

export default function notifyMethod(value) {
  const key = notifyMethodKeys[value];
  return key ? i18n.global.t(key) : "--";
}
