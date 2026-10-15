# Rau Má 3636 — Telegram Mini App (tiền ảo)

Đây là bộ khung chạy được cho Mini App Telegram: giao diện HTML, backend FastAPI/Python, SQLite, đăng ký/đăng nhập gắn với Telegram ID, ví tiền ảo, cược Tài/Xỉu, lịch sử cầu và menu admin.

## Quan trọng trước khi chạy

- Đây chỉ là trò chơi **tiền ảo**, không có nạp/rút tiền thật.
- Cần một URL HTTPS công khai cho backend và Mini App.
- Cần bot Telegram và token từ BotFather.
- **Không đưa token bot, APP_SECRET hay ADMIN_PASSWORD lên GitHub.**
- Đặt mật khẩu admin mới trong biến môi trường; mật khẩu đã gửi trong chat không được nhúng vào source code.
- Dữ liệu lưu ở SQLite trên máy chủ. Nếu dùng host có ổ đĩa tạm thời, dữ liệu có thể mất khi deploy/restart; cần persistent disk hoặc PostgreSQL cho vận hành lâu dài.

## Chạy thử local

1. Cài Python 3.11+.
2. Mở terminal tại thư mục này:
   ```bash
   python -m venv .venv
   ```
   Windows:
   ```bash
   .venv\Scripts\activate
   ```
   Android/Termux/Linux:
   ```bash
   source .venv/bin/activate
   ```
3. Cài thư viện:
   ```bash
   pip install -r requirements.txt
   ```
4. Đặt biến môi trường (không dùng thông tin mẫu ở production):
   ```bash
   export TELEGRAM_BOT_TOKEN="token_bot_cua_ban"
   export APP_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
   export ADMIN_USERNAME="tổ ayeuem"
   export ADMIN_PASSWORD="mat_khau_admin_moi_rat_manh"
   ```
   Windows PowerShell dùng `$env:TELEGRAM_BOT_TOKEN="..."` tương tự.
5. Chạy:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

Trang đăng nhập chỉ xác minh được khi mở bên trong Telegram Mini App qua HTTPS. Truy cập localhost bình thường sẽ báo cần mở từ bot — đó là chủ ý bảo mật.

## Thiết lập Telegram

1. Tạo bot qua `@BotFather`, lấy token.
2. Deploy toàn bộ project lên host hỗ trợ Python/ASGI, thiết lập các biến môi trường ở phần trên.
3. Dùng BotFather `/setmenubutton` để đặt URL Mini App HTTPS (hoặc cấu hình Main App nếu tài khoản bot hỗ trợ).
4. Mở Mini App từ bot. Người dùng đăng ký lần đầu trên Telegram của họ; hệ thống xác minh Telegram `initData` phía máy chủ và liên kết tài khoản với Telegram ID.

## Admin

- Username mặc định: `tổ ayeuem` (có thể đổi bằng `ADMIN_USERNAME`).
- Mật khẩu phải đặt bằng biến môi trường `ADMIN_PASSWORD`; không lưu mật khẩu admin trong HTML hoặc GitHub.
- Khi tài khoản admin đăng ký lần đầu bằng đúng username và mật khẩu cấu hình, tài khoản nhận quyền admin và 2.000.000 tiền ảo.
- Tên tài khoản admin phải khớp chính xác với biến `ADMIN_USERNAME`.
- Admin có thể xem ID/tên Telegram, username, số dư và cộng/trừ tiền ảo từ menu admin.

## Quy tắc game

- Một ván kéo dài 80 giây: 60 giây nhận cược và 20 giây mở bát.
- Ba xúc xắc tạo kết quả chung cho tất cả người chơi của ván đó.
- Tài = tổng 11–18; Xỉu = tổng 3–10.
- Cược thắng nhận lại tổng cộng 2 lần số cược (vốn + lãi bằng vốn cược).
- Mã `TEST` cộng 1.000.000 tiền ảo một lần cho mỗi tài khoản.
- Thưởng hằng ngày +100 tiền ảo.
- Cầu lịch sử được cập nhật sau khi kết quả ván được tạo.

## Giới hạn của bản khung

- Đây là bản cơ bản để học và thử nghiệm, chưa được kiểm thử bảo mật độc lập.
- Nên bổ sung HTTPS/reverse proxy, rate limiting, backup database, CSRF/origin controls, logging, và kiểm tra triển khai trước khi cho người dùng thật truy cập.
- Admin account được tạo bằng username/password cấu hình; nên đăng ký tài khoản admin trước khi người chơi khác biết URL.
