# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Personal Portfolio Tracker")
st.caption("Track your holdings, returns, and compare against the S&P 500 (SPY).")

# ------------------------------------------------------------------
# Sidebar: user defines the portfolio
# ------------------------------------------------------------------
st.sidebar.header("Your Portfolio")

default = pd.DataFrame({
    "Ticker": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
    "Shares": [10, 8, 5, 3, 4],
})
st.sidebar.write("Edit your holdings below:")
holdings = st.sidebar.data_editor(default, num_rows="dynamic", use_container_width=True)

start_date = st.sidebar.date_input("Start date", pd.to_datetime("2023-01-01"))

# ------------------------------------------------------------------
# Data download (cached so it doesn't re-download every interaction)
# ------------------------------------------------------------------
@st.cache_data(ttl=3600)  # cache for 1 hour
def load_prices(tickers, start):
    data = yf.download(tickers + ["SPY"], start=start)["Close"]
    return data.dropna(how="all")

tickers = [t.strip().upper() for t in holdings["Ticker"].dropna().tolist() if t.strip()]
shares = dict(zip(tickers, holdings["Shares"].fillna(0).tolist()))

if not tickers:
    st.warning("Add at least one ticker in the sidebar.")
    st.stop()

try:
    prices = load_prices(tickers, start_date)
except Exception as e:
    st.error(f"Could not download data: {e}")
    st.stop()

# ------------------------------------------------------------------
# Portfolio value over time
# ------------------------------------------------------------------
port_prices = prices[tickers]
shares_vec = pd.Series(shares)
port_value = (port_prices * shares_vec).sum(axis=1)     # daily portfolio $ value
invested = port_value.iloc[0]
current = port_value.iloc[-1]
total_return = current / invested - 1

# benchmark: same $ invested in SPY at start
spy = prices["SPY"]
spy_value = invested * (spy / spy.iloc[0])
spy_return = spy.iloc[-1] / spy.iloc[0] - 1

# ------------------------------------------------------------------
# Top metrics
# ------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Value", f"${current:,.0f}")
c2.metric("Total Return", f"{total_return*100:,.1f}%")
c3.metric("SPY Return", f"{spy_return*100:,.1f}%")
c4.metric("vs SPY", f"{(total_return - spy_return)*100:+.1f} pp")

# ------------------------------------------------------------------
# Chart 1: Portfolio value vs SPY
# ------------------------------------------------------------------
st.subheader("Portfolio Value vs SPY (same starting capital)")
fig = go.Figure()
fig.add_trace(go.Scatter(x=port_value.index, y=port_value.values, name="Portfolio"))
fig.add_trace(go.Scatter(x=spy_value.index, y=spy_value.values, name="SPY", line=dict(dash="dash")))
fig.update_layout(height=450, yaxis_title="Value ($)", hovermode="x unified")
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------
# Chart 2: Current allocation (pie)
# ------------------------------------------------------------------
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Current Allocation")
    latest_value = port_prices.iloc[-1] * shares_vec
    pie = go.Figure(data=[go.Pie(labels=latest_value.index, values=latest_value.values, hole=0.4)])
    pie.update_layout(height=400)
    st.plotly_chart(pie, use_container_width=True)

# ------------------------------------------------------------------
# Chart 3: Per-holding return
# ------------------------------------------------------------------
with col_b:
    st.subheader("Return by Holding")
    hold_ret = (port_prices.iloc[-1] / port_prices.iloc[0] - 1) * 100
    bar = go.Figure(data=[go.Bar(
        x=hold_ret.index, y=hold_ret.values,
        marker_color=["#5cb85c" if v >= 0 else "#d9534f" for v in hold_ret.values]
    )])
    bar.update_layout(height=400, yaxis_title="Return (%)")
    st.plotly_chart(bar, use_container_width=True)

# ------------------------------------------------------------------
# Table: holding detail
# ------------------------------------------------------------------
st.subheader("Holdings Detail")
detail = pd.DataFrame({
    "Shares": shares_vec,
    "Start Price": port_prices.iloc[0].round(2),
    "Current Price": port_prices.iloc[-1].round(2),
    "Current Value": (port_prices.iloc[-1] * shares_vec).round(2),
    "Return %": hold_ret.round(1),
})
st.dataframe(detail, use_container_width=True)
