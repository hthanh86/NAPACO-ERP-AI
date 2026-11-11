/**
 * ============================================================================
 * NAPACO ENTERPRISE ERP - ORDER SERVICE & REPOSITORY LAYER
 * File: OrderService.gs
 * Tầng kiến trúc: Tầng 2 & 3 - Business Logic & Data Repository
 * Nhiệm vụ:
 *  1. Xác thực người dùng kép (Hybrid Email/Dropdown) đối chiếu bảng '07.NhanVien'.
 *  2. Đọc dữ liệu nháp từ sheet 'TAO DON' (A8:I), gom nhóm nhiều PO của nhiều khách hàng,
 *     tự động gán Ngày đặt = TODAY() và Ngày giao = TODAY() + 10 ngày.
 *  3. Lưu liên tầng (Flow-based Upsert) có LockService (30,000 ms):
 *     - Tự tạo Khách hàng mới (KHxxxx) vào '01_KHACH_HANG'.
 *     - Tự tạo Sản phẩm mới (SPxxxx) hoặc cập nhật thông tin vào '02_SAN_PHAM'.
 *     - Tải tệp đính kèm PO lên Google Drive folder ID_STORAGES.
 *     - Sinh mã đơn hàng 'DH_yymmdd_xx' và mã chi tiết 'CT_yymmdd_xx'.
 *     - Ghi theo lô (Batch Write) vào '01.DonHang' và '02.ChiTietDH' kèm cơ chế Rollback.
 *     - Xóa trắng dữ liệu vùng A8:I trên sheet 'TAO DON' sau khi lưu thành công.
 *  4. Tra cứu kép (Dual-View): PO Header View và Line-Item Flat View.
 * ============================================================================
 */

const OrderService = {

  readDatabaseTable_: function(sheet, name, schema, required, idsOnly = false) {
    if (!sheet) throw new Error('Không tìm thấy bảng ' + name + '.');
    const lastRow = idsOnly ? sheet.getLastRow() : 0;
    const rows = idsOnly
      ? (lastRow ? sheet.getRange(1, 1, Math.min(10, lastRow), sheet.getLastColumn()).getValues() : [])
      : sheet.getDataRange().getValues();
    const normalize = value => String(value || '').trim().toLowerCase();
    const candidates = rows.slice(0, 10).map(row => row.map(normalize));
    const headerRow = candidates.findIndex(row => row.includes(normalize(schema.ID)));
    const headers = candidates[headerRow] || [];
    const columns = {};
    for (const [key, label] of Object.entries(schema)) {
      const normalized = normalize(label);
      const index = headers.indexOf(normalized);
      if (index !== headers.lastIndexOf(normalized)) {
        throw new Error('Cột "' + label + '" bị trùng trong ' + name + '.');
      }
      if (index < 0 && required.includes(key)) {
        throw new Error('Thiếu cột "' + label + '" trong ' + name + '.');
      }
      columns[key] = index;
    }
    const ids = idsOnly && lastRow > headerRow + 1
      ? sheet.getRange(headerRow + 2, columns.ID + 1, lastRow - headerRow - 1, 1).getValues().flat()
      : [];
    return { sheet, rows, headerRow, columns, ids };
  },

  readOrderUnits_: function(masterSS, rows, headerRow, unitColumn) {
    const configured = readErpSettings_(masterSS).get(CONFIG.COLUMNS.SETTINGS.UNITS) || [];
    const headers = rows[headerRow] || [];
    const configColumn = headers.findIndex((value, index) =>
      index > 0 && !String(headers[index - 1] || '').trim() &&
      String(value || '').trim().toLowerCase() === 'danh sách đvt');
    const body = rows.slice(headerRow + 1);
    const units = new Map();
    const add = value => {
      const unit = String(value || '').trim();
      if (unit && !units.has(unit.toLowerCase())) units.set(unit.toLowerCase(), unit);
    };
    configured.forEach(add);
    if (!units.size && configColumn >= 0) body.forEach(row => add(row[configColumn]));
    if (!units.size) {
      add(CONFIG.DEFAULT_UNIT || 'Cái');
      body.forEach(row => add(row[unitColumn]));
    }
    return Array.from(units.values());
  },

  sheetCell_: function(value) {
    if (value === '') return {};
    if (typeof value === 'number') return { userEnteredValue: { numberValue: value } };
    return { userEnteredValue: { stringValue: String(value) } };
  },

  appendDatabaseRows_: function(requests, table, records) {
    if (!records.length) return;
    const keys = Object.keys(records[0]);
    const width = Math.max(...keys.map(key => table.columns[key])) + 1;
    const rows = records.map(record => {
      const values = Array.from({ length: width }, () => ({}));
      for (const key of keys) values[table.columns[key]] = this.sheetCell_(record[key]);
      return { values };
    });
    requests.push({ appendCells: { sheetId: table.sheet.getSheetId(), rows, fields: 'userEnteredValue' } });
  },

  queueCellChange_: function(requests, sheetId, rowIndex, columnIndex, row, value) {
    if (row[columnIndex] === value) return;
    row[columnIndex] = value;
    requests.push({ updateCells: {
      start: { sheetId, rowIndex, columnIndex },
      rows: [{ values: [this.sheetCell_(value)] }],
      fields: 'userEnteredValue'
    } });
  },

  /**
   * Mở kết nối tới File 01. DB MASTER từ ScriptProperties
   * @private
   */
  getMasterSpreadsheet_: function() {
    const env = getSecureEnv_();
    return SpreadsheetApp.openById(env.ID_MASTER);
  },

  /**
   * Mở kết nối tới File 02. DB OPERATION từ ScriptProperties
   * @private
   */
  getOperationSpreadsheet_: function() {
    const env = getSecureEnv_();
    return SpreadsheetApp.openById(env.ID_OPERATION);
  },

  /**
   * Mở kết nối tới Thư mục lưu trữ File PO (ID_STORAGES)
   * @private
   */
  getStorageFolder_: function() {
    const env = getSecureEnv_();
    return DriveApp.getFolderById(env.ID_STORAGES);
  },

  /**
   * Xóa bộ nhớ đệm Cache khi có cập nhật
   */
  clearSystemCache: function() {
    try {
      const cache = CacheService.getScriptCache();
      cache.removeAll(['NAPACO_MASTER_CATALOG_V2']);
    } catch (e) {
      console.warn('Không thể xóa cache:', e.message);
    }
  },

  /**
   * Đọc danh mục Master (Khách hàng, Sản phẩm, Nhân viên) và Xác thực người dùng kép
   */
  getCatalogAndAuthData: function(masterSS = readOrderMaster_(getSecureEnv_().ID_MASTER)) {

    // 1. Đọc bảng 01_KHACH_HANG: [Ma_KH, name, address, contacter, phone]
    const custSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.CUSTOMERS);
    if (!custSheet) throw new Error('Không tìm thấy bảng ' + CONFIG.SHEET_NAMES.CUSTOMERS);
    const { rows: custValues, headerRow: custHeader, columns: custCols } = this.readDatabaseTable_(
      custSheet, CONFIG.SHEET_NAMES.CUSTOMERS, CONFIG.COLUMNS.CUSTOMERS, ['ID', 'NAME']);
    const customers = [];
    const customerByNameMap = {};
    const customerByIdMap = {};

    for (let i = custHeader + 1; i < custValues.length; i++) {
      const maKH = String(custValues[i][custCols.ID] || '').trim();
      const name = String(custValues[i][custCols.NAME] || '').trim();
      if (!maKH || !name) continue;
      const cusObj = {
        maKH: maKH,
        name: name,
        address: String(custValues[i][custCols.ADDRESS] || '').trim(),
        contacter: String(custValues[i][custCols.CONTACTER] || '').trim(),
        phone: String(custValues[i][custCols.PHONE] || '').trim()
      };
      customers.push(cusObj);
      customerByNameMap[name.toLowerCase()] = cusObj;
      customerByIdMap[maKH] = cusObj;
    }

    // 2. [ĐÃ SỬA] Đọc bảng Sản Phẩm tìm header động theo CONFIG.COLUMNS.PRODUCTS
    const prodSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.PRODUCTS);
    if (!prodSheet) throw new Error('Không tìm thấy bảng ' + CONFIG.SHEET_NAMES.PRODUCTS);
    const prodValues = prodSheet.getDataRange().getValues();
    const products = [];
    const productByIdMap = {};

    // Tìm dòng header thực tế chứa SP_ID
    let prodHdrIdx = -1;
    for (let r = 0; r < Math.min(prodValues.length, 5); r++) {
      const rowStr = prodValues[r].map(c => String(c || '').trim().toLowerCase());
      if (rowStr.indexOf(CONFIG.COLUMNS.PRODUCTS.ID.toLowerCase()) !== -1) {
        prodHdrIdx = r;
        break;
      }
    }
    if (prodHdrIdx === -1) prodHdrIdx = 0;

    const pHdrs = prodValues[prodHdrIdx].map(h => String(h || '').trim().toLowerCase());
    const cSpId = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.ID.toLowerCase());
    const cCusId = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.CUSTOMER_ID.toLowerCase());
    const cFilm = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.FILM.toLowerCase());
    const cType = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.TYPE.toLowerCase());
    const productTypeById = cType === -1 ? null : new Map();
    const cCodeCust = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.CODE_CUST.toLowerCase());
    const cName = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.NAME.toLowerCase());
    const cCavity = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.CAVITY.toLowerCase());
    const cStock = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.STOCK.toLowerCase());
    const cUnit = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.UNIT.toLowerCase());
    const cImage = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.IMAGE.toLowerCase());
    const cPacking = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.PACKING.toLowerCase());
    const cMoldPrice = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.MOLD_PRICE.toLowerCase());
    const cPrice = pHdrs.indexOf(CONFIG.COLUMNS.PRODUCTS.PRICE.toLowerCase());

    console.log('[DEBUG_LOG_SANPHAM] Header row index:', prodHdrIdx, '| Cột SP_ID:', cSpId, '| Cột FILM (Màng):', cFilm);

    for (let j = prodHdrIdx + 1; j < prodValues.length; j++) {
      const row = prodValues[j];
      const spId = cSpId !== -1 ? String(row[cSpId] || '').trim() : '';
      if (!spId) continue;
      const type = cType !== -1 ? String(row[cType] || '').trim() : '';
      if (productTypeById) productTypeById.set(spId.toUpperCase(), type);

      const nameNapaco = cName !== -1 ? String(row[cName] || '').trim() : '';
      if (!nameNapaco) continue;

      const mangVal = cFilm !== -1 ? String(row[cFilm] || '').trim() : '';
      const prodObj = {
        spId: spId,
        customerId: cCusId !== -1 ? String(row[cCusId] || '').trim() : '',
        mang: mangVal,
        type: type,
        codeSP: cCodeCust !== -1 ? String(row[cCodeCust] || '').trim() : '',
        prodName: nameNapaco,
        cavity: cCavity !== -1 ? (Number(row[cCavity]) || 0) : 0,
        tonkho: cStock !== -1 ? (Number(row[cStock]) || 0) : 0,
        unit: cUnit !== -1 ? (String(row[cUnit] || 'Cái').trim() || 'Cái') : 'Cái',
        imageURL: cImage !== -1 ? String(row[cImage] || '').trim() : '',
        donggoi: cPacking !== -1 ? String(row[cPacking] || '').trim() : '',
        giaKhuon: cMoldPrice !== -1 ? (Number(row[cMoldPrice]) || 0) : 0,
        price: cPrice !== -1 ? (Number(row[cPrice]) || 0) : 0
      };
      products.push(prodObj);
      productByIdMap[spId] = prodObj;
      productByIdMap[spId.toUpperCase()] = prodObj;
    }

    // 3. [ĐÃ SỬA] Đọc bảng Nhân Viên tìm header động theo CONFIG.COLUMNS.EMPLOYEES
    const { salesStaffList, employeeByIdMap, matchedEmployee, sessionEmail } = this.readOrderStaff_(masterSS);

    const now = new Date();
    const todayStr = Utilities.formatDate(now, CONFIG.TIMEZONE, 'yyyy-MM-dd');
    const deliveryDateObj = new Date(now.getTime() + CONFIG.DEFAULT_DELIVERY_DAYS * 86400000);
    const defaultDeliveryStr = Utilities.formatDate(deliveryDateObj, CONFIG.TIMEZONE, 'yyyy-MM-dd');

    return {
      customers: customers,
      customerByNameMap: customerByNameMap,
      customerByIdMap: customerByIdMap,
      products: products,
      orderUnits: this.readOrderUnits_(masterSS, prodValues, prodHdrIdx, cUnit),
      productByIdMap: productByIdMap,
      productTypeById: productTypeById,
      salesStaffList: salesStaffList,
      employeeByIdMap: employeeByIdMap,
      currentUser: {
        email: sessionEmail,
        isAuthenticated: Boolean(matchedEmployee),
        isLockedReadonly: Boolean(matchedEmployee),
        maNV: matchedEmployee ? matchedEmployee.maNV : '',
        hoTen: matchedEmployee ? matchedEmployee.hoTen : '',
        role: matchedEmployee ? matchedEmployee.role : '',
        quyenTruyCap: matchedEmployee ? matchedEmployee.quyenTruyCap : '',
        display: matchedEmployee ? matchedEmployee.display : ''
      },
      serverDate: todayStr,
      defaultDeliveryDate: defaultDeliveryStr
    };
  },

  readOrderStaff_: function(masterSS) {
    const empSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.EMPLOYEES);
    if (!empSheet) throw new Error('Không tìm thấy bảng ' + CONFIG.SHEET_NAMES.EMPLOYEES);
    const empValues = empSheet.getDataRange().getValues();

    let sessionEmail = '';
    try {
      sessionEmail = String(Session.getActiveUser().getEmail() || '').trim().toLowerCase();
    } catch (e) {
      sessionEmail = '';
    }

    const salesStaffList = [];
    const allActiveStaffList = [];
    const employeeByIdMap = {};
    let matchedEmployee = null;

    let empHdrIdx = -1;
    for (let r = 0; r < Math.min(empValues.length, 6); r++) {
      const rowStr = empValues[r].map(c => String(c || '').trim().toLowerCase());
      if (rowStr.indexOf(CONFIG.COLUMNS.EMPLOYEES.ID.toLowerCase()) !== -1) {
        empHdrIdx = r;
        break;
      }
    }
    if (empHdrIdx === -1) empHdrIdx = 0;

    const eHdrs = empValues[empHdrIdx].map(h => String(h || '').trim().toLowerCase());
    const cEmpId = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.ID.toLowerCase());
    const cEmpName = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.NAME.toLowerCase());
    const cEmpDept = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.DEPARTMENT.toLowerCase());
    const cEmpRole = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.ROLE.toLowerCase());
    const cEmpEmail = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.EMAIL.toLowerCase());
    const cEmpPhone = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.PHONE.toLowerCase());
    const cEmpAccess = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.ACCESS.toLowerCase());
    const cEmpStatus = eHdrs.indexOf(CONFIG.COLUMNS.EMPLOYEES.STATUS.toLowerCase());

    console.log('[DEBUG_LOG_NHANVIEN] Header row index:', empHdrIdx, '| Cột Ma_NV:', cEmpId, '| Cột Name:', cEmpName);

    for (let k = empHdrIdx + 1; k < empValues.length; k++) {
      const row = empValues[k];
      const maNV = cEmpId !== -1 ? String(row[cEmpId] || '').trim() : '';
      const empName = cEmpName !== -1 ? String(row[cEmpName] || '').trim() : '';
      if (!maNV || !/^NV/i.test(maNV) || !empName) continue;

      const phongBan = cEmpDept !== -1 ? String(row[cEmpDept] || '').trim() : '';
      const role = cEmpRole !== -1 ? String(row[cEmpRole] || '').trim() : '';
      const email = cEmpEmail !== -1 ? String(row[cEmpEmail] || '').trim().toLowerCase() : '';
      const sdt = cEmpPhone !== -1 ? String(row[cEmpPhone] || '').trim() : '';
      const quyenTruyCap = cEmpAccess !== -1 ? String(row[cEmpAccess] || '').trim() : '';
      const trangThai = cEmpStatus !== -1 ? String(row[cEmpStatus] || '').trim() : '';

      const empObj = {
        maNV: maNV,
        hoTen: empName,
        phongBan: phongBan,
        role: role,
        email: email,
        sdt: sdt,
        quyenTruyCap: quyenTruyCap,
        trangThai: trangThai,
        display: maNV + ' - ' + empName
      };

      // Ánh xạ đa quy tắc: hỗ trợ NV0001, NV-KD01, NV-KD1...
      employeeByIdMap[maNV] = empObj;
      employeeByIdMap[maNV.toUpperCase()] = empObj;
      const numMatch = maNV.match(/\d+/);
      if (numMatch) {
        const num = parseInt(numMatch[0], 10);
        employeeByIdMap['NV-KD' + String(num).padStart(2, '0')] = empObj;
        employeeByIdMap['NV-KD' + num] = empObj;
        employeeByIdMap['NV' + String(num).padStart(4, '0')] = empObj;
      }

      // [LOẠI BỎ HARDCODE] Dùng CONFIG.EMPLOYEE_STATUS.ACTIVE & CONFIG.DEPARTMENTS.SALES
      const isActive = trangThai.toLowerCase().includes(CONFIG.EMPLOYEE_STATUS.ACTIVE.toLowerCase()) || trangThai.toLowerCase().includes('hoạt động');
      if (isActive) {
        allActiveStaffList.push(empObj);
        const isSales = phongBan.toLowerCase().includes(CONFIG.DEPARTMENTS.SALES.toLowerCase());
        const isManager = quyenTruyCap.includes('Admin') || quyenTruyCap.includes('Manager');
        if (isSales || isManager) {
          salesStaffList.push(empObj);
        }
        if (sessionEmail && email && sessionEmail === email) {
          matchedEmployee = empObj;
        }
      }
    }
    console.log('[DEBUG_LOG_NHANVIEN] Số nhân viên KD tải được:', salesStaffList.length, '| Danh sách:', salesStaffList.map(s => s.display));

    const finalSalesDropdown = salesStaffList.length > 0 ? salesStaffList : allActiveStaffList;

    return { salesStaffList: finalSalesDropdown, employeeByIdMap, matchedEmployee, sessionEmail };
  },

  /**
   * Tra cứu nhanh thông tin Sản phẩm cho hàm onEdit trên sheet 'TAO DON'
   */
  lookupProductByNameAndCustomer: function(productName, customerName) {
    const catalog = this.getCatalogAndAuthData();
    const pNameLower = String(productName || '').trim().toLowerCase();
    const cNameLower = String(customerName || '').trim().toLowerCase();
    const cusObj = catalog.customerByNameMap[cNameLower];
    const targetCusId = cusObj ? cusObj.maKH : '';

    // Ưu tiên khớp cả tên sản phẩm và mã khách hàng
    let matched = catalog.products.find(function(p) {
      return p.prodName.toLowerCase() === pNameLower && (!targetCusId || p.customerId === targetCusId);
    });
    if (!matched) {
      matched = catalog.products.find(function(p) {
        return p.prodName.toLowerCase() === pNameLower;
      });
    }
    return matched || null;
  },

  /**
   * Xây dựng dữ liệu khởi tạo cho OrderModal.html
   * Quét vùng A8:I trên sheet 'TAO DON', gom nhóm theo (Khách hàng + Số PO),
   * tự động gán Ngày đặt = TODAY() và Ngày giao = TODAY() + 10 ngày.
   */
  buildModalInitialData: function(optSourceSpreadsheetId, webEntry) {
    if (webEntry) {
      requirePermission_(readUserPermissions_(this.getMasterSpreadsheet_()), CONFIG.PERMISSIONS.ORDER_CREATE);
    }
    const catalog = this.getCatalogAndAuthData();
    const todayStr = catalog.serverDate;
    const defaultDeliveryStr = catalog.defaultDeliveryDate;
    const yymmdd = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyMMdd');

    let wsSheet = null;
    try {
      if (!webEntry && optSourceSpreadsheetId) {
        wsSheet = SpreadsheetApp.openById(optSourceSpreadsheetId).getSheetByName(CONFIG.SHEET_NAMES.ORDER_WORKSPACE);
      } else if (!webEntry && SpreadsheetApp.getActiveSpreadsheet()) {
        wsSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CONFIG.SHEET_NAMES.ORDER_WORKSPACE);
      }
    } catch (e) {
      wsSheet = null;
    }

    const poGroupsMap = {};
    const poGroupsList = [];

    if (wsSheet) {
      const lastRow = wsSheet.getLastRow();
      const startRow = CONFIG.WORKSPACE_CONFIG.DATA_START_ROW;
      if (lastRow >= startRow) {
        const numRows = lastRow - startRow + 1;
        const rawRows = wsSheet.getRange(startRow, 1, numRows, CONFIG.WORKSPACE_CONFIG.DATA_END_COL).getValues();

        for (let r = 0; r < rawRows.length; r++) {
          const row = rawRows[r];
          const customerName = String(row[0] || '').trim();
          const prodName = String(row[1] || '').trim();
          const codeSPInput = String(row[2] || '').trim();
          const unitInput = String(row[3] || '').trim();
          const priceInput = this.parseNumber_(row[4]);
          const qtyInput = this.parseNumber_(row[5]);
          const soPOInput = String(row[6] || '').trim();
          const noteInput = String(row[7] || '').trim();
          const linkPOInput = String(row[8] || '').trim();

          // Bỏ qua dòng trống hoàn toàn
          if (!customerName && !prodName) continue;

          const effectiveCustomer = customerName || 'Khách lẻ';
          const cleanCus = this.removeVietnameseTones_(effectiveCustomer)
            .toUpperCase()
            .replace(/[^A-Z0-9]+/g, '-')
            .replace(/^-+|-+$/g, '');
          const autoPONumber = CONFIG.ORDER_CODE_PREFIX + yymmdd + '-' + (cleanCus || 'KH');
          const effectivePO = soPOInput || autoPONumber;

          // Kiểm tra Khách hàng cũ / mới
          const existingCus = catalog.customerByNameMap[effectiveCustomer.toLowerCase()] || null;

          // Kiểm tra Sản phẩm cũ / mới
          let existingProd = null;
          if (prodName) {
            const pLower = prodName.toLowerCase();
            existingProd = catalog.products.find(function(p) {
              return p.prodName.toLowerCase() === pLower && (!existingCus || p.customerId === existingCus.maKH);
            });
            if (!existingProd) {
              existingProd = catalog.products.find(function(p) {
                return p.prodName.toLowerCase() === pLower;
              });
            }
          }

          const groupKey = effectiveCustomer.toLowerCase() + '__' + effectivePO.toUpperCase();
          if (!poGroupsMap[groupKey]) {
            const newGroup = {
              customerName: existingCus ? existingCus.name : effectiveCustomer,
              maKH: existingCus ? existingCus.maKH : '',
              isNewCustomer: !existingCus,
              soPO: effectivePO,
              autoPONumber: autoPONumber,
              salesPerson: catalog.currentUser.isAuthenticated
                ? catalog.currentUser.maNV
                : (catalog.salesStaffList[0] ? catalog.salesStaffList[0].maNV : ''),
              ngayDat: todayStr,
              ngayGiaoDK: defaultDeliveryStr,
              orderNote: '',
              existingFileUrl: linkPOInput || '',
              items: []
            };
            poGroupsMap[groupKey] = newGroup;
            poGroupsList.push(newGroup);
          }

          if (linkPOInput && !poGroupsMap[groupKey].existingFileUrl) {
            poGroupsMap[groupKey].existingFileUrl = linkPOInput;
          }

          poGroupsMap[groupKey].items.push({
            spId: existingProd ? existingProd.spId : '',
            prodName: existingProd ? existingProd.prodName : prodName,
            codeSP: codeSPInput || (existingProd ? existingProd.codeSP : ''),
            unit: unitInput || (existingProd ? existingProd.unit : CONFIG.DEFAULT_UNIT),
            qty: qtyInput > 0 ? qtyInput : 0,
            price: priceInput > 0 ? priceInput : (existingProd ? existingProd.price : 0),
            giaKhuon: existingProd ? existingProd.giaKhuon : 0,
            mang: existingProd ? existingProd.mang : '',
            type: existingProd ? existingProd.type : '1',
            donggoi: existingProd ? existingProd.donggoi : '',
            ngayDat: todayStr,
            ngayGiao: defaultDeliveryStr,
            deliveryDate: defaultDeliveryStr,
            note: noteInput,
            isNew: !existingProd,
            isNewProduct: !existingProd
          });
        }
      }
    }

    // Nếu mở Modal khi sheet TAO DON đang trống -> Khởi tạo sẵn 1 PO Card mặc định
    if (poGroupsList.length === 0) {
      const defaultPO = CONFIG.ORDER_CODE_PREFIX + yymmdd + '-NEW';
      poGroupsList.push({
        customerName: '',
        maKH: '',
        isNewCustomer: false,
        soPO: defaultPO,
        autoPONumber: defaultPO,
        salesPerson: catalog.currentUser.isAuthenticated
          ? catalog.currentUser.maNV
          : (catalog.salesStaffList[0] ? catalog.salesStaffList[0].maNV : ''),
        ngayDat: todayStr,
        ngayGiaoDK: defaultDeliveryStr,
        orderNote: '',
        existingFileUrl: '',
        items: [{
          spId: '',
          prodName: '',
          codeSP: '',
          unit: webEntry ? catalog.orderUnits[0] : (CONFIG.DEFAULT_UNIT || 'Cái'),
          qty: webEntry ? 0 : 5000,
          price: 0,
          giaKhuon: 0,
          mang: '',
          type: '1',
          donggoi: '',
          ngayDat: todayStr,
          ngayGiao: defaultDeliveryStr,
          deliveryDate: defaultDeliveryStr,
          note: '',
          isNew: true,
          isNewProduct: true
        }]
      });
    }

    return {
      hasSourceSheet: Boolean(wsSheet),
      orderUnits: catalog.orderUnits,
      poGroups: poGroupsList,
      salesStaffList: catalog.salesStaffList,
      currentUser: catalog.currentUser,
      customers: catalog.customers.map(function(c) {
        return { maKH: c.maKH, name: c.name };
      }),
      products: catalog.products.map(function(p) {
        return {
          spId: p.spId,
          customerId: p.customerId,
          prodName: p.prodName,
          codeSP: p.codeSP,
          unit: p.unit,
          price: p.price,
          mang: p.mang,
          type: p.type,
          donggoi: p.donggoi,
          giaKhuon: p.giaKhuon
        };
      }),
      serverDate: todayStr,
      defaultDeliveryDate: defaultDeliveryStr
    };
  },

  /**
   * ==========================================================================
   * QUY TRÌNH LƯU LIÊN TẦNG (FLOW-BASED UPSERT SEQUENCE) CÓ LOCKSERVICE
   * ==========================================================================
   * Bước 1: Khóa chống xung đột (LockService.getScriptLock().waitLock(30000))
   * Bước 2: Xác thực dữ liệu đầu vào & xác thực nhân viên kinh doanh
   * Bước 3: Quét & Upsert Khách hàng mới (KHxxxx) vào '01_KHACH_HANG'
   * Bước 4: Quét & Upsert Sản phẩm mới (SPxxxx) vào '02_SAN_PHAM'
   * Bước 5: Upload file PO đính kèm (Base64 -> Blob) lên Drive 'ID_STORAGES'
   * Bước 6: Sinh mã Đơn hàng (DH_yymmdd_xx) & Chi tiết (CT_yymmdd_xx)
   * Bước 7: Ghi theo lô theo từng bảng tính
   * Bước 8: Xóa trắng dữ liệu vùng A8:I trên sheet 'TAO DON' & Giải phóng khóa
   */
  /**
   * Lưu giao dịch đơn hàng theo lô riêng cho MASTER và Operation.
   */
  saveOrderTransaction: function(payload) {
    const isDebug = typeof CONFIG !== 'undefined' && Boolean(CONFIG.DEBUG_MODE);
    if (isDebug) console.log("⏱️ [ORDER_SERVICE] Bắt đầu tiến trình lưu đơn hàng...");

    const requestId = String(payload && payload.requestId || '');
    if (requestId && !/^[a-zA-Z0-9-]{16,64}$/.test(requestId)) throw new Error('Mã yêu cầu lưu không hợp lệ.');
    const lock = LockService.getScriptLock();
    const timeoutMs = (CONFIG && CONFIG.LOCK_TIMEOUT_MS) ? CONFIG.LOCK_TIMEOUT_MS : 30000;
    
    // 1. Xin khóa độc quyền (Tối đa 30s)
    let hasLock = false;
    try {
      hasLock = lock.tryLock(timeoutMs);
    } catch (e) {
      hasLock = false;
    }

    if (!hasLock) {
      throw new Error("Hệ thống đang bận xử lý giao dịch từ người dùng khác. Vui lòng thử lại sau vài giây! (ERR_LOCK_TIMEOUT)");
    }

    try {
      const masterSS = this.getMasterSpreadsheet_();
      const access = readUserPermissions_(masterSS);
      requirePermission_(access, CONFIG.PERMISSIONS.ORDER_CREATE);
      const operSS = this.getOperationSpreadsheet_();
      // Receipts are committed with the order rows. Keep a bounded retry history per user.
      const receiptKey = 'NAPACO_ORDER_SAVE_' + access.userId;
      const receipts = requestId ? operSS.createDeveloperMetadataFinder().withKey(receiptKey).find() : [];
      const receipt = receipts.find(entry => entry.getValue().startsWith(requestId + '|'));
      if (receipt) {
        const [, day, first, count, details, customers, products] = receipt.getValue().split('|');
        const createdOrders = Array.from({ length: Number(count) }, (_, index) => ({
          maDH: 'DH_' + day + '_' + String(Number(first) + index).padStart(2, '0'),
          soPO: payload.poGroups[index]?.soPO || '',
          itemCount: payload.poGroups[index]?.items?.length || 0
        }));
        return {
          success: true, createdOrders, newCustomerCount: Number(customers), newProductCount: Number(products),
          message: 'Đã lưu thành công ' + count + ' đơn hàng gồm ' + details + ' chi tiết mặt hàng!'
        };
      }


      const custSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.CUSTOMERS);
      const prodSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.PRODUCTS);
      const orderSheet = operSS.getSheetByName(CONFIG.SHEET_NAMES.ORDERS);
      const detailSheet = operSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);

      if (!orderSheet || !detailSheet) {
        throw new Error("Không tìm thấy các bảng giao dịch 01.DonHang hoặc 02.ChiTietDH!");
      }

      const names = CONFIG.SHEET_NAMES;
      const schema = CONFIG.COLUMNS;
      const productKeys = ['ID', 'CUSTOMER_ID', 'FILM', 'TYPE', 'CODE_CUST', 'NAME',
        'CAVITY', 'STOCK', 'UNIT', 'PACKING', 'MOLD_PRICE', 'PRICE'];
      const detailKeys = ['ID', 'ORDER_ID', 'PRODUCT_ID', 'QTY_ORDER', 'PRICE', 'QTY_RUN',
        'QTY_DELIVERED', 'QTY_REMAINING', 'NOTE', 'DELIVERY_DATE', 'STAFF_ID', 'STATUS'];
      const customerTable = this.readDatabaseTable_(custSheet, names.CUSTOMERS, schema.CUSTOMERS, ['ID', 'NAME']);
      const productTable = this.readDatabaseTable_(prodSheet, names.PRODUCTS, schema.PRODUCTS, productKeys);
      const orderTable = this.readDatabaseTable_(orderSheet, names.ORDERS, schema.ORDERS, Object.keys(schema.ORDERS), true);
      const detailTable = this.readDatabaseTable_(detailSheet, names.ORDER_DETAILS, schema.ORDER_DETAILS, detailKeys, true);
      const { rows: custData, columns: custCols } = customerTable;
      const { rows: prodData, columns: prodCols } = productTable;
      const customerNamesById = new Map();
      const khMap = Object.create(null); // Tên KH (lowercase) -> Ma_KH
      let maxKhSeq = 0;

      for (let i = customerTable.headerRow + 1; i < custData.length; i++) {
        const ma = String(custData[i][custCols.ID] || '').trim();
        const ten = String(custData[i][custCols.NAME] || '').trim();
        if (ma && ten) {
          khMap[ten.toLowerCase()] = ma;
          customerNamesById.set(ma, ten.toLowerCase());
        }
        
        // Trích xuất số lớn nhất từ các mã KH (VD: KH0214 -> 214)
        const matchKh = ma.match(/KH(\d+)/i);
        if (matchKh) {
          const num = parseInt(matchKh[1], 10);
          if (num > maxKhSeq) maxKhSeq = num;
        }
      }

      const prodMap = Object.create(null); // Tên SP + Mã KH -> SP_ID
      let maxSpSeq = 0;
      const prodRowIndexMap = Object.create(null);
      for (let j = productTable.headerRow + 1; j < prodData.length; j++) {
        const spId = String(prodData[j][prodCols.ID] || '').trim();
        const cusId = String(prodData[j][prodCols.CUSTOMER_ID] || '').trim();
        const spName = String(prodData[j][prodCols.NAME] || '').trim().toLowerCase();
        if (spId && spName) {
          prodMap[spName + '__' + cusId] = spId;
          if (!prodMap[spName]) prodMap[spName] = spId;
          prodRowIndexMap[spId] = j + 1; // j bắt đầu từ 1 (hàng 2 trên Sheet), nên dòng thực tế là j + 1
        }

        // Trích xuất số lớn nhất từ các mã SP (VD: SP2174 -> 2174)
        const matchSp = spId.match(/SP(\d+)/i);
        if (matchSp) {
          const num = parseInt(matchSp[1], 10);
          if (num > maxSpSeq) maxSpSeq = num;
        }
      }

      // Biến tăng tuần tự chuẩn xác cho các bản ghi mới phát sinh trong giao dịch
      let currentMaxKh = maxKhSeq;
      let currentMaxSp = maxSpSeq;

      const poGroups = payload.webOrder ? this.normalizeAndValidatePayload_(payload) : (payload.poGroups || []);
      const allowedUnits = payload.webOrder
        ? this.readOrderUnits_(masterSS, prodData, productTable.headerRow, prodCols.UNIT).map(unit => unit.toLowerCase())
        : [];
      const salesCodes = payload.webOrder
        ? new Set(this.readOrderStaff_(masterSS).salesStaffList.map(person => person.maNV))
        : null;
      const createdOrders = [];
      const headerRows = [];
      const detailRows = [];
      const newCustRows = [];
      const newProdRows = [];
      const productUpdates = new Map();
      const attachments = [];

      const todayStr = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd");
      const yymmdd = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyMMdd");

      // Đếm số thứ tự đơn hàng và chi tiết trong ngày
      let orderSeq = 1;
      let detailSeq = 1;

      // Quét đơn hàng hiện có để lấy sequence lớn nhất trong ngày
      const orderRegex = new RegExp(`^DH_${yymmdd}_(\\d+)$`, 'i');
      for (const id of orderTable.ids) {
        const match = String(id || '').match(orderRegex);
        if (match) {
          const num = parseInt(match[1], 10);
          if (num >= orderSeq) orderSeq = num + 1;
        }
      }

      const detailRegex = new RegExp(`^CT_${yymmdd}_(\\d+)$`, 'i');
      for (const id of detailTable.ids) {
        const match = String(id || '').match(detailRegex);
        if (match) {
          const num = parseInt(match[1], 10);
          if (num >= detailSeq) detailSeq = num + 1;
        }
      }

      // 3. Xử lý từng khối PO
      for (let g = 0; g < poGroups.length; g++) {
        const grp = poGroups[g];
        const cusName = String(grp.customerName || 'Khách lẻ').trim();
        const cusKey = cusName.toLowerCase();
        const selectedCustomerId = payload.webOrder ? String(grp.customerId || '').trim() : '';
        if (selectedCustomerId && customerNamesById.get(selectedCustomerId) !== cusKey) {
          throw new Error('Thông tin khách hàng của PO "' + grp.soPO + '" đã thay đổi. Vui lòng tải lại trang.');
        }
        let targetMaKH = selectedCustomerId || khMap[cusKey];

        // Nếu là Khách Hàng mới -> Tự sinh mã KHxxxx
        // Nếu là Khách Hàng mới -> Lấy số lớn nhất hiện tại + 1
        if (!targetMaKH) {
          currentMaxKh++;
          targetMaKH = 'KH' + String(currentMaxKh).padStart(4, '0');
          khMap[cusKey] = targetMaKH;
          newCustRows.push({ ID: targetMaKH, NAME: cusName });
        }

        // Sinh mã đơn hàng: DH_yymmdd_xx
        const maDH = `DH_${yymmdd}_` + String(orderSeq++).padStart(2, '0');
        if (salesCodes && grp.salesPerson !== access.userId && !salesCodes.has(grp.salesPerson)) {
          throw new Error('Nhân viên kinh doanh của PO "' + grp.soPO + '" không hợp lệ.');
        }
        const ngayGiaoDK = payload.webOrder
          ? grp.items.reduce((latest, item) => item.ngayGiao > latest ? item.ngayGiao : latest, '')
          : (grp.ngayGiaoDK || todayStr);
        const soPO = grp.soPO || `PO-${yymmdd}-${cusName}`;

        // Header: [Ma_DH, MaKH, NgayDat, NgayGiaoDK, So_PO, File_PO]
        headerRows.push({
          ID: maDH, CUSTOMER_ID: targetMaKH, ORDER_DATE: payload.webOrder ? grp.items[0].ngayDat : todayStr, DELIVERY_DATE: ngayGiaoDK,
          PO_NUMBER: soPO, FILE_URL: grp.existingFileUrl || ''
        });

        if (grp.fileData && grp.fileData.base64) {
          attachments.push({ header: headerRows[headerRows.length - 1], file: grp.fileData });
        }

        // Xử lý các dòng sản phẩm con
        const items = grp.items || [];
        for (let it = 0; it < items.length; it++) {
          const item = items[it];
          const prodName = String(item.prodName || '').trim();
          const prodKey = prodName.toLowerCase() + '__' + targetMaKH;
          const selectedSpId = payload.webOrder ? String(item.spId || '').trim() : '';
          if (selectedSpId) {
            const product = prodData[prodRowIndexMap[selectedSpId] - 1];
            if (!product || String(product[prodCols.CUSTOMER_ID] || '').trim() !== targetMaKH ||
                String(product[prodCols.NAME] || '').trim().toLowerCase() !== prodName.toLowerCase()) {
              throw new Error('Sản phẩm "' + prodName + '" không khớp với danh mục của khách hàng "' + cusName + '".');
            }
          }
          let targetSpId = selectedSpId || prodMap[prodKey];
          if (!payload.webOrder && !targetSpId) targetSpId = prodMap[prodName.toLowerCase()];
          if (payload.webOrder) {
            const previousProduct = prodData[prodRowIndexMap[targetSpId] - 1];
            const previousUnit = previousProduct ? String(previousProduct[prodCols.UNIT] || 'Cái').trim().toLowerCase() : '';
            const unit = String(item.unit).trim().toLowerCase();
            if (!allowedUnits.includes(unit) && unit !== previousUnit) {
              throw new Error('Đơn PO "' + soPO + '" - Dòng #' + (it + 1) + ': Đơn vị tính không có trong danh sách.');
            }
          }

          // Nếu là Sản Phẩm mới -> Tự sinh mã SPxxxx
          // Nếu là Sản Phẩm mới -> Lấy số lớn nhất hiện tại + 1
          if (!targetSpId) {
            currentMaxSp++;
            targetSpId = 'SP' + String(currentMaxSp).padStart(4, '0');
            prodMap[prodKey] = targetSpId;
            newProdRows.push({
              ID: targetSpId, CUSTOMER_ID: targetMaKH, FILM: item.mang || '', TYPE: item.type || '1',
              CODE_CUST: item.codeSP || '', NAME: prodName, CAVITY: 0, STOCK: 0, UNIT: item.unit || 'Cái',
              PACKING: item.donggoi || '', MOLD_PRICE: item.giaKhuon || 0, PRICE: item.price || 0
            });
          } else {
            // Sản phẩm đã tồn tại -> Cập nhật lại thông số mới nhất vào bảng 02_SAN_PHAM
            const spRowIdx = prodRowIndexMap[targetSpId];
            if (spRowIdx) {
              const updates = {
                FILM: item.mang, TYPE: item.type, CODE_CUST: item.codeSP, UNIT: item.unit,
                PACKING: item.donggoi, MOLD_PRICE: Math.max(0, Number(item.giaKhuon)),
                PRICE: Math.max(0, Number(item.price))
              };
              if (!productUpdates.has(spRowIdx)) productUpdates.set(spRowIdx, new Map());
              const cells = productUpdates.get(spRowIdx);
              for (const [key, value] of Object.entries(updates)) {
                if (value) cells.set(prodCols[key], value);
              }
            }
          }

          // Sinh mã chi tiết: CT_yymmdd_xx
          const idChiTiet = `CT_${yymmdd}_` + String(detailSeq++).padStart(2, '0');
          const slDat = Number(item.qty) || 0;
          const donGia = Number(item.price) || 0;
          const ngayGiao = payload.webOrder ? item.ngayGiao : (item.deliveryDate || item.ngayGiao || ngayGiaoDK);
          const maNV = grp.salesPerson ? String(grp.salesPerson).split(' - ')[0].trim() : '';

          // Line Item: [ID_Chi_Tiet, ID_DonHang, Ma_SP, So_Luong_Dat, Don_Gia, So_Luong_Da_Chay, SL_Da_Giao, SL_Con_Lai, Ghi_Chu, Ngay_Giao, Ma_NV, Trang_Thai]
          detailRows.push({
            ID: idChiTiet, ORDER_ID: maDH, PRODUCT_ID: targetSpId, QTY_ORDER: slDat, PRICE: donGia,
            QTY_RUN: 0, QTY_DELIVERED: 0, QTY_REMAINING: slDat, NOTE: item.note || grp.orderNote || '',
            DELIVERY_DATE: ngayGiao, STAFF_ID: maNV, STATUS: CONFIG.LINE_STATUS.NEW
          });
        }

        createdOrders.push({
          maDH: maDH,
          soPO: soPO,
          itemCount: items.length
        });
      }

      // 4. Gom các ô sản phẩm cũ vào một lần ghi, giữ nguyên các cột ngoài cập nhật.
      const productRequests = [];
      if (productUpdates.size) {
        const sheetId = prodSheet.getSheetId();
        for (const [row, cells] of productUpdates) {
          for (const [columnIndex, value] of cells) {
            const userEnteredValue = typeof value === 'number' ? { numberValue: value } : { stringValue: String(value) };
            productRequests.push({ updateCells: {
              start: { sheetId, rowIndex: row - 1, columnIndex },
              rows: [{ values: [{ userEnteredValue }] }],
              fields: 'userEnteredValue'
            } });
          }
        }
      }
      if (attachments.length) {
        const folder = this.getStorageFolder_();
        for (const { header, file } of attachments) {
          const bytes = Utilities.base64Decode(file.base64);
          if (bytes.length > CONFIG.MAX_FILE_SIZE_BYTES) {
            throw new Error('Tệp đính kèm vượt quá giới hạn của PO ' + header.PO_NUMBER + '.');
          }
          const extension = String(file.fileName || '').match(/\.[a-zA-Z0-9]+$/);
          const name = String(header.PO_NUMBER).replace(/[\\/:*?"<>|]/g, '_') + (extension ? extension[0] : '.pdf');
          header.FILE_URL = folder.createFile(Utilities.newBlob(bytes, file.mimeType || 'application/pdf', name)).getUrl();
        }
      }

      const operationWrites = [];
      this.appendDatabaseRows_(productRequests, customerTable, newCustRows);
      this.appendDatabaseRows_(productRequests, productTable, newProdRows);
      this.appendDatabaseRows_(operationWrites, orderTable, headerRows);
      this.appendDatabaseRows_(operationWrites, detailTable, detailRows);
      if (requestId && headerRows.length) {
        // Leave room for retries of recent requests, including multiple open modals.
        const oldest = receipts.map(entry => ({
          id: entry.getId(), timestamp: Number(entry.getValue().split('|').pop())
        })).sort((a, b) => a.timestamp - b.timestamp).slice(0, Math.max(0, receipts.length - 19));
        for (const entry of oldest) {
          operationWrites.push({ deleteDeveloperMetadata: { dataFilter: { developerMetadataLookup: {
            metadataId: entry.id
          } } } });
        }
        const first = orderSeq - headerRows.length;
        operationWrites.push({ createDeveloperMetadata: { developerMetadata: {
          metadataKey: receiptKey,
          metadataValue: [requestId, yymmdd, first, headerRows.length, detailRows.length, newCustRows.length,
            newProdRows.length, Date.now()].join('|'),
          visibility: 'DOCUMENT',
          location: { spreadsheet: true }
        } } });
      }
      if (productRequests.length) Sheets.Spreadsheets.batchUpdate({ requests: productRequests }, masterSS.getId());
      if (operationWrites.length) Sheets.Spreadsheets.batchUpdate({ requests: operationWrites }, operSS.getId());

      // 5. Dọn dẹp dòng dữ liệu nháp trên Sheet 'TAO DON'
      if (payload.sourceSpreadsheetId) {
        try {
          const clientSS = SpreadsheetApp.openById(payload.sourceSpreadsheetId);
          const wsSheet = clientSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_WORKSPACE || 'TAO DON');
          if (wsSheet && wsSheet.getLastRow() >= 8) {
            wsSheet.getRange('A8:I' + wsSheet.getLastRow()).clearContent();
            SpreadsheetApp.flush();
          }
        } catch (wsErr) {
          console.warn("⚠️ Không thể xóa dòng nháp TAO DON:", wsErr.message);
        }
      }

      if (isDebug) console.log("✅ [ORDER_SERVICE] Lưu đơn hàng thành công!");

      return {
        success: true,
        createdOrders: createdOrders,
        newCustomerCount: newCustRows.length,
        newProductCount: newProdRows.length,
        message: `Đã lưu thành công ${createdOrders.length} đơn hàng gồm ${detailRows.length} chi tiết mặt hàng!`
      };

    } finally {
      // 6. BẮT BUỘC: Luôn luôn giải phóng khóa trong khối finally
      lock.releaseLock();
      if (isDebug) console.log("🔒 [ORDER_SERVICE] Đã giải phóng ScriptLock an toàn.");
    }
  },

  /**
   * ==========================================================================
   * TRA CỨU ĐƠN HÀNG & CHI TIẾT MẶT HÀNG (DUAL-VIEW: HEADER & LINE_ITEM)
   * ==========================================================================
   */
  queryOrdersAndLineItems: function(searchParams) {
    const params = searchParams || {};
    const requestedView = String(params.viewMode || 'HEADER').toUpperCase();
    const viewMode = ['LINE_ITEM', 'ALL_VIEWS'].includes(requestedView) ? requestedView : 'HEADER';
    const keyword = String(params.keyword || '').trim().toLowerCase();
    const maKHFilter = String(params.maKH || 'ALL').trim();
    /* [SỬA LỖI] Bỏ toLowerCase() để giữ nguyên hằng số nhóm ACTIVE_ALL / DONE_ALL */
    const statusFilter = String(params.status || 'ALL').trim();
    const orderIds = new Set(String(params.orderIds || '').split(',')
      .filter(id => /^DH_\d{6}_\d+$/.test(id)));
    const fromDate = String(params.fromDate || '').trim();
    const toDate = String(params.toDate || '').trim();
    const page = Math.max(1, parseInt(params.page, 10) || 1);
    const pageSize = Math.max(1, parseInt(params.pageSize, 10) || 100);

    const env = getSecureEnv_();
    const masterSS = readOrderMaster_(env.ID_MASTER, true);
    const catalog = this.getCatalogAndAuthData(masterSS);
    const productType = viewMode === 'ALL_VIEWS'
      ? (String(params.productType || '').trim() === '2' ? '2' : '1')
      : '';
    if (productType && !catalog.productTypeById) {
      throw new Error('Không tìm thấy cột ' + CONFIG.COLUMNS.PRODUCTS.TYPE + ' trong ' + CONFIG.SHEET_NAMES.PRODUCTS + '.');
    }
    const opSS = createReadBook_(env.ID_OPERATION, [CONFIG.SHEET_NAMES.ORDERS, CONFIG.SHEET_NAMES.ORDER_DETAILS]);
    const orderSheet = opSS.getSheetByName(CONFIG.SHEET_NAMES.ORDERS);
    const detailSheet = opSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);

    if (!orderSheet || !detailSheet) {
      throw new Error('Không tìm thấy bảng 01.DonHang hoặc 02.ChiTietDH!');
    }

    const orderRows = orderSheet.getDataRange().getValues();
    const detailRows = detailSheet.getDataRange().getValues();

    const moldMap = this.getMoldsMap_(masterSS);

    // =========================================================================
    // 1. [ĐƯA LÊN TRƯỚC] ÁNH XẠ HEADER ĐƠN HÀNG (01.DonHang) TẠO orderMap TRƯỚC
    // =========================================================================
    const oHdrs = orderRows[0].map(h => String(h || '').trim().toLowerCase());
    const colOMaDH = oHdrs.indexOf(CONFIG.COLUMNS.ORDERS.ID.toLowerCase());
    const colOMaKH = oHdrs.indexOf(CONFIG.COLUMNS.ORDERS.CUSTOMER_ID.toLowerCase());
    const colONgayDat = oHdrs.indexOf(CONFIG.COLUMNS.ORDERS.ORDER_DATE.toLowerCase());
    const colONgayGiao = oHdrs.indexOf(CONFIG.COLUMNS.ORDERS.DELIVERY_DATE.toLowerCase());
    const colOSoPO = oHdrs.indexOf(CONFIG.COLUMNS.ORDERS.PO_NUMBER.toLowerCase());
    const colOFilePO = oHdrs.indexOf(CONFIG.COLUMNS.ORDERS.FILE_URL.toLowerCase());

    const orderMap = {};
    const orderHeadersList = [];

    for (let i = 1; i < orderRows.length; i++) {
      const oRow = orderRows[i];
      const maDH = colOMaDH !== -1 ? String(oRow[colOMaDH] || '').trim() : '';
      if (!maDH) continue;

      const maKH = colOMaKH !== -1 ? String(oRow[colOMaKH] || '').trim() : '';
      const ngayDat = colONgayDat !== -1 ? this.formatSheetDate_(oRow[colONgayDat]) : '';
      const ngayGiaoDK = colONgayGiao !== -1 ? this.formatSheetDate_(oRow[colONgayGiao]) : '';
      const soPO = colOSoPO !== -1 ? String(oRow[colOSoPO] || '').trim() : '';
      const filePO = colOFilePO !== -1 ? String(oRow[colOFilePO] || '').trim() : '';

      const cusObj = catalog.customerByIdMap[maKH];
      const khachHangName = cusObj ? cusObj.name : maKH;

      const headerObj = {
        maDH: maDH,
        maKH: maKH,
        khachHang: khachHangName,
        ngayDat: ngayDat,
        ngayGiaoDK: ngayGiaoDK,
        soPO: soPO,
        filePO: filePO,
        tongSLDat: 0,
        tongDaGiao: 0,
        tongConLai: 0,
        tongGiaTri: 0,
        itemCount: 0,
        salesPerson: '',
        trangThai: CONFIG.ORDER_STATUS.NEW,
        items: []
      };

      orderMap[maDH] = headerObj;
      orderHeadersList.push(headerObj);
    }

    // =========================================================================
    // 2. ÁNH XẠ DÒNG CHI TIẾT MẶT HÀNG (02.ChiTietDH) - DÙNG orderMap AN TOÀN
    // =========================================================================
    const dHdrs = detailRows[0].map(h => String(h || '').trim().toLowerCase());
    const colDId = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.ID.toLowerCase());
    const colDOrderId = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.ORDER_ID.toLowerCase());
    const colDSpId = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.PRODUCT_ID.toLowerCase());
    const colDQty = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.QTY_ORDER.toLowerCase());
    const colDPrice = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.PRICE.toLowerCase());
    const colDQtyRun = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.QTY_RUN.toLowerCase());
    const colDQtyDel = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.QTY_DELIVERED.toLowerCase());
    const colDQtyRem = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.QTY_REMAINING.toLowerCase());
    const colDNote = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.NOTE.toLowerCase());
    const colDDate = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.DELIVERY_DATE.toLowerCase());
    const colDStaff = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.STAFF_ID.toLowerCase());
    const colDStatus = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.STATUS.toLowerCase());

    const allLineItems = [];
    for (let j = 1; j < detailRows.length; j++) {
      const row = detailRows[j];

      const idChiTiet = colDId !== -1 ? String(row[colDId] || '').trim() : '';
      const idDonHang = colDOrderId !== -1 ? String(row[colDOrderId] || '').trim() : '';
      if (!idChiTiet || !idDonHang) continue;

      const maSP = colDSpId !== -1 ? String(row[colDSpId] || '').trim() : '';
      const slDat = colDQty !== -1 ? (Number(row[colDQty]) || 0) : 0;
      const donGia = colDPrice !== -1 ? (Number(row[colDPrice]) || 0) : 0;
      const slDaChay = colDQtyRun !== -1 ? (Number(row[colDQtyRun]) || 0) : 0;
      const slDaGiao = colDQtyDel !== -1 ? (Number(row[colDQtyDel]) || 0) : 0;
      const slConLaiRaw = colDQtyRem !== -1 ? row[colDQtyRem] : '';
      const slConLai = (slConLaiRaw !== '' && slConLaiRaw !== null && slConLaiRaw !== undefined)
        ? Number(slConLaiRaw)
        : Math.max(0, slDat - slDaGiao);
      const ghiChu = colDNote !== -1 ? String(row[colDNote] || '').trim() : '';
      const ngayGiao = colDDate !== -1 ? this.formatSheetDate_(row[colDDate]) : '';
      const maNV = colDStaff !== -1 ? String(row[colDStaff] || '').trim() : '';
      const trangThaiRaw = colDStatus !== -1 ? String(row[colDStatus] || CONFIG.LINE_STATUS.NEW).trim() : CONFIG.LINE_STATUS.NEW;

      const parentOrder = orderMap[idDonHang];
      const prodObj = catalog.productByIdMap[maSP] || catalog.productByIdMap[maSP.toUpperCase()];
      const tenSalesVal = this.resolveStaffName_(maNV, catalog.employeeByIdMap, catalog.salesStaffList);

      const sanPhamName = prodObj ? prodObj.prodName : maSP;
      const codeSP = prodObj ? prodObj.codeSP : '';
      const dvt = prodObj ? prodObj.unit : 'Cái';
      const mangVal = prodObj && prodObj.mang ? prodObj.mang : '---';
      const moldInfo = moldMap[maSP] || { dinhHinh: [], dao: [] };

      const lineObj = {
        idChiTiet: idChiTiet,
        maDH: idDonHang,
        soPO: parentOrder ? parentOrder.soPO : '',
        filePO: parentOrder ? parentOrder.filePO : '',
        maKH: parentOrder ? parentOrder.maKH : (prodObj ? prodObj.customerId : ''),
        khachHang: parentOrder ? parentOrder.khachHang : '',
        ngayDat: parentOrder ? parentOrder.ngayDat : '',
        maSP: maSP,
        codeSP: codeSP,
        sanPham: sanPhamName,
        dvt: dvt,
        slDat: slDat,
        donGia: donGia,
        thanhTien: slDat * donGia,
        daChay: slDaChay,
        daGiao: slDaGiao,
        conLai: slConLai,
        ghiChu: ghiChu,
        ngayGiao: ngayGiao || (parentOrder ? parentOrder.ngayGiaoDK : ''),
        maNV: maNV,
        tenNV: tenSalesVal,
        trangThai: trangThaiRaw,
        mang: mangVal,
        moldInfo: moldInfo,
        imageURL: prodObj ? prodObj.imageURL : '',
        giaKhuon: prodObj ? prodObj.giaKhuon : 0
      };

      allLineItems.push(lineObj);

      if (parentOrder) {
        parentOrder.items.push(lineObj);
        parentOrder.itemCount++;
        parentOrder.tongSLDat += slDat;
        parentOrder.tongDaGiao += slDaGiao;
        parentOrder.tongConLai += slConLai;
        parentOrder.tongGiaTri += (slDat * donGia);
        if (!parentOrder.salesPerson && lineObj.tenNV && lineObj.tenNV !== '---') {
          parentOrder.salesPerson = lineObj.tenNV;
        }
      }
    }

    // 3. Tính toán Tiến độ & Trạng thái tổng hợp cho từng PO Header
    for (let h = 0; h < orderHeadersList.length; h++) {
      const ord = orderHeadersList[h];
      const progressPct = ord.tongSLDat > 0 ? Math.min(100, Math.round((ord.tongDaGiao / ord.tongSLDat) * 100)) : 0;
      ord.tienDo = progressPct + '% (' + ord.tongDaGiao.toLocaleString('vi-VN') + '/' + ord.tongSLDat.toLocaleString('vi-VN') + ')';
      ord.progressPercent = progressPct;

      if (ord.itemCount > 0 && ord.tongConLai <= 0 && ord.tongSLDat > 0) {
        ord.trangThai = 'Hoàn tất';
      } else if (ord.tongDaGiao > 0 || ord.items.some(function(it) { return it.daChay > 0 || it.trangThai.toLowerCase().indexOf('đang') !== -1; })) {
        ord.trangThai = 'Đang sản xuất';
      } else {
        ord.trangThai = 'Chờ sản xuất';
      }
    }

    /* [MỚI - Ý 5 & RÀ SOÁT HARDCODE] Hàm helper kiểm tra khớp trạng thái theo phân nhóm CONFIG */
    /* [SỬA LỖI] Hàm helper kiểm tra khớp trạng thái bao quát case-sensitive */
    const isStatusMatch = function(itemStatus, filterVal) {
      const fValUpper = String(filterVal).trim().toUpperCase();
      if (!filterVal || fValUpper === 'ALL') return true;
      
      const sLow = String(itemStatus || '').toLowerCase().trim();

      // Nhóm 1: Tất cả đơn đang chạy (Loại trừ các trạng thái đã đóng/hủy)
      if (fValUpper === CONFIG.FILTER_STATUS_GROUPS.ACTIVE_ALL) {
        const isDone = sLow.includes(CONFIG.LINE_STATUS.COMPLETED.toLowerCase()) || 
                       sLow.includes(CONFIG.LINE_STATUS.CLOSED.toLowerCase()) ||
                       sLow.includes(CONFIG.ORDER_STATUS.CANCELLED.toLowerCase()) ||
                       sLow.includes('hoàn tất');
        return !isDone;
      }
      
      // Nhóm 2: Tất cả đơn đã xong/kết thúc
      if (fValUpper === CONFIG.FILTER_STATUS_GROUPS.DONE_ALL) {
        return sLow.includes(CONFIG.LINE_STATUS.COMPLETED.toLowerCase()) || 
               sLow.includes(CONFIG.LINE_STATUS.CLOSED.toLowerCase()) ||
               sLow.includes('hoàn tất');
      }
      
      // Trạng thái cụ thể: ép về lowercase để tìm kiếm tương đối (ví dụ tìm: "chờ sản xuất")
      return sLow.includes(String(filterVal).trim().toLowerCase());
    };

    // Dùng cùng điều kiện lọc chi tiết cho cả Header và Line-Item.
      const validLines = allLineItems.filter(function(item) {
        if (productType && catalog.productTypeById.get(item.maSP.toUpperCase()) !== productType) return false;
        if (maKHFilter && maKHFilter !== 'ALL' && item.maKH !== maKHFilter && item.khachHang !== maKHFilter) {
          return false;
        }
        /* [MỚI - Ý 5] Lọc trạng thái theo điều kiện HOẶC chuẩn xác */
        if (statusFilter && statusFilter !== 'ALL' && statusFilter !== 'all') {
          const sLow = item.trangThai.toLowerCase().trim();
          if (statusFilter === CONFIG.FILTER_STATUS_GROUPS.ACTIVE_ALL) {
            // Điều kiện HOẶC: Chờ sản xuất HOẶC Đang làm khuôn HOẶC Đang sản xuất
            const isChoSX = sLow.includes(CONFIG.LINE_STATUS.NEW.toLowerCase());
            const isKhuon = sLow.includes(CONFIG.LINE_STATUS.MOLDING.toLowerCase()) || sLow.includes('khuôn');
            const isDangSX = sLow.includes(CONFIG.LINE_STATUS.IN_PRODUCTION.toLowerCase()) && !sLow.includes('chờ');
            if (!isChoSX && !isKhuon && !isDangSX) return false;
          } else if (statusFilter === CONFIG.FILTER_STATUS_GROUPS.DONE_ALL) {
            // Điều kiện HOẶC: Xong HOẶC Kết thúc HOẶC Hoàn tất
            const isXong = sLow.includes(CONFIG.LINE_STATUS.COMPLETED.toLowerCase());
            const isKetThuc = sLow.includes(CONFIG.LINE_STATUS.CLOSED.toLowerCase());
            const isHoanTat = sLow.includes(CONFIG.ORDER_STATUS.COMPLETED.toLowerCase());
            if (!isXong && !isKetThuc && !isHoanTat) return false;
          } else {
            if (sLow.indexOf(statusFilter.toLowerCase()) === -1) return false;
          }
        }
        if (fromDate && item.ngayDat && item.ngayDat < fromDate) return false;
        if (toDate && item.ngayGiao && item.ngayGiao > toDate) return false;
        if (orderIds.size && !orderIds.has(item.maDH)) return false;
        if (keyword) {
          const haystack = [
            item.idChiTiet, item.maDH, item.soPO, item.khachHang,
            item.maSP, item.codeSP, item.sanPham, item.ghiChu, item.tenNV
          ].join(' ').toLowerCase();
          if (haystack.indexOf(keyword) === -1) return false;
        }
        return true;
      });

    const buildLineView = () => {
      const filteredLines = validLines.slice().reverse();
      const total = filteredLines.length;

      /* [MỚI - Ý 5] Kiểm tra giới hạn bản ghi tối đa theo CONFIG */
      const maxLimit = CONFIG.MAX_DISPLAY_RECORDS || 100;
      if (total > maxLimit) {
        return {
          success: false,
          exceededLimit: true,
          total: total,
          maxLimit: maxLimit,
          message: 'Dữ liệu tìm kiếm vượt quá số lượng cho phép (' + total + ' / ' + maxLimit + ' dòng). Vui lòng nhập thêm từ khóa hoặc điều kiện lọc để thu hẹp phạm vi tìm kiếm!'
        };
      }

      const startIndex = (page - 1) * pageSize;
      const pagedData = filteredLines.slice(startIndex, startIndex + pageSize);

      return {
        success: true,
        viewMode: 'LINE_ITEM',
        total: total,
        summary: this.computeQueryMetrics_(null, filteredLines),
        customers: catalog.customers,
        salesStaffList: catalog.salesStaffList,
        data: pagedData
      };
    };

    const buildHeaderView = (sharedLines, includeMissingHeaders = false) => {
      const sourceLines = sharedLines || validLines;
      const itemsByOrder = new Map();
      sourceLines.forEach(function (item) {
        if (!itemsByOrder.has(item.maDH)) itemsByOrder.set(item.maDH, []);
        itemsByOrder.get(item.maDH).push(item);
      });
      const filteredHeaders = [];

      function addHeader(ord, matchedItemsForPO) {
        let subTongSLDat = 0, subTongDaGiao = 0, subTongConLai = 0, subTongGiaTri = 0;
        matchedItemsForPO.forEach(function(it) {
          subTongSLDat += (Number(it.slDat) || 0);
          subTongDaGiao += (Number(it.daGiao) || 0);
          subTongConLai += (Number(it.conLai) || 0);
          subTongGiaTri += ((Number(it.slDat) || 0) * (Number(it.donGia) || 0));
        });

        const cloneOrd = Object.assign({}, ord, {
          items: matchedItemsForPO,
          itemCount: matchedItemsForPO.length,
          tongSLDat: subTongSLDat,
          tongDaGiao: subTongDaGiao,
          tongConLai: subTongConLai,
          tongGiaTri: subTongGiaTri
        });

        filteredHeaders.push(cloneOrd);
      }

      orderHeadersList.forEach(function(ord) {
        if (!itemsByOrder.has(ord.maDH)) return;
        if (includeMissingHeaders && orderMap[ord.maDH] !== ord) return;
        addHeader(ord, itemsByOrder.get(ord.maDH));
        if (includeMissingHeaders) itemsByOrder.delete(ord.maDH);
      });

      // Giữ dòng chi tiết trong kết quả chung kể cả khi thiếu bản ghi đầu đơn.
      if (includeMissingHeaders) {
        itemsByOrder.forEach(function(items, maDH) {
          const first = items[0];
          addHeader({
            maDH: maDH,
            maKH: first.maKH,
            khachHang: first.khachHang,
            soPO: first.soPO,
            ngayDat: first.ngayDat,
            trangThai: 'Thiếu đầu đơn',
            tienDo: '---',
            missingHeader: true
          }, items);
        });
      }

      filteredHeaders.reverse();
      const total = filteredHeaders.length;

      /* [MỚI - Ý 5] Kiểm tra giới hạn bản ghi tối đa theo CONFIG cho Header */
      const maxLimit = CONFIG.MAX_DISPLAY_RECORDS || 100;
      if (total > maxLimit) {
        return {
          success: false,
          exceededLimit: true,
          total: total,
          maxLimit: maxLimit,
          message: 'Dữ liệu tìm kiếm vượt quá số lượng cho phép (' + total + ' / ' + maxLimit + ' đơn). Vui lòng nhập thêm từ khóa hoặc điều kiện lọc để thu hẹp phạm vi tìm kiếm!'
        };
      }

      const startIndex = (page - 1) * pageSize;
      const pagedData = sharedLines
        ? filteredHeaders
        : filteredHeaders.slice(startIndex, startIndex + pageSize);

      return {
        success: true,
        viewMode: 'HEADER',
        total: total,
        summary: this.computeQueryMetrics_(null, sourceLines),
        customers: catalog.customers,
        salesStaffList: catalog.salesStaffList,
        data: pagedData
      };
    };

    if (viewMode === 'ALL_VIEWS') {
      const lineView = buildLineView();
      const headerView = productType === '2' ? null
        : buildHeaderView(lineView.success ? lineView.data.slice().reverse() : null, true);
      if (lineView.success && headerView && headerView.success) lineView.summary = headerView.summary;
      const kanbanView = lineView.success
        ? this.buildLineKanbanData_(detailRows, catalog, new Map(
            lineView.data.map(item => [item.idChiTiet, item])
          ))
        : lineView;
      return {
        success: true,
        customers: catalog.customers,
        salesStaffList: catalog.salesStaffList,
        views: {
          HEADER: headerView,
          LINE_ITEM: lineView,
          KANBAN_LINE: kanbanView
        }
      };
    }

    return viewMode === 'LINE_ITEM' ? buildLineView() : buildHeaderView();
  },

  // ==========================================================================
  // CÁC HÀM HELPER NỘI BỘ (PRIVATE METHODS)
  // ==========================================================================

  /**
   * Chuẩn hóa cấu trúc payload từ Modal (hỗ trợ cả chuẩn poGroups và payload đơn)
   * @private
   */
  normalizeAndValidatePayload_: function(payload) {
    if (!payload) {
      throw new Error('Dữ liệu đơn hàng gửi lên trống!');
    }

    let rawGroups = [];
    if (Array.isArray(payload.poGroups)) {
      rawGroups = payload.poGroups;
    } else if (Array.isArray(payload.items)) {
      // Hỗ trợ tương thích nếu gửi từ form đơn 1 PO
      rawGroups = [{
        customerName: payload.customerName || '',
        soPO: payload.soPO || '',
        salesPerson: payload.salesEmployeeId || payload.salesPerson || '',
        ngayDat: payload.orderDate || payload.ngayDat || '',
        ngayGiaoDK: payload.deliveryDate || payload.ngayGiaoDK || '',
        orderNote: payload.notes || payload.orderNote || '',
        fileData: payload.fileData || null,
        items: payload.items.map(function(it) {
          return {
            prodName: it.prodName || it.productName || '',
            codeSP: it.codeSP || '',
            unit: it.unit || 'Cái',
            qty: Number(it.qty || it.quantity) || 0,
            price: Number(it.price || it.unitPrice) || 0,
            ngayDat: it.ngayDat || payload.orderDate || '',
            ngayGiao: it.ngayGiao || it.deliveryDate || payload.deliveryDate || '',
            note: it.note || it.techNotes || ''
          };
        })
      }];
    }

    if (rawGroups.length === 0) {
      throw new Error('Phải có ít nhất 1 đơn hàng (PO) trong giao dịch!');
    }

    const poCustomerCheck = Object.create(null);
    for (let g = 0; g < rawGroups.length; g++) {
      const grp = rawGroups[g];
      const cusName = String(grp.customerName || '').trim();
      const soPO = String(grp.soPO || '').trim();

      if (!cusName) {
        throw new Error('Đơn PO #' + (g + 1) + ': Tên khách hàng không được để trống!');
      }
      if (!soPO) {
        throw new Error('Đơn PO #' + (g + 1) + ' (' + cusName + '): Số PO không được để trống!');
      }

      if (payload.webOrder && !String(grp.salesPerson || '').trim()) {
        throw new Error('Đơn PO "' + soPO + '": Vui lòng chọn nhân viên kinh doanh.');
      }

      const poKey = soPO.toUpperCase();
      if (payload.webOrder && poCustomerCheck[poKey]) {
        throw new Error('Số PO "' + soPO + '" bị trùng trong cùng đợt lưu.');
      }
      if (poCustomerCheck[poKey] && poCustomerCheck[poKey] !== cusName.toLowerCase()) {
        throw new Error('Số PO "' + soPO + '" đang bị gán trùng cho 2 khách hàng khác nhau trong cùng giao dịch!');
      }
      poCustomerCheck[poKey] = cusName.toLowerCase();

      if (!Array.isArray(grp.items) || grp.items.length === 0) {
        throw new Error('Đơn PO "' + soPO + '" phải có ít nhất 1 dòng sản phẩm!');
      }

      for (let i = 0; i < grp.items.length; i++) {
        const it = grp.items[i];
        if (!it.prodName || !String(it.prodName).trim()) {
          throw new Error('Đơn PO "' + soPO + '" - Dòng #' + (i + 1) + ': Tên sản phẩm không được để trống!');
        }
        const qty = Number(it.qty);
        if (!Number.isFinite(qty) || qty <= 0) {
          throw new Error('Đơn PO "' + soPO + '" - Dòng #' + (i + 1) + ' (' + it.prodName + '): Số lượng đặt phải lớn hơn 0!');
        }
        const price = Number(it.price);
        if (!Number.isFinite(price) || price < 0) {
          throw new Error('Đơn PO "' + soPO + '" - Dòng #' + (i + 1) + ' (' + it.prodName + '): Đơn giá không hợp lệ!');
        }
        if (payload.webOrder) {
          const prefix = 'Đơn PO "' + soPO + '" - Dòng #' + (i + 1) + ': ';
          if (!String(it.unit || '').trim()) throw new Error(prefix + 'Vui lòng chọn đơn vị tính.');
          if (!Number.isFinite(Number(it.giaKhuon)) || Number(it.giaKhuon) < 0) {
            throw new Error(prefix + 'Giá khuôn không hợp lệ.');
          }
          if (!['1', '2'].includes(String(it.type))) throw new Error(prefix + 'Loại gia công không hợp lệ.');
          const isDate = value => {
            if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
            const date = new Date(value + 'T00:00:00Z');
            return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
          };
          if (!isDate(it.ngayDat) || !isDate(it.ngayGiao) || it.ngayGiao < it.ngayDat) {
            throw new Error(prefix + 'Ngày đặt hoặc ngày giao không hợp lệ.');
          }
        }
      }
    }

    return rawGroups;
  },

  /**
   * Đối chiếu Email phiên đăng nhập với bảng 07.NhanVien
   * Nếu khớp email nhân viên đang hoạt động -> Khóa cứng Ma_NV đó ở Backend
   * @private
   */
  resolveAuthenticatedSalesCode_: function(empSheet) {
    let email = '';
    try {
      email = String(Session.getActiveUser().getEmail() || '').trim().toLowerCase();
    } catch (e) {
      email = '';
    }
    if (!email) return '';

    const { rows, headerRow, columns } = this.readDatabaseTable_(empSheet, CONFIG.SHEET_NAMES.EMPLOYEES,
      CONFIG.COLUMNS.EMPLOYEES, ['ID', 'EMAIL', 'STATUS']);
    for (let i = headerRow + 1; i < rows.length; i++) {
      const maNV = String(rows[i][columns.ID] || '').trim();
      const rowEmail = String(rows[i][columns.EMAIL] || '').trim().toLowerCase();
      const trangThai = String(rows[i][columns.STATUS] || '').trim();
      if (maNV && /^NV/i.test(maNV) && rowEmail === email && trangThai.toLowerCase().includes(CONFIG.EMPLOYEE_STATUS.ACTIVE.toLowerCase())) {
        return maNV;
      }
    }
    return '';
  },

  /**
   * Bóc tách Mã nhân viên (VD: 'NV0001 - Hoàng Thành' -> 'NV0001')
   * @private
   */
  extractStaffCode_: function(salesPersonStr) {
    if (!salesPersonStr) return '';
    const raw = String(salesPersonStr).trim();
    if (raw.indexOf(' - ') !== -1) {
      return raw.split(' - ')[0].trim();
    }
    return raw;
  },

  /**
   * Tải tệp đính kèm PO lên Google Drive (ID_STORAGES)
   * Tự động đổi tên chuẩn: PO_[Số PO]_[Tên KH].[ext]
   * @private
   */
  uploadPoAttachmentToDrive_: function(fileObj, soPO, customerName) {
    try {
      const base64Data = String(fileObj.base64 || '').replace(/^data:[^;]+;base64,/, '');
      if (!base64Data) return '';

      const decodedBytes = Utilities.base64Decode(base64Data);
      if (decodedBytes.length > CONFIG.MAX_FILE_SIZE_BYTES) {
        throw new Error('Tệp đính kèm của PO "' + soPO + '" vượt quá dung lượng tối đa 15MB!');
      }

      const origName = String(fileObj.fileName || fileObj.originalName || 'PO.pdf');
      const ext = origName.indexOf('.') !== -1 ? origName.split('.').pop().toLowerCase() : 'pdf';
      const cleanPO = this.removeVietnameseTones_(soPO).replace(/[^a-zA-Z0-9_-]/g, '_');
      const cleanCus = this.removeVietnameseTones_(customerName).replace(/[^a-zA-Z0-9_-]/g, '_');
      const standardFileName = 'PO_' + cleanPO + '_' + cleanCus + '.' + ext;

      const mimeType = fileObj.mimeType || this.guessMimeType_(ext);
      const blob = Utilities.newBlob(decodedBytes, mimeType, standardFileName);
      const folder = this.getStorageFolder_();
      const createdFile = folder.createFile(blob);

      return createdFile.getUrl();
    } catch (err) {
      console.warn('[Upload PO File Warning]: ' + err.message);
      return '';
    }
  },

  /**
   * Cập nhật thông tin sản phẩm cũ trong 02_SAN_PHAM nếu đơn hàng mới có bổ sung thông số
   * @private
   */
  updateExistingProductIfChanged_: function(prodSheet, matchedProd, item) {
    try {
      const { columns } = this.readDatabaseTable_(prodSheet, CONFIG.SHEET_NAMES.PRODUCTS,
        CONFIG.COLUMNS.PRODUCTS, ['ID', 'CODE_CUST', 'PRICE', 'MOLD_PRICE', 'FILM', 'PACKING']);
      const rIdx = matchedProd.rowIndex;
      if (item.codeSP && item.codeSP !== matchedProd.codeSP) {
        prodSheet.getRange(rIdx, columns.CODE_CUST + 1).setValue(item.codeSP);
        matchedProd.codeSP = item.codeSP;
      }
      if (Number(item.price) > 0 && Number(item.price) !== matchedProd.price) {
        prodSheet.getRange(rIdx, columns.PRICE + 1).setValue(Number(item.price));
        matchedProd.price = Number(item.price);
      }
      if (Number(item.giaKhuon) > 0 && Number(item.giaKhuon) !== matchedProd.giaKhuon) {
        prodSheet.getRange(rIdx, columns.MOLD_PRICE + 1).setValue(Number(item.giaKhuon));
        matchedProd.giaKhuon = Number(item.giaKhuon);
      }
      if (item.mang && item.mang !== matchedProd.mang) {
        prodSheet.getRange(rIdx, columns.FILM + 1).setValue(item.mang);
        matchedProd.mang = item.mang;
      }
      if (item.donggoi && item.donggoi !== matchedProd.donggoi) {
        prodSheet.getRange(rIdx, columns.PACKING + 1).setValue(item.donggoi);
        matchedProd.donggoi = item.donggoi;
      }
    } catch (e) {
      console.warn('[Update Product Master Warning]: ' + e.message);
    }
  },

  /**
   * Xóa trắng vùng dữ liệu A8:I trên sheet 'TAO DON' sau khi lưu đơn thành công
   * Giữ nguyên công thức, định dạng và Data Validation
   * @private
   */
  clearWorkspaceSheetAfterSave_: function(optSourceSpreadsheetId) {
    try {
      let ss = null;
      if (optSourceSpreadsheetId) {
        ss = SpreadsheetApp.openById(optSourceSpreadsheetId);
      } else {
        ss = SpreadsheetApp.getActiveSpreadsheet();
      }
      if (!ss) return;

      const wsSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.ORDER_WORKSPACE);
      if (!wsSheet) return;

      const maxRows = wsSheet.getMaxRows();
      if (maxRows >= CONFIG.WORKSPACE_CONFIG.DATA_START_ROW) {
        wsSheet.getRange(CONFIG.WORKSPACE_CONFIG.CLEAR_RANGE_A1).clearContent();
      }
    } catch (e) {
      console.warn('[Clear TAO DON Warning]: ' + e.message);
    }
  },

  /**
   * Tính toán các chỉ số thống kê tổng quan cho giao diện Tra cứu
   * @private
   */
  computeQueryMetrics_: function(headers, lines) {
    let totalOrders = 0;
    let totalLineItems = 0;
    let totalRevenue = 0;
    let totalRemainingQty = 0;

    if (lines && Array.isArray(lines)) {
      totalLineItems = lines.length;
      const uniqueOrderIds = new Set();
      lines.forEach(function(l) {
        if (l.maDH) uniqueOrderIds.add(l.maDH);
        totalRevenue += ((Number(l.slDat) || 0) * (Number(l.donGia) || 0));
        totalRemainingQty += (Number(l.conLai) || 0);
      });
      totalOrders = uniqueOrderIds.size;
    } else if (headers && Array.isArray(headers)) {
      totalOrders = headers.length;
      headers.forEach(function(h) {
        totalRevenue += (Number(h.tongGiaTri) || 0);
        const subItems = h.items || [];
        totalLineItems += subItems.length;
        subItems.forEach(function(it) {
          totalRemainingQty += (Number(it.conLai) || 0);
        });
      });
    }

    return {
      totalOrders: totalOrders,
      totalLineItems: totalLineItems,
      totalRevenue: totalRevenue,
      totalRemainingQty: totalRemainingQty
    };
  },

  /**
   * Chuẩn hóa chuỗi ngày về yyyy-MM-dd
   * @private
   */
  normalizeDateStr_: function(val) {
    if (!val) return '';
    if (Object.prototype.toString.call(val) === '[object Date]' && !isNaN(val.getTime())) {
      return Utilities.formatDate(val, CONFIG.TIMEZONE, 'yyyy-MM-dd');
    }
    const s = String(val).trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    const dmy = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$/);
    if (dmy) {
      return dmy[3] + '-' + this.padZero_(dmy[2], 2) + '-' + this.padZero_(dmy[1], 2);
    }
    const parsed = new Date(s);
    if (!isNaN(parsed.getTime())) {
      return Utilities.formatDate(parsed, CONFIG.TIMEZONE, 'yyyy-MM-dd');
    }
    return '';
  },

  /**
   * Định dạng giá trị ngày đọc từ Google Sheet về yyyy-MM-dd
   * @private
   */
  formatSheetDate_: function(val) {
    return this.normalizeDateStr_(val);
  },

  /**
   * Chuyển yyyy-MM-dd sang yymmdd (VD: '2026-11-04' -> '261104')
   * @private
   */
  dateStrToYYMMDD_: function(dateStr) {
    const norm = this.normalizeDateStr_(dateStr);
    if (norm && /^\d{4}-\d{2}-\d{2}$/.test(norm)) {
      return norm.substring(2, 4) + norm.substring(5, 7) + norm.substring(8, 10);
    }
    return Utilities.formatDate(new Date(), CONFIG.TIMEZONE, 'yyMMdd');
  },

  /**
   * Đệm số 0 ở đầu
   * @private
   */
  padZero_: function(num, size) {
    let s = String(num);
    while (s.length < size) s = '0' + s;
    return s;
  },

  /**
   * Chuyển đổi chuỗi số có dấu phân cách sang Number
   * @private
   */
  parseNumber_: function(val) {
    if (typeof val === 'number') return isNaN(val) ? 0 : val;
    if (!val) return 0;
    const cleaned = String(val).replace(/\./g, '').replace(/,/g, '.').replace(/[^\d.-]/g, '');
    const n = parseFloat(cleaned);
    return isNaN(n) ? 0 : n;
  },

  /**
   * Loại bỏ dấu tiếng Việt
   * @private
   */
  removeVietnameseTones_: function(str) {
    if (!str) return '';
    return String(str)
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/đ/g, 'd')
      .replace(/Đ/g, 'D');
  },

  /**
   * Xác định MimeType theo đuôi file
   * @private
   */
  guessMimeType_: function(ext) {
    const map = {
      'pdf': 'application/pdf',
      'png': 'image/png',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'doc': 'application/msword',
      'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'xls': 'application/vnd.ms-excel',
      'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    };
    return map[ext] || 'application/octet-stream';
  },

  /**
   * Đồng bộ danh mục Khách hàng, Sản phẩm & Nhân viên KD từ DB MASTER sang _CACHE_DANH_MUC
   * Cú pháp giữ nguyên chuẩn Object Literal bên trong OrderService
   */
  /**
 * NAPACO ENTERPRISE ERP - ORDER SERVICE
 * File: OrderService.gs
 * Target: Business Logic Tier
 */

  /**
   * Đồng bộ danh mục Khách hàng, Sản phẩm & Nhân viên KD từ DB MASTER sang _CACHE_DANH_MUC
   * Cú pháp giữ nguyên chuẩn Object Literal bên trong OrderService
   */
  /**
   * Đồng bộ danh mục Khách hàng, Sản phẩm & Nhân viên KD từ DB MASTER sang _CACHE_DANH_MUC
   * Cú pháp giữ nguyên chuẩn Object Literal bên trong OrderService
   */
  syncCacheCatalogFromDatabase: function(optTargetSpreadsheetId) {
    const tStart = Date.now();
    const isDebug = typeof CONFIG !== 'undefined' && Boolean(CONFIG.DEBUG_MODE);

    if (isDebug) console.log("⏱️ [BACKEND-SYNC] Bắt đầu đồng bộ danh mục chuẩn...");

    const targetSS = optTargetSpreadsheetId 
      ? SpreadsheetApp.openById(optTargetSpreadsheetId) 
      : SpreadsheetApp.getActiveSpreadsheet();
    if (!targetSS) throw new Error("Không xác định được file Client đích!");

    const masterSS = this.getMasterSpreadsheet_();

    // 1. Tạo bản đồ: Ma_KH -> Tên Khách Hàng
    const custSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.CUSTOMERS);
    const customerTable = this.readDatabaseTable_(custSheet, CONFIG.SHEET_NAMES.CUSTOMERS,
      CONFIG.COLUMNS.CUSTOMERS, ['ID', 'NAME']);
    const { rows: custData, columns: custCols } = customerTable;
    const khMap = {};
    const allCustomerNames = [];
    for (let i = customerTable.headerRow + 1; i < custData.length; i++) {
      const ma = String(custData[i][custCols.ID] || '').trim();
      const ten = String(custData[i][custCols.NAME] || '').trim();
      if (ma && ten) {
        khMap[ma] = ten;
        if (!allCustomerNames.includes(ten)) allCustomerNames.push(ten);
      }
    }

    // 2. Đọc bảng 07.NhanVien -> Nhận diện động dòng tiêu đề & cột
    const empSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.EMPLOYEES);
    const empData = empSheet ? empSheet.getDataRange().getValues() : [];
    const salesStaffRows = [];

    const employeeHeaders = CONFIG.COLUMNS.EMPLOYEES;
    const employeeAliases = CONFIG.EMPLOYEE_HEADER_ALIASES;
    const matchesEmployeeHeader = (key, label) => employeeHeaders[key].toLowerCase() === label ||
      employeeAliases[key].includes(label);
    let empHeaderRowIdx = -1;
    let colMaNV = -1, colTenNV = -1, colPhongBan = -1, colTrangThai = -1;

    for (let r = 0; r < Math.min(empData.length, 10); r++) {
      for (let c = 0; c < empData[r].length; c++) {
        const val = String(empData[r][c] || '').trim().toLowerCase();
        if (matchesEmployeeHeader('ID', val)) {
          empHeaderRowIdx = r;
          break;
        }
      }
      if (empHeaderRowIdx !== -1) break;
    }

    if (empHeaderRowIdx !== -1) {
      const empHeaders = empData[empHeaderRowIdx];
      for (let c = 0; c < empHeaders.length; c++) {
        const h = String(empHeaders[c] || '').trim().toLowerCase();
        if (matchesEmployeeHeader('ID', h)) colMaNV = c;
        if (matchesEmployeeHeader('NAME', h)) colTenNV = c;
        if (matchesEmployeeHeader('DEPARTMENT', h)) colPhongBan = c;
        if (matchesEmployeeHeader('STATUS', h)) colTrangThai = c;
      }

      for (let k = empHeaderRowIdx + 1; k < empData.length; k++) {
        const row = empData[k];
        const maNV = colMaNV !== -1 ? String(row[colMaNV] || '').trim() : '';
        const tenNV = colTenNV !== -1 ? String(row[colTenNV] || '').trim() : '';
        const pb = colPhongBan !== -1 ? String(row[colPhongBan] || '').trim().toLowerCase() : '';
        const tt = colTrangThai !== -1 ? String(row[colTrangThai] || '').trim().toLowerCase() : '';

        // Thay thế đoạn:
        // if (maNV.toUpperCase().startsWith('NV') && tt.includes('hoạt động') && pb.includes('kinh doanh'))
        // Thành:
        const isAct = tt.includes(CONFIG.EMPLOYEE_STATUS.ACTIVE.toLowerCase());
        const isSal = pb.includes(CONFIG.DEPARTMENTS.SALES.toLowerCase());
        if (maNV.toUpperCase().startsWith('NV') && isAct && isSal) {
          salesStaffRows.push([`${maNV} - ${tenNV}`]);
        }
      }
    }

    if (isDebug) {
      console.log("⏱️ [DEBUG_CHECK] 1. Dòng tiêu đề Nhân viên phát hiện tại Row index:", empHeaderRowIdx);
      console.log("⏱️ [DEBUG_CHECK] 2. Lọc được " + salesStaffRows.length + " nhân viên KD đang hoạt động: " + JSON.stringify(salesStaffRows));
    }

    // 3. Đọc Sản Phẩm và ghép ĐÚNG Khách Hàng sở hữu qua customer_id
    const prodSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.PRODUCTS);
    const productTable = this.readDatabaseTable_(prodSheet, CONFIG.SHEET_NAMES.PRODUCTS,
      CONFIG.COLUMNS.PRODUCTS, ['ID', 'NAME', 'CUSTOMER_ID', 'CODE_CUST', 'UNIT', 'PRICE']);
    const { rows: prodData, columns: prodCols } = productTable;
    const cacheRows = [];
    for (let j = productTable.headerRow + 1; j < prodData.length; j++) {
      const tenSP = String(prodData[j][prodCols.NAME] || '').trim();
      if (!tenSP) continue;

      const cusId = String(prodData[j][prodCols.CUSTOMER_ID] || '').trim();
      const tenKH = khMap[cusId] || cusId;

      cacheRows.push([
        tenSP,
        tenKH,
        String(prodData[j][prodCols.CODE_CUST] || '').trim(),
        String(prodData[j][prodCols.UNIT] || 'Cái').trim() || 'Cái',
        Number(prodData[j][prodCols.PRICE]) || 0
      ]);
    }

    // 4. Ghi đè vào sheet _CACHE_DANH_MUC
    let cacheSheet = targetSS.getSheetByName(CONFIG.SHEET_NAMES.CACHE_CATALOG || '_CACHE_DANH_MUC');
    if (!cacheSheet) cacheSheet = targetSS.insertSheet(CONFIG.SHEET_NAMES.CACHE_CATALOG || '_CACHE_DANH_MUC');
    cacheSheet.clearContents();

    const headers = [['Tên Sản Phẩm', 'Khách Hàng', 'Code SP', 'Đơn Vị', 'Đơn Giá Chuẩn (₫)']];
    cacheSheet.getRange(1, 1, 1, 5).setValues(headers).setFontWeight('bold');
    if (cacheRows.length > 0) {
      cacheSheet.getRange(2, 1, cacheRows.length, 5).setValues(cacheRows);
    }

    // Ghi Danh sách NV KD vào Cột G (Cột 7)
    cacheSheet.getRange(1, 7).setValue('Danh Sách NV KD').setFontWeight('bold');
    if (salesStaffRows.length > 0) {
      cacheSheet.getRange(2, 7, salesStaffRows.length, 1).setValues(salesStaffRows);
      if (isDebug) {
        console.log("⏱️ [DEBUG_CHECK] 3. Đã ghi thành công " + salesStaffRows.length + " nhân viên vào Cột G của sheet _CACHE_DANH_MUC.");
      }
    }

    // Cột K (11): Danh sách tất cả khách hàng (Dropdown cột Khách Hàng)
    cacheSheet.getRange(1, 11).setValue('Danh Sách Tất Cả KH').setFontWeight('bold');
    if (allCustomerNames.length > 0) {
      cacheSheet.getRange(2, 11, allCustomerNames.length, 1).setValues(allCustomerNames.map(c => [c]));
    }

    // 5. Gán Data Validation Dropdown cho sheet TAO DON theo tên cột động từ CONFIG
    const wsSheet = targetSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_WORKSPACE || 'TAO DON');
    if (wsSheet) {
      const headerRow = wsSheet.getRange(CONFIG.FORM_COLUMNS.HEADER_ROW, 1, 1, wsSheet.getLastColumn()).getValues()[0];
      const findCol = (aliases) => {
        for (let c = 0; c < headerRow.length; c++) {
          const text = String(headerRow[c] || '').trim().toLowerCase();
          if (aliases.some(a => text.includes(a.toLowerCase()))) return c + 1;
        }
        return -1;
      };

      const colKh = findCol(CONFIG.FORM_COLUMNS.ALIASES.CUSTOMER);
      const colSp = findCol(CONFIG.FORM_COLUMNS.ALIASES.PRODUCT);
      const startRow = CONFIG.FORM_COLUMNS.DATA_START_ROW;
      const numRows = 100;

      if (colKh > 0 && allCustomerNames.length > 0) {
        wsSheet.getRange(startRow, colKh, numRows, 1).setDataValidation(
          SpreadsheetApp.newDataValidation().requireValueInRange(cacheSheet.getRange(2, 11, allCustomerNames.length, 1), true).setAllowInvalid(true).build()
        );
      }
      if (colSp > 0 && cacheRows.length > 0) {
        wsSheet.getRange(startRow, colSp, numRows, 1).setDataValidation(
          SpreadsheetApp.newDataValidation().requireValueInRange(cacheSheet.getRange(2, 1, cacheRows.length, 1), true).setAllowInvalid(true).build()
        );
      }
    }

    SpreadsheetApp.flush();
    if (isDebug) console.log("⏱️ [BACKEND-SYNC] Hoàn tất sau " + (Date.now() - tStart) + " ms.");

    return {
      success: true,
      message: `Đã đồng bộ chính xác ${allCustomerNames.length} khách hàng, ${cacheRows.length} sản phẩm và ${salesStaffRows.length} nhân viên KD!`
    };
  },

  /**
   * [MỚI - SPEC-ERP-LINEITEM-202611-01] Đọc bảng 05.Cong_Cu và tạo map Khuôn định hình theo SP_ID
   * @private
   */
  getMoldsMap_: function(masterSS = this.getMasterSpreadsheet_()) {
    try {
      const sheetName = (CONFIG.SHEET_NAMES && CONFIG.SHEET_NAMES.TOOLS) ? CONFIG.SHEET_NAMES.TOOLS : '05.Cong_Cu';
      const toolSheet = masterSS.getSheetByName(sheetName);
      if (!toolSheet) return {};

      const data = toolSheet.getDataRange().getValues();
      if (data.length <= 1) return {};

      const headers = data[0].map(h => String(h || '').trim().toLowerCase());
      const colSpId = headers.indexOf(CONFIG.COLUMNS.TOOLS.SP_ID.toLowerCase());
      const colType = headers.indexOf(CONFIG.COLUMNS.TOOLS.TOOL_TYPE.toLowerCase());
      const colMold = headers.indexOf(CONFIG.COLUMNS.TOOLS.MOLD_CODE.toLowerCase());
      const colStatus = headers.indexOf(CONFIG.COLUMNS.TOOLS.STATUS.toLowerCase());

      if (colSpId === -1 || colMold === -1) return {};

      const moldMap = {};
      for (let i = 1; i < data.length; i++) {
        const row = data[i];
        const spId = String(row[colSpId] || '').trim();
        const typeRaw = colType !== -1 ? String(row[colType] || '').trim().toLowerCase() : '';
        const moldCode = String(row[colMold] || '').trim();
        const statusRaw = colStatus !== -1 ? String(row[colStatus] || '').trim() : '';

        if (!spId || !moldCode) continue;
        if (!moldMap[spId]) {
          moldMap[spId] = { dinhHinh: [], dao: [] };
        }

        // [LOẠI BỎ HARDCODE] Phân loại khuôn định hình và khuôn dao qua CONFIG.MOLD_TYPES
        const isForming = typeRaw.includes(CONFIG.MOLD_TYPES.FORMING.toLowerCase()) || typeRaw.includes('dinhhinh') || typeRaw.includes('định hình') || !typeRaw;
        const isCutting = typeRaw.includes(CONFIG.MOLD_TYPES.CUTTING.toLowerCase()) || typeRaw.includes('dao');

        if (isForming) {
          moldMap[spId].dinhHinh.push({ code: moldCode, status: statusRaw });
        } else if (isCutting) {
          moldMap[spId].dao.push({ code: moldCode, status: statusRaw });
        }
      }
      return moldMap;
    } catch (e) {
      console.warn('[OrderService.getMoldsMap_] Cảnh báo đọc khuôn:', e.message);
      return {};
    }
  },

  /**
   * [MỚI - SPEC-ERP-LINEITEM-202611-01] Chỉnh sửa hàng loạt (Bulk Edit) với LockService và Batch Read/Write
   * @param {Object} payload { targetIds: string[], fieldsToUpdate: Object }
   */
  updateOrderLineItemsBulk: function(payload) {
    /* [MỚI - VẤN ĐỀ 5] Hỗ trợ đồng thời 2 cấu trúc payload: mảng itemsToUpdate (riêng từng SP) hoặc targetIds chung */
    const updateMap = Object.create(null); // idChiTiet -> fieldsToUpdate
    if (payload && Array.isArray(payload.itemsToUpdate) && payload.itemsToUpdate.length > 0) {
      payload.itemsToUpdate.forEach(item => {
        const id = String((item && item.idChiTiet) || '').trim();
        if (id) updateMap[id] = item.fields || {};
      });
    } else if (payload && Array.isArray(payload.targetIds) && payload.targetIds.length > 0) {
      const commonFields = payload.fieldsToUpdate || {};
      payload.targetIds.forEach(id => {
        const targetId = String(id || '').trim();
        if (targetId) updateMap[targetId] = commonFields;
      });
    } else {
      return { success: false, message: 'Danh sách dòng mặt hàng cần cập nhật không hợp lệ.' };
    }

    const targetIds = Object.keys(updateMap);
    if (targetIds.length === 0) {
      return { success: false, message: 'Không có dữ liệu mặt hàng nào được chọn.' };
    }

    // Khóa hệ thống trước khi kiểm tra quyền và ghi dữ liệu.
    const lock = LockService.getScriptLock();
    let hasLock = false;
    try {
      hasLock = lock.tryLock(30000);
    } catch (e) {
      hasLock = false;
    }

    if (!hasLock) {
      return { success: false, message: 'Hệ thống đang bận xử lý giao dịch khác. Vui lòng thử lại sau 30 giây.' };
    }

    try {
      const masterSS = this.getMasterSpreadsheet_();
      requirePermission_(readUserPermissions_(masterSS), CONFIG.PERMISSIONS.ORDER_EDIT);
      const catalog = this.readOrderStaff_(masterSS);
      const operSS = this.getOperationSpreadsheet_();

      const detailSheet = operSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);
      const orderSheet = operSS.getSheetByName(CONFIG.SHEET_NAMES.ORDERS);
      const prodSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.PRODUCTS);

      if (!detailSheet || !orderSheet || !prodSheet) {
        throw new Error('Không tìm thấy các sheet cơ sở dữ liệu cần cập nhật.');
      }

      const normalizeHeader = value => String(value || '').trim().toLowerCase();
      const requireColumn = (index, sheet, name) => {
        if (index < 0) throw new Error('Thiếu cột "' + name + '" trong ' + sheet.getName() + '.');
      };
      const detailColumns = CONFIG.COLUMNS.ORDER_DETAILS;
      const headerColumns = CONFIG.COLUMNS.ORDERS;
      const productColumns = CONFIG.COLUMNS.PRODUCTS;

      // Đọc toàn bộ bảng 02.ChiTietDH (Batch Read)
      const detailData = detailSheet.getDataRange().getValues();
      const dHeaders = detailData[0].map(normalizeHeader);
      
      const colIdChiTiet = dHeaders.indexOf(normalizeHeader(detailColumns.ID));
      const colIdDH = dHeaders.indexOf(normalizeHeader(detailColumns.ORDER_ID));
      const colMaSP = dHeaders.indexOf(normalizeHeader(detailColumns.PRODUCT_ID));
      const colSlDat = dHeaders.indexOf(normalizeHeader(detailColumns.QTY_ORDER));
      const colDonGia = dHeaders.indexOf(normalizeHeader(detailColumns.PRICE));
      const colDaGiao = dHeaders.indexOf(normalizeHeader(detailColumns.QTY_DELIVERED));
      const colConLai = dHeaders.indexOf(normalizeHeader(detailColumns.QTY_REMAINING));
      const colNgayGiao = dHeaders.indexOf(normalizeHeader(detailColumns.DELIVERY_DATE));

      const colStaff = dHeaders.indexOf(normalizeHeader(detailColumns.STAFF_ID));
      const colStatus = dHeaders.indexOf(normalizeHeader(detailColumns.STATUS));
      const detailFields = {
        soLuongDat: [[colSlDat, detailColumns.QTY_ORDER], [colDaGiao, detailColumns.QTY_DELIVERED],
          [colConLai, detailColumns.QTY_REMAINING]],
        donGia: [[colDonGia, detailColumns.PRICE]],
        ngayGiao: [[colNgayGiao, detailColumns.DELIVERY_DATE]],
        maNV: [[colStaff, detailColumns.STAFF_ID]],
        trangThai: [[colStatus, detailColumns.STATUS]]
      };
      const productFields = ['codeSP', 'mang', 'giaKhuon', 'dvt'];
      const hasValue = value => value !== undefined && value !== null && String(value).trim() !== '';
      requireColumn(colIdChiTiet, detailSheet, detailColumns.ID);
      targetIds.forEach(id => {
        const fields = updateMap[id];
        const keys = Object.keys(fields).filter(key => hasValue(fields[key]) ||
          (key === 'codeSP' && fields[key] === ''));
        const recognized = keys.filter(key => Object.prototype.hasOwnProperty.call(detailFields, key) ||
          key === 'ngayDat' || productFields.includes(key));
        if (recognized.length === 0) throw new Error('Không có giá trị cập nhật cho dòng ' + id + '.');
        recognized.forEach(key => {
          if (detailFields[key]) {
            detailFields[key].forEach(([index, name]) => requireColumn(index, detailSheet, name));
          }
          if (key === 'ngayDat') requireColumn(colIdDH, detailSheet, detailColumns.ORDER_ID);
          if (productFields.includes(key)) requireColumn(colMaSP, detailSheet, detailColumns.PRODUCT_ID);
        });
      });

      const operationWrites = [];
      const masterWrites = [];
      const detailSheetId = detailSheet.getSheetId();
      const remainingIds = new Set(targetIds);
      const affectedOrdersMap = Object.create(null); // maDH -> ngayDat mới
      const affectedProductsMap = Object.create(null); // maSP -> { mang, giaKhuon, donvi }
      let updatedCount = 0;
      const changes = { lines: [], products: [], orders: [] };
      const orderChanges = new Map();
      const colQtyRun = dHeaders.indexOf(normalizeHeader(detailColumns.QTY_RUN));
      const colZone = dHeaders.indexOf(normalizeHeader(detailColumns.KANBAN_ZONE));
      const colPriority = dHeaders.indexOf(normalizeHeader(detailColumns.PRIORITY_ORDER));

      // 3. CẬP NHẬT TRONG BỘ NHỚ BẢNG 02.ChiTietDH
      for (let r = 1; r < detailData.length; r++) {
        const rowId = String(detailData[r][colIdChiTiet] || '').trim();
        if (remainingIds.delete(rowId)) {
          const fields = updateMap[rowId] || {};
          updatedCount++;

          const currentDH = String(detailData[r][colIdDH] || '').trim();
          const currentSP = String(detailData[r][colMaSP] || '').trim();

          if (hasValue(fields.ngayDat) && !currentDH) throw new Error('Thiếu mã đơn hàng ở dòng ' + rowId + '.');
          if (!currentSP && productFields.some(key => hasValue(fields[key]) ||
              (key === 'codeSP' && fields[key] === ''))) {
            throw new Error('Thiếu mã sản phẩm ở dòng ' + rowId + '.');
          }
          if (currentDH && fields.ngayDat) {
            affectedOrdersMap[currentDH] = fields.ngayDat;
          }
          if (currentSP) {
        if (!affectedProductsMap[currentSP]) affectedProductsMap[currentSP] = {};
        if (fields.codeSP !== undefined && fields.codeSP !== null) affectedProductsMap[currentSP].codeSP = String(fields.codeSP).trim();
        if (fields.mang !== undefined && fields.mang !== '') affectedProductsMap[currentSP].mang = fields.mang;
        if (fields.giaKhuon !== undefined && fields.giaKhuon !== '') affectedProductsMap[currentSP].giaKhuon = fields.giaKhuon;
        if (fields.dvt !== undefined && fields.dvt !== '') affectedProductsMap[currentSP].donvi = fields.dvt;
        /* [MỚI - Ý 1] Cập nhật luôn Đơn giá mới vào Master 01_02_SAN_PHAM */
        if (fields.donGia !== undefined && fields.donGia !== null && fields.donGia !== '') {
          affectedProductsMap[currentSP].dongia = Number(fields.donGia) || 0;
        }
      }

          // Cập nhật Số lượng đặt & Tính lại SL_Con_Lai
          if (fields.soLuongDat !== undefined && fields.soLuongDat !== null && fields.soLuongDat !== '') {
            const newSlDat = Number(fields.soLuongDat) || 0;
            this.queueCellChange_(operationWrites, detailSheetId, r, colSlDat, detailData[r], newSlDat);
            const currentDaGiao = Number(detailData[r][colDaGiao]) || 0;
            this.queueCellChange_(operationWrites, detailSheetId, r, colConLai, detailData[r], Math.max(0, newSlDat - currentDaGiao));
          }

          // Cập nhật Đơn giá
          if (fields.donGia !== undefined && fields.donGia !== null && fields.donGia !== '') {
            this.queueCellChange_(operationWrites, detailSheetId, r, colDonGia, detailData[r], Number(fields.donGia) || 0);
          }

          // Cập nhật Ngày giao
          if (fields.ngayGiao !== undefined && fields.ngayGiao !== null && fields.ngayGiao !== '') {
            this.queueCellChange_(operationWrites, detailSheetId, r, colNgayGiao, detailData[r], this.formatSheetDate_(fields.ngayGiao));
          }

          /* [MỚI - Ý 3] Cập nhật Sales (Mã NV) */
          if (colStaff !== -1 && fields.maNV !== undefined && fields.maNV !== null && fields.maNV !== '') {
            this.queueCellChange_(operationWrites, detailSheetId, r, colStaff, detailData[r], String(fields.maNV).trim());
          }

          /* [MỚI - Ý 3] Cập nhật Trạng Thái dòng mặt hàng */
          if (colStatus !== -1 && fields.trangThai !== undefined && fields.trangThai !== null && fields.trangThai !== '') {
            this.queueCellChange_(operationWrites, detailSheetId, r, colStatus, detailData[r], String(fields.trangThai).trim());
            /* [MỚI - SPEC-LINE-DND-01] Quy tắc Reset Blank khi Hoàn thành */
            const newStLow = String(fields.trangThai).trim().toLowerCase();
            if (newStLow.includes('hoàn thành') || newStLow.includes('xong') || newStLow.includes('kết thúc')) {
              if (colZone !== -1) this.queueCellChange_(operationWrites, detailSheetId, r, colZone, detailData[r], '');
              if (colPriority !== -1) this.queueCellChange_(operationWrites, detailSheetId, r, colPriority, detailData[r], '');
            }
          }
          const row = detailData[r];
          const change = { idChiTiet: rowId };
          if (hasValue(fields.soLuongDat)) {
            change.slDat = row[colSlDat];
            change.conLai = row[colConLai];
          }
          if (hasValue(fields.donGia)) change.donGia = row[colDonGia];
          if (hasValue(fields.ngayGiao)) change.ngayGiao = row[colNgayGiao];
          if (hasValue(fields.maNV)) {
            change.maNV = row[colStaff];
            change.tenNV = this.resolveStaffName_(change.maNV, catalog.employeeByIdMap, catalog.salesStaffList);
          }
          if (hasValue(fields.trangThai)) {
            change.trangThai = row[colStatus];
            change.kanbanReadOnly = this.isClosedKanbanStatus_(change.trangThai);
            change.kanbanZone = colZone >= 0 ? String(row[colZone] || '').trim() : '';
            const rank = colPriority >= 0 ? row[colPriority] : '';
            change.kanbanPriority = rank !== '' && Number.isFinite(Number(rank)) ? parseInt(rank, 10) : 999999;
          }
          if (Object.keys(change).length > 1) changes.lines.push(change);
          if (currentDH && ['soLuongDat', 'maNV', 'trangThai', 'ngayDat'].some(key => hasValue(fields[key]))) {
            orderChanges.set(currentDH, { maDH: currentDH });
          }
        }
      }

      if (remainingIds.size > 0) {
        throw new Error('Không tìm thấy dòng mặt hàng: ' + Array.from(remainingIds).join(', '));
      }

      // 4. CẬP NHẬT HEADER BẢNG 01.DonHang
      const affectedDHKeys = Object.keys(affectedOrdersMap);
      if (affectedDHKeys.length > 0) {
        const { rows: orderData, headerRow, columns } = this.readDatabaseTable_(
          orderSheet, orderSheet.getName(), headerColumns, ['ID', 'ORDER_DATE']);
        const colMaDH = columns.ID;
        const colNgayDat = columns.ORDER_DATE;
        const orderSheetId = orderSheet.getSheetId();

        requireColumn(colMaDH, orderSheet, headerColumns.ID);
        requireColumn(colNgayDat, orderSheet, headerColumns.ORDER_DATE);
        const missingOrders = new Set(affectedDHKeys);
        for (let ro = headerRow + 1; ro < orderData.length; ro++) {
          const oId = String(orderData[ro][colMaDH] || '').trim();
          if (affectedOrdersMap[oId]) {
            this.queueCellChange_(operationWrites, orderSheetId, ro, colNgayDat, orderData[ro],
              this.formatSheetDate_(affectedOrdersMap[oId]));
            orderChanges.get(oId).ngayDat = orderData[ro][colNgayDat];
            missingOrders.delete(oId);
          }
        }
        if (missingOrders.size) {
          throw new Error('Không tìm thấy đơn hàng: ' + Array.from(missingOrders).join(', '));
        }
      }

      // 5. CẬP NHẬT MASTER 01_02_SAN_PHAM (Màng, Giá khuôn, Đơn vị tính)
      const affectedSPKeys = Object.keys(affectedProductsMap)
        .filter(id => Object.keys(affectedProductsMap[id]).length > 0);
      if (affectedSPKeys.length > 0) {
        const { rows: prodData, headerRow, columns } = this.readDatabaseTable_(
          prodSheet, prodSheet.getName(), productColumns, []);
        const colSpId = columns.ID;
        const colCodeCust = columns.CODE_CUST;
        const colFilm = columns.FILM;
        const colMoldPrice = columns.MOLD_PRICE;
        const colUnit = columns.UNIT;
        const colPrice = columns.PRICE;
        const productSheetId = prodSheet.getSheetId();

        const requiredProductFields = {
          codeSP: [colCodeCust, productColumns.CODE_CUST],
          mang: [colFilm, productColumns.FILM],
          giaKhuon: [colMoldPrice, productColumns.MOLD_PRICE],
          donvi: [colUnit, productColumns.UNIT]
        };
        const requiredProductIds = new Set(affectedSPKeys.filter(id =>
          Object.keys(affectedProductsMap[id]).some(key => key !== 'dongia')
        ));
        if (requiredProductIds.size) requireColumn(colSpId, prodSheet, productColumns.ID);
        requiredProductIds.forEach(id => {
          Object.keys(affectedProductsMap[id]).forEach(key => {
            if (requiredProductFields[key]) {
              const [index, name] = requiredProductFields[key];
              requireColumn(index, prodSheet, name);
            }
          });
        });

        if (colSpId !== -1) {
          for (let rp = headerRow + 1; rp < prodData.length; rp++) {
            const pId = String(prodData[rp][colSpId] || '').trim();
            if (affectedProductsMap[pId]) {
              const spUpdates = affectedProductsMap[pId];
              requiredProductIds.delete(pId);
              const change = { maSP: pId };
              if (spUpdates.codeSP !== undefined && colCodeCust !== -1) {
                this.queueCellChange_(masterWrites, productSheetId, rp, colCodeCust, prodData[rp], spUpdates.codeSP);
                change.codeSP = prodData[rp][colCodeCust];
              }
              if (spUpdates.mang !== undefined && colFilm !== -1) {
                this.queueCellChange_(masterWrites, productSheetId, rp, colFilm, prodData[rp], String(spUpdates.mang).trim());
                change.mang = prodData[rp][colFilm];
              }
              if (spUpdates.giaKhuon !== undefined && colMoldPrice !== -1) {
                this.queueCellChange_(masterWrites, productSheetId, rp, colMoldPrice, prodData[rp], Number(spUpdates.giaKhuon) || 0);
                change.giaKhuon = prodData[rp][colMoldPrice];
              }
              if (spUpdates.donvi !== undefined && colUnit !== -1) {
                this.queueCellChange_(masterWrites, productSheetId, rp, colUnit, prodData[rp], String(spUpdates.donvi).trim());
                change.dvt = prodData[rp][colUnit];
              }
              /* [MỚI - Ý 1] Ghi đè đơn giá mới vào bảng 01_02_SAN_PHAM */
              if (spUpdates.dongia !== undefined && colPrice !== -1) {
                this.queueCellChange_(masterWrites, productSheetId, rp, colPrice, prodData[rp], Number(spUpdates.dongia) || 0);
              }
              if (Object.keys(change).length > 1) changes.products.push(change);
            }
          }
          if (requiredProductIds.size) {
            throw new Error('Không tìm thấy sản phẩm: ' + Array.from(requiredProductIds).join(', '));
          }
        }
      }

      // Dùng dữ liệu đã đọc trong lượt lưu để tính tiến độ toàn PO.
      const orderTotals = new Map();
      if (orderChanges.size > 0) {
        for (let r = 1; r < detailData.length; r++) {
          const row = detailData[r];
          const maDH = String(row[colIdDH] || '').trim();
          if (!orderChanges.has(maDH) || !String(row[colIdChiTiet] || '').trim()) continue;
          if (!orderTotals.has(maDH)) {
            orderTotals.set(maDH, { ordered: 0, delivered: 0, remaining: 0, running: false, sales: '' });
          }
          const totals = orderTotals.get(maDH);
          const ordered = Number(row[colSlDat]) || 0;
          const delivered = Number(row[colDaGiao]) || 0;
          const remaining = row[colConLai];
          totals.ordered += ordered;
          totals.delivered += delivered;
          totals.remaining += hasValue(remaining) ? Number(remaining) || 0 : Math.max(0, ordered - delivered);
          totals.running = totals.running || Number(row[colQtyRun]) > 0 ||
            String(row[colStatus] || '').toLowerCase().includes('đang');
          if (!totals.sales && row[colStaff]) {
            const name = this.resolveStaffName_(row[colStaff], catalog.employeeByIdMap, catalog.salesStaffList);
            if (name !== '---') totals.sales = name;
          }
        }
      }
      orderChanges.forEach((change, id) => {
        const totals = orderTotals.get(id);
        if (totals) {
          change.progressPercent = totals.ordered > 0
            ? Math.min(100, Math.round(totals.delivered / totals.ordered * 100)) : 0;
          change.tienDo = change.progressPercent + '% (' + totals.delivered.toLocaleString('vi-VN') +
            '/' + totals.ordered.toLocaleString('vi-VN') + ')';
          change.trangThai = totals.remaining <= 0 && totals.ordered > 0 ? 'Hoàn tất'
            : totals.delivered > 0 || totals.running ? 'Đang sản xuất' : 'Chờ sản xuất';
          change.salesPerson = totals.sales;
        }
        changes.orders.push(change);
      });

      if (operationWrites.length) Sheets.Spreadsheets.batchUpdate({ requests: operationWrites }, operSS.getId());
      if (masterWrites.length) Sheets.Spreadsheets.batchUpdate({ requests: masterWrites }, masterSS.getId());
      return {
        success: true,
        updatedCount: updatedCount,
        changes: changes,
        message: 'Đã lưu thành công thông tin cho ' + updatedCount + ' dòng mặt hàng!'
      };

    } catch (err) {
      console.error('[OrderService.updateOrderLineItemsBulk] Lỗi:', err);
      return {
        success: false,
        message: 'Lỗi máy chủ trong quá trình cập nhật: ' + (err.message || String(err))
      };
    } finally {
      lock.releaseLock();
    }
  },

  /* [MỚI - Ý 2] Chuẩn hóa triệt để tra cứu tên nhân viên */
  resolveStaffName_: function(rawStaff, employeeByIdMap, allEmployeesList) {
    if (!rawStaff) return '---';
    const s = String(rawStaff).trim();
    if (!s || s === '---') return '---';

    // 1. Nếu chuỗi đã có sẵn tên dạng "NV0001 - Hoàng Thành" hoặc "NV-KD01 - Hoàng Thành"
    if (s.indexOf(' - ') !== -1) {
      const parts = s.split(' - ');
      if (parts[1] && parts[1].trim()) return parts[1].trim();
    }

    const sClean = s.toUpperCase().replace(/\s+/g, '');

    // 2. Tìm trực tiếp trong employeeByIdMap (case-insensitive & whitespace-stripped)
    if (employeeByIdMap) {
      if (employeeByIdMap[s]) return employeeByIdMap[s].hoTen;
      if (employeeByIdMap[sClean]) return employeeByIdMap[sClean].hoTen;

      // Quét toàn bộ keys của map để tránh lệch định dạng
      const mapKeys = Object.keys(employeeByIdMap);
      for (let k = 0; k < mapKeys.length; k++) {
        const key = mapKeys[k];
        if (key.toUpperCase().replace(/\s+/g, '') === sClean) {
          return employeeByIdMap[key].hoTen;
        }
      }
    }

    // 3. Chuẩn hóa mã số (ví dụ: NV-KD01 -> 1 -> NV0001)
    const matchNum = s.match(/\d+/);
    if (matchNum) {
      const numVal = parseInt(matchNum[0], 10);
      const targetStaffId = 'NV' + String(numVal).padStart(4, '0');
      if (employeeByIdMap && employeeByIdMap[targetStaffId]) {
        return employeeByIdMap[targetStaffId].hoTen;
      }
      if (allEmployeesList && Array.isArray(allEmployeesList)) {
        const found = allEmployeesList.find(e => {
          const eClean = String(e.maNV || '').toUpperCase().replace(/\s+/g, '');
          return eClean === targetStaffId || eClean.endsWith(String(numVal));
        });
        if (found && found.hoTen) return found.hoTen;
      }
    }

    return s;
  },

    /**
   * [MỚI - SPEC-LINE-DND-01] API lấy dữ liệu chi tiết đơn hàng phân theo 3 vùng Kanban dọc
   */
  getLineKanbanData: function() {
    const opSS = createReadBook_(getSecureEnv_().ID_OPERATION, [CONFIG.SHEET_NAMES.ORDER_DETAILS]);
    const detailSheet = opSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);
    if (!detailSheet) throw new Error('Không tìm thấy sheet: ' + CONFIG.SHEET_NAMES.ORDER_DETAILS);

    const catalog = this.getCatalogAndAuthData();
    return this.buildLineKanbanData_(detailSheet.getDataRange().getValues(), catalog);
  },

  isClosedKanbanStatus_: function(status) {
    const text = String(status || '').trim().toLowerCase();
    return ['hoàn thành', 'xong', 'kết thúc', 'hủy'].some(word => text.includes(word));
  },

  buildLineKanbanData_: function(detailRows, catalog, matchedLines) {
    if (detailRows.length <= 1) {
      return { success: true, data: { DANG_SAN_XUAT: [], UU_TIEN: [], CHO_SAN_XUAT: [] } };
    }

    const dHdrs = detailRows[0].map(h => String(h || '').trim().toLowerCase());
    const colId = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.ID.toLowerCase());
    const colOrderId = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.ORDER_ID.toLowerCase());
    const colSpId = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.PRODUCT_ID.toLowerCase());
    const colQty = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.QTY_ORDER.toLowerCase());
    const colDate = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.DELIVERY_DATE.toLowerCase());
    const colStatus = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.STATUS.toLowerCase());
    let colZone = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE.toLowerCase());
    let colPriority = dHdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER.toLowerCase());

    const result = {
      DANG_SAN_XUAT: [],
      UU_TIEN: [],
      CHO_SAN_XUAT: []
    };

    for (let r = 1; r < detailRows.length; r++) {
      const row = detailRows[r];
      const idChiTiet = colId !== -1 ? String(row[colId] || '').trim() : '';
      if (!idChiTiet || (matchedLines && !matchedLines.has(idChiTiet))) continue;

      const status = colStatus !== -1 ? String(row[colStatus] || '').trim() : '';
      const readOnly = this.isClosedKanbanStatus_(status);
      if (readOnly && !matchedLines) continue;
      const line = matchedLines && matchedLines.get(idChiTiet);

      let zone = (colZone !== -1 && row[colZone]) ? String(row[colZone]).trim() : '';
      if (!zone || !Object.prototype.hasOwnProperty.call(result, zone)) {
        zone = CONFIG.KANBAN_ZONES.PENDING; // Mặc định CHO_SAN_XUAT
      }

      const priority = (colPriority !== -1 && row[colPriority] !== '' && !isNaN(row[colPriority])) ? parseInt(row[colPriority], 10) : 999999;
      const spId = colSpId !== -1 ? String(row[colSpId] || '').trim() : '';
      const prodObj = catalog.productByIdMap[spId] || catalog.productByIdMap[spId.toUpperCase()];
      const prodName = prodObj ? prodObj.prodName : spId;

      result[zone].push({
        idChiTiet: idChiTiet,
        idDonHang: line ? line.maDH : colOrderId !== -1 ? String(row[colOrderId] || '').trim() : '',
        maSP: spId,
        tenSP: line ? line.sanPham : prodName,
        soLuongDat: line ? line.slDat : colQty !== -1 ? (Number(row[colQty]) || 0) : 0,
        ngayGiao: line ? line.ngayGiao : colDate !== -1 ? this.formatSheetDate_(row[colDate]) : '',
        trangThai: line ? line.trangThai : status,
        ...(matchedLines ? { readOnly: readOnly } : {}),
        thuTu: priority
      });
    }

    // Sắp xếp thứ tự ưu tiên tăng dần trong từng vùng
    ['DANG_SAN_XUAT', 'UU_TIEN', 'CHO_SAN_XUAT'].forEach(z => {
      result[z].sort((a, b) => Number(!!a.readOnly) - Number(!!b.readOnly) || a.thuTu - b.thuTu);
    });

    console.log(`[SERVER] Đã tải Kanban: Đang chạy=${result.DANG_SAN_XUAT.length}, Ưu tiên=${result.UU_TIEN.length}, Chờ=${result.CHO_SAN_XUAT.length}`);
    return { success: true, data: result };
  },

  /**
   * [MỚI - SPEC-LINE-DND-01] Cập nhật vị trí & thứ tự kéo thả có LockService và Batch Update
   */
  mergeFilteredKanbanPositions_: function(current, requested) {
    const zones = ['DANG_SAN_XUAT', 'UU_TIEN', 'CHO_SAN_XUAT'];
    const currentIds = new Set(zones.flatMap(zone => current[zone].map(card => card.idChiTiet)));
    const visibleIds = new Set();
    const desired = { DANG_SAN_XUAT: [], UU_TIEN: [], CHO_SAN_XUAT: [] };

    for (const update of requested) {
      if (!update || !zones.includes(update.vungHienThi) ||
          !currentIds.has(update.idChiTiet) || visibleIds.has(update.idChiTiet)) {
        throw new Error('Dữ liệu Kanban đã thay đổi. Bấm Lọc (DB) để tải lại.');
      }
      visibleIds.add(update.idChiTiet);
      desired[update.vungHienThi].push(update.idChiTiet);
    }

    const merged = [];
    zones.forEach(zone => {
      const existing = current[zone].map(card => card.idChiTiet);
      const existingVisible = existing.filter(id => visibleIds.has(id));
      const nextVisible = desired[zone];
      if (existingVisible.length === nextVisible.length &&
          existingVisible.every((id, index) => id === nextVisible[index])) return;

      let next = 0;
      const ordered = [];
      existing.forEach(id => {
        if (!visibleIds.has(id)) ordered.push(id);
        else if (next < nextVisible.length) ordered.push(nextVisible[next++]);
      });
      ordered.push(...nextVisible.slice(next));
      ordered.forEach((id, index) => {
        merged.push({ idChiTiet: id, vungHienThi: zone, thuTu: index + 1 });
      });
    });
    return merged;
  },

  updateLineKanbanPositions: function(payload) {
    console.log("=== [SERVER] updateLineKanbanPositions nhận payload:", JSON.stringify(payload));
    if (!payload || !Array.isArray(payload.updates) || payload.updates.length === 0) {
      return { success: false, message: 'Dữ liệu vị trí kéo thả không hợp lệ.' };
    }

    const lock = LockService.getScriptLock();
    let hasLock = false;
    try {
      hasLock = lock.tryLock(10000); // Khóa 10s theo đặc tả
    } catch (e) {
      hasLock = false;
    }
    if (!hasLock) {
      return { success: false, message: 'Hệ thống đang bận cập nhật vị trí từ người dùng khác. Vui lòng thử lại!' };
    }

    try {
      const opSS = this.getOperationSpreadsheet_();
      const detailSheet = opSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);
      if (!detailSheet) throw new Error('Không tìm thấy bảng: ' + CONFIG.SHEET_NAMES.ORDER_DETAILS);

      const dataRange = detailSheet.getDataRange();
      const values = dataRange.getValues();
      if (values.length <= 1) return { success: true, updatedCount: 0 };

      const headers = values[0].map(h => String(h || '').trim().toLowerCase());
      const colId = headers.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.ID.toLowerCase());
      let colZone = headers.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE.toLowerCase());
      let colPriority = headers.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER.toLowerCase());

      // Tự động thêm cột vào cuối sheet nếu chưa tồn tại
      if (colZone === -1) {
        colZone = headers.length;
        detailSheet.getRange(1, colZone + 1).setValue(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE);
        headers.push(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE);
      }
      if (colPriority === -1) {
        colPriority = headers.length;
        detailSheet.getRange(1, colPriority + 1).setValue(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER);
        headers.push(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER);
      }

      const updates = payload.filteredBoard === true
        ? this.mergeFilteredKanbanPositions_(
            this.buildLineKanbanData_(values, { productByIdMap: {} }).data, payload.updates
          )
        : payload.updates;
      if (updates.length === 0) {
        return { success: true, updatedCount: payload.updates.length };
      }

      const updateMap = Object.create(null);
      updates.forEach(u => {
        if (u.idChiTiet) {
          updateMap[String(u.idChiTiet).trim()] = {
            vungHienThi: u.vungHienThi || '',
            thuTu: (u.thuTu !== undefined && u.thuTu !== null && u.thuTu !== '') ? parseInt(u.thuTu, 10) : ''
          };
        }
      });

      const maxColIdx = Math.max(colZone, colPriority);
      let updatedCount = 0;

      // Cập nhật mảng in-memory và tạo ma trận ghi cột theo lô (Batch Write)
      const writeMatrix = [];
      for (let r = 1; r < values.length; r++) {
        const row = values[r];
        while (row.length <= maxColIdx) row.push('');
        const idCT = colId !== -1 ? String(row[colId] || '').trim() : '';

        if (idCT && updateMap[idCT]) {
          row[colZone] = updateMap[idCT].vungHienThi;
          row[colPriority] = updateMap[idCT].thuTu;
          updatedCount++;
        }
        writeMatrix.push(colZone < colPriority
          ? [row[colZone], row[colPriority]]
          : [row[colPriority], row[colZone]]);
      }

      // Ghi lô 2 cột M và N (Cột 13 và 14) bằng setValues duy nhất
      if (writeMatrix.length > 0) {
        const firstCol = Math.min(colZone, colPriority) + 1;
        const lastCol = Math.max(colZone, colPriority) + 1;
        if (lastCol === firstCol + 1) {
          detailSheet.getRange(2, firstCol, writeMatrix.length, 2).setValues(writeMatrix);
        } else {
          detailSheet.getRange(2, firstCol, writeMatrix.length, 1).setValues(writeMatrix.map(row => [row[0]]));
          detailSheet.getRange(2, lastCol, writeMatrix.length, 1).setValues(writeMatrix.map(row => [row[1]]));
        }
      }
      SpreadsheetApp.flush();
      console.log(`[SERVER] Đã cập nhật vị trí cho ${updatedCount} chi tiết đơn hàng thành công.`);
      return {
        success: true,
        message: 'Cập nhật vị trí thành công',
        updatedCount: payload.filteredBoard === true ? payload.updates.length : updatedCount
      };
    } catch (err) {
      console.error('[SERVER] Lỗi updateLineKanbanPositions:', err);
      return { success: false, message: 'Lỗi máy chủ khi lưu vị trí: ' + err.message };
    } finally {
      lock.releaseLock();
    }
  },

  /**
   * [MỚI - SPEC-LINE-DND-01] Hàm Migration Script chạy 1 lần khởi tạo 2 cột M & N cho dữ liệu cũ
   */
  migrateKanbanColumnsData: function() {
    console.log("=== BẮT ĐẦU MIGRATION DỮ LIỆU KANBAN ===");
    const opSS = this.getOperationSpreadsheet_();
    const detailSheet = opSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);
    if (!detailSheet) throw new Error('Không tìm thấy sheet: ' + CONFIG.SHEET_NAMES.ORDER_DETAILS);

    const range = detailSheet.getDataRange();
    const vals = range.getValues();
    if (vals.length <= 1) return 'Sheet rỗng.';

    const hdrs = vals[0].map(h => String(h || '').trim());
    let cZone = hdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE);
    let cPriority = hdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER);
    const cStatus = hdrs.indexOf(CONFIG.COLUMNS.ORDER_DETAILS.STATUS);

    if (cZone === -1) {
      cZone = hdrs.length;
      detailSheet.getRange(1, cZone + 1).setValue(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE);
      hdrs.push(CONFIG.COLUMNS.ORDER_DETAILS.KANBAN_ZONE);
    }
    if (cPriority === -1) {
      cPriority = hdrs.length;
      detailSheet.getRange(1, cPriority + 1).setValue(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER);
      hdrs.push(CONFIG.COLUMNS.ORDER_DETAILS.PRIORITY_ORDER);
    }

    const batchVals = [];
    let autoSeq = 1;
    for (let r = 1; r < vals.length; r++) {
      const st = cStatus !== -1 ? String(vals[r][cStatus] || '').trim().toLowerCase() : '';
      if (st.includes('hoàn thành') || st.includes('xong') || st.includes('kết thúc')) {
        batchVals.push(['', '']);
      } else {
        batchVals.push([CONFIG.KANBAN_ZONES.PENDING, autoSeq++]);
      }
    }

    detailSheet.getRange(2, cZone + 1, batchVals.length, 1).setValues(batchVals.map(([zone]) => [zone]));
    detailSheet.getRange(2, cPriority + 1, batchVals.length, 1).setValues(batchVals.map(([, priority]) => [priority]));
    SpreadsheetApp.flush();
    return `Migration thành công: đã cập nhật ${batchVals.length} dòng dữ liệu.`;
  }
}
