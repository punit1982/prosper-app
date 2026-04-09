"""
Smoke Tests for Prosper
=======================
Basic tests for critical paths: database CRUD, auth validation,
settings management, and data pipeline sanity checks.

Run: python -m pytest tests/ -v
"""

import os
import sys
import sqlite3
import json
import tempfile
import pytest

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_streamlit(monkeypatch):
    """
    Stub out streamlit.session_state and streamlit.secrets for unit tests.
    This prevents ImportError / RuntimeError when core modules import streamlit.
    """
    import types

    class FakeSessionState(dict):
        """Dict that supports attribute access like st.session_state."""
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError:
                raise AttributeError(name)

        def __setattr__(self, name, value):
            self[name] = value

        def __delattr__(self, name):
            try:
                del self[name]
            except KeyError:
                raise AttributeError(name)

    fake_state = FakeSessionState()

    # Create a minimal streamlit mock module
    try:
        import streamlit as st
        monkeypatch.setattr(st, "session_state", fake_state, raising=False)
    except Exception:
        pass


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Provide a temporary SQLite database for tests."""
    db_path = str(tmp_path / "test_prosper.db")

    # Patch the db_connector to use our temp DB
    import core.db_connector as dbc
    monkeypatch.setattr(dbc, "_use_turso", False)
    monkeypatch.setattr(dbc, "DB_PATH", db_path)
    monkeypatch.setattr(dbc, "DB_DIR", str(tmp_path))

    # Also patch streamlit session state for _db_initialized
    try:
        import streamlit as st
        st.session_state.pop("_db_initialized", None)
    except Exception:
        pass

    return db_path


# ──────────────────────────────────────────────────────────────────────────────
# Database Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDatabase:
    def test_init_db_creates_tables(self, tmp_db):
        """init_db should create all required tables."""
        from core.database import init_db
        init_db()

        conn = sqlite3.connect(tmp_db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()

        required = [
            "holdings", "portfolios", "transactions", "watchlist",
            "nav_snapshots", "price_cache", "news_cache", "ticker_cache",
            "parse_cache", "users", "ai_call_cache", "prosper_analysis",
            "cash_positions", "fortress_state", "briefing_cache",
            "user_preferences",
        ]
        for table in required:
            assert table in tables, f"Missing table: {table}"

    def test_portfolio_crud(self, tmp_db):
        """Create, read, rename, delete portfolio."""
        from core.database import init_db, create_portfolio, get_all_portfolios, rename_portfolio, delete_portfolio
        init_db()

        # Create
        pid = create_portfolio("Test Portfolio", "A test", user_id="testuser")
        assert isinstance(pid, int)
        assert pid > 0

        # Read
        portfolios = get_all_portfolios()
        assert not portfolios.empty
        names = portfolios["name"].tolist()
        assert "Test Portfolio" in names

        # Rename
        rename_portfolio(pid, "Renamed Portfolio")
        portfolios = get_all_portfolios()
        assert "Renamed Portfolio" in portfolios["name"].tolist()

        # Delete (skip if pid == 1 — protected)
        if pid != 1:
            delete_portfolio(pid)
            portfolios = get_all_portfolios()
            assert "Renamed Portfolio" not in portfolios["name"].tolist()

    def test_holdings_save_and_retrieve(self, tmp_db):
        """Save holdings and verify retrieval."""
        import pandas as pd
        from core.database import init_db, save_holdings, get_all_holdings
        init_db()

        df = pd.DataFrame([
            {"ticker": "AAPL", "name": "Apple Inc.", "quantity": 10, "avg_cost": 150.0, "currency": "USD"},
            {"ticker": "GOOGL", "name": "Alphabet", "quantity": 5, "avg_cost": 2800.0, "currency": "USD"},
        ])
        save_holdings(df, broker_source="test")

        holdings = get_all_holdings()
        assert len(holdings) == 2
        assert "AAPL" in holdings["ticker"].tolist()
        assert "GOOGL" in holdings["ticker"].tolist()

    def test_user_crud(self, tmp_db):
        """Create and retrieve a user."""
        from core.database import init_db, create_user, get_user_by_username, get_user_by_email, delete_user
        init_db()

        create_user("testuser", "test@example.com", "Test", "User", "hash123", "user")
        user = get_user_by_username("testuser")
        assert user is not None
        assert user["email"] == "test@example.com"

        user_by_email = get_user_by_email("test@example.com")
        assert user_by_email is not None
        assert user_by_email["username"] == "testuser"

        delete_user("testuser")
        assert get_user_by_username("testuser") is None

    def test_price_cache(self, tmp_db):
        """Save and retrieve price cache."""
        from core.database import init_db, save_price_cache, get_price_cache
        init_db()

        quotes = {
            "AAPL": {"price": 175.5, "change": 2.3, "changesPercentage": 1.3, "source": "yfinance"},
            "MSFT": {"price": 380.0, "change": -1.0, "changesPercentage": -0.26, "source": "yfinance"},
        }
        save_price_cache(quotes)

        cached = get_price_cache(["AAPL", "MSFT", "MISSING"])
        assert "AAPL" in cached
        assert "MSFT" in cached
        assert "MISSING" not in cached
        assert cached["AAPL"]["price"] == 175.5


# ──────────────────────────────────────────────────────────────────────────────
# Auth Validation Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_password_validation(self):
        """Password must meet minimum requirements."""
        from core.auth import validate_password

        # Too short
        errors = validate_password("Ab1")
        assert any("8" in e for e in errors)

        # No uppercase
        errors = validate_password("abcdefgh1")
        assert any("uppercase" in e.lower() for e in errors)

        # No number
        errors = validate_password("Abcdefgh")
        assert any("number" in e.lower() for e in errors)

        # Valid
        errors = validate_password("Abcdefg1")
        assert len(errors) == 0

    def test_password_hash_and_check(self):
        """bcrypt hash/check round-trip."""
        from core.auth import _hash_password, _check_password

        hashed = _hash_password("TestPass123")
        assert hashed.startswith("$2")
        assert _check_password("TestPass123", hashed) is True
        assert _check_password("WrongPass", hashed) is False

    def test_username_from_email_uniqueness(self):
        """Different domains should produce different usernames."""
        # Simulate the new username derivation logic
        email1 = "john@gmail.com"
        email2 = "john@company.com"

        def derive(email):
            return email.lower().replace("@", "_at_").replace(".", "_").replace("-", "_").replace("+", "_")

        u1 = derive(email1)
        u2 = derive(email2)
        assert u1 != u2, f"Username collision: {u1} == {u2}"


# ──────────────────────────────────────────────────────────────────────────────
# Settings Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestSettings:
    def test_defaults_loaded(self):
        """SETTINGS dict should have expected keys."""
        from core.settings import SETTINGS
        assert "base_currency" in SETTINGS
        assert "parse_cache_enabled" in SETTINGS
        assert "price_cache_ttl_seconds" in SETTINGS

    def test_get_api_key_from_env(self, monkeypatch):
        """get_api_key should read from environment."""
        from core.settings import get_api_key
        monkeypatch.setenv("TEST_KEY_12345", "my_secret_value")
        assert get_api_key("TEST_KEY_12345") == "my_secret_value"

    def test_get_api_key_missing(self):
        """get_api_key should return empty string if not set."""
        from core.settings import get_api_key
        assert get_api_key("DEFINITELY_NOT_A_REAL_KEY_XYZ") == ""


# ──────────────────────────────────────────────────────────────────────────────
# Currency Normalizer Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestCurrencyNormalizer:
    def test_detect_currency_from_ticker(self):
        """Ticker suffix should map to correct currency."""
        from core.currency_normalizer import detect_currency_from_ticker

        assert detect_currency_from_ticker("RELIANCE.NS") == "INR"
        assert detect_currency_from_ticker("EMAAR.AE") == "AED"
        assert detect_currency_from_ticker("0700.HK") == "HKD"
        assert detect_currency_from_ticker("AAPL") == "USD"  # No suffix = USD

    def test_normalise_currency(self):
        """Currency corrections should fix exchange codes."""
        from core.currency_normalizer import normalise_currency

        assert normalise_currency("DFM") == "AED"
        assert normalise_currency("NSE") == "INR"
        assert normalise_currency("USD") == "USD"


# ──────────────────────────────────────────────────────────────────────────────
# Data Engine Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDataEngine:
    def test_ticker_overrides_exist(self):
        """TICKER_OVERRIDES should be a non-empty dict."""
        from core.data_engine import TICKER_OVERRIDES
        assert isinstance(TICKER_OVERRIDES, dict)
        assert len(TICKER_OVERRIDES) > 0

    def test_crypto_tickers_mapped(self):
        """CRYPTO_TICKERS should map common symbols to -USD pairs."""
        from core.data_engine import CRYPTO_TICKERS
        assert CRYPTO_TICKERS.get("BTC") == "BTC-USD"
        assert CRYPTO_TICKERS.get("ETH") == "ETH-USD"
