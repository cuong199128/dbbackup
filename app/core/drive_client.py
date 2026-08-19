"""Thin wrapper around the Google Drive v3 API.

This is the ONLY place in the whole project (and the only place any of the
backed-up apps ever need) that talks to Google. Other Python apps being
backed up never need their own Drive integration — Database Backup Manager
reads their .db file from disk and does all the uploading itself.

OAuth: "installed app" flow, run once interactively (opens a browser),
then cached as a refresh token in token.json. All subsequent runs —
including the background/tray process — reuse the cached token and refresh
silently.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import credentials_path, token_path
from app.core.drive_layout import DrivePathParts
from app.logger import get_logger

log = get_logger("drive_client")

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveAuthError(RuntimeError):
    pass


def _is_retryable(exc: BaseException) -> bool:
    """Retry on network errors and Drive's transient 5xx / 429 responses.
    Do NOT retry on 401/403/404 — those need a human (re-auth, permissions,
    wrong file id) not a retry loop.
    """
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        return status in (429, 500, 502, 503, 504)
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def drive_retry(fn):
    return retry(
        reraise=True,
        stop=stop_after_attempt(6),
        wait=wait_exponential_jitter(initial=1, max=60),
        retry=retry_if_exception(_is_retryable),
    )(fn)


@dataclass
class DriveFileInfo:
    id: str
    name: str
    size: int
    modified_time: str


class DriveClient:
    def __init__(self):
        self._service = None
        self._folder_id_cache: dict[str, str] = {}  # "parentId/name" -> id

    # ---------------------------------------------------------------- auth
    def is_logged_in(self) -> bool:
        return token_path().exists()

    def login_interactive(self) -> None:
        """Runs the OAuth consent flow in a local browser tab. Called once
        by the user from the GUI's Login button. Requires the user to have
        placed their downloaded OAuth client credentials.json in the app
        data dir first.
        """
        if not credentials_path().exists():
            raise DriveAuthError(
                f"Missing OAuth client file at {credentials_path()}. "
                "Download it from Google Cloud Console (OAuth client, "
                "type 'Desktop app') and place it there, then try again."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path()), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path().write_text(creds.to_json(), encoding="utf-8")
        log.info("Google Drive login successful; token cached at %s", token_path())
        self._service = None  # force rebuild with new creds

    def logout(self) -> None:
        if token_path().exists():
            token_path().unlink()
        self._service = None

    def _credentials(self) -> Credentials:
        if not token_path().exists():
            raise DriveAuthError("Not logged in to Google Drive yet.")
        creds = Credentials.from_authorized_user_file(str(token_path()), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path().write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _svc(self):
        if self._service is None:
            self._service = build("drive", "v3", credentials=self._credentials(), cache_discovery=False)
        return self._service

    @drive_retry
    def get_account_email(self) -> str:
        """Email của tài khoản Google Drive đang đăng nhập — dùng để hiển
        thị bên cạnh trạng thái 'Connected' trên giao diện.
        """
        about = self._svc().about().get(fields="user(emailAddress)").execute()
        return about.get("user", {}).get("emailAddress", "")

    # ------------------------------------------------------------ folders
    @drive_retry
    def _find_child(self, parent_id: str, name: str, mime: Optional[str] = None) -> Optional[str]:
        safe_name = name.replace("'", "\\'")
        q = f"'{parent_id}' in parents and name = '{safe_name}' and trashed = false"
        if mime:
            q += f" and mimeType = '{mime}'"
        resp = self._svc().files().list(q=q, fields="files(id,name)", pageSize=1).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    @drive_retry
    def _create_folder(self, parent_id: str, name: str) -> str:
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        f = self._svc().files().create(body=body, fields="id").execute()
        return f["id"]

    def ensure_folder_path(self, segments: Iterable[str]) -> str:
        """Walks/creates folders segment by segment starting from 'root',
        returns the final folder's id. Cached so repeated backups don't
        re-resolve the same path every time.
        """
        parent_id = "root"
        for seg in segments:
            cache_key = f"{parent_id}/{seg}"
            cached = self._folder_id_cache.get(cache_key)
            if cached:
                parent_id = cached
                continue
            existing = self._find_child(parent_id, seg, mime=FOLDER_MIME)
            folder_id = existing or self._create_folder(parent_id, seg)
            self._folder_id_cache[cache_key] = folder_id
            parent_id = folder_id
        return parent_id

    # ------------------------------------------------------------- upload
    @drive_retry
    def upload_snapshot(self, local_path: Path, parts: DrivePathParts) -> str:
        """Always creates a new file (snapshots are never overwritten)."""
        folder_id = self.ensure_folder_path(parts.folder_segments)
        media = MediaFileUpload(str(local_path), mimetype="application/octet-stream", resumable=True)
        body = {"name": parts.filename, "parents": [folder_id]}
        f = self._svc().files().create(body=body, media_body=media, fields="id").execute()
        log.info("Uploaded snapshot to Drive: %s -> id=%s", parts.full_path, f["id"])
        return f["id"]

    @drive_retry
    def upload_or_replace(self, local_path: Path, parts: DrivePathParts) -> str:
        """Used for the 'Latest' mirror: overwrite in place if it already
        exists so the file keeps one stable id/URL, otherwise create it.
        """
        folder_id = self.ensure_folder_path(parts.folder_segments)
        existing_id = self._find_child(folder_id, parts.filename)
        media = MediaFileUpload(str(local_path), mimetype="application/octet-stream", resumable=True)
        if existing_id:
            self._svc().files().update(fileId=existing_id, media_body=media).execute()
            log.info("Updated Latest mirror on Drive: %s", parts.full_path)
            return existing_id
        body = {"name": parts.filename, "parents": [folder_id]}
        f = self._svc().files().create(body=body, media_body=media, fields="id").execute()
        log.info("Created Latest mirror on Drive: %s", parts.full_path)
        return f["id"]

    # --------------------------------------------------------------- list
    @drive_retry
    def list_snapshots(self, app_name: str) -> list[DriveFileInfo]:
        """Lists every snapshot .db under <app_name>/*/*/*.db (i.e. under
        the year/month-day subfolders), skipping the root-level Latest file.
        """
        from app.core.drive_layout import app_root_segments

        app_folder_id = self.ensure_folder_path(app_root_segments(app_name))
        results: list[DriveFileInfo] = []
        for year_id in self._list_subfolders(app_folder_id):
            for day_id in self._list_subfolders(year_id):
                results.extend(self._list_files_in(day_id))
        results.sort(key=lambda f: f.modified_time)
        return results

    @drive_retry
    def _list_subfolders(self, parent_id: str) -> list[str]:
        q = f"'{parent_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false"
        resp = self._svc().files().list(q=q, fields="files(id)", pageSize=1000).execute()
        return [f["id"] for f in resp.get("files", [])]

    @drive_retry
    def _list_files_in(self, parent_id: str) -> list[DriveFileInfo]:
        q = f"'{parent_id}' in parents and mimeType != '{FOLDER_MIME}' and trashed = false"
        resp = (
            self._svc()
            .files()
            .list(q=q, fields="files(id,name,size,modifiedTime)", pageSize=1000)
            .execute()
        )
        return [
            DriveFileInfo(id=f["id"], name=f["name"], size=int(f.get("size", 0)), modified_time=f["modifiedTime"])
            for f in resp.get("files", [])
        ]

    # ------------------------------------------------------------- delete
    @drive_retry
    def delete_file(self, file_id: str) -> None:
        self._svc().files().delete(fileId=file_id).execute()
        log.info("Deleted Drive file id=%s", file_id)

    # ----------------------------------------------------------- download
    @drive_retry
    def download_file(self, file_id: str, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        request = self._svc().files().get_media(fileId=file_id)
        fh = io.FileIO(str(dest_path), "wb")
        try:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        finally:
            fh.close()
        log.info("Downloaded Drive file id=%s -> %s", file_id, dest_path)
        return dest_path
