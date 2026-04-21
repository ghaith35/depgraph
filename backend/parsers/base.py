from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RawImport:
    module: str           # e.g. "os.path", "..utils.helpers", "."
    is_relative: bool
    symbol: Optional[str] # first imported name, e.g. "Path" from "from pathlib import Path"
    line: int             # 1-based source line


class LanguageHandler(ABC):
    @abstractmethod
    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        """
        Parse source_bytes and return (imports, parse_error).
        parse_error=True means the file had parse errors but we still tried.
        """

    @abstractmethod
    def resolve_import(
        self,
        raw: RawImport,
        file_path: str,
        repo_root: Path,
    ) -> Optional[str]:
        """
        Resolve a raw import to a relative file path within the repo.
        Returns None if the import is external / unresolvable.
        """
