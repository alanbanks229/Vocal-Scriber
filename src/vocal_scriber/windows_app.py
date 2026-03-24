"""Packaged Windows tray app for Vocal-Scriber."""

from __future__ import annotations

import ctypes
import os
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, ttk

from . import __version__
from .common import list_input_devices
from .platforms import windows as windows_runtime
from .windows_support import (
    APP_NAME,
    build_runtime_config,
    configure_file_logger,
    ensure_app_directories,
    get_device_display_name,
    get_log_path,
    get_logs_dir,
    load_app_settings,
    resolve_saved_input_device,
    save_app_settings,
)

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - import guard for user guidance
    raise SystemExit(
        "Windows app mode requires Pillow and pystray. Reinstall with the Windows package extra."
    ) from exc


def _center_window(window: tk.Misc) -> None:
    """Center a tkinter window on the current screen."""
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"+{x}+{y}")


@dataclass
class LaunchStatusState:
    """Thread-safe startup state consumed by the packaged launch dialog."""

    device_name: str
    first_run: bool
    phase: str = "starting"
    detail: str = "Preparing voice typing..."
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, str | bool]:
        with self.lock:
            return {
                "device_name": self.device_name,
                "first_run": self.first_run,
                "phase": self.phase,
                "detail": self.detail,
            }

    def set_starting(self, detail: str) -> None:
        with self.lock:
            self.phase = "starting"
            self.detail = detail

    def set_ready(self, device_name: str | None = None) -> None:
        with self.lock:
            if device_name:
                self.device_name = device_name
            self.phase = "ready"
            self.detail = "Click OK, then press F9 to start recording."

    def set_error(self, detail: str) -> None:
        with self.lock:
            self.phase = "error"
            self.detail = detail


class MicrophonePickerDialog:
    """Simple tkinter-based microphone picker for packaged Windows builds."""

    def __init__(self, selected_device_index: int | None = None):
        self.selected_device_index = selected_device_index
        self.devices = list_input_devices()
        self.result: tuple[int, str] | None = None
        self.root = tk.Tk()
        self.root.withdraw()
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title(f"{APP_NAME} Setup")
        self.dialog.resizable(False, False)
        self.dialog.protocol("WM_DELETE_WINDOW", self._cancel)
        try:
            self.dialog.attributes("-topmost", True)
        except Exception:
            pass

        self.selection_var = tk.StringVar(value="Select the microphone to use for F9 voice typing.")
        self.frame: tk.Frame | None = None
        self.listbox: tk.Listbox | None = None

        self._build_ui()
        self._populate_devices()

    def _build_ui(self) -> None:
        self.frame = tk.Frame(self.dialog, padx=14, pady=14)
        self.frame.pack(fill="both", expand=True)

        tk.Label(
            self.frame,
            text="Choose a microphone for Vocal-Scriber",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self.frame,
            text="You can change this later from the tray icon.",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 10))

        list_container = tk.Frame(self.frame, borderwidth=1, relief="sunken")
        list_container.pack(fill="both", expand=True)

        x_scrollbar = tk.Scrollbar(list_container, orient="horizontal")
        x_scrollbar.pack(side="bottom", fill="x")

        self.listbox = tk.Listbox(
            list_container,
            width=64,
            height=8,
            exportselection=False,
            font=("Segoe UI", 9),
            bg="white",
            fg="black",
            selectbackground="#0a64ad",
            selectforeground="white",
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            xscrollcommand=x_scrollbar.set,
        )
        self.listbox.pack(fill="both", expand=True, padx=1, pady=1)
        x_scrollbar.config(command=self.listbox.xview)
        self.listbox.bind("<<ListboxSelect>>", self._update_selection_label)

        tk.Label(
            self.frame,
            textvariable=self.selection_var,
            wraplength=440,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(10, 12))

        button_row = tk.Frame(self.frame)
        button_row.pack(fill="x")
        tk.Button(button_row, text="Cancel", width=12, command=self._cancel).pack(side="right")
        tk.Button(button_row, text="Use Microphone", width=14, command=self._confirm).pack(
            side="right", padx=(0, 8)
        )

    def _populate_devices(self) -> None:
        if not self.devices:
            self.selection_var.set("No microphones were detected on this system.")
            return

        default_selection = 0
        for index, device in enumerate(self.devices):
            label = device["name"]
            if device["is_default"]:
                label = f"{label} (system default)"
            self.listbox.insert(tk.END, label)
            if device["index"] == self.selected_device_index:
                default_selection = index
            elif self.selected_device_index is None and device["is_default"]:
                default_selection = index

        self.listbox.selection_set(default_selection)
        self.listbox.activate(default_selection)
        self._update_selection_label()

    def _update_selection_label(self, event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        device = self.devices[selection[0]]
        detail = (
            f"Preferred backend: {device['hostapi']} | "
            f"Channels: {device['channels']} | "
            f"Sample Rate: {device['sample_rate']:.0f} Hz"
        )
        self.selection_var.set(detail)

    def _confirm(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showerror(APP_NAME, "Please select a microphone.", parent=self.dialog)
            return

        device = self.devices[selection[0]]
        self.result = (device["index"], device["name"])
        self.dialog.destroy()
        self.root.quit()

    def _cancel(self) -> None:
        self.result = None
        self.dialog.destroy()
        self.root.quit()

    def show(self) -> tuple[int, str] | None:
        _center_window(self.dialog)
        try:
            self.dialog.grab_set()
        except Exception:
            pass
        self.dialog.deiconify()
        self.dialog.lift()
        self.dialog.focus_force()
        self.dialog.after(250, self._bring_to_front)
        self.root.mainloop()
        self.root.destroy()
        return self.result

    def _bring_to_front(self) -> None:
        try:
            self.dialog.deiconify()
            self.dialog.lift()
            self.dialog.focus_force()
            self.dialog.attributes("-topmost", True)
            self.dialog.after(1000, lambda: self.dialog.attributes("-topmost", False))
        except Exception:
            pass


class LaunchStatusDialog:
    """Startup progress and ready acknowledgement for the packaged Windows app."""

    def __init__(self, state: LaunchStatusState, open_logs_callback):
        self.state = state
        self._open_logs_callback = open_logs_callback
        self.result = "closed"
        self.root = tk.Tk()
        self.root.withdraw()
        self.dialog = tk.Toplevel(self.root)
        self.dialog.title(APP_NAME)
        self.dialog.resizable(False, False)
        self.dialog.protocol("WM_DELETE_WINDOW", self._ignore_close)
        try:
            self.dialog.attributes("-topmost", True)
        except Exception:
            pass

        self.title_var = tk.StringVar(value="Starting Vocal-Scriber")
        self.detail_var = tk.StringVar(value="Preparing voice typing...")
        self.device_var = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")
        self._current_phase = ""

        self._build_ui()

    def _build_ui(self) -> None:
        frame = tk.Frame(self.dialog, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            textvariable=self.title_var,
            font=("Segoe UI", 10, "bold"),
            justify="left",
        ).pack(anchor="w")

        tk.Label(
            frame,
            textvariable=self.detail_var,
            font=("Segoe UI", 9),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(8, 8))

        tk.Label(
            frame,
            textvariable=self.device_var,
            font=("Segoe UI", 9),
            wraplength=420,
            justify="left",
        ).pack(anchor="w")

        tk.Label(
            frame,
            textvariable=self.note_var,
            font=("Segoe UI", 9),
            wraplength=420,
            justify="left",
            fg="#4b5563",
        ).pack(anchor="w", pady=(8, 12))

        self.progress = ttk.Progressbar(frame, mode="indeterminate", length=360)
        self.progress.pack(fill="x", pady=(0, 12))

        button_row = tk.Frame(frame)
        button_row.pack(fill="x")

        self.close_button = tk.Button(button_row, text="Close", width=12, command=self._close_error)
        self.logs_button = tk.Button(button_row, text="Open Logs", width=12, command=self._open_logs)
        self.ok_button = tk.Button(
            button_row,
            text="Starting...",
            width=20,
            state="disabled",
            command=self._confirm_ready,
        )
        self.ok_button.pack(side="right")

    def _open_logs(self) -> None:
        self._open_logs_callback()

    def _ignore_close(self) -> None:
        return

    def _close_error(self) -> None:
        if self._current_phase != "error":
            return
        self.result = "error"
        if self.dialog.winfo_exists():
            self.dialog.destroy()
        self.root.quit()

    def _confirm_ready(self) -> None:
        if self._current_phase != "ready":
            return
        self.result = "ready"
        if self.dialog.winfo_exists():
            self.dialog.destroy()
        self.root.quit()

    def _apply_phase(self, phase: str) -> None:
        if phase == self._current_phase:
            return

        self._current_phase = phase
        if phase == "starting":
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
            self.ok_button.pack(side="right")
            self.ok_button.configure(text="Starting...", state="disabled")
            self.logs_button.pack_forget()
            self.close_button.pack_forget()
            self.dialog.protocol("WM_DELETE_WINDOW", self._ignore_close)
        elif phase == "ready":
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100, value=100)
            self.ok_button.pack(side="right")
            self.ok_button.configure(text="OK - Press F9 to Start", state="normal")
            self.logs_button.pack_forget()
            self.close_button.pack_forget()
            self.dialog.protocol("WM_DELETE_WINDOW", self._ignore_close)
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100, value=0)
            self.ok_button.pack_forget()
            self.close_button.pack(side="right")
            self.logs_button.pack(side="right", padx=(0, 8))
            self.dialog.protocol("WM_DELETE_WINDOW", self._close_error)

    def _render(self) -> None:
        snapshot = self.state.snapshot()
        phase = str(snapshot["phase"])
        self._apply_phase(phase)

        device_name = str(snapshot["device_name"])
        if device_name:
            self.device_var.set(f"Selected microphone: {device_name}")
        else:
            self.device_var.set("")

        if phase == "starting":
            self.title_var.set("Starting Vocal-Scriber")
            self.detail_var.set(str(snapshot["detail"]))
            if bool(snapshot["first_run"]):
                self.note_var.set("The speech model may download on first launch and can take a minute.")
            else:
                self.note_var.set("Vocal-Scriber will keep running in the system tray after startup.")
        elif phase == "ready":
            self.title_var.set("Vocal-Scriber is ready")
            self.detail_var.set("Click OK, then press F9 to start recording.")
            self.note_var.set("After you click OK, Vocal-Scriber will continue running from the system tray.")
        else:
            self.title_var.set("Vocal-Scriber could not start")
            self.detail_var.set(str(snapshot["detail"]))
            self.note_var.set("Use Open Logs for more details, or Close to exit.")

    def _poll_state(self) -> None:
        if not self.dialog.winfo_exists():
            return
        self._render()
        if self.dialog.winfo_exists():
            self.dialog.after(100, self._poll_state)

    def show(self) -> str:
        _center_window(self.dialog)
        try:
            self.dialog.grab_set()
        except Exception:
            pass
        self.dialog.deiconify()
        self.dialog.lift()
        self.dialog.focus_force()
        self.dialog.after(100, self._poll_state)
        self.root.mainloop()
        self.root.destroy()
        return self.result


class WindowsTrayApp:
    """System tray wrapper around the packaged Windows runtime."""

    def __init__(self):
        ensure_app_directories()
        self.settings = load_app_settings()
        self.logger = configure_file_logger(debug=bool(self.settings.get("debug", False)))
        self.status_text = "Starting"
        self.icon = None
        self._status_lock = threading.Lock()
        self._picker_lock = threading.Lock()
        self._launch_state: LaunchStatusState | None = None

    def set_status(self, status: str, detail: str = "") -> None:
        cleaned_status = status.strip("[]") if status else "Status"
        combined = f"{cleaned_status}: {detail}" if detail else cleaned_status
        with self._status_lock:
            self.status_text = combined
        if self._launch_state:
            if status == "[STARTING]":
                self._launch_state.set_starting(detail or "Preparing voice typing...")
            elif status == "[ERROR]":
                self._launch_state.set_error(detail or "Vocal-Scriber could not start.")
        self.logger.info("%s %s", status, detail)
        if self.icon:
            self.icon.update_menu()

    def notify(self, message: str) -> None:
        self.logger.info(message)
        if self.icon:
            try:
                self.icon.notify(message, APP_NAME)
                return
            except Exception:
                pass
        self._show_info(message)

    def _show_info(self, message: str) -> None:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x40)
            return

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, message, parent=root)
        root.destroy()

    def _show_error(self, message: str) -> None:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
            return

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message, parent=root)
        root.destroy()

    def _build_icon_image(self):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(30, 33, 45, 255))
        draw.rounded_rectangle((26, 16, 38, 36), radius=6, fill=(241, 245, 249, 255))
        draw.rectangle((29, 36, 35, 46), fill=(241, 245, 249, 255))
        draw.arc((20, 24, 44, 48), start=200, end=340, fill=(125, 211, 252, 255), width=3)
        draw.line((18, 48, 46, 48), fill=(125, 211, 252, 255), width=3)
        return image

    def _prompt_for_microphone(self, current_device_index: int | None = None) -> tuple[int, str] | None:
        dialog = MicrophonePickerDialog(selected_device_index=current_device_index)
        return dialog.show()

    def _prepare_runtime_for_launch(self, device_index: int) -> None:
        try:
            self.set_status("[STARTING]", "Preparing voice typing...")
            config = build_runtime_config(self.settings)
            windows_runtime.prepare_runtime(
                runtime_config=config,
                device_index=device_index,
                callbacks=windows_runtime.RuntimeCallbacks(
                    on_status=self.set_status,
                    on_debug=self.logger.debug,
                    on_error=self._handle_runtime_error,
                ),
                console_output=False,
            )
            device_name = get_device_display_name(device_index) or self.settings.get("selected_device_name") or ""
            self.settings["selected_device_index"] = device_index
            self.settings["selected_device_name"] = device_name
            self.settings["first_run_complete"] = True
            save_app_settings(self.settings)
            if self._launch_state:
                self._launch_state.set_ready(device_name)
            self.logger.info("Runtime prepared; waiting for user acknowledgement")
        except Exception as exc:
            self.logger.exception("Failed to prepare packaged Windows runtime")
            self.set_status("[ERROR]", str(exc))
            if self._launch_state:
                self._launch_state.set_error(f"{exc}\n\nUse Open Logs for more details.")

    def _handle_runtime_error(self, detail: str) -> None:
        self.logger.error(detail)
        self.set_status("[ERROR]", detail)

    def _start_runtime_after_acknowledgement(self) -> bool:
        try:
            self.logger.info("User acknowledged ready state; activating F9 listener")
            windows_runtime.start_hotkey_listener()
            return True
        except Exception as exc:
            self.logger.exception("Failed to start hotkey listener")
            self.set_status("[ERROR]", str(exc))
            windows_runtime.shutdown_runtime()
            self._show_error(
                "Vocal-Scriber could not finish startup.\n\n"
                f"{exc}\n\n"
                f"See logs at:\n{get_log_path()}"
            )
            return False

    def _restart_runtime_after_device_change(self, device_index: int) -> None:
        try:
            self.set_status("[STARTING]", "Restarting voice typing...")
            config = build_runtime_config(self.settings)
            windows_runtime.prepare_runtime(
                runtime_config=config,
                device_index=device_index,
                callbacks=windows_runtime.RuntimeCallbacks(
                    on_status=self.set_status,
                    on_debug=self.logger.debug,
                    on_error=self._handle_runtime_error,
                ),
                console_output=False,
            )
            windows_runtime.start_hotkey_listener()
            device_name = get_device_display_name(device_index) or self.settings.get("selected_device_name") or ""
            self.settings["selected_device_index"] = device_index
            self.settings["selected_device_name"] = device_name
            self.settings["first_run_complete"] = True
            save_app_settings(self.settings)
            self.notify(f"Using microphone: {device_name}")
        except Exception as exc:
            self.logger.exception("Failed to restart runtime after microphone change")
            self.set_status("[ERROR]", str(exc))
            windows_runtime.shutdown_runtime()
            self._show_error(
                "Could not restart Vocal-Scriber.\n\n"
                f"{exc}\n\n"
                f"See logs at:\n{get_log_path()}"
            )

    def _choose_microphone(self) -> None:
        if not self._picker_lock.acquire(blocking=False):
            self.logger.info("Microphone picker is already open")
            return

        try:
            current_device = self.settings.get("selected_device_index")
            selection = self._prompt_for_microphone(current_device)
            if selection is None:
                return

            device_index, device_name = selection
            self.settings["selected_device_index"] = device_index
            self.settings["selected_device_name"] = device_name
            save_app_settings(self.settings)

            if windows_runtime.is_runtime_active():
                try:
                    windows_runtime.switch_audio_device(device_index)
                    self.notify(f"Using microphone: {device_name}")
                    self.set_status("[READY]", "Press F9 to record")
                except Exception as exc:
                    self.logger.exception("Failed to switch microphone")
                    self._show_error(f"Could not switch microphones.\n\n{exc}")
            else:
                threading.Thread(
                    target=self._restart_runtime_after_device_change,
                    args=(device_index,),
                    daemon=True,
                ).start()
        finally:
            self._picker_lock.release()

    def _choose_microphone_async(self, icon=None, item=None) -> None:
        threading.Thread(target=self._choose_microphone, daemon=True).start()

    def _open_logs(self, icon=None, item=None) -> None:
        os.startfile(get_logs_dir())

    def _quit(self, icon=None, item=None) -> None:
        self.set_status("[STOPPING]", "Closing Vocal-Scriber...")
        windows_runtime.shutdown_runtime()
        if self.icon:
            self.icon.stop()

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: f"Status: {self.status_text}",
                None,
                enabled=False,
            ),
            pystray.MenuItem("Choose Microphone", self._choose_microphone_async),
            pystray.MenuItem("Open Logs", self._open_logs),
            pystray.MenuItem("Quit", self._quit),
        )

    def run(self) -> None:
        has_saved_device = (
            self.settings.get("selected_device_index") is not None
            or bool(self.settings.get("selected_device_name"))
        )
        first_run = not self.settings.get("first_run_complete")

        if not self.settings.get("first_run_complete") or not has_saved_device:
            selection = self._prompt_for_microphone()
            if selection is None:
                return
            device_index, device_name = selection
            self.settings["selected_device_index"] = device_index
            self.settings["selected_device_name"] = device_name
            save_app_settings(self.settings)
        else:
            device_index = resolve_saved_input_device(self.settings)
            if device_index is None:
                selection = self._prompt_for_microphone()
                if selection is None:
                    return
                device_index, device_name = selection
                self.settings["selected_device_index"] = device_index
                self.settings["selected_device_name"] = device_name
                save_app_settings(self.settings)

        device_name = get_device_display_name(device_index) or self.settings.get("selected_device_name") or ""
        self._launch_state = LaunchStatusState(device_name=device_name, first_run=first_run)
        launch_dialog = LaunchStatusDialog(self._launch_state, self._open_logs)
        threading.Thread(target=self._prepare_runtime_for_launch, args=(device_index,), daemon=True).start()
        launch_result = launch_dialog.show()
        self._launch_state = None

        if launch_result != "ready":
            windows_runtime.shutdown_runtime()
            return

        if not self._start_runtime_after_acknowledgement():
            return

        self.icon = pystray.Icon(
            name="vocal_scriber",
            title=f"{APP_NAME} {__version__}",
            icon=self._build_icon_image(),
            menu=self._build_menu(),
        )

        self.icon.run()


def main() -> None:
    """Run the packaged Windows tray app."""
    if os.name != "nt":
        raise SystemExit("The Windows tray app entrypoint only supports Windows.")
    WindowsTrayApp().run()


if __name__ == "__main__":
    main()
