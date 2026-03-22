# macOS Menu Bar Note

This is an internal engineering note for the macOS menu bar implementation.

## Key Requirement

Interactive `NSStatusItem` menu bar behavior requires the `NSApplication` event loop, not just `NSRunLoop`.

- `NSRunLoop` is enough for timers and animation updates
- `NSApplication.run()` is required for click handling on the menu bar item

## Current Code Locations

- macOS runtime: `src/vocal_scriber/platforms/macos.py`
- menu bar implementation: `src/vocal_scriber/ui/menubar_waveform.py`
- UI controller: `src/vocal_scriber/ui/controller.py`

## What To Preserve

- use `NSApplicationActivationPolicyAccessory` so the app stays out of the Dock
- schedule periodic timer checks to stop the app cleanly
- post a wake-up event when stopping the app if needed so the run loop exits promptly
- keep menu bar UI logic isolated in the UI package rather than mixing it into shared code

## Why This Exists

This note exists so future refactors do not accidentally replace `NSApplication.run()` with a simpler run-loop approach and break menu interactions.
