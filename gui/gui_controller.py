"""GUI controller for managing waveform visualization lifecycle."""
import sys
import threading
import queue
from gui.waveform_window import WaveformWindow


class GUIController:
    """
    Manages GUI lifecycle on the main thread (required for macOS).

    Provides thread-safe interface for showing/hiding the waveform window
    and passing audio data from the recording callback to the GUI.
    """

    def __init__(self, config):
        """
        Initialize GUI controller.

        Args:
            config: Configuration object with GUI settings
        """
        self.config = config
        self.audio_level_queue = queue.Queue(maxsize=60)
        self.window = None
        self.menubar_waveform = None  # macOS menu bar waveform icon
        self.is_running = False
        self._recording = False
        self._lock = threading.Lock()
        self.quit_callback = None  # Will be set by main app

    def create_window(self):
        """
        Create visualization components based on config.

        - If GUI enabled: Create tkinter window only
        - If GUI disabled and macOS: Create menu bar waveform icon only
        - Otherwise: No visualization

        Must be called on main thread on macOS.
        """
        if self.window is not None or self.menubar_waveform is not None:
            return

        try:
            if self.config.gui:
                # GUI mode: Create tkinter window
                import tkinter as tk
                self.window = WaveformWindow(self.config, self.audio_level_queue)
                self.window.create_window()
                if self.config.debug:
                    print("[DEBUG] Floating window GUI created")
            elif sys.platform == 'darwin':
                # Menu bar only mode (macOS only)
                try:
                    from gui.menubar_waveform import MenuBarWaveform
                    # PyObjC NSObject subclasses require alloc/init pattern
                    self.menubar_waveform = MenuBarWaveform.alloc().initWithConfig_audioLevelQueue_(
                        self.config,
                        self.audio_level_queue
                    )
                    if self.config.debug:
                        print("[DEBUG] Menu bar waveform created (default mode)")
                except Exception as e:
                    if self.config.debug:
                        print(f"[DEBUG] Menu bar waveform initialization failed: {e}")
                    raise

            self.is_running = True
        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] GUI/visualization creation error: {e}")
            raise

    def run_mainloop(self):
        """
        Run tkinter mainloop on current thread (blocks until window closes).

        Must be called on main thread on macOS. This will block until
        quit() is called or the window is closed.
        """
        if self.window and self.window.root:
            try:
                # Start tkinter main loop - blocks here
                self.window.root.mainloop()
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] GUI mainloop error: {e}")
            finally:
                self.is_running = False

    def show(self):
        """Show waveform visualization (window or menu bar) (thread-safe)."""
        with self._lock:
            self._recording = True

        # Show floating window (if GUI mode)
        if self.window and self.window.root:
            try:
                # Schedule on GUI thread
                self.window.root.after(0, self.window.show)
            except:
                pass

        # Start menu bar waveform updates (if menu bar mode)
        if self.menubar_waveform:
            try:
                # Thread-safe: start_recording dispatches to main thread if needed
                self.menubar_waveform.start_recording()
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] Failed to start menu bar waveform: {e}")

    def hide(self):
        """Hide waveform visualization (window or menu bar) (thread-safe)."""
        with self._lock:
            self._recording = False

        # Hide floating window (if GUI mode)
        if self.window and self.window.root:
            try:
                # Schedule on GUI thread
                self.window.root.after(0, self.window.hide)
            except:
                pass

        # Stop menu bar waveform updates (if menu bar mode, resets to flat line)
        if self.menubar_waveform:
            try:
                # Thread-safe: stop_recording dispatches to main thread if needed
                self.menubar_waveform.stop_recording()
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] Failed to stop menu bar waveform: {e}")

    def is_recording(self):
        """
        Check if currently recording (thread-safe).

        Returns:
            bool: True if recording, False otherwise
        """
        with self._lock:
            return self._recording

    def quit(self):
        """
        Quit the GUI mainloop (thread-safe).

        This will cause run_mainloop() to return, allowing the main thread to exit.
        """
        self.is_running = False

        if self.window and self.window.root:
            try:
                # Schedule quit on GUI thread
                self.window.root.after(0, self.window.root.quit)
            except:
                pass

    def stop(self):
        """Stop the GUI and clean up."""
        self.is_running = False

        # Clean up floating window
        if self.window and self.window.root:
            try:
                self.window.root.after(0, self.window.destroy)
            except:
                pass

        # Clean up menu bar icon
        if self.menubar_waveform:
            try:
                self.menubar_waveform.destroy()
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] Failed to destroy menu bar waveform: {e}")
