# Kiểm tra một luồng: lập kế hoạch → chạy máy → ghi nhật ký

Cập nhật 15/11/2026. Tạm dừng mở rộng và kiểm thử thêm theo yêu cầu. Chương trình local: http://localhost:8000.

## Dữ liệu đang có để kiểm tra

| Nội dung | Giá trị |
|---|---|
| Đơn A | PO `THUC-HANH-A-1511`, CTĐH `CT_261115_01`, đặt 200 cái |
| Đơn B | PO `THUC-HANH-B-1511`, CTĐH `CT_261115_02`, đặt 100 cái |
| LSX dùng chung | `LSX_261115_001` |
| Kế hoạch đầu tiên v1 | A 200 + B 100 chạy ghép trên `DH-01`, dự kiến 08:00 ngày 15/11 |
| Nhật ký thứ nhất | Ngày 15/11, `DH-01`, A tốt 100 + B tốt 100; 40 bìa chung; mẫu `QC_261115_10` |
| Kế hoạch cập nhật v3 | B đã đủ nên bỏ khỏi thành phần còn chạy; A tiếp trên `DH-02` ngày 16/11, giữ cùng LSX |
| Nhật ký thứ hai | Ngày mô phỏng 16/11, `DH-02`, A tốt 100; 20 bìa; mẫu mới `QC_261115_12` |
| Tổng đã ghi | A 200/200; B 100/100; cùng LSX có hai nhật ký và hai máy lịch sử |

**A/B đã ghi đủ sản lượng, vì vậy hiện không còn trong danh sách công việc được ghi mới. Không nhập lại các số dưới đây vào dữ liệu này.** Bảng thao tác là trình tự vận hành đã dùng; bảng kiểm tra cuối tài liệu là cách xem dữ liệu đã lưu ngay bây giờ.

Đây là dữ liệu thực hành. Chữ ký cấp/nhận và kỹ thuật/QC được mô phỏng bằng hai người giả có nhãn `[GIẢ LOCAL A/B]`, không phải xác thực Google thật. Template QC và thư mục lưu là fixture local dùng chung cơ chế QC; chưa kiểm chứng chọn file/thư mục hoặc xuất phiếu Drive thật. Nhật ký ngày 16/11 được nhập qua UI của tiến trình local có đồng hồ nghiệp vụ mô phỏng +1 ngày; tiến trình đó đã dừng. App chính cổng 8000 giữ đồng hồ thật. Số lượng, tiêu hao và khoảng chạy là số giả phục vụ thao tác, không phải thực tế sản xuất hoặc định mức đã xác minh.

## Trình tự vận hành một LSX

| Bước | Vào màn hình | Thực hiện lần lượt | Kết quả cần thấy |
|---|---|---|---|
| 1 | **Kế hoạch → Định Hình** | Chọn khoảng ngày giao bao gồm CTĐH cần làm → **Tải phạm vi** → chọn **Đã giữ nhựa** → **Tìm CTĐH**. Ví dụ A/B giao 16/11. | Hiện CTĐH A và B cùng lượng còn phải sản xuất và NVL đã giữ. Khoảng lọc danh sách chờ theo **ngày giao**. |
| 2 | Cùng màn hình | Tích A và B → **Tạo lần chạy / Ghép CTĐH** → **Chọn định mức** → tìm `THUCHANH-AB-PP-1511` → chọn phiên bản 1. | Máy, bước kéo, giây/chu kỳ, kg/bìa và cavity được điền từ định mức. Đây là cấu hình giả cho ví dụ PP 0,6 × 580; không thay thông số master sản phẩm. |
| 3 | Hộp lần chạy | Máy `DH-01`; mã nhóm `THUC-HANH-AB`; tích xác nhận chạy ghép. Sản lượng bố trí A=200, B=100. Nhập kg bố trí: lô A mới 10; B mới 2; lô tồn của B 5. Ghi lý do. Cho phép bắt đầu từ 15/11 08:00. Phần cắt chỉ ước tính trong ví dụ, nhập 2 giây/cái, chưa chọn máy cắt. | Một LSX chứa hai CTĐH; chưa phát hành và chưa được chạy. Sản lượng bố trí là tổng sẽ làm, không phải số thực tế đã làm. |
| 4 | **Định Hình** | **Đưa vào bản nháp** → **Tính thử** → xem kết quả/cảnh báo → **Lưu kế hoạch** → xác nhận các cảnh báo rồi **Xác nhận**. | Kế hoạch được lưu; biểu đồ có phần dự kiến. **Đưa vào bản nháp chưa phải lưu database.** |
| 5 | Cùng màn hình | Nếu cần giữ bản đầu để đối chiếu: **Chốt bản đầu ngày** → ghi chú → **Chốt và giữ nguyên**. | Bản đầu giữ nguyên khi cập nhật kế hoạch sau này. Trong dữ liệu đã tạo, bản này là v1 ngày 15/11. |
| 6 | Bấm thanh LSX trên biểu đồ | **Phát lệnh** → **Xác nhận**. | Có mã chính thức `LSX_261115_001` và liên kết **Phiếu đã phát**. Lưu kế hoạch và phát lệnh là hai thao tác khác nhau. |
| 7 | **Kế hoạch → Chuẩn bị nhựa** | Tìm CTĐH → **Phân bổ / cấp / trả** → ở phần giữ chọn **Lập phiếu cấp từ phần giữ** → nhập kg → **Tìm LSX** → chọn đúng mã → **Lưu**. Trên phiếu, người cấp ký; người nhận đăng nhập bằng tài khoản của mình rồi ký nhận. | Phiếu nháp chưa xuất kho. Ký cấp xuất kho một lần nhưng NVL còn chờ nhận; ký nhận mới được dùng sản xuất. Ví dụ đã có 3 phiếu A/B nhận tổng 17 kg bằng chữ ký mô phỏng. |
| 8 | **Kế hoạch → Kiểm mẫu trước chạy** | Tìm đúng mã LSX → chọn LSX và phân công `DH-01` → nhập thời điểm hết đợt cùng lý do → **Mở đợt · Chạy mẫu mới**. Chọn template QC đã đăng ký → số mẫu/kết quả/kết luận/quyết định → thư mục lưu → lưu phiếu → kỹ thuật và QC ký. | Phiếu Đạt đủ hai xác nhận mới mở chạy. Trong ví dụ dùng mẫu giả `QC_261115_10`; việc lưu nháp/chữ ký và thư mục giả được chuẩn bị bằng fixture, không phải thao tác Drive thật. |
| 9 | **Kế hoạch → Nhật ký định hình** | Chọn máy `DH-01` → **Ghi nhật ký LSX LSX_261115_001**. Kiểm tra phiếu mẫu căn cứ, máy, CTĐH, ngày/giờ và nguồn đã nhận. | Form điền sẵn thông tin có sẵn. Danh sách không bắt buộc chạy đúng giờ/thứ tự dự kiến. Nếu thiếu ký nhận NVL hoặc mẫu, chưa được lưu chạy hàng loạt. |
| 10 | Form nhật ký | Ví dụ đợt đầu: **Bìa tốt thực tế=40**, bìa NG=0; chia **A tốt=100**, **B tốt=100**. Vì hai CTĐH cùng sản phẩm nên nhập rõ phần chia. Giữ chế độ **Kg còn cuối kỳ**: lô tồn `N_NVL_261110_01`=3,6; lô A `N_NVL_261115_01`=6; lô B `N_NVL_261115_02`=1. | Một khoảng thời gian máy chung cho 40 bìa; sản lượng riêng từng CTĐH. Tiêu hao tính lại là 1,4 + 4 + 1 = 6,4 kg từ số kiểm đếm nhập vào. Không lấy tốc độ kế hoạch để suy ra sản lượng thực tế. |
| 11 | Cùng form | Sửa giờ bắt đầu/kết thúc nếu mốc điền sẵn khác thời gian thực tế. Nếu tạm nghỉ rồi tiếp tục cùng đợt, giữ **Tiếp tục / nghỉ trong cùng đợt**. Ví dụ đã chọn **Kết thúc đợt; chạy lại cần mẫu mới** vì dừng để chuyển sang đơn khác. Bấm **Lưu nhật ký**. | Lưu nhật ký, cập nhật lũy kế: A đã100 còn100, B đã100 còn0. Chỉ khi lưu mới ghi sản lượng và cân đối NVL. Đóng đợt không tự kết thúc LSX. |
| 12 | **Định Hình → mở LSX cũ** | Khi A chạy tiếp khác máy: chọn `DH-02`, đặt bắt đầu 16/11 08:00. B đã đủ thì **Bỏ CTĐH** B khỏi thành phần còn chạy; giữ tổng bố trí A=200 vì A đã làm100 và còn100. Giữ các nguồn đã cấp và lý do cập nhật. **Đưa vào bản nháp → Tính thử → Lưu kế hoạch**, xác nhận đổi máy/số dư. Không chọn **Tách CTĐH / Lập phần tiếp theo**. | Vẫn `LSX_261115_001`; B trở thành thành phần cũ có lịch sử. Nhật ký 15/11 vẫn là `DH-01`; kế hoạch tiếp theo gán `DH-02`. |
| 13 | **Kiểm mẫu trước chạy**, rồi **Nhật ký định hình** | Mở đợt mới cho cùng LSX trên `DH-02`, lập/ký mẫu mới. Chọn máy `DH-02`, mở LSX, nhập 20 bìa tốt → A tốt100; lô A cuối kỳ2,8; lô tồn3,6; lô B1 không đổi → kiểm tra giờ → **Lưu nhật ký**. | Nhật ký thứ hai cùng LSX, mẫu mới `QC_261115_12`; A đủ200/B đủ100. Trong lần kiểm tra này riêng ngày16/11 dùng đồng hồ giả, không phải cho phép app chính ghi tương lai. |

## Kiểm tra ngay dữ liệu đã lưu — không nhập thêm

| Bước | Vào màn hình | Thực hiện | Kết quả đã kiểm tra |
|---|---|---|---|
| 1 | [Kế hoạch → Định Hình](http://localhost:8000/production/schedule) | Từ ngày **10/11/2026**, đến ngày **16/11/2026**; ngày chốt cần xem **15/11/2026**; chế độ **So sánh · đầu ngày với thực tế** → **Tải chế độ đã chọn**. Khoảng từ10/11 cũng bao gồm đơn C có sẵn; chỉ theo dõi dòng LSX A/B. | `LSX_261115_001`: bên chốt dự kiến `DH-01` 15/11; bên thực tế có `DH-01, DH-02`, A200/B100. Có báo **Đổi máy**. Bản chốt được tạo trước phát hành, mã chính thức được dùng làm nhãn hiển thị mà không đổi bản chốt. |
| 2 | Cùng màn hình | Đổi chế độ **So sánh · đầu ngày với cập nhật** → **Tải chế độ đã chọn**. | Đối chiếu lịch đầu trên `DH-01` với bản cập nhật v3 trên `DH-02` ngày16/11. Lượng bố trí là tổng kế hoạch; xem sản lượng đã làm ở chế độ thực tế/nhật ký. |
| 3 | [Nhật ký định hình](http://localhost:8000/production/forming) | Chọn `DH-01`; phần **Nhật ký đã ghi**, từ15/11 đến16/11 → **Tra cứu** → mở dòng `LSX_261115_001`, mẫu `QC_261115_10`. | Nhật ký 15/11 16:06:01–16:06:43, máyDH-01; A100/B100; 40 bìa chung. Dòng C là LSX khác, không chọn nhầm. |
| 4 | Cùng màn hình | Chọn `DH-02`; từ15/11 đến16/11 → **Tra cứu** → mở `LSX_261115_001`, mẫu `QC_261115_12`. | Nhật ký ngày mô phỏng16/11 16:14:07–16:14:25, máyDH-02; A100; 20bìa. Tổng LSX A200/B100, B vẫn được ghi là thành phần cũ trong dữ liệu lũy kế. |
| 5 | [Kiểm mẫu trước chạy](http://localhost:8000/production/samples?qc_id=QC_261115_12) | Xem mẫu ngày2 rồi **Kiểm tra điều kiện chạy**. | Đợt đã đóng nên yêu cầu mẫu mới khi chạy lại. Không dùng mẫu này để mở chạy vô thời hạn. |
| 6 | [Phiếu bàn giao](http://localhost:8000/production/handovers) | Tìm `LSX_261115_001` → mở từng phiếu → **Xem NVL theo LSX và lô**. | Ba phiếu A/B đã nhận bằng hai danh tính giả khác nhau; còn lô A2,8kg, lô B1kg, lô tồn3,6kg. Tổng dư7,4kg. |

### Đọc đúng các trạng thái

- A/B đã đủ **sản lượng định hình**, chưa có nghĩa đã cắt xong, giao hàng hoặc kết thúc LSX. Ví dụ chưa làm công đoạn cắt.
- Màn hình Đơn hàng: cột **Đã Giao / Còn Lại** là lượng giao hàng, không phải lượng còn định hình. Không dùng hai cột này để kiểm tra sản lượng nhật ký.
- LSX A/B vẫn còn NVL dư7,4kg nên chưa kết thúc. Không ghi tiêu hao giả để ép hết số dư. Luồng trả/đối soát sau khi đóng đợt, hết sản lượng chưa được hoàn thiện trong lần này; không nới điều kiện backend hoặc tự mở lại đợt.
- Không nhập tốc độ/chạy thuần nếu chưa đo. Màn so sánh có thể ghi thiếu thời gian chạy thuần; không tự lấy thời gian kế hoạch thay thực tế. Các khoảng giờ ngắn trong ví dụ là số giả nhập để test thao tác.
- Định mức thực hành PP không sửa mô tả PET0,4 đang có ở master sản phẩm. Khuôn và template thực hành đều có nhãn giả; không dùng chúng làm thông số sản xuất thật.

## Dữ liệu cũ và kết quả kỹ thuật

Dữ liệu DEMO7/P14 trước đây đã được xóa theo phạm vi đã xác minh và có backup. Audit và bộ đếm mã được giữ nguyên; không reset mã để lấp số đã dùng. Các báo cáo P14 cũ chỉ là hồ sơ kiểm tra lịch sử, không đại diện dữ liệu hiện tại.

- [Báo cáo dữ liệu mới được giữ lại](reports/production-walkthrough-ab-20261115.json).
- [Báo cáo dọn dữ liệu cũ](reports/reset-gpt-demo-20261115.json).
- [Backup trước dọn](backups/napaco-pre-reset-gpt-demo-20261115.sql.gz).

Đã test UI: lập hai đơn, đặt/nhận12kg NVL mới, giữ nguồn mới+tồn, lưu/chốt/phát kế hoạch, lập phiếu bàn giao, mở đợt mẫu, nhập3nhật ký (2 của A/B và1 của C), cập nhật máy/thành phần cùng LSX, xem đối chiếu và lịch sử. Chữ ký và phần Drive của mẫu là fixture, đã nói rõ phía trên. Kiểm tra tập trung so sánh: **6 passed**; cú pháp JS đã sửa đạt; diff không lỗi whitespace. Build local thành công, backend/worker đã recreate; không deploy production. Dừng thực hiện thêm theo yêu cầu người dùng.
