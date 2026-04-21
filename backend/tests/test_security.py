"""
Security hardening tests — Phase 10.
Run: pytest backend/tests/test_security.py -v
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Allow importing from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, validate_url
from ai.scrubber import scrub
from middleware.rate_limit import InMemoryRateLimiter
from fastapi import HTTPException

client = TestClient(app)


# ---------------------------------------------------------------------------
# 10.1  URL injection / SSRF
# ---------------------------------------------------------------------------

MALICIOUS_URLS = [
    "git+ssh://github.com/foo/bar",
    "file:///etc/passwd",
    "https://user:pass@github.com/foo/bar",
    "http://github.com/foo/bar",
    "https://github.com/foo/../../../etc",
    "https://evil.com/foo/bar",
    "https://github.com/foo/bar; rm -rf /",
    "https://github.com/foo/bar\x00.git",
    "git@github.com:foo/bar.git",
    "ftp://github.com/foo/bar",
    "https://github.com/foo/bar?token=abc",
    "https://metadata.google.internal/computeMetadata/v1/",
]

@pytest.mark.parametrize("url", MALICIOUS_URLS)
def test_malicious_url_rejected(url):
    with pytest.raises(HTTPException) as exc_info:
        validate_url(url)
    assert exc_info.value.status_code == 400, f"Expected 400 for {url!r}"


def test_valid_github_url_accepted():
    vr = validate_url("https://github.com/psf/requests")
    assert vr.host == "github.com"
    assert vr.owner == "psf"
    assert vr.repo == "requests"


def test_valid_gitlab_url_accepted():
    vr = validate_url("https://gitlab.com/gitlab-org/gitlab-runner")
    assert vr.host == "gitlab.com"


def test_valid_bitbucket_url_accepted():
    vr = validate_url("https://bitbucket.org/atlassian/python-bitbucket")
    assert vr.host == "bitbucket.org"


def test_valid_tree_url_accepted():
    vr = validate_url("https://github.com/psf/requests/tree/main")
    assert vr.branch == "main"


# ---------------------------------------------------------------------------
# 10.7  Secret scrubber
# ---------------------------------------------------------------------------

def test_scrubber_redacts_aws_key():
    text = "key = AKIAIOSFODNN7EXAMPLE and more"
    result = scrub(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in result.text
    assert "[REDACTED-AWS_KEY]" in result.text
    assert result.count >= 1


def test_scrubber_redacts_github_token():
    token = "ghp_" + "a" * 36
    result = scrub(f"Authorization: token {token}")
    assert token not in result.text
    assert result.count >= 1


def test_scrubber_redacts_stripe_key():
    result = scrub("stripe_key = sk_live_" + "x" * 24)
    assert result.count >= 1


def test_scrubber_redacts_password():
    result = scrub('password = "supersecret123"')
    assert result.count >= 1
    assert "supersecret123" not in result.text


def test_scrubber_redacts_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = scrub(jwt)
    assert result.count >= 1


def test_scrubber_clean_text_unchanged():
    text = "def hello(): return 'world'"
    result = scrub(text)
    assert result.text == text
    assert result.count == 0


def test_scrubber_multiple_secrets():
    aws = "AKIAIOSFODNN7EXAMPLE"
    gh = "ghp_" + "b" * 36
    result = scrub(f"aws={aws} gh={gh}")
    assert result.count >= 2


# ---------------------------------------------------------------------------
# 10.11  Rate limiter
# ---------------------------------------------------------------------------

def test_rate_limiter_allows_under_limit():
    rl = InMemoryRateLimiter(max_per_hour=5)
    for _ in range(5):
        allowed, _ = rl.allow("1.2.3.4")
        assert allowed


def test_rate_limiter_blocks_at_limit():
    rl = InMemoryRateLimiter(max_per_hour=3)
    for _ in range(3):
        rl.allow("1.2.3.4")
    allowed, retry_after = rl.allow("1.2.3.4")
    assert not allowed
    assert retry_after > 0


def test_rate_limiter_isolates_ips():
    rl = InMemoryRateLimiter(max_per_hour=2)
    for _ in range(2):
        rl.allow("1.1.1.1")
    blocked, _ = rl.allow("1.1.1.1")
    assert not blocked
    allowed, _ = rl.allow("2.2.2.2")
    assert allowed


def test_rate_limiter_returns_429_on_api():
    """POST /analyze returns 429 after exhausting the rate limit."""
    # We need to exhaust via the API — use a known-bad URL that fails
    # validation (400) before hitting the rate limit counter.
    # Instead, patch the limiter directly.
    import main as m
    original_allow = m.rate_limiter.allow
    call_count = 0

    def mock_allow(ip):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            return False, 3599
        return True, 0

    m.rate_limiter.allow = mock_allow
    try:
        # First call goes through (bad URL → 400, not 429)
        r1 = client.post("/analyze", json={"url": "https://github.com/x/y"})
        # Second call hits rate limit
        r2 = client.post("/analyze", json={"url": "https://github.com/x/y"})
        assert r2.status_code == 429
    finally:
        m.rate_limiter.allow = original_allow


# ---------------------------------------------------------------------------
# 10.3  Path traversal
# ---------------------------------------------------------------------------

def test_path_traversal_url_rejected():
    with pytest.raises(HTTPException):
        validate_url("https://github.com/foo/../../../etc/passwd")


def test_null_byte_in_url_rejected():
    with pytest.raises(HTTPException):
        validate_url("https://github.com/foo/bar\x00evil")


# ---------------------------------------------------------------------------
# 10.8  Cache key collision resistance
# ---------------------------------------------------------------------------

def test_cache_key_no_collision():
    from cache.analysis import make_analysis_key
    k1 = make_analysis_key("https://github.com/a/b", "c")
    k2 = make_analysis_key("https://github.com/a", "b/c")
    assert k1 != k2, "null-byte separator should prevent prefix collision"
