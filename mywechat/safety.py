import ctypes
import os
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from .errors import SafetyError


class Guard:
    def __init__(self, settings):
        self.settings = settings

    def check(self):
        if Path(self.settings.stop_file).exists():
            raise SafetyError('紧急停止文件存在；人工确认后用 resume 删除')
        if os.name == 'nt' and ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000:
            self.stop()
            raise SafetyError('F12 紧急停止已触发')

    def stop(self):
        p = Path(self.settings.stop_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()

    def wait(self, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.check()
            time.sleep(min(.1, max(0, until - time.monotonic())))

    @contextmanager
    def watch(self):
        """Poll F12 independently so a press during an HTTP call is persisted."""
        done = threading.Event()
        def worker():
            while not done.wait(.05):
                if os.name == 'nt' and ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000:
                    self.stop()
        thread = threading.Thread(target=worker, name='mywechat-emergency', daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join(timeout=1)


class ProcessLock:
    """OS releases byte-range/file locks after a crash; lock file may remain."""
    def __init__(self, path):
        self.path, self.file = Path(path), None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise SafetyError('另一个 MyWeChat 进程正在使用这个数据库') from exc
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()
