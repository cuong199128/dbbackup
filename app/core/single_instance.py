"""Chống mở 2 phiên bản app cùng lúc (single-instance), hoạt động giống
nhau trên cả Windows và Ubuntu vì chỉ dùng QSharedMemory + QLocalServer
(Qt tự lo phần khác nhau giữa các OS bên dưới, ta không cần code riêng).

Vì sao cần: hai tiến trình cùng chạy sẽ có 2 APScheduler cùng backup theo
lịch của cùng một database (tốn tài nguyên, có thể tạo 2 snapshot gần như
cùng lúc), 2 icon tray, 2 cửa sổ — rất dễ gây nhầm lẫn và xung đột ghi
config.json.

Cách hoạt động:
  1. Thử tạo một vùng QSharedMemory với key cố định. Nếu tạo được -> đây là
     phiên bản đầu tiên (giữ vùng nhớ này sống suốt vòng đời app, vùng nhớ
     tự giải phóng khi tiến trình kết thúc, kể cả khi crash trên hầu hết
     trường hợp).
  2. Nếu tạo thất bại vì đã tồn tại -> đã có phiên bản khác đang chạy. Gửi
     một thông điệp ngắn qua QLocalSocket tới QLocalServer của phiên bản
     đó để yêu cầu nó tự hiện cửa sổ lên, rồi thoát ngay tiến trình mới.
  3. Trường hợp Linux hiếm gặp: tiến trình trước bị kill cứng (kill -9) có
     thể để sót vùng QSharedMemory/socket. Ta phát hiện bằng cách thử
     attach() rồi detach() ngay trước khi tạo lại — nếu server không phản
     hồi trong bước 2, coi như đó là rác sót lại và tự dọn để khởi động
     bình thường thay vì kẹt cứng vĩnh viễn không mở được app nữa.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from app.logger import get_logger

log = get_logger("single_instance")

_SHARED_MEM_KEY = "DatabaseBackupManager-singleinstance-v1"
_LOCAL_SERVER_NAME = "DatabaseBackupManager-ipc-v1"
_SHOW_COMMAND = b"SHOW\n"
_PING_TIMEOUT_MS = 1500


class SingleInstanceGuard(QObject):
    """Gọi is_already_running() ngay sau khi tạo QApplication, TRƯỚC khi
    tạo MainWindow/tray/scheduler. Nếu True thì thoát app luôn (đã có
    phiên bản khác lo phần còn lại).
    """

    show_requested = Signal()  # phát ra khi có tiến trình thứ 2 xin hiện cửa sổ

    def __init__(self):
        super().__init__()
        from PySide6.QtCore import QSharedMemory

        self._shared_mem = QSharedMemory(_SHARED_MEM_KEY)
        self._server: QLocalServer | None = None

    def is_already_running(self) -> bool:
        # Bước 3: dọn rác nếu tiến trình trước bị kill cứng — thử attach rồi
        # detach ngay; nếu server IPC không phản hồi ping thì coi là rác cũ.
        if self._shared_mem.attach():
            self._shared_mem.detach()
            if not self._ping_existing_server():
                log.warning("Phát hiện shared memory/socket cũ còn sót lại (có thể do lần trước bị tắt đột ngột) — dọn để khởi động lại bình thường.")
                QLocalServer.removeServer(_LOCAL_SERVER_NAME)
            else:
                return True

        if self._shared_mem.create(1):
            self._start_server()
            return False

        # create() thất bại dù attach() ở trên không thấy gì tồn tại —
        # trường hợp hiếm do race condition giữa 2 tiến trình khởi động
        # gần như đồng thời. Coi như đã có phiên bản khác đang chạy.
        return True

    def _ping_existing_server(self) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(_LOCAL_SERVER_NAME)
        ok = sock.waitForConnected(_PING_TIMEOUT_MS)
        if ok:
            sock.disconnectFromServer()
        return ok

    def notify_running_instance(self, request_show: bool = True) -> None:
        """Gọi khi is_already_running() trả về True. request_show=False khi
        tiến trình mới được autostart chạy nền (--background) — không cần
        làm phiền người dùng bằng việc tự bật cửa sổ lên.
        """
        if not request_show:
            log.info("Đã có phiên bản khác đang chạy — thoát êm (chế độ nền).")
            return
        sock = QLocalSocket()
        sock.connectToServer(_LOCAL_SERVER_NAME)
        if sock.waitForConnected(_PING_TIMEOUT_MS):
            sock.write(_SHOW_COMMAND)
            sock.waitForBytesWritten(_PING_TIMEOUT_MS)
            sock.disconnectFromServer()
            log.info("Đã có phiên bản khác đang chạy — yêu cầu hiện cửa sổ đó lên.")
        else:
            log.warning("Đã có phiên bản khác đang chạy nhưng không thể kết nối để yêu cầu hiện cửa sổ.")

    def _start_server(self) -> None:
        QLocalServer.removeServer(_LOCAL_SERVER_NAME)  # dọn socket rác từ lần chạy trước (nếu có)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(_LOCAL_SERVER_NAME):
            log.warning("Không thể mở IPC server single-instance: %s", self._server.errorString())

    def _on_new_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda: self._on_ready_read(conn))
        conn.disconnected.connect(conn.deleteLater)

    def _on_ready_read(self, conn) -> None:
        data = bytes(conn.readAll())
        if _SHOW_COMMAND.strip() in data:
            self.show_requested.emit()
