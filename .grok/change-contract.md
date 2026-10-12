# Change Contract — Prevent Pull-to-Refresh Triggering During Category Modal Scroll

## Problem
When scrolling down inside the detailed category transaction list (`CategoryModal`), dragging downwards (or scrolling back up to top) triggers the pull-to-refresh mechanism on `HomeScreen` (`Screen.jsx`), causing the entire app to reload/refresh unexpectedly while browsing transactions.

## Root Cause
1. `CategoryModal` is rendered inside `glance` in `Screen.jsx`. Touch events inside the modal bubble up to `onTouchStart`, `onTouchMove`, and `onTouchEnd` on `.glance`.
2. Even with `scrollTop` check on `.app-main`, the modal scroll is within `.category-modal-body` (not `.app-main`), so `scroller.scrollTop` remains 0, causing `Screen.jsx` to treat downward touch movements as a pull-to-refresh on the main dashboard.
3. Furthermore, mobile browsers (especially Chrome/Safari) also trigger the native browser pull-to-refresh when overscrolling if `overscroll-behavior` is not constrained.

## Must Touch
- `frontend/src/features/home/Screen.jsx`:
  - In `onTouchStart`, check if `e.target.closest('.category-modal-sheet')` or `e.target.closest('.category-modal-backdrop')` exists, or if `modalCategory` is active. If so, immediately abort touch tracking so modal gestures never trigger pull-to-refresh or month swipes.
- `frontend/src/features/home/CategoryModal.jsx`:
  - Add `onTouchStart={(e) => e.stopPropagation()}`, `onTouchMove={(e) => e.stopPropagation()}`, and `onTouchEnd={(e) => e.stopPropagation()}` on the modal backdrop and sheet to isolate modal touches completely from parent handlers.
- `frontend/src/App.css`:
  - Add `overscroll-behavior-y: contain` to `.category-modal-sheet`, `.category-modal-body`, and `.category-modal-backdrop` to prevent native browser rubber-banding/refresh.
- `frontend/public/sw.js`:
  - Bump service worker cache version to `expense-app-shell-v12`.

## Must Not Touch
- Backend APIs or domain logic.
- MCP / snapshot handlers.
- Desktop layout or unrelated screens.
