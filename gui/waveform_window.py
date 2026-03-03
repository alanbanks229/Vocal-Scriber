"""Tkinter-based waveform visualization window."""
import tkinter as tk
from collections import deque
import colorsys


class WaveformWindow:
    """Real-time waveform visualization window using tkinter."""

    def __init__(self, config, audio_level_queue):
        """
        Initialize waveform window.

        Args:
            config: Configuration object with GUI settings
            audio_level_queue: Queue to receive audio RMS levels
        """
        self.config = config
        self.audio_level_queue = audio_level_queue
        self.root = None
        self.canvas = None
        self.bars = []
        self.audio_buffer = deque(maxlen=60)  # Store last 60 audio levels
        self.is_visible = False
        self.update_job = None

        # Initialize buffer with zeros
        for _ in range(60):
            self.audio_buffer.append(0.0)

        # Theme settings
        if config.gui_theme == 'dark':
            self.bg_color = '#1a1a1a'
            self.text_color = '#ffffff'
            self.zero_line_color = '#404040'
        else:  # light theme
            self.bg_color = '#f0f0f0'
            self.text_color = '#000000'
            self.zero_line_color = '#c0c0c0'

    def create_window(self):
        """Create and configure the tkinter window."""
        self.root = tk.Tk()
        self.root.title("Vocal Scriber")

        # Configure window appearance
        self.root.overrideredirect(True)  # Frameless window
        self.root.attributes('-topmost', True)  # Always on top
        self.root.attributes('-alpha', self.config.gui_opacity)

        # Set window size
        self.root.geometry(f"{self.config.gui_width}x{self.config.gui_height}")

        # Calculate window position
        self._position_window()

        # Create canvas for waveform
        self.canvas = tk.Canvas(
            self.root,
            width=self.config.gui_width,
            height=self.config.gui_height,
            bg=self.bg_color,
            highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Create visual elements
        self._create_waveform_bars()
        self._create_zero_line()
        self._create_status_text()

        # Configure macOS-specific behavior (prevent focus stealing)
        self._configure_macos_window_behavior()

        # Start hidden
        self.root.withdraw()

    def _configure_macos_window_behavior(self):
        """
        Configure macOS-specific window behavior to prevent focus stealing.

        Uses Cocoa APIs to set the window to float above all applications
        without stealing focus or activating the app.
        """
        import sys
        if sys.platform != 'darwin':
            return

        try:
            from Cocoa import NSApp, NSFloatingWindowLevel
            from Cocoa import NSWindowCollectionBehaviorCanJoinAllSpaces
            from Cocoa import NSWindowCollectionBehaviorStationary
            from Cocoa import NSWindowCollectionBehaviorFullScreenAuxiliary

            # Get the NSWindow object from tkinter's window ID
            # tkinter stores the window ID in root.winfo_id()
            window_id = self.root.winfo_id()

            # Get NSApp and find our window
            app = NSApp()
            ns_window = None

            for window in app.windows():
                if window.windowNumber() == window_id:
                    ns_window = window
                    break

            if ns_window:
                # Set window level to float above everything, including full-screen apps
                ns_window.setLevel_(NSFloatingWindowLevel)

                # Configure collection behavior:
                # - CanJoinAllSpaces: appears on all desktops/spaces
                # - Stationary: doesn't participate in Spaces animations
                # - FullScreenAuxiliary: can appear over full-screen windows
                behavior = (NSWindowCollectionBehaviorCanJoinAllSpaces |
                           NSWindowCollectionBehaviorStationary |
                           NSWindowCollectionBehaviorFullScreenAuxiliary)
                ns_window.setCollectionBehavior_(behavior)

                # Prevent window from activating when shown
                ns_window.setIgnoresMouseEvents_(False)  # Still want mouse events

                if self.config.debug:
                    print("[DEBUG] macOS window behavior configured for no-focus overlay")
            else:
                if self.config.debug:
                    print("[DEBUG] Could not find NSWindow for tkinter window")
        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] Could not configure macOS window behavior: {e}")

    def _position_window(self):
        """Position window based on configuration."""
        from gui.monitor_utils import get_monitor_geometry

        # Get target monitor geometry
        monitor = get_monitor_geometry(self.config.gui_monitor)
        if monitor is None:
            monitor = get_monitor_geometry('primary')

        mon_x = monitor['x']
        mon_y = monitor['y']
        mon_width = monitor['width']
        mon_height = monitor['height']

        # Calculate base position based on gui_position setting
        position = self.config.gui_position
        if position == 'bottom-center':
            x = mon_x + (mon_width - self.config.gui_width) // 2
            y = mon_y + mon_height - self.config.gui_height - 50
        elif position == 'top-center':
            x = mon_x + (mon_width - self.config.gui_width) // 2
            y = mon_y + 50
        elif position == 'bottom-left':
            x = mon_x + 50
            y = mon_y + mon_height - self.config.gui_height - 50
        elif position == 'bottom-right':
            x = mon_x + mon_width - self.config.gui_width - 50
            y = mon_y + mon_height - self.config.gui_height - 50
        else:  # default to bottom-center
            x = mon_x + (mon_width - self.config.gui_width) // 2
            y = mon_y + mon_height - self.config.gui_height - 50

        # Apply offsets
        x += self.config.gui_offset_x
        y += self.config.gui_offset_y

        self.root.geometry(f"+{x}+{y}")

    def _create_waveform_bars(self):
        """Create 60 vertical bars for waveform visualization."""
        bar_count = 60
        bar_width = (self.config.gui_width - 20) / bar_count  # Leave margins
        bar_spacing = bar_width * 0.2
        bar_width = bar_width * 0.8

        # Waveform area height (leave space for text)
        waveform_height = self.config.gui_height - 30
        center_y = waveform_height // 2

        self.bars = []
        for i in range(bar_count):
            x = 10 + i * (bar_width + bar_spacing)
            # Create bar as thin rectangle (starts at zero height)
            bar = self.canvas.create_rectangle(
                x, center_y,
                x + bar_width, center_y,
                fill='#00ff00',
                outline=''
            )
            self.bars.append(bar)

    def _create_zero_line(self):
        """Create horizontal zero reference line."""
        waveform_height = self.config.gui_height - 30
        center_y = waveform_height // 2

        self.canvas.create_line(
            10, center_y,
            self.config.gui_width - 10, center_y,
            fill=self.zero_line_color,
            width=1
        )

    def _create_status_text(self):
        """Create status text at bottom of window."""
        text_y = self.config.gui_height - 15

        self.status_text = self.canvas.create_text(
            self.config.gui_width // 2,
            text_y,
            text="🎤 RECORDING (Press F9)",
            fill=self.text_color,
            font=('Arial', 10, 'bold')
        )

    def show(self):
        """Show the window and start updating."""
        if self.root and not self.is_visible:
            self.is_visible = True
            self.root.deiconify()
            # Don't call lift() - causes activation and focus stealing
            # Don't reset -topmost - already configured in create_window()
            self._start_update_loop()

    def hide(self):
        """Hide the window and stop updating."""
        if self.root and self.is_visible:
            self.is_visible = False
            if self.update_job:
                self.root.after_cancel(self.update_job)
                self.update_job = None
            self.root.withdraw()

            # Clear audio buffer
            self.audio_buffer.clear()
            for _ in range(60):
                self.audio_buffer.append(0.0)

    def _start_update_loop(self):
        """Start the update loop at ~30 FPS."""
        if self.is_visible:
            self.update_waveform()
            self.update_job = self.root.after(33, self._start_update_loop)  # ~30 FPS

    def update_waveform(self):
        """Update waveform visualization with latest audio data."""
        # Drain queue and add to buffer
        try:
            while not self.audio_level_queue.empty():
                level = self.audio_level_queue.get_nowait()
                self.audio_buffer.append(level)
        except:
            pass

        # Update bar heights and colors
        waveform_height = self.config.gui_height - 30
        center_y = waveform_height // 2
        max_bar_height = center_y - 5  # Leave small margin

        for i, bar in enumerate(self.bars):
            # Get audio level from buffer
            if i < len(self.audio_buffer):
                level = self.audio_buffer[i]
            else:
                level = 0.0

            # Normalize and scale (RMS values typically 0.0 - 0.3 for speech)
            # Amplify for better visualization
            normalized = min(level * 10.0, 1.0)

            # Calculate bar height
            bar_height = int(normalized * max_bar_height)

            # Calculate color based on level (green -> yellow -> orange -> red)
            color = self._get_color_for_level(normalized)

            # Update bar coordinates
            y1 = center_y - bar_height
            y2 = center_y + bar_height

            self.canvas.coords(bar, self.canvas.coords(bar)[0], y1,
                             self.canvas.coords(bar)[2], y2)
            self.canvas.itemconfig(bar, fill=color)

    def _get_color_for_level(self, level):
        """
        Get color based on audio level using gradient.

        Args:
            level: Normalized level (0.0 - 1.0)

        Returns:
            str: Hex color code
        """
        if level < 0.25:
            # Green
            return '#00ff00'
        elif level < 0.5:
            # Green to Yellow
            t = (level - 0.25) / 0.25
            r = int(t * 255)
            return f'#{r:02x}ff00'
        elif level < 0.75:
            # Yellow to Orange
            t = (level - 0.5) / 0.25
            g = int((1 - t * 0.5) * 255)
            return f'#ff{g:02x}00'
        else:
            # Orange to Red
            t = (level - 0.75) / 0.25
            g = int((0.5 - t * 0.5) * 255)
            return f'#ff{g:02x}00'

    def destroy(self):
        """Destroy the window."""
        try:
            if self.update_job:
                self.root.after_cancel(self.update_job)
            if self.root:
                self.root.destroy()
        except:
            pass
