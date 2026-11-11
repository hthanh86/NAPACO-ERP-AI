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

