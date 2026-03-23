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

# ========= 数据 =========
@st.cache_data(ttl=300)
def get_option_chain(ticker_symbol, exp):
    ticker = yf.Ticker(ticker_symbol)
    for _ in range(3):
        try:
            return ticker.option_chain(exp)
        except:
            time.sleep(1)
    return None

ticker = yf.Ticker(ticker_symbol)

try:
    expirations = ticker.options
except:
    st.error("❌ Failed to fetch options")
    st.stop()

exp = st.selectbox("Expiration", expirations)

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

# ========= 高亮函数 =========
def highlight(row):
    styles = []

    for col in row.index:
        style = ""

        # 🟢 最优（甜点区 + 流动性）
        if row["sweet"] and row["liquid"]:
            style = "background-color: #d4edda"

        # 🔥 高收益
        if row["annualized_return"] > 20:
            style = "background-color: #fff3cd"

        # ⚠️ 风险（不liquid）
        if not row["liquid"]:
            style = "background-color: #f8d7da"

        styles.append(style)

    return styles

# ========= 主逻辑 =========
if run:

    with st.spinner("Fetching data..."):

        opt = get_option_chain(ticker_symbol, exp)

        if opt is None:
            st.error("❌ Failed to fetch option chain")
            st.stop()

        ticker = yf.Ticker(ticker_symbol)
        price = ticker.history(period="1d")["Close"].iloc[-1]

        expiration_date = datetime.strptime(exp, "%Y-%m-%d")
        T = (expiration_date - datetime.today()).days / 365
        r = 0.0365

        st.subheader("📈 Underlying")
        st.write(f"Price: {price:.2f}")
        st.write(f"DTE: {T*365:.0f} days")

        # =========================
        # 🔵 CALL
        # =========================
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
        calls["call_return_pct"] = (calls["call_profit"] / cost * 100).round(2)
        calls["call_annualized"] = (calls["call_return_pct"] / T).round(2)

        calls["ratio"] = (calls["mid"] / calls["upside"]).round(2)

        calls["delta"] = calls.apply(
            lambda row: call_delta(price, row["strike"], T, r, row["impliedVolatility"]),
            axis=1
        ).round(2)

        calls["sweet"] = calls["delta"].between(0.30, 0.40)

        calls["return_pct"] = (calls["mid"] / cost * 100).round(2)
        calls["annualized_return"] = (calls["return_pct"] / T).round(2)

        calls["IV"] = (calls["impliedVolatility"] * 100).round(1)

        calls = calls.sort_values("ratio", ascending=False).reset_index(drop=True)

        # =========================
        # 🟢 PUT
        # =========================
        puts = opt.puts.copy()

        puts["downside"] = price - puts["strike"]
        puts = puts[puts["downside"] > 0]

        puts["mid"] = (puts["bid"] + puts["ask"]) / 2

        puts["moneyness"] = puts["downside"] / price
        puts["ratio"] = (puts["mid"] / puts["downside"]).round(2)

        puts["return_pct"] = (puts["mid"] / puts["strike"] * 100).round(2)
        puts["annualized_return"] = (puts["return_pct"] / T).round(2)

        puts["delta"] = puts.apply(
            lambda row: put_delta(price, row["strike"], T, r, row["impliedVolatility"]),
            axis=1
        ).round(2)

        puts["sweet"] = puts["delta"].abs().between(0.30, 0.40)

        puts["spread"] = puts["ask"] - puts["bid"]
        puts["spread_pct"] = puts["spread"] / puts["mid"]

        puts["liquid"] = (
            (puts["volume"] > 10) &
            (puts["openInterest"] > 50) &
            (puts["spread_pct"] < 0.3)
        )

        puts["IV"] = (puts["impliedVolatility"] * 100).round(1)

        puts = puts.sort_values("ratio", ascending=False).reset_index(drop=True)

    # ========= UI =========
    st.divider()

    st.markdown("""
    🟢 Best (sweet + liquid)  
    🟡 High Return (>20%)  
    🔴 Low Liquidity  
    """)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🔵 Covered Call")
        st.dataframe(
            calls[[
                "strike","mid","upside","delta","volume","openInterest",
                "IV","ratio","return_pct","annualized_return",
                "call_return_pct","call_annualized","sweet","liquid"
            ]]
            .head(10)
            .style.apply(highlight, axis=1),
            use_container_width=True
        )

    with col2:
        st.subheader("🟢 Cash Secured Put")
        st.dataframe(
            puts[[
                "strike","mid","downside","delta","volume","openInterest",
                "IV","ratio","return_pct","annualized_return","sweet","liquid"
            ]]
            .head(10)
            .style.apply(highlight, axis=1),
            use_container_width=True
        )
