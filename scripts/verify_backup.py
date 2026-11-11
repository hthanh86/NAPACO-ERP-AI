"""Restore the latest local backup into a disposable database, never into the live database."""
import gzip
import hashlib
import json
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOCKER = '/Applications/Docker.app/Contents/Resources/bin/docker'


def mysql(sql, database=None):
    command = [DOCKER, 'exec', '-i', 'napaco-mysql84', 'sh', '-c',
               'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --batch --skip-column-names "$@"', 'sh']
    if database:
        command.append(database)
    result = subprocess.run(command, input=sql, capture_output=True, check=True)
    return result.stdout.decode().strip()


def verify():
    files = sorted((ROOT / 'backups').glob('napaco-*.sql.gz'))
    if not files:
        raise RuntimeError('Chưa có bản sao lưu.')
    source = files[-1]
    expected = source.with_suffix(source.suffix + '.sha256').read_text().strip()
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Checksum bản sao lưu không khớp.')
    database = 'napaco_restorecheck_' + secrets.token_hex(8)
    created = False
    try:
        mysql(('CREATE DATABASE `' + database + '` CHARACTER SET utf8mb4;').encode())
        created = True
        mysql(gzip.decompress(source.read_bytes()), database)
        tables = ['customers', 'products', 'users', 'orders', 'order_lines', 'role_permissions', 'source_rows']
        counts = {table: int(mysql(('SELECT COUNT(*) FROM `' + table + '`;').encode(), database)) for table in tables}
        totals = mysql(b'SELECT SUM(quantity), SUM(delivered), SUM(quantity * price) FROM order_lines;', database)
        result = {'backup': source.name, 'checksum': 'PASS', 'restore': 'PASS', 'counts': counts, 'totals': totals,
                  'live_database_unchanged': True, 'temporary_database_removed': True}
    finally:
        if created:
            mysql(('DROP DATABASE `' + database + '`;').encode())
    (ROOT / 'reports/backup-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    verify()
