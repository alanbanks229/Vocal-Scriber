Please inspect the codebase pertaining to the packaging and deployment of a windows exe version of this app.

As of right now I am on a feature branch and prior to introducing these packaging changes, I had a working cross-platform windows/macos developer terminal workflow.

```md
Repo: Vocal-Scriber
Platform focus: Windows packaged tray app for non-developers
Current goal: make the packaged Windows app behave correctly end-to-end before I share it with non-technical users

What already works:

- `python -m vocal_scriber --debug` works on Windows in dev mode
- `.\scripts\build-windows-app.ps1 -BundleOnly` builds the app bundle
- `.\scripts\build-windows-app.ps1` builds the installer
- packaged app starts, loads the model, and reaches a ready state

What is broken right now:

- first-run microphone selection behavior is inconsistent
- tray menu `Choose Microphone` behavior is unreliable/confusing
- the packaged app sometimes reaches `[TRANSCRIBING]` and appears stuck
- the startup/order of operations feels wrong for a normal user flow
- I want the packaged app UX to be: launch -> choose mic on first run -> load model if needed -> tray ready -> F9 works

Relevant files to inspect:

- `src/vocal_scriber/windows_app.py`
- `src/vocal_scriber/platforms/windows.py`
- `src/vocal_scriber/windows_support.py`
- `src/vocal_scriber/common.py`
- `scripts/build-windows-app.ps1`
- `packaging/windows/VocalScriber.iss`
- `docs/windows/app-packaging.md`

Current packaged-app log tail:
[paste the latest 80-150 log lines here]

Please give me:

1. A root-cause analysis of the likely packaged Windows issues
2. A prioritized implementation plan
3. The minimum changes needed to make first-run mic selection reliable
4. The minimum changes needed to diagnose/fix the transcribing hang
5. Any architectural recommendation if the tray-first approach is causing the bugs
6. A short smoke-test checklist for verifying the fix

Important constraints:

- Keep `python -m vocal_scriber` working for developers
- Keep the packaged Windows path focused on non-developer use
- Prefer fail-fast debugging and small, high-confidence changes
- If you make assumptions, label them clearly

If the current tray architecture is the wrong shape, say so directly and propose a simpler Windows-first UX.
```
