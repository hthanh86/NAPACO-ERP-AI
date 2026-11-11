"""Read-only Sheets snapshot using the user's existing clasp sign-in. Never prints tokens."""
import datetime
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def export():
    config = json.loads((ROOT / 'source-appscript/schema.json').read_text())
    auth = json.loads((Path.home() / '.clasprc.json').read_text())['tokens']['default']
    data = urllib.parse.urlencode({k: auth[k] for k in ('client_id', 'client_secret', 'refresh_token')}
                                 | {'grant_type': 'refresh_token'}).encode()
    with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=data), timeout=30) as r:
        token = json.load(r)['access_token']

    def get(url):
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(request, timeout=90) as r:
            return json.load(r)

    snapshot = {'exported_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'books': {}}
    groups = {
        'master': ('ID_MASTER', ['CUSTOMERS', 'PRODUCTS', 'EMPLOYEES', 'PERMISSIONS', 'SETTINGS', 'TOOLS']),
        'operation': ('ID_OPERATION', ['ORDERS', 'ORDER_DETAILS']),
    }
    for group, (id_key, keys) in groups.items():
        book_id = config[id_key]
        base = 'https://sheets.googleapis.com/v4/spreadsheets/' + book_id
        metadata = get(base + '?fields=properties(timeZone,locale),sheets(properties(title))')
        available = {x['properties']['title'] for x in metadata['sheets']}
        names = [config['SHEET_NAMES'][k] for k in keys if config['SHEET_NAMES'][k] in available]
        required = keys[:4] if group == 'master' else keys
        missing = [config['SHEET_NAMES'][k] for k in required if config['SHEET_NAMES'][k] not in available]
        if missing:
            raise ValueError('Missing source sheets: ' + ', '.join(missing))
        params = [('ranges', "'" + n.replace("'", "''") + "'") for n in names]
        params += [('valueRenderOption', 'UNFORMATTED_VALUE'), ('dateTimeRenderOption', 'SERIAL_NUMBER')]
        raw = get(base + '/values:batchGet?' + urllib.parse.urlencode(params))
        snapshot['books'][group] = {'id': book_id, 'properties': metadata['properties'],
                                    'tables': {n: v.get('values', []) for n, v in zip(names, raw['valueRanges'])}}
        print(group + ': ' + ', '.join(n + '=' + str(len(v.get('values', []))) for n, v in zip(names, raw['valueRanges'])))
    target = ROOT / 'data/source-snapshot.json'
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        raise RuntimeError('Snapshot already exists; archive it before exporting again to preserve the migration baseline.')
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    os.chmod(target, 0o600)
    print('Saved read-only snapshot to data/source-snapshot.json. No source data changed.')


if __name__ == '__main__':
    export()
