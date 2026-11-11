/**
 * Read-only workbook data reused within one request.
 * Two batched value views identify native dates without fetching per-cell formats.
 * Workbook metadata and values are read afresh on the next request.
 */
function createReadBook_(spreadsheetId, tables) {
  let sheets;
  let timeZone;
  let nativeBook;
  const groups = tables.map(names => Array.isArray(names) ? names : [names]);
  const quote = name => "'" + name.replace(/'/g, "''") + "'";

  function load() {
    if (sheets || nativeBook) return;
    try {
      const metadata = Sheets.Spreadsheets.get(spreadsheetId, {
        fields: 'properties(timeZone),sheets(properties(sheetId,title))'
      });
      timeZone = metadata.properties.timeZone;
      const available = new Map((metadata.sheets || []).map(sheet => [sheet.properties.title, sheet.properties]));
      const names = [...new Set(groups.map(group => group.find(name => available.has(name))).filter(Boolean))];
      const loaded = new Map();
      if (!names.length) { sheets = loaded; return; }
      const ranges = names.map(quote);
      const options = { ranges, valueRenderOption: 'UNFORMATTED_VALUE' };
      const raw = Sheets.Spreadsheets.Values.batchGet(spreadsheetId, {
        ...options, dateTimeRenderOption: 'SERIAL_NUMBER'
      });
      const dated = Sheets.Spreadsheets.Values.batchGet(spreadsheetId, {
        ...options, dateTimeRenderOption: 'FORMATTED_STRING'
      });
      names.forEach((name, index) => {
        loaded.set(name, readSnapshotSheet_(
          available.get(name), raw.valueRanges[index].values || [],
          dated.valueRanges[index].values || [], timeZone,
          () => display(name)
        ));
      });
      sheets = loaded;
    } catch (error) {
      if (!readQuotaExceeded_(error)) throw error;
      nativeBook = SpreadsheetApp.openById(spreadsheetId);
    }
  }

  function display(name) {
    try {
      return Sheets.Spreadsheets.Values.get(spreadsheetId, quote(name), {
        valueRenderOption: 'FORMATTED_VALUE'
      }).values || [];
    } catch (error) {
      if (!readQuotaExceeded_(error)) throw error;
      nativeBook = nativeBook || SpreadsheetApp.openById(spreadsheetId);
      return nativeBook.getSheetByName(name).getDataRange().getDisplayValues();
    }
  }

  return {
    getId: () => spreadsheetId,
    getSpreadsheetTimeZone() { load(); return nativeBook ? nativeBook.getSpreadsheetTimeZone() : timeZone; },
    getSheetByName(name) { load(); return nativeBook ? nativeBook.getSheetByName(name) : sheets.get(name) || null; }
  };
}


// Use the native reader during API throttling. Permission and schema errors still propagate.
function readQuotaExceeded_(error) {
  return /quota|rate.?limit|RESOURCE_EXHAUSTED|429/i.test(String(error.message || error));
}

function readSnapshotSheet_(properties, raw, dated, timeZone, readDisplay) {
  const dates = new Map();
  const values = raw.map((row, r) => row.map((value, c) => {
    // Only native date/time numbers change type between these two API render modes.
    if (typeof value !== 'number' || typeof dated[r]?.[c] !== 'string') return value;
    if (!dates.has(value)) {
      const local = new Date(Math.round((value - 25569) * 86400000))
        .toISOString().slice(0, 23).replace('T', ' ');
      dates.set(value, Utilities.parseDate(local, timeZone, 'yyyy-MM-dd HH:mm:ss.SSS'));
    }
    return dates.get(value);
  }));
  const height = values.length;
  const width = values.reduce((maximum, row) => Math.max(maximum, row.length), 0);
  let displayValues;

  function range(row, column, rows, columns) {
    const copy = source => Array.from({ length: rows }, (_, r) =>
      Array.from({ length: columns }, (_, c) => {
        const value = source[row - 1 + r]?.[column - 1 + c] ?? '';
        return value instanceof Date ? new Date(value.getTime()) : value;
      }));
    return {
      getValues: () => copy(values),
      getDisplayValues() {
        if (!displayValues) displayValues = readDisplay();
        return copy(displayValues);
      }
    };
  }

  return {
    getName: () => properties.title,
    getSheetId: () => properties.sheetId,
    getLastRow: () => height,
    getLastColumn: () => width,
    getDataRange: () => range(1, 1, Math.max(1, height), Math.max(1, width)),
    getRange: range
  };
}

/** Master data shared by the order read screens. */
function readOrderMaster_(spreadsheetId, includeTools = false) {
  const names = CONFIG.SHEET_NAMES;
  const tables = [names.CUSTOMERS, names.PRODUCTS, names.EMPLOYEES, names.SETTINGS];
  if (includeTools) tables.push(names.TOOLS);
  return createReadBook_(spreadsheetId, tables);
}
