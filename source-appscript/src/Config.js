/**
 * FILE: Config.gs - NƠI DUY NHẤT ĐỊNH NGHĨA CẤU HÌNH HỆ THỐNG & TÊN CỘT GIAO DIỆN
 */
var CONFIG = {

  // ==========================================
  // 1. CỜ BẬT / TẮT LOG KIỂM TRA DỮ LIỆU
  // true: Xuất log chi tiết (Development / Staging)
  // false: Tắt toàn bộ log để tối ưu hiệu năng (Production)
  // ==========================================
  DEBUG_MODE: true,

  // BỔ SUNG THUỘC TÍNH MÚI GIỜ CHUẨN (Khắc phục dứt điểm lỗi Invalid argument: timeZone)
  TIMEZONE: 'Asia/Ho_Chi_Minh',

  // 1. CẤU HÌNH ID TRỰC TIẾP
  ID_MASTER: '1v4gg-9FcB2bxPa1w6gWVYkjlIFumcwacadUiuc77I1Y',
  ID_OPERATION: '1GLmBtMQ7uqZPgYuyMhHo1AYx1GWkraC3ebt0WgKn44c',
  ID_STORAGES: '1fiPuD9FkNE_cYVvtfiUsg3KHBz5zX-L6',

  // Khóa lưu trong ScriptProperties (khắc phục dứt điểm lỗi Cannot read properties of undefined reading ID_MASTER)
  PROPERTY_KEYS: {
    ID_MASTER: 'NAPACO_ID_MASTER',
    ID_OPERATION: 'NAPACO_ID_OPERATION',
    ID_STORAGES: 'NAPACO_ID_STORAGES'
  },

  // 2. TÊN CÁC SHEET
  SHEET_NAMES: {
    SETTINGS: '00.Config',
    CUSTOMERS: '01_KHACH_HANG',
    PRODUCTS: '02_SAN_PHAM',
    EMPLOYEES: '07.NhanVien',
    PERMISSIONS: '08.MaTranQuyen',
    FILM_PO: 'DAT_NHUA_PO',
    FILM_LINES: 'DAT_NHUA',
    FILM_MATERIALS: '04_ThongSoVatLieu',
    FILM_MATERIALS_LEGACY: '01_04_ThongSoVatLieu',
    FILM_SUPPLIERS: '03.DM_NhaCungCap',
    FILM_SUPPLIERS_LEGACY: '01_03_DM_NhaCungCap',
    FILM_RECEIPTS: 'KHO-FM-01A_NHAP_NVL',
    FILM_MOVEMENTS: 'KHO-FM-01B_CAPTRA',
    FORMING_LOG: '05.NHAT_KY_HUT',
    ORDERS: '01.DonHang',
    ORDER_DETAILS: '02.ChiTietDH',
    ORDER_WORKSPACE: 'TAO DON',
    CACHE_CATALOG: '_CACHE_DANH_MUC',
    /* [MỚI - SPEC-ERP-LINEITEM-202611-01] Khai báo sheet Công cụ / Khuôn */
    TOOLS: '05.Cong_Cu'
  },

  // BỔ SUNG KHỐI TRẠNG THÁI VÒNG ĐỜI (Khắc phục dứt điểm lỗi reading 'NEW')
  ORDER_STATUS: {
    NEW: 'Mới',
    IN_PRODUCTION: 'Đang sản xuất',
    COMPLETED: 'Hoàn tất',
    CANCELLED: 'Hủy'
  },

  LINE_STATUS: {
    NEW: 'Chờ sản xuất',
    MOLDING: 'Đang làm khuôn',
    IN_PRODUCTION: 'Đang sản xuất',
    COMPLETED: 'Xong',
    CLOSED: 'Kết thúc'
  },

  /* [MỚI - RÀ SOÁT HARDCODE] Định nghĩa tập trung Phòng ban, Trạng thái nhân sự, Trạng thái khuôn & Phân nhóm */
  DEPARTMENTS: {
    SALES: 'Kinh doanh',
    PLANNING: 'Kế hoạch',
    ACCOUNTING: 'Kế toán',
    TECHNICAL: 'Kỹ thuật'
  },

  EMPLOYEE_STATUS: {
    ACTIVE: 'Đang hoạt động',
    LOCKED: 'Tạm khóa'
  },

  MOLD_STATUS: {
    BROKEN: 'Hong',
    NORMAL: 'Bình thường'
  },

  MOLD_TYPES: {
    FORMING: 'KhuonDinhHinh',
    CUTTING: 'KhuonDao'
  },

  /* [MỚI - SPEC-LINE-DND-01] Định nghĩa tập trung danh mục Vùng hiển thị Kanban */
  KANBAN_ZONES: {
    IN_PRODUCTION: 'DANG_SAN_XUAT',
    PRIORITY: 'UU_TIEN',
    PENDING: 'CHO_SAN_XUAT'
  },

  FILTER_STATUS_GROUPS: {  
    ACTIVE_ALL: 'ACTIVE_ALL', // Nhóm Đang chạy (Chờ sản xuất + Đang sản xuất + Đang làm khuôn)  
    DONE_ALL: 'DONE_ALL', // Nhóm Đã xong (Xong + Kết thúc)  
    ALL: 'ALL' // Tất cả mọi trạng thái  
  },

  /* [MỚI - Ý 5] Cấu hình số lượng bản ghi hiển thị tối đa */
  MAX_DISPLAY_RECORDS: 100,
  MAX_FILE_SIZE_BYTES: 15 * 1024 * 1024,

  // 3. ĐỊNH NGHĨA TẬP TRUNG TÊN CỘT GIAO DIỆN 'TAO DON' (DÒNG 7)
  FORM_COLUMNS: {
    HEADER_ROW: 7,
    DATA_START_ROW: 8,
    ALIASES: {
      CUSTOMER: ['1. Khách Hàng (Bắt buộc)', '1. Khách Hàng', 'Khách Hàng', 'Tên Khách Hàng', 'Khach Hang'],
      PRODUCT:  ['2. Sản Phẩm (Bắt buộc)', '2. Sản Phẩm', 'Sản Phẩm', 'Tên Sản Phẩm', 'San Pham'],
      CODE:     ['3. Code SP', 'Code SP', 'Code Sản Phẩm', 'Mã SP'],
      UNIT:     ['4. Đơn Vị', 'Đơn Vị', 'ĐVT', 'DVT'],
      PRICE:    ['5. Đơn Giá (₫)', 'Đơn Giá (₫)', 'Đơn Giá', 'Giá Bán', 'Giá'],
      QTY:      ['6. Số Lượng', 'Số Lượng', 'SL'],
      PO:       ['7. Số PO', 'Số PO', 'PO', 'So_PO'],
      NOTE:     ['8. Ghi Chú Đơn Hàng', '8. Ghi Chú', 'Ghi Chú Đơn Hàng', 'Ghi Chú', 'Ghi chu'],
      LINK_PO:  ['9. Link File PO (Drive)', '9. Link PO', 'Link File PO', 'Link PO', 'Link']
    }
  },

// ========================================================
  // NƠI DUY NHẤT ĐỊNH NGHĨA TÊN CỘT DATABASE (SINGLE SOURCE OF TRUTH)
  // Toàn bộ logic Backend/Frontend chỉ gọi qua CONFIG.COLUMNS
  // ========================================================
  COLUMNS: {
    SETTINGS: {
      UNITS: 'Danh sách ĐVT', FILM_COLORS: 'DM_MAU_SAC', RESINS: 'Loại nhựa', GRADES: 'Cấp độ',
      DENSITY_RESIN: 'DM_TY_TRONG_NHUA', DENSITY: 'Ty_Trong'
    },
    FILM_PO: {
      ID: 'PO_NVL_ID', DATE: 'Ngay_Dat', SUPPLIER: 'Ma_NCC', USER: 'Nguoi_Dat',
      NOTE: 'Ghi_Chu', STATUS: 'Trang_Thai'
    },
    FILM_LINES: {
      ID: 'DN_ID', RESIN: 'Loai_Nhua', MATERIAL_ID: 'VL_ID', QTY: 'So_Luong',
      PRICE: 'Don_Gia', NOTE: 'Ghi_Chu', STATUS: 'Trang_Thai',
      PO_ID: 'PO_NVL_ID', DELIVERY: 'Ngay_Giao_Du_Kien', DATE: 'Ngay_Dat', SUPPLIER: 'Ma_NCC'
    },
    FILM_MATERIALS: {
      ID: 'VL_ID', GRADE: 'Cấp Độ', COLOR: 'Màu Sắc', ESD: 'Tĩnh Điện',
      THICKNESS: 'Độ Dày', WIDTH: 'Khổ Nhựa'
    },
    FILM_SUPPLIERS: { ID: 'Ma_NCC', NAME: 'Ten_NCC', TYPE: 'Loai_Cung_Cap' },
    FILM_MOVEMENTS: {
      ID: 'MV_NVL_ID', DATE: 'Ngay_Gio', TYPE: 'Loai_GD', ORDER_ID: 'ID_Lenh_SX',
      RECEIPT_ID: 'N_NVL_ID', QC_ID: 'QC_ID', QTY: 'So_KG',
      ISSUER: 'Nguoi_Cap', RECEIVER: 'Nguoi_Nhan', NOTE: 'Ghi_Chu'
    },
    FORMING_LOG: { MOVEMENT_ID: 'MV_NVL_ID', WEIGHT: 'Trong_Luong_bia',
      GOOD: 'SL_Bia_Thuc_Te_Dat', NG: 'SL_NG_Trong_Ca' },
    FILM_RECEIPTS: {
      ID: 'N_NVL_ID', DATE: 'Ngay_Nhan', PRODUCTION_DATE: 'Ngay_San_Xuat', LINE_ID: 'DN_ID',
      ROLLS: 'So_Cuon_Nhan', QTY: 'So_KG_Nhan', LOCATION: 'Vi_Tri', STATUS: 'Trang_Thai',
      USER: 'Nguoi_Nhap', IQC_ID: 'IQC_QC_ID', NOTE: 'Ghi_Chu'
    },
    // Bảng 01_KHACH_HANG
    CUSTOMERS: {
      ID: 'Ma_KH',
      NAME: 'name',
      ADDRESS: 'address',
      CONTACTER: 'contacter',
      PHONE: 'phone'
    },
    // Bảng 02_SAN_PHAM
    PRODUCTS: {
      ID: 'SP_ID',
      CUSTOMER_ID: 'customer_id',
      FILM: 'mang',
      TYPE: 'type',
      CODE_CUST: 'Code_Sanpham',
      NAME: 'name_napaco',
      CAVITY: 'cavity',
      STOCK: 'tonkho',
      UNIT: 'donvi',
      LENGTH: 'dai',
      WIDTH: 'rong',
      HEIGHT: 'cao',
      IMAGE: 'imageURL',
      PACKING: 'donggoi',
      MOLD_PRICE: 'Gia Khuon',
      PRICE: 'dongia'
    },
    // Bảng 07.NhanVien
    EMPLOYEES: {
      ID: 'Ma_NV',
      NAME: 'name',
      DEPARTMENT: 'phong_ban',
      ROLE: 'role',
      EMAIL: 'email',
      PHONE: 'sdt',
      ACCESS: 'quyen_truy_cap',
      STATUS: 'trang_thai'
    },
    // Bảng 01.DonHang
    ORDERS: {
      ID: 'Ma_DH',
      CUSTOMER_ID: 'MaKH',
      ORDER_DATE: 'NgayDat',
      DELIVERY_DATE: 'NgayGiaoDK',
      PO_NUMBER: 'So_PO',
      FILE_URL: 'File_PO'
    },
    // Bảng 02.ChiTietDH
    ORDER_DETAILS: {
      ID: 'ID_Chi_Tiet',
      FILM_LINE_ID: 'DN_ID',
      ORDER_ID: 'ID_DonHang',
      PRODUCT_ID: 'Ma_SP',
      QTY_ORDER: 'So_Luong_Dat',
      PRICE: 'Don_Gia',
      QTY_RUN: 'So_Luong_Da_Chay',
      QTY_DELIVERED: 'SL_Da_Giao',
      QTY_REMAINING: 'SL_Con_Lai',
      NOTE: 'Ghi_Chu',
      DELIVERY_DATE: 'Ngay_Giao',
      STAFF_ID: 'Ma_NV',
      STATUS: 'Trang_Thai',
      /* [MỚI - VẤN ĐỀ 4] Bổ sung ánh xạ cột đơn vị tính nếu bảng chi tiết có lưu hoặc đồng bộ Master */
      UNIT: 'dvt',
/* [MỚI - SPEC-LINE-DND-01] Khai báo tập trung 2 cột Phân vùng & Thứ tự ưu tiên */
      KANBAN_ZONE: 'Vung_Hien_Thi',
      PRIORITY_ORDER: 'Thu_Tu_Uu_Tien'
    },

    /* [MỚI - SPEC-ERP-LINEITEM-202611-01] Định nghĩa cột bảng Công cụ / Khuôn và danh sách quyền */
    TOOLS: {
      SP_ID: 'MaSP',
      TOOL_TYPE: 'LoaiCC',
      MOLD_CODE: 'Ma_Khuon',
      LENGTH: 'Dai_Khuon', WIDTH: 'Rong_Khuon', CAVITY: 'Cavity',
      /* [MỚI - Ý 4] Bổ sung ánh xạ cột trạng thái khuôn */
      STATUS: 'Trang_Thai'
    }
  },

  EMPLOYEE_HEADER_ALIASES: {
    ID: ['mã nv'], NAME: ['họ và tên', 'tên nv'],
    DEPARTMENT: ['phòng ban'], STATUS: ['trạng thái']
  },

  // Danh mục mã dùng ở cột Ma_Chuc_Nang của 08.MaTranQuyen.
  // Quyền của từng vai trò được cấu hình trong MASTER.
  PERMISSIONS: Object.freeze({
    ORDER_CREATE: 'ORDER_CREATE', // Lưu phiếu tạo đơn hàng
    ORDER_EDIT: 'ORDER_EDIT', // Lưu chỉnh sửa thông tin đơn hàng và chi tiết từ danh sách
    FILM_PO_VIEW: 'FILM_PO_VIEW',
    FILM_PO_CREATE: 'FILM_PO_CREATE',
    FILM_PO_EDIT: 'FILM_PO_EDIT',
    FILM_PO_ASSIGN: 'FILM_PO_ASSIGN',
    FILM_PO_CANCEL: 'FILM_PO_CANCEL', // Chưa có luồng hủy PO màng
    NVL_RECEIVE: 'NVL_RECEIVE',
    NVL_STOCK_VIEW: 'NVL_STOCK_VIEW',
    PRODUCTION_EDIT: 'PRODUCTION_EDIT' // Chưa áp dụng vào thao tác sản xuất
  }),

  DEFAULT_DELIVERY_DAYS: 10,
  DEFAULT_STATUS_DETAIL: 'Chờ sản xuất',
  ORDER_CODE_PREFIX: 'PO-'
};

// ========================================================
// ĐỊNH NGHĨA DANH SÁCH TRẠNG THÁI THEO NHÓM BỘ LỌC (SINGLE SOURCE OF TRUTH)
// Tham chiếu trực tiếp từ CONFIG.LINE_STATUS & CONFIG.ORDER_STATUS - Không hardcode chuỗi rời rạc
// ========================================================
CONFIG.FILTER_STATUS_GROUPS_LIST = {
  ACTIVE_ALL: [
    CONFIG.LINE_STATUS.NEW,           // 'Chờ sản xuất'
    CONFIG.LINE_STATUS.MOLDING,       // 'Đang làm khuôn'
    CONFIG.LINE_STATUS.IN_PRODUCTION  // 'Đang sản xuất'
  ],
  DONE_ALL: [
    CONFIG.LINE_STATUS.COMPLETED,     // 'Xong'
    CONFIG.LINE_STATUS.CLOSED,        // 'Kết thúc'
    CONFIG.ORDER_STATUS.CANCELLED     // 'Hủy'
  ]
};

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
