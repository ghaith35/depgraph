import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS_KEY",    re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GH_TOKEN",   re.compile(r"(ghp|gho|ghs|ghu)_[a-zA-Z0-9]{36}")),
    ("GH_PAT",     re.compile(r"github_pat_[a-zA-Z0-9_]{82}")),
    ("STRIPE_KEY", re.compile(r"sk_live_[a-zA-Z0-9]{24,}")),
    ("PASSWORD",   re.compile(r'password\s*=\s*["\'][^"\']{4,}["\']', re.IGNORECASE)),
    ("JWT",        re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    ("PEM",        re.compile(r"-----BEGIN [A-Z ]+-----[\s\S]+?-----END [A-Z ]+-----")),
    ("SLACK_TOKEN",re.compile(r"xox[abp]-[0-9]+-[0-9]+-[0-9]+-[a-f0-9]+")),
    ("GOOGLE_KEY", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
]


@dataclass
class ScrubResult:
    text: str
    count: int


def scrub(text: str) -> ScrubResult:
    count = 0
    for label, pattern in _PATTERNS:
        new_text, n = pattern.subn(f"[REDACTED-{label}]", text)
        text = new_text
        count += n
    return ScrubResult(text=text, count=count)
