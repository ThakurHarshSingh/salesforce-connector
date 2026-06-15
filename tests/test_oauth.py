import urllib.parse

from sf_connector.config import Settings
from sf_connector.oauth import _authorize_url, _pkce_pair


def _settings(**overrides) -> Settings:
    base = {
        "sf_client_id": "consumer-key",
        "sf_client_secret": "consumer-secret",
        "sf_redirect_uri": "http://localhost:1717/callback",
        "sf_domain": "login",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_authorize_url_targets_the_right_domain_and_params():
    url = _authorize_url(_settings(), state="xyz", code_challenge="chal")
    parsed = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(parsed.query))

    assert parsed.netloc == "login.salesforce.com"
    assert parsed.path == "/services/oauth2/authorize"
    assert params["response_type"] == "code"
    assert params["client_id"] == "consumer-key"
    assert params["redirect_uri"] == "http://localhost:1717/callback"
    assert params["state"] == "xyz"
    assert "refresh_token" in params["scope"]
    assert params["code_challenge"] == "chal"
    assert params["code_challenge_method"] == "S256"


def test_authorize_url_uses_sandbox_domain():
    url = _authorize_url(_settings(sf_domain="test"), state="s", code_challenge="c")
    assert urllib.parse.urlparse(url).netloc == "test.salesforce.com"


def test_pkce_pair_is_url_safe_and_unpadded():
    verifier, challenge = _pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert "=" not in challenge  # base64url, padding stripped
    assert "+" not in challenge and "/" not in challenge


def test_login_base_url_handles_shortcuts_and_my_domain():
    assert _settings(sf_domain="login").sf_login_base_url == "https://login.salesforce.com"
    assert _settings(sf_domain="test").sf_login_base_url == "https://test.salesforce.com"
    # A bare My Domain gets the salesforce.com suffix...
    assert (
        _settings(sf_domain="acme.my").sf_login_base_url
        == "https://acme.my.salesforce.com"
    )
    # ...and a full host is used as-is.
    assert (
        _settings(sf_domain="acme.my.salesforce.com").sf_login_base_url
        == "https://acme.my.salesforce.com"
    )


def test_authorize_url_uses_my_domain_host():
    url = _authorize_url(
        _settings(sf_domain="acme.my.salesforce.com"), state="s", code_challenge="c"
    )
    assert urllib.parse.urlparse(url).netloc == "acme.my.salesforce.com"
