# ============================================================
# data_fetcher.py — live market data retrieval
#
# Fetches OHLCV data from 2023 onwards — date range anchored
# to DATA_START_DATE in config.py so charts never show 1970s
# Unix epoch data from malformed timestamps.
#
# Primary: yfinance. Fallback: Alpha Vantage free tier.
# All timestamps normalised to UTC on ingest.
# Every fetch logged to fetch_log for data lineage.
# ============================================================

import os
import time
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from dotenv import load_dotenv
from src.config import (
    RETRY_DELAYS_SECONDS,
    DATA_START_DATE,
    TICKER_EXCHANGE_MAP
)

load_dotenv()
logger = logging.getLogger(__name__)


def get_date_range() -> tuple:
    """
    Return the standard date range for data fetching.

    Always fetches from DATA_START_DATE (2023-01-01) to today.
    Anchoring to a fixed start date prevents the pipeline from
    ever using pre-2023 data which caused the 1970 chart issue —
    that was a Unix epoch timestamp being misinterpreted as a date.

    Returns:
        Tuple of (date_from, date_to) as 'YYYY-MM-DD' strings.
    """
    today   = datetime.now(timezone.utc).date()
    date_to = today.strftime('%Y-%m-%d')
    return DATA_START_DATE, date_to


def fetch_ticker_data(
    ticker: str,
    date_from: str,
    date_to: str
) -> pd.DataFrame:
    """
    Fetch OHLCV price data for a single ticker from yfinance.

    Uses exponential backoff retry on failure. Falls back to
    Alpha Vantage if yfinance exhausts all retries. Returns
    standardised DataFrame or empty DataFrame on complete failure.

    Args:
        ticker:    Market ticker e.g. 'AAPL', 'HSBA.L', 'SAP.DE'
        date_from: Start date 'YYYY-MM-DD' — use DATA_START_DATE
        date_to:   End date 'YYYY-MM-DD' — use today

    Returns:
        Standardised DataFrame or empty DataFrame on failure.
    """
    for attempt, delay in enumerate(RETRY_DELAYS_SECONDS, start=1):
        try:
            raw_data = yf.download(
                ticker,
                start=date_from,
                end=date_to,
                progress=False,
                auto_adjust=True
            )

            if raw_data.empty:
                logger.warning(f"{ticker}: yfinance returned empty DataFrame")
                break

            standardised = _standardise_dataframe(raw_data, ticker)

            if standardised.empty:
                logger.warning(f"{ticker}: standardisation returned empty")
                break

            logger.info(f"{ticker}: {len(standardised)} rows fetched via yfinance")
            return standardised

        except Exception as error:
            logger.warning(
                f"{ticker}: attempt {attempt} failed — {error}. "
                f"Retrying in {delay}s."
            )
            time.sleep(delay)

    logger.info(f"{ticker}: attempting Alpha Vantage fallback")
    return _fetch_from_alpha_vantage(ticker, date_from, date_to)


def _standardise_dataframe(
    raw_data: pd.DataFrame,
    ticker: str
) -> pd.DataFrame:
    """
    Normalise yfinance output to project standard schema.

    Handles both old string columns and new tuple columns from
    recent yfinance versions. Converts index to plain date objects
    — this is critical to prevent the 1970 epoch bug where
    timezone-aware Timestamps were misread as Unix epoch 0.

    Args:
        raw_data: Raw DataFrame from yfinance.download()
        ticker:   Ticker symbol for metadata columns

    Returns:
        Clean standardised DataFrame.
    """
    df = raw_data.copy()

    # Handle tuple columns from newer yfinance versions
    new_cols = []
    for col in df.columns:
        if isinstance(col, tuple):
            new_cols.append(col[0].lower())
        else:
            new_cols.append(str(col).lower())
    df.columns = new_cols

    # Remove duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]

    required = ['open', 'high', 'low', 'close', 'volume']
    for col in required:
        if col not in df.columns:
            logger.warning(f"{ticker}: missing column '{col}'")
            return _empty_dataframe()

    # Reset index — convert to plain Python date objects.
    # This is the fix for the 1970 epoch issue: we explicitly
    # extract .date() which strips timezone info cleanly rather
    # than letting pandas store a timezone-aware Timestamp that
    # SQLite then misinterprets as a Unix millisecond timestamp.
    df = df.reset_index()
    date_col = df.columns[0]

    df['date'] = pd.to_datetime(df[date_col]).dt.date

    # Filter to only include dates from DATA_START_DATE onwards
    # as an extra safety check against any pre-2023 data
    cutoff = pd.to_datetime(DATA_START_DATE).date()
    df = df[df['date'] >= cutoff].copy()

    df['ticker']          = ticker
    df['exchange']        = TICKER_EXCHANGE_MAP.get(ticker, 'UNKNOWN')
    df['timezone_source'] = 'UTC'

    result = df[['date', 'open', 'high', 'low', 'close',
                 'volume', 'ticker', 'exchange', 'timezone_source']].copy()

    result = result.dropna(subset=['close'])
    result = result.reset_index(drop=True)

    return result


def _fetch_from_alpha_vantage(
    ticker: str,
    date_from: str,
    date_to: str
) -> pd.DataFrame:
    """
    Fallback data fetch using Alpha Vantage free tier.

    Called only when yfinance fails all retries. Requires
    ALPHA_VANTAGE_API_KEY in .env file to function.

    Args:
        ticker:    Market ticker symbol
        date_from: Start date 'YYYY-MM-DD'
        date_to:   End date 'YYYY-MM-DD'

    Returns:
        Standardised DataFrame or empty DataFrame on failure.
    """
    import requests

    api_key = os.getenv('ALPHA_VANTAGE_API_KEY', '')

    if not api_key or api_key == 'your_alpha_vantage_key_here':
        logger.error(f"{ticker}: no Alpha Vantage key in .env — add ALPHA_VANTAGE_API_KEY")
        return _empty_dataframe()

    try:
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=TIME_SERIES_DAILY_ADJUSTED"
            f"&symbol={ticker}&outputsize=full&apikey={api_key}"
        )
        response = requests.get(url, timeout=30)
        data     = response.json()

        if 'Time Series (Daily)' not in data:
            logger.error(f"{ticker}: Alpha Vantage unexpected response")
            return _empty_dataframe()

        cutoff = pd.to_datetime(DATA_START_DATE).date()
        rows   = []

        for date_str, values in data['Time Series (Daily)'].items():
            row_date = pd.to_datetime(date_str).date()
            if row_date >= cutoff:
                rows.append({
                    'date':            row_date,
                    'open':            float(values.get('1. open', 0)),
                    'high':            float(values.get('2. high', 0)),
                    'low':             float(values.get('3. low', 0)),
                    'close':           float(values.get('5. adjusted close', 0)),
                    'volume':          int(values.get('6. volume', 0)),
                    'ticker':          ticker,
                    'exchange':        TICKER_EXCHANGE_MAP.get(ticker, 'UNKNOWN'),
                    'timezone_source': 'UTC'
                })

        if not rows:
            logger.warning(f"{ticker}: Alpha Vantage returned no rows in range")
            return _empty_dataframe()

        df = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
        logger.info(f"{ticker}: {len(df)} rows from Alpha Vantage")
        return df

    except Exception as error:
        logger.error(f"{ticker}: Alpha Vantage failed — {error}")
        return _empty_dataframe()


def _empty_dataframe() -> pd.DataFrame:
    """Return empty DataFrame with correct column schema."""
    return pd.DataFrame(columns=[
        'date', 'open', 'high', 'low', 'close',
        'volume', 'ticker', 'exchange', 'timezone_source'
    ])