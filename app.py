import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from streamlit_searchbox import st_searchbox

st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📈 Portfolio Tracker")
st.caption("Multi-market portfolio tracking with TWR, fees/taxes, multi-account, dividends, FX conversion, and risk analytics.")

# ==================================================================
# LIVE MARKET HEADER
# ==================================================================
@st.cache_data(ttl=60)
def index_snapshot(symbol):
    for s in symbol.split("|"):
        try:
            d = yf.Ticker(s).history(period="5d")
            if not d.empty and len(d) >= 2:
                last = float(d["Close"].iloc[-1]); prev = float(d["Close"].iloc[-2])
                return last, (last / prev - 1) * 100
        except Exception:
            continue
    return None

@st.cache_data(ttl=60)
def intraday(symbol):
    for s in symbol.split("|"):
        d = yf.Ticker(s).history(period="1d", interval="1m")
        if d.empty:
            d = yf.Ticker(s).history(period="5d", interval="15m")
        if not d.empty:
            return d
    return pd.DataFrame()

INDICES = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Hang Seng": "^HSI", "CSI 300": "000300.SS|ASHR"}

st.subheader("🌐 Live Market")
mcols = st.columns(len(INDICES))
for (nm, sym), col in zip(INDICES.items(), mcols):
    snap = index_snapshot(sym)
    col.metric(nm, f"{snap[0]:,.0f}" if snap else "—", f"{snap[1]:+.2f}%" if snap else None)

idx_choice = st.selectbox("Intraday chart", list(INDICES.keys()), index=0)
intra = intraday(INDICES[idx_choice])
if not intra.empty:
    ifig = go.Figure()
    ifig.add_trace(go.Scatter(x=intra.index, y=intra["Close"], name=idx_choice, line=dict(color="#2E86DE")))
    ifig.update_layout(height=280, yaxis_title="Level", hovermode="x unified", margin=dict(t=10, b=10))
    st.plotly_chart(ifig, use_container_width=True)
st.caption("Data via Yahoo Finance (~15-min delayed). Weekends show the last session.")
st.divider()

# ==================================================================
# Stock database
# ==================================================================
@st.cache_data
def load_stock_db():
    try:
        db = pd.read_csv("stocks.csv")
    except Exception:
        db = pd.DataFrame([
            ("AAPL","Apple","苹果","US"), ("0700.HK","Tencent","腾讯","HK"),
            ("600519.SS","Kweichow Moutai","贵州茅台","CN"),
        ], columns=["Symbol","Name_EN","Name_CN","Market"])
    db["label"] = db["Name_CN"].astype(str) + " " + db["Name_EN"].astype(str) + " (" + db["Symbol"].astype(str) + ")"
    return db

STOCK_DB = load_stock_db()

def currency_of(sym):
    if sym in ("^HSI",):                            return "HKD"
    if sym.endswith(".HK"):                          return "HKD"
    if sym.endswith(".SS") or sym.endswith(".SZ"):   return "CNY"
    return "USD"

def market_of(s):
    if s.endswith(".HK"): return "Hong Kong"
    if s.endswith(".SS") or s.endswith(".SZ"): return "China A"
    return "US"

def search_stocks(query):
    if not query: return []
    qu = query.strip().upper(); qraw = query.strip(); results = []
    for _, row in STOCK_DB.iterrows():
        sym = str(row["Symbol"]).upper(); en = str(row["Name_EN"]).upper(); cn = str(row["Name_CN"])
        score = None
        if sym.startswith(qu):        score = 0
        elif en.startswith(qu):       score = 1
        elif qraw and qraw in cn:     score = 1
        elif qu in sym or qu in en:   score = 2
        if score is not None:
            results.append((score, str(row["label"]), str(row["Symbol"])))
    results.sort(key=lambda x: (x[0], x[1]))
    return [(lbl, sym) for _, lbl, sym in results]

@st.cache_data(ttl=600)
def price_on_date(ticker, date_str):
    try:
        d0 = pd.to_datetime(date_str)
        h = yf.Ticker(ticker).history(start=d0 - pd.Timedelta(days=7), end=d0 + pd.Timedelta(days=1))
        if h.empty:
            h = yf.Ticker(ticker).history(period="5d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_dividends(ticker, start):
    try:
        d = yf.Ticker(ticker).dividends
        if d.empty:
            return pd.Series(dtype=float)
        d.index = pd.to_datetime(d.index).tz_localize(None)
        return d[d.index >= pd.to_datetime(start)]
    except Exception:
        return pd.Series(dtype=float)

TXN_COLS = ["Date","Ticker","Action","Shares","Price","Fee","Tax","Account","Note"]

def normalize_txns(df):
    for c, default in [("Fee",0.0),("Tax",0.0),("Account","Default"),("Note","")]:
        if c not in df.columns:
            df[c] = default
    return df[TXN_COLS]

# ==================================================================
# Sidebar: transactions
# ==================================================================
st.sidebar.header("Transactions")

if "txns" not in st.session_state:
    st.session_state.txns = pd.DataFrame({
        "Date":   ["2022-01-03", "2022-01-03", "2023-06-01"],
        "Ticker": ["AAPL", "0700.HK", "600519.SS"],
        "Action": ["BUY", "BUY", "BUY"],
        "Shares": [10.0, 100.0, 10.0],
        "Price":  [180.0, 460.0, 1700.0],
        "Fee":    [1.0, 5.0, 3.0],
        "Tax":    [0.0, 0.0, 0.0],
        "Account":["Default","Default","Default"],
        "Note":   ["","",""],
    })
st.session_state.txns = normalize_txns(st.session_state.txns)

st.sidebar.subheader("Import / Export")
up = st.sidebar.file_uploader("Upload transactions CSV", type="csv")
if up is not None:
    try:
        st.session_state.txns = normalize_txns(pd.read_csv(up))
        st.sidebar.success("Imported!")
    except Exception as e:
        st.sidebar.error(f"Could not read CSV: {e}")

st.sidebar.subheader("Add a transaction")
with st.sidebar:
    picked = st_searchbox(search_stocks, placeholder="Type ticker or name (T, 腾讯, Tencent)…", key="stock_search")
manual = st.sidebar.text_input("…or enter any ticker manually").strip().upper()
t_ticker = manual if manual else (picked or "")

t_date = st.sidebar.date_input("Date", pd.to_datetime("2024-01-02"))
t_action = st.sidebar.selectbox("Action", ["BUY", "SELL"])
t_shares = st.sidebar.number_input("Shares", min_value=0.0, value=1.0, step=1.0)
auto_price = price_on_date(t_ticker, str(t_date)) if t_ticker else None
_default = float(auto_price) if auto_price else 100.0
t_price = st.sidebar.number_input("Price (local currency)", min_value=0.0, value=_default, step=1.0,
                                  key=f"price_{t_ticker}_{t_date}")
if auto_price:
    st.sidebar.caption(f"📈 Auto-filled: {auto_price:.2f} (editable)")
colf1, colf2 = st.sidebar.columns(2)
t_fee = colf1.number_input("Fee", min_value=0.0, value=0.0, step=1.0)
t_tax = colf2.number_input("Tax", min_value=0.0, value=0.0, step=1.0)
t_account = st.sidebar.text_input("Account", value="Default").strip() or "Default"
t_note = st.sidebar.text_input("Note", value="")

if st.sidebar.button("➕ Add transaction"):
    if not t_ticker:
        st.sidebar.error("Choose or enter a ticker.")
    elif t_shares <= 0 or t_price <= 0:
        st.sidebar.error("Shares and price must be positive.")
    else:
        in_db = t_ticker in STOCK_DB["Symbol"].values
        ok = True
        if not in_db:
            try: ok = not yf.Ticker(t_ticker).history(period="5d").empty
            except Exception: ok = False
        if not ok:
            st.sidebar.error(f"'{t_ticker}' not found.")
        else:
            new = pd.DataFrame([{"Date":str(t_date),"Ticker":t_ticker,"Action":t_action,
                                 "Shares":t_shares,"Price":t_price,"Fee":t_fee,"Tax":t_tax,
                                 "Account":t_account,"Note":t_note}])
            st.session_state.txns = pd.concat([st.session_state.txns, new], ignore_index=True)
            st.sidebar.success(f"Added {t_action} {t_shares} {t_ticker}")

st.sidebar.subheader("Manage transactions")
df_side = st.session_state.txns.reset_index(drop=True)
if not df_side.empty:
    options = [f"{i}: {r.get('Date','')}  {r.get('Action','')}  {r.get('Shares','')} {r.get('Ticker','')} @ {r.get('Price','')} [{r.get('Account','')}]"
               for i, r in df_side.iterrows()]
    to_delete = st.sidebar.multiselect("Select to delete", options)
    if st.sidebar.button("🗑️ Delete selected") and to_delete:
        idx = [int(o.split(":")[0]) for o in to_delete]
        st.session_state.txns = df_side.drop(index=idx).reset_index(drop=True)
        st.rerun()
else:
    st.sidebar.caption("No transactions yet.")

confirm_clear = st.sidebar.checkbox("Confirm clear all")
if st.sidebar.button("⚠️ Clear all") and confirm_clear:
    st.session_state.txns = st.session_state.txns.iloc[0:0]
    st.rerun()

with st.sidebar.expander("Advanced: edit raw table"):
    st.session_state.txns = normalize_txns(st.data_editor(
        st.session_state.txns, num_rows="dynamic", use_container_width=True, key="raw_editor"))

txns = st.session_state.txns.copy()
st.sidebar.download_button("💾 Download transactions CSV",
    txns.to_csv(index=False).encode(), "transactions.csv", "text/csv")

st.sidebar.subheader("Settings")
benchmark = st.sidebar.selectbox("Benchmark", ["SPY", "QQQ", "^HSI", "000300.SS"], index=0)
rf_rate = st.sidebar.number_input("Risk-free rate (%/yr)", 0.0, value=4.0, step=0.5) / 100
acct_list = sorted([a for a in txns.get("Account", pd.Series()).dropna().unique().tolist()])
sel_acct = st.sidebar.selectbox("Account view", ["All"] + acct_list)
st.sidebar.caption("Returns are time-weighted (TWR); all values in USD.")

# ==================================================================
# Clean & validate
# ==================================================================
if txns.empty or txns["Ticker"].dropna().empty:
    st.warning("Add at least one transaction."); st.stop()

txns["Ticker"] = txns["Ticker"].astype(str).str.upper().str.strip()
txns["Action"] = txns["Action"].astype(str).str.upper().str.strip()
txns["Date"] = pd.to_datetime(txns["Date"], errors="coerce")
for c in ["Shares","Price","Fee","Tax"]:
    txns[c] = pd.to_numeric(txns[c], errors="coerce")
txns["Fee"] = txns["Fee"].fillna(0.0); txns["Tax"] = txns["Tax"].fillna(0.0)
txns["Account"] = txns["Account"].fillna("Default")

bad = txns[~txns["Action"].isin(["BUY","SELL"]) | txns["Date"].isna()
           | (txns["Shares"] <= 0) | (txns["Price"] <= 0) | txns["Shares"].isna() | txns["Price"].isna()]
if not bad.empty:
    st.warning(f"{len(bad)} invalid row(s) ignored (need BUY/SELL, valid date, positive shares & price).")
txns = txns[txns["Action"].isin(["BUY","SELL"]) & txns["Date"].notna()
            & (txns["Shares"] > 0) & (txns["Price"] > 0)].sort_values("Date")

if sel_acct != "All":
    txns = txns[txns["Account"] == sel_acct]
if txns.empty:
    st.error("No valid transactions for this view."); st.stop()

tickers = sorted(txns["Ticker"].unique().tolist())
start_date = txns["Date"].min()

# ==================================================================
# FX + prices
# ==================================================================
@st.cache_data(ttl=1800)
def get_fx(start):
    fx = {"USD": None}
    for cur, pair in [("HKD","HKDUSD=X"), ("CNY","CNYUSD=X")]:
        try: fx[cur] = yf.download(pair, start=start, auto_adjust=True)["Close"].squeeze()
        except Exception: fx[cur] = None
    return fx

fx_cache = get_fx(start_date)
_fx_msg = [f"1 {c} = {float(fx_cache[c].iloc[-1]):.4f} USD" for c in ["HKD","CNY"]
           if fx_cache.get(c) is not None and hasattr(fx_cache[c],"empty") and not fx_cache[c].empty]
if _fx_msg:
    st.sidebar.success("💱 " + " | ".join(_fx_msg))
else:
    st.sidebar.warning("💱 FX unavailable")

@st.cache_data(ttl=1800)
def load_prices(tickers, bench, start, _fx):
    syms = tickers + [bench]
    data = yf.download(syms, start=start, auto_adjust=True)["Close"]
    if isinstance(data, pd.Series): data = data.to_frame()
    for col in data.columns:
        cur = currency_of(col)
        if _fx.get(cur) is not None:
            data[col] = data[col] * _fx[cur].reindex(data.index).ffill()
    return data.dropna(how="all")

try:
    prices = load_prices(tickers, benchmark, start_date, fx_cache)
except Exception as e:
    st.error(f"Could not download data: {e}"); st.stop()

valid = [t for t in tickers if t in prices.columns and prices[t].notna().any()]
dropped = set(tickers) - set(valid)
if dropped: st.warning(f"No data for: {', '.join(dropped)} (ignored).")
tickers = valid
if not tickers: st.error("No valid tickers."); st.stop()

price_index = prices.index
def to_usd(sym, amount, date):
    cur = currency_of(sym); s = fx_cache.get(cur)
    if s is None: return amount
    r = s.reindex(price_index).ffill()
    try:
        rate = r.asof(date); return amount * (rate if pd.notna(rate) else r.iloc[-1])
    except Exception:
        return amount

# ==================================================================
# Holdings, realised P&L (avg cost incl. fees/taxes), oversell warn
# ==================================================================
shares_ot = pd.DataFrame(0.0, index=price_index, columns=tickers)
pos = {t: {"shares":0.0, "avg_cost":0.0} for t in tickers}
realized = 0.0; total_fees = 0.0; oversell = []

for _, row in txns.iterrows():
    t = row["Ticker"]
    if t not in tickers: continue
    d, act, sh = row["Date"], row["Action"], float(row["Shares"])
    pr  = to_usd(t, float(row["Price"]), d)
    fee = to_usd(t, float(row["Fee"]), d) + to_usd(t, float(row["Tax"]), d)
    total_fees += fee
    p = pos[t]
    if act == "BUY":
        shares_ot.loc[shares_ot.index >= d, t] += sh
        cost = sh*pr + fee
        tot = p["shares"] + sh
        if tot > 0: p["avg_cost"] = (p["shares"]*p["avg_cost"] + cost) / tot
        p["shares"] = tot
    else:
        if sh > p["shares"] + 1e-9:
            oversell.append(f"{d.date()} SELL {sh:g} {t} > held {p['shares']:g}")
        sell = min(sh, p["shares"])
        shares_ot.loc[shares_ot.index >= d, t] -= sell
        proceeds = sell*pr - fee
        realized += proceeds - sell*p["avg_cost"]
        p["shares"] = max(p["shares"] - sell, 0.0)

if oversell:
    st.warning("Oversell (capped at held): " + "; ".join(oversell))

shares_ot = shares_ot.clip(lower=0)
port_prices = prices[tickers].ffill()
port_value = (shares_ot * port_prices).sum(axis=1)

# ---- Dividend income (auto-fetched) ----
div_income = {}
for t in tickers:
    divs = get_dividends(t, start_date)
    tot = 0.0
    for dt, dps in divs.items():
        try: sh_held = shares_ot[t].asof(dt)
        except Exception: sh_held = 0.0
        if pd.notna(sh_held) and sh_held > 0:
            tot += to_usd(t, float(dps) * float(sh_held), dt)
    if tot > 0:
        div_income[t] = tot
total_div = sum(div_income.values())

# ---- TWR ----
prev_shares = shares_ot.shift(1).fillna(0.0)
val_prev = (prev_shares * port_prices.shift(1)).sum(axis=1)
val_hold = (prev_shares * port_prices).sum(axis=1)
twr = (val_hold / val_prev - 1).replace([np.inf, -np.inf], np.nan)
port_ret = twr[val_prev > 0].dropna()
if port_ret.empty:
    st.warning("Not enough data to compute returns."); st.stop()
twr_curve = (1 + port_ret).cumprod(); twr_curve = twr_curve / twr_curve.iloc[0] * 100
port_total = twr_curve.iloc[-1]/100 - 1

cur_shares = pd.Series({t: pos[t]["shares"] for t in tickers}); cur_shares = cur_shares[cur_shares > 0]
cur_prices = port_prices.iloc[-1]
latest_value = cur_shares * cur_prices[cur_shares.index]
market_value = latest_value.sum()
cost_basis = pd.Series({t: pos[t]["avg_cost"]*pos[t]["shares"] for t in cur_shares.index}).sum()
unrealized = market_value - cost_basis

bench_px = prices[benchmark].reindex(port_ret.index).ffill()
bench_curve = bench_px / bench_px.iloc[0] * 100
bench_total = bench_curve.iloc[-1]/100 - 1
bench_ret = bench_px.pct_change().dropna()

# ---- Risk metrics ----
ann_vol = port_ret.std()*np.sqrt(252)
excess_ann = port_ret.mean()*252 - rf_rate
port_sharpe = excess_ann/ann_vol if ann_vol > 0 else 0.0
rf_daily = rf_rate/252
downside = port_ret[port_ret < rf_daily] - rf_daily
dd_dev = np.sqrt((downside**2).mean())*np.sqrt(252) if len(downside) else 0.0
port_sortino = excess_ann/dd_dev if dd_dev > 0 else 0.0
q = np.percentile(port_ret, 5) if len(port_ret) else 0.0
var95 = -q*100
cvar95 = -port_ret[port_ret <= q].mean()*100 if (port_ret <= q).any() else 0.0
port_mdd = (twr_curve/twr_curve.cummax()-1).min()
common = port_ret.index.intersection(bench_ret.index)
beta = (np.cov(port_ret.loc[common], bench_ret.loc[common])[0,1]/np.var(bench_ret.loc[common])
        if len(common) > 2 and np.var(bench_ret.loc[common]) > 0 else float("nan"))

# ==================================================================
# Summary
# ==================================================================
st.subheader(f"💼 My Portfolio  ·  {sel_acct}")
c1,c2,c3,c4 = st.columns(4)
c1.metric("Market Value (USD)", f"${market_value:,.0f}")
c2.metric("TWR Total Return", f"{port_total*100:+.1f}%")
c3.metric("Unrealised P&L", f"${unrealized:,.0f}", f"{(unrealized/cost_basis*100) if cost_basis>0 else 0:+.1f}%")
c4.metric("Realised P&L", f"${realized:,.0f}")

r1,r2,r3,r4,r5 = st.columns(5)
r1.metric("Sharpe", f"{port_sharpe:.2f}")
r2.metric("Sortino", f"{port_sortino:.2f}")
r3.metric("Volatility", f"{ann_vol*100:.1f}%")
r4.metric("Max Drawdown", f"{port_mdd*100:.1f}%")
r5.metric("Beta", f"{beta:.2f}")

r6,r7,r8,r9 = st.columns(4)
r6.metric("Daily VaR 95% (loss)", f"{var95:.2f}%")
r7.metric("Daily CVaR 95% (loss)", f"{cvar95:.2f}%")
r8.metric("Total Fees & Taxes", f"${total_fees:,.0f}")
r9.metric("Dividend Income", f"${total_div:,.0f}")

st.caption(f"Prices as of {price_index[-1].date()} | {len(port_ret)} obs | "
           f"Cost basis includes fees/taxes. Returns time-weighted (dividends & splits reflected). "
           f"Dividend income shown for transparency.")

st.divider()
tab1,tab2,tab3,tab4,tab5,tab6,tab7,tab8 = st.tabs(
    ["📊 Performance","🥧 Allocation","🔗 Risk","📅 Annual","📋 Holdings","🧾 Transactions","🌍 Exposure","💵 Dividends"])

with tab1:
    st.subheader(f"Growth of 100 — Portfolio (TWR) vs {benchmark}")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=twr_curve.index, y=twr_curve.values, name="Portfolio (TWR)"))
    fig.add_trace(go.Scatter(x=bench_curve.index, y=bench_curve.values, name=benchmark, line=dict(dash="dash")))
    fig.update_layout(height=400, yaxis_title="Index (start = 100)", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("Drawdown")
        dd = (twr_curve/twr_curve.cummax()-1)*100
        dfig=go.Figure(); dfig.add_trace(go.Scatter(x=dd.index,y=dd.values,fill="tozeroy",line=dict(color="#d9534f")))
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
    st.subheader(f"Annual Returns (TWR) vs {benchmark}")
    py = port_ret.groupby(port_ret.index.year).apply(lambda r: (1+r).prod()-1)*100
    sy = bench_ret.groupby(bench_ret.index.year).apply(lambda r: (1+r).prod()-1)*100
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
            "Avg Cost (incl. fees)": pd.Series({t:pos[t]["avg_cost"] for t in cur_shares.index}).round(2),
            "Current Price": cur_prices[cur_shares.index].round(2),
            "Market Value": latest_value.round(2),
            "Unrealised P&L": pd.Series({t:(cur_prices[t]-pos[t]["avg_cost"])*pos[t]["shares"] for t in cur_shares.index}).round(2),
            "Weight %": (latest_value/latest_value.sum()*100).round(1),
        }), use_container_width=True)
    st.caption(f"Realised P&L: ${realized:,.2f} | Fees & taxes: ${total_fees:,.2f} | Dividends: ${total_div:,.2f}")

with tab6:
    st.subheader("Transaction History")
    st.dataframe(txns.sort_values("Date"), use_container_width=True)

with tab7:
    st.subheader("Exposure & Concentration")
    if len(cur_shares) == 0:
        st.info("No current holdings.")
    else:
        w = latest_value / latest_value.sum()
        hhi = float((w**2).sum()); eff_n = 1/hhi if hhi > 0 else 0
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Holdings", f"{len(w)}")
        cc2.metric("Top Holding Weight", f"{w.max()*100:.1f}%")
        cc3.metric("Effective # (1/HHI)", f"{eff_n:.1f}")
        st.caption("Effective # = 1/HHI. Lower concentration = more diversified.")
        mkt = (w.groupby([market_of(t) for t in w.index]).sum()*100)
        cur = (w.groupby([currency_of(t) for t in w.index]).sum()*100)
        e1, e2 = st.columns(2)
        with e1:
            st.write("**By Market**")
            pm=go.Figure(data=[go.Pie(labels=mkt.index,values=mkt.values,hole=0.4)]); pm.update_layout(height=340,margin=dict(t=10,b=10)); st.plotly_chart(pm, use_container_width=True)
        with e2:
            st.write("**By Currency**")
            pc=go.Figure(data=[go.Pie(labels=cur.index,values=cur.values,hole=0.4)]); pc.update_layout(height=340,margin=dict(t=10,b=10)); st.plotly_chart(pc, use_container_width=True)

    st.subheader(f"Rolling Beta (126d) vs {benchmark}")
    aligned = pd.DataFrame({"p": port_ret, "b": bench_ret}).dropna()
    if len(aligned) > 130:
        rb = (aligned["p"].rolling(126).cov(aligned["b"]) / aligned["b"].rolling(126).var()).dropna()
        rbfig=go.Figure(); rbfig.add_trace(go.Scatter(x=rb.index,y=rb.values,name="Rolling Beta"))
        rbfig.add_hline(y=1, line_color="gray", line_dash="dash")
        rbfig.update_layout(height=300, yaxis_title="Beta"); st.plotly_chart(rbfig, use_container_width=True)
    else:
        st.info("Need more history for rolling beta.")

    st.subheader("Drawdown Duration")
    peak = twr_curve.cummax(); underwater = (twr_curve < peak).astype(int)
    runs = (underwater != underwater.shift()).cumsum()
    dd_lengths = underwater.groupby(runs).sum()
    longest = int(dd_lengths.max()) if len(dd_lengths) else 0
    current = int(underwater[::-1].cumprod().sum())
    dc1, dc2 = st.columns(2)
    dc1.metric("Longest Drawdown (days)", f"{longest}")
    dc2.metric("Current Drawdown (days)", f"{current}")

with tab8:
    st.subheader("Dividend Income (auto-fetched)")
    if div_income:
        ds = pd.Series(div_income).sort_values(ascending=False)
        st.metric("Total Dividend Income (USD)", f"${total_div:,.2f}")
        bar = go.Figure(data=[go.Bar(x=ds.index, y=ds.values, marker_color="#5cb85c")])
        bar.update_layout(height=380, yaxis_title="Dividend Income ($)")
        st.plotly_chart(bar, use_container_width=True)
        st.dataframe(ds.round(2).to_frame("Dividend Income (USD)"), use_container_width=True)
        st.caption("Estimated from shares held on each ex-dividend date, converted to USD. "
                   "Already reflected in total-return (TWR) performance; shown here for transparency.")
    else:
        st.info("No dividends found for current holdings over the period.")
