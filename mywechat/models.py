from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Chat:
    key: str
    title: str
    kind: Literal['private', 'group'] = 'private'


@dataclass(frozen=True)
class Message:
    id: str
    chat: str
    sender: str
    text: str
    outgoing: bool = False
    kind: str = 'text'
    mentions_me: bool = False


@dataclass(frozen=True)
class Action:
    chat: str
    kind: str
    text: str = ''
    path: str = ''
    member: str = ''
    request_id: str = ''
    reason: str = ''
    source_ids: list[str] = field(default_factory=list)
