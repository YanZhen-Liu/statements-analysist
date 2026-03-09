import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
from datetime import datetime, timedelta
import json
import os
from openai import OpenAI
import re

# --- 1. 系統初始化 ---
st.set_page_config(page_title="全球股權資訊對比助手", layout="wide")

st.markdown("""
    <style>
    [data-testid="stSidebar"] button {
        text-align: left !important;
        justify-content: flex-start !important;
        display: block;
        width: 100%;
        margin-bottom: 5px;
    }
    [data-testid="stExpander"] { border: none !important; }
    [data-testid="stVerticalBlockBorderWrapper"] { border: none !important; }
    .ai-chat-box { 
    background-color: #f8f9fa; 
    padding: 12px; 
    border-radius: 10px; 
    border: 1px solid #dee2e6; 
    height: 400px; 
    overflow-y: auto; 
    margin-bottom: 10px; 
    }
    .stChatMessage div.stMarkdown p {
        font-size: 12px !important;
        line-height: 1.2;
    }
    .st-emotion-cache-sh2k3v { 
        border-top: none !important; 
        background-color: transparent !important; 
    }
    .stMetric { 
    background-color: #ffffff; 
    border-radius: 5px; 
    padding: 5px; 
    border: 1px solid #eee; 
    }
    div.stButton > button:first-child { 
    height: 3em; 
    font-weight: bold;
    }
    .metric-red { color: #FF3333; font-weight: bold; font-size: 24px; }
    .metric-green { color: #00AA00; font-weight: bold; font-size: 24px; }
    [data-testid="stMetricValue"] { font-size: 20px !important; }
    div.stButton > button:first-child {
        height: 3em;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

api = DataLoader()
DB_FILE = "portfolio_db.json"

# 標準科目權重
US_STD_ORDER = {
    "Total Revenue": 10, "Cost of Revenue": 20, "Gross Profit": 30, "Operating Expense": 40,
    "Operating Income": 50, "Net Income": 90, "Basic EPS": 100
}

# yfinance 現成比率
YF_RATIOS = {
    "本益比 (PE, Trailing)": "trailingPE",
    "預估本益比 (PE, Forward)": "forwardPE",
    "PEG 指標": "pegRatio",
    "股價淨值比 (PB)": "priceToBook",
    "股價營收比 (PS)": "priceToSalesTrailing12Months",
    "EV/EBITDA": "enterpriseValueToEbitda",
    "淨利率 (Net Margin)": "profitMargins",
    "毛利率 (Gross Margin)": "grossMargins",
    "營益率 (Op Margin)": "operatingMargins",
    "ROE": "returnOnEquity",
    "ROA": "returnOnAssets",
    "流動比率": "currentRatio",
    "速動比率": "quickRatio",
    "負債權益比": "debtToEquity",
    "Beta (波動風險)": "beta",
    "殖利率 (Yield)": "dividendYield",
    "配息率": "payoutRatio"
}
PERCENTAGE_FIELDS = ["profitMargins", "grossMargins", "operatingMargins", "returnOnAssets", "returnOnEquity", "dividendYield", "payoutRatio"]

# 資料庫讀取
if 'db' not in st.session_state:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                temp_db = json.load(f)
                if "watchlists" not in temp_db:
                    temp_db = {"watchlists": temp_db, "custom_ratios": {}}
                if "custom_ratios" not in temp_db:
                    temp_db["custom_ratios"] = {}
                st.session_state.db = temp_db
        except:
            st.session_state.db = {"watchlists": {"權值股": ["2330", "TSLA"]}, "custom_ratios": {}}
    else:
        st.session_state.db = {"watchlists": {"權值股": ["2330", "TSLA"]}, "custom_ratios": {}}

if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'active_folder' not in st.session_state: st.session_state.active_folder = None
if 'formula_buffer' not in st.session_state: st.session_state.formula_buffer = ""

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.db, f, ensure_ascii=False, indent=4)

# --- 2. 核心數據引擎 ---

@st.cache_data(ttl=600)
def get_price_data(ticker, period_label, market):
    symbol = f"{ticker}.TW" if market == "台股" and ticker.isdigit() else ticker
    p_map = {"今日": "1d", "5日": "5d", "1月": "1mo", "1年": "1y", "5年": "5y"}
    i_map = {"今日": "1m", "5日": "5m", "1月": "60m", "1年": "1d", "5年": "1d"}
    
    try:
        # [均線補償邏輯] 計算年線(250日)需要更多歷史數據
        fetch_period = "2y" if period_label == "1年" else ("7y" if period_label == "5年" else p_map.get(period_label, "1d"))
        
        df = yf.download(symbol, period=fetch_period, interval=i_map.get(period_label, "1d"), progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns] 
        df.dropna(inplace=True)
        
        if df.empty: return pd.DataFrame()

        # 計算均線
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['MA250'] = df['Close'].rolling(window=250).mean()

        if df.index.tz is None: df.index = df.index.tz_localize('UTC')
        target_tz = 'Asia/Taipei' if market == "台股" else 'America/New_York'
        df.index = df.index.tz_convert(target_tz)

        df = df.reset_index()
        df.rename(columns={df.columns[0]: 'Date'}, inplace=True)
        df['Date'] = df['Date'].dt.tz_localize(None)
        
        # 過濾顯示範圍
        now = datetime.now()
        if period_label == "1年": df = df[df['Date'] >= (now - timedelta(days=365))]
        elif period_label == "1月": df = df[df['Date'] >= (now - timedelta(days=30))]

        return df
    except: return pd.DataFrame()

def add_baseline_line(fig, df, baseline, up_color, down_color, row, col):
    """基準線多色折線圖邏輯"""
    if df.empty: return
    dates, prices = df['Date'].tolist(), df['Close'].tolist()
    curr_x, curr_y, curr_status = [dates[0]], [prices[0]], prices[0] >= baseline
    for i in range(1, len(df)):
        status = prices[i] >= baseline
        if status == curr_status:
            curr_x.append(dates[i]); curr_y.append(prices[i])
        else:
            color = up_color if curr_status else down_color
            fig.add_trace(go.Scatter(x=curr_x, y=curr_y, mode='lines', line=dict(color=color, width=2.5), showlegend=False), row=row, col=col)
            curr_x, curr_y, curr_status = [dates[i-1], dates[i]], [prices[i-1], prices[i]], status
    fig.add_trace(go.Scatter(x=curr_x, y=curr_y, mode='lines', line=dict(color=(up_color if curr_status else down_color), width=2.5), showlegend=False), row=row, col=col)
    
@st.cache_data(ttl=3600)
def get_financial_data(ticker, market):
    try:
        if market == "台股":
            clean_id = "".join(filter(str.isdigit, ticker))
            df = api.taiwan_stock_financial_statement(stock_id=clean_id, start_date='2021-01-01')
            tw_us_map = {"Revenue": "Total Revenue", "CostOfGoodsSold": "Cost of Revenue", "GrossProfit": "Gross Profit", "OperatingExpenses": "Operating Expense", "OperatingIncome": "Operating Income", "NetIncome": "Net Income", "EPS": "Basic EPS"}
            df['type'] = df['type'].map(tw_us_map).fillna(df['type'])
            date_key = 'date' if 'date' in df.columns else df.columns[0]
            df = df.rename(columns={date_key: 'date'})
            return df[['date', 'type', 'value']].dropna()
        else:
            s = yf.Ticker(ticker)
            f = s.quarterly_financials.T
            df_m = f.reset_index().melt(id_vars='index', var_name='type', value_name='value').rename(columns={'index': 'date'})
            df_m.columns = ['date', 'type', 'value']
            df_m = df_m[df_m['type'].isin(US_STD_ORDER.keys())]
            df_m['date'] = pd.to_datetime(df_m['date']).dt.strftime('%Y-%m-%d')
            return df_m
    except: return pd.DataFrame()

def calculate_custom_formula(formula_str, pivot_df):
    try:
        if pivot_df.empty: return pd.Series(dtype=float)
        eval_str = formula_str.strip()
        available_cols = sorted(pivot_df.columns, key=len, reverse=True)
        for col in available_cols:
            if col in eval_str:
                eval_str = eval_str.replace(col, f"pivot_df['{col}']")
        return eval(eval_str, {"__builtins__": None}, {"pivot_df": pivot_df})
    except:
        return pd.Series(0, index=pivot_df.index)

# --- 3. 介面佈局 ---
with st.sidebar:
    st.title("控制中心")
    with st.expander("🔍 查詢設定", expanded=True):
        market_type = st.radio("選取市場", ["台股", "美股"], horizontal=True)
        main_id = st.text_input("輸入代號", value="2330").upper()

    with st.expander("📁 資料夾編輯", expanded=True):
        for fn in list(st.session_state.db["watchlists"].keys()):
            icon = "📂" if st.session_state.active_folder == fn else "📁"
            if st.button(f"{icon} {fn}", key=f"f_{fn}"):
                st.session_state.active_folder = fn; st.rerun()
            if st.session_state.active_folder == fn:
                for s in st.session_state.db["watchlists"][fn]: st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;📄 `{s}`")
        
        st.divider()
        st.write("**股票管理**")
        if st.button(f"加入 {main_id}", use_container_width=True):
            if st.session_state.active_folder:
                if main_id not in st.session_state.db["watchlists"][st.session_state.active_folder]:
                    st.session_state.db["watchlists"][st.session_state.active_folder].append(main_id)
                    save_db(); st.rerun()
            else: st.warning("請先選擇一個資料夾")

        if st.button(f"移除 {main_id}", use_container_width=True):
            if st.session_state.active_folder:
                if main_id in st.session_state.db["watchlists"][st.session_state.active_folder]:
                    st.session_state.db["watchlists"][st.session_state.active_folder].remove(main_id)
                    save_db(); st.rerun()
            else: st.warning("請先選擇一個資料夾")
            
        st.divider()
        st.write("**資料夾管理**")
        new_folder_name = st.text_input("新資料夾名稱", placeholder="輸入名稱...", label_visibility="collapsed")
        if st.button("✨ 建立新資料夾", use_container_width=True):
            if new_folder_name and new_folder_name not in st.session_state.db["watchlists"]:
                st.session_state.db["watchlists"][new_folder_name] = []
                save_db(); st.rerun()
        
        if st.button("🗑️ 刪除選中資料夾", use_container_width=True):
            if st.session_state.active_folder:
                del st.session_state.db["watchlists"][st.session_state.active_folder]
                st.session_state.active_folder = None
                save_db(); st.rerun()

    with st.expander("自定義財務公式", expanded=False):
        st.write("目前公式:")
        st.info(st.session_state.formula_buffer if st.session_state.formula_buffer else "(空)")
        sel_item = st.selectbox("選擇財報科目", list(US_STD_ORDER.keys()), label_visibility="collapsed")
        if st.button("加入科目", use_container_width=True):
            st.session_state.formula_buffer += f"{sel_item} "
            st.rerun()
            
        c1, c2, c3, c4 = st.columns(4)
        if c1.button("＋", key="btn_add"): st.session_state.formula_buffer += "+ "; st.rerun()
        if c2.button("−", key="btn_sub"): st.session_state.formula_buffer += "- "; st.rerun()
        if c3.button("×", key="btn_mul"): st.session_state.formula_buffer += "* "; st.rerun()
        if c4.button("÷", key="btn_div"): st.session_state.formula_buffer += "/ "; st.rerun()
        
        c5, c6, c7, c8 = st.columns(4)
        if c5.button("(", key="btn_p1"): st.session_state.formula_buffer += "( "; st.rerun()
        if c6.button(")", key="btn_p2"): st.session_state.formula_buffer += ") "; st.rerun()
        if c7.button("←", key="btn_back"): 
            st.session_state.formula_buffer = st.session_state.formula_buffer.strip().rsplit(' ', 1)[0] + ' ' if ' ' in st.session_state.formula_buffer.strip() else ""
            st.rerun()
        if c8.button("C", key="btn_clr"): 
            st.session_state.formula_buffer = ""
            st.rerun()
            
        st.divider()
        new_name = st.text_input("公式命名 (例如: 淨利率)")
        if st.button("💾 儲存自定義比率", use_container_width=True):
            if new_name and st.session_state.formula_buffer:
                st.session_state.db["custom_ratios"][new_name] = st.session_state.formula_buffer.strip()
                save_db()
                st.session_state.formula_buffer = "" 
                st.rerun()
                
        if st.session_state.db["custom_ratios"]:
            st.caption("已存公式：")
            for k, v in st.session_state.db["custom_ratios"].items():
                st.caption(f"• {k}: `{v}`")

    view_option = st.radio("深度分析 (左下角)", ["同業對比", "歷年趨勢", "三大法人/機構持有"])
    # [新增] API 金鑰設定 (建議放在 st.secrets 中，這裡提供手動輸入框作為備案)

    st.divider()
    st.write("🔑 **AI 配置**")
    api_key = st.text_input("輸入 OpenAI API Key", type="password")
    client = OpenAI(api_key=api_key) if api_key else None

# --- 4. 主畫面佈局 ---
l_col, r_col = st.columns([2, 1])
up_color, down_color, cur_label = ("#FF3333", "#00AA00", "NT$") if market_type == "台股" else ("#00AA00", "#FF3333", "US$")

# === 左欄 ===
with l_col:
    st.subheader(f"▍{main_id} 行情")
    c_type = st.selectbox("類型", ["K線圖", "折線圖"], label_visibility="collapsed")
    t_scale = st.select_slider("尺度", options=["今日", "5日", "1月", "1年", "5年"], value="今日")
    hist = get_price_data(main_id, t_scale, market_type)
    
    if not hist.empty and 'Close' in hist.columns:
        # [精細化K線：Subplot + 均線]
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_width=[0.2, 0.8])
        baseline = hist['Open'].iloc[0]
        if c_type == "折線圖":
            add_baseline_line(fig, hist, baseline, up_color, down_color, row=1, col=1)
            fig.add_hline(y=baseline, line_dash="dash", line_color="gray", line_width=1, row=1, col=1)
        else:
            fig.add_trace(go.Candlestick(
                x=hist['Date'], open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
                increasing_line_color=up_color, decreasing_line_color=down_color,
                increasing_fillcolor=up_color, decreasing_fillcolor=down_color, name="K線"
            ), row=1, col=1)
            # 疊加均線
            fig.add_trace(go.Scatter(x=hist['Date'], y=hist['MA20'], line=dict(color='#FFA500', width=1), name="月線(MA20)"), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist['Date'], y=hist['MA60'], line=dict(color='#008000', width=1), name="季線(MA60)"), row=1, col=1)
            fig.add_trace(go.Scatter(x=hist['Date'], y=hist['MA250'], line=dict(color='#800080', width=1.2), name="年線(MA250)"), row=1, col=1)
        
        # 成交量
        vol_colors = [up_color if c >= o else down_color for o, c in zip(hist['Open'], hist['Close'])]
        fig.add_trace(go.Bar(x=hist['Date'], y=hist['Volume'], marker_color=vol_colors, name="成交量"), row=2, col=1)
        
        breaks = [dict(bounds=["sat", "mon"])] 
        if t_scale in ["今日", "5日", "1月"]:
            if market_type == "台股": breaks.append(dict(bounds=[13.5, 9], pattern="hour"))
            else: breaks.append(dict(bounds=[16, 9.5], pattern="hour"))
        
        fig.update_xaxes(rangebreaks=breaks)
        fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_white", margin=dict(t=0,b=0), yaxis=dict(title=cur_label))
        st.plotly_chart(fig, use_container_width=True)

        # [行情詳情：五檔報價]
        with st.expander("📊 查看五檔報價詳情 (Order Book)"):
            cp = hist['Close'].iloc[-1]
            c1, c2 = st.columns(2)
            bid_df = pd.DataFrame({'買入價': [round(cp-0.05*i, 2) for i in range(1,6)], '量': [150, 320, 410, 220, 180]})
            ask_df = pd.DataFrame({'賣出價': [round(cp+0.05*i, 2) for i in range(1,6)], '量': [90, 210, 180, 350, 420]})
            c1.dataframe(bid_df, hide_index=True, use_container_width=True)
            c2.dataframe(ask_df, hide_index=True, use_container_width=True)
    else:
        st.error("無法獲取行情，請確認代號。")

    st.divider()

    # 左下分析面板
    if view_option == "歷年趨勢":
        st.subheader("歷年趨勢")
        trend_options = list(US_STD_ORDER.keys()) + list(st.session_state.db["custom_ratios"].keys())
        sel_t = st.multiselect("比率", trend_options, default=["Total Revenue"])
        df_f = get_financial_data(main_id, market_type)
        if not df_f.empty and sel_t:
            fig_t = go.Figure()
            piv = df_f.pivot_table(index='date', columns='type', values='value').sort_index()
            for m in sel_t:
                if m in st.session_state.db["custom_ratios"]:
                    res = calculate_custom_formula(st.session_state.db["custom_ratios"][m], piv)
                    if not isinstance(res, pd.Series) or res.empty: continue
                    fig_t.add_trace(go.Scatter(x=res.index, y=res, name=m))
                elif m in piv.columns:
                    fig_t.add_trace(go.Scatter(x=piv.index, y=piv[m], name=m))
            st.plotly_chart(fig_t, use_container_width=True)
            
    elif view_option == "同業對比":
        st.subheader("同業對比")
        full_options = list(US_STD_ORDER.keys()) + list(st.session_state.db["custom_ratios"].keys()) + list(YF_RATIOS.keys())
        sel_c = st.multiselect("指標", full_options, default=["本益比 (PE, Trailing)"])
        if st.session_state.active_folder:
            peers = st.session_state.db["watchlists"].get(st.session_state.active_folder, [])
            all_d = []
            for sid in peers:
                m_t = "台股" if sid.isdigit() else "美股"
                df_p = get_financial_data(sid, m_t)
                s_info = yf.Ticker(f"{sid}.TW" if m_t=="台股" else sid).info
                row = {"代號": sid}
                p_piv = df_p.pivot_table(index='date', columns='type', values='value').sort_index() if not df_p.empty else pd.DataFrame()
                for m in sel_c:
                    val = 0
                    if m in YF_RATIOS:
                        raw = s_info.get(YF_RATIOS[m], 0)
                        val = raw * 100 if raw and YF_RATIOS[m] in PERCENTAGE_FIELDS else (raw or 0)
                    elif m in st.session_state.db["custom_ratios"] and not p_piv.empty:
                        res = calculate_custom_formula(st.session_state.db["custom_ratios"][m], p_piv)
                        val = res.iloc[-1] if not res.empty else 0
                    elif not p_piv.empty and m in p_piv.columns:
                        val = p_piv[m].iloc[-1]
                    row[m] = val
                all_d.append(row)
            if all_d: 
                df_chart = pd.DataFrame(all_d).melt(id_vars="代號")
                st.plotly_chart(px.bar(df_chart, x="代號", y="value", color="variable", barmode="group", template="plotly_white"), use_container_width=True)
        else: st.info("請先選擇資料夾")

    elif view_option == "三大法人/機構持有":
        if market_type == "台股":
            st.subheader("台股三大法人買賣超 (淨額)")
            try:
                clean_id = "".join(filter(str.isdigit, main_id))
                df_chip = api.taiwan_stock_institutional_investors(stock_id=clean_id, start_date=(datetime.now()-timedelta(days=40)).strftime('%Y-%m-%d'))
                if not df_chip.empty:
                    df_chip['net'] = df_chip['buy'] - df_chip['sell']
                    fig_chip = px.bar(df_chip, x='date', y='net', color='name', barmode='group')
                    max_abs = df_chip['net'].abs().max() * 1.1
                    fig_chip.update_layout(yaxis_range=[-max_abs, max_abs], template="plotly_white")
                    st.plotly_chart(fig_chip, use_container_width=True)
                    
                    # [法人明細詳情]
                    with st.expander("📅 三大法人每日淨進出明細 (由近到遠)"):
                        detail = df_chip.pivot_table(index='date', columns='name', values='net', aggfunc='sum').sort_index(ascending=False)
                        st.dataframe(detail.style.applymap(lambda v: f'color: {"#FF3333" if v>0 else "#00AA00"}; font-weight:bold'), use_container_width=True)
            except: st.error("法人數據抓取失敗")
        else:
            st.subheader("美股機構持有")
            try:
                holders = yf.Ticker(main_id).institutional_holders
                if holders is not None: st.dataframe(holders, use_container_width=True)
            except: st.info("暫無資料")

# === 右欄 ===
with r_col:
    st.subheader("數據摘要")
    try:
        s_sym = f"{main_id}.TW" if (market_type=="台股" or main_id.isdigit()) else main_id
        ticker_obj = yf.Ticker(s_sym)
        info = ticker_obj.info
        curr_p = info.get('currentPrice') or info.get('regularMarketPrice') or (hist['Close'].iloc[-1] if not hist.empty else 0)
        
        m1, m2 = st.columns(2)
        m1.metric("現價", f"{cur_label} {curr_p:,.2f}")
        m1.metric("EPS", f"${info.get('trailingEps', 0):.2f}")
        m2.metric("本益比", f"{info.get('trailingPE', 0):.2f}")
        m2.metric("股利", f"${info.get('lastDividendValue', 0):.2f}")
    except: st.caption("載入中...")

    st.divider()
    st.subheader("財務報表")
    df_raw = get_financial_data(main_id, market_type)
    if not df_raw.empty:
        df_p = df_raw.pivot_table(index='type', columns='date', values='value').sort_index(axis=1, ascending=False)
        sorted_idx = sorted(df_p.index, key=lambda x: US_STD_ORDER.get(x, 999))
        st.dataframe(df_p.reindex(sorted_idx), height=500, use_container_width=True)
        
    st.divider()
    st.subheader("🤖 AI 投資助手")
    
    # 自動生成當前狀態背景
    if not hist.empty:
        ma60_val = hist['MA60'].iloc[-1]
        trend_status = "站在季線上方 (多頭趨勢)" if cp > ma60_val else "位居季線下方 (空頭趨勢)"
        context_prompt = f"當前股票: {main_id}, 現價: {cp}, {trend_status}。請提供投資建議。"
        
        # 對話顯示區
        chat_container = st.container(height=250)
        with chat_container:
            st.markdown('<div class="ai-chat-box">', unsafe_allow_html=True)
            if not st.session_state.chat_history:
                st.write(f"**系統提示:** 偵測到 {main_id}。{trend_status}。您可以開始詢問具體策略。")
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
            st.markdown('</div>', unsafe_allow_html=True)

        # 對話輸入
        if not client:
            st.warning("若需要使用模型，在左方側邊欄輸入OpenAI API Key即可啟動對話。")
            user_input = st.text_input("輸入您的問題 (例如: 支撐位在哪?)...", key="chat_input")
            if st.button("發送詢問", use_container_width=True):
                if user_input:
                    st.session_state.chat_history.append({"role": "user", "content": user_input})
                    # 模擬 AI 回應 (實務上可對接 OpenAI/Gemini API)
                    ai_reply = f"根據檢索，{main_id} 目前{trend_status}。技術面上，短線支撐約在 {round(cp*0.95, 2)} 附近。考量到當前市場波動，建議分批佈局。"
                st.session_state.chat_history.append({"role": "assistant", "content": ai_reply})
                st.rerun()
        else:
            user_input = st.text_input("詢問 AI 關於這檔股票...", key="chat_input")
            if st.button("發送詢問", use_container_width=True):
                if user_input:
                    context = f"當前標的: {main_id}, 現價: {curr_p}, 季線(MA60): {ma60_val}。投資者問題: {user_input}"
                    st.session_state.chat_history.append({"role": "user", "content": user_input})
                    with st.chat_message("assistant"):
                        message_placeholder = st.empty()
                        full_response = ""
                        try:
                            response = client.chat.completions.create(
                                model="gpt-3.5-turbo",
                                messages=[{"role": "system", "content": context + "你是一位專業的證券分析師。請根據提供的數據, 問題給出具體的投資分析與風險提示。"}, 
                                {"role": "user", "content": context}],
                                stream=True
                            )
                            for chunk in response:
                                if chunk.choices[0].delta.content:
                                    full_response += chunk.choices[0].delta.content
                                    message_placeholder.markdown(full_response + "▌")
                            message_placeholder.markdown(full_response)
                            st.session_state.chat_history.append({"role": "assistant", "content": full_response})
                            st.rerun()
                        except Exception as e:
                            st.error(f"API 呼叫失敗: {e}")
                    
    