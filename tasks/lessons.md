# Lessons

## 2026-05-18 — Verify product behavior, not just packaging

- Do not mark desktop release work complete after CI/signing/notarization alone.
- Always click through the installed app's primary path (Start → forms → provision/smoke where safe).
- Avoid inline HTML event handlers in Tauri/Vite apps; CSP can make buttons appear active while clicks do nothing. Use delegated `addEventListener` handlers.
- Do not substitute placeholder gradient blocks for branded app UI; use the approved brand asset in both bundle icons and in-window header.

## 2026-05-18 — Verify enabled/disabled transitions after form input

- When replacing inline handlers with delegated events, also verify dynamic button state transitions.
- Test the actual form path: type business name → slug auto-fills → primary CTA becomes enabled → click CTA.
- Prefer a small `syncNavState()` helper over full rerenders on every keystroke to avoid losing focus.
