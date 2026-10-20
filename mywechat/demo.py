"""Offline end-to-end exercise. No WeChat or external API calls."""
import json
import tempfile
from pathlib import Path
from .models import Chat, Message
from .config import Settings
from .store import Store
from .service import ActionService
from .safety import Guard
from .agent import Agent


class DemoDriver:
    def __init__(self):
        self.messages = []
    def open_chat(self, key):
        pass
    def read_messages(self, key):
        return self.messages
    def send_text(self, *args):
        raise AssertionError('DRY_RUN should never send')


class DemoAI:
    def decide(self, chat, history):
        return dict(participate=True, text='收到，这是离线预演回复。', reason='收到群聊@提问')


def main():
    root = Path('work/demo').resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as temp:
        settings = Settings(db=str(Path(temp)/'demo.db'), stop_file=str(Path(temp)/'STOP'))
        store = Store(settings.db)
        try:
            chats = {'g': Chat('g', '离线测试群', 'group')}
            driver, guard = DemoDriver(), Guard(settings)
            service = ActionService(settings, store, chats, driver, guard)
            agent = Agent(settings, chats, driver, store, DemoAI(), service, guard)
            events = [dict(step='first_snapshot', result=agent.poll('g'))]
            driver.messages.append(Message('demo1', 'g', '好友甲', '@胡锦程 你好', mentions_me=True))
            ident = agent.poll('g')
            events.append(dict(step='decision', state=store.get(ident)['state']))
            service.approve(ident)
            events.append(dict(step='approved_execute', result=service.execute(ident)))
            events.append(dict(step='duplicate_poll', result=agent.poll('g')))
            print(json.dumps(events, ensure_ascii=False, indent=2))
        finally:
            store.close()


if __name__ == '__main__':
    main()
