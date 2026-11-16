"""Synthetic FFmpeg round-trip tests; no third-party source material is used."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPT_DIR))
from core import run
import config
import media

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'FFmpeg and FFprobe are required for audiovisual integration')
class AudiovisualIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_synthetic_video_to_vertical_export(self):
        source = self.root / 'source.mp4'
        output = self.root / 'vertical.mp4'
        run([media.tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y',
             '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15',
             '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
             '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-shortest', str(source)], 60)
        source_info = media.validate_media(source, duration=2, full=True)
        self.assertEqual((source_info['width'], source_info['height']), (320, 180))
        self.assertTrue(source_info['full_decode'])
        cfg = config.load({'profile': '9:16', 'width': 360, 'height': 640, 'fps': 15,
                           'layout': 'camera-top', 'camera_box': [0, 0, 160, 90]})
        camera = media.faces(source, cfg)
        self.assertEqual(camera['method'], 'manual')
        self.assertEqual(camera['box'], [0, 0, 160, 90])
        captions_file = self.root / 'captions.ass'
        media.captions(captions_file, [dict(start=.2, end=.8, word='Audiovisual')],
                       'Synthetic test', 2, 360, 640, cfg)
        self.assertIn('Audiovisual', captions_file.read_text(encoding='utf-8'))
        graph = media.compose(360, 640, camera, cfg)
        run([media.tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y',
             '-i', str(source), '-filter_complex', graph,
             '-map', '[v]', '-map', '0:a:0', '-c:v', 'libx264',
             '-preset', 'ultrafast', '-crf', '28', '-r', '15',
             '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', str(output)],
            120, cwd=self.root)
        result = media.validate_media(output, duration=2, size=(360, 640), full=True)
        self.assertGreater(result['bytes'], 1000)
        self.assertTrue(result['full_decode'])
        self.assertGreaterEqual(result['audio_streams'], 1)
        self.assertGreaterEqual(result['video_streams'], 1)

    def test_corrupt_input_is_rejected(self):
        corrupt = self.root / 'corrupt.mp4'
        corrupt.write_bytes(b'not an mp4 file')
        with self.assertRaises(Exception):
            media.validate_media(corrupt)

if __name__ == '__main__':
    unittest.main()
