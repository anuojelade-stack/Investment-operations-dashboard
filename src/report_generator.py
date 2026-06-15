# ============================================================
# report_generator.py — single file multi-page HTML report
#
# Generates ONE self-contained HTML file containing:
#
#   Landing page    — overview dashboard with:
#                       · Normalised cumulative returns chart
#                       · 30-day and 50-day volatility side by side
#                       · Cross-asset correlation heatmap
#                       · Reconciliation summary table
#                       · Clickable grid of all 15 tickers
#
#   Stock pages     — individual page per ticker (hidden by
#                     default, shown on click) containing:
#                       · OHLCV candlestick via mplfinance
#                       · 20 and 50-day moving averages
#                       · Last 6 months of price data
#                       · Four key metrics for that stock
#                       · Back button to landing page
#
# Navigation handled by JavaScript show/hide — no server,
# no separate files, no external dependencies whatsoever.
# One double-click opens the entire dashboard in any browser.
# ============================================================

import base64
import logging
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.config import (
    REPORTS_DIR, TICKERS_US, TICKERS_UK, TICKERS_EU,
    ALL_TICKERS, TICKER_EXCHANGE_MAP,
    CHART_LOOKBACK_DAYS, MOVING_AVERAGE_SHORT, MOVING_AVERAGE_LONG
)

logger = logging.getLogger(__name__)

# ============================================================
# COLOUR PALETTE — unique colour per ticker by exchange family
# US = blue family, UK = purple/pink family, EU = green family
# ============================================================

TICKER_COLOURS = {}
_us = ['#1f77b4', '#4fa8d4', '#0a4a7a', '#5bb8e8', '#2196f3']
_uk = ['#9c27b0', '#e91e8c', '#c678dd', '#7b2d8b', '#d2a8ff']
_eu = ['#2ea043', '#56d364', '#1a7431', '#3fb950', '#88d8a3']
for i, t in enumerate(TICKERS_US): TICKER_COLOURS[t] = _us[i % 5]
for i, t in enumerate(TICKERS_UK): TICKER_COLOURS[t] = _uk[i % 5]
for i, t in enumerate(TICKERS_EU): TICKER_COLOURS[t] = _eu[i % 5]

EXCHANGE_LABEL = {
    **{t: 'NYSE / NASDAQ' for t in TICKERS_US},
    **{t: 'LSE'           for t in TICKERS_UK},
    **{t: 'XETRA / DAX'   for t in TICKERS_EU}
}

EXCHANGE_CSS = {
    **{t: 'us' for t in TICKERS_US},
    **{t: 'uk' for t in TICKERS_UK},
    **{t: 'eu' for t in TICKERS_EU}
}

# ============================================================
# CSS
# ============================================================

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117;
    color: #c9d1d9;
    font-size: 14px;
    line-height: 1.6;
}

.page { display: none; padding: 40px 48px; min-height: 100vh; }
.page.active { display: block; }

.header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    padding-bottom: 24px;
    margin-bottom: 40px;
    border-bottom: 1px solid #21262d;
}
.header h1 { font-size: 20px; font-weight: 500; color: #f0f6fc; }
.header .subtitle { font-size: 12px; color: #6e7681; margin-top: 4px; }
.header .meta { font-size: 12px; color: #6e7681; text-align: right; }

.section-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6e7681;
    margin-bottom: 16px;
}

.metrics-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 48px;
}
.metric-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 20px 24px;
}
.metric-card .label {
    font-size: 11px; font-weight: 500; text-transform: uppercase;
    letter-spacing: 0.07em; color: #6e7681; margin-bottom: 10px;
}
.metric-card .value { font-size: 26px; font-weight: 500; color: #f0f6fc; }
.metric-card .sub { font-size: 11px; color: #6e7681; margin-top: 6px; }
.metric-card.pos .value { color: #3fb950; }
.metric-card.neg .value { color: #f85149; }
.metric-card.neu .value { color: #58a6ff; }

.chart-full {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 48px;
}
.charts-grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 48px;
}
.chart-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 20px;
    overflow: hidden;
}
.chart-label {
    font-size: 12px;
    color: #8b949e;
    margin-bottom: 14px;
    font-weight: 500;
}
.chart-full img,
.chart-card img { width: 100%; border-radius: 4px; display: block; }

.ticker-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 48px;
}
.ticker-btn {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 14px 16px;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
    width: 100%;
}
.ticker-btn:hover { background: #1c2128; border-color: #388bfd; }
.ticker-btn .t-name { font-size: 14px; font-weight: 500; color: #f0f6fc; }
.ticker-btn .t-ex   { font-size: 11px; color: #6e7681; margin-top: 4px; }
.ticker-btn.us { border-top: 2px solid #1f77b4; }
.ticker-btn.uk { border-top: 2px solid #9c27b0; }
.ticker-btn.eu { border-top: 2px solid #2ea043; }

.back-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    color: #58a6ff;
    cursor: pointer;
    margin-bottom: 32px;
    transition: border-color 0.15s;
}
.back-btn:hover { border-color: #58a6ff; }

.recon-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 48px;
    font-size: 13px;
}
.recon-table thead tr { background: #161b22; border-bottom: 1px solid #21262d; }
.recon-table th {
    text-align: left; padding: 12px 16px;
    font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.07em; color: #6e7681;
}
.recon-table td { padding: 11px 16px; border-bottom: 1px solid #161b22; color: #c9d1d9; }
.recon-table tbody tr { cursor: pointer; }
.recon-table tbody tr:hover { background: #161b22; }
.pass   { color: #3fb950; font-weight: 500; }
.break  { color: #f85149; font-weight: 500; }
.detail { color: #8b949e; font-size: 12px; }

.badge {
    display: inline-block;
    font-size: 10px; font-weight: 600;
    padding: 2px 8px; border-radius: 20px;
}
.badge-us { background: #0d2644; color: #58a6ff; }
.badge-uk { background: #2d1a30; color: #d2a8ff; }
.badge-eu { background: #0d2d1a; color: #3fb950; }

.status-ok {
    background: #0a1a0f; border: 1px solid #123d1c;
    border-radius: 6px; padding: 10px 16px;
    font-size: 12px; color: #3fb950; margin-bottom: 16px;
}
.status-warn {
    background: #1a0a0a; border: 1px solid #3d1212;
    border-radius: 6px; padding: 10px 16px;
    font-size: 12px; color: #f85149; margin-bottom: 16px;
}

.summary-bar {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 8px; padding: 16px 24px;
    display: flex; gap: 40px; margin-bottom: 16px;
}
.summary-item { font-size: 13px; color: #6e7681; }
.summary-item span { color: #f0f6fc; font-weight: 500; margin-left: 6px; }
.summary-item .pass  { color: #3fb950; }
.summary-item .break { color: #f85149; }

.footer {
    border-top: 1px solid #21262d;
    padding-top: 20px; margin-top: 40px;
    font-size: 11px; color: #6e7681;
    display: flex; justify-content: space-between;
}
"""

# ============================================================
# JAVASCRIPT — single page app navigation
# ============================================================

JS = """
function showPage(pageId) {
    document.querySelectorAll('.page').forEach(function(p) {
        p.classList.remove('active');
    });
    var target = document.getElementById(pageId);
    if (target) {
        target.classList.add('active');
        window.scrollTo(0, 0);
    }
}

function showStock(ticker) {
    showPage('stock-' + ticker.replace(/\\./g, '_'));
}

function showHome() {
    showPage('landing');
}

document.addEventListener('DOMContentLoaded', function() {
    showPage('landing');
});
"""


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def generate_html_report(
    analytics_results: dict,
    recon_results: dict,
    chart_paths: dict,
    run_timestamp: str
) -> str:
    """
    Generate a single self-contained multi-page HTML report.

    All 15 stock pages plus the landing page live inside one
    HTML file. JavaScript handles navigation by showing and
    hiding sections. No server required — opens in any browser.

    Args:
        analytics_results: Full analytics output from pipeline
        recon_results:     Reconciliation report results dict
        chart_paths:       Dict mapping chart name to PNG path
        run_timestamp:     UTC timestamp string

    Returns:
        Full path of the saved HTML file as string.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp_clean = run_timestamp.replace(' ', '_').replace(':', '-')
    report_path     = REPORTS_DIR / f"dashboard_{timestamp_clean}.html"

    landing_html     = _build_landing_page(
        analytics_results, recon_results, chart_paths, run_timestamp
    )
    stock_pages_html = _build_all_stock_pages(analytics_results, run_timestamp)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Investment Operations Dashboard — {run_timestamp}</title>
    <style>{CSS}</style>
</head>
<body>
{landing_html}
{stock_pages_html}
<script>{JS}</script>
</body>
</html>"""

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)

    logger.info(f"Dashboard saved: {report_path}")
    return str(report_path)


# ============================================================
# LANDING PAGE
# ============================================================

def _build_landing_page(
    analytics_results: dict,
    recon_results: dict,
    chart_paths: dict,
    run_timestamp: str
) -> str:
    """
    Build the landing page HTML section.

    Layout from top to bottom:
      - Header with timestamp
      - Clickable ticker grid
      - Full width cumulative returns chart
      - Side by side: 30-day volatility | 50-day volatility
      - Full width correlation heatmap
      - Reconciliation summary and table

    Looks for both 'rolling_volatility_30' and
    'rolling_volatility_50' keys in chart_paths.
    Falls back to 'rolling_volatility' if the split
    keys are not present — backwards compatible.

    Args:
        analytics_results: Analytics results dict
        recon_results:     Reconciliation results dict
        chart_paths:       Chart file paths dict
        run_timestamp:     Pipeline timestamp string

    Returns:
        HTML string for the landing page div.
    """
    cumulative = _embed_chart(chart_paths.get('cumulative_returns', ''))
    heatmap    = _embed_chart(chart_paths.get('correlation_heatmap', ''))

    # Support both split keys and legacy single key
    vol_30_path = chart_paths.get('rolling_volatility_30') or chart_paths.get('rolling_volatility', '')
    vol_50_path = chart_paths.get('rolling_volatility_50', '')

    vol_30 = _embed_chart(vol_30_path)
    vol_50 = _embed_chart(vol_50_path)

    ticker_grid  = _build_ticker_grid()
    recon_rows   = _build_recon_rows(recon_results)
    summary_bar  = _build_summary_bar(recon_results)
    break_count  = recon_results.get('break_count', 0)
    total_checks = recon_results.get('total_checks', 0)

    status_banner = (
        f'<div class="status-warn">ACTION REQUIRED — {break_count} break(s) require investigation before valuations run</div>'
        if break_count > 0
        else f'<div class="status-ok">ALL CLEAR — All {total_checks} reconciliation checks passed</div>'
    )

    # Only show volatility comparison section if at least 30-day exists
    if vol_50_path:
        volatility_section = f"""
    <p class="section-label">Rolling volatility comparison — 30-day vs 50-day</p>
    <div class="charts-grid-2">
        <div class="chart-card">
            <div class="chart-label">
                30-day rolling annualised volatility —
                short-term signal, flags daily ops anomalies
            </div>
            {vol_30}
        </div>
        <div class="chart-card">
            <div class="chart-label">
                50-day rolling annualised volatility —
                structural trend, smooths short-term noise
            </div>
            {vol_50}
        </div>
    </div>"""
    else:
        volatility_section = f"""
    <p class="section-label">30-day rolling annualised volatility</p>
    <div class="chart-full">
        <div class="chart-label">All tickers — short-term ops monitoring signal</div>
        {vol_30}
    </div>"""

    return f"""
<div id="landing" class="page">

    <div class="header">
        <div>
            <h1>Investment Operations Dashboard</h1>
            <div class="subtitle">
                US · NYSE / NASDAQ &nbsp;|&nbsp;
                UK · London Stock Exchange &nbsp;|&nbsp;
                EU · XETRA / DAX
            </div>
        </div>
        <div class="meta">Pipeline run<br>{run_timestamp}</div>
    </div>

    <p class="section-label">Stock universe — click any stock to view detail</p>
    {ticker_grid}

    <p class="section-label">Normalised cumulative returns — 2023 to today</p>
    <div class="chart-full">
        <div class="chart-label">
            All tickers indexed to 100 on start date —
            direct comparison across USD, GBP, and EUR
        </div>
        {cumulative}
    </div>

    {volatility_section}

    <p class="section-label">Cross-asset correlation matrix</p>
    <div class="chart-full">
        <div class="chart-label">
            All 15 tickers across three exchanges —
            bright = high positive correlation · dark = low or negative
        </div>
        {heatmap}
    </div>

    <p class="section-label">Reconciliation report</p>
    {summary_bar}
    {status_banner}
    <table class="recon-table">
        <thead>
            <tr>
                <th>Ticker</th>
                <th>Exchange</th>
                <th>Check type</th>
                <th>Status</th>
                <th>Detail</th>
            </tr>
        </thead>
        <tbody>
            {recon_rows}
        </tbody>
    </table>

    <div class="footer">
        <span>Investment Operations Pipeline — automated report</span>
        <span>{run_timestamp}</span>
    </div>

</div>"""


def _build_ticker_grid() -> str:
    """
    Build clickable ticker navigation grid for the landing page.

    Each button calls showStock() to navigate to that stock page.
    Colour-coded by exchange family with a coloured top border.

    Returns:
        HTML string of the full ticker grid div.
    """
    cards = ''
    for ticker in ALL_TICKERS:
        css       = EXCHANGE_CSS.get(ticker, 'us')
        label     = EXCHANGE_LABEL.get(ticker, '')
        js_ticker = ticker.replace("'", "\\'")
        cards += f"""
        <button class="ticker-btn {css}" onclick="showStock('{js_ticker}')">
            <div class="t-name">{ticker}</div>
            <div class="t-ex">{label}</div>
        </button>"""

    return f'<div class="ticker-grid">{cards}</div>'


# ============================================================
# INDIVIDUAL STOCK PAGES
# ============================================================

def _build_all_stock_pages(
    analytics_results: dict,
    run_timestamp: str
) -> str:
    """
    Build all 15 individual stock page sections.

    Each is a hidden div shown when its ticker button is clicked.
    Contains OHLCV candlestick for last 6 months plus key metrics.
    Back button returns to the landing page.

    Args:
        analytics_results: Full analytics results dict
        run_timestamp:     Pipeline timestamp string

    Returns:
        HTML string of all 15 stock page divs concatenated.
    """
    from src.database import load_prices

    all_pages = ''

    for ticker in ALL_TICKERS:
        logger.info(f"Building stock page for {ticker}")

        today     = datetime.now(timezone.utc).date()
        date_from = (today - timedelta(days=CHART_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        date_to   = today.strftime('%Y-%m-%d')

        prices = load_prices(ticker, date_from, date_to)

        chart_b64 = (
            _generate_ohlcv_b64(prices, ticker)
            if not prices.empty
            else _placeholder_b64(ticker, "No price data — run with --refresh")
        )

        metrics_html = _build_stock_metrics(analytics_results, ticker)
        ex_label     = EXCHANGE_LABEL.get(ticker, TICKER_EXCHANGE_MAP.get(ticker, ''))
        page_id      = f"stock-{ticker.replace('.', '_')}"
        colour       = TICKER_COLOURS.get(ticker, '#888888')

        all_pages += f"""
<div id="{page_id}" class="page">

    <button class="back-btn" onclick="showHome()">
        ← Back to dashboard
    </button>

    <div class="header">
        <div>
            <h1>
                <span style="display:inline-block;width:4px;height:20px;
                             background:{colour};border-radius:2px;
                             margin-right:10px;vertical-align:middle"></span>
                {ticker}
            </h1>
            <div class="subtitle">
                {ex_label} &nbsp;·&nbsp;
                Last 6 months · SMA {MOVING_AVERAGE_SHORT} & SMA {MOVING_AVERAGE_LONG}
            </div>
        </div>
        <div class="meta">Pipeline run<br>{run_timestamp}</div>
    </div>

    <p class="section-label">Key metrics</p>
    <div class="metrics-grid">
        {metrics_html}
    </div>

    <p class="section-label">
        OHLCV candlestick — last 6 months &nbsp;·&nbsp;
        <span style="color:#f0883e">orange = SMA {MOVING_AVERAGE_SHORT}</span>
        &nbsp;·&nbsp;
        <span style="color:#d2a8ff">purple = SMA {MOVING_AVERAGE_LONG}</span>
    </p>
    <div class="chart-full">
        <div class="chart-label">
            {ticker} · Open High Low Close with Volume
        </div>
        <img src="data:image/png;base64,{chart_b64}"
             alt="{ticker} OHLCV"
             style="width:100%;border-radius:4px">
    </div>

    <div class="footer">
        <span>
            <button class="back-btn" onclick="showHome()" style="margin-bottom:0">
                ← Back to dashboard
            </button>
        </span>
        <span>{run_timestamp}</span>
    </div>

</div>"""

    return all_pages


def _generate_ohlcv_b64(prices: pd.DataFrame, ticker: str) -> str:
    """
    Generate OHLCV candlestick chart via mplfinance as base64.

    Uses last CHART_LOOKBACK_DAYS of data. 20 and 50-day SMAs
    overlaid. Dark theme consistent with the rest of the report.
    Returns placeholder if chart generation fails.

    Args:
        prices: DataFrame with OHLCV columns and date column
        ticker: Ticker symbol for title and error logging

    Returns:
        Base64 encoded PNG string for HTML src attribute.
    """
    try:
        df = prices.copy()
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()

        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df.dropna(subset=['open', 'high', 'low', 'close'])

        if df.empty:
            return _placeholder_b64(ticker, "Insufficient OHLCV data")

        sma_20 = df['close'].rolling(window=MOVING_AVERAGE_SHORT).mean()
        sma_50 = df['close'].rolling(window=MOVING_AVERAGE_LONG).mean()

        additional_plots = []
        if not sma_20.dropna().empty:
            additional_plots.append(
                mpf.make_addplot(sma_20, panel=0, color='#ffa726',
                                 width=1.5, label=f'SMA {MOVING_AVERAGE_SHORT}')
            )
        if not sma_50.dropna().empty:
            additional_plots.append(
                mpf.make_addplot(sma_50, panel=0, color='#42a5f5',
                                 width=1.5, label=f'SMA {MOVING_AVERAGE_LONG}')
            )

        # Bloomberg Terminal-inspired style — matches visualisation.py
        mc = mpf.make_marketcolors(
            up='#00c896',   down='#ef5350',
            edge={'up': '#00c896', 'down': '#ef5350'},
            wick={'up': '#00c896', 'down': '#ef5350'},
            volume={'up': '#00c896', 'down': '#ef5350'},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            facecolor='#0a0e1a', figcolor='#0a0e1a',
            gridcolor='#1a2332', gridstyle='-',
            rc={
                'axes.labelcolor':      '#8899aa',
                'xtick.color':          '#8899aa',
                'ytick.color':          '#8899aa',
                'xtick.labelsize':      9,
                'ytick.labelsize':      9,
                'axes.titlecolor':      '#c8d4e3',
                'axes.titlesize':       13,
                'figure.facecolor':     '#0a0e1a',
                'axes.spines.top':      False,
                'axes.spines.right':    False,
                'grid.alpha':           0.25,
            }
        )

        kwargs = {
            'type':        'candle',
            'style':        style,
            'volume':       True,
            'ylabel':       'Price',
            'ylabel_lower': '',
            'returnfig':    True,
            'figsize':      (14, 8),
            'tight_layout': True
        }
        if additional_plots:
            kwargs['addplot'] = additional_plots

        fig, axes = mpf.plot(df, **kwargs)

        # Remove mplfinance auto-injected figure texts
        # (e.g. "MCD · Open High Low Close with Volume" top-left)
        for txt in fig.texts:
            txt.set_visible(False)

        # Also clear any axes-level title mplfinance sets
        for ax in axes:
            ax.set_title('')

        # Currency symbol on price y-axis — derived from ticker suffix.
        # LSE tickers trade in pence (p), XETRA in € and US in $.
        import matplotlib.ticker as mticker
        currency = 'p' if ticker.endswith('.L') else '€' if ticker.endswith('.DE') else '$'
        axes[0].yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f'{currency}{x:,.2f}')
        )
        axes[0].set_ylabel(f'Price ({currency})', color='#8899aa', fontsize=10, labelpad=6)

        # SMA legend — white text so labels read cleanly on dark background
        legend = axes[0].get_legend()
        if legend:
            for text in legend.get_texts():
                text.set_color('#ffffff')

        # Format volume axis — clean M-suffix instead of 10^6 notation
        vol_ax = axes[2] if len(axes) >= 3 else (axes[1] if len(axes) >= 2 else None)
        if vol_ax is not None:
            vol_ax.yaxis.set_major_formatter(
                mticker.FuncFormatter(lambda x, _: f'{x / 1e6:.1f}M' if x >= 1e6 else f'{int(x):,}')
            )
            vol_ax.yaxis.offsetText.set_visible(False)
            vol_ax.set_facecolor('#0d1526')
            vol_ax.set_ylabel('Volume', color='#8b949e', fontsize=9, labelpad=6)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150,
                    bbox_inches='tight', facecolor='#0d1117')
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode('utf-8')

    except Exception as error:
        logger.error(f"{ticker}: OHLCV chart failed — {error}")
        return _placeholder_b64(ticker, f"Chart error: {error}")


def _build_stock_metrics(analytics_results: dict, ticker: str) -> str:
    """
    Build four metric cards for an individual stock page.

    Sharpe ratio, annualised return, max drawdown, and current
    30-day rolling volatility for the specific ticker.
    Conditional colour: green positive, red negative, blue neutral.

    Args:
        analytics_results: Full analytics results dict
        ticker:            The specific ticker to show

    Returns:
        HTML string of four metric card divs.
    """
    empty = '<div class="metric-card"><div class="label">No data</div><div class="value">—</div></div>' * 4

    if ticker not in analytics_results:
        return empty

    r = analytics_results[ticker]

    try:
        sharpe   = float(r.get('sharpe_ratio', 0) or 0)
        drawdown = float(r.get('max_drawdown', 0) or 0)
        ann_ret  = float(r.get('annualised_return', 0) or 0)
        vol_s    = r.get('rolling_volatility')
        vol      = float(vol_s.dropna().iloc[-1]) if (
            vol_s is not None and not vol_s.dropna().empty
        ) else 0.0
    except Exception:
        return empty

    return f"""
    <div class="metric-card {'pos' if sharpe > 0 else 'neg'}">
        <div class="label">Sharpe Ratio</div>
        <div class="value">{sharpe:.2f}</div>
        <div class="sub">Risk-adjusted return vs 4.5% base rate</div>
    </div>
    <div class="metric-card {'pos' if ann_ret > 0 else 'neg'}">
        <div class="label">Annualised Return</div>
        <div class="value">{ann_ret:.1%}</div>
        <div class="sub">CAGR from 2023 start date</div>
    </div>
    <div class="metric-card neg">
        <div class="label">Max Drawdown</div>
        <div class="value">{drawdown:.1%}</div>
        <div class="sub">Worst peak to trough loss</div>
    </div>
    <div class="metric-card neu">
        <div class="label">30D Volatility</div>
        <div class="value">{vol:.1f}%</div>
        <div class="sub">Current annualised (sqrt 252)</div>
    </div>"""


# ============================================================
# SHARED HELPERS
# ============================================================

def _embed_chart(file_path: str) -> str:
    """
    Embed a PNG chart file as a base64 img tag.

    Makes the HTML completely self-contained — no external
    file references. Works offline on any machine.

    Args:
        file_path: Full path string to the PNG file

    Returns:
        HTML img tag string or placeholder div if missing.
    """
    if not file_path:
        return '<div style="color:#6e7681;padding:40px;text-align:center">Chart not generated</div>'

    path = Path(file_path)
    if not path.exists():
        return f'<div style="color:#6e7681;padding:40px;text-align:center">File not found: {path.name}</div>'

    with open(path, 'rb') as f:
        encoded = base64.b64encode(f.read()).decode('utf-8')

    return f'<img src="data:image/png;base64,{encoded}" style="width:100%;border-radius:4px" alt="chart">'


def _placeholder_b64(ticker: str, message: str) -> str:
    """
    Generate a placeholder dark canvas chart as base64.

    Used when OHLCV data is unavailable so stock pages
    render cleanly with a meaningful message instead of
    a broken image or Python traceback.

    Args:
        ticker:  Ticker symbol for display
        message: Informative message to show on canvas

    Returns:
        Base64 encoded PNG string.
    """
    fig, ax = plt.subplots(figsize=(14, 8), facecolor='#0d1117')
    ax.set_facecolor('#0d1117')
    ax.text(0.5, 0.5, f'{ticker}\n{message}',
            transform=ax.transAxes, ha='center', va='center',
            color='#6e7681', fontsize=14)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100,
                bbox_inches='tight', facecolor='#0d1117')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def _build_summary_bar(recon_results: dict) -> str:
    """Build reconciliation pass/break summary bar."""
    total  = recon_results.get('total_checks', 0)
    passed = recon_results.get('pass_count', 0)
    broken = recon_results.get('break_count', 0)
    return f"""
    <div class="summary-bar">
        <div class="summary-item">Total checks<span>{total}</span></div>
        <div class="summary-item">Pass<span class="pass">{passed}</span></div>
        <div class="summary-item">Break<span class="break">{broken}</span></div>
    </div>"""


def _build_recon_rows(recon_results: dict) -> str:
    """
    Build colour-coded reconciliation table rows.

    Every row is clickable — clicking navigates to that
    ticker's individual stock page via showStock().
    PASS rows green, BREAK rows red with full detail.

    Args:
        recon_results: Dict from generate_reconciliation_report()

    Returns:
        HTML string of tr elements.
    """
    results = recon_results.get('results', [])
    if not results:
        return '<tr><td colspan="5" style="color:#6e7681;padding:16px">No results</td></tr>'

    badges = {
        'US': '<span class="badge badge-us">NYSE</span>',
        'UK': '<span class="badge badge-uk">LSE</span>',
        'EU': '<span class="badge badge-eu">XETRA</span>'
    }

    rows = ''
    for r in results:
        status = r.get('status', 'UNKNOWN')
        sc     = 'pass' if status == 'PASS' else 'break'
        ticker = r.get('ticker', '')
        detail = r.get('detail', '') or ''
        check  = r.get('check', '').replace('_', ' ')
        ex     = r.get('exchange', '')
        js_t   = ticker.replace("'", "\\'")

        rows += f"""
        <tr onclick="showStock('{js_t}')" title="Click to view {ticker}">
            <td style="color:#58a6ff;cursor:pointer">{ticker}</td>
            <td>{badges.get(ex, ex)}</td>
            <td>{check}</td>
            <td class="{sc}">{status}</td>
            <td class="detail">{detail}</td>
        </tr>"""

    return rows