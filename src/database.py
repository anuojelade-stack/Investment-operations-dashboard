# ============================================================
# database.py — SQLite data store and retrieval
#
# Three tables mirror investment ops data infrastructure:
#
#   prices             — one row per ticker per trading day.
#                        PRIMARY KEY on (ticker, date) makes
#                        duplicate records physically impossible
#                        at database level — no defensive code
#                        needed anywhere else in the project.
#
#   fetch_log          — every API call permanently recorded.
#                        Data lineage: any price in the database
#                        is traceable to its source, retrieval
#                        timestamp, and rows returned. This is
#                        how production ops teams govern data.
#
#   reconciliation_log — every quality check logged as PASS or
#                        BREAK with complete detail. Mirrors how
#                        real ops teams document daily recon
#                        work for internal audit purposes.
#
# Core logic: query database first on every run. Call the API
# only for dates genuinely absent per ticker. Insert and log.
# --refresh flag forces a full API pull bypassing local data.
#
# Adapts automatically to whatever tickers are in config.py.
# New tickers handled without any schema changes needed.
# ============================================================

import sqlite3
import logging
import pandas as pd
from datetime import datetime, timezone
from src.config import DB_PATH

logger = logging.getLogger(__name__)


def initialise_database() -> None:
    """
    Create all three database tables if they do not yet exist.

    Uses CREATE TABLE IF NOT EXISTS so this function is safe to
    call on every pipeline run — it only creates what is missing.
    PRIMARY KEY constraint on prices table enforces data integrity
    at the database level, making duplicate records impossible.
    """
    with sqlite3.connect(DB_PATH) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS prices (
                ticker              TEXT    NOT NULL,
                date                DATE    NOT NULL,
                open                REAL,
                high                REAL,
                low                 REAL,
                close               REAL,
                volume              INTEGER,
                daily_return        REAL,
                exchange            TEXT,
                timezone_source     TEXT,
                PRIMARY KEY (ticker, date)
            );

            CREATE TABLE IF NOT EXISTS fetch_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker              TEXT    NOT NULL,
                exchange            TEXT,
                fetched_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                date_from           DATE,
                date_to             DATE,
                rows_inserted       INTEGER,
                source              TEXT
            );

            CREATE TABLE IF NOT EXISTS reconciliation_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker              TEXT    NOT NULL,
                exchange            TEXT,
                check_date          DATE,
                checked_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                check_type          TEXT,
                status              TEXT,
                issue_detail        TEXT
            );
        """)
    logger.info("Database initialised — all tables confirmed present")


def get_missing_dates(
    ticker: str,
    date_from: str,
    date_to: str
) -> list:
    """
    Return list of dates absent from the database for this ticker.

    Compares dates held in the prices table against the requested
    range. Only absent dates are returned so the pipeline never
    makes redundant API calls for data already stored locally.
    This is the core efficiency mechanism of the pipeline.

    Args:
        ticker:    Market ticker symbol
        date_from: Start of requested range 'YYYY-MM-DD'
        date_to:   End of requested range 'YYYY-MM-DD'

    Returns:
        List of date strings missing from the database.
        Empty list if all dates already present.
    """
    query = """
        SELECT date FROM prices
        WHERE ticker = ?
        AND date BETWEEN ? AND ?
        ORDER BY date ASC
    """
    with sqlite3.connect(DB_PATH) as connection:
        existing_dates = pd.read_sql_query(
            query,
            connection,
            params=(ticker, date_from, date_to)
        )

    all_dates = pd.date_range(start=date_from, end=date_to, freq='B')
    all_dates_str = [d.strftime('%Y-%m-%d') for d in all_dates]
    existing_dates_set = set(existing_dates['date'].tolist())

    missing = [d for d in all_dates_str if d not in existing_dates_set]
    return missing


def insert_prices(
    price_data: pd.DataFrame,
    source: str
) -> int:
    """
    Insert fetched price data into the prices table and log the fetch.

    Uses INSERT OR IGNORE to respect the PRIMARY KEY constraint —
    if a row for (ticker, date) already exists it is silently skipped.
    Every successful insert is logged to fetch_log for data lineage.

    Args:
        price_data: Standardised DataFrame from data_fetcher.py
        source:     Data source used e.g. 'yfinance', 'alpha_vantage'

    Returns:
        Number of rows successfully inserted into prices table.
    """
    if price_data.empty:
        logger.warning("insert_prices called with empty DataFrame — skipping")
        return 0

    rows_inserted = 0

    with sqlite3.connect(DB_PATH) as connection:
        for _, row in price_data.iterrows():
            cursor = connection.execute("""
                INSERT OR IGNORE INTO prices
                (ticker, date, open, high, low, close, volume,
                 exchange, timezone_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['ticker'], str(row['date']),
                row['open'], row['high'], row['low'],
                row['close'], row['volume'],
                row['exchange'], row['timezone_source']
            ))
            rows_inserted += cursor.rowcount

        # Log the fetch for data lineage — every insert traceable
        # to its source and timestamp, matching ops audit standards
        connection.execute("""
            INSERT INTO fetch_log
            (ticker, exchange, date_from, date_to, rows_inserted, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            price_data['ticker'].iloc[0],
            price_data['exchange'].iloc[0],
            str(price_data['date'].min()),
            str(price_data['date'].max()),
            rows_inserted,
            source
        ))

    logger.info(f"Inserted {rows_inserted} rows for {price_data['ticker'].iloc[0]}")
    return rows_inserted


def load_prices(
    ticker: str,
    date_from: str,
    date_to: str
) -> pd.DataFrame:
    """
    Load price data for a ticker from the local database.

    Always called before API fetching — local database is the
    primary data source. API is only called for missing dates.

    Args:
        ticker:    Market ticker symbol
        date_from: Start of range 'YYYY-MM-DD'
        date_to:   End of range 'YYYY-MM-DD'

    Returns:
        DataFrame of price data from database for this ticker
        and date range. Empty DataFrame if no data found.
    """
    query = """
        SELECT * FROM prices
        WHERE ticker = ?
        AND date BETWEEN ? AND ?
        ORDER BY date ASC
    """
    with sqlite3.connect(DB_PATH) as connection:
        return pd.read_sql_query(
            query,
            connection,
            params=(ticker, date_from, date_to)
        )


def log_reconciliation_result(
    ticker: str,
    exchange: str,
    check_type: str,
    status: str,
    issue_detail: str = None
) -> None:
    """
    Write a reconciliation check result to reconciliation_log.

    Every check result — PASS or BREAK — is permanently recorded
    with full detail. This provides a complete audit trail of all
    data quality checks run, matching how real ops teams document
    their daily reconciliation work for compliance purposes.

    Args:
        ticker:       Market ticker symbol
        exchange:     Exchange the ticker trades on
        check_type:   Type of check: 'continuity', 'outliers', 'volume'
        status:       Result: 'PASS' or 'BREAK'
        issue_detail: Full description of the issue if status is BREAK
    """
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("""
            INSERT INTO reconciliation_log
            (ticker, exchange, check_type, status, issue_detail)
            VALUES (?, ?, ?, ?, ?)
        """, (ticker, exchange, check_type, status, issue_detail))
