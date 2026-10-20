# Mobile Task Pages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide dedicated mobile pages for job task history and task item details while preserving the current desktop pages unchanged.

**Architecture:** Turn `task.vue` and `taskDetail.vue` into breakpoint dispatchers. Move their existing implementations to desktop-only components, then create mobile pages with card-based lists. Reuse the already responsive current-task overview component on the mobile job-details page.

**Tech Stack:** Vue 3, Element Plus, VueUse `useMediaQuery`, Vue Router, SCSS

---

### Task 1: Split Desktop and Mobile Route Components

**Files:**
- Move: `web/src/views/pages/home/task.vue` to `web/src/views/pages/home/taskDesktop.vue`
- Move: `web/src/views/pages/home/taskDetail.vue` to `web/src/views/pages/home/taskDetailDesktop.vue`
- Create: `web/src/views/pages/home/task.vue`
- Create: `web/src/views/pages/home/taskDetail.vue`

**Step 1:** Preserve existing desktop component content during the moves.

**Step 2:** Add breakpoint dispatchers that mount exactly one desktop or mobile page.

### Task 2: Mobile Job Details

**Files:**
- Create: `web/src/views/pages/home/taskMobile.vue`

**Step 1:** Reuse the current-task overview and fetch paginated task history.

**Step 2:** Render each task as a card with status, timestamp, total/success/failure/other counts, failure reason, delete, and details actions.

**Step 3:** Preserve back, refresh, delete confirmation, task navigation, and pagination behavior.

### Task 3: Mobile Task Item Details

**Files:**
- Create: `web/src/views/pages/home/taskDetailMobile.vue`

**Step 1:** Fetch task items with status and type filters.

**Step 2:** Render cards containing file name, size, operation type, status or progress, source/target paths, creation time, and failure reason.

**Step 3:** Preserve back, refresh, filtering, and pagination behavior.

### Task 4: Mobile Copy

**Files:**
- Modify: `web/src/locales/zh-CN.yaml`
- Modify: `web/src/locales/en.yaml`

**Step 1:** Add mobile section headings, counts, and empty-state labels without changing desktop copy.

### Task 5: Verification Handoff

**Files:**
- No code changes.

**Step 1:** Do not run local build, lint, browser, or screenshot verification because the user requested to verify changes themselves.
