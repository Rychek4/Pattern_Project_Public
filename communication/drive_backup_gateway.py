"""
Pattern Project - Google Drive Backup Gateway
OAuth2-based Google Drive API integration for backing up the Pattern database.

This module uploads compressed SQLite snapshots to a dedicated Google Drive
folder and prunes old backups beyond a configurable retention count. On first
use, it triggers a browser-based OAuth consent flow. After consent, tokens
are saved locally and auto-refresh.

Uses the drive.file scope so the app can only see files it created — it
cannot access any other files on your Drive.
"""

import gzip
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.logger import log_info, log_error, log_success, log_warning


@dataclass
class BackupResult:
    """
    Result from a drive backup operation.

    Attributes:
        success: Whether the operation succeeded
        message: Status message (success info or error description)
        data: Structured result data (file metadata, list of backups, etc.)
        timestamp: When the operation occurred
    """
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{status}: {self.message}"


class DriveBackupGateway:
    """
    Google Drive backup gateway using the Drive API v3.

    Handles OAuth2 authentication with automatic token refresh.
    On first use, opens a browser for user consent. After consent,
    the token is stored locally and refreshed automatically.

    Uses the drive.file scope (can only see files created by this app).
    """

    # Restricted scope: only files created by this application
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        folder_name: str = "Pattern Backups",
        retention_count: int = 7,
    ):
        """
        Initialize the drive backup gateway.

        Args:
            credentials_path: Path to the OAuth2 credentials JSON from Google Cloud Console
            token_path: Path where the OAuth2 token will be saved/loaded
            folder_name: Name of the Drive folder to store backups in
            retention_count: Number of backups to keep (older ones are deleted)
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.folder_name = folder_name
        self.retention_count = retention_count
        self._service = None
        self._folder_id: Optional[str] = None

    def is_available(self) -> bool:
        """
        Check if the gateway is properly configured.

        Returns:
            True if the credentials file exists, False otherwise
        """
        return os.path.exists(self.credentials_path)

    def _get_service(self):
        """
        Get or create the authenticated Google Drive API service.

        On first call (no token file), opens a browser for OAuth consent.
        On subsequent calls, loads the saved token and refreshes if needed.

        Returns:
            Authenticated Google Drive API service object

        Raises:
            RuntimeError: If credentials file is missing or auth fails
        """
        if self._service is not None:
            return self._service

        if not self.is_available():
            raise RuntimeError(
                f"Google Drive credentials not found at {self.credentials_path}. "
                "Download OAuth2 credentials from Google Cloud Console."
            )

        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None

        # Load existing token if available
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(
                    self.token_path, self.SCOPES
                )
                log_info("Loaded existing Google Drive token")
            except Exception as e:
                log_warning(f"Failed to load Drive token, will re-authenticate: {e}")
                creds = None

        # Refresh or obtain new credentials
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                log_info("Refreshed Google Drive token")
            except Exception as e:
                log_warning(f"Drive token refresh failed, will re-authenticate: {e}")
                creds = None

        if not creds or not creds.valid:
            log_info("Starting Google Drive OAuth consent flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path, self.SCOPES
            )
            creds = flow.run_local_server(port=0)
            log_success("Google Drive OAuth consent completed")

            # Save token for future use
            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())
            log_info(f"Saved Google Drive token to {self.token_path}")

        self._service = build("drive", "v3", credentials=creds)
        log_success("Google Drive API service initialized")
        return self._service

    def _get_or_create_folder(self) -> str:
        """
        Get or create the backup folder on Google Drive.

        Searches for an existing folder with the configured name. If not
        found, creates one. Caches the folder ID for subsequent calls.

        Returns:
            The Google Drive folder ID

        Raises:
            RuntimeError: If folder creation fails
        """
        if self._folder_id is not None:
            return self._folder_id

        service = self._get_service()

        # Search for existing folder
        query = (
            f"name = '{self.folder_name}' "
            "and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        results = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name)",
            pageSize=1,
        ).execute()

        files = results.get("files", [])
        if files:
            self._folder_id = files[0]["id"]
            log_info(f"Found existing Drive folder '{self.folder_name}'")
            return self._folder_id

        # Create the folder
        folder_metadata = {
            "name": self.folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        folder = service.files().create(
            body=folder_metadata,
            fields="id",
        ).execute()

        self._folder_id = folder["id"]
        log_success(f"Created Drive folder '{self.folder_name}'")
        return self._folder_id

    def run_backup(self, db_path: str) -> BackupResult:
        """
        Perform a full backup: snapshot the database, compress, upload, and prune.

        Args:
            db_path: Path to the SQLite database file to back up

        Returns:
            BackupResult with upload metadata on success
        """
        if not os.path.exists(db_path):
            return BackupResult(
                success=False,
                message=f"Database not found at {db_path}",
            )

        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix="pattern_backup_")
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")

            # Step 1: Safe SQLite snapshot using .backup command
            snapshot_path = os.path.join(tmp_dir, "pattern_snapshot.db")
            log_info("Creating SQLite snapshot...")
            src_conn = sqlite3.connect(db_path)
            dst_conn = sqlite3.connect(snapshot_path)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            log_info("SQLite snapshot complete")

            # Step 2: Compress with gzip
            gz_filename = f"pattern_backup_{timestamp}.db.gz"
            gz_path = os.path.join(tmp_dir, gz_filename)
            log_info("Compressing snapshot...")
            with open(snapshot_path, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)

            original_size = os.path.getsize(snapshot_path)
            compressed_size = os.path.getsize(gz_path)
            log_info(
                f"Compressed {original_size / 1024 / 1024:.1f} MB → "
                f"{compressed_size / 1024 / 1024:.1f} MB"
            )

            # Step 3: Upload to Google Drive
            upload_result = self._upload_file(gz_path, gz_filename)
            if not upload_result.success:
                return upload_result

            # Step 4: Prune old backups
            prune_result = self._prune_old_backups()
            prune_msg = ""
            if prune_result.success and prune_result.data:
                deleted_count = prune_result.data.get("deleted_count", 0)
                if deleted_count > 0:
                    prune_msg = f", pruned {deleted_count} old backup(s)"

            return BackupResult(
                success=True,
                message=(
                    f"Backup uploaded: {gz_filename} "
                    f"({compressed_size / 1024 / 1024:.1f} MB)"
                    f"{prune_msg}"
                ),
                data={
                    "filename": gz_filename,
                    "file_id": upload_result.data.get("file_id") if upload_result.data else None,
                    "original_size_bytes": original_size,
                    "compressed_size_bytes": compressed_size,
                    "timestamp": timestamp,
                },
            )

        except RuntimeError as e:
            log_error(f"Drive backup gateway error: {e}")
            return BackupResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Drive backup failed: {e}")
            return BackupResult(success=False, message=f"Backup failed: {str(e)}")
        finally:
            # Clean up temp files
            if tmp_dir and os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _upload_file(self, file_path: str, filename: str) -> BackupResult:
        """
        Upload a file to the backup folder on Google Drive.

        Args:
            file_path: Local path to the file to upload
            filename: Name to give the file on Drive

        Returns:
            BackupResult with file metadata on success
        """
        try:
            from googleapiclient.http import MediaFileUpload

            service = self._get_service()
            folder_id = self._get_or_create_folder()

            file_metadata = {
                "name": filename,
                "parents": [folder_id],
            }

            media = MediaFileUpload(
                file_path,
                mimetype="application/gzip",
                resumable=True,
            )

            log_info(f"Uploading {filename} to Google Drive...")
            uploaded = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, name, size",
            ).execute()

            log_success(f"Uploaded backup to Drive: {filename}")

            return BackupResult(
                success=True,
                message=f"Uploaded: {filename}",
                data={
                    "file_id": uploaded.get("id"),
                    "name": uploaded.get("name"),
                    "size": uploaded.get("size"),
                },
            )

        except Exception as e:
            log_error(f"Failed to upload backup to Drive: {e}")
            return BackupResult(
                success=False,
                message=f"Upload failed: {str(e)}",
            )

    def list_backups(self) -> BackupResult:
        """
        List all backups in the Drive backup folder.

        Returns:
            BackupResult with list of backup file metadata
        """
        try:
            service = self._get_service()
            folder_id = self._get_or_create_folder()

            query = (
                f"'{folder_id}' in parents "
                "and trashed = false"
            )
            results = service.files().list(
                q=query,
                spaces="drive",
                fields="files(id, name, size, createdTime)",
                orderBy="createdTime desc",
                pageSize=100,
            ).execute()

            files = results.get("files", [])
            log_info(f"Found {len(files)} backup(s) on Drive")

            return BackupResult(
                success=True,
                message=f"Found {len(files)} backup(s)",
                data=[
                    {
                        "file_id": f["id"],
                        "name": f["name"],
                        "size": f.get("size"),
                        "created": f.get("createdTime"),
                    }
                    for f in files
                ],
            )

        except RuntimeError as e:
            log_error(f"Drive backup gateway error: {e}")
            return BackupResult(success=False, message=str(e))
        except Exception as e:
            log_error(f"Failed to list Drive backups: {e}")
            return BackupResult(
                success=False,
                message=f"Failed to list backups: {str(e)}",
            )

    def _prune_old_backups(self) -> BackupResult:
        """
        Delete backups beyond the retention count (oldest first).

        Returns:
            BackupResult with count of deleted backups
        """
        try:
            service = self._get_service()
            folder_id = self._get_or_create_folder()

            query = (
                f"'{folder_id}' in parents "
                "and trashed = false"
            )
            results = service.files().list(
                q=query,
                spaces="drive",
                fields="files(id, name, createdTime)",
                orderBy="createdTime desc",
                pageSize=100,
            ).execute()

            files = results.get("files", [])

            if len(files) <= self.retention_count:
                return BackupResult(
                    success=True,
                    message="No backups to prune",
                    data={"deleted_count": 0},
                )

            # Delete oldest files beyond retention count
            to_delete = files[self.retention_count:]
            deleted_count = 0

            for f in to_delete:
                try:
                    service.files().delete(fileId=f["id"]).execute()
                    log_info(f"Pruned old backup: {f['name']}")
                    deleted_count += 1
                except Exception as e:
                    log_warning(f"Failed to prune backup {f['name']}: {e}")

            log_info(f"Pruned {deleted_count} old backup(s)")
            return BackupResult(
                success=True,
                message=f"Pruned {deleted_count} old backup(s)",
                data={"deleted_count": deleted_count},
            )

        except Exception as e:
            log_error(f"Failed to prune Drive backups: {e}")
            return BackupResult(
                success=False,
                message=f"Failed to prune backups: {str(e)}",
            )


# Singleton instance
_gateway: Optional[DriveBackupGateway] = None


def get_drive_backup_gateway() -> DriveBackupGateway:
    """
    Get the global drive backup gateway instance.

    Returns:
        The global DriveBackupGateway instance

    Raises:
        RuntimeError: If gateway not initialized
    """
    if _gateway is None:
        raise RuntimeError(
            "Drive backup gateway not initialized. Call init_drive_backup_gateway() first."
        )
    return _gateway


def init_drive_backup_gateway(
    credentials_path: Optional[str] = None,
    token_path: Optional[str] = None,
    folder_name: Optional[str] = None,
    retention_count: Optional[int] = None,
) -> DriveBackupGateway:
    """
    Initialize the global drive backup gateway instance.

    Args:
        credentials_path: Path to OAuth2 credentials JSON (defaults to config)
        token_path: Path to save/load OAuth2 token (defaults to config)
        folder_name: Drive folder name for backups (defaults to config)
        retention_count: Number of backups to keep (defaults to config)

    Returns:
        The initialized DriveBackupGateway instance
    """
    global _gateway

    from config import (
        GOOGLE_DRIVE_BACKUP_CREDENTIALS_PATH,
        GOOGLE_DRIVE_BACKUP_TOKEN_PATH,
        GOOGLE_DRIVE_BACKUP_FOLDER_NAME,
        GOOGLE_DRIVE_BACKUP_RETENTION_COUNT,
    )

    _gateway = DriveBackupGateway(
        credentials_path=credentials_path or GOOGLE_DRIVE_BACKUP_CREDENTIALS_PATH,
        token_path=token_path or GOOGLE_DRIVE_BACKUP_TOKEN_PATH,
        folder_name=folder_name or GOOGLE_DRIVE_BACKUP_FOLDER_NAME,
        retention_count=retention_count if retention_count is not None else GOOGLE_DRIVE_BACKUP_RETENTION_COUNT,
    )

    if _gateway.is_available():
        log_info("Google Drive backup gateway initialized")
    else:
        log_warning(
            "Google Drive backup gateway initialized but credentials not found at "
            f"{_gateway.credentials_path}"
        )

    return _gateway


def run_drive_backup(db_path: Optional[str] = None) -> BackupResult:
    """
    Convenience function: run a backup using the global gateway.

    Args:
        db_path: Path to the database (defaults to config DATABASE_PATH)

    Returns:
        BackupResult from the backup operation
    """
    from config import DATABASE_PATH

    gateway = get_drive_backup_gateway()
    return gateway.run_backup(db_path or str(DATABASE_PATH))
