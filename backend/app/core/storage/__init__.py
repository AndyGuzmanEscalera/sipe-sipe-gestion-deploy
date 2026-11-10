from app.core.storage.local_filesystem_storage import LocalFilesystemStorage
from app.core.storage.storage_service import StorageService, validate_storage_key
from app.core.config import get_settings

def get_storage_service() -> StorageService:
    root = get_settings().storage_root
    root.mkdir(parents=True, exist_ok=True)
    return LocalFilesystemStorage(root)

__all__ = ['LocalFilesystemStorage', 'StorageService', 'validate_storage_key', 'get_storage_service']
