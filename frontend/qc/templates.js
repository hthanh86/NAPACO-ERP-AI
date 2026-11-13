(() => {
  const $ = id => document.getElementById(id), form = $('templateForm');
  let selected = null, items = [], page = 1, query = '', busy = false;
  let sourceEpoch = 0;
  const element = (tag, text) => {const node = document.createElement(tag); if (text != null) node.textContent = text; return node;};
  function message(text) {$('message').textContent = text;}
  async function api(url, options = {}) {
    const response = await fetch(url, {cache:'no-store', ...options});
    const body = await response.json();
    if (response.status === 401) location.assign('/login?next=' + encodeURIComponent(location.pathname));
    if (!response.ok) throw Error(typeof body.detail === 'string' ? body.detail :
      (body.detail || []).map(item => item.msg).join('; ') || 'Không thực hiện được yêu cầu.');
    return body;
  }
  async function work(action) {
    if (busy) return;
    busy = true;
    const controls = [...document.querySelectorAll('button,input,select')];
    const disabled = controls.map(node => node.disabled);
    controls.forEach(node => {node.disabled = true;});
    message('Đang xử lý…');
    try {await action();} catch (error) {message(error.message);}
    finally {controls.forEach((node, index) => {node.disabled = disabled[index];}); busy = false; pagination();}
  }
  let hasMore = false;
  function pagination() {$('previous').disabled = busy || page <= 1; $('next').disabled = busy || !hasMore;}
  function clearPreview() {
    sourceEpoch++; $('previewPanel').hidden = true; $('sheetPreview').replaceChildren(); $('sourceInfo').textContent = '';
  }
  function edit(row) {
    if (busy) return;
    selected = row; form.reset();
    if (row) for (const key of ['form_code','form_name','check_type','object_type','product_id','version','status']) form.elements[key].value = row[key] ?? '';
    form.elements.spreadsheet.value = row?.spreadsheet_id || '';
    $('editorTitle').textContent = row ? 'Sửa template ' + row.form_code : 'Thêm template mới';
    $('save').textContent = row ? 'Lưu thay đổi' : 'Đăng ký template';
    clearPreview(); message('');
    $('editor').scrollIntoView({behavior:'smooth'});
  }
  async function load(targetPage, keyword = query) {
    const data = await api('/api/qc/templates?' + new URLSearchParams({q:keyword,page:targetPage}));
    items = data.items; page = targetPage; query = keyword; hasMore = data.has_more;
    $('templates').replaceChildren(...items.map(row => {
      const tr = element('tr');
      for (const value of [row.form_code + ' · v' + row.version,row.form_name,row.check_type,row.object_type || 'Tất cả',row.product_id || 'Áp dụng chung',row.spreadsheet_id,row.status]) tr.append(element('td', value));
      const actions = element('td'), open = element('button','Sửa'), preview = element('button','Xem trước');
      open.type = preview.type = 'button'; open.onclick = () => edit(row);
      preview.onclick = () => work(async () => {
        clearPreview(); const data = await api('/api/qc/templates/' + encodeURIComponent(row.id) + '/preview');
        showPreview(data); message('Đã đọc template ' + row.form_code + '.');
      });
      actions.append(open, preview); tr.append(actions); return tr;
    }));
    $('listHint').textContent = items.length ? items.length + ' template trên trang này.' : 'Không có template phù hợp.';
    $('pageInfo').textContent = 'Trang ' + page;
  }
  function showPreview(data) {
    window.QCSheetPreview.render($('sheetPreview'), data);
    $('previewInfo').textContent = data.title + ' · Tab đầu tiên: ' + data.sheet_title + ' · Google: ' + (data.google_email || '') +
      (data.truncated ? ' · Giới hạn vùng A1, tối đa 500 hàng × 60 cột; có thể chưa hiển thị hết bảng.' : '');
    $('previewPanel').hidden = false;
  }
  async function inspect(preview) {
    const spreadsheet = form.elements.spreadsheet.value.trim();
    if (!spreadsheet) throw Error('Hãy nhập Spreadsheet ID hoặc URL.');
    clearPreview(); const epoch = sourceEpoch;
    const data = await api('/api/qc/templates/inspect', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({spreadsheet,preview})});
    if (epoch !== sourceEpoch) return;
    $('sourceInfo').textContent = 'Đọc thành công: ' + data.title + ' · ' + data.sheet_title + ' · SHEET_ID: ' + data.sheet_id + ' · ' + (data.google_email || '');
    if (preview) showPreview(data);
    message('Kết nối thành công. Google Sheets gốc chỉ được đọc.');
  }
  $('search').onsubmit = event => {event.preventDefault(); work(async () => {await load(1, $('query').value.trim()); message('Đã tải danh sách.');});};
  $('previous').onclick = () => work(async () => {await load(page - 1); message('Đã tải danh sách.');});
  $('next').onclick = () => work(async () => {await load(page + 1); message('Đã tải danh sách.');});
  $('newTemplate').onclick = () => edit(null);
  $('connection').onclick = () => work(() => inspect(false));
  $('preview').onclick = () => work(() => inspect(true));
  form.elements.spreadsheet.addEventListener('input', clearPreview);
  form.onsubmit = event => {
    event.preventDefault();
    // Capture before work() disables controls (disabled fields are absent from FormData).
    const values = Object.fromEntries(new FormData(form));
    values.product_id ||= null; values.object_type ||= null; values.version = Number(values.version);
    values.expected_updated_at = selected?.updated_at || null;
    const identifier = selected?.id;
    work(async () => {
      const row = await api('/api/qc/templates' + (identifier ? '/' + encodeURIComponent(identifier) : ''),
        {method:identifier?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
      selected = row; $('editorTitle').textContent = 'Sửa template ' + row.form_code; $('save').textContent = 'Lưu thay đổi';
      await load(1, ''); $('query').value = '';
      message('Đã lưu ' + row.form_code + ' ở trạng thái ' + row.status + '. Chưa áp dụng vào Tạo Phiếu QC.');
    });
  };
  window.NAPACO_IDENTITY.then(user => {
    if (!user.permissions.includes('QC_TEMPLATE_MANAGE')) {
      document.querySelectorAll('main button,main input,main select').forEach(node => {node.disabled=true;});
      message('Bạn chưa có quyền quản lý template QC.');
    }
  }).catch(error => message(error.message));
})();
