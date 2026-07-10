import { createI18n } from "vue-i18n";
import { LANGS } from "./langs";

const messages = Object.fromEntries(Object.entries(LANGS).map(([key, val]) => [key, val.value]));
const sysLang = navigator.language;
const defaultLang = "zh-CN";
let autoLang = defaultLang;
if (Object.hasOwn(messages, sysLang)) {
  autoLang = sysLang;
} else if (Object.hasOwn(messages, sysLang.split("_")[0])) {
  autoLang = sysLang.split("_")[0];
}
let locale = localStorage.getItem("lang");
if (!locale) {
  locale = autoLang;
  localStorage.setItem("lang", locale);
}
const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale,
  fallbackLocale: defaultLang,
  messages,
});

export default i18n;
