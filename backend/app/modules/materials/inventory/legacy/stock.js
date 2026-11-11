/** One read snapshot per request; stock is computed per receipt, never per PO. */
function filmStockAccess_() {
  const env = getSecureEnv_(), n = CONFIG.SHEET_NAMES;
  const master = createReadBook_(env.ID_MASTER, [n.EMPLOYEES, n.PERMISSIONS, n.PRODUCTS,
    [n.FILM_MATERIALS, n.FILM_MATERIALS_LEGACY], [n.FILM_SUPPLIERS, n.FILM_SUPPLIERS_LEGACY]]);
  const access = readUserPermissions_(master);
  requirePermission_(access, CONFIG.PERMISSIONS.NVL_STOCK_VIEW);
  const operation = createReadBook_(env.ID_OPERATION,
    [n.FILM_RECEIPTS, n.FILM_MOVEMENTS, n.FILM_LINES, n.FILM_PO, n.ORDER_DETAILS]);
  return { ...access, master, operation };
}

function filmStockNumber_(value, label) {
  const number = Number(value);
  if (sheetText_(value) === '' || !Number.isFinite(number) || number < 0) {
    throw new Error('Số kg không hợp lệ: ' + label);
  }
  return number;
}

function filmStockMovements_(operation) {
  const c = CONFIG.COLUMNS.FILM_MOVEMENTS;
  const table = readSheetTable_(operation, [CONFIG.SHEET_NAMES.FILM_MOVEMENTS], Object.values(c));
  const totals = new Map();
  let pendingCount = 0, pendingKg = 0;
  for (const { data, index } of table.rows) {
    if (!Object.values(data).some(Boolean)) continue;
    const type = sheetText_(data[c.TYPE]).normalize('NFC').toUpperCase();
    if (!['CẤP NVL', 'TRẢ NVL'].includes(type)) {
      throw new Error('Loại giao dịch không hợp lệ ở dòng ' + (index + 1));
    }
    const id = data[c.RECEIPT_ID];
    if (!id) throw new Error('Thiếu N_NVL_ID ở dòng cấp/trả ' + (index + 1));
    const kg = filmStockNumber_(data[c.QTY], id);
    const balance = totals.get(id) || { issued: 0, returned: 0, pending: 0 };
    if (type === 'CẤP NVL') balance.issued += kg;
    else if (data[c.RECEIVER]) balance.returned += kg;
    else if (kg > 0) { balance.pending += kg; pendingCount++; pendingKg += kg; }
    totals.set(id, balance);
  }
  const pending = table.rows.filter(({ data }) => sheetText_(data[c.TYPE]).normalize('NFC').toUpperCase() === 'TRẢ NVL' && !data[c.RECEIVER] && Number(data[c.QTY]) > 0).map(({ data }) => ({ id: data[c.ID], receiptId: data[c.RECEIPT_ID], orderId: data[c.ORDER_ID], kg: Number(data[c.QTY]), date: data[c.DATE], note: data[c.NOTE] }));
  return { totals, pendingCount, pendingKg, pending };
}

function getFilmPendingReturns() {
  const env = getSecureEnv_(), n = CONFIG.SHEET_NAMES;
  const master = createReadBook_(env.ID_MASTER, [n.EMPLOYEES, n.PERMISSIONS]);
  requirePermission_(readUserPermissions_(master), CONFIG.PERMISSIONS.NVL_STOCK_VIEW);
  const operation = createReadBook_(env.ID_OPERATION, [n.FILM_MOVEMENTS]);
  const { pendingCount, pendingKg } = filmStockMovements_(operation);
  return { count: pendingCount, kg: pendingKg };
}

function getFilmStock(filters = {}) {
  const db = filmStockAccess_(), n = CONFIG.SHEET_NAMES;
  const { FILM_RECEIPTS: r, FILM_LINES: l, FILM_PO: o, FILM_MATERIALS: m,
    FILM_SUPPLIERS: s, PRODUCTS: p, ORDER_DETAILS: d } = CONFIG.COLUMNS;
  const status = filters.status || 'available';
  if (!['available', 'empty'].includes(status)) throw new Error('Trạng thái không hợp lệ.');
  const ranges = ['thicknessMin', 'thicknessMax', 'widthMin', 'widthMax'];
  const limits = {};
  for (const key of ranges) limits[key] = filters[key] === '' || filters[key] == null
    ? null : filmStockNumber_(filters[key], key);
  for (const key of ['thickness', 'width']) if (limits[key + 'Min'] !== null && limits[key + 'Max'] !== null &&
    limits[key + 'Min'] > limits[key + 'Max']) throw new Error('Giá trị min phải nhỏ hơn hoặc bằng max.');
  const index = (name, cols, key) => new Map(readSheetTable_(db.operation, [name], cols)
    .rows.map(({ data }) => [data[key], data]));
  const lines = index(n.FILM_LINES, [l.ID, l.PO_ID, l.MATERIAL_ID, l.RESIN, l.PRICE, l.NOTE], l.ID);
  const orders = index(n.FILM_PO, [o.ID, o.SUPPLIER, o.NOTE], o.ID);
  const materials = new Map(filmMaterials_(db.master).rows.map(({ data }) => [data[m.ID], data]));
  const suppliers = readSheetTable_(db.master, [n.FILM_SUPPLIERS, n.FILM_SUPPLIERS_LEGACY], [s.ID, s.NAME])
    .rows.map(({ data }) => ({ id: data[s.ID], name: data[s.NAME] }));
  const supplierNames = new Map(suppliers.map(row => [row.id, row.name]));
  const movements = filmStockMovements_(db.operation);
  const receipts = readSheetTable_(db.operation, [n.FILM_RECEIPTS],
    [r.ID, r.LINE_ID, r.DATE, r.PRODUCTION_DATE, r.QTY, r.ROLLS]);
  const seen = new Set();
  let rows = [];
  for (const { data, index: rowIndex } of receipts.rows) {
    const id = data[r.ID];
    if (!id) continue;
    if (seen.has(id)) throw new Error('Mã nhận bị trùng: ' + id);
    seen.add(id);
    const received = filmStockNumber_(data[r.QTY], id);
    const movement = movements.totals.get(id) || { issued: 0, returned: 0, pending: 0 };
    const stock = Math.round((received - movement.issued + movement.returned) * 1e8) / 1e8;
    if ((status === 'available') !== (stock > 0)) continue;
    const line = lines.get(data[r.LINE_ID]);
    if (!line) throw new Error(id + ': không tìm thấy DN_ID ' + data[r.LINE_ID]);
    const spec = materials.get(line[l.MATERIAL_ID]);
    if (!spec) throw new Error(id + ': không tìm thấy VL_ID ' + line[l.MATERIAL_ID]);
    const order = orders.get(line[l.PO_ID]) || {};
    const supplier = order[o.SUPPLIER] || '';
    const thickness = Number(spec[m.THICKNESS]), width = Number(spec[m.WIDTH]);
    if (filters.supplier && filters.supplier !== supplier) continue;
    if (['thickness', 'width'].some(key => {
      const value = key === 'thickness' ? thickness : width;
      return (limits[key + 'Min'] !== null && (!Number.isFinite(value) || value < limits[key + 'Min'])) ||
        (limits[key + 'Max'] !== null && (!Number.isFinite(value) || value > limits[key + 'Max']));
    })) continue;
    rows.push({ id, lineId: data[r.LINE_ID], date: data[r.DATE], productionDate: data[r.PRODUCTION_DATE],
      received, stock, rolls: data[r.ROLLS], supplier: supplierNames.get(supplier) || supplier,
      price: line[l.PRICE], note: [line[l.NOTE], order[o.NOTE]].filter(Boolean).join(' · '),
      resin: line[l.RESIN], grade: spec[m.GRADE], color: spec[m.COLOR], esd: spec[m.ESD],
      thickness, width, supplierId: supplier,
      spec: spec[m.THICKNESS] + '*' + spec[m.WIDTH], pending: movement.pending, rowIndex });
  }
  rows.sort((a, b) => b.date.localeCompare(a.date) || b.rowIndex - a.rowIndex);
  const total = rows.length;
  if (status === 'empty') rows = rows.slice(0, 1000);
  const wanted = new Set(rows.map(row => row.lineId));
  const products = new Map(readSheetTable_(db.master, [n.PRODUCTS], [p.ID, p.NAME, p.TYPE])
    .rows.map(({ data }) => [data[p.ID], data]));
  const assignments = new Map();
  for (const { data } of readSheetTable_(db.operation, [n.ORDER_DETAILS], [d.PRODUCT_ID], [d.FILM_LINE_ID]).rows) {
    const id = data[d.FILM_LINE_ID];
    if (!wanted.has(id)) continue;
    const product = products.get(data[d.PRODUCT_ID]);
    if (!product) continue;
    if (!assignments.has(id)) assignments.set(id, new Map());
    assignments.get(id).set(data[d.PRODUCT_ID], { name: product[p.NAME] || data[d.PRODUCT_ID],
      type: product[p.TYPE] === '1' ? 'Định hình' : product[p.TYPE] === '2' ? 'Bế' : 'Chưa xác định' });
  }
  rows.forEach(row => { row.products = [...(assignments.get(row.lineId) || new Map()).values()]; delete row.rowIndex; });
  return { rows, total, suppliers, pendingCount: movements.pendingCount, pendingKg: movements.pendingKg, pendingReturns: movements.pending, canConfirm: db.permissions.get(CONFIG.PERMISSIONS.NVL_RECEIVE) === true };
}
