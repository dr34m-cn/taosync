import { createRouter, createWebHashHistory } from "vue-router";
import layout from "@/views/layout.vue";
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      component: () => import("@/views/index.vue"),
    },
    {
      path: "/login",
      component: () => import("@/views/login.vue"),
    },
    {
      path: "/home",
      component: layout,
      children: [
        {
          path: "",
          component: () => import("@/views/pages/home/index.vue"),
          meta: {
            leftIndex: "/home",
          },
        },
        {
          path: "task",
          component: () => import("@/views/pages/home/task.vue"),
          meta: {
            leftIndex: "/home",
          },
        },
        {
          path: "task/detail",
          component: () => import("@/views/pages/home/taskDetail.vue"),
          meta: {
            leftIndex: "/home",
          },
        },
      ],
    },
    {
      path: "/engine",
      component: layout,
      children: [
        {
          path: "",
          component: () => import("@/views/pages/engine/index.vue"),
          meta: {
            leftIndex: "/engine",
          },
        },
      ],
    },
    {
      path: "/notify",
      component: layout,
      children: [
        {
          path: "",
          component: () => import("@/views/pages/notify/index.vue"),
          meta: {
            leftIndex: "/notify",
          },
        },
      ],
    },
    {
      path: "/setting",
      component: layout,
      children: [
        {
          path: "",
          component: () => import("@/views/pages/setting/index.vue"),
          meta: {
            leftIndex: "/setting",
          },
        },
      ],
    },
  ],
});

export default router;
