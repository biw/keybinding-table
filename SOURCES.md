# Keybinding evidence sources

This register defines the compact source IDs used by the keybinding evidence
records and, once verified, by entries in [README.md](README.md). A source ID
identifies evidence for a result; it does not make an untested shortcut
universal. Every observed result is additionally tied to a browser version, OS
build, input layout, focus state, clean-profile status, and workflow artifact.

## Baseline

- Default profiles only: no extensions, enterprise policies, custom app
  shortcuts, or custom browser keybindings.
- Keyboard layout: U.S. layout. macOS results use ANSI virtual key codes and
  Windows results use the U.S. virtual-key mapping.
- The `meta` modifier in this repository remains Command on macOS and the
  Windows-logo key on Windows. Windows-logo rows describe Windows-shell
  behavior, not browser accelerators.
- Browser help pages are the authoritative public description of documented
  defaults. Release-matched shipped/source code is a tie-breaker only. A
  runtime observation wins when documented behavior is focus-sensitive.

## FF-KEYBOARD

- URL: <https://support.mozilla.org/en-US/kb/keyboard-shortcuts-perform-firefox-tasks-quickly>
- Retrieved: 2026-08-10
- Scope: Firefox desktop’s documented Windows and macOS shortcuts.
- Caveats: desktop/window-manager shortcuts can take precedence; Firefox 147+
  supports shortcut customization, so observations must use a reset profile.

## FF-SOURCE

- URL: <https://searchfox.org/mozilla-central/source/browser/base/content/browser-sets.inc>
- Retrieved: 2026-08-10
- Scope: Firefox browser-chrome key declarations and reservation behavior.
- Caveats: use a revision matching the observed release or its shipped
  `omni.ja`; never use Firefox main as proof for a released build.

## CHROME-KEYBOARD

- URL: <https://support.google.com/chrome/answer/157179?hl=en>
- Retrieved: 2026-08-10
- Scope: Google Chrome’s published desktop shortcuts.
- Caveats: absence from this curated list does not prove that a chord has no
  effect in an editable control.

## CHROMIUM-SOURCE

- URL: <https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/ui/accelerator_table.cc>
- Retrieved: 2026-08-10
- Scope: implementation-level Chromium accelerator and reservation analysis.
- Caveats: pin the link to the tested revision before citing it. It is not an
  authority for Microsoft Edge-specific behavior.

## EDGE-KEYBOARD

- URL: <https://support.microsoft.com/en-US/edge/keyboard-shortcuts-in-microsoft-edge>
- Retrieved: 2026-08-10
- Scope: Microsoft Edge’s documented Windows shortcuts.
- Caveats: Edge can add downstream commands and policy can change defaults;
  clean, policy-free runtime observations are required for gaps.

## EDGE-POLICY

- URL: <https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/ConfigureKeyboardShortcuts>
- Retrieved: 2026-08-10
- Scope: enterprise configuration that can remove Microsoft Edge shortcuts.
- Caveats: this policy can disable otherwise-default shortcuts; use a clean,
  policy-free profile for baseline observations.

## SAFARI-KEYBOARD

- URL: <https://support.apple.com/guide/safari/cpsh003/mac>
- Retrieved: 2026-08-10
- Scope: Safari on Mac’s documented menu and browsing shortcuts.
- Caveats: Safari documents that shortcuts vary with language and input source;
  inspect the tested Safari menu and record relevant Safari preferences.

## MAC-KEYBOARD

- URL: <https://support.apple.com/en-us/102650>
- Retrieved: 2026-08-10
- Scope: standard macOS app and text-editing shortcuts.
- Caveats: Apple states text-editing behavior can vary by app. Treat these as
  supporting context, not conclusive evidence for a browser textarea.

## WIN-KEYBOARD

- URL: <https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec>
- Retrieved: 2026-08-10
- Scope: Windows keyboard and Windows-logo-key shortcuts.
- Caveats: some Windows commands are configuration-, edition-, or
  device-dependent. Session-changing chords are documented rather than
  injected on shared CI runners.

## W3C-UIEVENTS

- URL: <https://www.w3.org/TR/uievents/>
- Retrieved: 2026-08-10
- Scope: browser keyboard-event and input-event semantics.
- Caveats: this specifies page events, not browser-chrome or OS shortcut
  reservation.

## MAC-CGEVENT

- URL: <https://developer.apple.com/documentation/coregraphics/cgevent/post(tap:)>
- Retrieved: 2026-08-10
- Scope: posting keyboard events into the macOS Quartz event stream.
- Caveats: this requires a real, foreground application and is intentionally
  performed only on disposable GitHub-hosted macOS runners.

## WIN-SENDINPUT

- URL: <https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput>
- Retrieved: 2026-08-10
- Scope: inserting keyboard events into the Windows input stream.
- Caveats: input can be blocked by integrity-level isolation. The workflow
  records an injector failure rather than fabricating a result.
