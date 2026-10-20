# Android Log And Web Tabs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent top tabs to the Android client so it opens on live logs and can show `http://127.0.0.1:8023/` inside the app's WebView.

**Architecture:** Extend the HTML served by the existing localhost log server on port 8024 into a two-view shell. Keep the log DOM as the default view and lazily attach port 8023 to an iframe when the web tab is first selected.

**Tech Stack:** Python 3.11, Tornado, HTML/CSS/JavaScript, python-for-android WebView bootstrap, unittest

---

### Task 1: Add shell contract tests

**Files:**
- Create: `test/test_android_webview_tabs.py`
- Inspect: `service/main.py:194`
- Inspect: `main_android.py:108`

**Step 1: Write the failing test**

Extract `_LOG_PAGE_HTML` from the source AST and assert that it contains two
tabs, defaults to the log view, targets `http://127.0.0.1:8023/`, and lazily
loads the iframe inside the existing page. Also assert that the outer log shell
uses the same `127.0.0.1` loopback host.

**Step 2: Run test to verify it fails**

Run: `python -m unittest test.test_android_webview_tabs -v`

Expected: FAIL because the current log page has no tab shell or 8023 iframe.

### Task 2: Implement the persistent tab shell

**Files:**
- Modify: `service/main.py:194`
- Modify: `main_android.py:108`

**Step 1: Add the layout**

Add a fixed top tab bar, wrap the existing log toolbar and log output in the
default view, and add a hidden web view containing a lazy iframe.

**Step 2: Add switching behavior**

Toggle active and accessibility state for tabs and views. Assign the iframe's
`data-src` to `src` only on the first selection of the web tab.

**Step 3: Align the outer WebView host**

Load the 8024 shell from `127.0.0.1` instead of `localhost` so the business
iframe remains same-site and WebView login cookies continue to work.

**Step 4: Run the focused test**

Run: `python -m unittest test.test_android_webview_tabs -v`

Expected: PASS.

### Task 3: Verify regressions and packaging assumptions

**Files:**
- Inspect: `buildozer.spec`
- Inspect: `.github/workflows/build.yml`

**Step 1: Run all Python tests**

Run: `python -m unittest discover -s test -v`

Expected: PASS.

**Step 2: Check the diff**

Run: `git diff --check`

Expected: no whitespace errors.

**Step 3: Confirm packaging**

Verify that `service/**` is already included by `buildozer.spec` and that the
Android workflow packages `service/main.py`. No workflow edit is required.
