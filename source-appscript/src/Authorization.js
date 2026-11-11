function sheetText_(value) {
  return String(value == null ? '' : value).trim();
}

function readSheetTable_(book, names, columns, optional = [], include = () => true, headersOnly = false) {
  const sheet = names.map(name => book.getSheetByName(name)).find(Boolean);
  if (!sheet) throw new Error('Thiếu tab ' + names[0] + '.');
  const lastRow = headersOnly ? sheet.getLastRow() : 0;
  const values = headersOnly
    ? (lastRow ? sheet.getRange(1, 1, Math.min(6, lastRow), sheet.getLastColumn()).getValues() : [])
    : sheet.getDataRange().getValues();
  const index = values.slice(0, 6).findIndex(row => row.map(sheetText_).includes(columns[0]));
  if (index < 0) throw new Error(sheet.getName() + ' thiếu cột ' + columns[0] + '.');
  const headers = values[index].map(sheetText_);
  const positions = new Map();
  for (const name of columns.concat(optional)) {
    const position = headers.indexOf(name);
    if (position !== headers.lastIndexOf(name)) {
      throw new Error(sheet.getName() + ' có cột ' + name + ' bị trùng.');
    }
    if (position >= 0) positions.set(name, position);
    else if (columns.includes(name)) throw new Error(sheet.getName() + ' thiếu cột ' + name + '.');
  }
  const rows = [];
  for (let rowIndex = index + 1; !headersOnly && rowIndex < values.length; rowIndex++) {
    const cells = values[rowIndex];
    if (!include(cells, positions)) continue;
    const data = {};
    for (const [name, col] of positions) {
      const value = cells[col];
      data[name] = value instanceof Date
        ? Utilities.formatDate(value, CONFIG.TIMEZONE, 'yyyy-MM-dd')
        : sheetText_(value);
    }
    rows.push({ index: rowIndex, data });
  }
  return { sheet, positions, rows };
}

function readUserPermissions_(master) {
  const email = sheetText_(Session.getActiveUser().getEmail()).toLowerCase();
  if (!email) {
    throw new Error('Không xác minh được email Google của người truy cập trong chế độ triển khai này.');
  }

  const names = CONFIG.SHEET_NAMES;
  const employee = CONFIG.COLUMNS.EMPLOYEES;
  const users = readSheetTable_(master, [names.EMPLOYEES],
    [employee.ID, employee.EMAIL, employee.STATUS, employee.ACCESS])
    .rows.map(row => row.data).filter(row => row[employee.EMAIL].toLowerCase() === email);
  const user = users[0];
  if (users.length !== 1 || !user[employee.ID] ||
      user[employee.STATUS].toLowerCase() !== CONFIG.EMPLOYEE_STATUS.ACTIVE.toLowerCase()) {
    throw new Error('Email Google phải khớp đúng một nhân viên đang hoạt động trong ' + names.EMPLOYEES + '.');
  }

  const access = user[employee.ACCESS].toUpperCase();
  const role = access === 'KINH DOANH' ? 'KINH_DOANH' : access;
  const code = 'Ma_Chuc_Nang';
  const permissions = new Map();
  const roleColumns = role && role !== code.toUpperCase() ? [role] : [];
  const { rows, positions } = readSheetTable_(master, [names.PERMISSIONS], [code], roleColumns);
  for (const { data } of rows) {
    const key = data[code];
    if (!key) continue;
    permissions.set(key, permissions.has(key) ? 'mã quyền bị trùng' : data[role] === '1');
  }
  return { userId: user[employee.ID], role, hasRoleColumn: roleColumns.length > 0 && positions.has(role), permissions };
}

function requirePermission_(access, feature) {
  const { role, hasRoleColumn, permissions } = access;
  const sheet = CONFIG.SHEET_NAMES.PERMISSIONS;
  if (!role) throw new Error('Thiếu quyen_truy_cap trong ' + CONFIG.SHEET_NAMES.EMPLOYEES + ' cho thao tác ' + feature + '.');
  if (!hasRoleColumn) throw new Error(sheet + ' thiếu cột vai trò ' + role + ' cho quyền ' + feature + '.');
  if (!permissions.has(feature)) throw new Error(sheet + ' thiếu dòng mã quyền ' + feature + '.');
  const permission = permissions.get(feature);
  if (permission !== true) {
    const reason = permission === false ? 'ô quyền phải bằng 1' : permission;
    throw new Error('Từ chối ' + feature + ' cho vai trò ' + role + ' trong ' + sheet + ' (' + reason + ').');
  }
}
