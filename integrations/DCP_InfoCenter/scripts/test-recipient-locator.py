"""Recipient localization regression using generated data, without private captures."""
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from direct_sender import recipient_candidates, lines

class RecipientLocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)
        self.window = dict(x=0, y=0, width=1280, height=772)
    def tearDown(self):
        self.temp.cleanup()
    def test_exact_local_name_excludes_network_suggestions(self):
        rows = [('Demo Group', 180, 129, 136), ('Demo Group', 180, 160, 113), ('Other Group', 180, 210, 136)]
        with patch('direct_sender.lines', side_effect=lambda *args, **kwargs: rows if kwargs.get('green') else []):
            self.assertEqual(recipient_candidates(None, self.window, self.state, 'Demo Group', None), [rows[0][:3]])
            self.assertEqual(recipient_candidates(None, self.window, self.state, 'Missing Group', None), [])
    def test_same_name_rows_remain_ambiguous(self):
        rows = [('Demo Group', 180, 129, 136), ('Demo Group', 180, 210, 136)]
        with patch('direct_sender.lines', side_effect=lambda *args, **kwargs: rows if kwargs.get('green') else []):
            self.assertEqual(len(recipient_candidates(None, self.window, self.state, 'Demo Group', None)), 2)
    def test_filehelper_history_shortcut_is_excluded(self):
        def recognized(*args, **kwargs):
            if kwargs.get('green'): return [('文件传输助手', 180, 130, 136), ('文件传输助手', 180, 390, 136)]
            if args[3] == (80, 62, 375, 742): return [('聊天记录', 100, 350)]
            return []
        with patch('direct_sender.lines', side_effect=recognized):
            self.assertEqual(recipient_candidates(None, self.window, self.state, '文件传输助手', None, filehelper=True), [('文件传输助手', 180, 130)])
    def test_empty_crop_never_runs_external_ocr(self):
        sample = self.state / 'generated.png'
        Image.new('RGB', (8, 8), 'white').save(sample)
        with patch('direct_sender.subprocess.run') as command:
            self.assertEqual(lines(None, self.window, self.state, (133, 78, 375, 65), snapshot=sample), [])
            command.assert_not_called()

if __name__ == '__main__': unittest.main()
