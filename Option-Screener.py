import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import time

st.set_page_config(page_title="Options Scanner", layout="wide")
st.title("📊 Options Strategy Scanner")

# ========= 输入 =========
ticker_symbol = st.text_input("Ticker", "APLD")
cost = st.number_input("Cost Basis", value=27.0)

# ========= expiration =========
def get_expirations(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    return ticker.options

try:
    expirations = get_expirations(ticker_symbol)
except:
    st.error("❌ Failed to fetch expirations")
    st.stop()

# ===== 标记 weekly =====
def is_weekly(exp_str):
    date = datetime.strptime(exp_str, "%Y-%m-%d")
    first_day = date.replace(day=1)
    first_friday_offset = (4 - first_day.weekday()) % 7
    third_friday = first_day.day + first_friday_offset + 14
    return date.day != third_friday

exp_display = []
exp_map = {}

for e in expirations:
    label = f"{e} (W)" if is_weekly(e) else e
    exp_display.append(label)
    exp_map[label] = e

selected_label = st.selectbox("Expiration", exp_display)
exp = exp_map[selected_label]

run = st.button("Run Analysis")

# ========= Delta =========
def call_delta(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1)

def put_delta(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1) - 1

# ========= 高亮 =========
def highlight(row):
    styles = []
    for col in row.index:
        style = ""

        if row["sweet"] and row["liquid"]:
            style = "background-color: #d4edda"  # 绿

        elif row["annualized_return"] > 20:
            style = "background-color: #fff3cd"  # 黄

        elif not row["liquid"]:
            style = "background-color: #f8d7da"  # 红

        styles.append(style)
    return styles

# ========= 数字格式 =========
def format_df(df):
    df = df.copy()
    num_cols = df.select_dtypes(include=[np.number]).columns
    df[num_cols] = df[num_cols].round(2)
    return df

# ========= 主逻辑 =========
if run:

    with st.spinner("Fetching data..."):

        ticker = yf.Ticker(ticker_symbol)

        # retry option_chain
        opt = None
        for _ in range(3):
            try:
                opt = ticker.option_chain(exp)
                break
            except:
                time.sleep(1)

        if opt is None:
            st.error("❌ Failed to fetch option chain")
            st.stop()

        price = ticker.history(period="1d")["Close"].iloc[-1]

        expiration_date = datetime.strptime(exp, "%Y-%m-%d")
        T = (expiration_date - datetime.today()).days / 365
        r = 0.0365

        st.subheader("📈 Underlying")
        st.write(f"Price: {price:.2f}")
        st.write(f"DTE: {T*365:.0f} days")

        # ================= CALL =================
        calls = opt.calls.copy()

        calls["upside"] = calls["strike"] - price
        calls = calls[calls["upside"] > 0]
        calls = calls[calls["strike"] >= cost * 1.10]

        calls["mid"] = (calls["bid"] + calls["ask"]) / 2
        calls["spread"] = calls["ask"] - calls["bid"]
        calls["spread_pct"] = calls["spread"] / calls["mid"]

        calls["liquid"] = (
            (calls["volume"] > 10) &
            (calls["openInterest"] > 50) &
            (calls["spread_pct"] < 0.3)
        )

        calls["call_profit"] = (calls["strike"] - cost) + calls["mid"]
        calls["call_return_pct"] = (calls["call_profit"] / cost * 100)
        calls["call_annualized"] = (calls["call_return_pct"] / T)

        calls["ratio"] = (calls["mid"] / calls["upside"])

        calls["delta"] = calls.apply(
            lambda row: call_delta(price, row["strike"], T, r, row["impliedVolatility"]),
            axis=1
        )

        calls["sweet"] = calls["delta"].between(0.30, 0.40)

        calls["return_pct"] = (calls["mid"] / cost * 100)
        calls["annualized_return"] = (calls["return_pct"] / T)

        calls["IV"] = calls["impliedVolatility"] * 100

        calls = calls.sort_values("ratio", ascending=False).reset_index(drop=True)

        # ================= PUT =================
        puts = opt.puts.copy()

        puts["downside"] = price - puts["strike"]
        puts = puts[puts["downside"] > 0]

        puts["mid"] = (puts["bid"] + puts["ask"]) / 2
        puts["ratio"] = (puts["mid"] / puts["downside"])

        puts["return_pct"] = (puts["mid"] / puts["strike"] * 100)
        puts["annualized_return"] = (puts["return_pct"] / T)

        puts["delta"] = puts.apply(
            lambda row: put_delta(price, row["strike"], T, r, row["impliedVolatility"]),
            axis=1
        )

        puts["sweet"] = puts["delta"].abs().between(0.30, 0.40)

        puts["spread"] = puts["ask"] - puts["bid"]
        puts["spread_pct"] = puts["spread"] / puts["mid"]

        puts["liquid"] = (
            (puts["volume"] > 10) &
            (puts["openInterest"] > 50) &
            (puts["spread_pct"] < 0.3)
        )

        puts["IV"] = puts["impliedVolatility"] * 100

        puts = puts.sort_values("ratio", ascending=False).reset_index(drop=True)

    st.divider()

    st.markdown("""
    🟢 Best (sweet + liquid)  
    🟡 High Return (>20%)  
    🔴 Low Liquidity  
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🔵 Covered Call")
        calls_display = format_df(
            calls[[
                "strike","mid","upside","delta","volume","openInterest",
                "IV","ratio","return_pct","annualized_return",
                "call_return_pct","call_annualized","sweet","liquid"
            ]].head(10)
        )
        st.dataframe(
            calls_display.style.apply(highlight, axis=1),
            use_container_width=True
        )

    with col2:
        st.subheader("🟢 Cash Secured Put")
        puts_display = format_df(
            puts[[
                "strike","mid","downside","delta","volume","openInterest",
                "IV","ratio","return_pct","annualized_return","sweet","liquid"
            ]].head(10)
        )
        st.dataframe(
            puts_display.style.apply(highlight, axis=1),
            use_container_width=True
        )
