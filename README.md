# Fashion Store — dự án web cá nhân

Ứng dụng Flask mô phỏng quy trình xem sản phẩm, đặt đơn và quản trị cửa hàng thời trang. Đây là project học tập/portfolio, không phải một cửa hàng có doanh thu hoặc người dùng thực đã được xác nhận.

## Phạm vi hiện có

- Catalog: tìm kiếm, gợi ý tìm kiếm, lọc/sắp xếp/phân trang, biến thể size–màu và tồn kho.
- Giỏ hàng phiên, wishlist tài khoản, đặt đơn COD, thông tin người nhận, lịch sử và trạng thái đơn.
- Admin: quản lý sản phẩm/biến thể, cập nhật đơn, xem khách hàng, phản hồi/ẩn bình luận, biểu đồ và CSV.
- Chat: tin nhắn lưu DB, chat hỗ trợ với credential do server ký, cuộc trò chuyện tài khoản, file đính kèm riêng tư và Redis room publication được kiểm chứng ở phạm vi hẹp.
- WebRTC một-một và mesh nhóm nhỏ tối đa bốn người là tính năng thử nghiệm. Browser test dùng thiết bị giả/local ICE; không bảo đảm TURN, NAT hay kết nối trên mọi mạng. Không có livestream phát một-nhiều.
- OAuth Google/GitHub login + liên kết tài khoản có triển khai disabled-safe, nhưng chưa smoke với provider thật do không có client credentials. Bản đồ đơn hàng là vị trí địa chỉ ước tính; network geocoding mặc định tắt và không phải carrier tracking.

**Chưa tích hợp:** thanh toán online, mã giảm giá thực, hãng vận chuyển/tracking trực tiếp, gửi newsletter tự động, mobile app, AI recommendations. Biểu đồ “doanh thu đã giao” tính giá trị đơn `Delivered`, theo ngày đặt; không phải sổ kế toán hoặc bằng chứng thanh toán.

## Stack và tổ chức

Python 3.11, Flask, psycopg2/PostgreSQL, Jinja2, Bootstrap 5, JavaScript, Flask-SocketIO, Chart.js, Docker. App Factory đăng ký Blueprints; service classes chứa thao tác DB. Các luồng chính dùng SQL có tham số và SQL functions/triggers, không phải một hệ ORM hoàn chỉnh.

```text
app/             routes, services, templates, CSS/JS, application factory
app/static/vendor/  browser libraries/fonts có version được khóa
db/              bootstrap.sql, seed_test.sql, nguồn gốc schema và giới hạn
 tests/          unit, contract, integration, e2e, js
 tools/          seed/test-server và asset tooling
 requirements*.in / requirements*.txt   dependency inputs + hash locks
```

## Chạy local an toàn

Không dùng credentials hoặc dữ liệu khách hàng thật để thử nghiệm. File `.env` không được track; App Factory chỉ đọc `.env` trong đúng thư mục project khi không truyền test config.

1. Tạo môi trường Python 3.11 và cài runtime:
   ```bash
   uv venv --python 3.11 .venv
   uv pip sync --python .venv/Scripts/python.exe requirements.txt
   ```
   Linux/macOS dùng `.venv/bin/python` thay cho `.venv/Scripts/python.exe`.
2. Tạo `.env` từ `.env.example`; tự sinh `SECRET_KEY` ít nhất 32 ký tự, điền PostgreSQL **local** đã chuẩn bị.
3. Đặt `DATABASE_URL` của DB local trong shell rồi chạy `python -m tools.migrate_db`. Lệnh tạo schema nếu cần và áp dụng các migration theo thứ tự. Xem [hướng dẫn PostgreSQL](db/README.md) trước khi nâng DB đang có dữ liệu.
4. Chạy `python run.py`. Mặc định bind `127.0.0.1:4000`, debug tắt. Dev server không thay thế production server.

### Docker Compose

Compose tạo PostgreSQL local, chạy migration trước khi khởi động web và expose web ở `127.0.0.1:4010`. Ảnh đại diện, file chat và ảnh sản phẩm tải từ Pixabay dùng volume `uploads`.

```bash
# Tự đặt SECRET_KEY độc lập và POSTGRES_PASSWORD trong shell/.env.
docker compose -p thua2-main-local up -d --build --wait
```

Chuỗi mật khẩu dùng trong URI cần URL-encode nếu có ký tự đặc biệt. DB chỉ truy cập được trong mạng Compose. Image chạy non-root, dùng Gunicorn `gthread` một worker. `/health/live` kiểm tra tiến trình, còn `/health/ready` kiểm tra kết nối, quyền truy cập và schema PostgreSQL. Docker kiểm tra readiness qua loopback với hostname từ `PUBLIC_BASE_URL` nếu có. Stack chính vẫn single-instance. `docker-compose.scale.yml` là topology kiểm thử local riêng với hai instance một-worker, Nginx sticky và Redis; chỉ persisted numeric-message delivery đã được chứng minh cross-worker. Call/presence/generation/cache invalidation và nhiều event family vẫn process-local hoặc chưa chứng nhận; xem `docs/LOAD_TESTING.md`.

## Bộ kiểm chứng

Dev dependencies tách khỏi runtime. Các tests cần DB chỉ chấp nhận `TEST_DATABASE_URL` loopback có tên chính xác `thua2_main_test`, không query/fragment override. DB test dùng tmpfs, dữ liệu tổng hợp và reset fixture. **Không chạy hai suite reset chung DB cùng lúc.**

```bash
uv pip sync --python .venv/Scripts/python.exe requirements-dev.txt
npm ci --ignore-scripts
npm run vendor
python -m playwright install chromium

docker compose -p thua2-main-tests -f docker-compose.test.yml up -d --wait
export TEST_DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:55434/thua2_main_test'

python -m ruff check app run.py tests tools
python -m ruff format --check app run.py tests tools
python -m pyright --project pyrightconfig.json
npm run lint
npm run test:js
python -m pip_audit -r requirements.txt --disable-pip
python -m pip_audit -r requirements-dev.txt --disable-pip
python -m pytest -m 'not e2e' --cov=app --cov-config=pyproject.toml --cov-branch --cov-report=html:artifacts/htmlcov
python -m pytest -m e2e --timeout=90

docker compose -p thua2-main-tests -f docker-compose.test.yml down -v
```

Chạy lệnh từ thư mục project; chạy coverage từ repo/worktree khác có thể đo nhầm source. Không import `run.py` trong tests vì nó tạo app theo environment.

### Preview dữ liệu kiểm thử

```bash
python tools/seed_test.py --yes-test-seed
python tools/serve_test.py --port 4010
```

Seed additive chỉ chấp nhận DB test; tài khoản `customer@example.test`, `admin@example.test`, `other@example.test`, mật khẩu thử nghiệm `TestUser123!`. Không phải credentials triển khai. Test server suppress mail/không dùng payment thật. Sau khi test reset DB, phải chuẩn bị lại state nếu muốn preview.

## Giới hạn bảo mật/triển khai

- Không có secret/API key fallback; production yêu cầu Secure cookies, trusted hosts, public HTTPS URL và shared rate-limit storage.
- Proxy headers chỉ tin khi bật rõ `TRUSTED_PROXY_COUNT`.
- Password hash, reset token digest/expiry/one-use, `auth_version` thu hồi phiên khi đổi/reset mật khẩu; quyền được đọc lại từ DB.
- Chat kiểm participant/scope ở HTTP, service và Socket.IO; admin không mặc nhiên đọc private chat. Upload decode/type/size check, đường dẫn tạo ngẫu nhiên, download qua ACL; đường dẫn chat public cũ bị chặn trong ứng dụng. Trên deployment dùng static reverse proxy, không phục vụ `app/static/uploads/chat/` trực tiếp. Đây không phải antivirus/content scanning.
- CSP hiện vẫn cho inline script/style do HTML main có inline handlers. Không nhận đây là CSP nonce-based hoàn thiện. Thư viện/font chính được phục vụ local.
- Cookie-based cart không được quảng cáo là giỏ multi-tab/server-side đồng bộ. Background reads không được ghi lại cookie cũ; sửa race có regression và E2E.
- Blueprint Render dùng Starter trả phí, disk 1 GB tại `UPLOAD_ROOT` và chạy migration trước khi khởi động phiên bản mới. Disk chỉ gắn được với một instance và có khoảng gián đoạn ngắn khi redeploy. Vercel Functions chỉ cho ghi vào `/tmp` của từng instance. Cần lưu file bên ngoài Functions và kiểm chứng reconnect/Socket.IO trước khi dùng làm môi trường chính. [Render Persistent Disks](https://render.com/docs/disks) · [Vercel Functions filesystem](https://vercel.com/docs/functions/runtimes#file-system-support) · [Vercel WebSockets](https://vercel.com/docs/functions/websockets)

Kết quả remediation đã push vẫn ở `docs/MAIN_REMEDIATION.md`. Phần mở rộng hiện tại, số aggregate mới, OAuth/map/mesh/Redis/load evidence và giới hạn nằm trong `docs/MAIN_EXPANSION.md`, `docs/LOAD_TESTING.md` và `docs/SECURITY_REVIEW.md`. Không suy ra production readiness chỉ từ test xanh; các thay đổi expansion vẫn local/uncommitted nếu chưa được commit/push riêng.
