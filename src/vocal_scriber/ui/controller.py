"""GUI controller for managing macOS menu bar waveform visualization."""
import sys
import threading
import queue


class GUIController:
    """Manages macOS menu bar waveform visualization."""

    def __init__(self, config):
        """
        Initialize GUI controller.

        Args:
            config: Configuration object with settings
        """
        if config.debug:
            print("[DEBUG] GUIController.__init__ starting...")
        self.config = config
        self.audio_level_queue = queue.Queue(maxsize=60)
        self.menubar_waveform = None  # macOS menu bar waveform icon
        self.is_running = False
        self._recording = False
        self._lock = threading.Lock()
        self.quit_callback = None  # Will be set by main app
        if config.debug:
            print("[DEBUG] GUIController.__init__ complete")

    def create_window(self):
        """
        Create menu bar icon (macOS only).

        Must be called on main thread on macOS.
        """
        if self.menubar_waveform is not None:
            return

        # Only create menu bar on macOS
        if sys.platform != 'darwin':
            if self.config.debug:
                print("[DEBUG] Not macOS, skipping menu bar creation")
            return

        try:
            if self.config.debug:
                print("[DEBUG] Controller: Importing MenuBarWaveform...")
            from .menubar_waveform import MenuBarWaveform
            if self.config.debug:
                print("[DEBUG] Controller: Calling alloc()...")
            # PyObjC NSObject subclasses require alloc/init pattern
            menubar_obj = MenuBarWaveform.alloc()
            if self.config.debug:
                print(f"[DEBUG] Controller: alloc() returned: {type(menubar_obj)}")
                print("[DEBUG] Controller: Calling initWithConfig_audioLevelQueue_...")
            self.menubar_waveform = menubar_obj.initWithConfig_audioLevelQueue_(
                self.config,
                self.audio_level_queue
            )
            if self.config.debug:
                print(f"[DEBUG] Controller: init returned: {type(self.menubar_waveform)}")
                print("[DEBUG] Menu bar waveform created")

            self.is_running = True
        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] Menu bar waveform initialization failed: {e}")
                import traceback
                traceback.print_exc()
            raise

    def show(self):
        """Show waveform visualization (menu bar) (thread-safe)."""
        with self._lock:
            self._recording = True

        # Start menu bar waveform updates
        if self.menubar_waveform:
            try:
                # Thread-safe: start_recording dispatches to main thread if needed
                self.menubar_waveform.start_recording()
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] Failed to start menu bar waveform: {e}")

    def hide(self):
        """Hide waveform visualization (menu bar) (thread-safe)."""
        with self._lock:
            self._recording = False

        # Stop menu bar waveform updates (resets to flat line)
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
        """Quit (no-op for menu bar mode, handled by system)."""
        self.is_running = False

    def stop(self):
        """Stop and clean up menu bar icon."""
        self.is_running = False

        # Clean up menu bar icon
        if self.menubar_waveform:
            try:
                self.menubar_waveform.destroy()
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] Failed to destroy menu bar waveform: {e}")
