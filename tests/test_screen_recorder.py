"""Unit tests for Pro Screen Recorder."""
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from settings import Settings
from recorder_engine import find_ffmpeg, detect_best_encoder, RecorderEngine
from audio_manager import AudioManager
from desktop_support import SingleInstance, exclude_from_capture


class TestSettings(unittest.TestCase):
    def test_default_values(self):
        s = Settings()
        self.assertIn(s.fps, (30, 60))
        self.assertEqual(s.get_bitrate(), "6M")
        self.assertTrue(s.record_cursor)
        self.assertTrue(s.record_mic)

    def test_bitrate_mapping(self):
        s = Settings()
        s.quality = "Standard"
        self.assertEqual(s.get_bitrate(), "3M")
        s.quality = "Ultra"
        self.assertEqual(s.get_bitrate(), "12M")


class TestFFmpegDetection(unittest.TestCase):
    def test_find_ffmpeg(self):
        path = find_ffmpeg()
        self.assertTrue(len(path) > 0)

    def test_detect_best_encoder(self):
        path = find_ffmpeg()
        enc = detect_best_encoder(path)
        self.assertIn(enc, ("h264_mf", "libx264"))


class TestAudioManager(unittest.TestCase):
    def test_device_enumeration(self):
        mgr = AudioManager()
        try:
            mics = mgr.list_microphones()
            self.assertIsInstance(mics, list)
            # Should have at least one mic on this machine (Microphone 2- ME6S)
            self.assertGreater(len(mics), 0)
        finally:
            mgr.close()

    def test_rms_calculation(self):
        mgr = AudioManager()
        try:
            # Silence
            silence = b"\x00" * 2048
            mgr._calculate_rms(silence)
            self.assertEqual(mgr.current_rms, 0.0)

            # Loud tone (full amplitude)
            import struct
            loud_samples = [30000 if i % 2 == 0 else -30000 for i in range(1024)]
            loud_bytes = struct.pack(f"{len(loud_samples)}h", *loud_samples)
            mgr._calculate_rms(loud_bytes)
            self.assertGreater(mgr.current_rms, 0.5)
        finally:
            mgr.close()


class TestRecorderEngine(unittest.TestCase):
    def test_region_formatting(self):
        s = Settings()
        engine = RecorderEngine(s)
        try:
            # Odd dimensions must be rounded to even
            engine.set_region((10, 20, 1001, 799))
            self.assertEqual(engine.capture_region, (10, 20, 1000, 798))

            engine.set_region(None)
            self.assertIsNone(engine.capture_region)
        finally:
            engine.audio_mgr.close()

    def test_state_flow(self):
        s = Settings()
        engine = RecorderEngine(s)
        try:
            self.assertEqual(engine.state, "idle")
            # Should return False if not recording
            self.assertFalse(engine.pause())
            self.assertFalse(engine.resume())
            self.assertIsNone(engine.stop())
        finally:
            engine.audio_mgr.close()


class TestSingleInstance(unittest.TestCase):
    def test_single_instance(self):
        lock1 = SingleInstance("Local\\TestMutexUnique.Instance")
        self.assertFalse(lock1.already_running)
        lock2 = SingleInstance("Local\\TestMutexUnique.Instance")
        self.assertTrue(lock2.already_running)
        lock2.close()
        lock1.close()

    def test_exclude_from_capture_safe(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            res = exclude_from_capture(root)
            self.assertIsInstance(res, bool)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
