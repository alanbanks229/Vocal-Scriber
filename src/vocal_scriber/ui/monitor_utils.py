"""Multi-monitor detection utilities for cross-platform support."""
import sys
import platform


def get_monitor_geometry(monitor_spec='active'):
    """
    Get monitor geometry based on specification.

    Args:
        monitor_spec: 'active', 'primary', or integer index (0, 1, 2, etc.)

    Returns:
        dict: {'x': int, 'y': int, 'width': int, 'height': int}
              or None if detection fails
    """
    if monitor_spec == 'active':
        return get_active_monitor()
    elif monitor_spec == 'primary':
        return get_primary_monitor()
    elif isinstance(monitor_spec, int) or (isinstance(monitor_spec, str) and monitor_spec.isdigit()):
        index = int(monitor_spec)
        return get_monitor_by_index(index)
    else:
        return get_primary_monitor()


def get_active_monitor():
    """
    Get the monitor containing the currently focused window.
    Falls back to primary monitor if detection fails.

    Returns:
        dict: {'x': int, 'y': int, 'width': int, 'height': int}
    """
    system = platform.system()

    try:
        if system == 'Darwin':
            return _get_active_monitor_macos()
        elif system == 'Linux':
            return _get_active_monitor_linux()
        elif system == 'Windows':
            return _get_active_monitor_windows()
    except Exception:
        pass

    # Fallback to primary monitor
    return get_primary_monitor()


def get_primary_monitor():
    """
    Get the primary/main monitor.

    Returns:
        dict: {'x': int, 'y': int, 'width': int, 'height': int}
    """
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return {'x': 0, 'y': 0, 'width': width, 'height': height}
    except Exception:
        # Ultimate fallback
        return {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}


def get_monitor_by_index(index):
    """
    Get monitor by index (0, 1, 2, etc.).

    Args:
        index: Monitor index (0-based)

    Returns:
        dict: {'x': int, 'y': int, 'width': int, 'height': int}
              or None if index is out of range
    """
    try:
        from screeninfo import get_monitors
        monitors = get_monitors()
        if 0 <= index < len(monitors):
            mon = monitors[index]
            return {
                'x': mon.x,
                'y': mon.y,
                'width': mon.width,
                'height': mon.height
            }
    except Exception:
        pass

    # If index is 0 or we failed, return primary monitor
    if index == 0:
        return get_primary_monitor()

    return None


def _get_active_monitor_macos():
    """Get active monitor on macOS using Cocoa APIs."""
    try:
        from Cocoa import NSWorkspace, NSScreen

        # Get the active application
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.activeApplication()

        if active_app:
            # Get all screens
            screens = NSScreen.screens()

            # Try to find which screen contains the active window
            # Since we can't easily get window bounds, we'll use mouse position
            from Cocoa import NSEvent
            mouse_location = NSEvent.mouseLocation()

            for screen in screens:
                frame = screen.frame()
                # Convert from Cocoa coordinates (origin at bottom-left)
                screen_x = int(frame.origin.x)
                screen_y = int(frame.origin.y)
                screen_width = int(frame.size.width)
                screen_height = int(frame.size.height)

                # Check if mouse is on this screen
                if (screen_x <= mouse_location.x < screen_x + screen_width and
                    screen_y <= mouse_location.y < screen_y + screen_height):
                    # Convert to top-left origin for consistency
                    # Get the main screen height for conversion
                    main_screen_height = int(screens[0].frame().size.height)
                    converted_y = main_screen_height - screen_y - screen_height

                    return {
                        'x': screen_x,
                        'y': converted_y,
                        'width': screen_width,
                        'height': screen_height
                    }

        # Fallback: return main screen
        main_screen = NSScreen.mainScreen()
        frame = main_screen.frame()
        return {
            'x': int(frame.origin.x),
            'y': 0,
            'width': int(frame.size.width),
            'height': int(frame.size.height)
        }
    except Exception:
        return None


def _get_active_monitor_linux():
    """Get active monitor on Linux using xdotool and screeninfo."""
    try:
        import subprocess
        from screeninfo import get_monitors

        # Get active window position using xdotool
        result = subprocess.run(
            ['xdotool', 'getactivewindow', 'getwindowgeometry'],
            capture_output=True,
            text=True,
            timeout=1
        )

        if result.returncode == 0:
            # Parse output to get window position
            # Format: "Position: X,Y (screen: N)"
            for line in result.stdout.split('\n'):
                if 'Position:' in line:
                    pos_str = line.split('Position:')[1].split('(')[0].strip()
                    x, y = map(int, pos_str.split(','))

                    # Find which monitor contains this position
                    monitors = get_monitors()
                    for mon in monitors:
                        if (mon.x <= x < mon.x + mon.width and
                            mon.y <= y < mon.y + mon.height):
                            return {
                                'x': mon.x,
                                'y': mon.y,
                                'width': mon.width,
                                'height': mon.height
                            }

        return None
    except Exception:
        return None


def _get_active_monitor_windows():
    """Get active monitor on Windows using Windows API."""
    try:
        import ctypes
        from ctypes import wintypes
        from screeninfo import get_monitors

        # Get foreground window
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()

        if hwnd:
            # Get window rect
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))

            # Get window center point
            center_x = (rect.left + rect.right) // 2
            center_y = (rect.top + rect.bottom) // 2

            # Find which monitor contains this point
            monitors = get_monitors()
            for mon in monitors:
                if (mon.x <= center_x < mon.x + mon.width and
                    mon.y <= center_y < mon.y + mon.height):
                    return {
                        'x': mon.x,
                        'y': mon.y,
                        'width': mon.width,
                        'height': mon.height
                    }

        return None
    except Exception:
        return None
