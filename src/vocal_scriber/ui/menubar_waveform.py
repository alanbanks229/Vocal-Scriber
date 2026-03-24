"""macOS menu bar waveform visualization."""
import sys
from collections import deque
import objc
from Cocoa import NSObject


class MenuBarWaveform(NSObject):
    """
    Menu bar icon with live waveform visualization.

    Displays a 30-bar waveform in the macOS menu bar that updates
    in real-time at 30 FPS during recording. Uses NSStatusBar API for native integration.
    """

    def initWithConfig_audioLevelQueue_(self, config, audio_level_queue):
        """
        Initialize menu bar waveform (Objective-C style initializer).

        This method follows PyObjC conventions for NSObject subclasses.
        The trailing underscores indicate it takes two arguments.

        Args:
            config: Configuration object with GUI settings
            audio_level_queue: Queue to receive audio RMS levels (shared with window)

        Returns:
            self if successful, None if initialization failed
        """
        self = objc.super(MenuBarWaveform, self).init()
        if self is None:
            return None

        if sys.platform != 'darwin':
            raise RuntimeError("MenuBarWaveform is only supported on macOS")

        self.config = config
        self.audio_level_queue = audio_level_queue
        self.audio_buffer = deque(maxlen=30)  # Store last 30 levels for menu bar
        self.status_item = None
        self.update_timer = None
        self.is_recording = False

        # Menu-related instance variables
        self.menu = None  # NSMenu instance
        self.device_menu_items = []  # Track device menu items
        self.current_device_index = None  # Track selected device
        self.device_change_callback = None  # Callback to notify main app of device change
        self.quit_callback = None  # Callback to quit the app

        # Initialize buffer with zeros (flat line when idle)
        for _ in range(30):
            self.audio_buffer.append(0.0)

        # Create status bar item
        self._create_status_item()

        # CRITICAL: Must return self for PyObjC initializers!
        return self

    def _create_status_item(self):
        """Create NSStatusItem in menu bar."""
        try:
            if self.config.debug:
                print("[DEBUG] MenuBarWaveform: Importing Cocoa...")
            from Cocoa import NSStatusBar, NSVariableStatusItemLength

            if self.config.debug:
                print("[DEBUG] MenuBarWaveform: Creating status bar item...")
            status_bar = NSStatusBar.systemStatusBar()
            self.status_item = status_bar.statusItemWithLength_(NSVariableStatusItemLength)

            if self.config.debug:
                print("[DEBUG] MenuBarWaveform: Updating initial icon...")
            # Set initial icon (flat line - no audio)
            self._update_icon()

            if self.config.debug:
                print("[DEBUG] MenuBarWaveform: Creating menu...")
            # Create dropdown menu
            self._create_menu()

            if self.config.debug:
                print("[DEBUG] MenuBarWaveform: Setting tooltip...")
            # Set tooltip
            button = self.status_item.button()
            if button:
                button.setToolTip_("Vocal-Scriber")

            if self.config.debug:
                print("[DEBUG] Menu bar waveform icon created")
        except ImportError as e:
            # PyObjC not installed - this should be caught earlier but just in case
            if self.config.debug:
                print(f"[DEBUG] Cocoa import failed: {e}")
            raise ImportError("PyObjC not installed. Run: pip install pyobjc-framework-Cocoa") from e
        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] Failed to create menu bar icon: {e}")
            raise

    def _update_icon(self):
        """Update menu bar icon with current waveform."""
        # Drain queue and update buffer
        try:
            while not self.audio_level_queue.empty():
                level = self.audio_level_queue.get_nowait()
                self.audio_buffer.append(level)
        except:
            pass

        # Normalize levels (same scaling as waveform window)
        # RMS values typically 0.0 - 0.3 for speech, amplify for better visualization
        normalized_levels = [min(level * 10.0, 1.0) for level in self.audio_buffer]

        # Generate icon image
        icon = self._generate_waveform_icon(normalized_levels)

        # Update status item
        if self.status_item and icon:
            self.status_item.button().setImage_(icon)

    def _generate_waveform_icon(self, audio_levels, width=60, height=22):
        """
        Generate menu bar waveform icon from audio levels.

        Creates a monochrome template image with vertical bars representing
        audio levels. Template mode ensures the icon automatically adapts
        to light/dark mode.

        Args:
            audio_levels: List of 30 normalized levels (0.0-1.0)
            width: Icon width in pixels (default 60)
            height: Icon height in pixels (default 22, menu bar height)

        Returns:
            NSImage with waveform visualization
        """
        try:
            from Cocoa import NSImage, NSColor, NSRect, NSBezierPath
            from Foundation import NSMakeRect

            # Create image
            image = NSImage.alloc().initWithSize_((width, height))
            image.lockFocus()

            # Debug logging for icon generation (only log once to avoid spam)
            if self.config.debug and not hasattr(self, '_logged_icon_gen'):
                self._logged_icon_gen = True
                print(f"[DEBUG] Generated menu bar icon: {width}x{height}px, {len(audio_levels)} bars")
                print(f"[DEBUG] Audio levels range: {min(audio_levels):.3f} - {max(audio_levels):.3f}")

            # Draw waveform bars
            bar_count = len(audio_levels)
            bar_width = width / bar_count
            center_y = height / 2.0

            for i, level in enumerate(audio_levels):
                # Calculate bar height with minimum baseline for visibility
                # Minimum of 2 pixels ensures icon is always visible even when idle
                min_bar_height = 1.0
                calculated_height = level * (height / 2.0) * 0.9
                bar_height = max(min_bar_height, calculated_height)
                x = i * bar_width

                # Create vertical bar centered at middle
                # Bar width is 60% of available space to leave gaps between bars
                bar_rect_width = bar_width * 0.6

                # Draw bar extending from center upward and downward
                top_rect = NSMakeRect(x, center_y, bar_rect_width, bar_height)
                bottom_rect = NSMakeRect(x, center_y - bar_height, bar_rect_width, bar_height)

                # Fill with black (will be inverted by template mode)
                NSColor.blackColor().set()
                NSBezierPath.fillRect_(top_rect)
                NSBezierPath.fillRect_(bottom_rect)

            image.unlockFocus()

            # Enable template mode - icon will automatically adapt to menu bar appearance
            # (dark in light mode, light in dark mode)
            image.setTemplate_(True)

            return image

        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] Failed to generate waveform icon: {e}")
            return None

    def start_recording(self):
        """Start updating icon during recording (thread-safe)."""
        # Dispatch to main thread if called from background thread
        from Foundation import NSThread
        if NSThread.isMainThread():
            self.startRecordingOnMainThread_(None)
        else:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                'startRecordingOnMainThread:',
                None,
                False
            )

    def startRecordingOnMainThread_(self, arg):
        """Internal: Start recording (must be called on main thread)."""
        if self.is_recording:
            return

        self.is_recording = True
        self._start_update_loop()

        if self.config.debug:
            print("[DEBUG] Menu bar waveform updates started")

    def stop_recording(self):
        """Stop updating icon and reset to flat line (thread-safe)."""
        # Dispatch to main thread if called from background thread
        from Foundation import NSThread
        if NSThread.isMainThread():
            self.stopRecordingOnMainThread_(None)
        else:
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                'stopRecordingOnMainThread:',
                None,
                False
            )

    def stopRecordingOnMainThread_(self, arg):
        """Internal: Stop recording (must be called on main thread)."""
        if not self.is_recording:
            return

        self.is_recording = False

        # Stop update timer
        if self.update_timer:
            self.update_timer.invalidate()
            self.update_timer = None

        # Clear buffer and show flat line (idle state)
        self.audio_buffer.clear()
        for _ in range(30):
            self.audio_buffer.append(0.0)
        self._update_icon()

        if self.config.debug:
            print("[DEBUG] Menu bar waveform updates stopped")

    def _start_update_loop(self):
        """Start update timer at 30 FPS."""
        if not self.is_recording:
            return

        try:
            from Foundation import NSTimer

            # Update icon with current audio levels
            self._update_icon()

            # Schedule next update
            # 0.033 seconds = ~30 FPS (smooth animation)
            self.update_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.033,
                self,
                'performUpdate:',
                None,
                False
            )
        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] Failed to schedule menu bar update: {e}")

    def performUpdate_(self, timer):
        """
        Timer callback to update icon.

        This method is called by NSTimer and follows Objective-C naming conventions.
        The trailing underscore indicates it takes one argument (the timer).
        """
        if self.is_recording:
            self._start_update_loop()

    def checkShouldQuit_(self, timer):
        """
        Timer callback to check if app should quit.

        Called periodically by NSTimer to check if the keyboard thread has died
        or the app has been signaled to quit. If so, stops the NSApplication run loop.
        """
        # This is checked by the macOS runtime - if the keyboard thread dies
        # or the running flag is set to False, the app will call stop() on us,
        # which will then call NSApplication.sharedApplication().stop_()
        pass

    def _create_menu(self):
        """Create dropdown menu for microphone selection."""
        try:
            from Cocoa import NSMenu, NSMenuItem
            import sounddevice as sd

            # Create menu
            self.menu = NSMenu.alloc().init()

            # Get all input devices
            devices = sd.query_devices()
            input_devices = []
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    input_devices.append({
                        'index': i,
                        'name': device['name'],
                        'is_default': i == sd.default.device[0]
                    })

            # Add microphone menu items
            for device_info in input_devices:
                menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    device_info['name'],
                    'selectMicrophone:',
                    ''
                )
                menu_item.setTarget_(self)
                menu_item.setTag_(device_info['index'])  # Store device index in tag

                # Set checkmark if this is the current device
                if self.current_device_index == device_info['index']:
                    menu_item.setState_(1)  # NSControlStateValueOn

                self.menu.addItem_(menu_item)
                self.device_menu_items.append(menu_item)

            # Add separator
            self.menu.addItem_(NSMenuItem.separatorItem())

            # Add quit option
            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                'Quit Vocal-Scriber',
                'quitApp:',
                'q'
            )
            quit_item.setTarget_(self)
            self.menu.addItem_(quit_item)

            # Attach menu to status item
            self.status_item.setMenu_(self.menu)

            if self.config.debug:
                print(f"[DEBUG] Menu bar menu created with {len(input_devices)} microphones")

        except Exception as e:
            if self.config.debug:
                print(f"[DEBUG] Failed to create menu: {e}")

    def selectMicrophone_(self, sender):
        """
        Handle microphone selection from menu.

        This method is called by NSMenuItem and follows Objective-C naming conventions.
        The trailing underscore indicates it takes one argument (the sender).
        """
        device_index = sender.tag()

        if self.config.debug:
            import sounddevice as sd
            device_info = sd.query_devices(device_index)
            print(f"[DEBUG] Menu: Selected microphone {device_index}: {device_info['name']}")

        # Update checkmarks
        for item in self.device_menu_items:
            if item.tag() == device_index:
                item.setState_(1)  # Check
            else:
                item.setState_(0)  # Uncheck

        # Store current device
        self.current_device_index = device_index

        # Notify main app to switch device
        if self.device_change_callback:
            self.device_change_callback(device_index)

    def quitApp_(self, sender):
        """
        Handle quit menu item.

        This method is called by NSMenuItem and follows Objective-C naming conventions.
        """
        if self.config.debug:
            print("[DEBUG] Menu: Quit selected")

        # Call quit callback if set
        if hasattr(self, 'quit_callback') and self.quit_callback:
            self.quit_callback()
        else:
            # Fallback: exit the app
            import sys
            sys.exit(0)

    def set_current_device(self, device_index):
        """Set the currently selected device and update checkmarks."""
        self.current_device_index = device_index

        # Update checkmarks in menu if menu exists
        if self.menu and self.device_menu_items:
            for item in self.device_menu_items:
                if item.tag() == device_index:
                    item.setState_(1)
                else:
                    item.setState_(0)

    def destroy(self):
        """Clean up status item, timer, and stop NSApplication if running."""
        # Stop update timer
        if self.update_timer:
            self.update_timer.invalidate()
            self.update_timer = None

        # Stop NSApplication run loop if it's running
        try:
            from Cocoa import NSApplication
            app = NSApplication.sharedApplication()
            if app.isRunning():
                app.stop_(None)

                # Post a dummy event to wake up the run loop so it processes the stop
                from Cocoa import NSEvent, NSApplicationDefined
                from Foundation import NSDate
                event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                    NSApplicationDefined,
                    (0, 0),
                    0,
                    NSDate.timeIntervalSinceReferenceDate(NSDate.date()),
                    0,
                    None,
                    0,
                    0,
                    0
                )
                app.postEvent_atStart_(event, True)
        except:
            pass

        # Remove status bar item
        if self.status_item:
            try:
                from Cocoa import NSStatusBar
                NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
                self.status_item = None

                if self.config.debug:
                    print("[DEBUG] Menu bar icon removed")
            except Exception as e:
                if self.config.debug:
                    print(f"[DEBUG] Failed to remove menu bar icon: {e}")
