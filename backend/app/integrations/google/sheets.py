"""Read-only, bounded first-tab preview using the current ERP user's OAuth."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from fastapi import HTTPException
from app.integrations.google.oauth import access_token
from app.core.performance import measure

MAX_ROWS = 500
MAX_COLUMNS = 60
MAX_BYTES = 12 * 1024 * 1024


def spreadsheet_id(value):
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{10,255}', value):
        return value
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        raise HTTPException(422, 'URL Google Sheets không hợp lệ.') from None
    match = re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]{10,255})(?:/.*)?', parsed.path)
    if (parsed.scheme == 'https' and parsed.netloc == 'docs.google.com' and match):
        return match[1]
    raise HTTPException(422, 'Nhập Spreadsheet ID hoặc URL https://docs.google.com/spreadsheets/d/ID hợp lệ.')


@measure('google.http_request')
def read_json(url, token):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token}, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, 'Vùng xem trước quá lớn. Hãy giảm nội dung/định dạng trong template.')
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        try:
            details = json.loads(error.read(65536)).get('error', {})
        except (ValueError, OSError):
            details = {}
        reasons = {item.get('reason') for item in details.get('errors', [])}
        reasons.update(item.get('reason') for item in details.get('details', []))
        if error.code == 401:
            raise HTTPException(403, 'Phiên Google hết hạn hoặc đã bị thu hồi. Hãy kết nối Google lại.') from None
        if error.code == 404:
            raise HTTPException(404, 'Không tìm thấy file hoặc Google đang ẩn file vì tài khoản hiện tại không có quyền đọc. Kiểm tra ID và chia sẻ file cho đúng email ERP.') from None
        if error.code == 403:
            if reasons & {'accessNotConfigured', 'SERVICE_DISABLED'}:
                raise HTTPException(503, 'Chưa bật Google Sheets API hoặc Google Drive API trong dự án OAuth. Bật API rồi thử lại.') from None
            raise HTTPException(403, 'Tài khoản Google hiện tại thiếu quyền đọc file, scope OAuth hoặc bị chính sách Workspace chặn. Kiểm tra chia sẻ và kết nối Google lại.') from None
        if error.code == 400:
            raise HTTPException(422, 'File không phải Google Sheets hợp lệ hoặc tab đầu tiên không đọc được.') from None
        if error.code == 429:
            raise HTTPException(429, 'Google giới hạn lượt đọc. Vui lòng thử lại sau.') from None
        raise HTTPException(502, 'Google Sheets tạm thời lỗi (HTTP ' + str(error.code) + ').') from None
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(502, 'Không kết nối được Google. Hãy kiểm tra mạng rồi thử lại.') from None
    except (ValueError, UnicodeError):
        raise HTTPException(502, 'Google trả về dữ liệu không hợp lệ.') from None


def first_tab(db, user, source, preview=False):
    identifier = spreadsheet_id(source)
    token = access_token(db, user)
    # Keep refreshed credentials even if a later file request fails.
    db.commit()
    file = read_json('https://www.googleapis.com/drive/v3/files/' + identifier +
                     '?fields=id,name,mimeType,trashed&supportsAllDrives=true', token)
    if file.get('trashed'):
        raise HTTPException(404, 'File đang nằm trong thùng rác Google Drive.')
    if file.get('mimeType') != 'application/vnd.google-apps.spreadsheet':
        raise HTTPException(422, 'File không phải Google Sheets. Hãy chuyển file Excel sang Google Sheets trước.')
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + identifier
    meta = read_json(base + '?' + urllib.parse.urlencode({'fields':
        'spreadsheetId,properties(title,spreadsheetTheme),sheets(properties)'}), token)
    first = next((sheet['properties'] for sheet in meta.get('sheets', [])
                  if sheet.get('properties', {}).get('index', 0) == 0), None)
    if not first or first.get('sheetType', 'GRID') != 'GRID':
        raise HTTPException(422, 'Tab index 0 không phải bảng ô Google Sheets có thể xem trước.')
    result = {'spreadsheet_id': identifier, 'title': meta.get('properties', {}).get('title', file['name']),
              'sheet_id': first.get('sheetId', 0), 'sheet_title': first['title'],
              'google_email': user.email, 'read_only': True}
    if not preview:
        return result
    grid = first.get('gridProperties', {})
    rows = min(grid.get('rowCount', 1), MAX_ROWS)
    columns = min(grid.get('columnCount', 1), MAX_COLUMNS)
    # Request an explicit A1 range so grid data is never loaded from other tabs.
    n, letters = columns, ''
    while n:
        n, digit = divmod(n - 1, 26)
        letters = chr(65 + digit) + letters
    area = "'" + first['title'].replace("'", "''") + "'!A1:" + letters + str(rows)
    data = read_json(base + '?' + urllib.parse.urlencode({'ranges': area, 'fields':
        'sheets(properties(sheetId),merges,data(startRow,startColumn,rowData(values(formattedValue,userEnteredValue,effectiveFormat)),rowMetadata(pixelSize,hiddenByUser,hiddenByFilter),columnMetadata(pixelSize,hiddenByUser)))'}), token)
    sheet = next((item for item in data.get('sheets', [])
                  if item.get('properties', {}).get('sheetId', 0) == result['sheet_id']), {})
    result.update(grid=sheet.get('data', [{}])[0], merges=sheet.get('merges', []),
                  theme=meta.get('properties', {}).get('spreadsheetTheme', {}),
                  row_count=rows, column_count=columns,
                  truncated=grid.get('rowCount', 0) > rows or grid.get('columnCount', 0) > columns)
    return result
