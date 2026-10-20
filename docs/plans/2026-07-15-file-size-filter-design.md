# File Size Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-job lower and upper file-size filters across persistence, sync execution, desktop/mobile forms, documentation, and tests.

**Architecture:** Store nullable `minFileSize` and `maxFileSize` values as integer bytes on each job. Apply the range in `JobTask` while comparing the unfiltered source and target listings so a filtered source file is never mistaken for a missing source file. Reuse one Vue component in both responsive job editors and convert B/KB/MB/GB values to canonical bytes at the UI boundary.

**Tech Stack:** Python 3, Tornado, SQLite, APScheduler, AList/OpenList API, Vue 3, Element Plus, vue-i18n, unittest.

---

## Design

### Contract and boundaries

- `minFileSize`: nullable non-negative integer bytes. Files strictly smaller than this value are excluded.
- `maxFileSize`: nullable non-negative integer bytes. Files strictly larger than this value are excluded.
- Values equal to either boundary remain eligible.
- Both values may be set to define an inclusive range; `minFileSize` must not exceed `maxFileSize`.
- `NULL` means that boundary is disabled. Existing jobs migrate with both values set to `NULL` and retain their current behavior.
- UI units use powers of 1024 and offer B, KB, MB, and GB.

### Sync safety

Filtering at `AlistClient.fileListApi` would independently hide source and target entries. In full-sync mode, a filtered source entry whose target copy falls on the other side of a threshold could then look source-missing and be deleted. The filter therefore belongs in `JobTask` after raw, path-excluded listings have been loaded.

- Source files outside the range are not copied or moved.
- A target file with a same-name source entry is never deleted merely because the source is outside the range.
- Target-only files outside the range are preserved in full-sync mode.
- When a target-only directory is encountered while a size filter is active, scan it recursively and delete only eligible files. Keep directory shells so an entire directory cannot bypass the file filter and remove protected descendants.
- With no size filter, retain the existing whole-directory deletion behavior and request pattern.

## Tasks

### Task 1: Persistence and request validation

**Files:**
- Modify: `common/sqlInit.py`
- Modify: `mapper/jobMapper.py`
- Modify: `service/syncJob/jobService.py`
- Modify: `locales/zh_CN.yaml`
- Modify: `locales/en.yaml`
- Test: `test/test_file_size_filter.py`

**Steps:**
1. Add failing tests for new-schema columns, migration columns, default `NULL` values, non-negative integer validation, and ordered boundaries.
2. Bump `sqlVersion` to `260715`; add both integer columns to new and upgraded databases.
3. Include both fields in job inserts and updates.
4. Normalize omitted values to `None` and reject malformed or reversed ranges with localized errors.
5. Run `python -m unittest test.test_file_size_filter -v` and expect all persistence/validation cases to pass.

### Task 2: Sync filtering semantics

**Files:**
- Modify: `service/syncJob/jobClient.py`
- Test: `test/test_file_size_filter.py`

**Steps:**
1. Add failing tests for lower/upper boundaries, only-add, move, full-sync deletion, mismatched same-name target sizes, and target-only directories.
2. Add a pure size-range predicate and a `JobTask` helper that reads the job boundaries.
3. Skip out-of-range source files in both existing-target and missing-target recursion.
4. In full-sync deletion, preserve out-of-range target-only files and recursively clean target-only directories when a filter is active.
5. Run `python -m unittest test.test_file_size_filter -v` and expect all sync behavior cases to pass.

### Task 3: Shared responsive UI

**Files:**
- Create: `web/src/views/pages/home/components/fileSizeFilter.vue`
- Modify: `web/src/views/pages/home/desktop.vue`
- Modify: `web/src/views/pages/home/mobile.vue`
- Modify: `web/src/locales/zh-CN.yaml`
- Modify: `web/src/locales/en.yaml`

**Steps:**
1. Create a compact shared control with two optional numeric rows, unit selectors, clear buttons, and accessible labels.
2. Bind canonical byte values with `v-model:min-file-size` and `v-model:max-file-size`.
3. Initialize new jobs with nullable boundaries and preserve API values when editing existing jobs.
4. Add a cross-field form validator and localized help/error text.
5. Run `npm run build` and `npm run lint -- --no-fix` from `web/`; expect successful compilation and no lint errors in changed files.

### Task 4: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `doc/changelog/v0.3.3.md`
- Create: `AGENTS.md`
- Create/update external memory: `~/memory/projects/taosync.md`, `~/memory/projects/INDEX.md`, `~/memory/INDEX.md`

**Steps:**
1. Document the filter and link GitHub issues `#146` and `#217` in the v0.3.3 feature entry.
2. Add the stable architecture and sync-flow summary to project memory and point future project sessions to it from `AGENTS.md`.
3. Run the complete Python unittest suite and the frontend production build.
4. Start the application locally, inspect desktop and mobile job editors, and verify that controls fit without overlap in both themes.
5. Review `git diff --check`, `git status --short`, and the final diff without altering unrelated user changes.
