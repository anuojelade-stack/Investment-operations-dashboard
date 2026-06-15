# ============================================================
# analytics.py — financial metric calculations
#
# Nine standalone functions. Each takes data as input and
# returns a result. No side effects. No global state.
# Maximum 30 lines each. Fully testable in isolation.
#
# Operates on whatever tickers are in config.ALL_TICKERS.
# No changes needed here when the stock universe changes.
#
# All nine metrics are standard in investment operations:
# daily returns feed performance reports, volatility flags
# unusual movements for investigation, VWAP benchmarks
# trade execution quality, Sharpe measures whether returns
# genuinely justify the risk taken to achieve them.
# ============================================================

import numpy as np
import pandas as pd
from src.config import (
    TRADING_DAYS_PER_YEAR,
    RISK_FREE_RATE_ANNUAL,
    VOLATILITY_WINDOW_DAYS,
    MOVING_AVERAGE_SHORT,
    MOVING_AVERAGE_LONG
)


def calculate_daily_returns(prices: pd.Series) -> pd.Series:
    """
    Calculate day-on-day percentage price change for a price series.

    Daily return is the fundamental unit of performance measurement
    in investment management. Every downstream metric — cumulative
    return, volatility, Sharpe ratio — is derived from this value.

    Args:
        prices: Daily closing prices as pandas Series, date-indexed

    Returns:
        Daily returns as decimal Series. 0.01 represents a 1% gain.
        First row returns NaN — no prior day to compare against.
    """
    # pct_change() divides today's close by yesterday's close and
    # subtracts 1 — the standard formula for simple daily return
    # used universally in investment performance measurement.
    return prices.pct_change()


def calculate_cumulative_returns(daily_returns: pd.Series) -> pd.Series:
    """
    Calculate cumulative returns indexed to a base value of 100.

    Normalising to 100 on the start date is the standard
    institutional format for comparing assets trading at very
    different price levels or denominated in different currencies.
    An AAPL chart and an HSBA.L chart become directly comparable.

    Args:
        daily_returns: Daily returns as decimal Series from
                       calculate_daily_returns()

    Returns:
        Cumulative return Series indexed to 100 at start date.
        Value of 150 means a 50% gain from the start date.
    """
    # (1 + r).cumprod() compounds each daily return. Multiplying
    # by 100 sets the starting point to 100 — the institutional
    # convention for multi-asset performance comparison charts.
    return (1 + daily_returns).cumprod() * 100


def calculate_moving_averages(
    prices: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """
    Calculate 20-day and 50-day simple moving averages.

    The 20 and 50-day SMAs are the standard institutional trend
    indicators. When the 20-day crosses above the 50-day it signals
    a bullish trend shift — a pattern ops teams include in daily
    monitoring dashboards across all major asset classes.

    Args:
        prices: Daily closing prices as pandas Series

    Returns:
        Tuple of (sma_20, sma_50) as pandas Series.
        First 19 values of sma_20 and first 49 of sma_50 are NaN.
    """
    sma_short = prices.rolling(window=MOVING_AVERAGE_SHORT).mean()
    sma_long  = prices.rolling(window=MOVING_AVERAGE_LONG).mean()
    return sma_short, sma_long


def calculate_rolling_volatility(
    prices: pd.Series,
    window: int = VOLATILITY_WINDOW_DAYS
) -> pd.Series:
    """
    Calculate rolling annualised volatility for a price series.

    Monitored daily in investment operations to flag unusual price
    movements. A sudden spike may indicate a data feed error or
    an unprocessed corporate action — stock split, special dividend
    — requiring immediate attention before valuations are generated.

    Args:
        prices: Daily closing prices as pandas Series
        window: Rolling window in trading days. Default 30.

    Returns:
        Annualised volatility as percentage Series.
        First (window - 1) rows return NaN.
    """
    daily_returns = prices.pct_change()
    rolling_std   = daily_returns.rolling(window=window).std()

    # Annualise by multiplying by sqrt(252) — the globally accepted
    # number of equity trading days per year. Without annualisation,
    # daily volatility cannot be compared to annual benchmarks used
    # in investment operations performance reports.
    return rolling_std * (TRADING_DAYS_PER_YEAR ** 0.5) * 100


def calculate_sharpe_ratio(daily_returns: pd.Series) -> float:
    """
    Calculate annualised Sharpe ratio for a return series.

    The Sharpe ratio is the primary risk-adjusted performance metric
    in investment management. It measures whether the returns earned
    justify the risk taken to achieve them, benchmarked against the
    return available with zero risk (the UK base rate).

    Args:
        daily_returns: Daily returns as decimal Series

    Returns:
        Annualised Sharpe ratio as float.
        Higher is better. Above 1.0 is generally considered good.
        Negative means returns below the risk-free rate.
    """
    # Convert annual risk-free rate to daily equivalent for comparison
    # against daily return series before annualising the result.
    daily_risk_free_rate = RISK_FREE_RATE_ANNUAL / TRADING_DAYS_PER_YEAR
    excess_returns       = daily_returns - daily_risk_free_rate

    if excess_returns.std() == 0:
        return 0.0

    # Annualise by multiplying by sqrt(252) — same convention as
    # volatility annualisation, making Sharpe comparable across
    # different measurement periods in ops performance reports.
    return (excess_returns.mean() / excess_returns.std()) * (TRADING_DAYS_PER_YEAR ** 0.5)


def calculate_max_drawdown(prices: pd.Series) -> float:
    """
    Calculate maximum peak-to-trough drawdown for a price series.

    Max drawdown shows the worst loss an investor holding through
    the full period would have experienced. A standard risk metric
    included in every investment operations performance report and
    client portfolio summary across all asset classes.

    Args:
        prices: Daily closing prices as pandas Series

    Returns:
        Maximum drawdown as a negative percentage float.
        -0.35 means the worst peak-to-trough loss was 35%.
    """
    # Rolling maximum tracks the highest price seen up to each date.
    # Dividing current price by rolling max shows how far below the
    # peak the price has fallen — the definition of drawdown.
    rolling_peak    = prices.cummax()
    drawdown_series = (prices - rolling_peak) / rolling_peak
    return float(drawdown_series.min())


def calculate_correlation_matrix(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate cross-asset correlation matrix across all tickers.

    Correlation measures how assets move relative to each other.
    Used in portfolio construction and risk monitoring by ops teams.
    Particularly meaningful across US, UK, and EU assets — showing
    cross-market relationships and diversification effectiveness.

    Args:
        prices_df: DataFrame with one column per ticker,
                   containing daily closing prices, date-indexed

    Returns:
        Symmetric correlation matrix DataFrame. Values range from
        -1.0 (perfectly inverse) to +1.0 (perfectly correlated).
    """
    # Correlate daily returns rather than raw prices — returns are
    # stationary and comparable across assets in different currencies.
    daily_returns = prices_df.pct_change().dropna()
    return daily_returns.corr()


def calculate_vwap(
    prices: pd.Series,
    volume: pd.Series
) -> pd.Series:
    """
    Calculate Volume Weighted Average Price for a price series.

    VWAP is the standard execution quality benchmark used by trading
    desks and monitored by investment operations teams. If a trader
    was instructed to achieve VWAP, ops verifies the actual execution
    price against this benchmark. Significant deviation triggers a
    performance shortfall investigation.

    Args:
        prices: Daily closing prices as pandas Series
        volume: Daily volume as pandas Series, same index as prices

    Returns:
        Cumulative VWAP as pandas Series. Resets each trading day
        in production — here calculated as rolling cumulative VWAP
        across the full period for portfolio-level monitoring.
    """
    # Price-volume product divided by cumulative volume gives the
    # volume-weighted average — the true average price paid weighted
    # by how much actually traded at each level during the period.
    price_volume_product = prices * volume
    return price_volume_product.cumsum() / volume.cumsum()


def calculate_annualised_return(prices: pd.Series) -> float:
    """
    Calculate annualised total return using CAGR formula.

    Compound Annual Growth Rate expresses total return as an
    annual rate, enabling fair comparison between periods of
    different lengths. The standard format for return reporting
    in investment operations client summaries and fund factsheets.

    Args:
        prices: Daily closing prices as pandas Series, date-indexed

    Returns:
        Annualised return as a decimal. 0.12 represents 12% per year.
        Negative value means annualised loss over the period.
    """
    total_return  = (prices.iloc[-1] / prices.iloc[0]) - 1
    number_of_years = len(prices) / TRADING_DAYS_PER_YEAR

    # CAGR formula: (end/start)^(1/years) - 1
    # Raises the total return to the power of (1/years) to express
    # it as the equivalent constant annual rate over the period.
    return (1 + total_return) ** (1 / number_of_years) - 1
