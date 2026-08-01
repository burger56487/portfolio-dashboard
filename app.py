import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Personal Portfolio Tracker")
st.caption("Track holdings, risk-adjusted performance, and benchmark against the S&P 500 (SPY).")

# ---- Sidebar ----
st.sidebar.header("Your Portfolio")
default = pd.DataFrame({
    "Ticker": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
    "Shares": [10, 8, 5, 3, 4],
})
holdings = st.sidebar.data_editor(default, num_rows="dynamic", use_container_width=True)
start_date = st.sidebar.date_input("Start date", pd.to_datetime("2023-01-01"))

# ---- Data ----
@st.cache_data(ttl=3600)
def load_prices(tickers, start):
    data = yf.download(tickers + ["SPY"], start=start)["Close"]
    return data.dropna(how="all")

tickers = [t.strip().upper() for t in holdings["Ticker"].dropna().tolist() if str(t).strip()]
shares = dict(zip(tickers, holdings["Shares"].fillna(0).tolist()))

if not tickers:
    st.warning("Add at least one ticker in the sidebar.")
    st.stop()

try:
    prices = load_prices(tickers, start_date)
except Exception as e:
    st.error(f"Could not download data: {e}")
    st.stop()

# ---- robustness: drop tickers that failed to download ----
valid = [t for t in tickers if t in prices.columns and prices[t].notna().any()]
dropped = set(tickers) - set(valid)
if dropped:
    st.warning(f"Could not find data for: {', '.join(dropped)} (ignored).")
if not valid:
    st.error("No valid tickers with data.")
    st.stop()
tickers = valid
shares_vec = pd.Series({t: shares[t] for t in tickers})

# ---- Core calculations ----
port_prices = prices[tickers].ffill().dropna()
port_value = (port_prices * shares_vec).sum(axis=1)
port_ret = port_value.pct_change().dropna()

invested = port_value.iloc[0]
current = port_value.iloc[-1]
total_return = current / invested - 1

spy = prices["SPY"].reindex(port_value.index).ffill()
spy_value = invested * (spy / spy.iloc[0])
spy_ret = spy.pct_change().dropna()
spy_return = spy.iloc[-1] / spy.iloc[0] - 1

# today's move
today_move = port_ret.iloc[-1] if len(port_ret) else 0.0

# ---- Risk metrics ----
def sharpe(r):
    v = r.std() * np.sqrt(252)
    return (r.mean() * 252 / v) if v > 0 else 0.0

def max_drawdown(value):
    cum = value / value.cummax() - 1
    return cum.min()

ann_vol = port_ret.std() * np.sqrt(252)
port_sharpe = sharpe(port_ret)
port_mdd = max_drawdown(port_value)
# beta vs SPY
common = port_ret.index.intersection(spy_ret.index)
beta = np.cov(port_ret.loc[common], spy_ret.loc[common])[0, 1] / np.var(spy_ret.loc[common])

# ================= LAYOUT =================
# Row 1: headline returns
c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Value", f"${current:,.0f}")
c2.metric("Total Return", f"{total_return*100:,.1f}%")
c3.metric("Today", f"{today_move*100:+.2f}%")
c4.metric("vs SPY", f"{(total_return - spy_return)*100:+.1f} pp")

# Row 2: risk metrics
r1, r2, r3, r4 = st.columns(4)
r1.metric("Sharpe Ratio", f"{port_sharpe:.2f}")
r2.metric("Annual Volatility", f"{ann_vol*100:.1f}%")
r3.metric("Max Drawdown", f"{port_mdd*100:.1f}%")
r4.metric("Beta vs SPY", f"{beta:.2f}")

st.divider()

tab1, tab2, tab3 = st.tabs(["📊 Performance", "🥧 Allocation", "📋 Holdings"])

with tab1:
    st.subheader("Portfolio Value vs SPY (same starting capital)")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=port_value.index, y=port_value.values, name="Portfolio"))
    fig.add_trace(go.Scatter(x=spy_value.index, y=spy_value.values, name="SPY", line=dict(dash="dash")))
    fig.update_layout(height=420, yaxis_title="Value ($)", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Drawdown")
    dd = (port_value / port_value.cummax() - 1) * 100
    dfig = go.Figure()
    dfig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                              line=dict(color="#d9534f"), name="Drawdown"))
    dfig.update_layout(height=300, yaxis_title="Drawdown (%)", hovermode="x unified")
    st.plotly_chart(dfig, use_container_width=True)

with tab2:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Current Allocation")
        latest_value = port_prices.iloc[-1] * shares_vec
        pie = go.Figure(data=[go.Pie(labels=latest_value.index, values=latest_value.values, hole=0.4)])
        pie.update_layout(height=400)
        st.plotly_chart(pie, use_container_width=True)
    with col_b:
        st.subheader("Return by Holding")
        hold_ret = (port_prices.iloc[-1] / port_prices.iloc[0] - 1) * 100
        bar = go.Figure(data=[go.Bar(
            x=hold_ret.index, y=hold_ret.values,
            marker_color=["#5cb85c" if v >= 0 else "#d9534f" for v in hold_ret.values]
        )])
        bar.update_layout(height=400, yaxis_title="Return (%)")
        st.plotly_chart(bar, use_container_width=True)

with tab3:
    st.subheader("Holdings Detail")
    hold_ret = (port_prices.iloc[-1] / port_prices.iloc[0] - 1) * 100
    detail = pd.DataFrame({
        "Shares": shares_vec,
        "Start Price": port_prices.iloc[0].round(2),
        "Current Price": port_prices.iloc[-1].round(2),
        "Current Value": (port_prices.iloc[-1] * shares_vec).round(2),
        "Weight %": (latest_value / latest_value.sum() * 100).round(1) if 'latest_value' in dir() else 0,
        "Return %": hold_ret.round(1),
    })
    st.dataframe(detail, use_container_width=True)
