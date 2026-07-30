"""VC020 fake secret, VC021 fake endpoint, VC022 env fallback."""

import pytest

from conftest import codes, describe, lines_for

VC020 = ["VC020"]
VC021 = ["VC021"]
VC022 = ["VC022"]


# =======================================================================
# VC020 - placeholder credentials
# =======================================================================


@pytest.mark.parametrize(
    "line",
    [
        'API_KEY = "your-api-key-here"',
        'SECRET_KEY = "changeme"',
        'password = "<your-password>"',
        'auth_token = "xxxxxxxx"',
        'CLIENT_SECRET = "{{ client_secret }}"',
        'ACCESS_KEY = "placeholder"',
        'db_password = "replace-me"',
        'STRIPE_SECRET = "sk-test"',
        'apikey = "abc123"',
        'private_key = "insert-key-here"',
    ],
)
def test_placeholder_credentials_are_flagged(scan_code, line):
    findings = scan_code(line + "\n", only=VC020)
    assert codes(findings) == ["VC020"], describe(findings)
    assert lines_for(findings, "VC020") == [1]


def test_placeholder_credential_in_a_keyword_argument(scan_code):
    source = """
    import http.client


    def build():
        return dict(host="db.internal", password="your-password-here")
    """
    findings = scan_code(source, only=VC020)
    assert codes(findings) == ["VC020"], describe(findings)


def test_placeholder_credential_in_a_dict_literal(scan_code):
    source = """
    CONFIG = {
        "region": "eu-west-1",
        "api_key": "TODO",
    }
    """
    findings = scan_code(source, only=VC020)
    assert codes(findings) == ["VC020"], describe(findings)
    assert lines_for(findings, "VC020") == [3]


def test_placeholder_credential_on_an_attribute(scan_code):
    source = """
    class Settings:
        pass


    settings = Settings()
    settings.api_key = "your-key-here"
    """
    findings = scan_code(source, only=VC020)
    assert codes(findings) == ["VC020"], describe(findings)


# -- true negatives ------------------------------------------------------


def test_credentials_read_from_the_environment_are_clean(scan_code):
    source = """
    import os

    API_KEY = os.environ["API_KEY"]
    SECRET_KEY = os.environ["SECRET_KEY"]
    """
    assert scan_code(source, only=VC020) == []


def test_realistic_looking_key_is_not_flagged(scan_code):
    # The literal below must stay generic. A value shaped like a real provider
    # key - `sk_live_...`, `AKIA...`, `ghp_...` - trips GitHub's push
    # protection and blocks the commit, even inside a test asserting we do
    # *not* flag it. Any opaque high-entropy string proves the same point.
    source = """
    API_KEY = "a3f9c1e84b7d26059fe1c8b34a7d92e6"
    password = "correct-horse-battery-staple"
    """
    findings = scan_code(source, only=VC020)
    assert findings == [], describe(findings)


def test_non_sensitive_name_with_placeholder_value_is_clean(scan_code):
    source = """
    PAGE_TITLE = "your-company-name"
    DEFAULT_LABEL = "placeholder"
    """
    findings = scan_code(source, only=VC020)
    assert findings == [], describe(findings)


def test_sensitive_name_with_non_string_value_is_clean(scan_code):
    source = """
    API_KEY_LENGTH = 32
    PASSWORD_ROTATION_DAYS = 90
    TOKEN_PREFIX_BYTES = None
    """
    assert scan_code(source, only=VC020) == []


def test_placeholder_credentials_in_test_files_are_ignored(scan_code):
    """Fake values are the whole point of a test fixture."""
    findings = scan_code(
        {"tests/test_client.py": 'API_KEY = "your-api-key-here"\n'},
        only=VC020,
    )
    assert findings == [], describe(findings)


def test_env_var_name_constant_is_clean(scan_code):
    source = """
    API_KEY_ENV = "MYAPP_API_KEY"
    SECRET_HEADER = "X-Auth-Token"
    """
    findings = scan_code(source, only=VC020)
    assert findings == [], describe(findings)


# =======================================================================
# VC021 - documentation domains used as real endpoints
# =======================================================================


@pytest.mark.parametrize(
    "line",
    [
        'API_URL = "https://api.example.com/v1/orders"',
        'BASE = "http://example.org/webhook"',
        'ENDPOINT = "https://your-domain.com/api"',
        'HOST = "https://mysite.com/callback"',
    ],
)
def test_documentation_domains_are_flagged(scan_code, line):
    findings = scan_code(line + "\n", only=VC021)
    assert codes(findings) == ["VC021"], describe(findings)
    assert lines_for(findings, "VC021") == [1]


def test_fake_endpoint_is_a_warning_not_a_critical(scan_code):
    findings = scan_code('URL = "https://api.example.com"\n', only=VC021)
    assert codes(findings) == ["VC021"], describe(findings)
    assert findings[0].severity.label == "warning"


# -- true negatives ------------------------------------------------------


def test_real_endpoints_are_clean(scan_code):
    source = """
    STRIPE = "https://api.stripe.com/v1"
    DOCS = "https://docs.python.org/3/library/ast.html"
    INTERNAL = "https://orders.svc.cluster.local:8080"
    LOCAL = "http://localhost:5432"
    """
    findings = scan_code(source, only=VC021)
    assert findings == [], describe(findings)


def test_example_domain_in_a_comment_is_clean(scan_code):
    source = """
    # See https://api.example.com/docs for the wire format we mirror.
    URL = "https://api.internal.corp/v1"
    """
    findings = scan_code(source, only=VC021)
    assert findings == [], describe(findings)


def test_example_email_address_is_clean(scan_code):
    source = """
    SUPPORT_CONTACT = "support@example.com"
    """
    findings = scan_code(source, only=VC021)
    assert findings == [], describe(findings)


def test_example_domain_in_test_files_is_ignored(scan_code):
    findings = scan_code(
        {"tests/test_api.py": 'BASE_URL = "https://api.example.com"\n'},
        only=VC021,
    )
    assert findings == [], describe(findings)


# =======================================================================
# VC022 - environment lookups with a placeholder fallback
# =======================================================================


def test_getenv_with_placeholder_default_is_flagged(scan_code):
    source = """
    import os

    API_KEY = os.getenv("API_KEY", "your-api-key")
    """
    findings = scan_code(source, only=VC022)
    assert codes(findings) == ["VC022"], describe(findings)
    assert lines_for(findings, "VC022") == [3]


def test_environ_get_with_placeholder_default_is_flagged(scan_code):
    source = """
    import os

    DB_URL = os.environ.get("DATABASE_URL", "changeme")
    """
    findings = scan_code(source, only=VC022)
    assert codes(findings) == ["VC022"], describe(findings)


def test_env_fallback_names_the_variable(scan_code):
    source = """
    import os

    SECRET = os.getenv("APP_SECRET", "replace-me")
    """
    findings = scan_code(source, only=VC022)
    assert codes(findings) == ["VC022"], describe(findings)
    assert "APP_SECRET" in findings[0].message


# -- true negatives ------------------------------------------------------


def test_sensible_env_defaults_are_clean(scan_code):
    source = """
    import os

    PORT = os.getenv("PORT", "8080")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    REGION = os.environ.get("AWS_REGION", "eu-west-1")
    """
    findings = scan_code(source, only=VC022)
    assert findings == [], describe(findings)


def test_getenv_without_a_default_is_clean(scan_code):
    source = """
    import os

    API_KEY = os.getenv("API_KEY")
    """
    assert scan_code(source, only=VC022) == []


def test_required_env_lookup_is_clean(scan_code):
    source = """
    import os

    API_KEY = os.environ["API_KEY"]
    """
    assert scan_code(source, only=VC022) == []


def test_plain_dict_get_with_placeholder_default_is_clean(scan_code):
    """`config.get("x", "placeholder")` is not an environment lookup."""
    source = """
    def resolve(config):
        return config.get("label", "placeholder")
    """
    findings = scan_code(source, only=VC022)
    assert findings == [], describe(findings)


def test_env_fallback_in_test_files_is_ignored(scan_code):
    findings = scan_code(
        {
            "tests/test_settings.py": (
                "import os\n"
                "\n"
                'KEY = os.getenv("API_KEY", "your-api-key")\n'
            )
        },
        only=VC022,
    )
    assert findings == [], describe(findings)
