const FILM_RECEIPT_LINE_STATUS = Object.freeze({
  WAITING: 'Chờ Nhận',
  PARTIAL: 'Nhận một phần',
  CLOSED: 'Đóng'
});

function filmReceivedStatus_(ordered, received) {
  const status = FILM_RECEIPT_LINE_STATUS;
  if (received <= 0) return status.WAITING;
  return received + 1e-8 >= ordered ? status.CLOSED : status.PARTIAL;
}

function filmLineStatus_(stored, ordered, received) {
  if (stored && stored.toLowerCase() === 'chờ nhận') return FILM_RECEIPT_LINE_STATUS.WAITING;
  if (stored && stored.toLowerCase() !== 'chờ nhập') return stored;
  return filmReceivedStatus_(ordered, received || 0);
}

function filmReceiptTotals_(incoming) {
  const col = CONFIG.COLUMNS.FILM_RECEIPTS;
  const totals = new Map();
  const seen = new Set();
  for (const { data } of incoming.rows) {
    const id = data[col.ID];
    const dn = data[col.LINE_ID];
    const kg = Number(data[col.QTY]);
    if (id && seen.has(id)) throw new Error('Mã phiếu nhận bị trùng: ' + id + '.');
    if (id) seen.add(id);
    if (!dn) continue;
    if (!id || !data[col.QTY] || !Number.isFinite(kg) || kg < 0) {
      throw new Error('Kiểm tra mã phiếu và số kg của các dòng kho có DN_ID.');
    }
    const linked = totals.get(dn) || { kg: 0, ids: [] };
    linked.kg += kg;
    linked.ids.push(id);
    totals.set(dn, linked);
  }
  return totals;
}

function getFilmOrders(filters = {}) {
  const { FILM_PO: FilmPo, FILM_LINES: FilmLine, FILM_MATERIALS: FilmMaterial } = CONFIG.COLUMNS;
  const access = filmAccess_(filters.create ? CONFIG.PERMISSIONS.FILM_PO_CREATE : CONFIG.PERMISSIONS.FILM_PO_VIEW, true);
  const db = filmDatabase_(access, true);
  const canViewStock = access.permissions.get(CONFIG.PERMISSIONS.NVL_STOCK_VIEW) === true;
  const copyIds = filters.create ? [...new Set((Array.isArray(filters.copyIds) ? filters.copyIds : [])
    .map(sheetText_).filter(Boolean))] : [];
  if (copyIds.length > 99) throw new Error('Mỗi đơn tối đa 99 dòng quy cách.');
  let orders = filters.create && !copyIds.length ? [] : filmOrders_(db, sheetText_(filters.orderId) || null, false);
  let copyLines = [];
  let copySupplier = '';
  let mixedSuppliers = false;
  let matchingLines = 0;
  const lineStatuses = new Set(Object.values(FILM_RECEIPT_LINE_STATUS));
  if (filters.create && copyIds.length) {
    const selection = new Map();
    const requested = new Set(copyIds);
    for (const order of orders) {
      for (const line of order.lines) {
        const id = line[FilmLine.ID];
        if (!requested.has(id)) continue;
        if (selection.has(id)) throw new Error('DN_ID bị trùng: ' + id + '.');
        const fields = [FilmLine.RESIN, FilmLine.MATERIAL_ID, FilmLine.QTY, FilmLine.PRICE, FilmLine.DELIVERY, FilmLine.NOTE];
        const copy = Object.fromEntries(fields.filter(key => line[key] !== undefined).map(key => [key, line[key]]));
        selection.set(id, { line: { ...copy, material: line.material }, supplier: order[FilmPo.SUPPLIER] || '' });
      }
    }
    if (selection.size !== copyIds.length) throw new Error('Có quy cách đã chọn không còn trong database.');
    const selected = copyIds.map(id => selection.get(id));
    const suppliers = new Set(selected.map(entry => entry.supplier));
    mixedSuppliers = suppliers.size > 1;
    copySupplier = mixedSuppliers ? '' : selected[0].supplier;
    copyLines = selected.map(entry => entry.line);
    orders = [];
  } else if (!filters.create && !filters.orderId) {
    const supplierNames = new Map(db.suppliers.map(row =>
      [row[CONFIG.COLUMNS.FILM_SUPPLIERS.ID], row[CONFIG.COLUMNS.FILM_SUPPLIERS.NAME]]));
    const terms = sheetText_(filters.search).toLowerCase().split(/\s+/).filter(Boolean);
    const getNames = groups => filmNamesByLine_(db,
      new Set(groups.flatMap(order => order.lines.map(line => line[FilmLine.ID]))));
    const searchNames = terms.length ? getNames(orders) : null;
    let remaining = 1000;
    orders = orders.flatMap(order => {
      const statusFor = line => order[FilmPo.STATUS] === 'Hủy' ? 'Hủy' : line[FilmLine.STATUS];
      order.lines.forEach(line => lineStatuses.add(statusFor(line)));
      const day = order[FilmPo.DATE] || '';
      const supplier = order[FilmPo.SUPPLIER];
      if ((filters.supplier && supplier !== filters.supplier) || (filters.from && day < filters.from) ||
          (filters.to && (!day || day > filters.to))) return [];
      const matches = order.lines.filter(line => {
        if (filters.status && statusFor(line) !== filters.status) return false;
        if (!terms.length) return true;
        const searchable = filmLineSearchText_(order, line, supplierNames.get(supplier),
          searchNames.get(line[FilmLine.ID]) || [], canViewStock);
        return terms.every(term => searchable.includes(term));
      });
      matchingLines += matches.length;
      const lines = matches.slice(0, remaining);
      remaining -= lines.length;
      return lines.length ? [{ ...order, lines }] : [];
    });
    const names = searchNames || getNames(orders);
    for (const order of orders) {
      for (const line of order.lines) {
        line.customerProducts = names.get(line[FilmLine.ID]) || [];
        line.searchText = filmLineSearchText_(order, line, supplierNames.get(order[FilmPo.SUPPLIER]),
          line.customerProducts, canViewStock);
      }
    }
  } else if (filters.orderId && orders.length) {
    // Compute the revision on the full order before adding permission-dependent display fields.
    const order = orders[0];
    order.revision = filmOrderRevision_(order);
  }
  for (const order of orders) {
    for (const line of order.lines) {
      line.hasAssignmentColumn = db.details.positions.has(CONFIG.COLUMNS.ORDER_DETAILS.FILM_LINE_ID);
      line.canAssign = access.permissions.get(CONFIG.PERMISSIONS.FILM_PO_ASSIGN) === true && line.hasAssignmentColumn &&
        order[FilmPo.STATUS] !== 'Hủy' && line[FilmLine.STATUS] !== 'Hủy';
      if (!canViewStock) {
        line.received = null;
        line.receiptIds = [];
      }
    }
    if (!canViewStock) {
      order.received = null;
      if (order[FilmPo.STATUS] !== 'Hủy') order.progress = 'Chưa rõ';
    }
  }
  return {
    orders, matchingLines, copyLines, copySupplier, mixedSuppliers,
    ...(filters.formData && (filters.create || (filters.orderId && orders.length)) ? {
      formData: filmOrderFormData_(access, filters.create ? null : orders[0].lines
        .filter(line => line.hasAssignmentColumn).map(line => line[FilmLine.ID]), true)
    } : {}),
    filterStatuses: [...lineStatuses].filter(Boolean),
    fields: {
      po: FilmPo, line: FilmLine, material: FilmMaterial, supplier: CONFIG.COLUMNS.FILM_SUPPLIERS
    },
    suppliers: db.suppliers,
    materials: db.materials.rows.map(row => row.data).filter(row => row[FilmMaterial.ID]),
    today: filmDate_(new Date()),
    setup: db.setup,
    permissions: {
      create: access.permissions.get(CONFIG.PERMISSIONS.FILM_PO_CREATE) === true,
      edit: access.permissions.get(CONFIG.PERMISSIONS.FILM_PO_EDIT) === true,
      assign: access.permissions.get(CONFIG.PERMISSIONS.FILM_PO_ASSIGN) === true
    },
    canEditWithReceipts: !db.receiptWarning,
    lineStatuses: Object.values(FILM_RECEIPT_LINE_STATUS),
    receiptWarning: canViewStock ? db.receiptWarning : ''
  };
}

function filmLineSearchText_(order, line, supplierName, names, canViewStock) {
  const { FILM_PO: po, FILM_LINES: col, FILM_MATERIALS: material } = CONFIG.COLUMNS;
  const spec = line.material;
  return [order[po.ID], order[po.SUPPLIER], supplierName, line[col.ID], line[col.MATERIAL_ID],
    line[col.RESIN], line[col.NOTE], ...Object.values(spec), spec[material.THICKNESS] + '*' + spec[material.WIDTH],
    ...names, ...(canViewStock ? line.receiptIds : [])].join(' ').toLowerCase();
}

function filmDetailNameIndex_(db, rows) {
  const { ORDER_DETAILS: detail, ORDERS: order, CUSTOMERS: customer, PRODUCTS: product } = CONFIG.COLUMNS;
  const names = CONFIG.SHEET_NAMES;
  const ids = (key, entries) => new Set(entries.map(({ data }) => data[key]).filter(Boolean));
  const index = (book, name, key, value, wanted) => wanted.size ? new Map(
    readSheetTable_(book, [name], [key, value], [],
      (cells, positions) => wanted.has(sheetText_(cells[positions.get(key)]))).rows
      .map(({ data }) => [data[key], data[value]])) : new Map();
  const orders = index(db.operation, names.ORDERS, order.ID, order.CUSTOMER_ID, ids(detail.ORDER_ID, rows));
  const customers = index(db.master, names.CUSTOMERS, customer.ID, customer.NAME, new Set(orders.values()));
  const products = index(db.master, names.PRODUCTS, product.ID, product.NAME, ids(detail.PRODUCT_ID, rows));
  return { orders, customers, products };
}

function filmNamesByLine_(db, lineIds) {
  const detail = CONFIG.COLUMNS.ORDER_DETAILS;
  const names = new Map();
  if (!lineIds.size) return names;
  const { rows } = readSheetTable_(db.operation, [CONFIG.SHEET_NAMES.ORDER_DETAILS],
    [detail.ID, detail.ORDER_ID, detail.PRODUCT_ID], [detail.FILM_LINE_ID],
    (cells, positions) => positions.has(detail.FILM_LINE_ID) &&
      lineIds.has(sheetText_(cells[positions.get(detail.FILM_LINE_ID)])) &&
      !!sheetText_(cells[positions.get(detail.ID)]));
  if (!rows.length) return names;

  const { orders, customers, products } = filmDetailNameIndex_(db, rows);
  for (const { data } of rows) {
    const id = data[detail.FILM_LINE_ID];
    const customerId = orders.get(data[detail.ORDER_ID]);
    const productId = data[detail.PRODUCT_ID];
    const label = [customers.get(customerId) || customerId, products.get(productId) || productId]
      .filter(Boolean).join(' · ');
    if (!label) continue;
    if (!names.has(id)) names.set(id, new Set());
    names.get(id).add(label);
  }
  return new Map([...names].map(([id, labels]) => [id, [...labels]]));
}

function filmDescribeDetails_(db, rows, summaryOnly = false) {
  const { ORDER_DETAILS: FilmDetail } = CONFIG.COLUMNS;
  if (!rows.length) return [];
  const { orders, customers, products } = filmDetailNameIndex_(db, rows);
  return rows.map(({ data }) => ({
    id: data[FilmDetail.ID],
    customer: customers.get(orders.get(data[FilmDetail.ORDER_ID])) || '',
    product: products.get(data[FilmDetail.PRODUCT_ID]) || '',
    ...(summaryOnly ? { orderId: data[FilmDetail.ORDER_ID] || '' } : {
      qty: data[FilmDetail.QTY_ORDER] || '',
      delivery: data[FilmDetail.DELIVERY_DATE] || '',
      assigned: !!data[FilmDetail.FILM_LINE_ID],
      editable: data[FilmDetail.STATUS] === CONFIG.LINE_STATUS.NEW
    })
  }));
}

function filmDetails_(operation, headersOnly = false, include, summaryOnly = false) {
  const detail = CONFIG.COLUMNS.ORDER_DETAILS;
  return readSheetTable_(operation, [CONFIG.SHEET_NAMES.ORDER_DETAILS],
    [detail.ID, detail.STATUS], [detail.FILM_LINE_ID, detail.ORDER_ID, detail.PRODUCT_ID,
      ...(summaryOnly ? [] : [detail.QTY_ORDER, detail.DELIVERY_DATE])], include, headersOnly);
}

function filmAssignmentRows_(operation, lineId, includeAvailable) {
  const { ORDER_DETAILS: FilmDetail } = CONFIG.COLUMNS;
  const details = filmDetails_(operation, false, (cells, positions) => {
    const detail = CONFIG.COLUMNS.ORDER_DETAILS;
    const link = sheetText_(cells[positions.get(detail.FILM_LINE_ID)]);
    return !!sheetText_(cells[positions.get(detail.ID)]) &&
      ((lineId && link === lineId) ||
        (includeAvailable && !link && sheetText_(cells[positions.get(detail.STATUS)]) === CONFIG.LINE_STATUS.NEW));
  });
  if (!details.positions.has(CONFIG.COLUMNS.ORDER_DETAILS.FILM_LINE_ID)) {
    throw new Error(CONFIG.SHEET_NAMES.ORDER_DETAILS + ' thiếu cột ' + FilmDetail.FILM_LINE_ID + '.');
  }
  return details;
}

function filmAssertAssignmentLine_(operation, lineId) {
  const { FILM_PO: FilmPo, FILM_LINES: FilmLine } = CONFIG.COLUMNS;
  const names = CONFIG.SHEET_NAMES;
  const lines = readSheetTable_(operation, [names.FILM_LINES], [FilmLine.ID, FilmLine.STATUS], [FilmLine.PO_ID]);
  const matches = lines.rows.filter(({ data }) => data[FilmLine.ID] === lineId);
  if (matches.length !== 1 || matches[0].data[FilmLine.STATUS] === 'Hủy') {
    throw new Error('Dòng đặt màng không tồn tại hoặc không thể sửa.');
  }
  const poId = matches[0].data[FilmLine.PO_ID];
  if (poId && operation.getSheetByName(names.FILM_PO)) {
    const headers = readSheetTable_(operation, [names.FILM_PO], [FilmPo.ID, FilmPo.STATUS]);
    if (headers.rows.some(({ data }) => data[FilmPo.ID] === poId && data[FilmPo.STATUS] === 'Hủy')) {
      throw new Error('Đơn đặt màng đã hủy.');
    }
  }
}

function getFilmOrderFormData(lineIds, lazyDetails = false) {
  const db = filmAccess_(undefined, lineIds === null && lazyDetails ? 'form' : true);
  return filmOrderFormData_(db, lineIds, lazyDetails);
}

function filmOrderFormData_(db, lineIds, lazyDetails) {
  const { SETTINGS: col, FILM_MATERIALS: material } = CONFIG.COLUMNS;
  if (lineIds === null) requirePermission_(db, CONFIG.PERMISSIONS.FILM_PO_CREATE);
  const settings = readErpSettings_(db.master);
  const list = name => [...new Set((settings.get(name) || []).filter(Boolean))];
  const colors = list(col.FILM_COLORS);
  const resins = list(col.RESINS);
  const grades = list(col.GRADES);
  const densities = new Map();
  const densityValues = settings.get(col.DENSITY) || [];
  (settings.get(col.DENSITY_RESIN) || []).forEach((resin, index) => {
    const value = Number(sheetText_(densityValues[index]).replace(',', '.'));
    if (!resin || !Number.isFinite(value) || value <= 0) return;
    const key = resin.toUpperCase();
    const values = densities.get(key) || [];
    if (!values.includes(value)) values.push(value);
    densities.set(key, values);
  });
  const catalogs = {
    colors: colors.length ? colors : [...new Set(filmMaterials_(db.master).rows
      .map(({ data }) => data[material.COLOR]).filter(Boolean))],
    resins, grades, densities: [...densities]
  };
  const today = filmDate_(new Date());
  if (lineIds === null) {
    const choices = !lazyDetails && db.permissions.get(CONFIG.PERMISSIONS.FILM_PO_ASSIGN) === true
      ? filmDescribeDetails_(db, filmAssignmentRows_(db.operation, '', true).rows) : [];
    return { today, ...catalogs, choices };
  }
  return { today, ...catalogs, assignments: filmOrderAssignments_(db, lineIds, lazyDetails) };
}

function getFilmOrderAssignments(lineIds) {
  return filmOrderAssignments_(filmAccess_(undefined, true), lineIds);
}

function filmOrderAssignments_(db, lineIds, summaryOnly = false) {
  const { ORDER_DETAILS: FilmDetail } = CONFIG.COLUMNS;
  if (!Array.isArray(lineIds)) throw new Error('Danh sách quy cách không hợp lệ.');
  const ids = new Set(lineIds.map(sheetText_).filter(Boolean));
  if (!ids.size) return [];
  const { rows } = filmDetails_(db.operation, false, (cells, positions) =>
    !!sheetText_(cells[positions.get(FilmDetail.ID)]) &&
    ids.has(sheetText_(cells[positions.get(FilmDetail.FILM_LINE_ID)])), summaryOnly);
  const entries = filmDescribeDetails_(db, rows, summaryOnly);
  const byLine = new Map();
  rows.forEach(({ data }, index) => {
    if (!byLine.has(data[FilmDetail.FILM_LINE_ID])) byLine.set(data[FilmDetail.FILM_LINE_ID], []);
    byLine.get(data[FilmDetail.FILM_LINE_ID]).push(entries[index]);
  });
  return Array.from(byLine);
}

function getFilmAssignedDetails(lineId) {
  const db = filmAccess_(undefined, true);
  const id = sheetText_(lineId);
  if (!id) throw new Error('Thiếu mã dòng đặt màng.');
  return filmDescribeDetails_(db, filmAssignmentRows_(db.operation, id, false).rows);
}

function getFilmAssignmentOptions(lineId) {
  const db = filmAccess_(CONFIG.PERMISSIONS.FILM_PO_ASSIGN, true);
  const id = sheetText_(lineId);
  if (id) filmAssertAssignmentLine_(db.operation, id);
  return filmDescribeDetails_(db, filmAssignmentRows_(db.operation, id, true).rows);
}

function saveFilmAssignments(lineId, originalIds, selectedIds) {
  const { ORDER_DETAILS: FilmDetail } = CONFIG.COLUMNS;
  const id = sheetText_(lineId);
  if (!id || !Array.isArray(originalIds) || !Array.isArray(selectedIds)) {
    throw new Error('Dữ liệu gán CTDH không hợp lệ.');
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const { operation } = filmAccess_(CONFIG.PERMISSIONS.FILM_PO_ASSIGN);
    filmAssertAssignmentLine_(operation, id);
    const details = filmDetails_(operation);
    if (!details.positions.has(CONFIG.COLUMNS.ORDER_DETAILS.FILM_LINE_ID)) {
      throw new Error(CONFIG.SHEET_NAMES.ORDER_DETAILS + ' thiếu cột ' + FilmDetail.FILM_LINE_ID + '.');
    }
    const original = new Set(originalIds);
    const selected = new Set(selectedIds);
    const linked = details.rows.filter(({ data }) => data[FilmDetail.FILM_LINE_ID] === id);
    if (linked.length !== original.size || linked.some(({ data }) => !original.has(data[FilmDetail.ID]))) {
      throw new Error('CTDH đã thay đổi. Hãy mở lại Sửa/Bổ sung.');
    }
    const byId = new Map();
    for (const row of details.rows) {
      const key = row.data[FilmDetail.ID];
      if (original.has(key) || selected.has(key)) byId.set(key, byId.has(key) ? null : row);
    }
    const requests = [];
    for (const key of new Set([...original, ...selected])) {
      if (original.has(key) === selected.has(key)) continue;
      const row = byId.get(key);
      if (!row || !key || row.data[FilmDetail.STATUS] !== CONFIG.LINE_STATUS.NEW ||
          (row.data[FilmDetail.FILM_LINE_ID] && row.data[FilmDetail.FILM_LINE_ID] !== id)) {
        throw new Error('Không thể đổi gán CTDH ' + key + '. Hãy mở lại Sửa/Bổ sung.');
      }
      filmWrite_(requests, details, row.index, { [FilmDetail.FILM_LINE_ID]: selected.has(key) ? id : '' });
    }
    if (requests.length) Sheets.Spreadsheets.batchUpdate({ requests }, operation.getId());
  } finally {
    lock.releaseLock();
  }
}

function filmDate_(value) {
  return value instanceof Date
    ? Utilities.formatDate(value, CONFIG.TIMEZONE, 'yyyy-MM-dd')
    : sheetText_(value);
}

function filmInputDate_(value, required) {
  const day = sheetText_(value);
  if (!day && !required) return '';
  const parsed = new Date(day + 'T00:00:00Z');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(+parsed) ||
      parsed.toISOString().slice(0, 10) !== day) {
    throw new Error('Ngày không hợp lệ.');
  }
  return day;
}

function filmAccess_(feature = CONFIG.PERMISSIONS.FILM_PO_VIEW, readOnly = false) {
  const env = getSecureEnv_();
  const names = CONFIG.SHEET_NAMES;
  const masterTables = [names.EMPLOYEES, names.PERMISSIONS,
    [names.FILM_MATERIALS, names.FILM_MATERIALS_LEGACY],
    [names.FILM_SUPPLIERS, names.FILM_SUPPLIERS_LEGACY],
    names.CUSTOMERS, names.PRODUCTS, names.SETTINGS];
  const operationTables = [names.FILM_PO, names.FILM_LINES, names.FILM_RECEIPTS,
    names.ORDER_DETAILS, names.ORDERS];
  const selectedMasterTables = readOnly === 'form'
    ? [names.EMPLOYEES, names.PERMISSIONS, names.SETTINGS,
      [names.FILM_MATERIALS, names.FILM_MATERIALS_LEGACY]]
    : masterTables;
  const master = readOnly ? createReadBook_(env.ID_MASTER, selectedMasterTables) : SpreadsheetApp.openById(env.ID_MASTER);
  const access = readUserPermissions_(master);
  requirePermission_(access, CONFIG.PERMISSIONS.FILM_PO_VIEW);
  requirePermission_(access, feature);
  const operation = readOnly
    ? createReadBook_(env.ID_OPERATION, operationTables)
    : SpreadsheetApp.openById(env.ID_OPERATION);
  return { ...access, master, operation };
}

function filmMaterials_(master) {
  const { FILM_MATERIALS: FilmMaterial } = CONFIG.COLUMNS;
  return readSheetTable_(master, [CONFIG.SHEET_NAMES.FILM_MATERIALS, CONFIG.SHEET_NAMES.FILM_MATERIALS_LEGACY],
    [FilmMaterial.ID, FilmMaterial.GRADE, FilmMaterial.COLOR, FilmMaterial.ESD,
      FilmMaterial.THICKNESS, FilmMaterial.WIDTH]);
}

function filmDatabase_({ master, operation, userId }, listOnly = false) {
  const {
    FILM_PO: FilmPo,
    FILM_LINES: FilmLine,
    FILM_SUPPLIERS: FilmSupplier,
    FILM_RECEIPTS: FilmReceipt,
    ORDER_DETAILS: FilmDetail
  } = CONFIG.COLUMNS;
  const names = CONFIG.SHEET_NAMES;
  const material = filmMaterials_(master);
  const suppliers = readSheetTable_(master, [names.FILM_SUPPLIERS, names.FILM_SUPPLIERS_LEGACY], Object.values(FilmSupplier))
    .rows.map(row => row.data).filter(row => /^NCC(0[1-9]|[1-9]\d)$/.test(row[FilmSupplier.ID]) &&
      /màng/i.test(row[FilmSupplier.TYPE]));
  const requiredForSave = [FilmLine.PO_ID, FilmLine.DELIVERY];
  const lines = readSheetTable_(operation, [names.FILM_LINES],
    [FilmLine.ID, FilmLine.RESIN, FilmLine.MATERIAL_ID, FilmLine.QTY,
      FilmLine.PRICE, FilmLine.NOTE, FilmLine.STATUS],
    [...requiredForSave, FilmLine.DATE, FilmLine.SUPPLIER]);
  const detail = CONFIG.COLUMNS.ORDER_DETAILS;
  const details = filmDetails_(operation, listOnly);
  const setup = [];
  let headers;
  try {
    headers = readSheetTable_(operation, [names.FILM_PO], Object.values(FilmPo));
  } catch (err) {
    setup.push(err.message);
  }
  for (const col of requiredForSave) {
    if (!lines.positions.has(col)) setup.push(names.FILM_LINES + ' thiếu cột ' + col + '.');
  }
  if (!details.positions.has(detail.FILM_LINE_ID)) setup.push(names.ORDER_DETAILS + ' thiếu cột ' + FilmDetail.FILM_LINE_ID + '.');

  let receipts = new Map();
  let receiptWarning = '';
  try {
    const incoming = readSheetTable_(operation, [names.FILM_RECEIPTS],
      [FilmReceipt.ID, FilmReceipt.LINE_ID, FilmReceipt.QTY]);
    receipts = filmReceiptTotals_(incoming);
  } catch (err) {
    receiptWarning = 'Chưa đọc được tiến độ nhận. ' + err.message;
  }
  return { master, operation, materials: material, suppliers, headers, lines, details,
    receipts, setup, receiptWarning, userId };
}

function filmOrders_(db, onlyId = null, includeRevision = true) {
  const { FILM_PO: FilmPo, FILM_LINES: FilmLine, FILM_MATERIALS: FilmMaterial } = CONFIG.COLUMNS;
  const orders = new Map();
  const materialById = new Map(db.materials.rows.map(({ data }) => [data[FilmMaterial.ID], data]));
  for (const { data } of db.headers ? db.headers.rows : []) {
    if (data[FilmPo.ID] && (!onlyId || data[FilmPo.ID] === onlyId)) orders.set(data[FilmPo.ID], { ...data, lines: [] });
  }
  for (const { data } of db.lines.rows) {
    if (!data[FilmLine.ID]) continue;
    const id = data[FilmLine.PO_ID] || data[FilmLine.ID];
    if (onlyId && id !== onlyId) continue;
    if (!orders.has(id)) {
      orders.set(id, { [FilmPo.ID]: id, [FilmPo.DATE]: data[FilmLine.DATE], [FilmPo.SUPPLIER]: data[FilmLine.SUPPLIER],
        [FilmPo.STATUS]: data[FilmLine.STATUS], legacy: true, lines: [] });
    }
    const receipt = db.receipts.get(data[FilmLine.ID]);
    orders.get(id).lines.push({ ...data, storedStatus: data[FilmLine.STATUS], material: materialById.get(data[FilmLine.MATERIAL_ID]) || {},
      [FilmLine.STATUS]: filmLineStatus_(data[FilmLine.STATUS], Number(data[FilmLine.QTY]), receipt && receipt.kg),
      received: db.receiptWarning ? null : (receipt ? receipt.kg : 0),
      receiptIds: receipt ? receipt.ids : [] });
  }
  return Array.from(orders.values()).map(order => {
    order.ordered = order.lines.reduce((sum, line) => sum + (Number(line[FilmLine.QTY]) || 0), 0);
    order.received = db.receiptWarning ? null : order.lines.reduce((sum, line) => sum + line.received, 0);
    order.progress = order[FilmPo.STATUS] === 'Hủy' ? 'Hủy' : db.receiptWarning ? 'Chưa rõ' :
      order.lines.length && order.lines.every(line =>
        Number(line[FilmLine.QTY]) > 0 && line.received + 1e-8 >= Number(line[FilmLine.QTY])) ? 'Đã nhận đủ' :
      order.received > 0 ? 'Nhận một phần' : 'Chờ giao';
    if (includeRevision) order.revision = filmOrderRevision_(order);
    return order;
  }).sort((a, b) => (b[FilmPo.DATE] || '').localeCompare(a[FilmPo.DATE] || '') ||
    b[FilmPo.ID].localeCompare(a[FilmPo.ID]));
}

function filmOrderRevision_(order) {
  return Utilities.base64EncodeWebSafe(Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256, JSON.stringify(order)));
}

function filmNumber_(value, positive, label) {
  const input = sheetText_(value).replace(',', '.');
  if (!input && !positive) return '';
  const number = Number(input);
  if (!/^\d+(?:\.\d+)?$/.test(input) || !Number.isFinite(number) || (positive && number <= 0)) {
    throw new Error(label + ' không hợp lệ.');
  }
  return number;
}

function filmMaterialKey_(data) {
  const { FILM_MATERIALS: FilmMaterial } = CONFIG.COLUMNS;
  const normalize = field => sheetText_(data[field]).normalize('NFC').toLowerCase();
  const dimension = field => {
    const value = normalize(field).replace(',', '.');
    return /^\d+(?:\.\d+)?$/.test(value) ? Number(value) : value;
  };
  return JSON.stringify([normalize(FilmMaterial.GRADE), normalize(FilmMaterial.COLOR),
    normalize(FilmMaterial.ESD), dimension(FilmMaterial.THICKNESS), dimension(FilmMaterial.WIDTH)]);
}

function filmHighest_(table, column, prefix, digits) {
  let highest = 0;
  for (const { data } of table.rows) {
    const id = sheetText_(data[column]);
    const suffix = id.slice(prefix.length);
    if (id.startsWith(prefix) && suffix.length === digits && /^\d+$/.test(suffix)) {
      highest = Math.max(highest, Number(suffix));
    }
  }
  return highest;
}

function filmSequence_(props, table, col, kind, day) {
  const prefix = kind + '_' + day + '_';
  const key = 'FILM_SEQUENCE_' + kind;
  const stored = (props.getProperty(key) || '').split(':');
  let highest = Math.max(filmHighest_(table, col, prefix, 2), stored[0] === day ? Number(stored[1]) : 0);
  return {
    next() {
      if (highest >= 99) throw new Error(kind + ' đã đạt giới hạn 99 mã trong ngày.');
      return prefix + String(++highest).padStart(2, '0');
    },
    reserve() {
      props.setProperty(key, day + ':' + highest);
    }
  };
}

function filmCell_(value, isDate) {
  if (value === '') return {};
  if (isDate) {
    const serial = Date.parse(value + 'T00:00:00Z') / 86400000 + 25569;
    return { userEnteredValue: { numberValue: serial },
      userEnteredFormat: { numberFormat: { type: 'DATE', pattern: 'yyyy-mm-dd' } } };
  }
  return { userEnteredValue: typeof value === 'number' ? { numberValue: value } : { stringValue: value } };
}

function filmWrite_(requests, table, rowIndex, data) {
  const { FILM_PO: FilmPo, FILM_LINES: FilmLine, FILM_RECEIPTS: FilmReceipt } = CONFIG.COLUMNS;
  const sheetId = table.sheet.getSheetId();
  const dateColumns = [FilmPo.DATE, FilmLine.DATE, FilmLine.DELIVERY, FilmReceipt.DATE, FilmReceipt.PRODUCTION_DATE];
  if (rowIndex === null) {
    const cells = Array.from({ length: Math.max(...table.positions.values()) + 1 }, () => ({}));
    for (const [name, value] of Object.entries(data)) {
      cells[table.positions.get(name)] = filmCell_(value, dateColumns.includes(name));
    }
    requests.push({ appendCells: { sheetId, rows: [{ values: cells }], fields: '*' } });
    return;
  }
  for (const [name, value] of Object.entries(data)) {
    requests.push({ updateCells: {
      start: { sheetId, rowIndex, columnIndex: table.positions.get(name) },
      rows: [{ values: [filmCell_(value, dateColumns.includes(name))] }],
      fields: dateColumns.includes(name) && value ? 'userEnteredValue,userEnteredFormat.numberFormat' : 'userEnteredValue'
    } });
  }
}

function saveFilmOrder(payload) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    return payload?.statusChanges ? filmSaveStatusesLocked_(payload) : filmSaveLocked_(payload);
  } finally {
    lock.releaseLock();
  }
}

function filmSaveStatusesLocked_(payload) {
  const { FILM_PO: po, FILM_LINES: col } = CONFIG.COLUMNS;
  const names = CONFIG.SHEET_NAMES;
  const { operation } = filmAccess_(CONFIG.PERMISSIONS.FILM_PO_EDIT);
  const id = sheetText_(payload.id);
  const changes = payload.statusChanges;
  if (!id || !Array.isArray(changes) || !changes.length || changes.length > 99) {
    throw new Error('Danh sách trạng thái cần cập nhật không hợp lệ.');
  }
  const orders = readSheetTable_(operation, [names.FILM_PO], [po.ID, po.STATUS],
    [], (cells, positions) => sheetText_(cells[positions.get(po.ID)]) === id).rows;
  if (orders.length !== 1 || orders[0].data[po.STATUS] === 'Hủy') {
    throw new Error('Không thể sửa trạng thái của PO này.');
  }
  const table = readSheetTable_(operation, [names.FILM_LINES], [col.ID, col.PO_ID, col.STATUS],
    [], (cells, positions) => sheetText_(cells[positions.get(col.PO_ID)]) === id);
  const rows = new Map();
  for (const row of table.rows) {
    const dn = row.data[col.ID];
    rows.set(dn, rows.has(dn) ? null : row);
  }
  const allowed = new Set(Object.values(FILM_RECEIPT_LINE_STATUS));
  const used = new Set();
  const requests = [];
  for (const change of changes) {
    const dn = sheetText_(change?.id);
    const status = sheetText_(change?.status);
    const row = rows.get(dn);
    if (!dn || !row || used.has(dn) || !allowed.has(status) || row.data[col.STATUS] === 'Hủy') {
      throw new Error('Dòng hoặc trạng thái không hợp lệ: ' + dn);
    }
    used.add(dn);
    const current = row.data[col.STATUS];
    if (current === status) continue;
    if (current !== sheetText_(change.before)) {
      throw new Error('Trạng thái của ' + dn + ' đã thay đổi. Hãy mở lại PO.');
    }
    filmWrite_(requests, table, row.index, { [col.STATUS]: status });
  }
  if (requests.length) Sheets.Spreadsheets.batchUpdate({ requests }, operation.getId());
  return { id };
}

function filmSaveLocked_(payload) {
  const {
    FILM_PO: FilmPo,
    FILM_LINES: FilmLine,
    FILM_MATERIALS: FilmMaterial,
    FILM_SUPPLIERS: FilmSupplier,
    ORDER_DETAILS: FilmDetail
  } = CONFIG.COLUMNS;
  if (!payload || !Array.isArray(payload.lines) || !payload.lines.length || payload.lines.length > 99) {
    throw new Error('Đơn cần từ 1 đến 99 dòng quy cách.');
  }
  const orderId = sheetText_(payload.id);
  const access = filmAccess_(orderId ? CONFIG.PERMISSIONS.FILM_PO_EDIT : CONFIG.PERMISSIONS.FILM_PO_CREATE);
  const db = filmDatabase_(access);
  if (db.setup.length) throw new Error(db.setup.join(' '));
  const props = PropertiesService.getScriptProperties();
  const token = sheetText_(payload.token);
  const retryKey = 'FILM_LAST_CREATE_' + db.userId;
  const lastCreate = (props.getProperty(retryKey) || '').split(':');
  if (!orderId && !/^[a-z0-9-]{16,64}$/i.test(token)) throw new Error('Mã phiên tạo đơn không hợp lệ.');
  if (!orderId && lastCreate[0] === token &&
      db.headers.rows.some(row => row.data[FilmPo.ID] === lastCreate[1])) {
    return { id: lastCreate[1] };
  }

  const existing = orderId ? filmOrders_(db, orderId)[0] : null;
  if (orderId && (!existing || existing.legacy || existing[FilmPo.STATUS] === 'Hủy' ||
      existing.revision !== payload.revision)) {
    throw new Error('Đơn đã thay đổi hoặc không thể sửa. Hãy tải lại danh sách.');
  }
  if (existing && db.receiptWarning) throw new Error(db.receiptWarning);
  const supplier = sheetText_(payload.supplier);
  if (!db.suppliers.some(row => row[FilmSupplier.ID] === supplier) && (!existing || existing[FilmPo.SUPPLIER] !== supplier)) {
    throw new Error('Chọn nhà cung cấp màng nhựa hợp lệ.');
  }
  const date = filmInputDate_(payload.date, true);
  if (existing && existing.lines.some(line => line.receiptIds.length) &&
      (existing[FilmPo.SUPPLIER] !== supplier || existing[FilmPo.DATE] !== date)) {
    throw new Error('Đơn đã có phiếu nhận. Không thể đổi nhà cung cấp hoặc ngày đặt.');
  }

  const day = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyMMdd');
  const poSequence = filmSequence_(props, db.headers, FilmPo.ID, 'PO_NVL', day);
  const dnSequence = filmSequence_(props, db.lines, FilmLine.ID, 'DN', day);
  const poId = orderId || poSequence.next();
  const oldLines = new Map(existing ? existing.lines.map(line => [line[FilmLine.ID], line]) : []);
  const oldRows = new Map();
  for (const row of db.lines.rows) {
    const id = row.data[FilmLine.ID];
    if (oldLines.has(id) && !oldRows.has(id)) oldRows.set(id, row);
  }
  const usedLines = new Set();
  const targetDetails = new Map();
  const detailRows = new Map();
  const existingAssignments = new Map();
  for (const row of db.details.rows) {
    if (!row.data[FilmDetail.ID]) continue;
    detailRows.set(row.data[FilmDetail.ID], detailRows.has(row.data[FilmDetail.ID]) ? null : row);
    if (oldLines.has(row.data[FilmDetail.FILM_LINE_ID])) {
      if (!existingAssignments.has(row.data[FilmDetail.FILM_LINE_ID])) existingAssignments.set(row.data[FilmDetail.FILM_LINE_ID], []);
      existingAssignments.get(row.data[FilmDetail.FILM_LINE_ID]).push(row.data[FilmDetail.ID]);
    }
  }

  const materials = new Map();
  let highestMaterial = filmHighest_(db.materials, FilmMaterial.ID, 'VL', 4);
  const masterWrites = [];
  let nextMaterialRow = db.materials.sheet.getLastRow();
  const writes = [];
  for (const { data } of db.materials.rows) {
    if (!data[FilmMaterial.THICKNESS] || !data[FilmMaterial.WIDTH]) continue;
    const key = filmMaterialKey_(data);
    const current = materials.get(key);
    if (!current || (!current[FilmMaterial.ID] && data[FilmMaterial.ID])) materials.set(key, data);
  }
  for (const line of payload.lines) {
    if (!line) throw new Error('Dòng quy cách không hợp lệ.');
    const suppliedId = sheetText_(line.id);
    const old = oldLines.get(suppliedId);
    if (suppliedId && (!old || usedLines.has(suppliedId))) throw new Error('DN_ID không thuộc đơn hoặc bị trùng.');
    const id = suppliedId || dnSequence.next();
    usedLines.add(id);
    const resin = sheetText_(line.resin);
    if (!resin) throw new Error('Chọn loại nhựa.');
    const enteredQty = filmNumber_(line.qty, true, 'Số lượng (kg)');
    const qty = old ? enteredQty : Math.round(enteredQty);
    if (qty <= 0) throw new Error('Số lượng đặt sau khi làm tròn phải lớn hơn 0 kg.');
    const material = {
      [FilmMaterial.GRADE]: sheetText_(line.grade), [FilmMaterial.COLOR]: sheetText_(line.color),
      [FilmMaterial.ESD]: sheetText_(line.esd),
      [FilmMaterial.THICKNESS]: filmNumber_(line.thickness, true, 'Độ dày'),
      [FilmMaterial.WIDTH]: filmNumber_(line.width, true, 'Khổ nhựa')
    };
    const key = filmMaterialKey_(material);
    const sameMaterial = old && filmMaterialKey_(old.material) === key;
    if (!['', '10^6-10^9', '10^9-10^11'].includes(material[FilmMaterial.ESD]) && !sameMaterial) {
      throw new Error('Giá trị tĩnh điện không hợp lệ.');
    }
    const matched = materials.get(key);
    let vl = sameMaterial ? old[FilmLine.MATERIAL_ID] : (matched && matched[FilmMaterial.ID]);
    if (!vl) {
      if (highestMaterial >= 9999) throw new Error('Danh mục đã đạt giới hạn VL9999.');
      vl = 'VL' + String(++highestMaterial).padStart(4, '0');
      materials.set(key, { ...material, [FilmMaterial.ID]: vl });
      const blank = matched && db.materials.rows.find(row => row.data === matched);
      filmWrite_(masterWrites, db.materials, blank ? blank.index : nextMaterialRow++,
        blank ? { [FilmMaterial.ID]: vl } : { ...material, [FilmMaterial.ID]: vl });
    }
    if (old && old.receiptIds.length &&
        (old[FilmLine.MATERIAL_ID] !== vl || old[FilmLine.RESIN] !== resin ||
          (qty !== Number(old[FilmLine.QTY]) && qty + 1e-8 < old.received))) {
      throw new Error(id + ' đã có phiếu nhận. Giữ quy cách và khi đổi số kg đặt, nhập ít nhất bằng số kg đã nhận.');
    }
    const status = old ? (line.status === undefined ? old[FilmLine.STATUS] : sheetText_(line.status))
      : FILM_RECEIPT_LINE_STATUS.WAITING;
    if (old && status !== old[FilmLine.STATUS] &&
        (old[FilmLine.STATUS] === 'Hủy' || !Object.values(FILM_RECEIPT_LINE_STATUS).includes(status))) {
      throw new Error('Trạng thái dòng ' + id + ' không hợp lệ.');
    }
    // Existing lines can save their spec without overwriting separately edited assignments.
    const assignedIds = existingAssignments.get(id) || [];
    if (old && line.originalIds !== undefined) {
      if (!Array.isArray(line.originalIds)) throw new Error('Danh sách CTDH ban đầu không hợp lệ.');
      const original = new Set(line.originalIds);
      if (assignedIds.length !== original.size || assignedIds.some(id => !original.has(id))) {
        throw new Error('CTDH của ' + id + ' đã thay đổi. Hãy mở lại đơn.');
      }
    }
    const detailIds = old && line.detailIds === undefined ? assignedIds : line.detailIds;
    if (!Array.isArray(detailIds)) throw new Error('Dòng quy cách không hợp lệ.');
    for (const detailId of detailIds) {
      const detail = detailRows.get(detailId);
      if (!detail || targetDetails.has(detailId)) throw new Error('CTDH thiếu hoặc bị gán trùng.');
      const prior = detail.data[FilmDetail.FILM_LINE_ID];
      if (prior !== id && (detail.data[FilmDetail.STATUS] !== CONFIG.LINE_STATUS.NEW || (prior && !oldLines.has(prior)))) {
        throw new Error('CTDH ' + detailId + ' đã được gán hoặc đã qua trạng thái Chờ sản xuất.');
      }
      targetDetails.set(detailId, id);
    }
    const priorRow = oldRows.get(id);
    const data = {
      [FilmLine.ID]: id, [FilmLine.PO_ID]: poId, [FilmLine.RESIN]: resin, [FilmLine.MATERIAL_ID]: vl, [FilmLine.QTY]: qty,
      [FilmLine.PRICE]: filmNumber_(line.price, false, 'Đơn giá'),
      [FilmLine.DELIVERY]: filmInputDate_(line.delivery, false), [FilmLine.NOTE]: sheetText_(line.note),
      [FilmLine.STATUS]: old ? old[FilmLine.STATUS] : 'Chờ nhận'
    };
    if (db.lines.positions.has(FilmLine.DATE)) data[FilmLine.DATE] = date;
    if (db.lines.positions.has(FilmLine.SUPPLIER)) data[FilmLine.SUPPLIER] = supplier;
    filmWrite_(writes, db.lines, priorRow ? priorRow.index : null, data);
  }

  if (Array.from(oldLines.keys()).some(id => !usedLines.has(id))) {
    throw new Error('Giữ các dòng đã lưu khi sửa đơn.');
  }
  for (const row of db.details.rows) {
    const id = row.data[FilmDetail.ID];
    const prior = row.data[FilmDetail.FILM_LINE_ID];
    const next = targetDetails.get(id) || '';
    if (prior === next || (!oldLines.has(prior) && !next)) continue;
    requirePermission_(access, CONFIG.PERMISSIONS.FILM_PO_ASSIGN);
    if (row.data[FilmDetail.STATUS] !== CONFIG.LINE_STATUS.NEW || detailRows.get(id) !== row) {
      throw new Error('Không thể đổi gán CTDH ' + id + '. Hãy tải lại danh sách.');
    }
    filmWrite_(writes, db.details, row.index, { [FilmDetail.FILM_LINE_ID]: next });
  }
  const headerRow = existing && db.headers.rows.find(row => row.data[FilmPo.ID] === poId);
  filmWrite_(writes, db.headers, headerRow ? headerRow.index : null, {
    [FilmPo.ID]: poId, [FilmPo.DATE]: date, [FilmPo.SUPPLIER]: supplier,
    [FilmPo.USER]: existing ? existing[FilmPo.USER] : db.userId, [FilmPo.NOTE]: sheetText_(payload.note),
    [FilmPo.STATUS]: existing ? existing[FilmPo.STATUS] : 'Chờ giao'
  });

  // Reserve before writing so an interrupted request cannot reissue an ID.
  poSequence.reserve();
  dnSequence.reserve();
  if (!orderId) props.setProperty(retryKey, token + ':' + poId);
  // The master is a separate workbook. A saved specification remains valid if
  // the operation batch fails, and the next attempt will match it by attributes.
  if (masterWrites.length) {
    const extraRows = nextMaterialRow - db.materials.sheet.getMaxRows();
    if (extraRows > 0) {
      masterWrites.unshift({ appendDimension: {
        sheetId: db.materials.sheet.getSheetId(), dimension: 'ROWS', length: extraRows
      } });
    }
    Sheets.Spreadsheets.batchUpdate({ requests: masterWrites }, db.master.getId());
  }
  Sheets.Spreadsheets.batchUpdate({ requests: writes }, db.operation.getId());
  return { id: poId };
}

function getFilmReceiptHistory(lineId) {
  const { operation } = filmAccess_(CONFIG.PERMISSIONS.NVL_STOCK_VIEW);
  const col = CONFIG.COLUMNS.FILM_RECEIPTS;
  const id = sheetText_(lineId);
  if (!id) return [];
  return readSheetTable_(operation, [CONFIG.SHEET_NAMES.FILM_RECEIPTS],
    [col.ID, col.LINE_ID, col.DATE, col.ROLLS, col.QTY, col.STATUS],
    [], (cells, positions) => sheetText_(cells[positions.get(col.LINE_ID)]) === id)
    .rows.map(({ data }) => ({
      id: data[col.ID], date: data[col.DATE], rolls: data[col.ROLLS], kg: data[col.QTY], status: data[col.STATUS]
    })).sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
}

function getFilmProducts() {
  const { master } = filmAccess_(CONFIG.PERMISSIONS.FILM_PO_CREATE);
  const col = CONFIG.COLUMNS.PRODUCTS;
  return readSheetTable_(master, [CONFIG.SHEET_NAMES.PRODUCTS], [col.ID, col.NAME, col.CODE_CUST])
    .rows.filter(({ data }) => data[col.ID]).map(({ data }) => ({
      id: data[col.ID], name: data[col.NAME], code: data[col.CODE_CUST]
    }));
}

function getFilmProductReference(productId) {
  const { master, operation } = filmAccess_(CONFIG.PERMISSIONS.FILM_PO_CREATE);
  const { TOOLS: tool, ORDER_DETAILS: detail, FILM_PO: po, FILM_LINES: line, FILM_MATERIALS: material } = CONFIG.COLUMNS;
  const names = CONFIG.SHEET_NAMES;
  const id = sheetText_(productId);
  if (!id) return { molds: [], history: [] };
  const molds = readSheetTable_(master, [names.TOOLS],
    [tool.SP_ID, tool.TOOL_TYPE, tool.MOLD_CODE],
    [tool.LENGTH, tool.WIDTH, tool.CAVITY, tool.STATUS], (cells, positions) =>
      sheetText_(cells[positions.get(tool.SP_ID)]) === id &&
      sheetText_(cells[positions.get(tool.TOOL_TYPE)]) === CONFIG.MOLD_TYPES.FORMING)
    .rows.map(({ data }) => ({
      code: data[tool.MOLD_CODE], length: data[tool.LENGTH] || '', width: data[tool.WIDTH] || '',
      cavity: data[tool.CAVITY] || '', status: data[tool.STATUS] || ''
    })).sort((a, b) => Number(b.status === 'SanSang') - Number(a.status === 'SanSang'));
  const links = readSheetTable_(operation, [names.ORDER_DETAILS], [detail.PRODUCT_ID],
    [detail.FILM_LINE_ID], (cells, positions) => sheetText_(cells[positions.get(detail.PRODUCT_ID)]) === id);
  const ids = new Set(links.rows.map(({ data }) => data[detail.FILM_LINE_ID]).filter(Boolean));
  if (!ids.size) return { molds, history: [] };
  const headers = new Map(readSheetTable_(operation, [names.FILM_PO], [po.ID, po.DATE, po.SUPPLIER, po.STATUS])
    .rows.map(({ data }) => [data[po.ID], data]));
  const specs = new Map(filmMaterials_(master).rows.map(({ data }) => [data[material.ID], data]));
  const history = readSheetTable_(operation, [names.FILM_LINES],
    [line.ID, line.PO_ID, line.MATERIAL_ID, line.RESIN, line.QTY, line.PRICE, line.STATUS],
    [line.DATE, line.SUPPLIER, line.NOTE, line.DELIVERY], (cells, positions) => ids.has(sheetText_(cells[positions.get(line.ID)])))
    .rows.filter(({ data }) => data[line.STATUS] !== 'Hủy' && headers.get(data[line.PO_ID])?.[po.STATUS] !== 'Hủy')
    .map(({ data }) => {
      const order = headers.get(data[line.PO_ID]) || {};
      const spec = specs.get(data[line.MATERIAL_ID]) || {};
      return {
        id: data[line.ID], date: order[po.DATE] || data[line.DATE] || '',
        supplier: order[po.SUPPLIER] || data[line.SUPPLIER] || '', qty: data[line.QTY], price: data[line.PRICE],
        note: data[line.NOTE], delivery: data[line.DELIVERY],
        resin: data[line.RESIN], grade: spec[material.GRADE], color: spec[material.COLOR], esd: spec[material.ESD],
        thickness: spec[material.THICKNESS], width: spec[material.WIDTH]
      };
    }).sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id)).slice(0, 10);
  return { molds, history };
}
