# ============================================================
# visualisation.py — professional chart generation
#
# Four chart functions plus one additional comparison chart:
#
#   plot_cumulative_returns    — normalised returns all tickers
#   plot_candlestick_with_volume — OHLCV single ticker
#   plot_rolling_volatility_30 — 30-day rolling volatility
#   plot_rolling_volatility_50 — 50-day rolling volatility
#   plot_correlation_heatmap   — cross-asset correlation
#
# matplotlib — industry standard professional charting.
# seaborn    — correlation heatmap only.
#
# All charts use consistent dark theme matching the HTML report.
# No hardcoded dates — always uses actual data dates.
# Each ticker has a unique distinct colour by exchange family.
# ============================================================

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import mplfinance as mpf
import seaborn as sns
import pandas as pd
import numpy as np
from src.config import (
    CHARTS_DIR, TICKERS_US, TICKERS_UK, TICKERS_EU,
    TRADING_DAYS_PER_YEAR
)

# ============================================================
# COLOUR PALETTE — unique colour per ticker
# US = blue family, UK = purple/pink, EU = green
# ============================================================

TICKER_COLOURS = {}
_us = ['#1f77b4', '#4fa8d4', '#0a4a7a', '#5bb8e8', '#2196f3']
_uk = ['#9c27b0', '#e91e8c', '#c678dd', '#7b2d8b', '#d2a8ff']
_eu = ['#2ea043', '#56d364', '#1a7431', '#3fb950', '#88d8a3']
for i, t in enumerate(TICKERS_US): TICKER_COLOURS[t] = _us[i % 5]
for i, t in enumerate(TICKERS_UK): TICKER_COLOURS[t] = _uk[i % 5]
for i, t in enumerate(TICKERS_EU): TICKER_COLOURS[t] = _eu[i % 5]


def plot_cumulative_returns(
    cumulative_returns: dict,
    exchange_map: dict,
    break_dates: list = None
) -> plt.Figure:
    """
    Plot normalised cumulative returns for all tickers.

    All assets indexed to 100 on the first available date.
    Each ticker has a unique colour. Exchange families grouped
    by colour so US/UK/EU assets are visually distinguishable.
    Date axis always reflects actual data — never hardcoded.

    Args:
        cumulative_returns: Dict mapping ticker to return Series
        exchange_map:       Dict mapping ticker to exchange code
        break_dates:        Reconciliation BREAK dates to mark

    Returns:
        matplotlib Figure ready for saving or embedding.
    """
    fig, ax = plt.subplots(figsize=(14, 7), facecolor='#0d1117')
    ax.set_facecolor('#0d1117')

    plotted_any = False

    for ticker, series in cumulative_returns.items():
        if series is None or series.dropna().empty:
            continue

        clean  = series.dropna()
        colour = TICKER_COLOURS.get(ticker, '#888888')

        ax.plot(
            clean.index, clean.values,
            label=ticker, color=colour,
            linewidth=1.8, alpha=0.9
        )
        plotted_any = True

    if not plotted_any:
        ax.text(0.5, 0.5, 'No data available',
                transform=ax.transAxes, ha='center', va='center',
                color='#6e7681', fontsize=14)

    # Base reference line at 100
    ax.axhline(y=100, color='#6e7681', linewidth=0.8,
               linestyle=':', alpha=0.6, label='Base (100)')

    # Mark reconciliation breaks as red verticals
    if break_dates:
        for i, d in enumerate(break_dates):
            ax.axvline(x=d, color='#f85149', alpha=0.4,
                       linewidth=1.0, linestyle='--',
                       label='Recon break' if i == 0 else None)

    _style_axes(ax,
                title='Normalised Cumulative Returns — US · UK · EU Equities',
                xlabel='Date',
                ylabel='Indexed Return (Base = 100)')

    ax.legend(loc='upper left', fontsize=8, ncol=3,
              framealpha=0.3, facecolor='#161b22',
              edgecolor='#21262d', labelcolor='#c9d1d9')

    plt.tight_layout(pad=1.5)
    return fig


def plot_candlestick_with_volume(
    ohlcv_data: pd.DataFrame,
    ticker: str,
    sma_short: pd.Series,
    sma_long: pd.Series,
    break_dates: list = None
) -> plt.Figure:
    """
    Plot OHLCV candlestick chart with volume and moving averages.

    Standard chart used by trading desks and ops teams for
    individual security analysis. Date axis always reflects
    actual data — never hardcoded.

    Args:
        ohlcv_data:  DataFrame with OHLCV columns, date index
        ticker:      Ticker symbol for chart title
        sma_short:   20-day SMA Series
        sma_long:    50-day SMA Series
        break_dates: Reconciliation BREAK dates to mark

    Returns:
        matplotlib Figure ready for saving or embedding.
    """
    if ohlcv_data is None or ohlcv_data.empty:
        fig, ax = plt.subplots(figsize=(14, 8), facecolor='#0d1117')
        ax.set_facecolor('#0d1117')
        ax.text(0.5, 0.5, f'No data for {ticker}',
                transform=ax.transAxes, ha='center', va='center',
                color='#6e7681', fontsize=14)
        return fig

    ohlcv_data = ohlcv_data.copy()
    ohlcv_data.index = pd.to_datetime(ohlcv_data.index)

    sma_short = sma_short.reindex(ohlcv_data.index)
    sma_long  = sma_long.reindex(ohlcv_data.index)

    additional_plots = []
    if not sma_short.dropna().empty:
        additional_plots.append(
            mpf.make_addplot(sma_short, panel=0, color='#ffa726',
                             width=1.5, label='SMA 20')
        )
    if not sma_long.dropna().empty:
        additional_plots.append(
            mpf.make_addplot(sma_long, panel=0, color='#42a5f5',
                             width=1.5, label='SMA 50')
        )

    # Bloomberg Terminal-inspired style — deep navy background,
    # teal-green up candles, red down candles, volume bars coloured
    # to match, razor-thin grid lines, clean axis typography.
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

    fig, axes = mpf.plot(ohlcv_data, **kwargs)

    # Remove the auto-generated mplfinance figure-level text
    # (e.g. "QSR · Open High Low Close with Volume" top-left)
    for txt in fig.texts:
        txt.set_visible(False)

    # Currency symbol on price y-axis — derived from ticker suffix.
    # LSE tickers trade in pence (p), XETRA in € and US in $.
    currency = 'p' if ticker.endswith('.L') else '€' if ticker.endswith('.DE') else '$'
    axes[0].yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f'{currency}{x:,.2f}')
    )
    axes[0].set_ylabel(f'Price ({currency})', color='#8899aa', fontsize=10, labelpad=6)

    # SMA legend — white text so labels are clearly readable on dark background
    legend = axes[0].get_legend()
    if legend:
        for text in legend.get_texts():
            text.set_color('#ffffff')

    # Format volume panel — replace 10^6 scientific notation with
    # clean M-suffix labels (e.g. 2.5M). Professional and readable.
    if len(axes) >= 3:
        vol_ax = axes[2]
    elif len(axes) >= 2:
        vol_ax = axes[1]
    else:
        vol_ax = None

    if vol_ax is not None:
        vol_ax.yaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f'{x / 1e6:.1f}M' if x >= 1e6 else f'{int(x):,}')
        )
        vol_ax.yaxis.offsetText.set_visible(False)
        vol_ax.set_facecolor('#0d1526')
        vol_ax.set_ylabel('Volume', color='#8b949e', fontsize=9, labelpad=6)

    if break_dates and axes:
        for d in break_dates:
            try:
                axes[0].axvline(x=pd.to_datetime(d), color='#f85149',
                                alpha=0.5, linewidth=1.2, linestyle='--')
            except Exception:
                pass

    return fig


def plot_rolling_volatility_30(
    volatility_series: dict,
    exchange_map: dict,
    outlier_dates: dict = None
) -> plt.Figure:
    """
    Plot 30-day rolling annualised volatility for all tickers.

    Short-term volatility window — standard for daily ops
    monitoring. Flags unusual movements requiring investigation.
    Displayed alongside the 50-day chart for comparison.

    Args:
        volatility_series: Dict mapping ticker to volatility Series
        exchange_map:      Dict mapping ticker to exchange
        outlier_dates:     Dict mapping ticker to BREAK dates

    Returns:
        matplotlib Figure ready for saving or embedding.
    """
    return _plot_volatility(
        volatility_series, exchange_map, outlier_dates,
        window_label='30-Day',
        title='30-Day Rolling Annualised Volatility — US · UK · EU Equities'
    )


def plot_rolling_volatility_50(
    prices_dict: dict,
    exchange_map: dict
) -> plt.Figure:
    """
    Plot 50-day rolling annualised volatility for all tickers.

    Longer-term volatility window — shows structural trend in
    volatility rather than short-term spikes. Displayed alongside
    the 30-day chart for side-by-side comparison in the dashboard.

    Args:
        prices_dict:  Dict mapping ticker to closing price Series
        exchange_map: Dict mapping ticker to exchange

    Returns:
        matplotlib Figure ready for saving or embedding.
    """
    # Calculate 50-day volatility from closing prices
    vol_50 = {}
    for ticker, prices in prices_dict.items():
        if prices is None or prices.dropna().empty:
            continue
        daily_returns = prices.pct_change()
        rolling_std   = daily_returns.rolling(window=50).std()

        # Annualise — same sqrt(252) convention as 30-day calculation
        vol_50[ticker] = rolling_std * (TRADING_DAYS_PER_YEAR ** 0.5) * 100

    return _plot_volatility(
        vol_50, exchange_map, None,
        window_label='50-Day',
        title='50-Day Rolling Annualised Volatility — US · UK · EU Equities'
    )


def _plot_volatility(
    volatility_series: dict,
    exchange_map: dict,
    outlier_dates: dict,
    window_label: str,
    title: str
) -> plt.Figure:
    """
    Shared volatility chart renderer used by both 30 and 50-day plots.

    Keeps both charts visually identical so they read as a
    clean pair when displayed side by side in the dashboard.

    Args:
        volatility_series: Dict mapping ticker to volatility Series
        exchange_map:      Dict mapping ticker to exchange
        outlier_dates:     Dict mapping ticker to BREAK dates (optional)
        window_label:      Label for the window e.g. '30-Day'
        title:             Full chart title string

    Returns:
        matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=(14, 6), facecolor='#0d1117')
    ax.set_facecolor('#0d1117')

    plotted_any = False

    for ticker, vol in volatility_series.items():
        if vol is None or vol.dropna().empty:
            continue

        clean  = vol.dropna()
        colour = TICKER_COLOURS.get(ticker, '#888888')

        ax.plot(
            clean.index, clean.values,
            label=ticker, color=colour,
            linewidth=1.5, alpha=0.85
        )
        plotted_any = True

        if outlier_dates and ticker in outlier_dates:
            for d in outlier_dates[ticker]:
                try:
                    dt = pd.to_datetime(d)
                    if dt in clean.index:
                        ax.scatter(dt, clean[dt], color='#f85149',
                                   s=50, zorder=5, marker='o')
                except Exception:
                    pass

    if not plotted_any:
        ax.text(0.5, 0.5, f'No {window_label} volatility data',
                transform=ax.transAxes, ha='center', va='center',
                color='#6e7681', fontsize=14)

    _style_axes(ax, title=title, xlabel='Date',
                ylabel=f'Annualised Volatility (%)')

    ax.legend(loc='upper right', fontsize=8, ncol=3,
              framealpha=0.3, facecolor='#161b22',
              edgecolor='#21262d', labelcolor='#c9d1d9')

    plt.tight_layout(pad=1.5)
    return fig


def plot_correlation_heatmap(correlation_matrix: pd.DataFrame) -> plt.Figure:
    """
    Plot cross-asset correlation heatmap across all tickers.

    COLOUR SCHEME:
    Uses 'magma_r' colourmap — dark purple for low/negative
    correlation, bright yellow/white for high positive. This
    reads cleanly against the dark #0d1117 background with no
    harsh white areas. Diagonal (self-correlation = 1.0) shows
    as bright, off-diagonal relationships as graduated colour.

    No axis gridlines — removed for clean dark theme appearance.

    Args:
        correlation_matrix: Square DataFrame from analytics module

    Returns:
        matplotlib Figure ready for saving or embedding.
    """
    if correlation_matrix is None or correlation_matrix.empty:
        fig, ax = plt.subplots(figsize=(7.5, 6), facecolor='#0d1117')
        ax.text(0.5, 0.5, 'No correlation data',
                transform=ax.transAxes, ha='center', va='center',
                color='#6e7681', fontsize=12)
        return fig

    fig, ax = plt.subplots(figsize=(16, 10), facecolor='#0d1117')
    ax.set_facecolor('#0d1117')

    sns.heatmap(
        correlation_matrix,
        annot=True,
        fmt='.2f',
        cmap='magma_r',
        vmin=-1,
        vmax=1,
        square=True,
        linewidths=0.4,
        linecolor='#0d1117',
        ax=ax,
        annot_kws={'size': 8, 'color': '#ffffff', 'weight': 'bold'},
        cbar_kws={'shrink': 0.6}
    )

    ax.set_title(
        'Cross-Asset Correlation Matrix — US · UK · EU Equities',
        fontsize=13, color='#f0f6fc', pad=14, fontweight='500'
    )

    # Enough padding on bottom so rotated x labels are never clipped
    ax.tick_params(colors='#8b949e', labelsize=9, length=0)
    plt.xticks(rotation=45, ha='right', color='#8b949e')
    plt.yticks(rotation=0, color='#8b949e')

    # Style the colourbar to match dark theme
    cbar = ax.collections[0].colorbar
    cbar.ax.tick_params(colors='#8b949e', labelsize=9, length=0)
    cbar.outline.set_edgecolor('#21262d')

    # Remove outer border
    for spine in ax.spines.values():
        spine.set_visible(False)

    plt.tight_layout(pad=2.0)
    return fig


def save_figure(fig: plt.Figure, filename: str) -> str:
    """
    Save a matplotlib Figure to outputs/charts/ at 300 DPI.

    Args:
        fig:      matplotlib Figure to save
        filename: Output filename e.g. 'cumulative_returns.png'

    Returns:
        Full path string where the file was saved.
    """
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CHARTS_DIR / filename

    fig.savefig(
        output_path,
        dpi=300,
        bbox_inches='tight',
        facecolor=fig.get_facecolor(),
        edgecolor='none'
    )
    plt.close(fig)
    return str(output_path)


def _style_axes(
    ax: plt.Axes,
    title: str,
    xlabel: str,
    ylabel: str
) -> None:
    """
    Apply consistent dark theme styling to a matplotlib Axes object.

    Called by every chart function to ensure visual consistency
    across all charts in the dashboard. One function to change
    if the theme ever needs updating.

    Args:
        ax:     matplotlib Axes to style
        title:  Chart title string
        xlabel: X-axis label
        ylabel: Y-axis label
    """
    ax.set_title(title, fontsize=14, color='#f0f6fc',
                 pad=16, fontweight='500')
    ax.set_xlabel(xlabel, fontsize=11, color='#8b949e', labelpad=8)
    ax.set_ylabel(ylabel, fontsize=11, color='#8b949e', labelpad=8)

    ax.tick_params(colors='#8b949e', labelsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=30, ha='right')

    for spine in ax.spines.values():
        spine.set_color('#21262d')

    ax.grid(True, alpha=0.12, color='#6e7681', linestyle='-')