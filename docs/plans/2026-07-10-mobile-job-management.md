# Mobile Job Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Load a dedicated mobile job-management page at phone widths while keeping the current desktop job-management page unchanged.

**Architecture:** Convert the route component into a breakpoint dispatcher. Move the current implementation to `desktop.vue`, and create `mobile.vue` with its own API state, card list, pagination, full-screen editor, path selection, and job actions. Only one page component is mounted, so desktop and mobile do not duplicate requests.

**Tech Stack:** Vue 3, Element Plus, VueUse `useMediaQuery`, Vue Router, SCSS

---

### Task 1: Split the Route Component

**Files:**
- Move: `web/src/views/pages/home/index.vue` to `web/src/views/pages/home/desktop.vue`
- Create: `web/src/views/pages/home/index.vue`

**Step 1:** Keep the current desktop file content unchanged during the move.

**Step 2:** Create a small route component that renders `mobile.vue` at `max-width: 768px` and `desktop.vue` otherwise.

### Task 2: Implement the Mobile Job List

**Files:**
- Create: `web/src/views/pages/home/mobile.vue`

**Step 1:** Fetch the same paginated `/job` data used by desktop.

**Step 2:** Render jobs as readable cards containing status, sync method, trigger type, source path, and target paths.

**Step 3:** Provide new job, run all, refresh, manual run, task details, edit, enable/disable, and delete actions.

### Task 3: Implement the Mobile Job Editor

**Files:**
- Modify: `web/src/views/pages/home/mobile.vue`

**Step 1:** Use a full-screen mobile drawer with top-aligned labels and sectioned form content.

**Step 2:** Support engine selection, source/target directory selection, sync method, cache settings, scan intervals, excludes, interval/cron/manual triggers, and enable state.

**Step 3:** Reuse the existing path selector and submit the same payload shape as the desktop implementation.

### Task 4: Add Mobile Copy

**Files:**
- Modify: `web/src/locales/zh-CN.yaml`
- Modify: `web/src/locales/en.yaml`

**Step 1:** Add concise section labels and mobile empty-state copy without changing existing desktop translations.

### Task 5: Verification Handoff

**Files:**
- No code changes.

**Step 1:** Do not run local build, lint, browser, or screenshot verification because the user requested to verify changes themselves.
