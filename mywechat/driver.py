"""Self-developed UIA driver. Selectors must come from the actual client's probe."""
import contextlib
import ctypes
import hashlib
import json
import re
import time
from pathlib import Path
from .errors import CalibrationError, DeliveryUncertain, SafetyError
from .models import Message
from .probe import desktop

FIELDS = {'name', 'automation_id', 'control_type', 'class_name'}


def matches(c, spec):
    if not spec or not set(spec) <= FIELDS:
        raise CalibrationError('选择器必须是非空的 name/automation_id/control_type/class_name 精确条件')
    return all(getattr(c.element_info, k) == v for k, v in spec.items())


def find(root, spec):
    return [c for c in root.descendants() if matches(c, spec) and c.is_visible()]


def one(root, spec):
    hits = find(root, spec)
    if len(hits) != 1:
        raise CalibrationError(f'控件匹配数量 {len(hits)}，要求唯一：{spec}')
    return hits[0]


class WeChatDriver:
    def __init__(self, profile, chats, guard=lambda: None):
        self.profile = json.loads(Path(profile).read_text(encoding='utf-8'))
        self.chats, self.guard, self.root = chats, guard, None

    def connect(self):
        p = self.profile
        if not p.get('calibrated') or not isinstance(p.get('process_id'), int) or p['process_id'] <= 0:
            raise CalibrationError('先运行 probe，填写真实 profile.json，并设置 calibrated=true 和当前 process_id')
        hits = [w for w in desktop().windows() if w.element_info.process_id == p['process_id']
                and matches(w, p['window'])]
        if len(hits) != 1:
            raise CalibrationError('未找到唯一微信主窗口；检查登录状态、PID、控件映射和权限级别')
        self.root = hits[0]

    def control(self, key, root=None):
        spec = self.profile.get('selectors', {}).get(key)
        if not spec:
            raise CalibrationError(f'尚未校准 selectors.{key}')
        if 'match' in spec:
            scope, match = spec.get('scope', 'window'), spec['match']
            if scope == 'process' and root is None:
                hits = []
                for window in desktop().windows():
                    if window.element_info.process_id == self.profile['process_id']:
                        if matches(window, match) and window.is_visible():
                            hits.append(window)
                        hits.extend(find(window, match))
                if len(hits) != 1:
                    raise CalibrationError(f'进程范围控件 {key} 匹配 {len(hits)} 个，要求唯一')
                return hits[0]
            if scope not in ('window', 'process'):
                raise CalibrationError('选择器 scope 只支持 window/process')
            spec = match
        return one(root or self.root, spec)

    def _foreground(self):
        import win32gui
        import win32process
        fg = win32gui.GetForegroundWindow()
        if win32process.GetWindowThreadProcessId(fg)[1] != self.profile['process_id']:
            raise SafetyError('微信不在前台，已中止操作')

    def audit(self):
        result = {}
        for key in self.profile.get('selectors', {}):
            try:
                c = self.control(key)
                result[key] = {'matched': True, 'type': c.element_info.control_type}
            except CalibrationError as exc:
                result[key] = {'matched': False, 'error': str(exc)}
        return result

    def _activate(self):
        self.guard()
        self.root.set_focus()
        self._foreground()

    def _click(self, c):
        self.guard()
        self._foreground()
        c.click_input()

    def _keys(self, c, keys):
        self.guard()
        self._foreground()
        c.type_keys(keys, set_foreground=False)

    def _fill(self, c, text):
        self.guard()
        self._foreground()
        c.set_edit_text(text)

    def _wait(self, callback, seconds=4):
        until = time.monotonic() + seconds
        while True:
            self.guard()
            try:
                value = callback()
                if value:
                    return value
            except CalibrationError:
                pass
            if time.monotonic() > until:
                raise CalibrationError('等待控件状态超时')
            time.sleep(.15)

    def current_title(self):
        return self.control('chat_title').window_text().strip()

    def assert_chat(self, key):
        if key not in self.chats or self.current_title() != self.chats[key].title:
            raise SafetyError('当前会话与白名单目标不符，已中止')

    def open_chat(self, key):
        if key not in self.chats:
            raise SafetyError('目标不在白名单')
        self._activate()
        target = self.chats[key]
        if self.current_title() != target.title:
            self._fill(self.control('search_edit'), target.title)
            def result():
                hits = find(self.control('search_results'), {'name': target.title})
                return hits[0] if len(hits) == 1 else None
            self._click(self._wait(result))
            self._wait(lambda: self.current_title() == target.title)
        self.assert_chat(key)

    def contacts(self):
        return [c.window_text() for c in self.control('contacts_list').children() if c.window_text().strip()]

    def read_messages(self, key):
        self.assert_chat(key)
        p = self.profile['message']
        result = []
        for row in find(self.control('messages'), p['row']):
            body = one(row, p['body']).window_text()
            sender = one(row, p['sender']).window_text()
            outgoing = bool(find(row, p['outgoing_marker']))
            if not sender:
                raise CalibrationError('发送者为空，不能可靠区分自己和群成员')
            if p.get('id_source') == 'automation_id':
                identity = row.element_info.automation_id
            elif p.get('id_source') == 'runtime_id':
                identity = row.element_info.runtime_id
            else:
                raise CalibrationError('message.id_source 必须是 automation_id 或 runtime_id')
            if not identity:
                raise CalibrationError('消息行无可用标识，停止读取以避免错误去重')
            mid = hashlib.sha256(json.dumps([key, identity, sender, body], ensure_ascii=False).encode()).hexdigest()
            pattern = p.get('mention_pattern', '')
            result.append(Message(mid, key, sender, body, outgoing, 'text', bool(pattern and re.search(pattern, body))))
        if len({m.id for m in result}) != len(result):
            raise CalibrationError('消息标识重复，请重新校准 id_source')
        return result

    def _editor(self, key):
        self.assert_chat(key)
        editor = self.control('input_edit')
        if editor.window_text().strip():
            raise SafetyError('输入框有未发送草稿，请人工清理后再试')
        return editor

    def _send(self, key):
        self.guard()
        self._foreground()
        self.assert_chat(key)
        try:
            self._click(self.control('send_button'))
        except Exception as exc:
            raise DeliveryUncertain('发送结果未知；请人工核对，禁止自动重试') from exc
        return 'submitted'

    def send_text(self, key, text):
        self.open_chat(key)
        self._fill(self._editor(key), text)
        return self._send(key)

    def send_mention(self, key, member, text):
        if self.chats[key].kind != 'group':
            raise SafetyError('@只允许群聊')
        self.open_chat(key)
        editor = self._editor(key)
        self._click(editor)
        self._keys(editor, '@')
        popup = self._wait(lambda: self.control('mention_popup'))
        self._click(one(popup, {'name': member}))
        with clipboard_text(' ' + text):
            self._keys(editor, '^v')
        return self._send(key)

    def send_media(self, key, path):
        path = Path(path).resolve(strict=True)
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.bmp', '.gif'):
            raise SafetyError('仅支持 PNG/JPG/BMP/GIF 文件')
        self.open_chat(key)
        self._editor(key)
        self._click(self.control('attach_button'))
        dialog = self._wait(lambda: self.control('file_dialog'))
        self._fill(self.control('file_name_edit', dialog), str(path))
        self._click(self.control('file_open_button', dialog))
        self._wait(lambda: self.control('media_preview'))
        self.assert_chat(key)
        try:
            self._click(self.control('media_send_button'))
        except Exception as exc:
            raise DeliveryUncertain('媒体发送结果未知，请人工核对') from exc
        return 'submitted'

    def friend_requests(self):
        cfg = self.profile.get('friend', {})
        if not cfg:
            raise CalibrationError('尚未校准 friend 配置')
        result = []
        for row in find(self.control('friend_requests'), cfg['row']):
            name, detail = one(row, cfg['name']).window_text(), one(row, cfg['detail']).window_text()
            identity = row.element_info.automation_id or row.element_info.runtime_id
            rid = hashlib.sha256(json.dumps([identity, name, detail], ensure_ascii=False).encode()).hexdigest()
            result.append(dict(id=rid, name=name, detail=detail, row=row))
        return result

    def accept_friend(self, request_id):
        self._activate()
        hits = [r for r in self.friend_requests() if r['id'] == request_id]
        if len(hits) != 1:
            raise SafetyError('好友申请不存在或身份不唯一，请重新读取')
        try:
            self._click(one(hits[0]['row'], self.profile['friend']['accept']))
            if self.profile['friend'].get('requires_confirm', False):
                self._click(self._wait(lambda: self.control('friend_confirm_button')))
        except Exception as exc:
            raise DeliveryUncertain('好友接受结果未知，请人工核对') from exc
        return 'submitted'

    def add_friend(self, identifier, greeting):
        self._activate()
        self._fill(self.control('add_friend_search'), identifier)
        self._click(self.control('add_friend_search_button'))
        self._wait(lambda: self.control('add_friend_result_id').window_text().strip() == identifier)
        self._click(self.control('add_friend_button'))
        self._fill(self.control('friend_greeting'), greeting)
        try:
            self._click(self.control('friend_request_send'))
        except Exception as exc:
            raise DeliveryUncertain('好友申请发送结果未知，请人工核对') from exc
        return 'submitted'


@contextlib.contextmanager
def clipboard_text(text):
    import pythoncom
    import win32clipboard
    import win32con
    pythoncom.OleInitialize()
    try:
        saved = pythoncom.OleGetClipboard()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
        try:
            yield
        finally:
            time.sleep(.2)
            if ctypes.windll.user32.GetClipboardSequenceNumber() == sequence:
                pythoncom.OleSetClipboard(saved)
                pythoncom.OleFlushClipboard()
    finally:
        pythoncom.OleUninitialize()
