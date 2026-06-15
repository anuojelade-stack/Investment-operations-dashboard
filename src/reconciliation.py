# ============================================================
# reconciliation.py — automated data quality checks
#
# Reconciliation is the defining daily function of investment
# operations. Before NAV calculations run and before any report
# reaches a portfolio manager or client, ops analysts verify
# that data is complete, accurate, and internally consistent.
# This module automates that process across every ticker in
# config.ALL_TICKERS spanning three exchanges simultaneously.
#
# Adapts automatically when tickers change in config.py.
# TICKER_EXCHANGE_MAP ensures the correct holiday calendar is
# always applied per ticker — no manual configuration needed.
#
# Three checks mirror the exact morning workflow of real
# investment operations teams:
#
#   1. Price continuity  — every expected trading day present?
#      Checked only within each ticker's actual stored date
#      range — days before data collection began are never
#      flagged as missing. A genuine missing day within the
#      stored range is a BREAK that blocks NAV calculation.
#      Holiday calendars applied automatically per exchange:
#        LSE    — UK bank holidays (England and Wales)
#        XETRA  — German public holidays
#        NYSE   — US federal holidays
#      Genuine market closures never trigger false breaks.
#
#   2. Return outliers   — daily move beyond ±5% flagged as
#      REVIEW. Almost always a corporate action ops must
#      document: stock split, special dividend, rights issue,
#      merger announcement. Flagged for analyst sign-off
#      before that day's valuation is considered clean.
#
#   3. Volume anomalies  — beyond 3 standard deviations from
#      rolling 30-day average flagged as REVIEW. Indicates
#      either a probable data vendor error or a significant
#      market event requiring documentation. Not a hard block
#      but must be reviewed before reports are distributed.
#
# Status definitions — three outcomes used throughout:
#   PASS    — check clean, no action required
#   REVIEW  — flagged for analyst review, not a hard block
#             on valuations. Common for volatile equities.
#   BREAK   — critical data issue. Blocks NAV calculation.
#             Must be resolved before ops proceeds.
#
# All results logged to reconciliation_log as PASS, REVIEW,
# or BREAK. Mirrors how real ops teams document daily recon
# for internal audit and compliance purposes.
# ============================================================

import logging
from datetime import date, timedelta

import pandas as pd

from src.config import (
    ALL_TICKERS,
    TICKER_EXCHANGE_MAP,
    RETURN_OUTLIER_THRESHOLD_PCT,
    VOLUME_ANOMALY_STD_DEVIATIONS
)
from src.database import load_prices, log_reconciliation_result

logger = logging.getLogger(__name__)

# Wide window used when loading all stored data for a ticker.
# Deliberately broad so we always capture the full stored range
# regardless of when data collection began.
_LOAD_START = '2020-01-01'
_LOAD_END   = '2026-12-31'

# Recency buffer — do not flag the last N calendar days as missing.
# Accounts for T+1 settlement lag and weekend/holiday edge cases
# where the most recent trading day may not yet be in the feed.
_RECENCY_BUFFER_DAYS = 3


def check_price_continuity(ticker: str, exchange: str) -> dict:
    """
    Check that all expected trading days are present in the database.

    Checks only within each ticker's actual stored date range — days
    before the first stored record are never flagged as missing, since
    those dates were never requested from the API. A genuine missing
    day within the stored range signals a broken feed for that date
    and requires investigation before any NAV calculation proceeds.

    Holiday calendars applied per exchange so genuine market closures
    (UK bank holidays, US federal holidays, German public holidays)
    never produce false BREAK flags.

    Args:
        ticker:   Market ticker symbol
        exchange: Exchange code: 'US', 'UK', or 'EU'

    Returns:
        Dict with keys: status ('PASS' or 'BREAK'),
        missing_dates (list), issue_detail (str or None).
    """
    prices = load_prices(ticker, _LOAD_START, _LOAD_END)

    if prices.empty:
        issue = f"{ticker}: no price data found in database — feed check required"
        log_reconciliation_result(ticker, exchange, 'continuity', 'BREAK', issue)
        return {'status': 'BREAK', 'missing_dates': [], 'issue_detail': issue}

    stored_dates = set(pd.to_datetime(prices['date']).dt.date)

    # Bound the calendar check to the ticker's own data range.
    # This prevents false breaks for dates before data collection began.
    data_start = min(stored_dates)
    data_end   = max(stored_dates)

    expected_dates = _get_expected_trading_dates(exchange, data_start, data_end)

    # Apply recency buffer — exclude the last few days from the check
    # to account for T+1 settlement and weekend boundary edge cases.
    recency_cutoff = date.today() - timedelta(days=_RECENCY_BUFFER_DAYS)
    expected_dates = {d for d in expected_dates if d <= recency_cutoff}

    missing_dates = sorted(expected_dates - stored_dates)

    if missing_dates:
        issue = (
            f"Missing {len(missing_dates)} trading day(s) within stored range "
            f"[{data_start} → {data_end}]: {missing_dates[:5]}"
            f"{'...' if len(missing_dates) > 5 else ''}"
        )
        log_reconciliation_result(ticker, exchange, 'continuity', 'BREAK', issue)
        return {'status': 'BREAK', 'missing_dates': missing_dates, 'issue_detail': issue}

    log_reconciliation_result(ticker, exchange, 'continuity', 'PASS')
    return {'status': 'PASS', 'missing_dates': [], 'issue_detail': None}


def check_return_outliers(
    ticker: str,
    exchange: str,
    threshold_pct: float = RETURN_OUTLIER_THRESHOLD_PCT
) -> dict:
    """
    Flag any daily return exceeding the outlier threshold as REVIEW.

    Daily moves beyond ±5% almost always have an identifiable cause —
    earnings surprise, macro announcement, corporate action (stock split,
    special dividend, rights issue). These are flagged as REVIEW rather
    than BREAK: the move may be entirely legitimate and already processed,
    but an analyst must confirm and document it before the day's valuation
    is considered signed-off. Common for high-volatility equities like
    large-cap US tech names.

    Args:
        ticker:        Market ticker symbol
        exchange:      Exchange code for logging
        threshold_pct: Alert threshold in percentage points. Default 5.0%
                       defined in config.RETURN_OUTLIER_THRESHOLD_PCT

    Returns:
        Dict with status ('PASS' or 'REVIEW'), flagged_dates list,
        issue_detail string.
    """
    prices = load_prices(ticker, _LOAD_START, _LOAD_END)

    if prices.empty:
        issue = f"{ticker}: no data available for outlier check"
        log_reconciliation_result(ticker, exchange, 'outliers', 'BREAK', issue)
        return {'status': 'BREAK', 'flagged_dates': [], 'issue_detail': issue}

    threshold_decimal    = threshold_pct / 100
    prices               = prices.copy()
    prices['daily_return'] = pd.to_numeric(prices['close'], errors='coerce').pct_change()

    outliers = prices[prices['daily_return'].abs() > threshold_decimal]

    if not outliers.empty:
        flagged = [
            f"{row['date']}: {row['daily_return']:.1%}"
            for _, row in outliers.iterrows()
        ]
        issue = (
            f"{len(flagged)} day(s) exceed ±{threshold_pct:.0f}% threshold — "
            f"analyst review required: {'; '.join(flagged[:3])}"
            f"{'...' if len(flagged) > 3 else ''}"
        )
        log_reconciliation_result(ticker, exchange, 'outliers', 'REVIEW', issue)
        return {'status': 'REVIEW', 'flagged_dates': flagged, 'issue_detail': issue}

    log_reconciliation_result(ticker, exchange, 'outliers', 'PASS')
    return {'status': 'PASS', 'flagged_dates': [], 'issue_detail': None}


def check_volume_anomalies(
    ticker: str,
    exchange: str,
    std_threshold: float = VOLUME_ANOMALY_STD_DEVIATIONS
) -> dict:
    """
    Flag days where volume exceeds the rolling average by std_threshold.

    Volume beyond 3 standard deviations from the 30-day rolling average
    warrants investigation — it may indicate a data vendor error (duplicated
    feed, incorrect unit reporting) or a genuine market event (index
    inclusion, major news) that should be documented. Flagged as REVIEW:
    not a hard block on valuations, but must be signed off before
    the day's data is considered clean for reporting purposes.

    Args:
        ticker:        Market ticker symbol
        exchange:      Exchange code for logging
        std_threshold: Standard deviation multiplier. Default 3.0
                       defined in config.VOLUME_ANOMALY_STD_DEVIATIONS

    Returns:
        Dict with status ('PASS' or 'REVIEW'), flagged_dates list,
        issue_detail string.
    """
    prices = load_prices(ticker, _LOAD_START, _LOAD_END)

    if prices.empty:
        issue = f"{ticker}: no data available for volume check"
        log_reconciliation_result(ticker, exchange, 'volume', 'BREAK', issue)
        return {'status': 'BREAK', 'flagged_dates': [], 'issue_detail': issue}

    volume       = pd.to_numeric(prices['volume'], errors='coerce')
    rolling_mean = volume.rolling(window=30).mean()
    rolling_std  = volume.rolling(window=30).std()

    # Statistical threshold: mean + N standard deviations.
    # In a normal distribution, values beyond 3σ occur in fewer
    # than 0.3% of observations — genuinely anomalous activity.
    anomaly_mask   = volume > (rolling_mean + std_threshold * rolling_std)
    anomalous_days = prices[anomaly_mask]['date'].tolist()

    if anomalous_days:
        issue = (
            f"{len(anomalous_days)} day(s) exceed {std_threshold:.0f}σ volume threshold — "
            f"data vendor or market event review required"
        )
        log_reconciliation_result(ticker, exchange, 'volume', 'REVIEW', issue)
        return {'status': 'REVIEW', 'flagged_dates': anomalous_days, 'issue_detail': issue}

    log_reconciliation_result(ticker, exchange, 'volume', 'PASS')
    return {'status': 'PASS', 'flagged_dates': [], 'issue_detail': None}


def generate_reconciliation_report() -> dict:
    """
    Run all three checks across every ticker and print a formatted report.

    Runs check_price_continuity, check_return_outliers, and
    check_volume_anomalies for every ticker in config.ALL_TICKERS.
    All results logged to reconciliation_log automatically by each
    check function. Prints a clean summary to terminal and returns
    a structured dict for use by report_generator.py.

    Status summary:
      PASS   — data clean, no action required
      REVIEW — flagged for analyst review, does not block valuations
      BREAK  — critical issue, must be resolved before NAV runs

    Returns:
        Dict with total_checks, pass_count, review_count, break_count,
        and results list for each ticker and check combination.
    """
    print("\nRECONCILIATION REPORT — Investment Operations Pipeline")
    print("=" * 60)

    results      = []
    pass_count   = 0
    review_count = 0
    break_count  = 0

    for ticker in ALL_TICKERS:
        exchange = TICKER_EXCHANGE_MAP.get(ticker, 'UNKNOWN')

        checks = {
            'continuity': check_price_continuity(ticker, exchange),
            'outliers':   check_return_outliers(ticker, exchange),
            'volume':     check_volume_anomalies(ticker, exchange)
        }

        for check_name, result in checks.items():
            status = result['status']
            detail = result.get('issue_detail') or ''

            if status == 'PASS':
                pass_count += 1
                print(f"  {ticker:<10} | {check_name:<12} | PASS")
            elif status == 'REVIEW':
                review_count += 1
                # Truncate detail for terminal readability
                short_detail = (detail[:70] + '...') if len(detail) > 70 else detail
                print(f"  {ticker:<10} | {check_name:<12} | REVIEW — {short_detail}")
            else:
                break_count += 1
                short_detail = (detail[:70] + '...') if len(detail) > 70 else detail
                print(f"  {ticker:<10} | {check_name:<12} | BREAK  — {short_detail}")

            results.append({
                'ticker':   ticker,
                'exchange': exchange,
                'check':    check_name,
                'status':   status,
                'detail':   detail
            })

    total_checks = pass_count + review_count + break_count

    print("=" * 60)
    print(
        f"  SUMMARY: {total_checks} checks | "
        f"{pass_count} PASS | "
        f"{review_count} REVIEW | "
        f"{break_count} BREAK"
    )

    if break_count > 0:
        print(f"  ACTION:  {break_count} BREAK item(s) — resolve before running valuations")
    if review_count > 0:
        print(f"  REVIEW:  {review_count} item(s) flagged — analyst sign-off required")
    if break_count == 0 and review_count == 0:
        print("  STATUS:  All checks clean — pipeline clear to proceed")

    print("=" * 60 + "\n")

    return {
        'total_checks': total_checks,
        'pass_count':   pass_count,
        'review_count': review_count,
        'break_count':  break_count,
        'results':      results
    }


def _get_expected_trading_dates(
    exchange: str,
    start: date,
    end: date
) -> set:
    """
    Return the set of expected trading dates for a given exchange
    within the specified date range.

    Applies the correct public holiday calendar per exchange so
    genuine market closures never trigger false BREAK flags in the
    continuity check. UK bank holidays for LSE, German public
    holidays for XETRA, US federal holidays for NYSE/NASDAQ.

    Args:
        exchange: Exchange code 'US', 'UK', or 'EU'
        start:    First date to include in the expected set
        end:      Last date to include in the expected set

    Returns:
        Set of date objects representing expected trading days
        within [start, end] for the given exchange.
    """
    import pandas_market_calendars as mcal

    calendar_map = {
        'US': 'NYSE',
        'UK': 'LSE',
        'EU': 'EUREX'
    }

    calendar_name = calendar_map.get(exchange, 'NYSE')
    calendar      = mcal.get_calendar(calendar_name)
    schedule      = calendar.schedule(
        start_date=start.strftime('%Y-%m-%d'),
        end_date=end.strftime('%Y-%m-%d')
    )

    return set(schedule.index.date)
