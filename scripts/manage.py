"""Local operator shortcuts. Does not print credentials."""
import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DOCKER = '/Applications/Docker.app/Contents/Resources/bin/docker'
COMPOSE = '/Applications/Docker.app/Contents/Resources/cli-plugins/docker-compose'
os.environ['PATH'] = str(Path(DOCKER).parent) + ':' + os.environ.get('PATH', '')
os.chdir(ROOT)


def run(args, **kw):
    return subprocess.run(args, check=True, **kw)


def compose(*args, **kw):
    return run([COMPOSE, '--env-file', '.mysql.env', *args], **kw)


def ready():
    run(['open', '-a', 'Docker'])
    for n in range(60):
        if subprocess.run([DOCKER, 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
        if n % 10 == 0: print('Đang chờ Docker Desktop khởi động…', flush=True)
        time.sleep(1)
    raise RuntimeError('Docker chưa sẵn sàng. Hãy mở Docker Desktop rồi thử lại.')


def backup():
    folder = ROOT / 'backups'
    folder.mkdir(exist_ok=True)
    target = folder / ('napaco-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sql.gz')
    command = [DOCKER, 'exec', 'napaco-mysql84', 'sh', '-c',
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --hex-blob --no-tablespaces --set-gtid-purged=OFF "$MYSQL_DATABASE"']
    with target.open('wb') as raw:
        os.chmod(target, 0o600)
        with gzip.GzipFile(fileobj=raw, mode='wb') as zipped:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for block in iter(lambda: proc.stdout.read(1024 * 1024), b''):
                zipped.write(block)
            error = proc.stderr.read()
            if proc.wait():
                target.unlink(missing_ok=True)
                raise RuntimeError('Sao lưu thất bại: ' + error.decode())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + '.sha256').write_text(digest + '\n')
    print('Đã sao lưu:', target.name, flush=True)


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action == 'start':
        ready()
        compose('up', '-d', 'mysql')
        compose('run', '--rm', '--no-deps', 'backend', 'alembic', 'upgrade', 'head')
        compose('up', '-d', 'backend')
        import urllib.request
        for _ in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2) as response:
                    if response.status == 200: break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('Backend chưa sẵn sàng. Kiểm tra trạng thái trong Docker Desktop.')
        run(['open', 'http://127.0.0.1:8000'])
        print('Ứng dụng đã mở: http://127.0.0.1:8000')
    elif action == 'stop':
        compose('stop', 'backend', 'mysql')
    elif action == 'backup':
        ready(); backup()
    elif action in {'preview', 'import'}:
        args = ['--apply'] if action == 'import' else []
        compose('run', '--rm', '--no-deps', '--user', str(os.getuid()) + ':' + str(os.getgid()),
                'backend', 'python', '-m', 'app.migrate_data', *args)
    elif action == 'status':
        compose('ps')
    else:
        raise SystemExit('Unknown action: ' + action)
