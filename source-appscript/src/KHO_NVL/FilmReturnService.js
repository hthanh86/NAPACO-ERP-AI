/** Auto returns keep their issue reference in the MV_NVL_ID cell note.
 * Never edit or copy that note when entering manual transactions.
 */
const FILM_AUTO_RETURN_NOTE_ = 'NAPACO_AUTO_RETURN_V1:';

function filmReturnAccess_(feature) {
  const env = getSecureEnv_(), n = CONFIG.SHEET_NAMES;
  const master = createReadBook_(env.ID_MASTER, [n.EMPLOYEES, n.PERMISSIONS]);
  const access = readUserPermissions_(master);
  requirePermission_(access, feature);
  return { ...access, operation: SpreadsheetApp.openById(env.ID_OPERATION) };
}

function filmReturnTable_(operation) {
  const c = CONFIG.COLUMNS.FILM_MOVEMENTS;
  const table = readSheetTable_(operation, [CONFIG.SHEET_NAMES.FILM_MOVEMENTS], Object.values(c));
  const count = table.sheet.getLastRow();
  const notes = count ? table.sheet.getRange(1, table.positions.get(c.ID) + 1, count, 1).getNotes() : [];
  const ids = new Set();
  table.rows = table.rows.filter(({ data }) => Object.values(data).some(Boolean));
  table.rows.forEach(row => {
    const id = row.data[c.ID];
    if (!id || ids.has(id)) throw new Error('Mã giao dịch cấp/trả thiếu hoặc trùng: ' + id);
    ids.add(id);
    const note = notes[row.index]?.[0] || '';
    row.sourceId = note.startsWith(FILM_AUTO_RETURN_NOTE_) ? note.slice(FILM_AUTO_RETURN_NOTE_.length) : '';
  });
  return table;
}

/** Pure calculation, shared by synchronization and regression tests. */
function filmReturnPlan_(rows, logs, requestedId) {
  const c = CONFIG.COLUMNS.FILM_MOVEMENTS, j = CONFIG.COLUMNS.FORMING_LOG;
  const byId = new Map(rows.map(row => [row.data[c.ID], row]));
  const requested = byId.get(requestedId);
  if (!requested) throw new Error('Không tìm thấy giao dịch ' + requestedId);
  const sourceId = requested.sourceId || requestedId;
  const issue = byId.get(sourceId);
  const type = row => sheetText_(row.data[c.TYPE]).normalize('NFC').toUpperCase();
  if (!issue || type(issue) !== 'CẤP NVL') throw new Error('Không xác định được lần cấp gốc của ' + requestedId);
  const related = rows.filter(row => row.sourceId === sourceId);
  for (const row of related) if (type(row) !== 'TRẢ NVL' ||
    row.data[c.RECEIPT_ID] !== issue.data[c.RECEIPT_ID] || row.data[c.ORDER_ID] !== issue.data[c.ORDER_ID]) {
    throw new Error('Liên kết phiếu trả không hợp lệ: ' + row.data[c.ID]);
  }
  const pending = related.filter(row => !row.data[c.RECEIVER]);
  if (pending.length > 1) throw new Error('Có nhiều phiếu trả chờ cho lần cấp ' + sourceId);
  const references = new Set([sourceId, ...related.map(row => row.data[c.ID])]);
  let used = 0, entries = 0;
  for (const { data } of logs) {
    if (!references.has(data[j.MOVEMENT_ID])) continue;
    if ([j.WEIGHT, j.GOOD, j.NG].some(key => sheetText_(data[key]) === '')) {
      throw new Error('Nhật ký của ' + data[j.MOVEMENT_ID] + ' chưa đủ trọng lượng và sản lượng.');
    }
    const weight = filmStockNumber_(data[j.WEIGHT], j.WEIGHT);
    if (weight <= 0) throw new Error('Trọng lượng bìa phải lớn hơn 0.');
    const good = filmStockNumber_(data[j.GOOD], j.GOOD), ng = filmStockNumber_(data[j.NG], j.NG);
    if (!Number.isSafeInteger(good) || !Number.isSafeInteger(ng)) throw new Error('Sản lượng bìa phải là số nguyên.');
    used += weight * (good + ng) / 1000;
    entries++;
  }
  const issued = filmStockNumber_(issue.data[c.QTY], sourceId);
  const confirmed = related.filter(row => row.data[c.RECEIVER])
    .reduce((sum, row) => sum + filmStockNumber_(row.data[c.QTY], row.data[c.ID]), 0);
  const remaining = Math.round((issued - used - confirmed) * 1e8) / 1e8;
  if (remaining < 0) throw new Error('Tổng sử dụng và trả đã nhận vượt số kg cấp của ' + sourceId + '. Cần kiểm tra nhật ký.');
  if (confirmed > 0 && remaining > 0) throw new Error('Nhật ký đã thay đổi sau khi kho nhận trả. Cần đối chiếu trước khi điều chỉnh.');
  return { sourceId, issue, pending: pending[0], used, remaining, entries };
}

function filmSyncReturnLocked_(operation, movementId, userId) {
  const table = filmReturnTable_(operation), j = CONFIG.COLUMNS.FORMING_LOG, c = CONFIG.COLUMNS.FILM_MOVEMENTS;
  const logs = readSheetTable_(operation, [CONFIG.SHEET_NAMES.FORMING_LOG], Object.values(j));
  const plan = filmReturnPlan_(table.rows, logs.rows, sheetText_(movementId));
  // No completed journal means no evidence that production has finished a line.
  if (!plan.entries) return { id: '', kg: 0, used: 0, changed: false };
  const writes = [];
  let id = plan.pending?.data[c.ID] || '';
  if (plan.pending) {
    const previous = filmStockNumber_(plan.pending.data[c.QTY], id);
    if (Math.abs(previous - plan.remaining) < 1e-8) return { id, kg: plan.remaining, used: plan.used, changed: false };
    filmWrite_(writes, table, plan.pending.index, { [c.QTY]: plan.remaining });
  } else if (plan.remaining > 0) {
    id = 'MV_TRA_AUTO_' + Utilities.getUuid();
    filmWrite_(writes, table, null, {
      [c.ID]: id, [c.DATE]: Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyyy-MM-dd HH:mm:ss'),
      [c.TYPE]: 'TRẢ NVL', [c.ORDER_ID]: plan.issue.data[c.ORDER_ID],
      [c.RECEIPT_ID]: plan.issue.data[c.RECEIPT_ID], [c.QC_ID]: plan.issue.data[c.QC_ID],
      [c.QTY]: plan.remaining, [c.ISSUER]: userId, [c.RECEIVER]: '',
      [c.NOTE]: 'Trả tự động từ lần cấp ' + plan.sourceId
    });
    writes[0].appendCells.rows[0].values[table.positions.get(c.ID)].note = FILM_AUTO_RETURN_NOTE_ + plan.sourceId;
  }
  if (writes.length) Sheets.Spreadsheets.batchUpdate({ requests: writes }, operation.getId());
  return { id, kg: plan.remaining, used: plan.used, changed: writes.length > 0 };
}

/** Call AFTER a journal save; pass its MV_NVL_ID (original issue or pending return).
 * Journal writes must use the same ScriptLock and call filmSyncReturnLocked_
 * before releasing it. This RPC also supports retries/repair after a saved log.
 */
function syncFilmReturnFromJournal(movementId) {
  const access = filmReturnAccess_(CONFIG.PERMISSIONS.PRODUCTION_EDIT);
  const lock = LockService.getScriptLock();lock.waitLock(30000);
  try { return filmSyncReturnLocked_(access.operation, movementId, access.userId); }
  finally { lock.releaseLock(); }
}

function confirmFilmReturn(payload) {
  const access = filmReturnAccess_(CONFIG.PERMISSIONS.NVL_RECEIVE);
  requirePermission_(access, CONFIG.PERMISSIONS.NVL_STOCK_VIEW);
  const id = sheetText_(payload && payload.id);
  const expected = filmStockNumber_(payload && payload.kg, 'Số kg cần xác nhận');
  const lock = LockService.getScriptLock();lock.waitLock(30000);
  try {
    const c = CONFIG.COLUMNS.FILM_MOVEMENTS;
    let table = filmReturnTable_(access.operation);
    let row = table.rows.find(row => row.data[c.ID] === id);
    if (!row || sheetText_(row.data[c.TYPE]).normalize('NFC').toUpperCase() !== 'TRẢ NVL') throw new Error('Không tìm thấy phiếu trả.');
    if (row.data[c.RECEIVER]) return { id, alreadyConfirmed: true };
    if (row.sourceId) {
      filmSyncReturnLocked_(access.operation, id, access.userId);
      table = filmReturnTable_(access.operation);
      row = table.rows.find(row => row.data[c.ID] === id);
    }
    const current = filmStockNumber_(row.data[c.QTY], id);
    if (current <= 0 || Math.abs(current - expected) >= 1e-8) throw new Error('Số kg trả đã thay đổi. Hãy tải lại trước khi xác nhận.');
    const writes = [];
    filmWrite_(writes, table, row.index, { [c.RECEIVER]: access.userId });
    Sheets.Spreadsheets.batchUpdate({ requests: writes }, access.operation.getId());
    return { id, kg: current };
  } finally { lock.releaseLock(); }
}
