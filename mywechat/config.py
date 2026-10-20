import json
import os
from dataclasses import dataclass
from pathlib import Path
from .errors import SafetyError
from .models import Chat


@dataclass
class Settings:
    dry_run: bool = True
    approval_required: bool = True
    cooldown: float = 30
    poll_seconds: float = 3
    approval_ttl: float = 300
    db: str = 'data/mywechat.sqlite3'
    stop_file: str = 'data/STOP'
    base_url: str = 'https://api.deepseek.com'
    api_key: str = ''
    model: str = 'deepseek-chat'
    self_name: str = ''
    persona: str = '你是胡锦程的微信聊天助手。自然、简洁、诚实，不编造个人经历或承诺。'
    group_topics: tuple[str, ...] = ()

    @classmethod
    def load(cls):
        from dotenv import load_dotenv
        load_dotenv()
        def boolean(name, default):
            raw = os.getenv(name, str(default)).lower()
            if raw not in ('true', 'false'):
                raise SafetyError(f'{name} 必须是 true 或 false')
            return raw == 'true'
        s = cls(dry_run=boolean('DRY_RUN', True),
                approval_required=boolean('REQUIRE_APPROVAL', True),
                cooldown=float(os.getenv('COOLDOWN_SECONDS', '30')),
                poll_seconds=float(os.getenv('POLL_SECONDS', '3')),
                approval_ttl=float(os.getenv('APPROVAL_TTL_SECONDS', '300')),
                db=os.getenv('DATABASE_PATH', 'data/mywechat.sqlite3'),
                stop_file=os.getenv('STOP_FILE', 'data/STOP'),
                base_url=os.getenv('AI_BASE_URL', 'https://api.deepseek.com'),
                api_key=os.getenv('AI_API_KEY', ''), model=os.getenv('AI_MODEL', 'deepseek-chat'),
                self_name=os.getenv('SELF_NAME', ''),
                group_topics=tuple(x.strip() for x in os.getenv('GROUP_TOPICS', '').split(',') if x.strip()))
        if min(s.cooldown, s.approval_ttl) < 0 or s.poll_seconds < 1:
            raise SafetyError('冷却/审批期限不得为负，轮询间隔至少 1 秒')
        return s


def load_chats(path='config/chats.json'):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    chats = [Chat(**c) for c in raw]
    if len({c.key for c in chats}) != len(chats) or len({c.title for c in chats}) != len(chats):
        raise SafetyError('白名单 key 和 title 必须唯一；同名联系人请先设置唯一备注')
    if any(not c.key or not c.title or c.kind not in ('private', 'group') for c in chats):
        raise SafetyError('无效白名单')
    return {c.key: c for c in chats}
