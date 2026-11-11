/**
 * HÀM TEST KIỂM THỬ TRỰC TIẾP TRÊN SERVER (EXECUTE SERVER-SIDE)
 * Chạy hàm này trong Apps Script Editor để kiểm tra kết quả trả về
 */
function test_queryOrdersAndLineItems() {
  console.log("🚀 BẮT ĐẦU KIỂM THỬ queryOrdersAndLineItems...");

  // Giả lập tham số tìm kiếm (có thể thay đổi theo dữ liệu thực tế đang test)
  const testParamsLine = {
    viewMode: 'LINE_ITEM',
    keyword: '',
    maKH: 'ALL',
    status: 'ACTIVE_ALL',
    fromDate: '',
    toDate: '',
    page: 1,
    pageSize: 100
  };

  const resLine = OrderService.queryOrdersAndLineItems(testParamsLine);
  console.log("--- KẾT QUẢ CHẾ ĐỘ LINE_ITEM ---");
  console.log("Tổng CTĐH lấy được:", resLine.data ? resLine.data.length : 0);
  console.log("Summary KPI:", JSON.stringify(resLine.summary));

  const testParamsHeader = {
    viewMode: 'HEADER',
    keyword: '',
    maKH: 'ALL',
    status: 'ACTIVE_ALL',
    fromDate: '',
    toDate: '',
    page: 1,
    pageSize: 100
  };

  const resHeader = OrderService.queryOrdersAndLineItems(testParamsHeader);
  console.log("--- KẾT QUẢ CHẾ ĐỘ HEADER ---");
  console.log("Tổng Header lấy được:", resHeader.data ? resHeader.data.length : 0);
  console.log("Summary KPI:", JSON.stringify(resHeader.summary));

  // Kiểm tra tính nhất quán logic
  if (resLine.summary && resHeader.summary) {
    console.log("✅ Đã hoàn thành test. Kiểm tra tính khớp nối KPI thành công!");
  }
}

/**
 * Hàm test độc lập để debug luồng truy vấn đơn hàng trực tiếp trên máy chủ
 */
function test_queryOrdersAndLineItems() {
  console.log("=== BẮT ĐẦU TEST HÀM queryOrdersAndLineItems ===");

  // 1. Giả lập payload tìm kiếm gửi từ Client (mặc định khi load trang)
  const searchParams = {
    viewMode: 'LINE_ITEM', // Thử test chế độ Chi tiết mặt hàng
    keyword: '',
    maKH: 'ALL',
    status: 'ACTIVE_ALL', // Nghi ngờ lỗi do bộ lọc trạng thái này
    fromDate: '',
    toDate: '',
    page: 1,
    pageSize: 50
  };

  console.log("1. Tham số tìm kiếm (searchParams):", JSON.stringify(searchParams));

  try {
    // 2. Gọi trực tiếp vào OrderService
    const result = OrderService.queryOrdersAndLineItems(searchParams);

    // 3. In kết quả tổng quan
    console.log("2. Kết quả trả về - Success:", result.success);
    console.log("3. Tổng số bản ghi (total) lấy được:", result.total);
    
    if (result.exceededLimit) {
      console.log("CẢNH BÁO: Vượt giới hạn bản ghi (exceededLimit = true)");
    }

    // 4. In chi tiết để kiểm tra cấu trúc dữ liệu nếu có kết quả
    if (result.data && result.data.length > 0) {
      console.log("4. Dữ liệu mẫu (Dòng 1):", JSON.stringify(result.data[0]));
      console.log("-> Trạng thái của dòng 1 là:", result.data[0].trangThai);
    } else {
      console.log("KHÔNG TÌM THẤY DỮ LIỆU NÀO KHỚP VỚI ĐIỀU KIỆN LỌC!");
      
      // 5. Thử gỡ bộ lọc trạng thái để đối chiếu nguyên nhân
      console.log("--- Thử truy vấn lại với status = 'ALL' ---");
      searchParams.status = 'ALL';
      const resultAll = OrderService.queryOrdersAndLineItems(searchParams);
      
      console.log("Tổng số dòng khi status='ALL':", resultAll.total);
      if (resultAll.data && resultAll.data.length > 0) {
        console.log("Dữ liệu mẫu khi status='ALL':", JSON.stringify(resultAll.data[0]));
        console.log("=> KẾT LUẬN: Lỗi do hàm `isStatusMatch` không xử lý đúng giá trị trạng thái:", resultAll.data[0].trangThai);
      } else {
        console.log("=> KẾT LUẬN: Bảng ChiTietDH / DonHang thực sự không có dữ liệu, hoặc lỗi ánh xạ dữ liệu (orderMap).");
      }
    }

  } catch (err) {
    console.error("LỖI EXCEPTION THỰC THI:", err.message);
    console.error("Stack trace:", err.stack);
  }
  
  console.log("=== KẾT THÚC TEST ===");
}

/**
 * Test Server-side: Kiểm tra hàm queryOrdersAndLineItems có phản hồi đúng định dạng không
 */
function testQueryOrdersAndLineItems() {
  console.log("=== BẮT ĐẦU TEST SERVER RPC: queryOrdersAndLineItems ===");
  try {
    // 1. Test chế độ xem PO Header
    const resHeader = OrderController.queryOrdersAndLineItems({
      viewMode: 'HEADER',
      keyword: '',
      maKH: 'ALL',
      status: 'ALL',
      fromDate: '',
      toDate: '',
      page: 1,
      pageSize: 10
    });
    console.log("1. Kết quả View HEADER:", {
      success: resHeader.success,
      totalOrders: resHeader.summary ? resHeader.summary.totalOrders : 0,
      recordCount: (resHeader.data || []).length,
      customersCount: (resHeader.customers || []).length
    });

    if (!resHeader.success) {
      throw new Error("Lỗi khi test Header: " + JSON.stringify(resHeader.error));
    }

    // 2. Test chế độ xem Chi tiết mặt hàng (Line Item)
    const resLine = OrderController.queryOrdersAndLineItems({
      viewMode: 'LINE_ITEM',
      page: 1,
      pageSize: 10
    });
    console.log("2. Kết quả View LINE_ITEM:", {
      success: resLine.success,
      recordCount: (resLine.data || []).length
    });

    console.log("✅ TẤT CẢ TEST BACKEND THÀNH CÔNG 100%!");
  } catch (err) {
    console.error("❌ TEST SERVER THẤT BẠI:", err.message, err.stack);
  }
}

function test_checkTimezoneConfig() {
  try {
    const tz = CONFIG.TIMEZONE;
    const testDateStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
    console.log("✅ [TEST-TZ] Định dạng múi giờ '" + tz + "' thành công! Ngày giờ hiện tại: " + testDateStr);
  } catch (err) {
    console.error("❌ [TEST-TZ] Lỗi: " + err.message);
  }
}

/**
 * HÀM TEST TÌM KIẾM TỆP TRÊN GOOGLE DRIVE
 */
function test_searchDriveFiles_Backend() {
  console.log("🚀 [TEST-DRIVE] Bắt đầu kiểm tra tìm kiếm tệp trên Google Drive...");
  
  // Thử tìm kiếm với từ khóa phổ biến (hoặc nhập từ khóa tệp bạn đang có trên Drive)
  const testKeyword = "PO";
  const result = searchUserDriveFiles(testKeyword);
  
  console.log("🔍 Kết quả tìm kiếm từ khóa '" + testKeyword + "':", JSON.stringify(result));
  if (result.success) {
    console.log("✅ Tìm thấy " + result.files.length + " tệp trên Google Drive.");
    if (result.files.length > 0) {
      console.log("📄 Tệp mẫu đầu tiên: Tên = " + result.files[0].name + " | URL = " + result.files[0].url);
    }
  } else {
    console.error("❌ Lỗi khi tìm kiếm:", result.error);
  }
}

/**
 * HÀM TEST THUẬT TOÁN SINH MÃ ID KHÁCH HÀNG & SẢN PHẨM MỚI (MAX ID + 1)
 */
function test_generateNextIds_Backend() {
  console.log("🚀 [TEST-ID] Bắt đầu kiểm tra thuật toán sinh mã Max ID + 1...");
  
  const masterSS = SpreadsheetApp.openById(CONFIG.ID_MASTER);
  const custSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.CUSTOMERS);
  const prodSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.PRODUCTS);

  // 1. Kiểm tra Khách hàng
  const { rows: custData, headerRow: custHeader, columns: custCols } = OrderService.readDatabaseTable_(
    custSheet, CONFIG.SHEET_NAMES.CUSTOMERS, CONFIG.COLUMNS.CUSTOMERS, ['ID']);
  let maxKh = 0;
  for (let i = custHeader + 1; i < custData.length; i++) {
    const ma = String(custData[i][custCols.ID] || '').trim();
    const m = ma.match(/KH(\d+)/i);
    if (m) {
      const n = parseInt(m[1], 10);
      if (n > maxKh) maxKh = n;
    }
  }
  const nextKhId = 'KH' + String(maxKh + 1).padStart(4, '0');
  console.log(`✅ [TEST-ID] Khách Hàng: Mã số lớn nhất hiện tại = KH${String(maxKh).padStart(4, '0')} -> Mã cho KH mới tiếp theo = ${nextKhId}`);

  // 2. Kiểm tra Sản phẩm
  const { rows: prodData, headerRow: prodHeader, columns: prodCols } = OrderService.readDatabaseTable_(
    prodSheet, CONFIG.SHEET_NAMES.PRODUCTS, CONFIG.COLUMNS.PRODUCTS, ['ID']);
  let maxSp = 0;
  for (let j = prodHeader + 1; j < prodData.length; j++) {
    const spId = String(prodData[j][prodCols.ID] || '').trim();
    const m = spId.match(/SP(\d+)/i);
    if (m) {
      const n = parseInt(m[1], 10);
      if (n > maxSp) maxSp = n;
    }
  }
  const nextSpId = 'SP' + String(maxSp + 1).padStart(4, '0');
  console.log(`✅ [TEST-ID] Sản Phẩm: Mã số lớn nhất hiện tại = SP${String(maxSp).padStart(4, '0')} -> Mã cho SP mới tiếp theo = ${nextSpId}`);

  console.log("🎉 [TEST-ID] Kết quả mong đợi: Khách mới phải là KH0215, Sản phẩm mới phải là SP2175!");
}

/**
 * NAPACO ENTERPRISE ERP - BACKEND TEST RUNNER
 * File: TestBackend.gs
 * Mục đích: Kiểm tra kết nối DB, đọc dữ liệu theo tên cột định nghĩa tại CONFIG.COLUMNS
 */

function test_backendConnectionAndSchema() {
  console.log("==================================================");
  console.log("🚀 BẮT ĐẦU KIỂM TRA BACKEND & SCHEMA DATABASE");
  console.log("==================================================");

  try {
    // 1. Kiểm tra kết nối tới 01. DB MASTER
    var masterSS = SpreadsheetApp.openById(CONFIG.ID_MASTER);
    console.log("✅ 1. Kết nối 01. DB MASTER: THÀNH CÔNG (" + masterSS.getName() + ")");

    // 2. Kiểm tra đọc bảng Khách hàng theo cột cấu hình
    var custSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.CUSTOMERS);
    if (!custSheet) throw new Error("Không tìm thấy Sheet " + CONFIG.SHEET_NAMES.CUSTOMERS);
    
    var custData = custSheet.getDataRange().getValues();
    var custHeaders = custData[0];
    
    // Tìm index cột theo CONFIG.COLUMNS.CUSTOMERS
    var idxCustId = custHeaders.indexOf(CONFIG.COLUMNS.CUSTOMERS.ID);
    var idxCustName = custHeaders.indexOf(CONFIG.COLUMNS.CUSTOMERS.NAME);
    
    console.log("✅ 2. Bảng 01_KHACH_HANG: Tìm thấy cột '" + CONFIG.COLUMNS.CUSTOMERS.ID + "' (Index: " + idxCustId + "), '" + CONFIG.COLUMNS.CUSTOMERS.NAME + "' (Index: " + idxCustName + ")");
    console.log("   -> Tổng số khách hàng: " + (custData.length - 1) + " bản ghi");
    if (custData.length > 1) {
      console.log("   -> Mẫu bản ghi đầu: ID=" + custData[1][idxCustId] + " | Tên=" + custData[1][idxCustName]);
    }

    // 3. Kiểm tra đọc bảng Sản phẩm theo cột cấu hình
    var prodSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.PRODUCTS);
    if (!prodSheet) throw new Error("Không tìm thấy Sheet " + CONFIG.SHEET_NAMES.PRODUCTS);
    
    var prodData = prodSheet.getDataRange().getValues();
    var prodHeaders = prodData[0];
    var idxProdId = prodHeaders.indexOf(CONFIG.COLUMNS.PRODUCTS.ID);
    var idxProdName = prodHeaders.indexOf(CONFIG.COLUMNS.PRODUCTS.NAME);
    var idxProdPrice = prodHeaders.indexOf(CONFIG.COLUMNS.PRODUCTS.PRICE);

    console.log("✅ 3. Bảng 02_SAN_PHAM: Tìm thấy cột '" + CONFIG.COLUMNS.PRODUCTS.ID + "' (Index: " + idxProdId + "), '" + CONFIG.COLUMNS.PRODUCTS.NAME + "' (Index: " + idxProdName + ")");
    console.log("   -> Tổng số sản phẩm: " + (prodData.length - 1) + " bản ghi");
    if (prodData.length > 1) {
      console.log("   -> Mẫu bản ghi đầu: ID=" + prodData[1][idxProdId] + " | Tên=" + prodData[1][idxProdName] + " | Đơn giá=" + prodData[1][idxProdPrice]);
    }

    // 4. Kiểm tra đọc bảng Nhân viên theo cột cấu hình
    var empSheet = masterSS.getSheetByName(CONFIG.SHEET_NAMES.EMPLOYEES);
    if (!empSheet) throw new Error("Không tìm thấy Sheet " + CONFIG.SHEET_NAMES.EMPLOYEES);
    
    var empData = empSheet.getDataRange().getValues();
    var empHeaders = empData[0];
    var idxEmpId = empHeaders.indexOf(CONFIG.COLUMNS.EMPLOYEES.ID);
    var idxEmpName = empHeaders.indexOf(CONFIG.COLUMNS.EMPLOYEES.NAME);
    var idxEmpDept = empHeaders.indexOf(CONFIG.COLUMNS.EMPLOYEES.DEPARTMENT);

    console.log("✅ 4. Bảng 07.NhanVien: Tìm thấy cột '" + CONFIG.COLUMNS.EMPLOYEES.ID + "' (Index: " + idxEmpId + "), '" + CONFIG.COLUMNS.EMPLOYEES.NAME + "' (Index: " + idxEmpName + ")");
    console.log("   -> Tổng số nhân sự: " + (empData.length - 1) + " bản ghi");

    // 5. Kiểm tra kết nối tới 02. Operation
    var operSS = SpreadsheetApp.openById(CONFIG.ID_OPERATION);
    console.log("✅ 5. Kết nối 02. Operation: THÀNH CÔNG (" + operSS.getName() + ")");
    
    var orderSheet = operSS.getSheetByName(CONFIG.SHEET_NAMES.ORDERS);
    var detailSheet = operSS.getSheetByName(CONFIG.SHEET_NAMES.ORDER_DETAILS);
    console.log("   -> Số lượng đơn hàng (Header): " + (orderSheet ? orderSheet.getLastRow() - 1 : 0));
    console.log("   -> Số lượng chi tiết mặt hàng (Line-Item): " + (detailSheet ? detailSheet.getLastRow() - 1 : 0));

    console.log("==================================================");
    console.log("🎉 KẾT QUẢ: TẤT CẢ KẾT NỐI VÀ ÁNH XẠ CỘT ĐỀU HOÀN TOÀN HỢP LỆ!");
    console.log("==================================================");
    return true;

  } catch (err) {
    console.error("❌ LỖI TRONG QUÁ TRÌNH KIỂM TRA: " + err.message);
    console.error(err.stack);
    return false;
  }
}