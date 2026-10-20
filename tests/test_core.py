import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from mywechat.config import Settings, load_chats
from mywechat.models import Chat, Message, Action
from mywechat.store import Store
from mywechat.safety import Guard, ProcessLock
from mywechat.service import ActionService
from mywechat.agent import Agent
from mywechat.ai import ChatAI
from mywechat.errors import SafetyError, MyWeChatError


class CoreTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent / 'work' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = Settings(db=str(self.root / 'test.db'), stop_file=str(self.root / 'STOP'))
        self.chats = {'a': Chat('a', '好友甲'), 'b': Chat('b', '好友乙'), 'g': Chat('g', '测试群', 'group')}
        self.store = Store(self.settings.db)
        self.addCleanup(self.store.close)
        self.guard = Guard(self.settings)
        self.driver = Mock()
        self.driver.send_text.return_value = 'submitted'
        self.service = ActionService(self.settings, self.store, self.chats, self.driver, self.guard)

    def test_06_dedupe_isolation_and_baseline(self):
        a = Message('1', 'a', '甲', '私聊记忆')
        b = Message('2', 'b', '乙', '另一个人的记忆')
        self.store.ingest([a], baseline=True)
        assert self.store.unread('a') == []
        assert self.store.ingest([a, b]) == [b]
        assert len(self.store.history('a')) == 1
        assert '私聊记忆' in self.store.history('a')[0]['content']
        assert '私聊记忆' not in str(self.store.history('b'))

    def test_06_approval_dry_run_never_calls_driver(self):
        ident = self.service.submit(Action('a', 'text', '你好'))
        with self.assertRaises(SafetyError):
            self.service.execute(ident)
        self.service.approve(ident)
        assert self.service.execute(ident) == 'simulated'
        assert self.driver.mock_calls == []
        with self.assertRaises(SafetyError):
            self.service.execute(ident)

    def test_06_whitelist_and_friend_always_needs_approval(self):
        self.settings.approval_required = False
        with self.assertRaises(SafetyError):
            self.service.submit(Action('unknown', 'text', 'x'))
        ident = self.service.submit(Action('friend:req', 'accept_friend', request_id='req'))
        assert self.store.get(ident)['state'] == 'pending'

    def test_06_cooldown_and_unknown_result_no_retry(self):
        self.settings.dry_run = False
        first = self.service.submit(Action('a', 'text', '你好'))
        self.service.approve(first)
        self.service.execute(first)
        second = self.service.submit(Action('a', 'text', '再次你好'))
        self.service.approve(second)
        assert self.service.execute(second) == 'cooldown'
        self.settings.cooldown = 0
        self.driver.send_text.side_effect = RuntimeError('UI failure')
        with self.assertRaises(RuntimeError):
            self.service.execute(second)
        assert self.store.get(second)['state'] == 'uncertain'
        with self.assertRaises(SafetyError):
            self.service.execute(second)
        with self.assertRaises(SafetyError):
            self.service.submit(Action('a', 'text', '禁止重发'))

    def test_06_crash_recovery(self):
        ident = self.store.queue(Action('a', 'text', 'x'), approved=True)
        self.store.transition(ident, 'approved', 'executing')
        self.store.recover()
        assert self.store.get(ident)['state'] == 'uncertain'

    def test_06_expiry(self):
        ident = self.service.submit(Action('a', 'text', 'x'))
        self.settings.approval_ttl = 0
        with self.assertRaises(SafetyError):
            self.service.approve(ident)
        assert self.store.get(ident)['state'] == 'expired'

    def test_06_stop_and_exclusive_lock(self):
        self.guard.stop()
        with self.assertRaises(SafetyError):
            self.service.submit(Action('a', 'text', 'x'))
        path = str(self.root / 'lock')
        with ProcessLock(path):
            with self.assertRaises(SafetyError):
                with ProcessLock(path):
                    pass

    def test_06_media_approval_binds_bytes(self):
        path = self.root / 'a.gif'
        path.write_bytes(b'GIF89a')
        ident = self.service.submit(Action('a', 'media', path=str(path)))
        self.service.approve(ident)
        path.write_bytes(b'GIF89a modified')
        with self.assertRaises(SafetyError):
            self.service.execute(ident)

    def test_06_duplicate_contact_titles_rejected(self):
        path = self.root / 'chats.json'
        path.write_text(json.dumps([{'key':'a','title':'同名'}, {'key':'b','title':'同名'}]), encoding='utf-8')
        with self.assertRaises(SafetyError):
            load_chats(path)

    def make_agent(self):
        ai = Mock()
        ai.decide.return_value = dict(participate=True, text='收到', reason='被提问')
        return Agent(self.settings, self.chats, self.driver, self.store, ai, self.service, self.guard)

    def test_07_agent_baseline_group_gate_and_queue(self):
        agent = self.make_agent()
        old = Message('old', 'g', '甲', '旧消息')
        self.driver.read_messages.return_value = [old]
        assert agent.poll('g') == 'baseline'
        ordinary = Message('normal', 'g', '甲', '普通讨论')
        self.driver.read_messages.return_value = [old, ordinary]
        assert agent.poll('g') == 'skip-topic'
        agent.ai.decide.assert_not_called()
        mention = Message('mention', 'g', '乙', '@胡锦程 有空吗', mentions_me=True)
        self.driver.read_messages.return_value = [old, ordinary, mention]
        ident = agent.poll('g')
        assert self.store.get(ident)['state'] == 'pending'
        assert agent.poll('g') == 'idle'
        agent.ai.decide.assert_called_once()

    def test_07_ai_declines_and_outgoing_does_not_trigger(self):
        agent = self.make_agent()
        self.driver.read_messages.return_value = []
        agent.poll('a')
        own = Message('own', 'a', '我', '自己发的', outgoing=True)
        self.driver.read_messages.return_value = [own]
        assert agent.poll('a') == 'idle'
        agent.ai.decide.return_value = dict(participate=False, text='', reason='无需回复')
        self.driver.read_messages.return_value = [own, Message('new', 'a', '甲', '好的')]
        assert agent.poll('a') == 'skip-ai'

    def test_07_ai_failure_keeps_inbox_retryable(self):
        agent = self.make_agent()
        self.driver.read_messages.return_value = []
        agent.poll('a')
        self.driver.read_messages.return_value = [Message('new', 'a', '甲', '你好')]
        agent.ai.decide.side_effect = MyWeChatError('timeout')
        with self.assertRaises(MyWeChatError):
            agent.poll('a')
        assert len(self.store.unread('a')) == 1

    def test_07_virtualized_history_resync_no_duplicate_reply(self):
        agent = self.make_agent()
        self.driver.read_messages.return_value = [Message('old', 'a', '甲', '历史')]
        agent.poll('a')
        self.driver.read_messages.return_value = [Message('changed-runtime-id', 'a', '甲', '历史')]
        assert agent.poll('a') == 'resync'
        agent.ai.decide.assert_not_called()


class AITests(unittest.TestCase):
    def setUp(self):
        import httpx
        self.httpx = httpx
        self.settings = Settings(api_key='test-key')

    def client(self, payload, status=200):
        def handler(request):
            assert request.url.path == '/chat/completions'
            body = json.loads(request.content)
            assert body['response_format'] == {'type':'json_object'}
            return self.httpx.Response(status, json=payload)
        return ChatAI(self.settings, self.httpx.MockTransport(handler))

    def test_07_http_contract(self):
        payload = {'choices':[{'message':{'content':json.dumps(dict(participate=True,text='你好',reason='合适'))}}]}
        assert self.client(payload).decide(Chat('a','甲'), [])['text'] == '你好'

    def test_07_malformed_and_rate_limit(self):
        for payload, status in [({},200), ({},429), ({'choices':[{'message':{'content':'[]'}}]},200),
                                 ({'choices':[{'message':{'content':'{"participate":"false","text":"x","reason":"x"}'}}]},200)]:
            with self.assertRaises(MyWeChatError):
                self.client(payload,status).decide(Chat('a','甲'), [])
