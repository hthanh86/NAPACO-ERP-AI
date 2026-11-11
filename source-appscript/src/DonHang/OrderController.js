/**
 * ============================================================================
 * NAPACO ENTERPRISE ERP - ORDER CONTROLLER (WEB APP & RPC ROUTER)
 * File: OrderController.gs
 * Tầng kiến trúc: Tầng 2 - Controller Layer
 * Nhiệm vụ:
 *  - Cung cấp hàm doGet(e) phục vụ Standalone Web App (routing giữa màn hình
 *    Tra cứu đơn hàng Dual-View 'OrderList_View' và Tạo đơn hàng 'OrderModal').
 *  - Cung cấp các hàm Global RPC để Client HTML gọi qua google.script.run.
 *  - Kiểm soát thông báo lỗi chuẩn hóa, không làm lộ thông tin nhạy cảm.
 * ============================================================================
 */

/**
 * Entry point cho Standalone Web App
 * Hỗ trợ tham số URL:
 *  - Không có tham số hoặc ?view=index: Mở trang Đơn Hàng.
 *  - ?view=list: Mở danh sách Định Hình (type 1).
 *  - ?view=film: Mở phân hệ Đặt Màng.
 *  - ?view=be: Mở danh sách Bế (type 2).
 *  - ?view=create: Mở giao diện Tạo đơn hàng (OrderModal.html).
 */
function doGet(e) {
  try {
    const params = (e && e.parameter) ? e.parameter : {};
    const view = String(params.view || 'index').toLowerCase();

    const appUrl = ScriptApp.getService().getUrl() || '';
    if (view === 'create' || view === 'modal') {
      const webEntry = view === 'create' && !params.sourceId;
      const initRes = OrderController.getOrderModalInitData(webEntry ? '' : params.sourceId || '', webEntry);
      const template = HtmlService.createTemplateFromFile('DonHang/OrderModal');
      template.orderWebUrl = appUrl;
      template.orderWebEntry = webEntry;
      const jsonStr = JSON.stringify(initRes.success ? initRes.data : { initError: initRes.error.message });
      template.initialDataJson = Utilities.base64Encode(Utilities.newBlob(jsonStr, 'application/json').getBytes());

      return template.evaluate()
        .setTitle('NAPACO ERP - Tạo Phiếu Đơn Đặt Hàng Mới')
        .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
        .addMetaTag('viewport', 'width=device-width, initial-scale=1');
    }

    let output;
    let title;
    if (view === 'index') {
      const template = HtmlService.createTemplateFromFile('DonHang/OrderIndex_View');
      template.appUrl = appUrl;
      output = template.evaluate();
      title = 'NAPACO ERP - Đơn Hàng';
    } else if (view === 'film' || view === 'film-create') {
      const template = HtmlService.createTemplateFromFile('KHO_NVL/FilmOrder_View');
      template.appUrl = appUrl;
      template.filmMode = view;
      template.copyIds = String(params.copy || '').slice(0, 4500);
      output = template.evaluate();
      title = view === 'film-create' ? 'NAPACO ERP - Tạo Đơn Đặt Màng' : 'NAPACO ERP - Màng Đã Đặt';
    } else if (view === 'film-stock') {
      const template = HtmlService.createTemplateFromFile('KHO_NVL/FilmStock_View');
      template.appUrl = appUrl;
      output = template.evaluate();
      title = 'NAPACO ERP - Tồn Kho NVL';
    } else if (view === 'film-receive') {
      const template = HtmlService.createTemplateFromFile('KHO_NVL/FilmReceipt_View');
      template.appUrl = appUrl;
      output = template.evaluate();
      title = 'NAPACO ERP - Nhận Màng';
    } else {
      const productType = view === 'be' ? '2' : '1';
      output = renderOrderListView_(productType, appUrl, params);
      title = productType === '2' ? 'NAPACO ERP - Đơn Hàng Bế' : 'NAPACO ERP - Đơn Hàng Định Hình';
    }

    return output
      .setTitle(title)
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
      .addMetaTag('viewport', 'width=device-width, initial-scale=1');

  } catch (err) {
    return HtmlService.createHtmlOutput(
      '<div style="font-family:sans-serif;padding:24px;color:#991b1b;background:#fef2f2;border:1px solid #f87171;border-radius:8px;">' +
      '<h3>⚠️ Lỗi khởi chạy ứng dụng NAPACO ERP</h3>' +
      '<p>' + String(err.message || err) + '</p></div>'
    );
  }
}

function renderOrderMenu_(appUrl, activeModule) {
  const links = [
    { id: 'index', group: 'Đơn hàng', icon: '▦', label: 'Đơn Hàng', url: appUrl + '?view=index' },
    { id: 'create', group: 'Đơn hàng', icon: '+', label: 'Tạo đơn hàng', url: appUrl + '?view=create' },
    { id: 'list', group: 'Đơn hàng', icon: '◫', label: 'Định Hình', url: appUrl + '?view=list' },
    { id: 'be', group: 'Đơn hàng', icon: '✂', label: 'Bế', url: appUrl + '?view=be' },
    // Điền URL web app của từng phân hệ khi có đường dẫn.
    { id: 'film-create', group: 'Nguyên Liệu', icon: '+', label: 'Tạo Đơn', url: appUrl + '?view=film-create' },
    { id: 'film', group: 'Nguyên Liệu', icon: '▤', label: 'Màng Đã Đặt', url: appUrl + '?view=film' },
    { id: 'film-receive', group: 'Nguyên Liệu', icon: '↓', label: 'Nhận Màng', url: appUrl + '?view=film-receive' },
    { id: 'film-stock', group: 'Nguyên Liệu', icon: '▥', label: 'Tồn Kho', url: appUrl + '?view=film-stock' },
    { id: 'forming-log', group: 'Sản xuất', icon: '▣', label: 'Nhật Ký Định Hình', url: '' }
  ];
  const template = HtmlService.createTemplateFromFile('DonHang/OrderMenu_View');
  template.appUrl = appUrl;
  template.links = links;
  template.activeModule = activeModule;
  return template.evaluate().getContent();
}

function renderOrderListView_(productType, appUrl, filters) {
  const template = HtmlService.createTemplateFromFile('DonHang/OrderList_View');
  const params = filters || {};
  template.productType = productType;
  template.createdOrderIds = String(params.orders || '').split(',')
    .filter(id => /^DH_\d{6}_\d+$/.test(id)).join(',');
  template.createdPO = String(params.po || '');
  template.showOtherOrderType = String(params.mixed || '') === '1';
  template.appUrl = appUrl;
  return template.evaluate();
}

function getSavedOrderListPage(params) {
  const filters = params || {};
  const productType = filters.view === 'be' ? '2' : '1';
  return renderOrderListView_(productType, ScriptApp.getService().getUrl() || '', filters).getContent();
}

/**
 * Hàm hỗ trợ nhúng file HTML con (nếu dùng <?!= include(...) ?>)
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

/**
 * Đối tượng Controller điều phối nghiệp vụ Module 1
 */
const OrderController = {

  /**
   * 1. Lấy dữ liệu khởi tạo cho OrderModal.html (bao gồm xác thực kép, danh mục & các dòng từ TAO DON)
   * @param {string=} optSourceSpreadsheetId ID bảng tính nguồn (nếu gọi từ Sheet TAO DON)
   */
  getOrderModalInitData: function(optSourceSpreadsheetId, webEntry) {
    try {
      const data = OrderService.buildModalInitialData(optSourceSpreadsheetId, webEntry);
      return {
        success: true,
        data: data
      };
    } catch (err) {
      console.error('[OrderController.getOrderModalInitData] Error:', err);
      return {
        success: false,
        error: {
          code: 'ERR_INIT_MODAL',
          message: err.message || 'Không thể tải dữ liệu khởi tạo form đơn hàng.'
        }
      };
    }
  },

  /**
   * 2. Lấy dữ liệu danh mục Master + thông tin xác thực nhân sự cho Web App độc lập
   */
  getOrderFormData: function() {
    try {  
        const data = OrderService.getCatalogAndAuthData();  
        return {  
          success: true,  
          customers: data.customers,  
          products: data.products,  
          salesStaffList: data.salesStaffList,  
          currentUser: data.currentUser,  
          serverDate: data.serverDate,  
          defaultDeliveryDate: data.defaultDeliveryDate,
          systemConfig: {
            filterGroups: CONFIG.FILTER_STATUS_GROUPS,
            statusGroupsList: CONFIG.FILTER_STATUS_GROUPS_LIST || {
              ACTIVE_ALL: [CONFIG.LINE_STATUS.NEW, CONFIG.LINE_STATUS.MOLDING, CONFIG.LINE_STATUS.IN_PRODUCTION],
              DONE_ALL: [CONFIG.LINE_STATUS.COMPLETED, CONFIG.LINE_STATUS.CLOSED, CONFIG.ORDER_STATUS.CANCELLED]
            }
          }
        };
    } catch (err) {
      console.error('[OrderController.getOrderFormData] Error:', err);
      return {
        success: false,
        error: {
          code: 'ERR_INIT_FORM',
          message: err.message || 'Không thể tải danh mục hệ thống.'
        }
      };
    }
  },

  /**
   * 3. Lưu giao dịch tạo đơn hàng liên tầng (Flow-based Upsert) có LockService
   * Đáp ứng chuẩn API Contract: saveOrderTransaction(payload)
   */
  
  saveOrderTransaction: function(payload) {
    try {
      if (!payload || !payload.poGroups || payload.poGroups.length === 0) {
        throw new Error("Dữ liệu đơn hàng gửi lên không hợp lệ hoặc danh sách rỗng!");
      }
      // Chuyển toàn bộ việc quản lý Lock và ghi DB cho OrderService
      return OrderService.saveOrderTransaction(payload);
    } catch (err) {
      console.error('[OrderController.saveOrderTransaction] Error:', err);
      return {
        success: false,
        error: {
          code: err.code || 'ERR_SAVE_ORDER',
          message: err.message || 'Lỗi trong quá trình lưu đơn hàng.'
        },
        message: err.message || 'Lỗi trong quá trình lưu đơn hàng.'
      };
    }
  },

  /**
   * 4. Tra cứu danh sách đơn hàng và chi tiết mặt hàng theo 2 chế độ xem kép (HEADER | LINE_ITEM)
   * Đáp ứng chuẩn API Contract: queryOrdersAndLineItems(searchParams)
   */
  queryOrdersAndLineItems: function(searchParams) {
    try {
      return OrderService.queryOrdersAndLineItems(searchParams || {});
    } catch (err) {
      console.error('[OrderController.queryOrdersAndLineItems] Error:', err);
      return {
        success: false,
        viewMode: (searchParams && searchParams.viewMode) ? searchParams.viewMode : 'HEADER',
        total: 0,
        data: [],
        error: {
          code: 'ERR_QUERY_ORDERS',
          message: err.message || 'Lỗi khi truy vấn dữ liệu đơn hàng.'
        }
      };
    }
  },

  /* [MỚI - SPEC-ERP-LINEITEM-202611-01] Controller tiếp nhận lệnh Bulk Edit */
  updateOrderLineItemsBulk: function(payload) {
    try {
      return OrderService.updateOrderLineItemsBulk(payload);
    } catch (err) {
      console.error('[OrderController.updateOrderLineItemsBulk] Error:', err);
      return {
        success: false,
        message: err.message || 'Lỗi xử lý chỉnh sửa hàng loạt.'
      };
    }
  },

  /**
   * 5. Hàm phục vụ hiển thị nhanh trên Sheet (nếu gọi từ ClientLauncher)
   */
  getOrdersForSheet: function(viewMode) {
    try {
      const res = OrderService.queryOrdersAndLineItems({
        viewMode: viewMode === 'LINE_ITEM' ? 'LINE_ITEM' : 'HEADER',
        page: 1,
        pageSize: 500
      });
      return {
        success: true,
        rows: res.data || []
      };
    } catch (err) {
      return {
        success: false,
        error: { message: err.message }
      };
    }
  }, 

    /* [MỚI - SPEC-LINE-DND-01] Controller lấy dữ liệu 3 phân vùng Kanban */
  getLineKanbanData: function() {
    try {
      return OrderService.getLineKanbanData();
    } catch (err) {
      console.error('[OrderController.getLineKanbanData] Lỗi:', err);
      return { success: false, message: err.message || 'Lỗi tải dữ liệu Kanban' };
    }
  },

  /* [MỚI - SPEC-LINE-DND-01] Controller cập nhật vị trí kéo thả */
  updateLineKanbanPositions: function(payload) {
    try {
      return OrderService.updateLineKanbanPositions(payload);
    } catch (err) {
      console.error('[OrderController.updateLineKanbanPositions] Lỗi:', err);
      return { success: false, message: err.message || 'Lỗi lưu vị trí kéo thả' };
    }
  }
};

// ============================================================================
// CÁC HÀM GLOBAL RPC EXPOSED CHO GOOGLE.SCRIPT.RUN TỪ CLIENT HTML
// ============================================================================

/**
 * RPC: Lấy dữ liệu khởi tạo Modal tạo đơn hàng
 */
function getOrderModalInitData(sourceSpreadsheetId) {
  return OrderController.getOrderModalInitData(sourceSpreadsheetId);
}

/**
 * RPC: Lấy danh mục Khách hàng, Sản phẩm, Nhân viên và User Auth
 */
function getOrderFormData() {
  return OrderController.getOrderFormData();
}

/**
 * RPC chuẩn theo tài liệu đặc tả: Lưu giao dịch đơn hàng liên tầng
 */
function saveOrderTransaction(payload) {
  return OrderController.saveOrderTransaction(payload);
}

/**
 * RPC tương thích ngược với code cũ: saveOrderFromModal(payload)
 * Tự động ánh xạ về cùng luồng xử lý saveOrderTransaction
 */
function saveOrderFromModal(payload) {
  const result = OrderController.saveOrderTransaction(payload);
  if (!result.success) {
    throw new Error(result.message || (result.error && result.error.message) || 'Lỗi lưu đơn hàng');
  }
  return result;
}

/**
 * RPC tương thích với mã nguồn mẫu: submitOrderTransaction(payload)
 */
function submitOrderTransaction(payload) {
  return OrderController.saveOrderTransaction(payload);
}

/**
 * RPC chuẩn theo tài liệu đặc tả: Truy vấn đơn hàng & dòng mặt hàng (Dual-View)
 */
function queryOrdersAndLineItems(searchParams) {
  return OrderController.queryOrdersAndLineItems(searchParams);
}

/**
 * [MỚI - SPEC-ERP-LINEITEM-202611-01] Global RPC gọi Chỉnh sửa hàng loạt dòng mặt hàng
 */
function updateOrderLineItemsBulk(payload) {
  return OrderController.updateOrderLineItemsBulk(payload);
}

/**
 * [MỚI - SPEC-LINE-DND-01] Global RPC lấy dữ liệu Kanban 3 vùng
 */
function apiGetLineKanbanData() {
  return OrderController.getLineKanbanData();
}

/**
 * [MỚI - SPEC-LINE-DND-01] Global RPC cập nhật vị trí kéo thả Kanban
 */
function apiUpdateLineKanbanPositions(payload) {
  return OrderController.updateLineKanbanPositions(payload);
}

/**
 * [MỚI - SPEC-LINE-DND-01] Hàm gọi thủ công để chạy Migration
 */
function runKanbanMigration() {
  return OrderService.migrateKanbanColumnsData();
}

/**
 * Router đón request POST từ ClientLauncher.gs của Google Sheets
 */
function doPost(e) {
  try {
    // Kiểm tra đầu vào an toàn
    if (!e || !e.postData || !e.postData.contents) {
      throw new Error("Payload request trống hoặc không hợp lệ.");
    }
    
    var data = JSON.parse(e.postData.contents);
    var action = data.action;
    var payload = data.payload || {};
    var result = null;

    if (action === 'SYNC_CATALOG') {
      result = OrderService.syncCacheCatalogFromDatabase();
    } else if (action === 'GET_MODAL_INIT') {
      result = OrderService.buildModalInitialData(payload.sourceSpreadsheetId);
    } else if (action === 'SAVE_ORDER') {
      result = OrderService.saveOrderTransaction(payload);
    } else {
      throw new Error("Action không tồn tại: " + action);
    }

    // Trả về JSON chuẩn 100%
    return ContentService.createTextOutput(JSON.stringify({
      success: true,
      data: result
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    // Bắt toàn bộ lỗi bên trong service/controller và ép gói về JSON, tuyệt đối không cho văng HTML
    return ContentService.createTextOutput(JSON.stringify({
      success: false,
      error: {
        message: err.message || String(err),
        stack: err.stack || ""
      }
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * CẦU NỐI CÔNG KHAI ĐỂ CLIENT LAUNCHER GỌI QUA THƯ VIỆN BACKEND
 */

function refreshOrderData(targetSpreadsheetId) {
  return OrderService.syncCacheCatalogFromDatabase(targetSpreadsheetId);
}

/**
 * ĐỌC DỮ LIỆU TỪ SHEET 'TAO DON' THEO TÊN CỘT ĐỘNG VÀ ĐÓNG GÓI CHO MODAL
 */
/**
 * ĐỌC DỮ LIỆU TỪ SHEET 'TAO DON' THEO TÊN CỘT ĐỘNG VÀ ĐÓNG GÓI CHO MODAL
 */
function getOrderFormDataForModal(optSourceSpreadsheetId) {
  try {
    const ss = optSourceSpreadsheetId 
      ? SpreadsheetApp.openById(optSourceSpreadsheetId) 
      : SpreadsheetApp.getActiveSpreadsheet();
    if (!ss) return JSON.stringify({ poGroups: [], salesStaffList: [] });

    const sheet = ss.getSheetByName(CONFIG.SHEET_NAMES.ORDER_WORKSPACE || 'TAO DON');
    if (!sheet) return JSON.stringify({ poGroups: [], salesStaffList: [] });

    const headerRowIdx = CONFIG.FORM_COLUMNS.HEADER_ROW;
    const startDataRow = CONFIG.FORM_COLUMNS.DATA_START_ROW;
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    if (lastRow < startDataRow || lastCol < 1) {
      return JSON.stringify({ poGroups: [], salesStaffList: [] });
    }

    // 1. Quét tiêu đề dòng 7 và tìm vị trí cột dựa trên CONFIG
    const headers = sheet.getRange(headerRowIdx, 1, 1, lastCol).getValues()[0];
    const findColIdx = (aliases) => {
      for (let c = 0; c < headers.length; c++) {
        const text = String(headers[c] || '').trim().toLowerCase();
        if (aliases.some(a => text.includes(a.toLowerCase()))) return c;
      }
      return -1;
    };

    const c_kh    = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.CUSTOMER);
    const c_sp    = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.PRODUCT);
    const c_code  = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.CODE);
    const c_unit  = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.UNIT);
    const c_price = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.PRICE);
    const c_qty   = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.QTY);
    const c_po    = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.PO);
    const c_note  = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.NOTE);
    const c_link  = findColIdx(CONFIG.FORM_COLUMNS.ALIASES.LINK_PO);

    // 2. Đọc Cache Sản phẩm và Danh sách Nhân Viên KD từ _CACHE_DANH_MUC
    const cacheSheet = ss.getSheetByName(CONFIG.SHEET_NAMES.CACHE_CATALOG || '_CACHE_DANH_MUC');
    const cacheProductMap = {};
    const salesStaffList = [];

    if (cacheSheet && cacheSheet.getLastRow() >= 2) {
      const cacheRowsCount = cacheSheet.getLastRow() - 1;

      // Đọc Sản phẩm từ Cột A:E
      const cacheData = cacheSheet.getRange(2, 1, cacheRowsCount, 5).getValues();
      for (let i = 0; i < cacheData.length; i++) {
        const pName = String(cacheData[i][0] || '').trim().toLowerCase();
        if (pName) {
          cacheProductMap[pName] = {
            unit: cacheData[i][3] || 'Cái',
            price: Number(cacheData[i][4]) || 0
          };
        }
      }

      // Đọc Danh sách Nhân Viên KD từ Cột G (Cột 7)
      if (cacheSheet.getLastColumn() >= 7) {
        const staffVals = cacheSheet.getRange(2, 7, cacheRowsCount, 1).getValues();
        for (let s = 0; s < staffVals.length; s++) {
          const val = String(staffVals[s][0] || '').trim();
          if (val) {
            const parts = val.split(' - ');
            salesStaffList.push({
              display: val,
              maNV: parts[0] ? parts[0].trim() : val,
              hoTen: parts[1] ? parts[1].trim() : val
            });
          }
        }
      }
    }

    // Fallback: nếu Cache chưa có NV thì lấy qua Service
    if (salesStaffList.length === 0 && typeof OrderService.getCatalogAndAuthData === 'function') {
      const authData = OrderService.getCatalogAndAuthData();
      if (authData && authData.salesStaffList) {
        authData.salesStaffList.forEach(st => salesStaffList.push(st));
      }
    }

    // 3. Tự động nhận diện tài khoản Google đăng nhập để chọn sẵn Sales
    let defaultSalesPerson = '';
    try {
      const userEmail = String(Session.getActiveUser().getEmail() || '').trim().toLowerCase();
      if (userEmail && typeof OrderService.getCatalogAndAuthData === 'function') {
        const authData = OrderService.getCatalogAndAuthData();
        if (authData.currentUser && authData.currentUser.display) {
          defaultSalesPerson = authData.currentUser.display;
        }
      }
    } catch (e) {
      defaultSalesPerson = '';
    }

    // 4. Đọc dữ liệu các dòng trên TAO DON và gom nhóm theo PO
    const rawData = sheet.getRange(startDataRow, 1, lastRow - startDataRow + 1, lastCol).getValues();
    const poGroupsMap = {};
    const today = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyyy-MM-dd");
    const defaultDelivery = Utilities.formatDate(new Date(Date.now() + 10 * 86400000), "Asia/Ho_Chi_Minh", "yyyy-MM-dd");

    for (let r = 0; r < rawData.length; r++) {
      const row = rawData[r];
      const prodName = c_sp >= 0 ? String(row[c_sp] || '').trim() : '';
      if (!prodName) continue;

      const custName = c_kh >= 0 ? String(row[c_kh] || '').trim() : '';
      let poNum = c_po >= 0 ? String(row[c_po] || '').trim() : '';
      if (!poNum) {
        const yymmdd = Utilities.formatDate(new Date(), "Asia/Ho_Chi_Minh", "yyMMdd");
        const cleanCus = custName.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-+|-+$/g, "");
        poNum = 'PO-' + yymmdd + '-' + (cleanCus || 'KH');
      }

      const existingLink = c_link >= 0 ? String(row[c_link] || '').trim() : '';
      const orderNote = c_note >= 0 ? String(row[c_note] || '').trim() : '';

      if (!poGroupsMap[poNum]) {
        poGroupsMap[poNum] = {
          customerName: custName,
          soPO: poNum,
          autoPONumber: poNum,
          salesPerson: defaultSalesPerson,
          ngayDat: today,
          ngayGiaoDK: defaultDelivery,
          orderNote: orderNote,
          existingFileUrl: existingLink,
          items: []
        };
      }

      const codeSP = c_code >= 0 ? String(row[c_code] || '').trim() : '';
      const unit = c_unit >= 0 ? (String(row[c_unit] || 'Cái').trim() || 'Cái') : 'Cái';
      const qty = c_qty >= 0 ? (Number(row[c_qty]) || 0) : 0;
      const price = c_price >= 0 ? (Number(row[c_price]) || 0) : 0;
      const cached = cacheProductMap[prodName.toLowerCase()] || {};

      poGroupsMap[poNum].items.push({
        prodName: prodName,
        codeSP: codeSP,
        unit: unit,
        qty: qty > 0 ? qty : 5000,
        price: price > 0 ? price : (cached.price || 0),
        giaKhuon: 0,
        mang: '',
        type: '1',
        donggoi: '',
        ngayDat: today,
        ngayGiao: defaultDelivery,
        deliveryDate: defaultDelivery,
        note: orderNote,
        isNewProduct: !Boolean(cacheProductMap[prodName.toLowerCase()])
      });
    }

    return JSON.stringify({
      poGroups: Object.values(poGroupsMap),
      salesStaffList: salesStaffList
    });

  } catch (err) {
    console.error("❌ [BACKEND] Lỗi getOrderFormDataForModal:", err);
    return JSON.stringify({ poGroups: [], salesStaffList: [] });
  }
}

/**
 * HÀM CẦU NỐI MỞ MODAL ĐƯỢC CLIENT GỌI QUA THƯ VIỆN BACKEND
 */
function openOrderModal(optSourceSpreadsheetId) {
  const targetId = optSourceSpreadsheetId || (SpreadsheetApp.getActiveSpreadsheet() ? SpreadsheetApp.getActiveSpreadsheet().getId() : null);
  
  // 1. Chuẩn bị dữ liệu từ sheet TAO DON và mã hóa Base64
  const jsonDataStr = getOrderFormDataForModal(targetId);
  const base64Data = Utilities.base64Encode(Utilities.newBlob(jsonDataStr, 'application/json').getBytes());

  // 2. Nạp dữ liệu thẳng vào Template HTML (KHÔNG CẦN CHỜ RPC FALLBACK)
  const template = HtmlService.createTemplateFromFile('DonHang/OrderModal');
  template.initialDataJson = base64Data;

  const htmlOutput = template.evaluate()
    .setWidth(1150)
    .setHeight(700)
    .setTitle('NAPACO ERP - Tạo Đơn Hàng');

  SpreadsheetApp.getUi().showModalDialog(htmlOutput, 'NAPACO ERP - Phiếu Tạo Đơn Hàng');
}

// 3. Hàm xử lý onEdit tự động điền sản phẩm
function onEditClientHandler(e) {
  onEditAutoFillProduct(e);
}

/**
 * Hàm nhận giao dịch lưu đơn hàng
 */
function saveOrderFromModal(payload) {
  console.log('[BACKEND] >>> Bắt đầu xử lý saveOrderFromModal:');
  console.log('[BACKEND] Payload nhận được:', JSON.stringify(payload).substring(0, 300) + '...');

  if (typeof OrderService !== 'undefined' && typeof OrderService.saveOrderTransaction === 'function') {
    const res = OrderService.saveOrderTransaction(payload);
    console.log('[BACKEND] <<< Lưu thành công, kết quả:', JSON.stringify(res));
    return res;
  } else if (typeof executeSaveOrdersWithSchema === 'function') {
    const res = executeSaveOrdersWithSchema(payload);
    console.log('[BACKEND] <<< Lưu thành công qua executeSaveOrdersWithSchema:', JSON.stringify(res));
    return res;
  } else {
    throw new Error('Không tìm thấy hàm xử lý ghi đơn hàng (saveOrderTransaction / executeSaveOrdersWithSchema)!');
  }
}

function test_refreshOrderData_Backend() {
  const masterSS = SpreadsheetApp.openById(CONFIG.ID_MASTER);
  
  // IN RA TẤT CẢ TÊN SHEET ĐANG CÓ TRONG 01. DB MASTER ĐỂ ĐỐI CHIẾU
  const allSheetNames = masterSS.getSheets().map(s => s.getName());
  console.log("🔍 [DEBUG-MASTER] Danh sách tên Sheet trong DB MASTER:", JSON.stringify(allSheetNames));

  // Thử mở sheet nhân viên theo cấu hình
  const empSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.EMPLOYEES);
  if (!empSheet) {
    console.error("❌ [DEBUG-MASTER] KHÔNG TÌM THẤY SHEET:", CONFIG.SHEET_NAMES.EMPLOYEES);
  } else {
    console.log("✅ [DEBUG-MASTER] Tìm thấy sheet:", empSheet.getName(), "- Số dòng:", empSheet.getLastRow());
    console.log("🔍 [DEBUG-MASTER] Dòng tiêu đề (Row 1):", JSON.stringify(empSheet.getRange(1, 1, 1, empSheet.getLastColumn()).getValues()[0]));
    if (empSheet.getLastRow() >= 2) {
      console.log("🔍 [DEBUG-MASTER] Dòng dữ liệu đầu tiên (Row 2):", JSON.stringify(empSheet.getRange(2, 1, 1, empSheet.getLastColumn()).getValues()[0]));
    }
    // In ra các dòng từ 4 đến 7 để xác định vị trí tiêu đề và dòng dữ liệu đầu tiên
  for (let r = 4; r <= 8; r++) {
    const rowVals = empSheet.getRange(r, 1, 1, empSheet.getLastColumn()).getValues()[0];
    console.log(`🔍 [ROW-${r}]:`, JSON.stringify(rowVals));
  }
  }

  // Chạy đồng bộ như cũ
  const TEST_CLIENT_SPREADSHEET_ID = '1iOJq_bxA6c8Oky1hsH-7ukiyT8YyGCLLgJ8AJ1Om5bE';
  const result = OrderService.syncCacheCatalogFromDatabase(TEST_CLIENT_SPREADSHEET_ID);
  console.log("✅ [TEST-BACKEND] Kết quả:", JSON.stringify(result));
}

/**
 * RPC: Tìm kiếm tệp trên Google Drive của người dùng theo từ khóa
 * @param {string} keyword Từ khóa tìm kiếm (tên file, số PO, tên khách...)
 * @return {{success: boolean, files: Array<{id: string, name: string, url: string, mimeType: string, size: number, updated: string}>}}
 */
function searchUserDriveFiles(keyword) {
  try {
    const kw = String(keyword || '').trim();
    if (!kw) return { success: true, files: [] };

    const fields = 'id,name,webViewLink,mimeType,size,modifiedTime,trashed,resourceKey';
    const folderMime = 'application/vnd.google-apps.folder';
    const link = kw.match(/^https:\/\/(drive|docs)\.google\.com(?:\/[^\s]*)?$/i);
    let matches = [];
    let incomplete = false;

    if (link) {
      const pathId = kw.match(/\/d\/([\w-]+)(?=[/?#]|$)/);
      const queryId = kw.match(/[?&]id=([\w-]+)(?=[&#]|$)/);
      const resourceKey = kw.match(/[?&]resourcekey=([\w-]+)(?=[&#]|$)/i);
      const id = (pathId || queryId || [])[1];
      if (!id) throw new Error('Vui lòng dán liên kết đến một tệp Drive cụ thể.');
      if (resourceKey) {
        const file = DriveApp.getFileByIdAndResourceKey(id, resourceKey[1]);
        matches = [{
          id, name: file.getName(), mimeType: file.getMimeType(), size: file.getSize(),
          modifiedTime: file.getLastUpdated(), trashed: file.isTrashed(), webViewLink: kw
        }];
      } else {
        matches = [Drive.Files.get(id, { supportsAllDrives: true, fields })];
      }
    } else {
      const literal = value => "'" + value.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "'";
      const terms = kw.match(/[\p{L}\p{M}\p{N}]+/gu) || [];
      const conditions = ['name contains ' + literal(kw), 'fullText contains ' + literal(kw)];
      if (terms.length > 1 && terms.length <= 8) {
        conditions.push('(' + terms.map(term => 'fullText contains ' + literal(term)).join(' and ') + ')');
      }
      const options = {
        q: "trashed = false and mimeType != '" + folderMime + "' and (" + conditions.join(' or ') + ')',
        corpora: 'allDrives',
        spaces: 'drive',
        supportsAllDrives: true,
        includeItemsFromAllDrives: true,
        orderBy: 'modifiedTime desc',
        pageSize: 20,
        fields: 'nextPageToken,incompleteSearch,files(' + fields + ')'
      };
      do {
        const page = Drive.Files.list(options);
        matches.push(...(page.files || []));
        incomplete = incomplete || Boolean(page.incompleteSearch);
        options.pageToken = page.nextPageToken;
      } while (options.pageToken && matches.length < 20);
    }

    const files = matches.filter(file => !file.trashed && file.mimeType !== folderMime).slice(0, 20).map(file => {
      let url = file.webViewLink || 'https://drive.google.com/open?id=' + encodeURIComponent(file.id);
      if (file.resourceKey && !/[?&]resourcekey=/i.test(url)) {
        url += (url.includes('?') ? '&' : '?') + 'resourcekey=' + encodeURIComponent(file.resourceKey);
      }
      return {
        id: file.id,
        name: file.name,
        url,
        mimeType: file.mimeType,
        size: Number(file.size) || 0,
        updated: file.modifiedTime
          ? Utilities.formatDate(new Date(file.modifiedTime), CONFIG.TIMEZONE, 'dd/MM/yyyy')
          : ''
      };
    });
    return { success: true, files, incomplete };
  } catch (err) {
    console.error('[searchUserDriveFiles]', err);
    return { success: false, error: err.message, files: [] };
  }
}
