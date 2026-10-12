"""Playlist lifecycle tests without a desktop, network or audio output."""
import queue
import threading
import unittest
from unittest.mock import patch

from app import App
from audio_engine import Cancelled


class PlaylistTests(unittest.TestCase):
    def make_app(self):
        app = App.__new__(App)
        app.events = queue.Queue()
        app.track_cancel = threading.Event()
        return app

    def events(self, app):
        result = []
        while not app.events.empty():
            result.append(app.events.get_nowait())
        return result

    def test_sequence_continues_after_bad_file(self):
        app = self.make_app()
        with patch('app.play_file', side_effect=[None, ValueError('broken MP3'), None]) as play:
            app.music_worker(['one.mp3', 'broken.mp3', 'three.mp3'], 17, 0.3, threading.Event())
        self.assertEqual([call.args[0] for call in play.call_args_list], ['one.mp3', 'broken.mp3', 'three.mp3'])
        events = self.events(app)
        self.assertEqual([value for kind, value in events if kind == 'music_track'], [0, 1, 2])
        self.assertIn(('music_done', '播放清單已播放完成。 1 首失敗。'), events)

    def test_skip_current_track_continues_next(self):
        app = self.make_app()
        app.track_cancel.set()
        def play(path, device, volume, cancel, progress):
            if cancel.is_set():
                raise Cancelled()
        with patch('app.play_file', side_effect=play) as output:
            app.music_worker(['one.mp3', 'two.mp3'], 17, 0.3, threading.Event())
        self.assertEqual(output.call_count, 2)
        self.assertFalse(output.call_args_list[1].args[3].is_set())

    def test_stop_does_not_start_next_track(self):
        app = self.make_app()
        stop = threading.Event()
        def play(*args):
            stop.set()
            raise Cancelled()
        with patch('app.play_file', side_effect=play) as output:
            app.music_worker(['one.mp3', 'two.mp3'], 17, 0.3, stop)
        self.assertEqual(output.call_count, 1)
        self.assertIn(('music_done', '音樂已停止。'), self.events(app))

    def test_music_finishes_without_speech_completion_event(self):
        app = self.make_app()
        with patch('app.play_file'):
            app.music_worker(['one.mp3'], 17, 0.3, threading.Event())
        self.assertNotIn('done', [kind for kind, _ in self.events(app)])
