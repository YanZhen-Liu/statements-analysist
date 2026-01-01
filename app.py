import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import json
import os
from datetime import datetime

# --- 1. 初始化與檔案存取 ---
DB_FILE = "portfolio_db.json"
st.set_page_config(page_title="台股深度財務分析系統", layout="wide")

def save_data():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.watchlists, f, ensure_ascii=False, indent=4)

if 'watchlists' not in st.session_state:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            st.session_state.watchlists = json.load(f)
    else:
        st.session_state.watchlists = {}

# --- 2. MOPS 爬蟲解析器 (抓取台股深度財報) ---
@st.cache_data(ttl=3600)  # 快取一小時
def get_mops_detailed_data(stock_id, year, season):
    url = "https://mops.twse.com.tw/mops/web/t164sb04"
    payload = {
        'step': '1', 'firstin': '1', 'off': '1', 'TYPEK': 'all',
        'co_id': stock_id, 'year': str(year), 'season': str(season).zfill(2),
    }
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        response = requests.post(url, data=payload, headers=headers, timeout=10)
        dfs = pd.read_html(response.text)
        
        target_df = None
        for df in dfs:
            if '營業收入合計' in df.iloc[:, 0].values:
                target_df = df
                break
        
        if target_df is not None:
            data_map = dict(zip(target_df.iloc[:, 0], target_df.iloc[:, 1]))
            return {
                "營收": data_map.get("營業收入合計", 0),
                "成本": data_map.get("營業成本合計", 0),
                "費用": data_map.get("營業費用合計", 0),
                "業外": data_map.get("營業外收入及支出合計", 0),
                "稅": data_map.get("所得稅費用（利益）合計", 0),
                "淨利": data_map.get("本期淨利（損）", 0)
            }
    except:
        return None
    return None

# --- 3. 側邊欄與收藏功能 ---
with st.sidebar:
    st.header("📂 投資組合與設定")
    # 預設搜尋台積電
    target_input = st.text_input("🔍 搜尋台股代號", value="2330").upper()
    target_ticker = f"{target_input}.TW"
    
    st.divider()
    selected_cat = st.selectbox("我的資料夾", list(st.session_state.watchlists.keys()))
    
    with st.expander("📁 管理資料夾"):
        new_cat = st.text_input("新資料夾名稱")
        if st.button("建立"):
            if new_cat and new_cat not in st.session_state.watchlists:
                st.session_state.watchlists[new_cat] = {"tickers": {}}
                save_data(); st.rerun()

    if selected_cat:
        with st.form("add_stock"):
            t_add = st.text_input("加入代號至此資料夾").upper()
            if st.form_submit_button("確認加入"):
                st.session_state.watchlists[selected_cat]["tickers"][f"{t_add}.TW"] = {"cost": 0, "shares": 0}
                save_data(); st.rerun()

# --- 4. 主頁面佈局 (四分位區塊) ---
left_col, right_col = st.columns([1, 1])

# 抓取 YFinance 基本資訊
try:
    stock_obj = yf.Ticker(target_ticker)
    info = stock_obj.info
except:
    st.error("代號輸入錯誤或無法連結 Yahoo Finance")
    st.stop()

# --- A. 左側區塊 ---
with left_col:
    # [左上：行情圖]
    st.subheader(f"📈 {info.get('longName', target_ticker)} 走勢")
    c_type = st.radio("類型", ["折線圖", "K線圖"], horizontal=True)
    
    tabs = st.tabs(["1日", "5日", "1月", "3月", "半年", "1年"])
    periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y"]
    
    for i, tab in enumerate(tabs):
        with tab:
            hist = stock_obj.history(period=periods[i])
            fig_hist = go.Figure()
            if c_type == "折線圖":
                fig_hist.add_trace(go.Scatter(x=hist.index, y=hist['Close'], mode='lines', name='收盤'))
            else:
                fig_hist.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], 
                                                low=hist['Low'], close=hist['Close'],
                                                increasing_line_color='#FF3333', decreasing_line_color='#00AA00'))
            fig_hist.update_layout(height=350, xaxis_rangeslider_visible=False, template="plotly_white", margin=dict(t=0, b=0))
            st.plotly_chart(fig_hist, use_container_width=True)

    st.divider()

    # [左下：同業財務對比]
    st.subheader("📊 資料夾同業對比")
    if selected_cat:
        peers = list(st.session_state.watchlists[selected_cat]["tickers"].keys())
        if target_ticker not in peers: peers.append(target_ticker)
        
        comp_data = []
        for p in peers:
            p_inf = yf.Ticker(p).info
            comp_data.append({
                "代號": p,
                "ROE(%)": p_inf.get("returnOnEquity", 0) * 100,
                "毛利(%)": p_inf.get("grossMargins", 0) * 100,
                "殖利率(%)": p_inf.get("dividendYield", 0) * 100
            })
        df_comp = pd.DataFrame(comp_data)
        metric = st.selectbox("選擇指標", ["ROE(%)", "毛利(%)", "殖利率(%)"])
        fig_comp = px.bar(df_comp, x="代號", y=metric, color="代號", text_auto='.2f')
        st.plotly_chart(fig_comp, use_container_width=True)

# --- B. 右側區塊 ---
with right_col:
    # [右上：核心財報指標]
    st.subheader("📋 核心財報指標 (Yahoo)")
    m1, m2, m3 = st.columns(3)
    m1.metric("本益比 (P/E)", f"{info.get('trailingPE', 0):.2f}")
    m2.metric("淨值比 (P/B)", f"{info.get('priceToBook', 0):.2f}")
    m3.metric("負債比 (D/E)", f"{info.get('debtToEquity', 0):.2f}%")

    st.divider()

    # [右下：MOPS 損益瀑布圖]
    st.subheader("💹 台股深度損益結構 (觀測站數據)")
    
    # 讓使用者選擇最新一季財報
    col_y, col_s = st.columns(2)
    cur_year = datetime.now().year - 1912 # 預設去年/前年
    y_mops = col_y.number_input("年份 (民國)", value=112, step=1)
    s_mops = col_s.selectbox("季度", [1, 2, 3, 4], index=2)
    
    mops_data = get_mops_detailed_data(target_input, y_mops, s_mops)
    
    if mops_data:
        # 計算瀑布圖項：營收(+) -> 成本(-) -> 費用(-) -> 業外(+/-) -> 所得稅(-) -> 淨利(Total)
        labels = ["營業收入", "營業成本", "營業費用", "業外損益", "所得稅", "淨利"]
        y_val = [
            mops_data["營收"],
            -abs(mops_data["成本"]),
            -abs(mops_data["費用"]),
            mops_data["業外"],
            -abs(mops_data["稅"]),
            mops_data["淨利"]
        ]
        
        fig_wf = go.Figure(go.Waterfall(
            orientation = "v",
            measure = ["relative", "relative", "relative", "relative", "relative", "total"],
            x = labels,
            y = y_val,
            text = [f"{v/100000:.1f}億" for v in y_val],
            textposition = "outside",
            connector = {"line":{"color":"#555"}},
            increasing = {"marker":{"color":"#FF4B4B"}},
            decreasing = {"marker":{"color":"#00CC96"}},
            totals = {"marker":{"color":"#31333F"}}
        ))
        fig_wf.update_layout(height=480, template="plotly_white", margin=dict(t=20))
        st.plotly_chart(fig_wf, use_container_width=True)
    else:
        st.warning("無法從公開資訊觀測站獲取該季財報，請確認代號與年度是否正確。")