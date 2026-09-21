"""OAuth secrets must never reach Tempo through httpx span attributes."""

from app.core.observability import _httpx_request_hook, scrub_url


def test_accounts_zoho_query_is_dropped_entirely():
    url = (
        "https://accounts.zoho.in/oauth/v2/token?refresh_token=1000.abc.def"
        "&client_id=1000.X&client_secret=s3cr3t&grant_type=refresh_token"
    )
    clean = scrub_url(url)
    assert clean == "https://accounts.zoho.in/oauth/v2/token"
    assert "s3cr3t" not in clean and "1000.abc" not in clean


def test_secret_params_are_masked_on_other_hosts():
    clean = scrub_url("https://example.com/cb?code=abc&state=xyz&token=t")
    assert "abc" not in clean and "=t" not in clean
    assert "state=xyz" in clean


def test_ordinary_zoho_api_urls_are_left_readable():
    url = "https://www.zohoapis.in/books/v3/invoices?organization_id=123&page=2"
    assert scrub_url(url) == url


class FakeSpan:
    def __init__(self):
        self.attributes = {"http.url": "https://accounts.zoho.in/oauth/v2/token?client_secret=x"}

    def is_recording(self):
        return True

    def set_attribute(self, key, value):
        self.attributes[key] = value


class FakeRequestInfo:
    url = "https://accounts.zoho.in/oauth/v2/token?client_secret=x&refresh_token=y"


def test_request_hook_overwrites_the_recorded_url():
    span = FakeSpan()
    _httpx_request_hook(span, FakeRequestInfo())
    assert span.attributes["http.url"] == "https://accounts.zoho.in/oauth/v2/token"
    assert span.attributes["url.full"] == "https://accounts.zoho.in/oauth/v2/token"
