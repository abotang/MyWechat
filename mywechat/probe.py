"""Read-only, bounded UIA inventory. Never focuses or clicks windows."""
import json
import platform
from pathlib import Path
from .errors import CalibrationError


def desktop():
    if platform.system() != 'Windows':
        raise CalibrationError('驱动只支持 Windows')
    try:
        from pywinauto import Desktop
        return Desktop(backend='uia')
    except ImportError as exc:
        raise CalibrationError('请先运行 scripts/setup.ps1 安装 UIA 依赖') from exc


def describe(c):
    i = c.element_info
    r = c.rectangle()
    return dict(name=i.name, automation_id=i.automation_id, control_type=i.control_type,
                class_name=i.class_name, process_id=i.process_id, handle=i.handle,
                runtime_id=list(i.runtime_id or []), rectangle=[r.left, r.top, r.right, r.bottom],
                visible=c.is_visible(), enabled=c.is_enabled())


def probe(output, pid=None, depth=8, limit=4000):
    result = dict(schema=1, platform=platform.platform(), windows=[], trees=[], truncated=False, errors=[])
    budget = [limit]
    def walk(c, level):
        if budget[0] <= 0:
            result['truncated'] = True
            return None
        budget[0] -= 1
        try:
            node = describe(c)
            node['children'] = []
            if level < depth:
                for child in c.children():
                    row = walk(child, level + 1)
                    if row is not None:
                        node['children'].append(row)
            elif c.children():
                result['truncated'] = True
            return node
        except Exception as exc:
            result['errors'].append(type(exc).__name__)
            return None
    for window in desktop().windows():
        try:
            data = describe(window)
            result['windows'].append(data)
            if pid and data['process_id'] == pid:
                tree = walk(window, 0)
                if tree:
                    result['trees'].append(tree)
        except Exception as exc:
            result['errors'].append(type(exc).__name__)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return dict(windows=len(result['windows']), trees=len(result['trees']),
                truncated=result['truncated'], errors=result['errors'], output=str(output))
