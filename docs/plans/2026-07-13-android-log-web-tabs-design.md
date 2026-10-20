# Android Log And Web Tabs Design

## Context

The Android package uses python-for-android's `webview` bootstrap. The activity's
internal WebView opens the local log page on port 8024, while the background
service exposes the full taoSync web application on port 8023.

## Options Considered

1. Rebuild the activity layout with native Android buttons and re-parent
   `PythonActivity.mWebView`. This creates true native tabs, but it couples the
   Python entry point to python-for-android implementation details and UI-thread
   callbacks.
2. Navigate the existing WebView directly between ports 8024 and 8023. This is
   small, but the menu disappears after navigation and switching depends on the
   browser history stack.
3. Keep port 8024 as a persistent shell with two top tabs and render port 8023
   in an iframe inside the same Android WebView. This keeps navigation visible,
   preserves both views while switching, and needs no new Android dependency.

Option 3 is selected because it is the smallest change that preserves the
existing process model and always keeps the log tab available.

## Behavior

- The top bar has `日志` and `网页` tabs.
- `日志` is selected on every fresh app launch.
- The existing live log viewer remains active and keeps polling while hidden.
- The `网页` tab lazily loads `http://127.0.0.1:8023/` in an iframe rendered by
  the app's existing Android WebView. No external browser intent is used.
- The outer log shell also uses `127.0.0.1` instead of `localhost`, keeping the
  cross-port iframe same-site so Android WebView does not reject login cookies
  as third-party cookies.
- Switching tabs hides and shows the existing views without recreating them, so
  web page state and log scroll state are retained.

## Error Handling And Verification

If port 8023 is not ready, the WebView displays its normal connection error and
the user can still return to `日志`. Static tests extract the inline HTML without
importing `service/main.py`, then verify the default tab, local URL, lazy loading,
and view-switching hooks. The existing Python tests remain the regression suite.
