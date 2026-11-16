# Định mức và kế hoạch định hình — nghiệp vụ đã chốt

- Giữ máy trong định mức; một định mức được có nhiều sản phẩm và nhiều khuôn. Không cần migration 017; migration đang đề xuất trước đó đã bỏ.
- Mã mới tự sinh DM_yymmdd_xx. Lưu setting tạo phiên bản; các phiên bản cũ và snapshot LSX/nhật ký giữ nguyên. Lưu là xác nhận sử dụng, không cần hai checkbox áp dụng/duyệt.
- Tên gợi ý: PET-500x600-15(chuky); cấu hình ghép thêm Ghep_Khuon_. Được đặt tên riêng hoặc bấm Dùng tên gợi ý.
- Một khuôn: khổ màng = khổ khuôn + 40 mm; kéo màng = dài khuôn + 60 mm. Nhiều khuôn: gợi ý ghép ngang với tổng khổ + 40 và dài lớn nhất + 60; người dùng được sửa cho bố trí thực tế.
- Khổ sử dụng phải khớp mã NVL đã chọn để tránh tính thiếu kg/bìa; nếu không khớp, chọn đúng mã NVL hoặc sửa khổ. Không sửa danh mục NVL ngầm.
- Tỷ trọng lấy từ danh mục loại nhựa–tỷ trọng hiện có. Nếu mã NVL có nhiều khả năng loại nhựa, người dùng chọn; không suy loại nhựa từ cấp độ NS/A/B.
- Chọn định mức trên kế hoạch rồi sửa tốc độ, setup, khổ/kéo hoặc cavity chỉ lưu thông số lần chạy. API kế hoạch không tạo hoặc sửa định mức. Muốn lưu định mức phải mở Thiết lập định mức.
- Định hình quản lý số cái/chiếc theo cavity. Đơn vị Tấm/mét của dữ liệu sản phẩm thuộc công đoạn bế không được dùng để chặn CTĐH định hình có đơn vị Cái/Chiếc. Không đổi dữ liệu master hay quy đổi số lượng lịch sử.
- Thiếu NVL chỉ cảnh báo khi xếp kế hoạch/Gantt. Khi chạy thực tế vẫn kiểm tra nguồn ký nhận, mẫu QC và nhật ký như hiện có.

Chưa chạy test nghiệp vụ cho thay đổi này.
