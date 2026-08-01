# 📈 Portfolio Tracker

An interactive portfolio dashboard that tracks holdings in real time, computes
risk-adjusted performance, and benchmarks against the S&P 500.

**🔗 Live demo:** https://portfolio-dashboard-fpbkun68rflrzx98zu4szu.streamlit.app/

## Features
- Real-time price data via yfinance
- Editable holdings — adjust tickers and shares live
- Risk metrics: Sharpe ratio, annualised volatility, max drawdown, beta vs SPY
- Portfolio value vs SPY, drawdown chart, allocation and per-holding returns

## Tech Stack
Python · Streamlit · yfinance · Plotly · pandas

## Run Locally
```bash
pip install -r requirements.txt
streamlit run app.py
