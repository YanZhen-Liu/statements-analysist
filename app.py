import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import json
import os

# --- 1. 系統初始化 ---
st.set_page_config(page_title="台股專業全方位分析系統", layout="wide")
api = DataLoader()
DB_FILE = "portfolio_db.json"

if 'watchlists' not in st.session_state:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            st.session_state.watchlists = json.load(f)
    else:
        st.session_state.watchlists = {"權值股": ["2330", "2317", "2454"]}

if 'active_folder' not in st.session_state:
    st.session_state.active_folder = None

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.watchlists, f, ensure_ascii=False, indent=4)

# --- 2. 數據獲取函式 ---
@st.cache_data(ttl=60)
def get_price_data(ticker, period_label):
    """獲取行情資料"""
    stock = yf.Ticker(f"{ticker}.TW")
    if period_label == "今日":
        df = stock.history(period="1d", interval="1m")
        if df.empty: df = stock.history(period="5d", interval="5m")
    elif period_label == "5日":
        df = stock.history(period="5d", interval="5m")
    else:
        p_map = {"1月": "1mo", "3月": "3mo", "半年": "6mo", "1年": "1y", "5年": "5y"}
        df = stock.history(period=p_map.get(period_label, "1d"))
    if not df.empty and df.index.tz is not None:
        df.index = df.index.tz_convert('Asia/Taipei')
    return df

@st.cache_data(ttl=60)
def get_header_metrics(ticker):
    s = yf.Ticker(f"{ticker}.TW")
    h_today = s.history(period="1d")
    h_year = s.history(period="1y")
    info = s.info
    open_p = h_today['Open'].iloc[-1] if not h_today.empty else 0
    current_p = info.get("currentPrice", h_today['Close'].iloc[-1] if not h_today.empty else 0)
    growth = ((current_p - h_year['Close'].iloc[0]) / h_year['Close'].iloc[0] * 100) if not h_year.empty else 0
    return {"open": open_p, "current": current_p, "eps": info.get("trailingEps", 0), "dividend": info.get("lastDividendValue", 0), "growth": growth}

# --- 3. 側邊欄佈局 ---
with st.sidebar:
    st.title("🛡️ 戰情控制中心")

    with st.expander("🔍 股票查詢", expanded=True):
        main_search_id = st.text_input("輸入代號 (主圖顯示)", value="2330").upper()
    
    with st.expander("📁 資料夾編輯", expanded=True):
        st.write("**現有資料夾：**")
        for folder_name in list(st.session_state.watchlists.keys()):
            is_active = (st.session_state.active_folder == folder_name)
            icon = "📂" if is_active else "📁"
            if st.button(f"{icon} {folder_name}", key=f"f_{folder_name}", use_container_width=True):
                st.session_state.active_folder = folder_name if not is_active else None
                st.rerun()
            if st.session_state.active_folder == folder_name:
                stocks = st.session_state.watchlists[folder_name]
                if stocks:
                    for s in stocks: st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;📄 `{s}`")
                else: st.caption("&nbsp;&nbsp;&nbsp;&nbsp;(資料夾為空)")

        st.write("---")
        # --- 按鈕移至此處 (列表下方) ---
        if st.button(f"📥 加入 {main_search_id}", use_container_width=True):
            if st.session_state.active_folder and main_search_id not in st.session_state.watchlists[st.session_state.active_folder]:
                st.session_state.watchlists[st.session_state.active_folder].append(main_search_id)
                save_db(); st.rerun()
        
        if st.button(f"📤 移除 {main_search_id}", use_container_width=True):
            if st.session_state.active_folder and main_search_id in st.session_state.watchlists[st.session_state.active_folder]:
                st.session_state.watchlists[st.session_state.active_folder].remove(main_search_id)
                save_db(); st.rerun()

        st.divider()
        st.write("**管理動作：**")
        new_f = st.text_input("新資料夾名稱", placeholder="輸入名稱...", label_visibility="collapsed")
        if st.button("✨ 建立新資料夾", use_container_width=True):
            if new_f: st.session_state.watchlists[new_f] = []; save_db(); st.rerun()
        
        if st.button("🗑️ 刪除選中資料夾", use_container_width=True):
            if st.session_state.active_folder:
                del st.session_state.watchlists[st.session_state.active_folder]
                st.session_state.active_folder = None; save_db(); st.rerun()

    with st.expander("📊 分析維度設定", expanded=True):
        view_option = st.radio("左下角顯示內容：", ["三大法人買賣超", "歷年趨勢對比", "同業指標對比"])

# --- 4. 主畫面佈局 ---
left_main, right_info = st.columns([2, 1])

with left_main:
    # [左上：行情圖區]
    st.subheader(f"📈 {main_search_id} 行情走勢")
    t_col1, t_col2 = st.columns([1, 2])
    chart_type = t_col1.selectbox("類別", ["K線圖", "折線圖"])
    time_scale = t_col2.select_slider("時間尺度", options=["今日", "5日","1月", "3月", "半年", "1年", "5年"])
    
    hist = get_price_data(main_search_id, time_scale)
    if not hist.empty:
        fig = go.Figure()
        if chart_type == "折線圖":
            fig.add_trace(go.Scatter(x=hist.index, y=hist['Close'], mode='lines', line=dict(color='#1f77b4')))
        else:
            fig.add_trace(go.Candlestick(x=hist.index, open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close']))
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
        fig.update_layout(height=400, xaxis_rangeslider_visible=False, template="plotly_white", margin=dict(t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # [左下：動態呈現區]
    st.subheader(f"🧐 深度分析：{view_option}")
    
    if view_option == "三大法人買賣超":
        df_chip = api.taiwan_stock_institutional_investors(stock_id=main_search_id, start_date=(datetime.now()-timedelta(days=30)).strftime('%Y-%m-%d'))
        if not df_chip.empty:
            st.plotly_chart(px.bar(df_chip, x='date', y='buy', color='name', barmode='group', template="plotly_white"), use_container_width=True)
            
    elif view_option == "歷年趨勢對比":
        # 歷年指標選擇 (位於圖表上方)
        sel = st.multiselect("選擇歷年指標", ["Revenue", "CostOfGoodsSold", "GrossProfit", "EPS"], default=["EPS"])
        df_f = api.taiwan_stock_financial_statement(stock_id=main_search_id, start_date='2021-01-01')
        if not df_f.empty and sel:
            df_plt = df_f[df_f['type'].isin(sel)]
            st.plotly_chart(px.line(df_plt, x='date', y='value', color='type', markers=True, template="plotly_white"), use_container_width=True)
            
    elif view_option == "同業指標對比":
        # 同業指標選擇 (位於圖表上方)
        compare_metrics = st.multiselect("選擇對比指標", ["EPS", "本益比(PER)", "股價淨值比(PBR)", "股利率"], default=["EPS"])
        target_folder = st.session_state.active_folder
        
        if target_folder and st.session_state.watchlists[target_folder] and compare_metrics:
            peer_list = st.session_state.watchlists[target_folder]
            comp_data = []
            for sid in peer_list:
                try:
                    s_inf = yf.Ticker(f"{sid}.TW").info
                    m_map = {
                        "EPS": s_inf.get("trailingEps", 0),
                        "本益比(PER)": s_inf.get("trailingPE", 0),
                        "股價淨值比(PBR)": s_inf.get("priceToBook", 0),
                        "股利率": (s_inf.get("dividendYield", 0) * 100) if s_inf.get("dividendYield") else 0
                    }
                    row = {"代號": sid}
                    for m_name in compare_metrics: row[m_name] = m_map.get(m_name, 0)
                    comp_data.append(row)
                except: continue
            
            if comp_data:
                df_comp = pd.DataFrame(comp_data)
                df_melt = df_comp.melt(id_vars="代號", var_name="指標", value_name="數值")
                st.plotly_chart(px.bar(df_melt, x="代號", y="數值", color="指標", barmode="group", template="plotly_white"), use_container_width=True)
        else:
            st.info("請點選左側資料夾並選擇指標。")

with right_info:
    # [右上：數據卡片]
    st.subheader("💎 核心指標數據")
    try:
        m = get_header_metrics(main_search_id)
        r1, r2 = st.columns(2)
        r1.metric("今日開盤", f"${m['open']:.2f}")
        r1.metric("現價/收盤", f"${m['current']:.2f}", f"{m['growth']:.2f}% (年)")
        r2.metric("追蹤 EPS", f"${m['eps']:.2f}")
        r2.metric("最新股利", f"${m['dividend']:.2f}")
    except: st.error("數據更新中...")

    st.divider()
    # [右下：詳細財報表格]
    st.subheader("📋 歷史財務報表")
    df_raw = api.taiwan_stock_financial_statement(stock_id=main_search_id, start_date='2022-01-01')
    if not df_raw.empty:
        df_p = df_raw.pivot(index='type', columns='date', values='value').sort_index(axis=1, ascending=False)
        st.dataframe(df_p, height=550, use_container_width=True)