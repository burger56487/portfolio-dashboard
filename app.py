import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Portfolio Tracker")
st.caption("Transaction-based portfolio tracking with realised/unrealised P&L, dividends, and risk analytics.")

# ==================================================================
# Sidebar: transaction log
# ==================================================================
st.sidebar.header("Transactions")

if "txns" not in st.session_state:
    st.session_state.txns = pd.DataFrame({
        "Date":   ["2023-01-03", "2023-01-03", "2023-06-01"],
        "Ticker": ["AAPL", "MSFT", "NVDA"],
        "Action": ["BUY", "BUY", "BUY"],
        "Shares": [10.0, 8.0, 5.0],
        "Price":  [125.0, 240.0, 390.0],
    })

# --- Import CSV ---
st.sidebar.subheader("Import / Export")
up = st.sidebar.file_uploader("Upload transactions CSV", type="csv")
if up is not None:
    try:
        df = pd.read_csv(up)
        st.session_state.txns = df[["Date", "Ticker", "Action", "Shares", "Price"]]
        st.sidebar.success("Transactions imported!")
    except Exception as e:
        st.sidebar.error(f"Could not read CSV: {e}")

# --- Add a transaction ---
st.sidebar.subheader("Add a transaction")
t_date = st.sidebar.date_input("Date", pd.to_datetime("2024-01-02"))
t_ticker = st.sidebar.text_input("Ticker (e.g. TSLA)").strip().upper()
t_action = st.sidebar.selectbox("Action", ["BUY", "SELL"])
t_shares = st.sidebar.number_input("Shares", min_value=0.0, value=1.0, step=1.0)
t_price = st.sidebar.number_input("Price", min_value=0.0, value=100.0, step=1.0)

if st.sidebar.button("➕ Add transaction"):
    if not t_ticker:
        st.sidebar.error("Enter a ticker.")
    else:
        try:
            test = yf.Ticker(t_ticker).history(period="5d")
            if test.empty:
                st.sidebar.error(f"'{t_ticker}' not found.")
            else:
                new = pd.DataFrame({
                    "Date": [str(t_date)], "Ticker": [t_ticker], "Action": [t_action],
                    "Shares": [t_shares], "Price": [t_price],
                })
                st.session_state.txns = pd.concat([st.session_state.txns, new], ignore_index=True)
                st.sidebar.success(f"Added {t_action} {t_shares} {t_ticker}")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")

st.sidebar.write("Edit transactions:")
st.session_state.txns = st.sidebar.data_editor(
    st.session_state.txns, num_rows="dynamic", use_container_width=True
)
txns = st.session_state.txns.copy()

# --- Download button (persistence) ---
st.sidebar.download_button(
    "💾 Download transactions CSV",
    txns.to_csv(index=False).encode(),
    "transactions.csv", "text/csv",
)

# --- Settings ---
st.sidebar.subheader("Settings")
benchmark = st.sidebar.selectbox("Benchmark", ["SPY", "QQQ", "DIA", "IWM"], index=0)
rf_rate = st.sidebar.number_input("Risk-free rate (%/yr)", min_value=0.0, value=4.0, step=0.5) / 100

# ==================================================================
# Validate & clean transactions
# ==================================================================
if txns.empty or txns["Ticker"].dropna().empty:
    st.warning("Add at least one transaction in the sidebar.")
    st.stop()

txns = txns.dropna(subset=["Ticker", "Action", "Shares", "Price"])
txns["Ticker"] = txns["Ticker"].astype(str).str.upper()
txns["Date"] = pd.to_datetime(txns["Date"], errors="coerce")
txns = txns.dropna(subset=["Date"]).sort_values("Date")
tickers = sorted(txns["Ticker"].unique().tolist())
start_date = txns["Date"].min()

# ==================================================================
# Data (auto_adjust=True includes dividends -> total return)
# ==================================================================
@st.cache_data(ttl=3600)
def load_prices(tickers, bench, start):
    data = yf.download(tickers + [bench], start=start, auto_adjust=True)["Close"]
    return data.dropna(how="all")

try:
    prices = load_prices(tickers, benchmark, start_date)
except Exception as e:
    st.error(f"Could not download data: {e}")
    st.stop()

valid = [t for t in tickers if t in prices.columns and prices[t].notna().any()]
dropped = set(tickers) - set(valid)
if dropped:
    st.warning(f"No data for: {', '.join(dropped)} (ignored).")
tickers = valid
if not tickers:
    st.error("No valid tickers with data.")
    st.stop()

# ==================================================================
# Reconstruct holdings over time + realised P&L (average-cost method)
# ==================================================================
price_index = prices.index
shares_ot = pd.DataFrame(0.0, index=price_index, columns=tickers)
pos = {t: {"shares": 0.0, "avg_cost": 0.0} for t in tickers}
realized = 0.0

for _, row in txns.iterrows():
    t = row["Ticker"]
    if t not in tickers:
        continue
    d, act, sh, pr = row["Date"], row["Action"], float(row["Shares"]), float(row["Price"])
    sign = 1 if act == "BUY" else -1
    shares_ot.loc[shares_ot.index >= d, t] += sign * sh
    p = pos[t]
    if act == "BUY":
        tot = p["shares"] + sh
        if tot > 0:
            p["avg_cost"] = (p["shares"] * p["avg_cost"] + sh * pr) / tot
        p["shares"] = tot
    else:  # SELL
        realized += (pr - p["avg_cost"]) * min(sh, p["shares"])
        p["shares"] = max(p["shares"] - sh, 0.0)

shares_ot = shares_ot.clip(lower=0)
port_prices = prices[tickers].ffill()
port_value = (shares_ot * port_prices).sum(axis=1)
port_value = port_value[port_value > 0]          # start from first holding
if port_value.empty:
    st.warning("No active holdings over the period.")
    st.stop()
port_ret = port_value.pct_change().dropna()

# current holdings
cur_shares = pd.Series({t: pos[t]["shares"] for t in tickers})
cur_shares = cur_shares[cur_shares > 0]
cur_prices = port_prices.iloc[-1]
market_value = (cur_shares * cur_prices[cur_shares.index]).sum()
cost_basis = pd.Series({t: pos[t]["avg_cost"] * pos[t]["shares"] for t in cur_shares.index}).sum()
unrealized = market_value - cost_basis

# benchmark aligned to portfolio life
bench_px = prices[benchmark].reindex(port_value.index).ffill()
bench_ret = bench_px.pct_change().dropna()
bench_total = bench_px.iloc[-1] / bench_px.iloc[0] - 1
port_total = port_value.iloc[-1] / port_value.iloc[0] - 1
today_move = port_ret.iloc[-1] if len(port_ret) else 0.0

# ==================================================================
# Risk metrics (with risk-free rate)
# ==================================================================
def sharpe(r, rf):
    excess = r.mean() * 252 - rf
    v = r.std() * np.sqrt(252)
    return excess / v if v > 0 else 0.0

def sortino(r, rf):
    excess = r.mean() * 252 - rf
    downside = r[r < 0].std() * np.sqrt(252)
    return excess / downside if downside > 0 else 0.0

ann_vol = port_ret.std() * np.sqrt(252)
port_sharpe = sharpe(port_ret, rf_rate)
port_sortino = sortino(port_ret, rf_rate)
var95 = np.percentile(port_ret, 5) * 100 if len(port_ret) else 0.0   # daily 95% VaR
port_mdd = (port_value / port_value.cummax() - 1).min()
common = port_ret.index.intersection(bench_ret.index)
if len(common) > 2 and np.var(bench_ret.loc[common]) > 0:
    beta = np.cov(port_ret.loc[common], bench_ret.loc[common])[0, 1] / np.var(bench_ret.loc[common])
else:
    beta = float("nan")

# ==================================================================
# Layout
# ==================================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("Market Value", f"${market_value:,.0f}")
c2.metric("Unrealised P&L", f"${unrealized:,.0f}",
          f"{(unrealized/cost_basis*100) if cost_basis>0 else 0:+.1f}%")
c3.metric("Realised P&L", f"${realized:,.0f}")
c4.metric(f"vs {benchmark}", f"{(port_total - bench_total)*100:+.1f} pp")

r1, r2, r3, r4, r5 = st.columns(5)
r1.metric("Sharpe", f"{port_sharpe:.2f}")
r2.metric("Sortino", f"{port_sortino:.2f}")
r3.metric("Volatility", f"{ann_vol*100:.1f}%")
r4.metric("Max Drawdown", f"{port_mdd*100:.1f}%")
r5.metric("Daily VaR 95%", f"{var95:.2f}%")

st.divider()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["📊 Performance", "🥧 Allocation", "🔗 Risk", "📅 Annual", "📋 Holdings", "🧾 Transactions"]
)

latest_value = cur_shares * cur_prices[cur_shares.index]

with tab1:
    st.subheader(f"Portfolio Value vs {benchmark} (same starting capital)")
    bench_scaled = port_value.iloc[0] * (bench_px / bench_px.iloc[0])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=port_value.index, y=port_value.values, name="Portfolio"))
    fig.add_trace(go.Scatter(x=bench_scaled.index, y=bench_scaled.values, name=benchmark, line=dict(dash="dash")))
    fig.update_layout(height=400, yaxis_title="Value ($)", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Drawdown")
        dd = (port_value / port_value.cummax() - 1) * 100
        dfig = go.Figure()
        dfig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                                  line=dict(color="#d9534f"), name="Drawdown"))
        dfig.update_layout(height=320, yaxis_title="Drawdown (%)", hovermode="x unified")
        st.plotly_chart(dfig, use_container_width=True)
    with col2:
        st.subheader("Rolling 6-Month Sharpe")
        w = 126
        roll = (port_ret.rolling(w).mean()*252 - rf_rate) / (port_ret.rolling(w).std()*np.sqrt(252))
        roll = roll.dropna()
        rfig = go.Figure()
        rfig.add_trace(go.Scatter(x=roll.index, y=roll.values, name="Rolling Sharpe"))
        rfig.add_hline(y=0, line_color="gray")
        rfig.update_layout(height=320, yaxis_title="Sharpe", hovermode="x unified")
        st.plotly_chart(rfig, use_container_width=True)

with tab2:
    if len(cur_shares) == 0:
        st.info("No current holdings.")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Current Allocation")
            pie = go.Figure(data=[go.Pie(labels=latest_value.index, values=latest_value.values, hole=0.4)])
            pie.update_layout(height=400)
            st.plotly_chart(pie, use_container_width=True)
        with col_b:
            st.subheader("Unrealised Return by Holding")
            hr = pd.Series({t: (cur_prices[t]/pos[t]["avg_cost"]-1)*100
                            for t in cur_shares.index if pos[t]["avg_cost"] > 0})
            bar = go.Figure(data=[go.Bar(x=hr.index, y=hr.values,
                        marker_color=["#5cb85c" if v>=0 else "#d9534f" for v in hr.values])])
            bar.update_layout(height=400, yaxis_title="Return (%)")
            st.plotly_chart(bar, use_container_width=True)

with tab3:
    st.subheader("Correlation of Daily Returns")
    hold_returns = port_prices[cur_shares.index].pct_change().dropna() if len(cur_shares) else pd.DataFrame()
    if hold_returns.shape[1] >= 2:
        corr = hold_returns.corr()
        hm = go.Figure(data=go.Heatmap(z=corr.values, x=corr.columns, y=corr.index,
                    zmin=-1, zmax=1, colorscale="RdBu", reversescale=True,
                    text=corr.round(2).values, texttemplate="%{text}"))
        hm.update_layout(height=500)
        st.plotly_chart(hm, use_container_width=True)
        avg_corr = corr.values[np.triu_indices_from(corr.values, k=1)].mean()
        st.metric("Average Pairwise Correlation", f"{avg_corr:.2f}")
    else:
        st.info("Need at least two current holdings for a correlation matrix.")

with tab4:
    st.subheader(f"Annual Returns: Portfolio vs {benchmark}")
    def yearly(v):
        return pd.Series({yr: g.iloc[-1]/g.iloc[0]-1 for yr, g in v.groupby(v.index.year)})
    py = yearly(port_value)*100
    sy = yearly(bench_px)*100
    yrs = [str(y) for y in py.index]
    afig = go.Figure()
    afig.add_trace(go.Bar(x=yrs, y=py.values, name="Portfolio"))
    afig.add_trace(go.Bar(x=yrs, y=sy.reindex(py.index).values, name=benchmark))
    afig.update_layout(height=420, barmode="group", yaxis_title="Return (%)")
    st.plotly_chart(afig, use_container_width=True)
    st.dataframe(pd.DataFrame({"Portfolio %": py.round(1),
                               f"{benchmark} %": sy.reindex(py.index).round(1)}),
                 use_container_width=True)

with tab5:
    st.subheader("Current Holdings")
    if len(cur_shares) == 0:
        st.info("No current holdings.")
    else:
        detail = pd.DataFrame({
            "Shares": cur_shares,
            "Avg Cost": pd.Series({t: pos[t]["avg_cost"] for t in cur_shares.index}).round(2),
            "Current Price": cur_prices[cur_shares.index].round(2),
            "Market Value": latest_value.round(2),
            "Unrealised P&L": pd.Series({t: (cur_prices[t]-pos[t]["avg_cost"])*pos[t]["shares"]
                                         for t in cur_shares.index}).round(2),
            "Weight %": (latest_value/latest_value.sum()*100).round(1),
        })
        st.dataframe(detail, use_container_width=True)
    st.caption(f"Realised P&L to date: ${realized:,.2f}  |  Prices are dividend-adjusted (total return).")

with tab6:
    st.subheader("Transaction History")
    st.dataframe(txns.sort_values("Date"), use_container_width=True)
