"""High-Performance Screen Recorder Engine for Windows."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from datetime import datetime

from audio_manager import AudioManager
from settings import Settings

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def ensure_input_desktop():
    """Ensure the calling thread is attached to the active input desktop."""
    try:
        hdesk = u32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            u32.SetThreadDesktop(hdesk)
    except Exception:
        pass


class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hCursor', wintypes.HANDLE),
        ('ptScreenPos', POINT)
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD)
    ]


class CursorRenderer:
    """Pro mouse cursor renderer with 100% reliable positioning, highlight halo, and click ripples."""

    def __init__(self):
        self.h_arrow = u32.LoadCursorW(0, 32512)
        # BGR: Gold/Yellow halo (0x0000E5FF)
        self.pen_halo = g32.CreatePen(0, 3, 0x0000E5FF)
        self.pen_lclick = g32.CreatePen(0, 3, 0x000000EF) # Red ripple
        self.pen_rclick = g32.CreatePen(0, 3, 0x00F87138) # Sky blue ripple
        self.brush_null = g32.GetStockObject(5) # NULL_BRUSH
        self.active_ripples = []
        self._was_l_down = False
        self._was_r_down = False

    def draw(self, hdc_mem, left, top, show_cursor, halo, click_ripple, excluded_rect):
        if not show_cursor:
            return

        pt = POINT()
        if not u32.GetCursorPos(ctypes.byref(pt)):
            return

        cur_x = pt.x - left
        cur_y = pt.y - top

        # Exclude if inside floating bar
        if excluded_rect:
            rx, ry, rw, rh = excluded_rect
            if rx <= pt.x <= rx + rw and ry <= pt.y <= ry + rh:
                return

        # Check clicks
        if click_ripple:
            l_down = bool(u32.GetAsyncKeyState(0x01) & 0x8000)
            r_down = bool(u32.GetAsyncKeyState(0x02) & 0x8000)
            if l_down and not self._was_l_down:
                self.active_ripples.append([cur_x, cur_y, 6, self.pen_lclick])
            if r_down and not self._was_r_down:
                self.active_ripples.append([cur_x, cur_y, 6, self.pen_rclick])
            self._was_l_down = l_down
            self._was_r_down = r_down

        # Draw ripples
        if self.active_ripples:
            old_brush = g32.SelectObject(hdc_mem, self.brush_null)
            next_ripples = []
            for r in self.active_ripples:
                rx, ry, radius, pen = r
                old_pen = g32.SelectObject(hdc_mem, pen)
                g32.Ellipse(hdc_mem, rx - radius, ry - radius, rx + radius, ry + radius)
                g32.SelectObject(hdc_mem, old_pen)
                if radius < 24:
                    r[2] += 4
                    next_ripples.append(r)
            self.active_ripples = next_ripples
            g32.SelectObject(hdc_mem, old_brush)

        # Draw halo (golden highlight circle around cursor)
        if halo:
            old_brush = g32.SelectObject(hdc_mem, self.brush_null)
            old_pen = g32.SelectObject(hdc_mem, self.pen_halo)
            g32.Ellipse(hdc_mem, cur_x - 18, cur_y - 18, cur_x + 18, cur_y + 18)
            g32.SelectObject(hdc_mem, old_pen)
            g32.SelectObject(hdc_mem, old_brush)

        # Draw actual cursor icon (query current cursor or fallback to arrow)
        ci = CURSORINFO()
        ci.cbSize = ctypes.sizeof(CURSORINFO)
        h_cur = None
        if u32.GetCursorInfo(ctypes.byref(ci)) and ci.hCursor:
            h_cur = ci.hCursor
        if not h_cur:
            h_cur = self.h_arrow

        u32.DrawIconEx(hdc_mem, cur_x, cur_y, h_cur, 0, 0, 0, 0, 3)

    def close(self):
        try:
            g32.DeleteObject(self.pen_halo)
            g32.DeleteObject(self.pen_lclick)
            g32.DeleteObject(self.pen_rclick)
        except Exception:
            pass


def find_ffmpeg():
    """Find FFmpeg binary path."""
    candidates = [
        Path(__file__).parent / "tools" / "ffmpeg.exe",
        Path(__file__).parent.parent / "tools" / "ffmpeg.exe",
        Path("C:/Users/Admin/AppData/Local/Programs/Ghi Âm Zalo PC/tools/ffmpeg.exe"),
        Path("C:/Users/Admin/AppData/Local/Programs/Ghi Âm Zalo PC/Source/tools/ffmpeg.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)

    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg

    # Check winget packages
    winget_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    for p in winget_dir.glob("**/ffmpeg.exe"):
        if p.is_file():
            return str(p)

    return "ffmpeg"


def detect_best_encoder(ffmpeg_path):
    """Test if h264_mf (hardware accelerated) works, otherwise fallback to libx264."""
    try:
        cmd = [
            ffmpeg_path, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", "64x64",
            "-pix_fmt", "bgra",
            "-r", "10",
            "-i", "-",
            "-c:v", "h264_mf",
            "-pix_fmt", "nv12",
            "-f", "null", "-"
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW
        )
        dummy_frame = b"\x00" * (64 * 64 * 4)
        proc.stdin.write(dummy_frame)
        proc.stdin.close()
        proc.wait(timeout=2.0)
        if proc.returncode == 0:
            return "h264_mf"
    except Exception:
        pass
    return "libx264"


class RecorderEngine:
    def __init__(self, settings: Settings, on_update_callback=None):
        self.settings = settings
        self.on_update = on_update_callback
        self.ffmpeg_path = find_ffmpeg()
        self.audio_mgr = AudioManager()

        self.state = "idle"  # idle, recording, paused, stopping
        self.start_time = 0.0
        self.paused_duration = 0.0
        self.pause_start = 0.0
        self.frames_captured = 0
        self.current_fps = 0.0

        self._record_thread = None
        self._stats_thread = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

        self.temp_video_path = None
        self.temp_audio_path = None
        self.final_output_path = None

        # Capture geometry
        self.capture_region = None  # None for full screen, or (left, top, width, height)
        self._excluded_rect_provider = None

    def set_excluded_rect_provider(self, provider):
        self._excluded_rect_provider = provider

    def set_region(self, region):
        """Set custom region: (left, top, width, height) or None for full screen."""
        if region:
            left, top, w, h = region
            # FFmpeg requires even dimensions (divisible by 2)
            w = (w // 2) * 2
            h = (h // 2) * 2
            self.capture_region = (left, top, max(2, w), max(2, h))
        else:
            self.capture_region = None

    def start(self):
        if self.state != "idle":
            return False

        ensure_input_desktop()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(self.settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        self.temp_video_path = out_dir / f"~temp_v_{timestamp}.mp4"
        self.temp_audio_path = out_dir / f"~temp_a_{timestamp}.wav"
        self.final_output_path = out_dir / f"REC_{timestamp}.mp4"

        # Determine geometry
        screen_w = u32.GetSystemMetrics(0)
        screen_h = u32.GetSystemMetrics(1)
        if self.capture_region:
            left, top, width, height = self.capture_region
        else:
            left, top = 0, 0
            width, height = screen_w, screen_h

        # Ensure width and height are even
        width = (width // 2) * 2
        height = (height // 2) * 2

        # Check resolution scaling preset
        out_w, out_h = width, height
        preset = getattr(self.settings, "resolution_preset", "Native")
        if preset == "720p" and (width > 1280 or height > 720):
            scale = min(1280 / width, 720 / height)
            out_w = (int(width * scale) // 2) * 2
            out_h = (int(height * scale) // 2) * 2
        elif preset == "1080p" and (width > 1920 or height > 1080):
            scale = min(1920 / width, 1080 / height)
            out_w = (int(width * scale) // 2) * 2
            out_h = (int(height * scale) // 2) * 2

        scale_filter = ["-vf", f"scale={out_w}:{out_h}"] if (out_w != width or out_h != height) else []

        # Start audio if enabled
        has_audio = False
        if self.settings.record_mic:
            try:
                mic_vol = getattr(self.settings, "mic_volume", 1.0)
                self.audio_mgr.start_recording(mic_index=self.settings.mic_device_index, volume=mic_vol)
                has_audio = True
            except Exception as e:
                print(f"Warning: Failed to start mic recording: {e}")

        # Detect encoder
        encoder = self.settings.encoder
        if encoder == "auto":
            encoder = detect_best_encoder(self.ffmpeg_path)

        fps = self.settings.fps
        bitrate = self.settings.get_bitrate()

        video_cmd = [
            self.ffmpeg_path, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "bgra",
            "-r", str(fps),
            "-i", "-",
            *scale_filter,
            "-c:v", encoder,
            *(["-preset", "ultrafast", "-tune", "zerolatency"] if encoder == "libx264" else []),
            "-b:v", bitrate,
            "-pix_fmt", "nv12" if encoder == "h264_mf" else "yuv420p",
            str(self.temp_video_path)
        ]

        try:
            v_proc = subprocess.Popen(
                video_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=NO_WINDOW
            )
        except Exception as e:
            if has_audio:
                self.audio_mgr.stop_and_save(self.temp_audio_path)
            raise RuntimeError(f"Failed to launch FFmpeg: {e}")

        self.state = "recording"
        self.start_time = time.perf_counter()
        self.paused_duration = 0.0
        self.pause_start = 0.0
        self.frames_captured = 0
        self._stop_event.clear()
        self._pause_event.clear()

        self._record_thread = threading.Thread(
            target=self._capture_loop,
            args=(v_proc, left, top, width, height, fps),
            daemon=True
        )
        self._record_thread.start()

        self._stats_thread = threading.Thread(target=self._stats_loop, daemon=True)
        self._stats_thread.start()
        return True

    def _capture_loop(self, v_proc, left, top, width, height, fps):
        ensure_input_desktop()

        hdc_screen = u32.GetDC(0)
        hdc_mem = g32.CreateCompatibleDC(hdc_screen)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        p_bits = ctypes.c_void_p()
        hbm = g32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(p_bits), 0, 0)
        g32.SelectObject(hdc_mem, hbm)

        cursor_renderer = CursorRenderer()
        target_interval = 1.0 / fps
        frame_bytes = width * height * 4
        record_cursor = self.settings.record_cursor
        mouse_halo = getattr(self.settings, "mouse_halo", True)
        mouse_click_ripple = getattr(self.settings, "mouse_click_ripple", True)

        try:
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    time.sleep(0.05)
                    continue

                t_frame_start = time.perf_counter()

                # BitBlt screen region to memory DC
                # 0x00CC0020 (SRCCOPY) | 0x40000000 (CAPTUREBLT for layered windows)
                g32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, 0x00CC0020 | 0x40000000)

                # Draw mouse cursor with halo & click ripple effects
                if record_cursor:
                    ex_rect = self._excluded_rect_provider() if self._excluded_rect_provider else None
                    cursor_renderer.draw(
                        hdc_mem, left, top,
                        show_cursor=True,
                        halo=mouse_halo,
                        click_ripple=mouse_click_ripple,
                        excluded_rect=ex_rect
                    )

                # Write raw BGRA frame to FFmpeg stdin
                buf = (ctypes.c_char * frame_bytes).from_address(p_bits.value)
                try:
                    v_proc.stdin.write(buf)
                    self.frames_captured += 1
                except (BrokenPipeError, OSError):
                    break

                # Sleep to maintain stable framerate
                elapsed = time.perf_counter() - t_frame_start
                sleep_left = target_interval - elapsed
                if sleep_left > 0.001:
                    time.sleep(sleep_left)

        finally:
            try:
                v_proc.stdin.close()
                v_proc.wait(timeout=5.0)
            except Exception:
                pass

            cursor_renderer.close()
            g32.DeleteObject(hbm)
            g32.DeleteDC(hdc_mem)
            u32.ReleaseDC(0, hdc_screen)

    def _stats_loop(self):
        last_frame_count = 0
        last_calc_time = time.perf_counter()

        while not self._stop_event.is_set():
            time.sleep(0.2)
            now = time.perf_counter()

            if self.state == "recording":
                elapsed = now - self.start_time - self.paused_duration
            elif self.state == "paused":
                elapsed = self.pause_start - self.start_time - self.paused_duration
            else:
                elapsed = 0.0

            # Calculate live FPS
            dt = now - last_calc_time
            if dt >= 0.5:
                df = self.frames_captured - last_frame_count
                self.current_fps = max(0.0, df / dt)
                last_frame_count = self.frames_captured
                last_calc_time = now

            # Calculate estimated size
            size_bytes = 0
            if self.temp_video_path and self.temp_video_path.is_file():
                try:
                    size_bytes = self.temp_video_path.stat().st_size
                except Exception:
                    pass

            mic_rms = self.audio_mgr.current_rms if self.settings.record_mic else 0.0

            if self.on_update:
                self.on_update({
                    "state": self.state,
                    "elapsed": max(0.0, elapsed),
                    "fps": round(self.current_fps, 1),
                    "size_bytes": size_bytes,
                    "mic_rms": mic_rms
                })

    def pause(self):
        if self.state == "recording":
            self.state = "paused"
            self.pause_start = time.perf_counter()
            self._pause_event.set()
            self.audio_mgr.pause()
            return True
        return False

    def resume(self):
        if self.state == "paused":
            now = time.perf_counter()
            self.paused_duration += (now - self.pause_start)
            self.state = "recording"
            self._pause_event.clear()
            self.audio_mgr.resume()
            return True
        return False

    def stop(self):
        if self.state not in ("recording", "paused"):
            return None

        self.state = "stopping"
        self._stop_event.set()
        self._pause_event.clear()

        if self._record_thread:
            self._record_thread.join(timeout=6.0)
            self._record_thread = None

        if self._stats_thread:
            self._stats_thread.join(timeout=2.0)
            self._stats_thread = None

        # Stop audio
        has_audio = False
        if self.settings.record_mic and self.temp_audio_path:
            has_audio = self.audio_mgr.stop_and_save(self.temp_audio_path)

        # Mux video and audio with FFmpeg
        final_file = self._mux_recording(has_audio)
        self.state = "idle"
        return final_file

    def _mux_recording(self, has_audio):
        if not self.temp_video_path or not self.temp_video_path.is_file():
            self._clean_temp_files()
            return None

        final_path = self.final_output_path

        if has_audio and self.temp_audio_path and self.temp_audio_path.is_file():
            mux_cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(self.temp_video_path),
                "-i", str(self.temp_audio_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(final_path)
            ]
        else:
            mux_cmd = [
                self.ffmpeg_path, "-y",
                "-i", str(self.temp_video_path),
                "-c:v", "copy",
                "-movflags", "+faststart",
                str(final_path)
            ]

        try:
            subprocess.run(
                mux_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                creationflags=NO_WINDOW
            )
            self._clean_temp_files()
            if final_path.is_file():
                return str(final_path)
        except Exception as e:
            print(f"Error during muxing: {e}")
            # If muxing failed, fallback to keeping temp_video_path
            if self.temp_video_path.is_file():
                try:
                    shutil.move(str(self.temp_video_path), str(final_path))
                    return str(final_path)
                except Exception:
                    pass
        return None

    def _clean_temp_files(self):
        try:
            if self.temp_video_path and self.temp_video_path.is_file():
                self.temp_video_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if self.temp_audio_path and self.temp_audio_path.is_file():
                self.temp_audio_path.unlink(missing_ok=True)
        except Exception:
            pass
