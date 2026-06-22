"""Base repository for working with JSON files."""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Generic, TypeVar

from ..exceptions import FileStorageError

# Generic type variable for typing repositories
T = TypeVar("T")

logger = logging.getLogger(__name__)


class BaseRepository(Generic[T]):
    """
    Base repository class for working with JSON files.

    Provides CRUD operations with automatic serialization/deserialization.
    """

    def __init__(self, file_path: Path):
        """
        Initialize the repository.

        Args:
            file_path: Path to the JSON file
        """
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the file with empty data if it does not exist."""
        if not self.file_path.exists():
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json(self._get_empty_data())

    def _get_empty_data(self) -> Any:
        """
        Return an empty data structure for initialization.

        Should be overridden in subclasses.

        Returns:
            Any: Empty structure (usually [] or {})
        """
        return []

    def _read_json(self) -> Any:
        """
        Read and parse the JSON file.

        On a JSON decode error, the corrupted file is backed up with a
        timestamp, reset to empty data, and the empty data is returned.

        Returns:
            Any: Parsed data

        Raises:
            FileStorageError: If the file cannot be read (OS/IO error)
        """
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in {self.file_path}: {e}")
            # Create a timestamped backup to avoid overwriting it
            backup_path = self._create_timestamped_backup(self.file_path)
            logger.warning(f"Created backup of corrupted file: {backup_path}")
            self._write_json(self._get_empty_data())
            return self._get_empty_data()
        except (OSError, IOError) as e:
            logger.error(f"Error reading file {self.file_path}: {e}", exc_info=True)
            raise FileStorageError(f"Failed to read {self.file_path}: {e}") from e

    def _write_json(self, data: Any) -> None:
        """
        Atomically write data to the JSON file.

        Uses a write-to-temp-then-rename pattern to prevent data loss
        during concurrent operations or failures.

        Args:
            data: Data to write

        Raises:
            FileStorageError: If the data cannot be serialized or written
        """
        temp_path: str | None = None
        try:
            # Create the temp file in the same directory
            # (required for os.replace to work correctly across all OSes)
            fd, temp_path = tempfile.mkstemp(
                dir=self.file_path.parent,
                prefix=f".{self.file_path.stem}_",
                suffix=".tmp",
            )

            # Write the data to the temp file
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2,
                    default=str,  # Converts datetime and other objects to strings
                )

            # Atomically move the temp file into the target location
            # os.replace() is atomic on both Windows and Unix
            os.replace(temp_path, self.file_path)
            temp_path = None  # Moved successfully, nothing to clean up

        except (OSError, IOError, TypeError, ValueError) as e:
            logger.error(f"Error writing file {self.file_path}: {e}", exc_info=True)
            raise FileStorageError(f"Failed to write {self.file_path}: {e}") from e

        finally:
            # Clean up the temp file on error
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _create_timestamped_backup(self, source_path: Path) -> Path:
        """
        Create a timestamped backup (prevents overwriting an existing backup).

        Renames the source file to the backup path; the original path is left
        without a file until the caller writes new data.

        Args:
            source_path: Path to the source file

        Returns:
            Path: Path to the created backup file
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = source_path.with_suffix(f".{timestamp}.backup")
        source_path.rename(backup_path)
        return backup_path

    def load_all(self) -> list[dict[str, Any]]:
        """
        Load all data from the file.

        If the stored data is a dict, its values are returned as a list.

        Returns:
            List[Dict[str, Any]]: List of all records
        """
        data = self._read_json()
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return list(data.values())
        else:
            logger.warning(f"Unexpected data type in {self.file_path}: {type(data)}")
            return []

    def save_all(self, data: list[dict[str, Any]]) -> None:
        """
        Save all data to the file.

        Args:
            data: List of records to save
        """
        self._write_json(data)
