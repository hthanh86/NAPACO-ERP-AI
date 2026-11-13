"""Template-only permissions/persistence and read-only Google request contract."""
from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.auth.models import RolePermission
from app.integrations.google import sheets
from app.modules.qc.template_models import QCTemplate
from app.modules.qc.models import QualityCheck


def payload():
    return {'form_code':'QC_NVL_V1', 'form_name':'Kiểm tra NVL', 'check_type':'QC NVL',
            'object_type':'NVL', 'product_id':None, 'version':1, 'status':'DRAFT',
            'spreadsheet':'https://docs.google.com/spreadsheets/d/template-sheet-123/edit#gid=999'}


def mock_source(monkeypatch):
    calls = []
    def first(db, user, source, preview=False):
        calls.append((user.id, source, preview))
        return {'spreadsheet_id':'template-sheet-123', 'sheet_id':42, 'sheet_title':'First',
                'title':'QC', 'read_only':True, 'grid':{}, 'merges':[], 'row_count':1, 'column_count':1}
    monkeypatch.setattr(sheets, 'first_tab', first)
    return calls


def test_all_template_operations_require_dedicated_permission(clients, monkeypatch):
    admin, reader, conn = clients
    calls = mock_source(monkeypatch)
    # QC_EDIT is deliberately insufficient to manage source templates.
    conn.execute(RolePermission.__table__.insert().values(role='TEST_READER', permission='QC_EDIT', allowed=True))
    for method, path, data in [('get','/qc/templates',None),('get','/api/qc/templates',None),
            ('post','/api/qc/templates',payload()),('put','/api/qc/templates/missing',payload()),
            ('post','/api/qc/templates/inspect',{'spreadsheet':'template-sheet-123'}),
            ('get','/api/qc/templates/missing/preview',None)]:
        response = reader.request(method, path, **({'json':data} if data else {}))
        assert response.status_code == 403, response.text
    assert calls == []
    conn.execute(RolePermission.__table__.insert().values(role='TEST_READER', permission='QC_TEMPLATE_MANAGE', allowed=True))
    assert reader.get('/api/qc/templates').status_code == 200
    assert admin.get('/qc/templates').status_code == 200


def test_registration_edit_conflict_duplicate_and_existing_qc_untouched(clients, monkeypatch):
    admin, _, conn = clients
    calls = mock_source(monkeypatch)
    before = conn.scalar(select(func.count()).select_from(QualityCheck))
    template = {**payload(), 'form_code':'QC_TEST_' + uuid4().hex.upper()}
    response = admin.post('/api/qc/templates', json=template)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['sheet_id'] == 42 and saved['spreadsheet_id'] == 'template-sheet-123'
    assert saved['created_by'] == '_TEST_ADMIN' and saved['status'] == 'DRAFT'
    assert admin.post('/api/qc/templates', json=template).status_code == 409
    data = {**template, 'expected_updated_at':saved['updated_at'], 'status':'INACTIVE'}
    updated = admin.put('/api/qc/templates/' + saved['id'], json=data)
    assert updated.status_code == 200, updated.text
    assert updated.json()['status'] == 'INACTIVE'
    assert admin.put('/api/qc/templates/' + saved['id'], json=data).status_code == 409
    assert admin.get('/api/qc/templates/' + saved['id'] + '/preview').status_code == 200
    assert calls[-1][-1] is True
    assert conn.scalar(select(func.count()).select_from(QualityCheck)) == before
    assert admin.get('/api/qc/templates?q=' + template['form_code']).json()['items'][0]['id'] == saved['id']


@pytest.mark.parametrize('changes', [{'status':'ACTIVE'}, {'object_type':'CAT'}, {'product_id':'_TEST_P1'}, {'version':2}])
def test_initial_template_must_be_general_nvl_and_cannot_activate(clients, monkeypatch, changes):
    admin, _, _ = clients
    calls = mock_source(monkeypatch)
    assert admin.post('/api/qc/templates', json={**payload(), **changes}).status_code == 422
    assert not calls


def test_google_failure_never_registers_template(clients, monkeypatch):
    admin, _, conn = clients
    before = conn.scalar(select(func.count()).select_from(QCTemplate))
    def denied(*args, **kwargs):
        raise HTTPException(403, 'Không có quyền đọc Google Sheets.')
    monkeypatch.setattr(sheets, 'first_tab', denied)
    assert admin.post('/api/qc/templates', json=payload()).status_code == 403
    assert conn.scalar(select(func.count()).select_from(QCTemplate)) == before


def test_first_tab_only_bounded_range_and_read_only_http(monkeypatch):
    requests = []
    class Response(BytesIO):
        pass
    def urlopen(request, **kwargs):
        requests.append(request)
        query = parse_qs(urlsplit(request.full_url).query)
        if '/drive/' in request.full_url:
            value = {'name':'QC', 'mimeType':'application/vnd.google-apps.spreadsheet'}
        elif 'ranges' not in query:
            value = {'properties':{'title':'QC'}, 'sheets':[
                {'properties':{'index':1,'sheetId':99,'title':'Do not load'}},
                {'properties':{'index':0,'sheetId':42,'title':"Đầu ' ca",'gridProperties':{'rowCount':1000,'columnCount':100}}}]}
        else:
            assert query['ranges'] == ["'Đầu '' ca'!A1:BH500"]
            value = {'sheets':[{'properties':{'sheetId':42}, 'data':[{'rowData':[{'values':[
                {'formattedValue':'<script>alert(1)</script>','effectiveFormat':{'textFormat':{'bold':True}}}]}]}],
                'merges':[{'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':2}]}]}
        return Response(json.dumps(value).encode())
    monkeypatch.setattr(sheets, 'access_token', lambda db,user:'secret-test-token')
    monkeypatch.setattr(sheets.urllib.request, 'urlopen', urlopen)
    result = sheets.first_tab(SimpleNamespace(commit=lambda:None), SimpleNamespace(email='manager@example.test'), payload()['spreadsheet'], True)
    assert result['sheet_id'] == 42 and result['truncated'] and result['read_only']
    assert result['grid']['rowData'][0]['values'][0]['formattedValue'].startswith('<script>')
    assert len(requests) == 3
    assert all(request.get_method() == 'GET' and request.data is None for request in requests)
    assert sum('ranges=' in request.full_url for request in requests) == 1


@pytest.mark.parametrize('code,body,status,message', [
    (404,{},404,'Không tìm thấy'), (401,{},403,'kết nối Google lại'),
    (403,{},403,'thiếu quyền'), (403,{'error':{'errors':[{'reason':'accessNotConfigured'}]}},503,'Chưa bật'),
    (400,{},422,'không phải'), (429,{},429,'giới hạn')])
def test_specific_google_errors(monkeypatch, code, body, status, message):
    def failed(request, **kwargs):
        raise HTTPError(request.full_url, code, 'Google error', {}, BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr(sheets.urllib.request, 'urlopen', failed)
    with pytest.raises(HTTPException) as error:
        sheets.read_json('https://sheets.googleapis.com/v4/spreadsheets/test', 'test-token')
    assert error.value.status_code == status
    assert message in error.value.detail


@pytest.mark.parametrize('source', ['https://evil.test/spreadsheets/d/template-sheet-123/edit',
    'https://docs.google.com.evil.test/spreadsheets/d/template-sheet-123/edit', 'file:///tmp/template-sheet-123',
    'https://docs.google.com/spreadsheets/d/e/2PACX-published/pubhtml', 'short'])
def test_reject_invalid_source_without_network(source):
    with pytest.raises(HTTPException):
        sheets.spreadsheet_id(source)
