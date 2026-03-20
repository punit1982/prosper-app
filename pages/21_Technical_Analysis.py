"""
Technical Analysis — Moving Averages, RSI, Bollinger Bands
==========================================================
Single-stock technical analysis with key indicators overlaid on price charts.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from core.database import get_all_holdings
from core.data_engine import get_history, get_ticker_info_batch

st.markdown(
    "<h2 style='margin-bottom:0'>📉 Technical Analysis</h2>"
    "<p style='color:#888;margin-top:0'>Moving averages, RSI, Bollinger Bands & volume analysis</p>",
    unsafe_allow_html=True,
)

# ── Ticker Selection ──
holdings = get_all_holdings()
portfolio_tickers = sorted(holdings["ticker"].unique().tolist()) if not holdings.empty else []

col_ticker, col_period = st.columns([2, 1])
with col_ticker:
    ticker = st.selectbox(
        "Select Ticker",
        portfolio_tickers if portfolio_tickers else ["AAPL"],
        help="Choose from portfolio holdings or type a ticker",
    )
with col_period:
    period = st.selectbox("Period", ["3mo", "6mo", "1y", "2y", "5y"], index=2)

if not ticker:
    st.stop()

# ── Fetch Historical Data ──
@st.cache_data(ttl=900, show_spinner=False)
def _load_history(ticker, period):
    return get_history(ticker, period=period)

with st.spinner(f"Loading {ticker} data…"):
    hist = _load_history(ticker, period)

if hist is None or hist.empty:
    st.warning(f"No historical data available for {ticker}. Try a US-listed ticker.")
    st.stop()

# Ensure correct column names
close_col = "Close" if "Close" in hist.columns else hist.columns[0]
high_col = "High" if "High" in hist.columns else close_col
low_col = "Low" if "Low" in hist.columns else close_col
open_col = "Open" if "Open" in hist.columns else close_col
volume_col = "Volume" if "Volume" in hist.columns else None

df = hist.copy()
df["close"] = pd.to_numeric(df[close_col], errors="coerce")
df["high"] = pd.to_numeric(df[high_col], errors="coerce")
df["low"] = pd.to_numeric(df[low_col], errors="coerce")
df["open"] = pd.to_numeric(df[open_col], errors="coerce")
if volume_col:
    df["volume"] = pd.to_numeric(df[volume_col], errors="coerce")
df = df.dropna(subset=["close"])

if df.empty:
    st.warning("Insufficient data for analysis.")
    st.stop()

# ── Calculate Indicators ──
# Moving Averages
df["SMA_20"] = df["close"].rolling(20).mean()
df["SMA_50"] = df["close"].rolling(50).mean()
df["SMA_200"] = df["close"].rolling(200).mean()
df["EMA_12"] = df["close"].ewm(span=12).mean()
df["EMA_26"] = df["close"].ewm(span=26).mean()

# RSI (14-period)
delta = df["close"].diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rs = gain / loss
df["RSI"] = 100 - (100 / (1 + rs))

# MACD
df["MACD"] = df["EMA_12"] - df["EMA_26"]
df["MACD_signal"] = df["MACD"].ewm(span=9).mean()
df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

# Bollinger Bands (20-period, 2 std)
df["BB_middle"] = df["close"].rolling(20).mean()
bb_std = df["close"].rolling(20).std()
df["BB_upper"] = df["BB_middle"] + 2 * bb_std
df["BB_lower"] = df["BB_middle"] - 2 * bb_std

# ATR (14-period)
tr = pd.concat([
    df["high"] - df["low"],
    (df["high"] - df["close"].shift()).abs(),
    (df["low"] - df["close"].shift()).abs(),
], axis=1).max(axis=1)
df["ATR"] = tr.rolling(14).mean()

# ── Signal Summary ──
latest = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else latest

signals = []
current_price = latest["close"]

# SMA signals
if pd.notna(latest["SMA_50"]):
    if current_price > latest["SMA_50"]:
        signals.append(("🟢", "Above 50-DMA", f"Price {current_price:.2f} > SMA50 {latest['SMA_50']:.2f}"))
    else:
        signals.append(("🔴", "Below 50-DMA", f"Price {current_price:.2f} < SMA50 {latest['SMA_50']:.2f}"))

if pd.notna(latest["SMA_200"]):
    if current_price > latest["SMA_200"]:
        signals.append(("🟢", "Above 200-DMA", f"Price {current_price:.2f} > SMA200 {latest['SMA_200']:.2f}"))
    else:
        signals.append(("🔴", "Below 200-DMA", f"Price {current_price:.2f} < SMA200 {latest['SMA_200']:.2f}"))

# Golden/Death cross
if pd.notna(latest["SMA_50"]) and pd.notna(latest["SMA_200"]):
    if latest["SMA_50"] > latest["SMA_200"] and pd.notna(prev["SMA_50"]) and prev["SMA_50"] <= prev["SMA_200"]:
        signals.append(("⭐", "GOLDEN CROSS", "50-DMA just crossed above 200-DMA — bullish"))
    elif latest["SMA_50"] < latest["SMA_200"] and pd.notna(prev["SMA_50"]) and prev["SMA_50"] >= prev["SMA_200"]:
        signals.append(("💀", "DEATH CROSS", "50-DMA just crossed below 200-DMA — bearish"))

# RSI signals
if pd.notna(latest["RSI"]):
    rsi = latest["RSI"]
    if rsi > 70:
        signals.append(("🔴", "Overbought", f"RSI = {rsi:.1f} (>70)"))
    elif rsi < 30:
        signals.append(("🟢", "Oversold", f"RSI = {rsi:.1f} (<30)"))
    else:
        signals.append(("⚪", "RSI Neutral", f"RSI = {rsi:.1f}"))

# Bollinger Band signals
if pd.notna(latest["BB_upper"]) and pd.notna(latest["BB_lower"]):
    if current_price > latest["BB_upper"]:
        signals.append(("🔴", "Above Upper BB", "Price above Bollinger Band — potential reversal"))
    elif current_price < latest["BB_lower"]:
        signals.append(("🟢", "Below Lower BB", "Price below Bollinger Band — potential bounce"))

# MACD signal
if pd.notna(latest["MACD"]) and pd.notna(latest["MACD_signal"]):
    if latest["MACD"] > latest["MACD_signal"] and prev["MACD"] <= prev["MACD_signal"]:
        signals.append(("🟢", "MACD Bullish Cross", "MACD crossed above signal line"))
    elif latest["MACD"] < latest["MACD_signal"] and prev["MACD"] >= prev["MACD_signal"]:
        signals.append(("🔴", "MACD Bearish Cross", "MACD crossed below signal line"))

# ── Signal Display ──
st.markdown(f"### {ticker} — Technical Signals")
sig_cols = st.columns(min(len(signals), 4)) if signals else []
for i, (icon, label, detail) in enumerate(signals[:4]):
    with sig_cols[i % 4]:
        st.markdown(f"{icon} **{label}**")
        st.caption(detail)

if len(signals) > 4:
    sig_cols2 = st.columns(min(len(signals) - 4, 4))
    for i, (icon, label, detail) in enumerate(signals[4:8]):
        with sig_cols2[i]:
            st.markdown(f"{icon} **{label}**")
            st.caption(detail)

st.divider()

# ── Indicator Toggles ──
with st.sidebar:
    st.subheader("📉 Indicators")
    show_sma = st.checkbox("Moving Averages (20/50/200)", value=True)
    show_bb = st.checkbox("Bollinger Bands", value=True)
    show_volume = st.checkbox("Volume", value=True)
    show_rsi = st.checkbox("RSI (14)", value=True)
    show_macd = st.checkbox("MACD", value=False)

# ── Build Chart ──
n_rows = 1 + (1 if show_volume else 0) + (1 if show_rsi else 0) + (1 if show_macd else 0)
row_heights = [0.5]
subplot_titles = [f"{ticker} Price"]
if show_volume:
    row_heights.append(0.15)
    subplot_titles.append("Volume")
if show_rsi:
    row_heights.append(0.15)
    subplot_titles.append("RSI (14)")
if show_macd:
    row_heights.append(0.20)
    subplot_titles.append("MACD")

fig = make_subplots(
    rows=n_rows, cols=1, shared_xaxes=True,
    row_heights=row_heights,
    subplot_titles=subplot_titles,
    vertical_spacing=0.03,
)

# Candlestick
fig.add_trace(go.Candlestick(
    x=df.index, open=df["open"], high=df["high"],
    low=df["low"], close=df["close"], name="OHLC",
    increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
), row=1, col=1)

# Moving Averages
if show_sma:
    for ma, color, dash in [("SMA_20", "#ffa726", "dot"), ("SMA_50", "#42a5f5", "solid"), ("SMA_200", "#ab47bc", "solid")]:
        if ma in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ma], name=ma,
                line=dict(color=color, width=1.5, dash=dash), opacity=0.8,
            ), row=1, col=1)

# Bollinger Bands
if show_bb:
    fig.add_trace(go.Scatter(
        x=df.index, y=df["BB_upper"], name="BB Upper",
        line=dict(color="rgba(150,150,150,0.5)", width=1, dash="dash"),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["BB_lower"], name="BB Lower",
        line=dict(color="rgba(150,150,150,0.5)", width=1, dash="dash"),
        fill="tonexty", fillcolor="rgba(150,150,150,0.05)",
    ), row=1, col=1)

current_row = 2

# Volume
if show_volume and "volume" in df.columns:
    colors = ["#26a69a" if c >= o else "#ef5350"
              for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df.index, y=df["volume"], name="Volume",
        marker_color=colors, opacity=0.5,
    ), row=current_row, col=1)
    current_row += 1

# RSI
if show_rsi:
    fig.add_trace(go.Scatter(
        x=df.index, y=df["RSI"], name="RSI",
        line=dict(color="#7c4dff", width=1.5),
    ), row=current_row, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=current_row, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=current_row, col=1)
    fig.add_hrect(y0=30, y1=70, fillcolor="rgba(100,100,100,0.05)", line_width=0, row=current_row, col=1)
    current_row += 1

# MACD
if show_macd:
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD"], name="MACD",
        line=dict(color="#2196f3", width=1.5),
    ), row=current_row, col=1)
    fig.add_trace(go.Scatter(
        x=df.index, y=df["MACD_signal"], name="Signal",
        line=dict(color="#ff9800", width=1.5),
    ), row=current_row, col=1)
    macd_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_hist"].fillna(0)]
    fig.add_trace(go.Bar(
        x=df.index, y=df["MACD_hist"], name="MACD Hist",
        marker_color=macd_colors, opacity=0.5,
    ), row=current_row, col=1)

fig.update_layout(
    height=200 + n_rows * 200,
    margin=dict(t=30, l=50, r=20, b=30),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    xaxis_rangeslider_visible=False,
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

st.plotly_chart(fig, use_container_width=True)

# ── Key Metrics Table ──
st.divider()
st.markdown("### 📊 Key Technical Metrics")
met_cols = st.columns(5)
with met_cols[0]:
    st.metric("Current Price", f"{current_price:.2f}")
with met_cols[1]:
    if pd.notna(latest.get("SMA_50")):
        dist = (current_price - latest["SMA_50"]) / latest["SMA_50"] * 100
        st.metric("vs 50-DMA", f"{dist:+.1f}%")
    else:
        st.metric("vs 50-DMA", "—")
with met_cols[2]:
    if pd.notna(latest.get("SMA_200")):
        dist = (current_price - latest["SMA_200"]) / latest["SMA_200"] * 100
        st.metric("vs 200-DMA", f"{dist:+.1f}%")
    else:
        st.metric("vs 200-DMA", "—")
with met_cols[3]:
    st.metric("RSI (14)", f"{latest['RSI']:.1f}" if pd.notna(latest.get("RSI")) else "—")
with met_cols[4]:
    if pd.notna(latest.get("ATR")):
        atr_pct = latest["ATR"] / current_price * 100
        st.metric("ATR (14)", f"{latest['ATR']:.2f} ({atr_pct:.1f}%)")
    else:
        st.metric("ATR (14)", "—")

# ── Actionable Trading Summary ──────────────────────────────────────────────
st.divider()
st.markdown("### 🎯 Action Plan")

# Count bullish vs bearish signals
bullish = sum(1 for icon, _, _ in signals if icon in ("🟢", "⭐"))
bearish = sum(1 for icon, _, _ in signals if icon in ("🔴", "💀"))
total_signals = bullish + bearish

if total_signals > 0:
    score = bullish / total_signals * 100  # 0=fully bearish, 100=fully bullish
else:
    score = 50

# Determine action
if score >= 70:
    action, action_color, action_icon = "BUY / ADD", "#4CAF50", "🟢"
    action_desc = "Technical indicators are predominantly bullish. Consider building a position."
elif score >= 55:
    action, action_color, action_icon = "LEAN BULLISH", "#8BC34A", "🟢"
    action_desc = "Slight bullish edge. Hold existing positions, small adds on dips."
elif score >= 45:
    action, action_color, action_icon = "HOLD / NEUTRAL", "#FF9800", "🟡"
    action_desc = "Mixed signals. Hold positions but avoid adding. Wait for clarity."
elif score >= 30:
    action, action_color, action_icon = "LEAN BEARISH", "#FF5722", "🟠"
    action_desc = "Slight bearish edge. Tighten stops, consider trimming."
else:
    action, action_color, action_icon = "SELL / REDUCE", "#f44336", "🔴"
    action_desc = "Technical indicators are predominantly bearish. Consider reducing exposure."

# Calculate key levels
support_levels = []
resistance_levels = []
if pd.notna(latest.get("SMA_50")):
    lvl = latest["SMA_50"]
    if lvl < current_price:
        support_levels.append(("50-DMA", lvl))
    else:
        resistance_levels.append(("50-DMA", lvl))
if pd.notna(latest.get("SMA_200")):
    lvl = latest["SMA_200"]
    if lvl < current_price:
        support_levels.append(("200-DMA", lvl))
    else:
        resistance_levels.append(("200-DMA", lvl))
if pd.notna(latest.get("BB_lower")):
    support_levels.append(("Lower BB", latest["BB_lower"]))
if pd.notna(latest.get("BB_upper")):
    resistance_levels.append(("Upper BB", latest["BB_upper"]))

# Recent swing high/low (last 20 days)
recent = df.tail(20)
swing_low = recent["low"].min()
swing_high = recent["high"].max()
support_levels.append(("20D Low", swing_low))
resistance_levels.append(("20D High", swing_high))

# Sort by proximity to current price
support_levels.sort(key=lambda x: current_price - x[1])
resistance_levels.sort(key=lambda x: x[1] - current_price)

# ATR-based stop loss
atr_val = latest["ATR"] if pd.notna(latest.get("ATR")) else 0
stop_loss = current_price - 2 * atr_val if atr_val > 0 else None
take_profit_1 = current_price + 1.5 * atr_val if atr_val > 0 else None
take_profit_2 = current_price + 3 * atr_val if atr_val > 0 else None

# Display action card
st.markdown(
    f"<div style='padding:16px 20px;border-radius:12px;border:2px solid {action_color};"
    f"background:rgba(255,255,255,0.03);margin-bottom:16px'>"
    f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:8px'>"
    f"<span style='font-size:1.8rem'>{action_icon}</span>"
    f"<span style='font-size:1.4rem;font-weight:700;color:{action_color}'>{action}</span>"
    f"<span style='font-size:0.9rem;color:#999;margin-left:auto'>"
    f"Signal Score: {score:.0f}/100 ({bullish}B / {bearish}S)</span></div>"
    f"<p style='margin:0;color:#ccc;font-size:0.95rem'>{action_desc}</p>"
    f"</div>",
    unsafe_allow_html=True,
)

# Key levels table
lev_c1, lev_c2, lev_c3 = st.columns(3)
with lev_c1:
    st.markdown("**Support Levels**")
    for name, lvl in support_levels[:3]:
        dist = (current_price - lvl) / current_price * 100
        st.markdown(f"- {name}: **{lvl:.2f}** ({dist:+.1f}% away)")

with lev_c2:
    st.markdown("**Resistance Levels**")
    for name, lvl in resistance_levels[:3]:
        dist = (lvl - current_price) / current_price * 100
        st.markdown(f"- {name}: **{lvl:.2f}** (+{dist:.1f}% away)")

with lev_c3:
    st.markdown("**Trade Levels (ATR-based)**")
    if stop_loss:
        st.markdown(f"- Stop Loss: **{stop_loss:.2f}** ({(stop_loss/current_price-1)*100:+.1f}%)")
        st.markdown(f"- Target 1 (1.5R): **{take_profit_1:.2f}** ({(take_profit_1/current_price-1)*100:+.1f}%)")
        st.markdown(f"- Target 2 (3R): **{take_profit_2:.2f}** ({(take_profit_2/current_price-1)*100:+.1f}%)")
    else:
        st.caption("Insufficient data for ATR-based levels.")

st.caption("*Technical signals are informational only. Always combine with fundamental analysis and risk management.*")
