"""Windows desktop integration: Single instance mutex, high DPI, and system tray."""
import ctypes
from pathlib import Path
from PIL import Image
import pystray


def set_high_dpi_aware():
    """Enable Per-Monitor V2 High-DPI awareness on Windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class SingleInstance:
    """Ensures only one instance of the application runs at any time."""

    def __init__(self, app_id="Local\\ProScreenRecorder.Instance"):
        self.app_id = app_id
        self.mutex = None
        self.already_running = False

        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, False, self.app_id)
        last_error = ctypes.windll.kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            self.already_running = True

    def close(self):
        if self.mutex:
            ctypes.windll.kernel32.CloseHandle(self.mutex)
            self.mutex = None


def create_tray(icon_path: Path, on_open, on_quit):
    """Creates a system tray icon with Open and Exit options."""
    try:
        img = Image.open(icon_path)
    except Exception:
        img = Image.new("RGBA", (32, 32), (239, 68, 68, 255))

    menu = pystray.Menu(
        pystray.MenuItem("Mở giao diện", on_open, default=True),
        pystray.MenuItem("Thoát hoàn toàn", on_quit)
    )

    tray = pystray.Icon("ProScreenRecorder", img, "Pro Screen Recorder", menu)
    return tray


WDA_EXCLUDEFROMCAPTURE = 0x00000011


def exclude_from_capture(window):
    """
    Exclude a Tkinter / CustomTkinter window from Windows screen capture.
    The window remains visible and interactive to the user on screen,
    but is 100% invisible in the recorded video.
    """
    try:
        window.update_idletasks()
        hwnd_client = window.winfo_id()
        GA_ROOT = 2
        hwnd_top = ctypes.windll.user32.GetAncestor(hwnd_client, GA_ROOT)
        if not hwnd_top:
            hwnd_top = hwnd_client
        res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd_top, WDA_EXCLUDEFROMCAPTURE)
        return bool(res)
    except Exception:
        return False

