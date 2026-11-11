function setupSystemProperties() {
  const scriptProps = PropertiesService.getScriptProperties();
  const currentProps = scriptProps.getProperties();

  const defaultSecrets = {};
  if (!currentProps[CONFIG.PROPERTY_KEYS.ID_MASTER]) {
    defaultSecrets[CONFIG.PROPERTY_KEYS.ID_MASTER] = CONFIG.ID_MASTER;
  }
  if (!currentProps[CONFIG.PROPERTY_KEYS.ID_OPERATION]) {
    defaultSecrets[CONFIG.PROPERTY_KEYS.ID_OPERATION] = CONFIG.ID_OPERATION;
  }
  if (!currentProps[CONFIG.PROPERTY_KEYS.ID_STORAGES]) {
    defaultSecrets[CONFIG.PROPERTY_KEYS.ID_STORAGES] = CONFIG.ID_STORAGES;
  }

  if (Object.keys(defaultSecrets).length > 0) {
    scriptProps.setProperties(defaultSecrets, false);
  }

  return {
    success: true,
    message: 'Đã thiết lập cấu hình bảo mật ScriptProperties thành công!'
  };
}

function getSecureEnv_() {
  const scriptProps = PropertiesService.getScriptProperties();
  let idMaster = scriptProps.getProperty(CONFIG.PROPERTY_KEYS.ID_MASTER);
  let idOperation = scriptProps.getProperty(CONFIG.PROPERTY_KEYS.ID_OPERATION);
  let idStorages = scriptProps.getProperty(CONFIG.PROPERTY_KEYS.ID_STORAGES);

  if (!idMaster || !idOperation || !idStorages) {
    setupSystemProperties();
    idMaster = scriptProps.getProperty(CONFIG.PROPERTY_KEYS.ID_MASTER) || CONFIG.ID_MASTER;
    idOperation = scriptProps.getProperty(CONFIG.PROPERTY_KEYS.ID_OPERATION) || CONFIG.ID_OPERATION;
    idStorages = scriptProps.getProperty(CONFIG.PROPERTY_KEYS.ID_STORAGES) || CONFIG.ID_STORAGES;
  }

  return {
    ID_MASTER: idMaster,
    ID_OPERATION: idOperation,
    ID_STORAGES: idStorages
  };
}
function readErpSettings_(master) {
  const sheet = master.getSheetByName(CONFIG.SHEET_NAMES.SETTINGS);
  if (!sheet) return new Map();
  const [headers, ...rows] = sheet.getDataRange().getDisplayValues();
  const settings = new Map();
  headers.forEach((value, index) => {
    const header = String(value).trim();
    if (!header) return;
    if (settings.has(header)) throw new Error(CONFIG.SHEET_NAMES.SETTINGS + ' có tiêu đề bị trùng: ' + header);
    settings.set(header, rows.map(row => String(row[index]).trim()));
  });
  return settings;
}
