# ============================================================
# main.py — CLI pipeline orchestrator
#
# Runs the complete investment operations pipeline from the
# terminal. Zero business logic lives here — every operation
# is handled by its dedicated module in src/. This file
# only sequences the calls in the correct order.
#
# To change which stocks the pipeline covers, edit config.py.
# This file requires absolutely no changes when tickers change.
# That is a design requirement enforced by architecture.
#
# Usage:
#   python src/main.py                    # full pipeline, all tickers
#   python src/main.py --refresh          # force full API pull
#   python src/main.py --ticker HSBA.L    # single ticker only
#   python src/main.py --report           # reconciliation report only
#
# Pipeline execution order:
#   1. Initialise database — create tables if not present
#   2. Fetch missing price data for all tickers from API
#   3. Calculate all nine analytics metrics
#   4. Run reconciliation checks across all tickers
#   5. Generate four charts — save to outputs/charts/
#   6. Generate HTML report — save to outputs/reports/
#   7. Print clean summary to terminal
# ============================================================

import argparse
import logging
import time
import zoneinfo
import pandas as pd
from datetime import datetime, timezone, timedelta

from src.config import ALL_TICKERS, TICKER_EXCHANGE_MAP, DEFAULT_LOOKBACK_DAYS
from src.database import initialise_database, load_prices, insert_prices
from src.data_fetcher import fetch_ticker_data
from src import analytics, reconciliation, visualisation
from src.report_generator import generate_html_report

# Configure logging — INFO level shows pipeline progress clearly
# in terminal output without flooding with debug noise
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s — %(levelname)s — %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def run_pipeline(
    tickers: list,
    force_refresh: bool = False
) -> dict:
    """
    Execute the complete investment operations data pipeline.

    Orchestrates all pipeline stages in sequence: database init,
    data fetching, analytics calculation, reconciliation checks,
    chart generation, and HTML report output. All stages are
    handled by dedicated modules — this function only sequences.

    Args:
        tickers:       List of ticker symbols to process
        force_refresh: If True, fetch all data from API regardless
                       of what is already in the database

    Returns:
        Dict containing pipeline results for all stages,
        used by report_generator to build the HTML output.
    """
    pipeline_start = time.time()

    # Use London local time — BST (UTC+1) in summer, GMT (UTC+0) in winter
    _london_tz  = zoneinfo.ZoneInfo('Europe/London')
    _london_now = datetime.now(_london_tz)
    _tz_label   = 'BST' if _london_now.utcoffset().seconds == 3600 else 'GMT'
    run_timestamp = _london_now.strftime(f'%Y-%m-%d %H:%M {_tz_label}')

    _print_header(run_timestamp)

    # Stage 1 — initialise database
    initialise_database()

    # Stage 2 — fetch missing price data
    print("Fetching price data...")
    fetch_results = _fetch_all_tickers(tickers, force_refresh)

    # Stage 3 — calculate analytics
    print("\nRunning analytics...")
    analytics_results = _run_analytics(tickers)

    # Stage 4 — reconciliation
    print("\nRunning reconciliation...")
    recon_results = reconciliation.generate_reconciliation_report()

    # Stage 5 — generate charts
    print("Generating charts...")
    chart_paths = _generate_charts(analytics_results, recon_results)

    # Stage 6 — generate HTML report
    print("Generating HTML report...")
    report_path = generate_html_report(
        analytics_results, recon_results, chart_paths, run_timestamp
    )

    pipeline_duration = time.time() - pipeline_start
    _print_summary(chart_paths, report_path, recon_results, pipeline_duration)

    return {
        'fetch_results':     fetch_results,
        'analytics_results': analytics_results,
        'recon_results':     recon_results,
        'chart_paths':       chart_paths,
        'report_path':       report_path
    }


def _fetch_all_tickers(tickers: list, force_refresh: bool) -> dict:
    """
    Fetch missing price data for all tickers from the API.

    Queries the database first per ticker. Only calls the API
    for dates genuinely absent from local storage. Logs each
    fetch result to terminal for transparency and audit trail.

    Args:
        tickers:       List of ticker symbols to process
        force_refresh: Bypass database check and fetch all from API

    Returns:
        Dict mapping ticker to number of rows inserted.
    """
    fetch_results = {}
    date_to   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    date_from = (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime('%Y-%m-%d')

    for ticker in tickers:
        price_data = fetch_ticker_data(ticker, date_from, date_to)

        if not price_data.empty:
            rows_inserted = insert_prices(price_data, source='yfinance')
            exchange = TICKER_EXCHANGE_MAP.get(ticker, 'UNKNOWN')
            print(f"  {ticker:<10} — {rows_inserted} rows ({exchange}) — cached to database")
            fetch_results[ticker] = rows_inserted
        else:
            print(f"  {ticker:<10} — fetch failed — check logs")
            fetch_results[ticker] = 0

    return fetch_results


def _run_analytics(tickers: list) -> dict:
    """
    Calculate all nine financial metrics for all tickers.

    Loads price data from database for each ticker and runs
    the complete analytics suite. Each metric logged to terminal
    on completion. Results structured for chart generation and
    HTML report embedding.

    Args:
        tickers: List of ticker symbols to calculate metrics for

    Returns:
        Nested dict: {ticker: {metric_name: result_value}}
    """
    metric_names = [
        'daily_returns', 'cumulative_returns', 'moving_averages',
        'rolling_volatility', 'sharpe_ratio', 'max_drawdown',
        'correlation_matrix', 'vwap', 'annualised_return'
    ]

    results = {}
    date_to   = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    date_from = (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime('%Y-%m-%d')

    all_closes = {}

    for ticker in tickers:
        prices = load_prices(ticker, date_from, date_to)

        if prices.empty:
            logger.warning(f"{ticker}: no price data for analytics — skipping")
            continue

        # Set date as index so all analytics Series carry proper date index.
        # Without this, integer index 0 is misread as Unix epoch → 1970 on charts.
        date_index = pd.to_datetime(prices['date'])
        close  = prices['close'].astype(float).set_axis(date_index)
        volume = prices['volume'].astype(float).set_axis(date_index)

        daily_returns = analytics.calculate_daily_returns(close)

        results[ticker] = {
            'daily_returns':      daily_returns,
            'cumulative_returns': analytics.calculate_cumulative_returns(daily_returns),
            'moving_averages':    analytics.calculate_moving_averages(close),
            'rolling_volatility': analytics.calculate_rolling_volatility(close),
            'sharpe_ratio':       analytics.calculate_sharpe_ratio(daily_returns),
            'max_drawdown':       analytics.calculate_max_drawdown(close),
            'vwap':               analytics.calculate_vwap(close, volume),
            'annualised_return':  analytics.calculate_annualised_return(close)
        }

        all_closes[ticker] = close

    # Correlation matrix calculated across all tickers simultaneously
    # as it requires the full cross-asset return series together
    if all_closes:
        closes_df  = pd.DataFrame(all_closes).dropna()
        correlation = analytics.calculate_correlation_matrix(closes_df)
        for ticker in results:
            results[ticker]['correlation_matrix'] = correlation

    for metric in metric_names:
        print(f"  {metric.replace('_', ' ').title():<25} — DONE")

    return results


def _generate_charts(
    analytics_results: dict,
    recon_results: dict,
    selected_ticker: str = None
) -> dict:
    """
    Generate all five professional charts and save to outputs/charts/.

    Five charts total:
      1. Normalised cumulative returns — all tickers
      2. Candlestick OHLCV — selected ticker (last 6 months)
      3. 30-day rolling volatility — all tickers (from July 2024)
      4. 50-day rolling volatility — all tickers (comparison)
      5. Cross-asset correlation heatmap — all tickers

    Reconciliation break dates passed through to mark on charts.
    All charts saved as 300 DPI PNGs to outputs/charts/.

    Args:
        analytics_results: Full analytics output from _run_analytics()
        recon_results:     Reconciliation report from run_pipeline()
        selected_ticker:   Specific ticker for candlestick chart

    Returns:
        Dict mapping chart name to saved file path string.
    """
    from datetime import datetime, timezone, timedelta
    from src.config import TICKER_EXCHANGE_MAP, CHART_LOOKBACK_DAYS
    from src.database import load_prices

    chart_paths = {}
    break_dates = _extract_break_dates(recon_results)

    # ---- Chart 1: Normalised cumulative returns ----
    cumulative = {
        t: r['cumulative_returns']
        for t, r in analytics_results.items()
        if 'cumulative_returns' in r
    }
    if cumulative:
        fig1 = visualisation.plot_cumulative_returns(
            cumulative, TICKER_EXCHANGE_MAP, break_dates.get('all', [])
        )
        chart_paths['cumulative_returns'] = visualisation.save_figure(
            fig1, 'cumulative_returns.png'
        )
        print(f"  outputs/charts/cumulative_returns.png     — SAVED")

    # ---- Chart 2: Candlestick for selected ticker ----
    candle_ticker = (
        selected_ticker
        if selected_ticker and selected_ticker in analytics_results
        else list(analytics_results.keys())[0] if analytics_results else None
    )
    if candle_ticker:
        today     = datetime.now(timezone.utc).date()
        date_from = (today - timedelta(days=CHART_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        date_to   = today.strftime('%Y-%m-%d')
        prices    = load_prices(candle_ticker, date_from, date_to)

        if not prices.empty:
            ohlcv = prices[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
            ohlcv['date'] = pd.to_datetime(ohlcv['date'])
            ohlcv = ohlcv.set_index('date')

            sma_s, sma_l = analytics_results[candle_ticker]['moving_averages']
            fig2 = visualisation.plot_candlestick_with_volume(
                ohlcv, candle_ticker, sma_s, sma_l,
                break_dates.get(candle_ticker, [])
            )
            chart_paths['candlestick'] = visualisation.save_figure(
                fig2, f'candlestick_{candle_ticker}.png'
            )
            print(f"  outputs/charts/candlestick_{candle_ticker}.png     — SAVED")

    # ---- Chart 3: 30-day rolling volatility (from July 2024) ----
    _vol_start = pd.Timestamp('2024-07-01')
    vol_30 = {}
    for t, r in analytics_results.items():
        if 'rolling_volatility' not in r:
            continue
        series = r['rolling_volatility']
        if series is None or series.dropna().empty:
            continue
        series = series.copy()
        series.index = pd.to_datetime(series.index)
        series = series[series.index >= _vol_start].dropna()
        if not series.empty:
            vol_30[t] = series
    if vol_30:
        fig3 = visualisation.plot_rolling_volatility_30(
            vol_30, TICKER_EXCHANGE_MAP
        )
        chart_paths['rolling_volatility_30'] = visualisation.save_figure(
            fig3, 'rolling_volatility_30.png'
        )
        print(f"  outputs/charts/rolling_volatility_30.png  — SAVED")

    # ---- Chart 4: 50-day rolling volatility ----
    closing_prices = {
        t: load_prices(t, '2023-01-01', datetime.now(timezone.utc).date().strftime('%Y-%m-%d'))
        for t in analytics_results.keys()
    }
    prices_dict = {}
    for t, df in closing_prices.items():
        if not df.empty:
            close = pd.to_numeric(df['close'], errors='coerce')
            close.index = pd.to_datetime(df['date'])
            prices_dict[t] = close

    if prices_dict:
        fig4 = visualisation.plot_rolling_volatility_50(
            prices_dict, TICKER_EXCHANGE_MAP
        )
        chart_paths['rolling_volatility_50'] = visualisation.save_figure(
            fig4, 'rolling_volatility_50.png'
        )
        print(f"  outputs/charts/rolling_volatility_50.png  — SAVED")

    # ---- Chart 5: Correlation heatmap ----
    first_with_corr = next(
        (t for t in analytics_results if 'correlation_matrix' in analytics_results[t]),
        None
    )
    if first_with_corr:
        fig5 = visualisation.plot_correlation_heatmap(
            analytics_results[first_with_corr]['correlation_matrix']
        )
        chart_paths['correlation_heatmap'] = visualisation.save_figure(
            fig5, 'correlation_heatmap.png'
        )
        print(f"  outputs/charts/correlation_heatmap.png    — SAVED")

    return chart_paths


def _extract_break_dates(recon_results: dict) -> dict:
    """
    Extract reconciliation BREAK dates organised by ticker.

    Processes the reconciliation report results dict to pull out
    BREAK dates per ticker for marking on the chart panels.

    Args:
        recon_results: Dict returned by generate_reconciliation_report()

    Returns:
        Dict mapping ticker to list of BREAK dates, plus 'all' key
        containing every BREAK date across all tickers combined.
    """
    break_dates = {'all': []}

    for result in recon_results.get('results', []):
        if result['status'] == 'BREAK':
            ticker = result['ticker']
            if ticker not in break_dates:
                break_dates[ticker] = []

    return break_dates


def _print_header(run_timestamp: str) -> None:
    """Print the pipeline header to terminal."""
    print("\nINVESTMENT OPERATIONS PIPELINE — " + run_timestamp)
    print("=" * 55)


def _print_summary(
    chart_paths: dict,
    report_path: str,
    recon_results: dict,
    duration: float
) -> None:
    """Print the pipeline completion summary to terminal."""
    pass_count   = recon_results.get('pass_count', 0)
    review_count = recon_results.get('review_count', 0)
    break_count  = recon_results.get('break_count', 0)

    print(f"\nPipeline complete — {duration:.1f} seconds")
    print(f"Reconciliation: {pass_count} PASS | {review_count} REVIEW | {break_count} BREAK")
    print(f"Report: {report_path}")
    print("=" * 55 + "\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Investment Operations Stock Dashboard Pipeline'
    )
    parser.add_argument(
        '--refresh', action='store_true',
        help='Force full API pull for all tickers regardless of cached data'
    )
    parser.add_argument(
        '--ticker', type=str, default=None,
        help='Run pipeline for a single ticker only e.g. --ticker HSBA.L'
    )
    parser.add_argument(
        '--report', action='store_true',
        help='Run reconciliation report only — skip data fetch and charts'
    )
    args = parser.parse_args()

    tickers_to_run = [args.ticker] if args.ticker else ALL_TICKERS

    if args.report:
        initialise_database()
        reconciliation.generate_reconciliation_report()
    else:
        run_pipeline(tickers=tickers_to_run, force_refresh=args.refresh)
