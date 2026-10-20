# Vue 3 Functional Parity Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore functional behaviors present in the Vue 2 frontend but missing or weakened in the Vue 3 frontend.

**Architecture:** Keep all current Vue 3 page structures and mobile routes. Apply narrowly scoped fixes to the request lifecycle, authenticated layout, login flow, path selector, and current-task polling so the migrated frontend preserves the old runtime behavior without reintroducing unused legacy helpers.

**Tech Stack:** Vue 3, Pinia, Axios, Element Plus, js-cookie, vue-i18n

---

### Task 1: Restore Global Request Loading Mask

**Files:**
- Modify: `web/src/views/layout.vue`

**Step 1:** Read the Pinia app store in the layout.

**Step 2:** Bind `appStore.loading` to the authenticated content container with Element Plus `v-loading`.

### Task 2: Restore Session Handling Parity

**Files:**
- Modify: `web/src/views/login.vue`
- Modify: `web/src/utils/request.js`
- Modify: `web/src/locales/zh-CN.yaml`
- Modify: `web/src/locales/en.yaml`

**Step 1:** Remove the stale TaoSync cookie before submitting a login request.

**Step 2:** Restore the single-instance expired-session confirmation on authenticated routes.

**Step 3:** On confirmation, clear the cookie and route to login; on cancellation, keep the current page.

### Task 3: Restore Path Dialog Layering

**Files:**
- Modify: `web/src/views/pages/home/components/pathSelect.vue`

**Step 1:** Restore `append-to-body` so the directory dialog appears above nested dialogs and mobile drawers.

### Task 4: Restore Current-Task Error Backoff

**Files:**
- Modify: `web/src/views/pages/home/components/taskCurrent.vue`

**Step 1:** Release `loadingTask` immediately on success.

**Step 2:** Keep it locked for the legacy retry delay after failures instead of clearing it in `finally`.

### Task 5: Switch the Release Pipeline to Vue 3

**Files:**
- Modify: `.github/workflows/build.yml`
- Modify: `taoSync.spec`
- Modify: `README.md`

**Step 1:** Build `web` with Node 22 and the checked-in pnpm lockfile.

**Step 2:** Replace version placeholders in both locale files before building.

**Step 3:** Upload and download `web/dist` for Docker, Windows, and macOS packaging.

**Step 4:** Package `web/dist` into the existing runtime `front` directory and update the repository logo path.

### Task 6: Verification Handoff

**Files:**
- No code changes.

**Step 1:** Do not run local build, lint, browser, or screenshot verification because the user requested to verify changes themselves.
