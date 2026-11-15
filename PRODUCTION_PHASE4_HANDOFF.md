# Giai đoạn 4 — Nhật ký hút / định hình

Trạng thái: đã viết code và rà soát diff. Chưa chạy test, kiểm tra cú pháp, build/recreate hoặc nghiệm thu trình duyệt theo yêu cầu tạm hoãn test tập trung. Không deploy production.

## Kiểm tra trước khi sửa

- Đã đọc AGENTS.md, đối chiếu source của giai đoạn 1–3, schema MySQL local của `forming_logs`, `production_shift_items`, `production_shift_materials`, `production_order_items` và cơ chế lịch chung.
- Database local đang ở revision 015. Migration 016 của giai đoạn 2 vẫn chưa được áp dụng; cần schema này trước khi chạy backend mới. Giai đoạn 4 không thêm bảng, cột, khóa hoặc migration.
- Dùng lại `forming_logs` làm nhật ký, `production_shift_items` làm sản lượng từng CTĐH, `production_shift_materials` làm cân đối theo lô. Giữ ID nhật ký và liên kết nguồn cắt/ép biên hiện có; không tạo sổ hay mô hình LSX cạnh tranh.

## Luồng nhập ít thông tin

1. Mở **Nhật ký định hình**, chọn máy. Danh mục máy được tải khi mở màn hình; công việc chỉ tải khi chọn máy hoặc nhấn nạp lại.
2. Mỗi lựa chọn hiển thị rõ mã LSX chính thức cùng CTĐH/sản phẩm và lượng còn lại. Cùng CTĐH ở nhiều LSX có các lựa chọn riêng theo LSX; không tự chọn LSX theo CTĐH. Danh sách dùng phân công hiện hành, trạng thái phát hành và phần còn thực hiện; không lọc giờ hoặc bắt theo thứ tự kế hoạch.
3. Khi chọn LSX, backend nạp đủ thành phần ghép, phân công, đợt chạy, phiếu mẫu, nguồn NVL và version. Một trang danh sách có thể chỉ chứa một phần các CTĐH; màn hình ghi vẫn nạp đủ nhóm của LSX được chọn.
4. Ngày giờ có giá trị điền trước: hôm nay cho nhật ký mới, mốc nhật ký cuối cùng trong ngày/đợt khi có, và giờ kết thúc hiện tại. Mốc bắt đầu được giới hạn bởi phân công và thời điểm đủ ký mẫu. Đây là gợi ý từ dữ liệu có sẵn, người ghi phải sửa nếu khác thời gian thực tế; không lấy giờ kế hoạch làm giờ chạy thực tế.
5. Nhập bìa tốt, bìa NG (mặc định 0). Với sản phẩm chỉ có một CTĐH, điền trước số cái từ **bìa thực tế × cavity** và cho sửa. Nếu nhiều CTĐH cùng sản phẩm, người ghi phải phân chia số cái thực tế; hệ thống không đoán phân bổ.
6. Mỗi lô chỉ cần nhập **kg còn cuối kỳ** hoặc chuyển sang **kg tiêu hao**. Số còn lại được tính bằng phương trình cân đối từ dữ liệu đã ký nhận/cấp–trả thực tế. Tính số kg trên giao diện dùng số thập phân chính xác đến 8 chữ số; backend vẫn kiểm tra lại độc lập.
7. Không bắt nhập ID nội bộ, người ghi, máy, LSX, khuôn, cavity, từng movement hay thông số kế hoạch lặp lại. Ghi chú thông thường là tùy chọn. Thông số thực tế bổ sung để trống nếu chưa đo; không tự ghi thông số kế hoạch vào cột thực tế.
8. Chọn **Tiếp tục / nghỉ trong cùng đợt** hoặc **Kết thúc đợt; chạy lại cần mẫu mới** rồi lưu. LSX chưa bắt đầu được bắt đầu cùng transaction với nhật ký đầu; nếu lưu lỗi, trạng thái bắt đầu cũng rollback.

## Đợt chạy, nhiều ngày và chuyển máy

- Mỗi lần lưu tạo một nhật ký riêng. Hôm nay lưu, mai mở ghi tiếp sẽ có hai nhật ký cùng LSX; không tự gộp các ngày vào bản ghi cũ.
- Nghỉ trưa lấy từ cấu hình chung/ghi đè máy để hiển thị và lưu bản tham chiếu. Không tự tách nhật ký, tự đóng đợt hoặc suy ra thời gian chạy thuần từ giờ nghỉ. Khoảng nhật ký có thể bao gồm nghỉ; chạy thuần/setup chỉ lưu khi có số thực tế được nhập.
- Nghỉ trong cùng đợt giữ phiếu mẫu nếu đợt vẫn còn hiệu lực. Đóng đợt ghi thời điểm kết thúc thực tế đã nhập trong cùng transaction; giữ trạng thái LSX để có thể chạy tiếp. Lần chạy lại cần đợt mới và mẫu mới đúng giai đoạn 3.
- Máy được giải phóng khi đợt đã đóng/hết hiệu lực, không bắt kết thúc LSX chỉ để chuyển sang LSX khác. Những LSX cũ đang chạy nhưng chưa có bằng chứng đợt vẫn được kiểm soát thận trọng; giữ cơ chế giải phóng máy bằng dừng đã ghi nhận hiện có.
- Sau cập nhật kế hoạch DH01 → DH02 và kiểm mẫu lại, nhật ký mới vẫn dùng ID LSX cũ. Số dư NVL lấy theo LSX/lô, không theo máy; nhật ký DH01 giữ nguyên máy và phân công đã ghi. Không ghi đè nhật ký cũ bằng máy hiện tại của header LSX.

## Kiểm soát backend

- Mọi lần ghi dùng khóa ERP, transaction, khóa/version LSX, phân công, đợt và idempotency hiện có. Quyền vẫn là `PRODUCTION_EDIT`; không thay ma trận quyền.
- Kiểm tra LSX đã phát/còn hiệu lực, máy đúng loại và phân công, đầy đủ CTĐH hiện hành và giới hạn sản lượng tại cả LSX lẫn CTĐH tổng.
- Phiếu mẫu phải đủ kỹ thuật/QC, đúng máy/đợt và khoảng thực hiện, có quyết định cho phép. Kiểm tra cả mã và version phiếu được chọn, không tự thay phiếu khác trong lúc lưu. NG + Cho chạy lọc hợp lệ vẫn được ghi và giữ NG.
- Chỉ dùng NVL đã ký nhận. Theo từng lô: **đầu kỳ + nhận thêm − trả/chuyển − tiêu hao = cuối kỳ**. Trả chờ kho nhận đã bị tách khỏi lượng dùng; không cộng lại vào kho ở bước ghi nhật ký.
- Lưu dấu nguồn trên màn hình và kiểm tra lại khi ghi. Nguồn đổi trong lúc nhập thì yêu cầu nạp/kiểm đếm lại; không âm thầm thay số tiêu hao tính từ số kiểm đếm cũ. Gửi lại thao tác khi mất kết nối dùng cùng nội dung, ID nhật ký và Idempotency-Key.
- Sửa cách đọc nguồn theo mốc thời gian: nhật ký kết thúc sau mốc đang xét không được làm số dư mở đầu cho mốc trước đó. Guard riêng kiểm tra nhật ký cuối toàn LSX để thay đổi này không mở đường chèn nhập bù.
- Chặn khoảng trùng trên cùng máy hoặc cùng LSX qua hai máy, kể cả khoảng có nghỉ/không có sản lượng. Khoảng là nửa mở: kết thúc nhật ký trước bằng bắt đầu nhật ký sau được phép.
- Với nhật ký cũ cùng máy/LSX cùng ngày có thiếu giờ, từ chối xác nhận khoảng chồng ngày để đối soát; không tự suy diễn giờ/máy lịch sử.
- Guard chỉ xét nhật ký định hình cho xung đột định hình; không khóa máy cắt vì máy định hình đang chạy. Nguồn cắt/ép biên vẫn là ID `forming_logs` và các dòng `production_shift_items` hiện có.

## Lũy kế và tương thích

- API lũy kế lấy tất cả nhật ký cùng LSX qua các ngày/máy: bìa ở header, cái tốt/NG theo CTĐH và lượng đã nhận/tiêu hao/còn dùng theo lô.
- Thời gian máy cộng theo header nhật ký một lần, không JOIN để nhân theo số CTĐH. Hiển thị rõ thời gian khoảng ghi nhận gồm nghỉ; không gọi đó là thời gian chạy thuần.
- Giá trị thực tế chưa nhập giữ `NULL`/chưa biết, gồm tốc độ, bước kéo, khối lượng bìa, chạy thuần và setup. Màn hình nhật ký cũ cũng bỏ điền thông số kế hoạch vào ô thực tế và nhận các giá trị trống này khi sửa; dữ liệu thực tế cũ có sẵn được giữ để người dùng xem/sửa.
- Dữ liệu cũ không tự được coi là có chữ ký bàn giao hay phiếu mẫu mới. Giữ phần lịch sử chưa xác minh tách khỏi lượng NVL dùng được; không backfill số đo, chữ ký hoặc biến động kho.
- Chi tiết nhật ký hiển thị mã LSX chính thức và máy từ bằng chứng nhật ký/bản chụp lịch sử, không lấy máy hiện tại của LSX để thay lịch sử. Không sửa dữ liệu cũ khi đọc.

## Giới hạn nhập bù / sửa

- Hỗ trợ thêm tiếp ở cuối chuỗi với khoảng đã thực hiện, nguồn hợp lệ, còn đúng phân công/cấu hình và phiếu mẫu có hiệu lực tại khoảng đó. Không ghi tương lai.
- Chưa hỗ trợ chèn nhật ký vào giữa chuỗi số dư hoặc sửa nhật ký đã có nhật ký sau.
- Chưa hỗ trợ sửa nhật ký sau khi công đoạn cắt/ép biên đã dùng nguồn, đổi máy/phân công cũ, đổi phiếu căn cứ, hồi tố nhật ký cũ thiếu phiếu mẫu, hoặc sửa LSX đã kết thúc.
- Sửa nhật ký cuối cần lý do; không thay đổi hành động đóng/tiếp tục đợt hoặc tự mở lại đợt đã đóng. Cấu hình lịch tham chiếu ban đầu được giữ khi sửa.
- LSX chưa bắt đầu không tự được suy thành đã chạy trong quá khứ nếu đợt mẫu đã đóng/hết hiệu lực trước nhật ký đầu: thao tác bắt đầu hiện tại vẫn phải qua guard. Trường hợp nhập bù này cần chính sách riêng, chưa mở trong giai đoạn 4.
- Không tự phân bổ tiêu hao cho lịch sử thiếu lô/giờ hoặc suy ra số thực tế từ kế hoạch để lấp dữ liệu.
- Không tự hồi tố phiếu cấp/trả lập sau giờ chốt vào nhật ký đã lưu. Trường hợp kiểm đếm thực tế và thời điểm lập biến động kho lệch kỳ cần đối soát; không âm thầm sửa chuỗi số dư.

## File và API

- [Màn hình nhập](frontend/production/forming.html), [logic giao diện](frontend/production/forming.js).
- [Service nhập/lũy kế](backend/app/modules/production/forming_service.py), [schema đầu vào](backend/app/modules/production/forming_schemas.py), [API](backend/app/modules/production/forming_api.py).
- Điểm ghi cốt lõi vẫn là `run_service.save_shift`; các thay đổi trực tiếp còn có schema nhật ký, source accounting, trạng thái bận máy, đóng đợt, menu và màn hình nhật ký cũ.
- `GET /api/production/forming/machines`: danh mục máy định hình phù hợp.
- `GET /api/production/machines/{machine_id}/work?stage=forming`: danh sách CTĐH–LSX đã phát/còn thực hiện được, không xét thứ tự/giờ kế hoạch.
- `GET /api/production/forming/context`: dữ liệu điền trước theo LSX/máy/đợt/khoảng nguồn, phiếu căn cứ và dấu nguồn.
- `POST /api/production/forming/runs/{run_id}/logs`: ghi nhật ký; `PUT .../logs/{log_id}`: sửa có kiểm soát.
- `GET /api/production/forming/runs/{run_id}/summary`: lũy kế cùng LSX qua các máy.
- `GET /api/production/forming/history`: tra cứu có bộ lọc và pagination; `GET /api/production/shifts/{id}`: chi tiết hiện có, tiếp tục dùng cho công đoạn sau.

## Kiểm tra còn lại

- [Bộ test giai đoạn 4](backend/tests/test_forming_diary.py) đã chuẩn bị bằng dữ liệu giả trong fixture MySQL rollback; chưa chạy. Có ca nhập tối thiểu/không suy số đo, nhiều ngày cùng LSX, cùng đợt, nguồn tại mốc quá khứ, nguồn thay đổi rollback bắt đầu, sai phiếu/phân công/lô, vượt lượng, chèn bù, đổi máy giữ lịch sử và ghép CTĐH không nhân thời gian.
- Chưa xác nhận runtime, UI hay tính đồng thời bằng test. Đợt kiểm tra tập trung cần thêm B trước A/nhiều LSX cùng CTĐH, nghỉ trưa, máy bận/đóng đợt, lỗi mạng gửi lại, dữ liệu cũ và hồi quy cắt/ép biên cùng giai đoạn 1–3.
- Chưa ghi dữ liệu giả vào database local hoặc áp dụng migration trong lượt code này. Trước khi dùng UI mới cần migration 016 và build/recreate backend/worker đồng bộ cho các giai đoạn đã viết; không đưa backend mới chạy trên schema 015.
