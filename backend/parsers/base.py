from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from graph.context import RepoContext


@dataclass
class RawImport:
    module: str            # e.g. "os.path", "..utils.helpers", "./utils", "crate::foo"
    is_relative: bool      # starts with . (Python/JS) or self/super/crate (Rust)
    symbol: Optional[str]  # first imported name for symbol annotation
    line: int              # 1-based source line
    is_dynamic: bool = False          # import() with template string
    target_pattern: Optional[str] = None  # e.g. "./locales/*.js"


class LanguageHandler(ABC):
    language_name: str

    @abstractmethod
    def extract_imports(self, source_bytes: bytes) -> tuple[list[RawImport], bool]:
        """Return (imports, parse_error)."""

    @abstractmethod
    def resolve_import(
        self,
        raw: RawImport,
        file_path: str,
        ctx: "RepoContext",
    ) -> Optional[str]:
        """Resolve to a repo-relative file path, or None if external/unresolvable."""
