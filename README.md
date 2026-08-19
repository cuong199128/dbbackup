# Database Backup Manager

Một app Python + PySide6, chạy được trên Windows và Ubuntu, dùng để backup
nhiều SQLite `data.db` của các app Python khác lên Google Drive. **Chỉ app
này tích hợp Google Drive API** — các app khác không cần biết gì về Drive,
Database Backup Manager chỉ đọc file `.db` của chúng từ đĩa.

## Cấu trúc thư mục trên Google Drive

```
Python Database Backup/
└── <Tên ứng dụng>/
    ├── data.db              <- "Latest", bật/tắt riêng từng database
    └── 2026/08-19/
        ├── 08-00-00.db
        └── 12-00-00.db
```

## Cài đặt

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Thiết lập Google OAuth (làm một lần)

1. Vào [Google Cloud Console](https://console.cloud.google.com/) → tạo project
   → bật **Google Drive API**.
2. APIs & Services → Credentials → Create Credentials → **OAuth client ID**
   → Application type: **Desktop app**.
3. Tải file JSON, đổi tên thành `credentials.json`, đặt vào thư mục dữ liệu
   của app:
   - Windows: `%APPDATA%\DatabaseBackupManager\credentials.json`
   - Linux: `~/.local/share/DatabaseBackupManager/credentials.json`
4. Chạy app, tab **Databases** → **Login to Google Drive** → đăng nhập trên
   trình duyệt một lần. Token được lưu (`token.json`) và tự refresh cho các
   lần chạy sau, kể cả khi chạy nền/tray.

Scope dùng: `drive.file` — app chỉ thấy và quản lý được các file/folder do
chính nó tạo ra, không đọc được toàn bộ Drive của người dùng.

## Chạy

```bash
python -m app.main            # mở cửa sổ
python -m app.main --background   # chạy ẩn vào tray (dùng cho autostart)
```

## Tự khởi động cùng hệ thống

Trong GUI (Settings — có thể mở rộng thêm dialog Settings gọi các hàm dưới),
hoặc trực tiếp:

```python
from app.platform import autostart
autostart.enable()   # Windows: shortcut trong Startup folder
                      # Linux: systemd --user service (dbbackup.service)
autostart.disable()
```

## Kiến trúc module

```
app/
  config.py            # đường dẫn dữ liệu app, ConfigStore (danh sách database, settings)
  models.py             # dataclass: DatabaseConfig, RetentionPolicy, BackupRecord
  logger.py              # logging tập trung, ring buffer cho tab Logs

  core/
    change_detector.py   # phát hiện database có thay đổi hay không (fingerprint)
    backup_engine.py      # SQLite Online Backup API, integrity_check, VACUUM/ANALYZE
    drive_layout.py        # xây dựng đường dẫn thư mục/tên file trên Drive (pure, test được)
    drive_client.py         # OAuth, upload/download/list/delete trên Drive, retry
    retention.py             # chọn snapshot nào cần xoá (pure), áp dụng sau khi upload OK
    backup_service.py         # điều phối 1 lượt backup: change check -> snapshot -> upload -> retention
    restore.py                 # backup an toàn bản hiện tại -> tải bản chọn -> integrity check -> swap
    scheduler.py                # APScheduler cron theo từng database
    history_store.py             # lịch sử backup/restore (SQLite nội bộ của app)

  platform/
    autostart_windows.py   # shortcut trong Startup folder
    autostart_linux.py      # systemd --user unit
    autostart.py              # dispatcher theo OS

  gui/
    main_window.py   # 3 tab: Databases / History / Logs
    dialogs.py         # Add/Edit database, Restore
    tray.py              # system tray, menu Backup Now theo từng DB

  main.py   # entry point, nối các module lại, cầu nối thread-safe scheduler -> GUI
```

## Nguyên tắc an toàn đã áp dụng

- **Không bao giờ ghi vào file database gốc**: nguồn luôn mở `mode=ro`;
  copy bằng SQLite Online Backup API (`sqlite3.Connection.backup()`).
- **Chỉ backup khi có thay đổi**: fingerprint (size/mtime/hash mẫu) so với
  lần backup thành công gần nhất; `force=True` khi bấm "Backup Now".
- **Integrity trước khi tin bất cứ file nào**: sau khi tạo snapshot, sau khi
  tải file từ Drive về để restore, và sau khi ghi đè vào vị trí thật.
- **Retention chỉ chạy sau khi upload bản mới được xác nhận thành công**
  (`backup_service.run_backup`: `apply_retention()` chỉ được gọi sau dòng
  `upload_snapshot()` trả về id thành công).
- **Restore luôn tự backup bản hiện tại lên Drive trước** rồi mới ghi đè,
  và ghi đè bằng cách viết ra file tạm cùng thư mục rồi `os.replace()`
  (atomic), không bao giờ mở file đích ở chế độ ghi trực tiếp.
- **Retry mạng**: `drive_client.py` dùng `tenacity` với exponential backoff
  + jitter, chỉ retry lỗi tạm thời (mất mạng, 429/5xx), không retry lỗi cần
  con người xử lý (401/403/404).

## Test

```bash
pytest tests/
```

`change_detector`, `backup_engine`, `drive_layout`, `retention` đều test
được mà không cần mạng hay Google credentials — phần duy nhất phụ thuộc
mạng (`drive_client.py`) được tách riêng và giữ mỏng (thin wrapper) để rủi
ro nằm ở một chỗ dễ kiểm soát.

## Icon ứng dụng

Nằm trong `assets/`:
- `icon.svg` — bản vector gốc (chỉnh sửa/thiết kế lại thì sửa file này).
- `icon.ico` — dùng cho Windows (chứa sẵn 16/24/32/48/64/128/256px trong 1 file).
- `icon.png`, `icon_16.png` ... `icon_256.png` — dùng cho Linux (taskbar, tray,
  file .desktop) và làm nguồn build lại .ico nếu cần.

App tự nạp icon qua `app/gui/icons.py` — ưu tiên `icon.ico`, sau đó `icon.png`,
và chỉ vẽ icon tạm bằng code nếu cả hai đều thiếu. `icons.py` tự nhận diện khi
chạy từ file .exe/binary đã đóng gói (PyInstaller `sys._MEIPASS`) lẫn khi chạy
trực tiếp từ source, nên không cần chỉnh gì thêm giữa 2 trường hợp.

## Đóng gói thành file thực thi (tuỳ chọn)

```bash
pip install pyinstaller
python packaging/build.py
```

Script `packaging/build.py` tự chọn đúng icon theo hệ điều hành (`icon.ico`
trên Windows, `icon.png` trên Linux) và đóng gói kèm cả thư mục `assets/`
vào bản build, nên icon vẫn hiển thị đúng trên file .exe/binary thành phẩm
chứ không chỉ khi chạy `python -m app.main`. Kết quả nằm trong
`dist/DatabaseBackupManager/`.

Muốn icon xuất hiện trong menu ứng dụng trên Linux (không chỉ khi chạy từ
terminal), dùng file mẫu `packaging/dbbackup.desktop` — xem hướng dẫn cài
đặt ngay trong file đó.

Trên Windows nhớ cài thêm `pywin32` (đã có trong requirements khi chạy trên
Windows) để tạo shortcut Startup; trên Linux không cần thêm gì, chỉ cần
`systemctl` có sẵn (mặc định trên Ubuntu).

## Cập nhật giao diện (bản mới nhất)

- **Giao diện tiếng Việt** toàn bộ (menu tray, tab, dialog, thông báo).
- **Tab Database** giờ hiển thị dạng cây thư mục (mỗi database là một node,
  bấm mở ra xem chi tiết: đường dẫn, lịch, retention, Latest, lần backup
  gần nhất...). Có 2 nút **Mở rộng tất cả** / **Thu gọn tất cả**. Trạng
  thái được tô màu (xanh = thành công, đỏ = thất bại, xám = chưa backup).
  Các nút Sửa / Xóa / Backup ngay / Khôi phục chỉ hiện ra khi đã chọn một
  database, ẩn đi khi chưa chọn gì.
- Dòng trạng thái **Google Drive** hiển thị màu (● xanh/đỏ) kèm **email
  tài khoản** đang đăng nhập.
- Nếu chưa có `credentials.json`, khi bấm **Đăng nhập Google Drive** app sẽ
  tự hiện hộp thoại cho chọn file (hoạt động giống nhau trên cả Windows và
  Linux) thay vì chỉ báo lỗi — chọn xong app tự copy vào đúng vị trí và thử
  đăng nhập lại ngay.
- **Log tự động xoá bớt**: file log dùng `RotatingFileHandler` (5MB x 5
  file, tối đa ~30MB, tự xoay vòng — không cần dọn tay). Ngoài ra có nút
  **Xóa log** trong tab Nhật ký để dọn ngay nếu muốn. Lịch sử backup/restore
  (tab Lịch sử) cũng được dọn bớt tự động khi khởi động app
  (`HistoryStore.trim_old`, mặc định giữ các bản ghi trong 180 ngày, không
  bao giờ xóa xuống dưới 500 bản ghi gần nhất).

## Chống mở 2 phiên bản app cùng lúc (single-instance)

Có. `app/core/single_instance.py` dùng `QSharedMemory` + `QLocalServer` của
Qt (không cần thư viện thêm, hoạt động giống nhau trên Windows và Ubuntu):

- Mở app lần 2 bằng cách bấm icon/shortcut như bình thường → tiến trình mới
  phát hiện đã có phiên bản đang chạy, gửi yêu cầu qua IPC để phiên bản đó
  tự hiện cửa sổ lên (`showNormal + raise_ + activateWindow`), rồi thoát
  ngay — không tạo thêm scheduler/tray/cửa sổ thứ hai.
- Autostart chạy `--background` khi app đã đang chạy sẵn (ví dụ user vừa mở
  tay app, rồi máy lại kích hoạt autostart do một tác vụ khác) → thoát êm,
  không tự bật cửa sổ lên làm phiền.
- Có xử lý trường hợp hiếm trên Linux: tiến trình trước bị `kill -9` để sót
  shared memory/socket → lần khởi động sau tự phát hiện (ping IPC không có
  phản hồi) và dọn rác thay vì bị kẹt vĩnh viễn không mở lại được app.
