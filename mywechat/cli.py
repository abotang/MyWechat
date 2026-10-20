import argparse
import json
import logging
import platform
import sys
from pathlib import Path
from .config import Settings, load_chats
from .errors import MyWeChatError, SafetyError
from .models import Action
from .safety import Guard, ProcessLock
from .store import Store
from .service import ActionService


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(description='MyWeChat Windows 4.x UIA Agent')
    p.add_argument('--profile', default='config/profile.json')
    p.add_argument('--chats', default='config/chats.json')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    q = commands.add_parser('probe', help='只读控件树探测，不聚焦/点击')
    q.add_argument('--pid', type=int)
    q.add_argument('--output', default='data/probe.json')
    q.add_argument('--depth', type=int, default=8)
    q.add_argument('--limit', type=int, default=4000)
    q = commands.add_parser('read')
    q.add_argument('chat')
    commands.add_parser('contacts')
    commands.add_parser('verify-profile', help='只读验证当前界面控件是否唯一匹配')
    commands.add_parser('friends')
    q = commands.add_parser('send')
    q.add_argument('chat')
    q.add_argument('text')
    q = commands.add_parser('mention')
    q.add_argument('chat')
    q.add_argument('member')
    q.add_argument('text')
    q = commands.add_parser('media')
    q.add_argument('chat')
    q.add_argument('path')
    q = commands.add_parser('accept-friend')
    q.add_argument('request_id')
    q = commands.add_parser('add-friend')
    q.add_argument('identifier')
    q.add_argument('greeting')
    q = commands.add_parser('actions')
    q.add_argument('--state')
    for name in ['approve', 'reject', 'execute', 'resolve']:
        q = commands.add_parser(name)
        q.add_argument('id')
        if name == 'resolve':
            q.add_argument('--note', required=True, help='人工核对客户端后的处理说明')
    q = commands.add_parser('run')
    q.add_argument('--once', action='store_true', help='仅做一轮快照，首次轮询仅基线')
    q.add_argument('--ai-consent', action='store_true', help='确认将白名单聊天上下文发送到配置的AI服务')
    q = commands.add_parser('forget')
    q.add_argument('chat')
    commands.add_parser('stop')
    commands.add_parser('resume')
    return p


def doctor():
    import importlib.util
    version = platform.python_version()
    return dict(python=version, target='Python 3.12.x',
                python312_tested=version.startswith('3.12.'), platform=platform.platform(),
                modules={m: importlib.util.find_spec(m) is not None for m in ['pywinauto', 'win32api', 'httpx', 'dotenv']},
                real_wechat_verified=False)


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    store = None
    try:
        if args.command == 'doctor':
            emit(doctor())
            return 0
        if args.command == 'probe':
            from .probe import probe
            if not 1 <= args.depth <= 20 or not 1 <= args.limit <= 20000:
                raise SafetyError('depth 允许 1~20，limit 允许 1~20000')
            emit(probe(args.output, args.pid, args.depth, args.limit))
            return 0
        s = Settings.load()
        guard = Guard(s)
        if args.command == 'stop':
            guard.stop()
            emit({'status': 'stopped'})
            return 0
        if args.command == 'resume':
            Path(s.stop_file).unlink(missing_ok=True)
            emit({'status': 'resumed', 'note': '未自动重启 Agent'})
            return 0
        chats = load_chats(args.chats)
        store = Store(s.db)
        service = ActionService(s, store, chats, None, guard)
        cmd = args.command
        # Approval and queue updates remain available while the UI process runs.
        if cmd == 'actions':
            emit(store.actions(args.state))
        elif cmd == 'approve':
            service.approve(args.id)
            emit({'id': args.id, 'state': 'approved'})
        elif cmd == 'reject':
            row = store.get(args.id)
            if row['state'] not in ('pending', 'approved'):
                raise SafetyError('只能拒绝 pending/approved 动作')
            store.transition(args.id, row['state'], 'rejected')
            emit({'id': args.id, 'state': 'rejected'})
        elif cmd == 'resolve':
            store.transition(args.id, 'uncertain', 'resolved', args.note[:1000])
            emit({'id': args.id, 'state': 'resolved'})
        elif cmd == 'forget':
            with ProcessLock(s.db + '.lock'):
                store.purge(args.chat)
            emit({'chat': args.chat, 'status': 'forgotten'})
        elif cmd in ('send', 'mention', 'media', 'accept-friend', 'add-friend'):
            if cmd == 'send':
                action = Action(args.chat, 'text', args.text)
            elif cmd == 'mention':
                action = Action(args.chat, 'mention', args.text, member=args.member)
            elif cmd == 'media':
                action = Action(args.chat, 'media', path=args.path)
            elif cmd == 'accept-friend':
                action = Action('friend:' + args.request_id, 'accept_friend', request_id=args.request_id)
            else:
                action = Action('add:' + args.identifier, 'add_friend', text=args.greeting, member=args.identifier)
            ident = service.submit(action)
            emit({'id': ident, 'state': store.get(ident)['state'], 'dry_run': s.dry_run})
        else:
            if cmd == 'run' and not args.ai_consent:
                raise SafetyError('run 需要 --ai-consent，确认将白名单聊天上下文发送到 AI 接口')
            with ProcessLock(s.db + '.lock'), guard.watch():
                guard.check()
                store.recover()
                from .driver import WeChatDriver
                driver = None
                if cmd != 'execute' or not s.dry_run:
                    driver = WeChatDriver(args.profile, chats, guard.check)
                service.driver = driver
                # Dry-run execution does not instantiate or touch the UI.
                if cmd != 'execute' or not s.dry_run:
                    driver.connect()
                if cmd == 'read':
                    from dataclasses import asdict
                    driver.open_chat(args.chat)
                    emit([asdict(m) for m in driver.read_messages(args.chat)])
                elif cmd == 'contacts':
                    emit(driver.contacts())
                elif cmd == 'verify-profile':
                    emit(driver.audit())
                elif cmd == 'friends':
                    emit([{k: v for k, v in r.items() if k != 'row'} for r in driver.friend_requests()])
                elif cmd == 'execute':
                    emit({'id': args.id, 'result': service.execute(args.id)})
                elif cmd == 'run':
                    from .ai import ChatAI
                    from .agent import Agent
                    Agent(s, chats, driver, store, ChatAI(s), service, guard).run(args.once)
        return 0
    except KeyboardInterrupt:
        print('已停止。正在执行的动作如未确定结果，需要人工核对。', file=sys.stderr)
        return 130
    except (MyWeChatError, OSError, ValueError, TypeError, KeyError) as exc:
        # OS errors may include local filenames, but never include API credentials.
        print(f'错误 [{type(exc).__name__}]: {exc}', file=sys.stderr)
        return 2
    except Exception as exc:
        print(f'错误 [{type(exc).__name__}]：操作中止，请检查控件映射和客户端状态。', file=sys.stderr)
        return 3
    finally:
        if store:
            store.close()
