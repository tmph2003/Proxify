"""Unit tests for the unified Stealth Engine."""

import pytest
from proxify.utils.stealth import (
    sanitize_headers,
    is_soft_blocked,
    is_retryable_status,
    StealthResponse,
    HEADERS_TO_STRIP,
)


class TestSanitizeHeaders:
    """Test header sanitization for curl_cffi consistency."""

    def test_removes_pseudo_headers(self):
        headers = {
            ":authority": "example.com",
            ":method": "GET",
            ":path": "/",
            ":scheme": "https",
            "User-Agent": "Chrome/131",
        }
        result = sanitize_headers(headers)
        assert ":authority" not in result
        assert ":method" not in result
        assert ":path" not in result
        assert ":scheme" not in result
        assert result["User-Agent"] == "Chrome/131"

    def test_removes_hop_by_hop_headers(self):
        headers = {
            "host": "example.com",
            "content-length": "42",
            "accept-encoding": "gzip",
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "Cookie": "abc=123",
        }
        result = sanitize_headers(headers)
        assert "host" not in result
        assert "content-length" not in result
        assert "accept-encoding" not in result
        assert "connection" not in result
        assert "transfer-encoding" not in result
        assert result["Cookie"] == "abc=123"

    def test_preserves_normal_headers(self):
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Cookie": "session=abc",
            "X-Custom-Header": "value",
            "sec-ch-ua": '"Chromium";v="131"',
        }
        result = sanitize_headers(headers)
        assert len(result) == 4
        assert result["User-Agent"] == "Mozilla/5.0"

    def test_empty_headers(self):
        assert sanitize_headers({}) == {}

    def test_removes_unknown_pseudo_headers(self):
        """Any header starting with ':' should be removed."""
        headers = {":custom": "value", "Accept": "text/html"}
        result = sanitize_headers(headers)
        assert ":custom" not in result
        assert result["Accept"] == "text/html"


class TestIsSoftBlocked:
    """Test soft-block detection for anti-bot challenge pages."""

    def test_detects_cloudflare_challenge_header(self):
        assert is_soft_blocked(200, b"normal content", {"cf-mitigated": "challenge"})

    def test_detects_cloudflare_waiting_page(self):
        assert is_soft_blocked(200, b"Just a moment... checking browser", {})

    def test_detects_facebook_checkpoint(self):
        assert is_soft_blocked(200, b'<html>checkpoint required</html>', {})

    def test_detects_facebook_server_redirect(self):
        content = b'{"require":["ServerRedirect","handleRedirect"]}'
        assert is_soft_blocked(200, content, {})

    def test_normal_response_not_blocked(self):
        assert not is_soft_blocked(200, b'{"data": {"user": "test"}}', {})

    def test_large_response_not_checked(self):
        """Responses larger than 50KB are not scanned (performance optimization)."""
        content = b"checkpoint" + b"x" * 60000
        assert not is_soft_blocked(200, content, {})

    def test_empty_content_not_blocked(self):
        assert not is_soft_blocked(200, b"", {})

    def test_captcha_detection(self):
        assert is_soft_blocked(200, b"Please complete the captcha to continue", {})

    def test_access_denied_detection(self):
        assert is_soft_blocked(403, b"Access denied - bot detected", {})


class TestIsRetryableStatus:
    """Test which HTTP status codes trigger retry."""

    def test_429_is_retryable(self):
        assert is_retryable_status(429)

    def test_503_is_retryable(self):
        assert is_retryable_status(503)

    def test_502_is_retryable(self):
        assert is_retryable_status(502)

    def test_cloudflare_errors_retryable(self):
        for code in (520, 521, 522, 523, 524):
            assert is_retryable_status(code), f"{code} should be retryable"

    def test_200_not_retryable(self):
        assert not is_retryable_status(200)

    def test_404_not_retryable(self):
        assert not is_retryable_status(404)

    def test_403_not_retryable(self):
        assert not is_retryable_status(403)


class TestStealthResponse:
    """Test the StealthResponse wrapper."""

    def test_basic_response(self):
        resp = StealthResponse(200, b"hello world", {"content-type": "text/plain"})
        assert resp.status_code == 200
        assert resp.text == "hello world"
        assert resp.is_blocked is False
        assert resp.attempts == 1

    def test_blocked_response(self):
        resp = StealthResponse(200, b"checkpoint", {}, is_blocked=True, attempts=3)
        assert resp.is_blocked is True
        assert resp.attempts == 3

    def test_unicode_decode(self):
        resp = StealthResponse(200, "Xin chào".encode("utf-8"), {})
        assert resp.text == "Xin chào"

    def test_invalid_utf8_fallback(self):
        resp = StealthResponse(200, b"\xff\xfe invalid utf8", {})
        # Should not raise, uses errors="replace"
        text = resp.text
        assert isinstance(text, str)

    def test_repr(self):
        resp = StealthResponse(200, b"x" * 100, {})
        assert "200" in repr(resp)
        assert "100 bytes" in repr(resp)

    def test_blocked_repr(self):
        resp = StealthResponse(200, b"", {}, is_blocked=True, attempts=3)
        assert "BLOCKED" in repr(resp)
        assert "3 attempts" in repr(resp)


class TestFacebookStealth:
    """Test Facebook stealth mechanics (SessionStateManager & DelayConfig)."""

    def test_session_state_mutation(self):
        from proxify.platforms.facebook.stealth import SessionStateManager
        manager = SessionStateManager(counter_offset=10)
        
        # Case 1: When __s is missing, it should generate a valid session token
        data_missing = {"existing_param": "val"}
        manager.update_params(data_missing)
        assert data_missing["__req"] == "a"  # 10 in base36 is 'a'
        assert "__s" in data_missing
        assert ":" in data_missing["__s"]
        assert "__spin_t" in data_missing
        assert manager.request_count == 1

        # Case 2: When __s is already present from browser session, preserve it across requests
        data_existing = {"existing_param": "val", "__s": "session_from_browser"}
        manager.update_params(data_existing)
        assert data_existing["__req"] == "b"  # 11 in base36 is 'b'
        assert data_existing["__s"] == "session_from_browser"  # Preserves genuine browser session
        assert manager.request_count == 2

    def test_crawl_delay_config(self):
        from proxify.platforms.facebook.stealth import comment_delay, page_delay, CrawlDelayConfig
        config = CrawlDelayConfig()
        
        # Verify human-like minimum constraints
        assert config.comment_min >= 1.5
        assert config.page_min >= 2.0
        
        for _ in range(20):
            c_delay = comment_delay(config)
            assert c_delay >= 1.5
            p_delay = page_delay(config)
            assert p_delay >= 2.0

