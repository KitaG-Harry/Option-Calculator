import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from scipy.stats import norm
from datetime import datetime
import time

st.set_page_config(page_title="Options Scanner", layout="centered")

st.title("📊 Options Strategy Scanner")

# ========= 输入 =========
ticker_symbol = st.text_input("Ticker", "APLD")
cost = st.number_input("Cost Basis", value=27.0)

# ========= 过滤 =========
only_sweet = st.toggle("Only show sweet (recommended execution zone)", value=False)

# ========= expiration =========
def get_expirations(ticker_symbol):
    ticker = yf.Ticker(ticker_symbol)
    return ticker.options

try:
    expirations = get_expirations(ticker_symbol)
except:
    st.error("❌ Failed to fetch expirations")
    st.stop()

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

# ========= HTML 表格 =========
def render_table(df, sweet_col="sweet"):
    html = "<table style='width:100%; border-collapse: collapse;'>"

    html += "<tr>"
    for col in df.columns:
        html += f"<th style='border:1px solid #ccc; padding:6px; text-align:center;'>{col}</th>"
    html += "</tr>"

    for _, row in df.iterrows():
        is_sweet = row.get(sweet_col, False)
        style = "font-weight:bold;" if is_sweet else ""

        html += f"<tr style='{style}'>"
        for val in row:
            html += f"<td style='border:1px solid #ccc; padding:6px; text-align:center;'>{val}</td>"
        html += "</tr>"

    html += "</table>"

    st.markdown(html, unsafe_allow_html=True)

# ========= 主逻辑 =========
if run:

    with st.spinner("Fetching data..."):

        ticker = yf.Ticker(ticker_symbol)

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
        calls["ratio"] = calls["mid"] / calls["upside"]

        # ✅ 不被行权收益（关键）
        calls["ret_no_assign"] = calls["mid"] / cost * 100
        calls["ann_no_assign"] = calls["ret_no_assign"] / T

        # ✅ 被行权收益（完整收益）
        calls["ret_called"] = ((calls["strike"] - cost) + calls["mid"]) / cost * 100
        calls["ann_called"] = calls["ret_called"] / T

        calls["delta"] = calls.apply(
            lambda row: call_delta(price, row["strike"], T, r, row["impliedVolatility"]),
            axis=1
        )

        calls["spread"] = calls["ask"] - calls["bid"]
        calls["spread_pct"] = calls["spread"] / calls["mid"]

        calls["liquid"] = (
            (calls["volume"] > 10) &
            (calls["openInterest"] > 50) &
            (calls["spread_pct"] < 0.3)
        )

        calls["sweet"] = calls["delta"].between(0.25, 0.35)

        calls["IV"] = calls["impliedVolatility"] * 100

        calls = calls.sort_values("ratio", ascending=False).reset_index(drop=True)

        if only_sweet:
            calls = calls[calls["sweet"]]

        st.divider()
        st.subheader("🔵 Covered Call")

        calls_display = calls[[
            "strike","mid","delta","IV",
            "ret_no_assign","ann_no_assign",
            "ret_called","ann_called",
            "ratio","sweet"
        ]].head(10).round(2)

        render_table(calls_display)

        # ================= PUT =================
        puts = opt.puts.copy()

        puts["downside"] = price - puts["strike"]
        puts = puts[puts["downside"] > 0]

        puts["mid"] = (puts["bid"] + puts["ask"]) / 2
        puts["ratio"] = puts["mid"] / puts["downside"]

        puts["return_pct"] = puts["mid"] / puts["strike"] * 100
        puts["annualized_return"] = puts["return_pct"] / T

        puts["delta"] = puts.apply(
            lambda row: put_delta(price, row["strike"], T, r, row["impliedVolatility"]),
            axis=1
        )

        puts["spread"] = puts["ask"] - puts["bid"]
        puts["spread_pct"] = puts["spread"] / puts["mid"]

        puts["liquid"] = (
            (puts["volume"] > 10) &
            (puts["openInterest"] > 50) &
            (puts["spread_pct"] < 0.3)
        )

        puts["sweet"] = puts["delta"].abs().between(0.20, 0.30)

        puts["IV"] = puts["impliedVolatility"] * 100

        puts = puts.sort_values("ratio", ascending=False).reset_index(drop=True)

        if only_sweet:
            puts = puts[puts["sweet"]]

        st.subheader("🟢 Cash Secured Put")

        puts_display = puts[[
            "strike","mid","delta","IV",
            "return_pct","annualized_return","ratio","sweet"
        ]].head(10).round(2)

        render_table(puts_display)
