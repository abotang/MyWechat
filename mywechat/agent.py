import logging
import time
from .models import Action
from .errors import SafetyError

log = logging.getLogger(__name__)


class Agent:
    def __init__(self, settings, chats, driver, store, ai, service, guard):
        self.settings, self.chats, self.driver = settings, chats, driver
        self.store, self.ai, self.service, self.guard = store, ai, service, guard
        self.baselined = set()
        self.snapshots = {}
        self.failures = {}
        self.retry_after = {}

    def poll(self, key):
        self.guard.check()
        chat = self.chats[key]
        self.driver.open_chat(key)
        messages = self.driver.read_messages(key)
        previous = self.snapshots.get(key, [])
        self.snapshots[key] = messages
        # Each start/switch's first snapshot is baseline; never reply to old backlog.
        if key not in self.baselined:
            self.store.ingest(messages, baseline=True)
            self.baselined.add(key)
            return 'baseline'
        if previous and messages and previous[-1].id not in {m.id for m in messages}:
            # UIA virtualization, user scrolling or changed runtime IDs: continuity
            # cannot be proved. Baseline rather than answer old history again.
            self.store.ingest(messages, baseline=True)
            return 'resync'
        self.store.ingest(messages)
        unread = self.store.unread(key)
        if not unread or self.store.pending_for(key):
            return 'idle'
        if time.time() - self.store.last_sent(key) < self.settings.cooldown:
            return 'cooldown'
        ids = [m.id for m in unread]
        if chat.kind == 'group':
            eligible = any(m.mentions_me or any(t.casefold() in m.text.casefold()
                           for t in self.settings.group_topics) for m in unread)
            if not eligible:
                self.store.handled(ids)
                return 'skip-topic'
        decision = self.ai.decide(chat, self.store.history(key))
        self.guard.check()
        if not decision['participate']:
            self.store.handled(ids)
            return 'skip-ai'
        ident = self.service.submit(Action(key, 'text', decision['text'].strip(),
                                           reason=decision['reason'][:300], source_ids=ids))
        if self.store.get(ident)['state'] == 'approved':
            self.service.execute(ident)
        return ident

    def run(self, once=False):
        if not self.chats:
            raise SafetyError('白名单为空；请先配置 config/chats.json')
        while True:
            for row in self.store.actions():
                if row['state'] in ('pending', 'approved') and time.time() - row['created'] >= self.settings.approval_ttl:
                    try:
                        self.store.transition(row['id'], row['state'], 'expired')
                    except SafetyError:
                        pass  # An approval/rejection raced with expiry; next pass rechecks.
            for row in self.store.actions('approved'):
                self.guard.check()
                self.service.execute(row['id'])
            for key in self.chats:
                if time.monotonic() < self.retry_after.get(key, 0):
                    continue
                try:
                    result = self.poll(key)
                    self.failures.pop(key, None)
                    self.retry_after.pop(key, None)
                    log.info('chat=%s result=%s', key, result)
                except SafetyError:
                    raise
                except Exception as exc:
                    # Do not log private text, credentials or exception message.
                    log.error('chat=%s error=%s', key, type(exc).__name__)
                    count = min(self.failures.get(key, 0) + 1, 5)
                    self.failures[key] = count
                    self.retry_after[key] = time.monotonic() + min(60, 2 ** count * 3)
                self.guard.wait(self.settings.poll_seconds)
            if once:
                break
            self.guard.wait(1)
