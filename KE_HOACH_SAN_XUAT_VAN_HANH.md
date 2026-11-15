# Vận hành Kế hoạch sản xuất

Bản local ngày 14/11/2026. Đăng nhập tài khoản có quyền **PRODUCTION_EDIT**, vào **Kế hoạch → Định Hình**. **Bế Dán** vẫn là thông báo chưa triển khai.

## Dữ liệu nền và duyệt định mức

1. Trong Giờ nghỉ mặc định, nạp lịch, nhập một lần giờ làm/nghỉ chung và bấm **Áp dụng vào T2–CN**. Sửa riêng từng thứ rồi Lưu. Máy kế thừa lịch chung; ngày đặc biệt dùng ngoại lệ máy/ngày, ví dụ chạy xuyên nghỉ. Ngoại lệ chỉ có hiệu lực trong phạm vi ngày/máy được lưu.
2. Trong Dữ liệu nền, phân loại máy và trạng thái sử dụng. Định mức dùng khuôn/vật liệu/sản phẩm hiện có, cavity riêng mỗi sản phẩm. Bước kéo mm, tốc độ giây/chu kỳ, 1 chu kỳ = 1 bìa; trọng lượng kg/bìa dùng công thức đặt nhựa chung.
3. **Đang áp dụng** và **đã duyệt** là hai thông tin riêng. Đánh dấu **Tôi duyệt phiên bản này khi lưu** để chốt xác nhận của người có quyền hiện hành. Sửa tạo phiên bản mới; bản mới cần duyệt lại chủ động. Bản cũ không tự trở thành đã duyệt. Không sửa ngược thông số trong phiên bản đã lưu.

## Từ nhựa đến kế hoạch

1. Chuẩn bị nhựa: tìm CTĐH, chọn định mức, nguồn nhập **OK** và kg. Gán là giữ ngay; nguồn chưa nhận chỉ là dự kiến. Phần đã bố trí cho lần chạy không được giải phóng khi chưa sửa/kết thúc bố trí đó.
2. Trên màn hình kế hoạch chọn khoảng sản xuất rồi **Tải chế độ**. Bộ lọc không query liên tục khi gõ. Chọn CTĐH chờ xếp, tạo ID lần chạy ổn định, chọn định mức và nguồn đã giữ. Ghép nhiều CTĐH cần người lập kế hoạch xác nhận; cavity tính theo sản phẩm, không cộng theo số CTĐH.
3. Trong editor, chọn công đoạn và **Tìm lịch sử phù hợp**. Xem riêng định mức đã duyệt, định mức đang áp dụng, lần phù hợp gần nhất, trung vị/dao động/số mẫu và nguồn nhật ký. Mẫu gần giống khác máy/bước kéo tách riêng; ít hơn 3 lần chạy đã kết thúc không có nút áp dụng thống kê mặc định. Chọn áp dụng vào nháp hoặc tự nhập. Thay cấu hình sau khi tìm phải tìm lại/bỏ nguồn để nhập thủ công.
4. Với Cắt/Ép biên, chọn máy hoặc để ước tính, nhập đúng đơn vị năng suất, setup, chờ hàng và chờ toàn bộ/cuốn chiếu. Cuốn chiếu cần lượng đều hoặc danh sách lượng từng lần. Sản phẩm không cần ép biên không bị ép vào tuyến ép biên của sản phẩm khác trong nhóm.
5. **Tính thử**, đọc cảnh báo và xác nhận trước khi **Lưu**. Không kéo phần đã thực hiện. Backend kiểm tra lại nguồn, sản lượng, lịch, version và hash; gặp xung đột phải tải lại/tính thử lại, không gửi lại dữ liệu cũ với version tự tăng.
6. Chuyển máy chỉ áp dụng lần chưa chạy; xác nhận thay bố trí cũ. Lần đã chạy phải chốt ca, kết thúc cấu hình và lập ID mới cho phần thiếu. Nhóm có một sản phẩm đủ thì kết thúc cấu hình ghép, lập cấu hình phù hợp cho phần còn lại.
7. Dừng biết thời lượng sẽ tính lại lịch. Dừng chưa biết và giữ máy làm các giờ phía sau chưa xác định. Giải phóng máy đưa phần còn lại về chờ xếp. Muốn chạy lại phải xử lý dừng và lưu bố trí mới; không tự coi dừng đã kết thúc.

## Nhật ký và cân đối nhựa

- Bắt đầu lần chạy, cấp từ phân bổ đúng CTĐH/nguồn. Cấp làm giảm giữ và giảm tồn đúng một lần. Không suy rằng toàn bộ kg đã cấp vẫn còn tại máy.
- Nhập ngày giờ **sản xuất** có múi giờ. Nhật ký hiện có độ chính xác giây: khoảng ca/công đoạn ít nhất 1 giây; backend chuẩn hóa trước lưu để tránh MySQL làm tròn sang giây kế tiếp.
- Chốt đủ CTĐH trong lần chạy và đủ nguồn: **đầu + cấp thêm − trả/chuyển ra − tiêu hao = cuối**. Nhập tiêu hao hoặc cuối ca; nhập cả hai phải khớp. Ca sau mang số dư từng N_NVL_ID, không gộp nguồn.
- **Chạy thuần đã đo** và **Setup đã đo** là tùy chọn, bỏ trống nếu chưa biết. Không điền cả khoảng ca vào chạy thuần khi có nghỉ/chờ. Tổng setup + chạy thuần không vượt khoảng sản xuất. Dữ liệu không đủ/không cân đối không được thay bằng tốc độ danh nghĩa để tạo mẫu.
- Kết thúc ca không kết thúc lần chạy. Chỉ sửa ca cuối còn đủ điều kiện; ca đã có ca sau hoặc được công đoạn sau sử dụng phải đối soát, không sửa ngược chuỗi số dư.
- Trả chờ kho nhận tách khỏi nhựa tại máy, chưa tăng tồn kho; xác nhận kho nhận mới tăng tồn. Chuyển nguồn giữ nguyên N_NVL_ID và liên kết cấp/trả. Trả/chuyển phát sinh sau ca phải được chốt vào ca cân đối trước khi kết thúc lần chạy.
- Cắt/Ép biên chọn **ID nhật ký hút**, không dùng ID đơn hàng thay DH_ID. Cùng nguồn được xử lý nhiều lần trong giới hạn sản lượng còn lại. Nhiều CTĐH cùng lô ghi chung một nhật ký; không tạo các nhật ký chồng giờ trên cùng máy.

## Chốt ngày và đối chiếu

- Lưu bản cập nhật chụp **toàn bộ phạm vi đang lập, cả ngày tương lai**. Lưu tiếp thay con trỏ cập nhật nguyên tử; các snapshot đã lưu giữ nguyên.
- **Chốt bản đầu ngày** là thao tác chủ động một lần trong ngày Việt Nam hiện tại. Bản đã chốt không bị thay khi chỉnh lịch, định mức hoặc nhập nhật ký muộn.
- Sang ngày mới đọc bản cập nhật gần nhất thành nháp; chưa tự ghi/chốt. Có thể chốt nháp có snapshot đầy đủ hoặc tính thử/lưu trước.
- Chọn **ngày chốt** riêng với **khoảng sản xuất**. Điều hành xem bản cập nhật; so sánh xem đầu ngày với thực tế hoặc với cập nhật. Cả hai khung Theo máy/Theo CTĐH dùng cùng dữ liệu backend.
- Chưa có nhật ký hiện **Chưa có dữ liệu**; không suy khoảng trống là máy nghỉ. Chạy thuần chỉ so khi đủ số đo và phạm vi. Timestamp audit cập nhật thực tế tách khỏi lúc tải dữ liệu. Bản chụp ngoài khoảng xem được ghi rõ, không coi là chưa từng lập kế hoạch.

## Xem bộ dữ liệu DEMO7 được giữ lại

- Mở khoảng **10/11/2026–18/11/2026**, ngày chốt **14/11/2026**. Tải lại sau mỗi thay đổi bộ lọc.
- Máy: `DEMO7-DH-A`, `DEMO7-DH-B`, `DEMO7-AUTO`, `DEMO7-EDGE`; công đoạn Cắt dùng máy có sẵn `BC-01`.
- CTĐH: `CT_261101_14` / `SP0006` và `CT_261106_08` / `SP0002`. Dùng nguồn nhận có sẵn `N_NVL_261110_01`, `N_NVL_261110_06`, vật liệu `VL0001`, khuôn nguồn `CC0001`. Khả năng chạy các sản phẩm trên cấu hình DEMO7 là giả định phục vụ kiểm tra, không phải định mức sản xuất đã được xưởng xác minh.
- `DEMO7-H1/H2/H3`: lịch sử chạy lẻ với số đo thuần, setup, tiêu hao; `DEMO7-G1`: ghép qua hai ngày/ca, hai nguồn, một sản phẩm đủ trước; `DEMO7-TAIL`: phần chạy lẻ còn thiếu, đang giải phóng máy/chờ xếp.
- `DEMO7-U1`: có trong bản đầu ngày, chuyển máy có xác nhận, nhập nhật ký muộn rồi kết thúc; `DEMO7-U1-CONT`: phần thiếu tiếp nối; `DEMO7-U2`: kế hoạch còn chờ; `DEMO7-AUTO-RUN`: máy tự động, dừng chưa rõ và giữ máy, phần sau bôi xám.
- `DEMO7-STOCK-SRC/DST`: cấp–trả–chuyển và chốt tồn đúng nguồn; `DEMO7-RACE-SHIFT`: cấp đồng thời với chốt ca, version cũ bị từ chối và thử lại an toàn.
- Định mức DEMO7 có lịch sử phiên bản: bản đầu thử dữ liệu bị phát hiện khác đơn vị không được dùng cho lần chạy; bản 2 dùng dữ liệu hợp lệ; bản mới được duyệt chủ động cho người dùng xem nguồn đã duyệt. Không tự sửa master để hợp thức hóa dữ liệu thử.
- Dữ liệu thử làm thay đổi tồn khả dụng và sản lượng đã sản xuất của hai CTĐH **trên local**. Không xóa lại sau test. Không chạy các script tạo mẫu trên production.

Xem [bàn giao kỹ thuật](./KE_HOACH_SAN_XUAT_HANDOFF.md) và [báo cáo kiểm thử MySQL/dữ liệu mẫu](./reports/production-phase7-demo.json). Các cảnh báo deprecation của thư viện trong pytest không phải kết quả kiểm thử browser. UI sau đăng nhập cần người dùng nghiệm thu trực tiếp.
