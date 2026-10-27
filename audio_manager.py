"""Audio Manager: Device enumeration, live microphone recording, and VU meter."""
import math
import struct
import threading
import time
import wave
from pathlib import Path
import pyaudiowpatch as pyaudio


class AudioManager:
    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.recording = False
        self.paused = False
        self._thread = None
        self._stop_event = threading.Event()
        self.current_rms = 0.0  # Normalized 0.0 - 1.0 for UI VU meter
        self.frames = []
        self.sample_rate = 44100
        self.channels = 1
        self.stream = None

    def list_microphones(self):
        devices = []
        try:
            count = self.pa.get_device_count()
            for i in range(count):
                info = self.pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0 and not info.get("isLoopbackDevice", False):
                    devices.append({
                        "index": i,
                        "name": info.get("name", f"Microphone {i}"),
                        "channels": min(2, info.get("maxInputChannels", 1)),
                        "default_rate": int(info.get("defaultSampleRate", 44100))
                    })
        except Exception:
            pass
        return devices

    def list_speakers(self):
        devices = []
        try:
            for loopback in self.pa.get_loopback_device_info_generator():
                devices.append({
                    "index": loopback["index"],
                    "name": loopback["name"],
                    "channels": loopback["maxInputChannels"],
                    "default_rate": int(loopback["defaultSampleRate"])
                })
        except Exception:
            pass
        return devices

    def start_recording(self, mic_index=None, sample_rate=44100, volume=1.0):
        self.frames = []
        self.current_rms = 0.0
        self.paused = False
        self.volume = volume
        self._stop_event.clear()

        try:
            if mic_index is None:
                default_info = self.pa.get_default_input_device_info()
                mic_index = default_info["index"]
                self.sample_rate = int(default_info.get("defaultSampleRate", sample_rate))
                self.channels = min(2, default_info.get("maxInputChannels", 1))
            else:
                info = self.pa.get_device_info_by_index(mic_index)
                self.sample_rate = int(info.get("defaultSampleRate", sample_rate))
                self.channels = min(2, info.get("maxInputChannels", 1))

            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=mic_index,
                frames_per_buffer=1024
            )
        except Exception as e:
            self.stream = None
            raise RuntimeError(f"Cannot initialize microphone: {e}")

        self.recording = True
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def _record_loop(self):
        while not self._stop_event.is_set():
            if self.paused:
                self.current_rms = 0.0
                time.sleep(0.05)
                continue
            try:
                data = self.stream.read(1024, exception_on_overflow=False)
                if getattr(self, "volume", 1.0) != 1.0:
                    try:
                        import numpy as np
                        arr = np.frombuffer(data, dtype=np.int16)
                        data = np.clip(arr * self.volume, -32768, 32767).astype(np.int16).tobytes()
                    except Exception:
                        pass
                self.frames.append(data)
                self._calculate_rms(data)
            except Exception:
                break
        self.current_rms = 0.0

    def _calculate_rms(self, data):
        try:
            count = len(data) // 2
            if count == 0:
                self.current_rms = 0.0
                return
            shorts = struct.unpack(f"{count}h", data)
            sum_squares = sum(s * s for s in shorts)
            rms = math.sqrt(sum_squares / count)
            # Map 0 - 32768 to 0.0 - 1.0 with a logarithmic perception curve
            if rms > 10:
                norm = min(1.0, math.log10(rms) / 4.2)
                self.current_rms = max(0.0, norm)
            else:
                self.current_rms = 0.0
        except Exception:
            self.current_rms = 0.0

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop_and_save(self, wav_path):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        self.recording = False
        self.paused = False
        self.current_rms = 0.0

        if not self.frames:
            return False

        try:
            wf = wave.open(str(wav_path), "wb")
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # paInt16
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(self.frames))
            wf.close()
            return True
        except Exception:
            return False

    def close(self):
        if self.recording:
            self.stop_and_save(Path.home() / "temp_abort.wav")
        try:
            self.pa.terminate()
        except Exception:
            pass
