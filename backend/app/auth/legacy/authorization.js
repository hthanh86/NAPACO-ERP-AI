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
