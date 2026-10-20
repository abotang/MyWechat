import hashlib
import time
from dataclasses import replace
from pathlib import Path
from .models import Action
from .errors import SafetyError


class ActionService:
    def __init__(self, settings, store, chats, driver, guard):
        self.settings, self.store, self.chats = settings, store, chats
        self.driver, self.guard = driver, guard

    def validate(self, action):
        if action.kind not in ('text', 'mention', 'media', 'accept_friend', 'add_friend'):
            raise SafetyError('不支持的动作类型')
        if action.kind in ('text', 'mention', 'media') and action.chat not in self.chats:
            raise SafetyError('目标不在白名单')
        if action.kind in ('text', 'mention') and (not action.text.strip() or len(action.text) > 2000):
            raise SafetyError('消息必须是 1～2000 字符')
        if action.kind == 'mention' and (not action.member or self.chats[action.chat].kind != 'group'):
            raise SafetyError('@需要群聊和明确成员名')
        if action.kind == 'accept_friend' and not action.request_id:
            raise SafetyError('缺少好友申请标识')
        if action.kind == 'add_friend' and (not action.member or not action.text.strip()):
            raise SafetyError('需要准确微信号/手机号和申请说明')
        if action.kind == 'media':
            path = Path(action.path).resolve(strict=True)
            if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.bmp', '.gif') or path.stat().st_size > 20 * 1024 * 1024:
                raise SafetyError('媒体类型不支持或超过 20MB')

    def submit(self, action):
        self.guard.check()
        self.validate(action)
        # Bind approvals to the exact bytes. Files may change before execution.
        if action.kind == 'media':
            path = Path(action.path).resolve(strict=True)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            action = replace(action, path=str(path), reason=f'sha256:{digest}')
        friend = action.kind in ('accept_friend', 'add_friend')
        return self.store.queue(action, approved=not (friend or self.settings.approval_required))

    def approve(self, ident):
        r = self.store.get(ident)
        if r['state'] != 'pending':
            raise SafetyError('只能审批 pending 动作')
        if time.time() - r['created'] >= self.settings.approval_ttl:
            self.store.transition(ident, r['state'], 'expired')
            raise SafetyError('审批已过期，请重新提交')
        self.store.transition(ident, 'pending', 'approved')

    def execute(self, ident):
        import json
        r = self.store.get(ident)
        if r['state'] != 'approved':
            raise SafetyError('动作未经审批或已经执行')
        action = Action(**json.loads(r['payload']))
        self.guard.check()
        self.validate(action)
        if time.time() - r['created'] >= self.settings.approval_ttl:
            self.store.transition(ident, 'approved', 'expired')
            return 'expired'
        if time.time() - self.store.last_sent(action.chat) < self.settings.cooldown:
            return 'cooldown'
        if action.kind == 'media':
            digest = hashlib.sha256(Path(action.path).read_bytes()).hexdigest()
            if action.reason != f'sha256:{digest}':
                raise SafetyError('审批后的媒体内容发生变化，拒绝发送')
        if self.settings.dry_run:
            self.store.transition(ident, 'approved', 'simulated', 'DRY_RUN: no driver calls')
            return 'simulated'
        self.store.transition(ident, 'approved', 'executing')
        try:
            self.guard.check()
            if action.kind == 'text':
                result = self.driver.send_text(action.chat, action.text)
            elif action.kind == 'mention':
                result = self.driver.send_mention(action.chat, action.member, action.text)
            elif action.kind == 'media':
                result = self.driver.send_media(action.chat, action.path)
            elif action.kind == 'accept_friend':
                result = self.driver.accept_friend(action.request_id)
            else:
                result = self.driver.add_friend(action.member, action.text)
            self.store.transition(ident, 'executing', 'submitted', result)
            return 'submitted'
        except BaseException as exc:
            self.store.transition(ident, 'executing', 'uncertain', type(exc).__name__)
            raise
