# Web Mobile Responsive Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep the Vue 3 desktop UI unchanged while making every route usable and readable on phone-sized screens.

**Architecture:** Add shared mobile-only overrides at `max-width: 768px`, then add narrowly scoped component overrides where layout semantics differ. The desktop layout remains the default; mobile converts the sidebar to a bottom navigation bar, stacks dense controls, constrains teleported dialogs to the viewport, and preserves horizontal scrolling for data tables that cannot be reduced without losing information.

**Tech Stack:** Vue 3, Element Plus, SCSS, CSS media queries, VueUse `useMediaQuery`

---

### Task 1: Shared Mobile Foundation

**Files:**
- Modify: `web/src/assets/style/css-vars.css`

**Step 1:** Add a `@media (max-width: 768px)` block only.

**Step 2:** Reduce page padding, stack expanded detail fields, wrap pagination, constrain Element Plus dialogs/message boxes, and move dialog form labels above controls.

**Step 3:** Keep dense tables horizontally scrollable rather than shrinking their content below readable sizes.

### Task 2: Application Shell and Navigation

**Files:**
- Modify: `web/src/views/layout.vue`
- Modify: `web/src/views/components/appAside.vue`
- Modify: `web/src/views/components/appHeader.vue`
- Modify: `web/src/views/components/user.vue`
- Modify: `web/src/views/components/locale.vue`
- Modify: `web/src/views/index.vue`

**Step 1:** Detect the mobile breakpoint with `useMediaQuery('(max-width: 768px)')` and force the menu to remain expanded on mobile.

**Step 2:** In mobile-only CSS, move the four primary navigation items to a fixed bottom bar and remove the desktop collapse control.

**Step 3:** Remove left content padding on mobile, reserve bottom-navigation space, compact header spacing, and hide only the username text when width is constrained.

### Task 3: Authentication, Cards, Settings, and Forms

**Files:**
- Modify: `web/src/views/login.vue`
- Modify: `web/src/views/pages/engine/index.vue`
- Modify: `web/src/views/pages/notify/index.vue`
- Modify: `web/src/views/pages/setting/index.vue`

**Step 1:** Make the login panel fluid and center it without changing desktop width or placement.

**Step 2:** Convert engine and notification card grids to one column, reduce mobile gutters, and keep action buttons wrapped.

**Step 3:** Make the settings panel full width and move footer links into normal document flow on mobile.

### Task 4: Job Management

**Files:**
- Modify: `web/src/views/pages/home/index.vue`
- Modify: `web/src/views/pages/home/components/pathSelect.vue`

**Step 1:** Stack the mobile toolbar into title and actions rows while retaining the desktop toolbar.

**Step 2:** Keep the job table horizontally scrollable and give it a stable mobile viewport height.

**Step 3:** Convert the job dialog to a single-column, top-label form and make path/exclude controls wrap without overflow.

### Task 5: Task Lists, Filters, and Running Task Overview

**Files:**
- Modify: `web/src/views/pages/home/task.vue`
- Modify: `web/src/views/pages/home/taskDetail.vue`
- Modify: `web/src/views/pages/home/components/taskCurrent.vue`
- Modify: `web/src/views/pages/home/components/taskDetailTable.vue`
- Modify: `web/src/views/pages/home/components/menuRefresh.vue`

**Step 1:** Stack mobile filters and legends, while preserving horizontal scrolling for result tables.

**Step 2:** Change the running-task metrics, chart, status tabs, and task table from a fixed 1120px row into a vertical mobile flow.

**Step 3:** Emit a larger running-task container height on mobile so following content does not overlap.

### Task 6: Verification Handoff

**Files:**
- No code changes.

**Step 1:** Do not run build, lint, browser, or screenshot verification because the user explicitly requested to perform verification themselves.

**Step 2:** Report the changed files and the intended mobile behavior for user validation.
