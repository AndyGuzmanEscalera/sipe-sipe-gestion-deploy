from pathlib import PurePosixPath
from typing import BinaryIO, Protocol

class StorageService(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> bool: ...

def validate_storage_key(key: str) -> str:
    normalized = key.strip().replace('\\', '/')
    if not normalized or normalized.startswith('/') or PurePosixPath(normalized).is_absolute() or '..' in PurePosixPath(normalized).parts:
        raise ValueError('Clave de almacenamiento inválida')
    return normalized
