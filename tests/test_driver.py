import json
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from mywechat.driver import WeChatDriver, one
from mywechat.models import Chat
from mywechat.errors import CalibrationError, SafetyError, DeliveryUncertain


class Node:
    def __init__(self, name='', aid='', kind='Text', children=(), rid=(1,)):
        self.element_info = NS(name=name, automation_id=aid, control_type=kind, class_name='', runtime_id=rid)
        self.nodes = list(children)
        self.click_input = Mock()
        self.set_edit_text = Mock()
        self.type_keys = Mock()
    def descendants(self):
        return [n for c in self.nodes for n in [c, *c.descendants()]]
    def children(self):
        return self.nodes
    def is_visible(self):
        return True
    def window_text(self):
        return self.element_info.name


def make_driver(tmp_path):
    body = Node('你好😀', 'body')
    sender = Node('好友甲', 'sender')
    row = Node(aid='m1', kind='ListItem', children=[body, sender])
    profile = dict(selectors={k: {'automation_id': k} for k in ['messages', 'chat_title', 'input_edit', 'send_button']},
                   message=dict(row={'control_type': 'ListItem'}, body={'automation_id': 'body'},
                                sender={'automation_id': 'sender'}, outgoing_marker={'automation_id': 'own'},
                                id_source='automation_id', mention_pattern='@胡锦程'))
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(profile), encoding='utf-8')
    d = WeChatDriver(path, {'a': Chat('a', '好友甲'), 'g': Chat('g', '测试群', 'group')})
    d.root = Node(children=[Node('好友甲', 'chat_title'), Node(aid='messages', children=[row]),
                            Node(aid='input_edit'), Node(aid='send_button')])
    d._activate = Mock()
    d._foreground = Mock()
    return d


class DriverTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent / 'work' / 'test-tmp'
        root.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        self.tmp_path = Path(temp.name)
        self.driver = make_driver(self.tmp_path)

    def test_01_read_identity_unicode_dedup(self):
        driver = self.driver
        first = driver.read_messages('a')
        assert first == driver.read_messages('a')
        assert first[0].sender == '好友甲' and first[0].text == '你好😀'
        assert not first[0].outgoing


    def test_01_reject_ambiguous_and_wrong_chat(self):
        driver = self.driver
        with self.assertRaises(CalibrationError):
            one(Node(children=[Node('同名'), Node('同名')]), {'name': '同名'})
        with self.assertRaises(SafetyError):
            driver.read_messages('g')


    def test_01_outgoing_marker(self):
        driver = self.driver
        row = driver.control('messages').nodes[0]
        row.nodes.append(Node(aid='own'))
        assert driver.read_messages('a')[0].outgoing


    def test_01_duplicate_message_identity_fails(self):
        driver = self.driver
        rows = driver.control('messages').nodes
        rows.append(rows[0])
        with self.assertRaises(CalibrationError):
            driver.read_messages('a')


    def test_02_text_send_and_draft_guard(self):
        driver = self.driver
        assert driver.send_text('a', '你好') == 'submitted'
        driver.control('input_edit').set_edit_text.assert_called_once_with('你好')
        driver.control('send_button').click_input.assert_called_once()
        driver.control('input_edit').element_info.name = '我的草稿'
        with self.assertRaises(SafetyError):
            driver.send_text('a', '不要覆盖')


    def test_02_send_failure_is_uncertain(self):
        driver = self.driver
        driver.control('send_button').click_input.side_effect = RuntimeError()
        with self.assertRaises(DeliveryUncertain):
            driver.send_text('a', '你好')


    def test_03_mentions_require_group(self):
        driver = self.driver
        with self.assertRaises(SafetyError):
            driver.send_mention('a', '小王', '你好')


    def test_03_real_member_selection(self):
        driver = self.driver
        import contextlib
        import mywechat.driver as module
        patcher = patch.object(module, 'clipboard_text', lambda t: contextlib.nullcontext())
        patcher.start()
        self.addCleanup(patcher.stop)
        driver.control('chat_title').element_info.name = '测试群'
        driver.profile['selectors']['mention_popup'] = {'automation_id': 'popup'}
        member = Node('小王')
        driver.root.nodes.append(Node(aid='popup', children=[member]))
        assert driver.send_mention('g', '小王', '你好') == 'submitted'
        member.click_input.assert_called_once()
        assert driver.control('input_edit').type_keys.call_count == 2


    def test_04_media_requires_preview(self):
        driver, tmp_path = self.driver, self.tmp_path
        path = tmp_path / 'a.gif'
        path.write_bytes(b'GIF89a')
        for key in ['attach_button', 'file_dialog', 'media_preview', 'media_send_button']:
            driver.profile['selectors'][key] = {'automation_id': key}
            driver.root.nodes.append(Node(aid=key))
        dialog = driver.control('file_dialog')
        for key in ['file_name_edit', 'file_open_button']:
            driver.profile['selectors'][key] = {'automation_id': key}
            dialog.nodes.append(Node(aid=key))
        assert driver.send_media('a', path) == 'submitted'
        driver.control('media_send_button').click_input.assert_called_once()


    def test_05_friend_exact_identity(self):
        driver = self.driver
        driver.profile['selectors']['friend_requests'] = {'automation_id': 'friends'}
        driver.profile['friend'] = dict(row={'control_type': 'ListItem'}, name={'automation_id': 'name'},
                                       detail={'automation_id': 'detail'}, accept={'automation_id': 'accept'})
        accept = Node(aid='accept')
        row = Node(aid='req1', kind='ListItem', children=[Node('小王', 'name'), Node('来自群聊', 'detail'), accept])
        driver.root.nodes.append(Node(aid='friends', children=[row]))
        req = driver.friend_requests()[0]
        assert req['name'] == '小王'
        with self.assertRaises(SafetyError):
            driver.accept_friend('invalid')
        assert driver.accept_friend(req['id']) == 'submitted'
        accept.click_input.assert_called_once()

    def test_04_media_missing_preview_stops(self):
        driver = self.driver
        path = self.tmp_path / 'a.png'
        path.write_bytes(b'fake-png-for-ui-test')
        for key in ['attach_button', 'file_dialog', 'media_send_button']:
            driver.profile['selectors'][key] = {'automation_id': key}
            driver.root.nodes.append(Node(aid=key))
        dialog = driver.control('file_dialog')
        for key in ['file_name_edit', 'file_open_button']:
            driver.profile['selectors'][key] = {'automation_id': key}
            dialog.nodes.append(Node(aid=key))
        driver._wait = Mock(side_effect=[dialog, CalibrationError('preview missing')])
        with self.assertRaises(CalibrationError):
            driver.send_media('a', path)
        driver.control('media_send_button').click_input.assert_not_called()

    def test_05_add_friend_exact_account(self):
        driver = self.driver
        keys = ['add_friend_search', 'add_friend_search_button', 'add_friend_result_id',
                'add_friend_button', 'friend_greeting', 'friend_request_send']
        for key in keys:
            driver.profile['selectors'][key] = {'automation_id': key}
            driver.root.nodes.append(Node(aid=key))
        driver.control('add_friend_result_id').element_info.name = 'test_wechat_id'
        assert driver.add_friend('test_wechat_id', '你好') == 'submitted'
        driver.control('friend_request_send').click_input.assert_called_once()
        driver.control('friend_request_send').click_input.reset_mock()
        driver._wait = Mock(side_effect=CalibrationError('account mismatch'))
        with self.assertRaises(CalibrationError):
            driver.add_friend('different_id', '你好')
        driver.control('friend_request_send').click_input.assert_not_called()

    def test_01_contacts_and_missing_mapping(self):
        driver = self.driver
        with self.assertRaises(CalibrationError):
            driver.contacts()
        driver.profile['selectors']['contacts_list'] = {'automation_id': 'contacts'}
        driver.root.nodes.append(Node(aid='contacts', children=[Node('唯一备注甲'), Node('唯一备注乙')]))
        assert driver.contacts() == ['唯一备注甲', '唯一备注乙']

    def test_00_uncalibrated_profile_never_accesses_desktop(self):
        with patch('mywechat.driver.desktop') as desktop:
            with self.assertRaises(CalibrationError):
                self.driver.connect()
            desktop.assert_not_called()
