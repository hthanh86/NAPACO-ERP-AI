function filmReceiptAccess_(readOnly = false) {
  const env = getSecureEnv_();
  const names = CONFIG.SHEET_NAMES;
  const master = readOnly ? createReadBook_(env.ID_MASTER, [
    names.EMPLOYEES, names.PERMISSIONS, names.CUSTOMERS, names.PRODUCTS,
    [names.FILM_MATERIALS, names.FILM_MATERIALS_LEGACY],
    [names.FILM_SUPPLIERS, names.FILM_SUPPLIERS_LEGACY]
  ]) : SpreadsheetApp.openById(env.ID_MASTER);
  const access = readUserPermissions_(master);
  if (access.role === 'KTV') throw new Error('Vai trò KTV không có quyền nhận màng.');
  requirePermission_(access, CONFIG.PERMISSIONS.NVL_RECEIVE);
  const operation = readOnly ? createReadBook_(env.ID_OPERATION, [
    names.FILM_PO, names.FILM_LINES, names.FILM_RECEIPTS, names.ORDER_DETAILS, names.ORDERS
  ]) : SpreadsheetApp.openById(env.ID_OPERATION);
  return { ...access, master, operation };
}

function filmReceiptTables_(operation, forSave = true) {
  const { FILM_PO: po, FILM_LINES: line, FILM_RECEIPTS: receipt } = CONFIG.COLUMNS;
  const names = CONFIG.SHEET_NAMES;
  const orders = readSheetTable_(operation, [names.FILM_PO], [po.ID, po.STATUS, po.SUPPLIER]);
  const lines = readSheetTable_(operation, [names.FILM_LINES],
    [line.ID, line.PO_ID, line.MATERIAL_ID, line.RESIN, line.QTY, line.STATUS]);
  const incoming = readSheetTable_(operation, [names.FILM_RECEIPTS],
    forSave ? Object.values(receipt) : [receipt.ID, receipt.LINE_ID, receipt.QTY]);
  return { orders, lines, incoming, totals: filmReceiptTotals_(incoming) };
}

function filmReceivableLine_(line, order, received) {
  const { FILM_PO: po, FILM_LINES: col } = CONFIG.COLUMNS;
  if (!line[col.ID] || !order || order[po.STATUS] === 'Hủy') return false;
  const ordered = Number(line[col.QTY]);
  const status = filmLineStatus_(line[col.STATUS], ordered, received);
  return Number.isFinite(ordered) && ordered > 0 &&
    (status === FILM_RECEIPT_LINE_STATUS.WAITING || status === FILM_RECEIPT_LINE_STATUS.PARTIAL);
}

function getFilmReceiptLines() {
  const { FILM_PO: po, FILM_LINES: line, FILM_MATERIALS: material, FILM_SUPPLIERS: supplier } = CONFIG.COLUMNS;
  const { master, operation } = filmReceiptAccess_(true);
  const db = filmReceiptTables_(operation, false);
  const orders = new Map(db.orders.rows.map(({ data }) => [data[po.ID], data]));
  const materials = new Map(filmMaterials_(master).rows.map(({ data }) => [data[material.ID], data]));
  const names = CONFIG.SHEET_NAMES;
  const suppliers = new Map(readSheetTable_(master, [names.FILM_SUPPLIERS, names.FILM_SUPPLIERS_LEGACY],
    [supplier.ID, supplier.NAME]).rows.map(({ data }) => [data[supplier.ID], data[supplier.NAME]]));
  const lines = [];
  for (const { data } of db.lines.rows) {
    const id = data[line.ID];
    const order = orders.get(data[line.PO_ID]);
    const received = db.totals.get(id)?.kg || 0;
    if (!filmReceivableLine_(data, order, received)) continue;
    const spec = materials.get(data[line.MATERIAL_ID]) || {};
    const size = [spec[material.THICKNESS], spec[material.WIDTH]].filter(Boolean).join('*');
    const ordered = Number(data[line.QTY]);
    lines.push({
      id, po: order[po.ID], supplier: suppliers.get(order[po.SUPPLIER]) || order[po.SUPPLIER], ordered, received,
      status: filmLineStatus_(data[line.STATUS], ordered, received),
      spec: [data[line.RESIN], spec[material.GRADE],
        spec[material.COLOR], spec[material.ESD], size].filter(Boolean).join(' · ')
    });
  }
  const namesByLine = filmNamesByLine_({ master, operation }, new Set(lines.map(line => line.id)));
  for (const line of lines) line.customerProducts = namesByLine.get(line.id) || [];
  return { lines, today: filmDate_(new Date()) };
}

function saveFilmReceipt(payload) {
  const result = saveFilmReceipts({ token: payload && payload.token, receipts: [payload] });
  return { id: result.ids[0] };
}

function saveFilmReceipts(payload) {
  const access = filmReceiptAccess_();
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    return filmSaveReceiptsLocked_(access, payload);
  } finally {
    lock.releaseLock();
  }
}

function filmSaveReceiptsLocked_({ operation, userId }, payload) {
  const { FILM_PO: po, FILM_LINES: line, FILM_RECEIPTS: col } = CONFIG.COLUMNS;
  const token = sheetText_(payload && payload.token);
  if (!/^[a-f0-9-]{36}$/i.test(token) || !Array.isArray(payload.receipts) || !payload.receipts.length) {
    throw new Error('Danh sách lưu tạm hoặc mã phiên nhập kho không hợp lệ.');
  }
  const db = filmReceiptTables_(operation);
  const rows = db.incoming.rows;
  const marker = 'NAPACO_NVL_RECEIPT:' + userId + ':' + token;
  if (rows.length) {
    const firstRow = rows[0].index;
    const notes = db.incoming.sheet.getRange(firstRow + 1, db.incoming.positions.get(col.ID) + 1, rows.length, 1).getNotes();
    const prior = rows.filter(({ index }) => notes[index - firstRow][0] === marker);
    if (prior.length) return { ids: prior.map(row => row.data[col.ID]) };
  }

  const indexUnique = (rows, key) => {
    const index = new Map();
    for (const row of rows) {
      const id = row.data[key];
      if (id) index.set(id, index.has(id) ? null : row);
    }
    return index;
  };
  const lines = indexUnique(db.lines.rows, line.ID);
  const orders = indexUnique(db.orders.rows, po.ID);
  const used = new Set();
  const sequences = new Map();
  const ids = [];
  const requests = [];
  const appendRows = [];
  for (const entry of payload.receipts) {
    const dn = sheetText_(entry && entry.dn);
    if (!dn || used.has(dn)) throw new Error('Danh sách lưu tạm thiếu hoặc trùng DN_ID.');
    used.add(dn);
    const row = lines.get(dn);
    if (!row) throw new Error(dn + ' không tồn tại hoặc bị trùng.');
    const order = orders.get(row.data[line.PO_ID])?.data;
    const received = db.totals.get(dn)?.kg || 0;
    if (!filmReceivableLine_(row.data, order, received)) {
      throw new Error(dn + ' không còn mở để nhận. Hãy tải lại danh sách.');
    }
    const ordered = Number(row.data[line.QTY]);
    if (entry.received !== received || entry.ordered !== ordered) {
      throw new Error('Số kg đặt hoặc đã nhận của ' + dn + ' đã thay đổi. Hãy tải lại và sửa dòng lưu tạm.');
    }

    const date = filmInputDate_(entry.date, true);
    const productionDate = filmInputDate_(entry.productionDate, false);
    if (productionDate && productionDate > date) throw new Error(dn + ': ngày sản xuất sau ngày nhận.');
    const rolls = filmNumber_(entry.rolls, true, 'Số cuộn của ' + dn);
    if (!Number.isSafeInteger(rolls)) throw new Error(dn + ': số cuộn phải là số nguyên dương.');
    const kg = filmNumber_(entry.kg, true, 'Số kg nhận của ' + dn);
    const quality = sheetText_(entry.quality);
    const note = sheetText_(entry.note);
    if (!['OK', 'NG'].includes(quality) || (quality === 'NG' && !note)) {
      throw new Error(dn + ': chọn OK hoặc NG. Nếu chọn NG, hãy nhập ghi chú.');
    }

    const prefix = 'N_NVL_' + date.slice(2).replace(/-/g, '') + '_';
    const sequence = (sequences.get(prefix) ?? filmHighest_(db.incoming, col.ID, prefix, 2)) + 1;
    if (sequence > 99) throw new Error(date + ' đã đạt giới hạn 99 mã nhập NVL.');
    sequences.set(prefix, sequence);
    const id = prefix + String(sequence).padStart(2, '0');
    ids.push(id);
    const append = [];
    filmWrite_(append, db.incoming, null, {
      [col.ID]: id, [col.DATE]: date, [col.PRODUCTION_DATE]: productionDate, [col.LINE_ID]: dn,
      [col.ROLLS]: rolls, [col.QTY]: kg, [col.LOCATION]: sheetText_(entry.location),
      [col.STATUS]: quality, [col.USER]: userId, [col.IQC_ID]: '', [col.NOTE]: note
    });
    const receiptRow = append[0].appendCells.rows[0];
    // A retried request finds the IDs from the same committed batch.
    receiptRow.values[db.incoming.positions.get(col.ID)].note = marker;
    appendRows.push(receiptRow);
    filmWrite_(requests, db.lines, row.index, { [line.STATUS]: filmReceivedStatus_(ordered, received + kg) });
  }
  requests.unshift({ appendCells: { sheetId: db.incoming.sheet.getSheetId(), rows: appendRows, fields: '*' } });
  Sheets.Spreadsheets.batchUpdate({ requests }, operation.getId());
  return { ids };
}
