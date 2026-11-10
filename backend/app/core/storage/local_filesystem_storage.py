from pathlib import Path
from app.core.storage.storage_service import validate_storage_key

class LocalFilesystemStorage:
    def __init__(self, root: Path):
        self._root = root.resolve()

    def _resolve(self, key: str) -> Path:
        candidate = (self._root / validate_storage_key(key)).resolve()
        if self._root not in candidate.parents and candidate != self._root:
            raise ValueError('La clave escapa del storage root')
        return candidate

    def put(self, key: str, data: bytes) -> None:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.is_file():
            raise FileNotFoundError(key)
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def delete(self, key: str) -> bool:
        target = self._resolve(key)
        if not target.is_file():
            return False
        target.unlink()
        return True
