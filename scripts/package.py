"""Build source delivery with tests; excludes secrets and local chat data."""
import ast
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    sources = []
    for directory in ['mywechat', 'tests', 'scripts', 'config']:
        for path in sorted((root / directory).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            if directory == 'config' and path.name not in ('chats.json', 'profile.example.json'):
                continue
            if path.suffix in ('.py', '.json', '.ps1', '.cmd'):
                sources.append(path)
    for name in ['README.md','CALIBRATION.md','VALIDATION.md','requirements.txt','pyproject.toml','.env.example','.gitignore']:
        sources.append(root / name)
    for path in sources:
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3,12))
    test = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],
                          capture_output=True, env={**os.environ, 'PYTHONUTF8':'1'}, cwd=root)
    log = test.stdout.decode('utf-8') + test.stderr.decode('utf-8')
    (root/'test-results.txt').write_text(log,encoding='utf-8')
    if test.returncode:
        print(log)
        return test.returncode
    sources.append(root/'test-results.txt')
    destination = root/'outputs'/'MyWeChat-source.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, 'MyWeChat/' + path.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all('/data/' not in n and '/work/' not in n and not n.endswith('/.env')
                   and not n.endswith('/profile.json') for n in archive.namelist())
    print(json.dumps(dict(path=str(destination), files=len(sources),
                          sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                          tests='passed', python312_syntax='passed',
                          python312_runtime=sys.version.startswith('3.12.'),
                          python_version=sys.version.split()[0], real_wechat='not tested'),indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
