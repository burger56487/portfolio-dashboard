import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Portfolio Tracker")
st.caption("Multi-market (US / HK / A-share) portfolio tracking with P&L, dividends, FX conversion, and risk analytics.")

# ==================================================================
# Built-in stock database (extend freely). Symbol / EN / CN / Market
# ==================================================================
STOCK_DB = pd.DataFrame([
    ("AAPL","Apple","苹果","US"), ("MSFT","Microsoft","微软","US"),
    ("NVDA","Nvidia","英伟达","US"), ("AMZN","Amazon","亚马逊","US"),
    ("GOOGL","Alphabet","谷歌","US"), ("META","Meta","脸书","US"),
    ("TSLA","Tesla","特斯拉","US"), ("NFLX","Netflix","奈飞","US"),
    ("JPM","JPMorgan","摩根大通","US"), ("V","Visa","维萨","US"),
    ("0700.HK","Tencent","腾讯","HK"), ("9988.HK","Alibaba","阿里巴巴","HK"),
    ("3690.HK","Meituan","美团","HK"), ("0941.HK","China Mobile","中国移动","HK"),
    ("1299.HK","AIA","友邦保险","HK"), ("0388.HK","HKEX","香港交易所","HK"),
    ("1810.HK","Xiaomi","小米","HK"), ("2318.HK","Ping An","中国平安","HK"),
    ("600519.SS","Kweichow Moutai","贵州茅台","CN"), ("601398.SS","ICBC","工商银行","CN"),
    ("600036.SS","China Merchants Bank","招商银行","CN"), ("601318.SS","Ping An","中国平安","CN"),
    ("000001.SZ","Ping An Bank","平安银行","CN"), ("000858.SZ","Wuliangye","五粮液","CN"),
    ("300750.SZ","CATL","宁德时代","CN"), ("002594.SZ","BYD","比亚迪","CN"),
], columns=["Symbol","Name_EN","Name_CN","Market"])
STOCK_DB["label"] = STOCK_DB["Name_CN"] + " " + STOCK_DB["Name_EN"] + " (" + STOCK_DB["Symbol"] + ")"

def currency_of(sym):
    if sym.endswith(".HK"): return "HKD"
    if sym.endswith(".SS") or sym.endswith(".SZ"): return "CNY"
    return "USD"

# ==================================================================
# Sidebar: transactions
# ==================================================================
st.sidebar.header("Transactions")

if "txns" not in st.session_state:
    st.session_state.txns = pd.DataFrame({
        "Date":   ["2023-01-03", "2023-01-03", "2023-06-01"],
        "Ticker": ["AAPL", "0700.HK", "600519.SS"],
        "Action": ["BUY", "BUY", "BUY"],
        "Shares": [10.0, 100.0, 10.0],
        "Price":  [125.0, 330.0, 1700.0],
    })

# Import / Export
st.sidebar.subheader("Import / Export")
up = st.sidebar.file_uploader("Upload transactions CSV", type="csv")
if up is not None:
    try:
        st.session_state.txns = pd.read_csv(up)[["Date","Ticker","Action","Shares","Price"]]
        st.sidebar.success("Imported!")
    except Exception as e:
        st.sidebar.error(f"Could not read CSV: {e}")

# Add a transaction (searchable)
st.sidebar.subheader("Add a transaction")
choice = st.sidebar.selectbox(
    "Search stock (type name / ticker, e.g. T, 腾讯, Tencent)",
    options=["— manual entry —"] + STOCK_DB["label"].tolist(),
)
if choice == "— manual entry —":
    t_ticker = st.sidebar.text_input("Enter any ticker (e.g. 0857.HK)").strip().upper()
else:
    t_ticker = STOCK_DB.loc[STOCK_DB["label"] == choice, "Symbol"].iloc[0]

t_date = st.sidebar.date_input("Date", pd.to_datetime("2024-01-02"))
t_action = st.sidebar.selectbox("Action", ["BUY", "SELL"])
t_shares = st.sidebar.number_input("Shares", min_value=0.0, value=1.0, step=1.0)
t_price = st.sidebar.number_input("Price (local currency)", min_value=0.0, value=100.0, step=1.0)

if st.sidebar.button("➕ Add transaction"):
    if not t_ticker:
        st.sidebar.error("Choose or enter a ticker.")
    else:
        try:
            if yf.Ticker(t_ticker).history(period="5d").empty:
                st.sidebar.error(f"'{t_ticker}' not found.")
            else:
                new = pd.DataFrame({"Date":[str(t_date)],"Ticker":[t_ticker],
                                    "Action":[t_action],"Shares":[t_shares],"Price":[t_price]})
                st.session_state.txns = pd.concat([st.session_state.txns, new], ignore_index=True)
                st.sidebar.success(f"Added {t_action} {t_shares} {t_ticker}")
        except Exception as e:
            st.sidebar.error(f"Error: {e}")

st.sidebar.write("Edit transactions:")
st.session_state.txns = st.sidebar.data_editor(
    st.session_state.txns, num_rows="dynamic", use_container_width=True)
txns = st.session_state.txns.copy()

st.sidebar.download_button("💾 Download transactions CSV",
    txns.to_csv(index=False).encode(), "transactions.csv", "text/csv")

st.sidebar.subheader("Settings")
benchmark = st.sidebar.selectbox("Benchmark", ["SPY", "QQQ", "^HSI", "000300.SS"], index=0)
rf_rate = st.sidebar.number_input("Risk-free rate (%/yr)", 0.0, value=4.0, step=0.5) / 100
st.sidebar.caption("All values converted to USD. Prices are dividend-adjusted.")

# ==================================================================
# Clean transactions
# ==================================================================
if txns.empty or txns["Ticker"].dropna().empty:
    st.warning("Add at least one transaction.")
    st.stop()
txns = txns.dropna(subset=["Ticker","Action","Shares","Price"])
txns["Ticker"] = txns["Ticker"].astype(str).str.upper()
txns["Date"] = pd.to_datetime(txns["Date"], errors="coerce")
txns = txns.dropna(subset=["Date"]).sort_values("Date")
tickers = sorted(txns["Ticker"].unique().tolist())
start_date = txns["Date"].min()

# ==================================================================
# Data + FX conversion to USD
# ==================================================================
@st.cache_data(ttl=3600)
def load_prices(tickers, bench, start):
    syms = tickers + [bench]
    data = yf.download(syms, start=start, auto_adjust=True)["Close"]
    if isinstance(data, pd.Series):
        data = data.to_frame()
    # FX rates -> USD
    fx = {}
    if any(s.endswith(".HK") for s in syms):
        h = yf.download("HKDUSD=X", start=start, auto_adjust=True)["Close"]
        fx["HKD"] = h.squeeze()
    if any(s.endswith(".SS") or s.endswith(".SZ") for s in syms):
        c = yf.download("CNYUSD=X", start=start, auto_adjust=True)["Close"]
        fx["CNY"] = c.squeeze()
    for col in data.columns:
        cur = currency_of(col)
        if cur in fx:
            data[col] = data[col] * fx[cur].reindex(data.index).ffill()
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
    st.error("No valid tickers.")
    st.stop()

# ==================================================================
# Reconstruct holdings + realised P&L (average cost, in USD)
# NOTE: transaction Price is local currency; convert to USD at trade date
# ==================================================================
price_index = prices.index
shares_ot = pd.DataFrame(0.0, index=price_index, columns=tickers)
pos = {t: {"shares":0.0, "avg_cost":0.0} for t in tickers}
realized = 0.0

@st.cache_data(ttl=3600)
def fx_series(cur, start):
    if cur == "USD": return None
    pair = "HKDUSD=X" if cur == "HKD" else "CNYUSD=X"
    return yf.download(pair, start=start, auto_adjust=True)["Close"].squeeze()

fx_cache = {c: fx_series(c, start_date) for c in ["HKD","CNY"]}

def to_usd(sd.Series({t: pos[t]["avg_cost"]*pos[t]["shares"] for t in cur_shares.index}).sum()
unrealized = market_value - cost_basis

bench_px = prices[benchmark].reindex(port_value.index).ffill()
bench_total = bench_px.iloc[-1]/bench_px.iloc[0] - 1
port_total = port_value.iloc[-1]/port_value.iloc[0] - 1
bench_ret = bench_px.pct_change().dropna()
today_move = port_ret.iloc[-1] if len(port_ret) else 0.0

# ==================================================================
# Risk metrics
# ==================================================================
def sharpe(r, rf):
    v = r.std()*np.sqrt(252)
    return (r.mean()*252 - rf)/v if v > 0 else 0.0
def sortino(r, rf):
    dn = r[r<0].std()*np.sqrt(252)
    return (r.mean()*252 - rf)/dn if dn > 0 else 0.0

ann_vol = port_ret.std()*np.sqrt(252)
port_sharpe = sharpe(port_ret, rf_rate)
port_sortino = sortino(port_ret, rf_rate)
var95 = np.percentile(port_ret, 5)*100 if len(port_ret) else 0.0
port_mdd = (port_value/port_value.cummax()-1).min()
common = port_ret.index.intersection(bench_ret.index)
beta = (np.cov(port_ret.loc[common], bench_ret.loc[common])[0,1]/np.var(bench_ret.loc[common])
        if len(common)>2 and np.var(bench_ret.loc[common])>0 else float("nan"))

# ==================================================================
# Layout
# ==================================================================
c1,c2,c3,c4 = st.columns(4)
c1.metric("Market Value (USD)", f"${market_value:,.0f}")
c2.metric("Unrealised P&L", f"${unrealized:,.0f}", f"{(unrealized/cost_basis*100) if cost_basis>0 else 0:+.1f}%")
c3.metric("Realised P&L", f"${realized:,.0f}")
c4.metric(f"vs {benchmark}", f"{(port_total-bench_total)*100:+.1f} pp")

r1,r2,r3,r4,r5 = st.columns(5)
r1.metric("Sharpe", f"{port_sharpe:.2f}")
r2.metric("Sortino", f"{port_sortino:.2f}")
r3.metric("Volatility", f"{ann_vol*100:.1f}%")
r4.metric("Max Drawdown", f"{port_mdd*100:.1f}%")
r5.metric("Daily VaR 95%", f"{var95:.2f}%")

st.divider()
tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs(
    ["📊 Performance","🥧 Allocation","🔗 Risk","📅 Annual","📋 Holdings","🧾 Transactions"])

with tab1:
    st.subheader(f"Portfolio Value vs {benchmark} (USD)")
    bs = port_value.iloc[0]*(bench_px/bench_px.iloc[0])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=port_value.index, y=port_value.values, name="Portfolio"))
    fig.add_trace(go.Scatter(x=bs.index, y=bs.values, name=benchmark, line=dict(dash="dash")))
    fig.update_layout(height=400, yaxis_title="Value ($)", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Drawdown")
        dd = (port_value/port_value.cummax()-1)*100
        dfig = go.Figure(); dfig.add_trace(go.Scatter(x=dd.index,y=dd.values,fill="tozeroy",line=dict(color="#d9534f")))
        dfig.update_layout(height=320, yaxis_title="Drawdown (%)"); st.plotly_chart(dfig, use_container_width=True)
    with col2:
        st.subheader("Rolling 6M Sharpe")
        w=126; roll=((port_ret.rolling(w).mean()*252 - rf_rate)/(port_ret.rolling(w).std()*np.sqrt(252))).dropna()
        rfig=go.Figure(); rfig.add_trace(go.Scatter(x=roll.index,y=roll.values)); rfig.add_hline(y=0,line_color="gray")
        rfig.update_layout(height=320, yaxis_title="Sharpe"); st.plotly_chart(rfig, use_container_width=True)

with tab2:
    if len(cur_shares)==0: st.info("No current holdings.")
    else:
        a,b = st.columns(2)
        with a:
            st.subheader("Allocation (USD)")
            pie=go.Figure(data=[go.Pie(labels=latest_value.index,values=latest_value.values,hole=0.4)])
            pie.update_layout(height=400); st.plotly_chart(pie, use_container_width=True)
        with b:
            st.subheader("Unrealised Return by Holding")
            hr=pd.Series({t:(cur_prices[t]/pos[t]["avg_cost"]-1)*100 for t in cur_shares.index if pos[t]["avg_cost"]>0})
            bar=go.Figure(data=[go.Bar(x=hr.index,y=hr.values,marker_color=["#5cb85c" if v>=0 else "#d9534f" for v in hr.values])])
            bar.update_layout(height=400, yaxis_title="Return (%)"); st.plotly_chart(bar, use_container_width=True)

with tab3:
    st.subheader("Correlation of Daily Returns")
    hrs = port_prices[cur_shares.index].pct_change().dropna() if len(cur_shares) else pd.DataFrame()
    if hrs.shape[1]>=2:
        corr=hrs.corr()
        hm=go.Figure(data=go.Heatmap(z=corr.values,x=corr.columns,y=corr.index,zmin=-1,zmax=1,
            colorscale="RdBu",reversescale=True,text=corr.round(2).values,texttemplate="%{text}"))
        hm.update_layout(height=500); st.plotly_chart(hm, use_container_width=True)
        st.metric("Avg Pairwise Correlation", f"{corr.values[np.triu_indices_from(corr.values,k=1)].mean():.2f}")
    else: st.info("Need ≥2 current holdings.")

with tab4:
    st.subheader(f"Annual Returns vs {benchmark}")
    def yearly(v): return pd.Series({yr:g.iloc[-1]/g.iloc[0]-1 for yr,g in v.groupby(v.index.year)})
    py=yearly(port_value)*100; sy=yearly(bench_px)*100
    yrs=[str(y) for y in py.index]
    af=go.Figure(); af.add_trace(go.Bar(x=yrs,y=py.values,name="Portfolio"))
    af.add_trace(go.Bar(x=yrs,y=sy.reindex(py.index).values,name=benchmark))
    af.update_layout(height=420,barmode="group",yaxis_title="Return (%)"); st.plotly_chart(af, use_container_width=True)
    st.dataframe(pd.DataFrame({"Portfolio %":py.round(1),f"{benchmark} %":sy.reindex(py.index).round(1)}), use_container_width=True)

with tab5:
    st.subheader("Current Holdings (USD)")
    if len(cur_shares)==0: st.info("No holdings.")
    else:
        st.dataframe(pd.DataFrame({
            "Shares": cur_shares,
            "Avg Cost": pd.Series({t:pos[t]["avg_cost"] for t in cur_shares.index}).round(2),
            "Current Price": cur_prices[cur_shares.index].round(2),
            "Market Value": latest_value.round(2),
            "Unrealised P&L": pd.Series({t:(cur_prices[t]-pos[t]["avg_cost"])*pos[t]["shares"] for t in cur_shares.index}).round(2),
            "Weight %": (latest_value/latest_value.sum()*100).round(1),
        }), use_container_width=True)
    st.caption(f"Realised P&L: ${realized:,.2f} | All in USD, dividend-adjusted.")

with tab6:
    st.subheader("Transaction History")
    st.dataframe(txns.sort_values("Date"), use_container_width=True)
