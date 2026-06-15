# ============================================================
# config.py — centralised project configuration
#
# Every constant in the project lives here and nowhere else.
# To change any stock, edit the ticker lists below.
# The entire pipeline updates automatically everywhere.
#
# TICKER FORMAT:
#   NYSE / NASDAQ  — plain symbol:     AAPL, JPM, NVDA
#   LSE            — symbol + .L:      HSBA.L, BP.L
#   XETRA / DAX    — symbol + .DE:     SAP.DE, BMW.DE
# ============================================================

from pathlib import Path

# --- Project paths ---
ROOT_DIR    = Path(__file__).parent.parent
DATA_DIR    = ROOT_DIR / 'data'
OUTPUTS_DIR = ROOT_DIR / 'outputs'
CHARTS_DIR  = OUTPUTS_DIR / 'charts'
REPORTS_DIR = OUTPUTS_DIR / 'reports'
DB_PATH     = DATA_DIR / 'stock_dashboard.db'

# ============================================================
# TICKERS — EDIT THESE LISTS TO CHANGE YOUR STOCK UNIVERSE
# Only change here — everything else updates automatically.
# ============================================================

TICKERS_US = ["NVDA", "AAPL", "JPM", "XOM", "AMZN"]
TICKERS_UK = ["AZN.L", "LSEG.L", "BARC.L", "BP.L", "RIO.L"]
TICKERS_EU = ["SAP.DE", "SIE.DE", "ALV.DE", "BMW.DE", "BAS.DE"]

ALL_TICKERS = TICKERS_US + TICKERS_UK + TICKERS_EU

TICKER_EXCHANGE_MAP = (
    {t: "US" for t in TICKERS_US} |
    {t: "UK" for t in TICKERS_UK} |
    {t: "EU" for t in TICKERS_EU}
)

# Exchange display labels
EXCHANGE_LABELS = {
    "US": "NYSE / NASDAQ",
    "UK": "London Stock Exchange",
    "EU": "XETRA / DAX"
}

# --- Data date range ---
# Hard start date — only fetch data from 2023 onwards.
# This ensures the database never contains stale historical
# data from before this period and all charts show recent
# market behaviour relevant to current ops monitoring.
DATA_START_DATE = "2023-01-01"

# --- Market calendar ---
# 252 trading days per year — globally accepted convention.
# Used to annualise daily volatility and return figures.
TRADING_DAYS_PER_YEAR = 252

# --- Risk-free rate ---
# UK base rate 2025. Benchmark for Sharpe ratio calculation.
# Update when Bank of England rate changes.
RISK_FREE_RATE_ANNUAL = 0.045

# --- Rolling windows ---
VOLATILITY_WINDOW_DAYS = 30
MOVING_AVERAGE_SHORT   = 20
MOVING_AVERAGE_LONG    = 50

# --- Chart date range for OHLCV / MA charts ---
# 6 months of trading days for candlestick and MA charts.
# Shows recent trend without cluttering with old data.
CHART_LOOKBACK_DAYS = 180

# --- Reconciliation thresholds ---
RETURN_OUTLIER_THRESHOLD_PCT  = 5.0
VOLUME_ANOMALY_STD_DEVIATIONS = 3.0

# --- API configuration ---
RETRY_DELAYS_SECONDS = [2, 4, 8]

# Full lookback from DATA_START_DATE to today
# Calculated at runtime in data_fetcher.py
DEFAULT_LOOKBACK_DAYS = 730