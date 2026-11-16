"""Additional reliability and benchmark-summary tests for the Stream Clipper."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
import wave

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import install
import media
from clip import summarize_benchmark


class InstallReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = Path(__file__).resolve().parents[1]
        self.destination = self.root / 'personal' / 'stream-clipper'

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_backup_verifies_and_rollback_preserves_current(self):
        install.install(self.source, self.destination)
        (self.destination / 'user-note.txt').write_text('keep this note', encoding='utf-8')

        update = install.install(self.source, self.destination)
        backup = Path(update['backup'])
        self.assertTrue(install.verify(backup)['valid'])
        self.assertEqual((backup / 'user-note.txt').read_text(encoding='utf-8'), 'keep this note')

        result = install.rollback(self.destination, backup)
        self.assertTrue((self.destination / 'user-note.txt').is_file())
        self.assertTrue(Path(result['retained']).is_dir())

    def test_verify_detects_modified_installed_file(self):
        install.install(self.source, self.destination)
        install.verify(self.destination)
        skill = self.destination / 'SKILL.md'
        skill.write_text(skill.read_text(encoding='utf-8') + '\nlocal modification\n', encoding='utf-8')
        with self.assertRaises(Exception):
            install.verify(self.destination)

    @unittest.skipIf(os.name == 'nt', 'Creating symlinks may require elevated privileges on Windows')
    def test_dangling_symlink_in_existing_install_is_rejected(self):
        install.install(self.source, self.destination)
        dangling = self.destination / 'dangling-link'
        dangling.symlink_to(self.root / 'target-that-does-not-exist')
        with self.assertRaises(Exception):
            install.install(self.source, self.destination)
        self.assertTrue(dangling.is_symlink())
        self.assertTrue((self.destination / 'SKILL.md').is_file())

    def test_failed_staging_keeps_existing_installation(self):
        install.install(self.source, self.destination)
        before = (self.destination / 'SKILL.md').read_bytes()
        from unittest.mock import patch
        with patch('install.shutil.copytree', side_effect=OSError('simulated copy failure')):
            with self.assertRaises(OSError):
                install.install(self.source, self.destination)
        self.assertEqual((self.destination / 'SKILL.md').read_bytes(), before)
        self.assertFalse(list(self.destination.parent.glob('.stream-clipper.stage-*')))


class MediaAndBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_audio_peak_analysis_handles_streamed_pcm(self):
        sample_rate = 16000
        t = np.arange(sample_rate, dtype=np.float64) / sample_rate
        quiet = (np.sin(2 * np.pi * 440 * t) * 800).astype('<i2')
        loud = (np.sin(2 * np.pi * 440 * t) * 12000).astype('<i2')
        audio = self.root / 'peaks.wav'
        with wave.open(str(audio), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(quiet.tobytes() + loud.tobytes() + quiet.tobytes())
        peaks = media.audio_peaks(audio)
        self.assertEqual([item['second'] for item in peaks], [1])
        self.assertGreater(peaks[0]['above_median_db'], 8)

    def test_corrupt_media_is_rejected_by_ffprobe(self):
        if not media.tool('ffprobe') or not media.tool('ffmpeg'):
            self.skipTest('FFmpeg tools unavailable')
        corrupt = self.root / 'corrupt.mp4'
        corrupt.write_bytes(b'not an MP4')
        with self.assertRaises(Exception):
            media.validate_media(corrupt)

    def test_benchmark_summary_uses_medians_and_exposes_cuda_failure(self):
        results = [
            dict(device='cpu', status='complete', repetition=0, load_seconds=2,
                 transcribe_seconds=4, wall_seconds=6, transcript='hello there',
                 resources=dict(rss_bytes=100, vram_total_mib=200, vram_baseline_mib=190)),
            dict(device='cpu', status='complete', repetition=1, load_seconds=4,
                 transcribe_seconds=6, wall_seconds=10, transcript='hello there',
                 resources=dict(rss_bytes=120, vram_total_mib=220, vram_baseline_mib=200)),
            dict(device='cuda', status='complete', repetition=0, load_seconds=1,
                 transcribe_seconds=2, wall_seconds=3, transcript='hello there',
                 resources=dict(rss_bytes=80, vram_total_mib=4000, vram_baseline_mib=1000)),
            dict(device='cuda', status='failed', repetition=1, error='RuntimeError'),
        ]
        result = summarize_benchmark(results)
        self.assertEqual(result['cpu']['median_transcribe_seconds'], 5)
        self.assertEqual(result['cuda']['failures'], 1)
        self.assertEqual(result['cuda_speedup_vs_cpu'], 2.5)
        self.assertEqual(result['cpu_cuda_transcript_similarity'], 1.0)
        self.assertIn('not WER/CER', result['transcript_similarity_note'])


if __name__ == '__main__':
    unittest.main()
