"""SQLite inbox, bounded per-chat history and durable action state machine."""
import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from .models import Action, Message
from .errors import SafetyError


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, chat TEXT NOT NULL, sender TEXT, text TEXT,
            outgoing INTEGER, kind TEXT, mentions_me INTEGER, observed REAL,
            handled INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS msg_chat ON messages(chat, observed);
        CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY, chat TEXT, payload TEXT, state TEXT,
            created REAL, updated REAL, result TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS act_chat ON actions(chat, updated);
        ''')
        self.db.commit()

    def recover(self):
        # Called only by the UI process after acquiring its exclusive lock.
        with self.db:
            self.db.execute("UPDATE actions SET state='uncertain', result='process interrupted' WHERE state='executing'")

    def close(self):
        self.db.close()

    def ingest(self, messages, baseline=False):
        fresh = []
        with self.db:
            for m in messages:
                cur = self.db.execute('INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?)',
                                      (m.id, m.chat, m.sender, m.text[:16000], m.outgoing, m.kind,
                                       m.mentions_me, time.time(), int(baseline or m.outgoing)))
                if cur.rowcount and not baseline and not m.outgoing:
                    fresh.append(m)
        return fresh

    def unread(self, chat):
        rows = self.db.execute('SELECT * FROM messages WHERE chat=? AND handled=0 AND outgoing=0 ORDER BY observed, rowid LIMIT 100', (chat,))
        return [Message(r['id'], r['chat'], r['sender'], r['text'], bool(r['outgoing']), r['kind'], bool(r['mentions_me'])) for r in rows]

    def handled(self, ids):
        with self.db:
            self.db.executemany('UPDATE messages SET handled=1 WHERE id=?', [(i,) for i in ids])

    def history(self, chat, limit=30):
        rows = self.db.execute('SELECT sender,text,outgoing FROM messages WHERE chat=? ORDER BY observed DESC, rowid DESC LIMIT ?', (chat, limit)).fetchall()
        # Include only UI-observed outgoing text, never pretend submitted means delivered.
        return [dict(role='assistant' if r['outgoing'] else 'user',
                     content=r['text'] if r['outgoing'] else f"{r['sender']}: {r['text']}") for r in reversed(rows)]

    def pending_for(self, chat):
        return bool(self.db.execute("SELECT 1 FROM actions WHERE chat=? AND state IN ('pending','approved','executing','uncertain')", (chat,)).fetchone())

    def last_sent(self, chat):
        row = self.db.execute("SELECT MAX(updated) AS t FROM actions WHERE chat=? AND state IN ('submitted','uncertain','executing')", (chat,)).fetchone()
        return row['t'] or 0

    def queue(self, action, approved=False):
        ident, now = uuid.uuid4().hex[:16], time.time()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            # Atomic: one unresolved action per chat, even across process submissions.
            if self.pending_for(action.chat):
                raise SafetyError('该会话已有待处理或结果未知的动作')
            self.db.execute('INSERT INTO actions(id,chat,payload,state,created,updated) VALUES(?,?,?,?,?,?)',
                            (ident, action.chat, json.dumps(asdict(action), ensure_ascii=False),
                             'approved' if approved else 'pending', now, now))
            self.db.executemany('UPDATE messages SET handled=1 WHERE id=?', [(i,) for i in action.source_ids])
        return ident

    def get(self, ident):
        r = self.db.execute('SELECT * FROM actions WHERE id=?', (ident,)).fetchone()
        if r is None:
            raise SafetyError('动作不存在')
        return dict(r)

    def actions(self, state=None):
        sql = 'SELECT * FROM actions'
        return [dict(r) for r in self.db.execute(sql + (' WHERE state=?' if state else '') + ' ORDER BY created', (state,) if state else ())]

    def transition(self, ident, expected, new, result=''):
        with self.db:
            cur = self.db.execute('UPDATE actions SET state=?,updated=?,result=? WHERE id=? AND state=?',
                                  (new, time.time(), result, ident, expected))
            if cur.rowcount != 1:
                raise SafetyError('动作状态已经变化，拒绝重复执行')

    def purge(self, chat):
        with self.db:
            self.db.execute('DELETE FROM messages WHERE chat=?', (chat,))
            self.db.execute('DELETE FROM actions WHERE chat=?', (chat,))
