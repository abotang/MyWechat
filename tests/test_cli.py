import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mywechat.cli import main
from mywechat.config import Settings


class CLITests(unittest.TestCase):
    def test_08_queue_approve_execute_stop_without_profile(self):
        root = Path(__file__).resolve().parent.parent / 'work' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            root = Path(temp)
            settings = Settings(db=str(root/'cli.db'),stop_file=str(root/'STOP'))
            chats = root/'chats.json'
            chats.write_text(json.dumps([dict(key='a',title='测试好友')]), encoding='utf-8')
            def call(*args):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    rc = main(['--chats',str(chats),*args])
                return rc, output.getvalue()
            with patch('mywechat.cli.Settings.load',return_value=settings):
                rc, out = call('send','a','你好😀')
                assert rc == 0
                ident = json.loads(out)['id']
                assert call('approve',ident)[0] == 0
                rc, out = call('execute',ident)
                assert rc == 0 and json.loads(out)['result'] == 'simulated'
                assert call('execute',ident)[0] == 2
                assert call('stop')[0] == 0
                assert call('send','a','被停止')[0] == 2
                assert call('resume')[0] == 0
                assert call('send','unknown','不在白名单')[0] == 2
