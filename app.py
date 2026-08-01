import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Personal Portfolio Tracker")
st.caption("Track holdings, real P&L, risk-adjusted performance, and benchmark against the S&P 500 (SPY).")

# ==================================================================
# Sidebar
# ==================================================================
st.sidebar.header("Your Portfolio")

if "holdings" not in st.session_state:
    st.session_state.holdings = pd.DataFrame({
        "Ticker": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"],
        "Shares": [10, 8, 5, 3, 4],
        "CostPrice": [0.0, 0.0, 0.0, 0.0, 0.0],   # 0 = use start-date price
    })

# --- CSV upload ---
st.sidebar.subheader("Import holdings (CSV)")
st.sidebar.caption("CSV with columns: Ticker, Shares, CostPrice")
up = st.sidebar.file_uploader("Upload CSV", type="csv")
if up is not None:
    try:
        df = pd.read_csv(up)
        cols = {c.lower(): c for c in df.columns}
        df = df.rename(columns={cols.get("ticker","Ticker"):"Ticker",
                                cols.get("shares","Shares"):"Shares",
                                cols.get("costprice","CostPrice"):"CostPrice"})
        if "CostPrice" not in df.columns:
            df["CostPrice"] = 0.0
        st.session_state.holdings = df[["Ticker","Shares","CostPrice"]]
        st.sidebar.success("Holdings imported!")
    except Exception as e:
        st.sidebar.error(f"Could not read CSV: {e}")

# --- Add a stock (ticker code) with validation ---
st.sidebar.subheader("Add a stock")
new_ticker = st.sidebar.text_input("Ticker symbol (e.g. TSLA)").strip().upper()
new_shares = st.sidebar.number_input("Shares", min_value=0.0, value=1.0, step=1.0)
new_cost = st.sidebar.number_input("Cost price (0 = since start date)", min_value=0.0, value=0.0, step=1.0)

if st.sidebar.button("➕ Add to portfolio"):
    if not new_ticker:
        st.sidebar.error("Please enter a ticker symbol.")
    else:
        try:
            test = yf.Ticker(new_ticker).history(period="5d")
            if test.empty:
                st.sidebar.error(f"'{new_ticker}' not found. Check the symbol.")
            elif new_ticker in st.session_state.holdings["Ticker"].values:
                st.sidebar.warning(f"{new_ticker} is already in your portfolio.")
            else:
                st.session_state.holdings = pd.concat([
                    st.session_state.holdings,
                    pd.DataFrame({"Ticker":[new_ticker],"Shares":[new_shares],"CostPrice":[new_cost]})
                ], ignore_index=True)
                st.sidebar.success(f"Added {new_ticker}!")
        except Exception as e:
            st.sidebar.error(f"Error checking '{new_ticker}': {e}")

st.sidebar.write("Your holdings (editable):")
st.session_state.holdings = st.sidebar.data_editor(
    st.session_state.holdings, num_rows="dynamic", use_container_width=True
)
holdings = st.session_state.holdings

start_date = st.sidebar.date_input("Start date", pd.to_datetime("2023-01-01"))

# ==================================================================
# Data
# ==================================================================
@st.cache_data(ttl=3600)
def load_prices(tickers, start):
    data = yf.download(tickers + ["SPY"], start=start)["Close"]
    return data.dropna(how="all")

tickers = [str(t).strip().upper() for t in holdings["Ticker"].dropna().tolist() if str(t).strip()]
shares = dict(zip(tickers, holdings["Shares"].fillna(0).tolist()))
cost_prices = dict(zip(tickers, holdings["CostPrice"].fillna(0).tolist()))

if not tickers:
    st.warning("Add at least one ticker in the sidebar.")
    st.stop()

try:
    prices = load_prices(tickers, start_date)
except Exception as e:
    st.error(f"Could not download data: {e}")
    st.stop()

valid = [t for t in tickers if t in prices.columns and prices[t].notna().any()]
dropped = set(tickers) - set(valid)
if dropped:
    st.warning(f"Could not find data for: {', '.join(dropped)} (ignored).")
if not valid:
    st.error("No valid tickers with data.")
    st.stop()
tickers = valid
shares_vec = pd.Series({t: shares[t] for t in tickers})

# ==================================================================
# Core calculations
# ==================================================================
port_prices = prices[tickers].ffill().dropna()
port_value = (port_prices * shares_vec).sum(axis=1)
port_ret = port_value.pct_change().dropna()

invested = port_value.iloc[0]
current = port_value.iloc[-1]
total_return = current / invested - 1
today_move = port_ret.iloc[-1] if len(port_ret) else 0.0

spy = prices["SPY"].reindex(port_value.index).ffill()
spy_value = invested * (spy / spy.iloc[0])
spy_ret = spy.pct_change().dropna()
spy_return = spy.iloc[-1] / spy.iloc[0] - 1

# --- Cost basis / P&L (cost 0 -> use start-date price) ---
start_prices = port_prices.iloc[0]
eff_cost = pd.Series({t: (cost_prices[t] if cost_prices.get(t, 0) > 0 else start_prices[t]) for t in tickers})
cost_basis = (eff_cost * shares_vec).sum()
latest_value = port_prices.iloc[-1] * shares_vec
market_value = latest_value.sum()
pnl = market_value - cost_basis
pnl_pct = pnl / cost_basis if cost_basis > 0 else 0.0

# --- Risk metrics ---
def sharpe(r):
    v = r.std() * np.sqrt(252)
    return (r.mean() * 252 / v) if v > 0 else 0.0

ann_vol = port_ret.std() * np.sqrt(252)
port_sharpe = sharpe(port_ret)
port_mdd = (port_value / port_value.cummax() - 1).min()
common = port_ret.index.intersection(spy_ret.index)
if len(common) > 2 and np.var(spy_ret.loc[common]) > 0:
    beta = np.cov(port_ret.loc[common], spy_ret.loc[common])[0, 1] / np.var(spy_ret.loc[common])
else:
    beta = float("nan")

# ==================================================================
# Layout: metrics
# ==================================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("Market Value", f"${market_value:,.0f}")
c2.metric("Unrealized P&L", f"${pnl:,.0f}", f"{pnl_pct*100:+.1f}%")
c3.metric("Today", f"{today_move*100:+.2f}%")
c4.metric("vs SPY (since start)", f"{(total_return - spy_return)*100:+.1f} pp")

r1, r2, r3, r4 = st.columns(4)
r1.metric("Sharpe Ratio", f"{port_sharpe:.2f}")
r2.metric("Annual Volatility", f"{ann_vol*100:.1f}%")
r3.metric("Max Drawdown", f"{port_mdd*100:.1f}%")
r4.metric("Beta vs SPY", f"{beta:.2f}")

st.divider()

hold_ret = (port_prices.iloc[-1] / port_prices.iloc[0] - 1) * 100

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 Performance", "🥧 Allocation", "🔗 Risk", "📅 Annual", "📋 Holdings"]
)

# ---- Tab 1: Performance (value, drawdown, rolling Sharpe) ----
with tab1:
    st.subheader("Portfolio Value vs SPY (same starting capital)")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=port_value.index, y=port_value.values, name="Portfolio"))
    fig.add_trace(go.Scatter(x=spy_value.index, y=spy_value.values, name="SPY", line=dict(dash="dash")))
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
        window = 126
        roll = (port_ret.rolling(window).mean() * 252) / (port_ret.rolling(window).std() * np.sqrt(252))
        roll = roll.dropna()
        rfig = go.Figure()
        rfig.add_trace(go.Scatter(x=roll.index, y=roll.values, name="Rolling Sharpe"))
        rfig.add_hline(y=0, line_color="gray")
        rfig.update_layout(height=320, yaxis_title="Sharpe (annualised)", hovermode="x unified")
        st.plotly_chart(rfig, use_container_width=True)

# ---- Tab 2: Allocation ----
with tab2:
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Current Allocation")
        pie = go.Figure(data=[go.Pie(labels=latest_value.index, values=latest_value.values, hole=0.4)])
        pie.update_layout(height=400)
        st.plotly_chart(pie, use_container_width=True)
    with col_b:
        st.subheader("Return by Holding (since start)")
        bar = go.Figure(data=[go.Bar(
            x=hold_ret.index, y=hold_ret.values,
            marker_color=["#5cb85c" if v >= 0 else "#d9534f" for v in hold_ret.values]
        )])
        bar.update_layout(height=400, yaxis_title="Return (%)")
        st.plotly_chart(bar, use_container_width=True)

# ---- Tab 3: Risk (correlation heatmap) ----
with tab3:
    st.subheader("Correlation of Daily Returns")
    st.caption("Lower correlations mean better diversification.")
    hold_returns = port_prices.pct_change().dropna()
    if hold_returns.shape[1] >= 2:
        corr = hold_returns.corr()
        hm = go.Figure(data=go.Heatmap(
            z=corr.values, x=corr.columns, y=corr.index,
            zmin=-1, zmax=1, colorscale="RdBu", reversescale=True,
            text=corr.round(2).values, texttemplate="%{text}"
        ))
        hm.update_layout(height=500)
        st.plotly_chart(hm, use_container_width=True)
        avg_corr = corr.values[np.triu_indices_from(corr.values, k=1)].mean()
        st.metric("Average Pairwise Correlation", f"{avg_corr:.2f}")
    else:
        st.info("Add at least two stocks to see the correlation matrix.")

# ---- Tab 4: Annual returns ----
with tab4:
    st.subheader("Annual Returns: Portfolio vs SPY")
    def yearly_returns(value):
        out = {}
        for yr, grp in value.groupby(value.index.year):
            out[yr] = grp.iloc[-1] / grp.iloc[0] - 1
        return pd.Series(out)
    py = yearly_returns(port_value) * 100
    sy = yearly_returns(spy) * 100
    years = [str(y) for y in py.index]
    afig = go.Figure()
    afig.add_trace(go.Bar(x=years, y=py.values, name="Portfolio"))
    afig.add_trace(go.Bar(x=years, y=sy.values, name="SPY"))
    afig.update_layout(height=420, barmode="group", yaxis_title="Return (%)")
    st.plotly_chart(afig, use_container_width=True)
    ann_table = pd.DataFrame({"Portfolio %": py.round(1), "SPY %": sy.round(1)})
    st.dataframe(ann_table, use_container_width=True)

# ---- Tab 5: Holdings detail (with P&L) ----
with tab5:
    st.subheader("Holdings Detail")
    detail = pd.DataFrame({
        "Shares": shares_vec,
        "Cost Price": eff_cost.round(2),
        "Current Price": port_prices.iloc[-1].round(2),
        "Cost Basis": (eff_cost * shares_vec).round(2),
        "Market Value": latest_value.round(2),
        "P&L $": (latest_value - eff_cost * shares_vec).round(2),
        "P&L %": ((port_prices.iloc[-1] / eff_cost - 1) * 100).round(1),
        "Weight %": (latest_value / latest_value.sum() * 100).round(1),
    })
    st.dataframe(detail, use_container_width=True)
    st.caption("Cost Price of 0 falls back to the start-date price. Enter your real purchase price for accurate P&L.")
