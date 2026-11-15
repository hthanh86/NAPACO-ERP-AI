# Luồng sản xuất NAPACO ERP — giai đoạn 1–4

Cập nhật 15/11/2026 theo source và kiểm tra tích hợp local. Mở http://127.0.0.1:8000. Xem [bảng kiểm tra màn hình](PRODUCTION_PHASE14_UAT.md), [dữ liệu giả](reports/production-phase14-demo.json) và [kết quả HTTP/MySQL](reports/production-phase14-verification.json).

## Luồng đã triển khai

| Bước | Màn hình | Quy tắc thực tế tại backend |
|---|---|---|
| Chuẩn bị NVL | Nhập kho/IQC; Kế hoạch → Chuẩn bị nhựa | Dùng luồng nhập/IQC/lô OK/phần giữ hiện có. Giữ NVL chưa phải cấp hay ký nhận. |
| Lập kế hoạch | Kế hoạch → Định Hình | Tính thử → xác nhận cảnh báo → Lưu. Được lưu LSX nội bộ chưa phát; chưa được cấp, chạy mẫu hoặc ghi sản xuất. |
| Phát LSX | Lần chạy / nhật ký ca → mở lệnh → Phát lệnh | Cần kế hoạch đã lưu khớp phiên bản. Giữ ID; cấp mã đã thống nhất `LSX_YYMMDD_NNN` theo ngày phát, lưu người/thời điểm/bản chụp đã phát. Phát lại không tạo lệnh hoặc mã mới. |
| Phân công | Định Hình → sửa/Chuyển máy → Tính thử → Lưu | Lưu phiên phân công theo công đoạn/máy/CTĐH. Đổi máy, số lượng, thành phần sau phát phải qua kế hoạch, giữ phần đã thực hiện và bản phát ban đầu. |
| Lập phiếu cấp | Chuẩn bị nhựa → Phân bổ / cấp / trả → Lập phiếu cấp | Chọn rõ LSX đã phát, còn thực hiện, lô/phần giữ hợp lệ. Cấp được nhiều lần. Nháp giữ cam kết cấp nhưng chưa xuất kho. |
| Ký cấp | Cấp NVL và ký bàn giao → Mở phiếu | Kiểm tra quyền kho, tồn, lô, phần giữ và bố trí trong transaction. Tạo một giao dịch cấp ở sổ cũ, giảm tồn/phần giữ một lần. NVL chờ bàn giao, người nhận còn trống, chưa được dùng. |
| Ký nhận | Cùng phiếu, người nhận đăng nhập Google của mình | Ghi danh tính, thời điểm, phiên, nét ký và dấu nội dung. Tăng nguồn đã nhận; không trừ tồn thêm. Không tự lấy tài khoản người cấp làm người nhận. |
| Mở đợt/chạy mẫu | Kiểm mẫu trước chạy → tìm LSX → chọn phân công → mở đợt | Kiểm tra máy/CTĐH và NVL đã ký nhận còn dùng được. Đợt có hạn thực hiện và bản chụp cấu hình. Chạy lại sau kết thúc/dừng/đổi cấu hình cần mẫu mới. |
| Nhập/ký mẫu | Chọn template từ Drive → nhập kết quả → Lưu → kỹ thuật/QC ký | Dùng chung QC_TEMPLATES, mapping và template đầu/giữa/cuối ca. Nháp chưa mở chạy. Đạt + hai xác nhận: hàng loạt. NG + hai xác nhận + Cho chạy lọc: được chạy nhưng vẫn NG. NG Dừng, thiếu ký, đang nhập/hủy: chặn. |
| Nhật ký hút | Nhật ký định hình → chọn máy → chọn rõ LSX → nhập thực tế → Lưu | Danh sách đúng phân công, đã phát, CTĐH còn thực hiện. Không lọc giờ hoặc ép thứ tự kế hoạch. Điền sẵn ngày/giờ tham chiếu, máy, CTĐH, mẫu, lô; cho sửa trong giới hạn nghiệp vụ. |
| Đối soát ca | Cùng nhật ký | Theo lô: đầu kỳ + nhận thêm − trả/chuyển − tiêu hao = cuối kỳ. Chỉ dùng nguồn ký nhận, không cộng lại phiếu đã chốt. Nhập tiêu hao hoặc cuối kỳ; backend kiểm vế còn lại. |
| Nghỉ/chạy tiếp | Nhật ký → Sau nhật ký này | Nghỉ trong cùng đợt không tạo LSX mới. Nghỉ trưa không tự tách nhật ký. Qua ngày ghi nhật ký khác cùng LSX; đợt đã đóng/hết hạn thì phải kiểm mẫu mới. |
| Kết thúc định hình | Lần chạy / nhật ký ca → Kết thúc | Không còn bàn giao nháp/chờ nhận, trả chờ kho, giao dịch chưa chốt hoặc số dư theo lô khác 0 (kể cả số lịch sử chưa đối soát). Không tự trả kho/ghi tiêu hao/giải phóng phần giữ. |
| Cắt/ép biên | Lệnh → nhật ký hút nguồn → Cắt / Ép biên | Giữ nguồn hàng thực tế, tuyến, lượng tốt còn lại, phân công và mẫu công đoạn. Có thể song song với hút tiếp theo từ nguồn đã chốt. Kết thúc định hình không xóa nguồn cắt/ép biên còn hợp lệ; không cho định hình lại LSX đã kết thúc. |

## Nguyên tắc dữ liệu

- LSX vẫn là `production_orders`; nhiều–nhiều qua `production_order_items`. Một CTĐH được nằm trong nhiều LSX trong giới hạn lượng còn lại. Không có mô hình LSX cạnh tranh.
- `production_schedule_plans` giữ phiên kế hoạch; `production_order_assignments` giữ phân công. DH01 → DH02 không sửa máy/phân công trong nhật ký cũ, không đổi mã/ID LSX.
- LSX ghép dùng một header `forming_logs`/một khoảng máy; `production_shift_items` giữ sản lượng từng CTĐH. Hai CTĐH cùng sản phẩm nhập phân chia thực tế, không nhân thời gian theo số CTĐH.
- Không trùng khoảng trên một máy hoặc cùng LSX ở hai máy định hình. Không chặn cắt khác công đoạn với nguồn hợp lệ.
- `film_movements` vẫn là sổ cấp–trả vật lý; `material_handovers` bổ sung vòng đời/chữ ký. Trả chờ kho đã trừ khỏi nguồn tại máy; tồn chỉ tăng khi kho xác nhận theo luồng cũ.
- `production_setups` là đợt thực tế. Phiếu mẫu dùng `qc_checks` và template chung. Nhật ký giữ căn cứ mẫu theo đợt, kết luận và quyết định đã ký.
- Tốc độ, thời gian chạy thuần, trọng lượng thực tế chưa đo được để trống; không suy diễn từ kế hoạch.
- API ghi dùng quyền backend, khóa ERP/MySQL, version, transaction và idempotency. Dữ liệu nguồn thay đổi phải tải lại, không ghi đè ngầm.
- Mã chính thức dùng trên danh sách, chọn lệnh, phiếu phát, bàn giao, mẫu và nhật ký. ID LSX chỉ dùng liên kết, không yêu cầu nhập trong thao tác thông thường.

## API nền

| Mục đích | API |
|---|---|
| Kế hoạch | `POST /api/production/schedule/preview`, `/save` |
| Phát/phiếu phát | `POST /api/production/runs/{id}/release`, `GET .../release-sheet` |
| Công việc máy/phân công | `GET /api/production/machines/{machine}/work?stage=forming`, `/api/production/runs/{id}/assignments` |
| Bàn giao | `/api/production/materials/handovers`, `/{id}/confirm-signature`, `/{id}/sign` |
| Nguồn đã nhận theo LSX/lô | `GET /api/production/materials/runs/{id}/balance` |
| Đợt/mẫu/điều kiện chạy | `/api/production/sample-episodes`, `/api/production/samples`, `/api/production/runs/{id}/sample-eligibility` |
| Nhật ký/lũy kế | `/api/production/forming/context`, `/runs/{id}/logs`, `/history`, `/runs/{id}/summary` |

## Dữ liệu cũ và schema

Migration 015 bổ sung phát hành/phân công; 016 bổ sung bàn giao, đã áp dụng local sau backup. Giai đoạn 3–4 mở rộng bảng/JSON hiện có, không có migration mới.

12 LSX trước bộ P14 vẫn là dữ liệu cũ chưa xác nhận phát hành. Không phát/cấp mã giả, không lấy máy hiện tại điền lịch sử. Tiếp tục cần kiểm tra và phát rõ ràng trên kế hoạch hiện hành. `receiver_id` cũ không là chữ ký mới; số dư cũ hiển thị riêng và không tự thành nguồn đã nhận. Không tự chuyển/đối soát dữ liệu lịch sử.

## Để sau và giới hạn

| Nội dung | Trạng thái |
|---|---|
| Kiểm máy đầu ca bằng form Drive | Chưa làm; không mở rộng bảo trì máy. |
| Chèn nhật ký giữa chuỗi/sửa ca cũ đã có ca sau | Chưa hỗ trợ. |
| Sửa sau đổi phân công, đổi mẫu căn cứ hoặc nguồn đã được cắt/ép biên sử dụng | Chưa hỗ trợ; không mở chính sách hồi tố. |
| Nhập ca đầu của LSX chưa chạy khi mẫu đã đóng/hết hạn | Bị điều kiện bắt đầu hiện hành chặn; chưa có chính sách nhập bù. |
| Chốt trả hết NVL trong đợt còn hợp lệ | Cho nhật ký 0 sản lượng/0 tiêu hao để đối soát trả, vẫn cần mẫu đủ xác nhận. Không cấp quyền sản xuất khi không còn nguồn. |
| Đối soát bổ sung khi mẫu hết hạn/đợt đóng, không còn NVL để mẫu lại | Chưa có luồng điều chỉnh riêng. Phải đối soát trong đợt hợp lệ trước khi đóng; không nới gate để tự đóng lệnh. |
| QC khoanh vùng sự cố, NCR/CAPA, IPQC/FQC, đóng gói/bàn giao thành phẩm | Giữ module hiện có nếu có; không xây dựng/mở rộng trong phạm vi này. |
| Google ký thật và xuất Sheets/PDF thật | Source nối cơ chế hiện có; bộ P14 mô phỏng, chưa xác minh với tài khoản/file Google thực tế. |
