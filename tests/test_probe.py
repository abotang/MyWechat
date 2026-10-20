import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock
from test_driver import Node
from mywechat.probe import probe


class ProbeTests(unittest.TestCase):
    def test_00_bounded_read_only_probe(self):
        root = Path(__file__).resolve().parent.parent / 'work' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            a = Node('微信', children=[Node('消息', children=[Node('正文')])])
            for n in [a, *a.descendants()]:
                n.element_info.process_id = 123
                n.element_info.handle = 456
                n.rectangle = lambda: NS(left=0,top=0,right=100,bottom=100)
                n.is_enabled = lambda: True
            fake = Mock()
            fake.windows.return_value = [a]
            with patch('mywechat.probe.desktop', return_value=fake):
                result = probe(Path(temp)/'probe.json', pid=123, limit=2)
            assert result['trees'] == 1 and result['truncated']
            for n in [a, *a.descendants()]:
                n.click_input.assert_not_called()
                n.set_edit_text.assert_not_called()
