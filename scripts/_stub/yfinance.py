"""
Inert stand-in for yfinance, used ONLY by local batch scripts (--stub-yfinance).

Why this exists
---------------
yfinance segfaults (SIGSEGV, exit 139) for ANY ticker in the local venv on Python 3.14.
It is a pre-existing environment fault, unrelated to app code, and production (3.12) is
fine — but it kills the whole process, so it cannot be caught with try/except and it takes
a batch run down with it on the first name.

Everything the batch path actually needs is already covered without yfinance: prices come
from the Yahoo `chart` endpoint and the price cache, fundamentals from Finnhub/FMP, and
GROW's standard/full tiers retrieve the real figures from filings via web search anyway.
The only thing lost is the aggregator financial-statement block in the Tier-5 snapshot,
which GROW treats as confirmation-only under §6.2 and never as a price-setting number.

Do NOT put this on the path for the app itself.
"""


class _Empty:
    def __getattr__(self, name):
        return None

    def __bool__(self):
        return False


def _empty_df():
    import pandas as pd
    return pd.DataFrame()


class Ticker:
    def __init__(self, *args, **kwargs):
        self.info = {}
        self.fast_info = {}

    def history(self, *args, **kwargs):
        return _empty_df()

    def get_financials(self, *args, **kwargs):
        return _empty_df()

    @property
    def financials(self):
        return _empty_df()

    @property
    def quarterly_financials(self):
        return _empty_df()

    @property
    def cashflow(self):
        return _empty_df()

    @property
    def balance_sheet(self):
        return _empty_df()

    @property
    def recommendations(self):
        return _empty_df()

    def __getattr__(self, name):
        return _Empty()


class Tickers:
    def __init__(self, *args, **kwargs):
        self.tickers = {}


def download(*args, **kwargs):
    return _empty_df()
