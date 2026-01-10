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
    .metric-red { color: #FF3333; font-weight: bold; font-size: 24px; }
    .metric-green { color: #00AA00; font-weight: bold; font-size: 24px; }
    [data-testid="stMetricValue"] { font-size: 20px !important; }
    /* 計算機按鈕樣式優化 */
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

if 'db' not in st.session_state:
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            st.session_state.db = json.load(f)
    else:
        st.session_state.db = {"watchlists": {"權值股": ["2330", "TSLA"]}, "custom_ratios": {}}

if 'active_folder' not in st.session_state: st.session_state.active_folder = None
# 初始化公式緩衝區
if 'formula_buffer' not in st.session_state: st.session_state.formula_buffer = ""

def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.db, f, ensure_ascii=False, indent=4)

# --- 2. 核心數據引擎 ---

@st.cache_data(ttl=10)
def get_price_data(ticker, period_label, market):
    symbol = f"{ticker}.TW" if market == "台股" and ticker.isdigit() else ticker
    p_map = {"今日": "1d", "5日": "5d", "1月": "1mo", "1年": "1y", "5年": "5y"}
    i_map = {"今日": "1m", "5日": "5m", "1月": "60m", "1年": "1d", "5年": "1d"}
    
    try:
        df = yf.download(symbol, period=p_map.get(period_label, "1d"), interval=i_map.get(period_label, "1d"), progress=False, auto_adjust=True)
        
        # 備援
        if (df.empty or len(df) < 2) and period_label == "今日":
            df = yf.download(symbol, period="5d", interval="5m", progress=False, auto_adjust=True)

        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns] 
        df.dropna(inplace=True)
        if df.empty: return pd.DataFrame()

        if df.index.tz is None: df.index = df.index.tz_localize('UTC')
        target_tz = 'Asia/Taipei' if market == "台股" else 'America/New_York'
        df.index = df.index.tz_convert(target_tz)

        df = df.reset_index()
        df.rename(columns={df.columns[0]: 'Date'}, inplace=True)
        df['Date'] = df['Date'].dt.tz_localize(None)
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_financial_data(ticker, market):
    try:
        if market == "台股":
            clean_id = "".join(filter(str.isdigit, ticker))
            df = api.taiwan_stock_financial_statement(stock_id=clean_id, start_date='2021-01-01')
            tw_us_map = {
                "Revenue": "Total Revenue", "CostOfGoodsSold": "Cost of Revenue", "GrossProfit": "Gross Profit", 
                "OperatingExpenses": "Operating Expense", "OperatingIncome": "Operating Income", 
                "NetIncome": "Net Income", "EPS": "Basic EPS"
            }
            df['type'] = df['type'].map(tw_us_map).fillna(df['type'])
            return df
        else:
            s = yf.Ticker(ticker)
            f = s.quarterly_financials.T
            rename_us = {
                "Total Revenue": "Total Revenue", "Cost Of Revenue": "Cost of Revenue", "Gross Profit": "Gross Profit",
                "Operating Expense": "Operating Expense", "Operating Income": "Operating Income", "Net Income": "Net Income",
                "Basic EPS": "Basic EPS", "Diluted EPS": "Basic EPS", "Net Income Common Stockholders": "Net Income"
            }
            cols_to_rename = {k: v for k, v in rename_us.items() if k in f.columns}
            f = f.rename(columns=cols_to_rename)
            df_m = f.reset_index().melt(id_vars='index', var_name='type', value_name='value')
            df_m.columns = ['date', 'type', 'value']
            df_m = df_m[df_m['type'].isin(US_STD_ORDER.keys())]
            df_m['date'] = pd.to_datetime(df_m['date']).dt.strftime('%Y-%m-%d')
            return df_m
    except: return pd.DataFrame()

# 輔助函式：安全計算自定義公式
def calculate_custom_formula(formula_str, pivot_df):
    try:
        if pivot_df.empty: return pd.Series(dtype=float)
        eval_str = formula_str
        available_cols = sorted(pivot_df.columns, key=len, reverse=True)
        for col in available_cols:
            if col in eval_str:
                eval_str = eval_str.replace(col, f"pivot_df['{col}']")
        return eval(eval_str, {"__builtins__": None}, {"pivot_df": pivot_df})
    except Exception as e:
        return pd.Series(0, index=pivot_df.index)

# --- 3. 介面佈局 ---
with st.sidebar:
    st.title("控制中心")
    with st.expander("🔍 查詢設定", expanded=True):
        market_type = st.radio("選取市場", ["台股", "美股"], horizontal=True)
        main_id = st.text_input("輸入代號", value="2330").upper()

    with st.expander("📁 資料夾編輯", expanded=True):
        for fn in list(st.session_state.db["watchlists"].keys()):
            # 若選中則標示為 📂，否則 📁
            icon = "📂" if st.session_state.active_folder == fn else "📁"
            if st.button(f"{icon} {fn}", key=f"f_{fn}"):
                st.session_state.active_folder = fn; st.rerun()
            if st.session_state.active_folder == fn:
                for s in st.session_state.db["watchlists"][fn]: st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;📄 `{s}`")
        
        st.divider()
        
        # [修改點] 移除 st.columns(2)，改為垂直排列
        # 加入按鈕
        if st.button(f"加入 {main_id}", use_container_width=True):
            if st.session_state.active_folder:
                if main_id not in st.session_state.db["watchlists"][st.session_state.active_folder]:
                    st.session_state.db["watchlists"][st.session_state.active_folder].append(main_id)
                    save_db(); st.rerun()
            else:
                st.warning("請先選擇一個資料夾")

        # 移除按鈕
        if st.button(f"移除 {main_id}", use_container_width=True):
            if st.session_state.active_folder:
                if main_id in st.session_state.db["watchlists"][st.session_state.active_folder]:
                    st.session_state.db["watchlists"][st.session_state.active_folder].remove(main_id)
                    save_db(); st.rerun()
            else:
                st.warning("請先選擇一個資料夾")

    # 互動式公式計算機
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
            st.session_state.formula_buffer = st.session_state.formula_buffer[:-1]
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
                st.success(f"已儲存: {new_name}")
                st.session_state.formula_buffer = "" 
                st.rerun()
                
        if st.session_state.db["custom_ratios"]:
            st.caption("已存公式：")
            for k, v in st.session_state.db["custom_ratios"].items():
                st.caption(f"• {k}: `{v}`")

    view_option = st.radio("深度分析 (左下角)", ["同業對比", "歷年趨勢", "三大法人/機構持有"])

# --- 4. 主畫面佈局 ---
l_col, r_col = st.columns([2, 1])

# === 左欄 ===
with l_col:
    st.subheader(f"▍{main_id} 行情")
    c_type = st.selectbox("類型", ["K線圖", "折線圖"], label_visibility="collapsed")
    t_scale = st.select_slider("尺度", options=["今日", "5日", "1月", "1年", "5年"], value="今日")
    
    hist = get_price_data(main_id, t_scale, market_type)
    
    if not hist.empty and 'Close' in hist.columns:
        fig = go.Figure()
        red, green = "#FF3333", "#00AA00"
        
        if c_type == "折線圖":
            fig.add_trace(go.Scatter(x=hist['Date'], y=hist['Close'], line=dict(color=red)))
        else:
            fig.add_trace(go.Candlestick(
                x=hist['Date'], open=hist['Open'], high=hist['High'], low=hist['Low'], close=hist['Close'],
                increasing_line_color=red, decreasing_line_color=green,
                increasing_fillcolor=red, decreasing_fillcolor=green
            ))
        
        breaks = [dict(bounds=["sat", "mon"])] 
        if t_scale in ["今日", "5日", "1月"]:
            if market_type == "台股": breaks.append(dict(bounds=[13.5, 9], pattern="hour"))
            else: breaks.append(dict(bounds=[16, 9.5], pattern="hour"))
        
        fig.update_xaxes(rangebreaks=breaks)
        fig.update_layout(height=400, xaxis_rangeslider_visible=False, template="plotly_white", margin=dict(t=0,b=0), yaxis=dict(autorange=True, fixedrange=False))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("無法獲取行情，請確認代號。")

    st.divider()

    # 左下分析
    if view_option == "歷年趨勢":
        st.subheader("歷年趨勢")
        trend_options = list(US_STD_ORDER.keys()) + list(st.session_state.db["custom_ratios"].keys())
        sel_t = st.multiselect("比率", trend_options, default=["Total Revenue"])
        
        df_f = get_financial_data(main_id, market_type)
        if not df_f.empty and sel_t:
            fig_t = go.Figure()
            piv = df_f.pivot_table(index='date', columns='type', values='value')
            piv = piv.sort_index()
            
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
                
                if not df_p.empty:
                    p_piv = df_p.pivot_table(index='date', columns='type', values='value')
                    p_piv = p_piv.sort_index()
                else:
                    p_piv = pd.DataFrame()

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
            st.subheader("台股三大法人")
            try:
                clean_id = "".join(filter(str.isdigit, main_id))
                df_chip = api.taiwan_stock_institutional_investors(stock_id=clean_id, start_date=(datetime.now()-timedelta(days=40)).strftime('%Y-%m-%d'))
                if not df_chip.empty:
                    st.plotly_chart(px.bar(df_chip, x='date', y='buy', color='name', barmode='group'), use_container_width=True)
            except: st.error("API 失敗")
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
        s_sym = f"{main_id}.TW" if market_type=="台股" else main_id
        info = yf.Ticker(s_sym).info
        h_1y = yf.download(s_sym, period="1y", progress=False, auto_adjust=True)
        if isinstance(h_1y.columns, pd.MultiIndex): h_1y.columns = h_1y.columns.get_level_values(0)
        
        if not h_1y.empty:
            open_p = h_1y['Open'].iloc[-1]
            curr_p = h_1y['Close'].iloc[-1]
            yoy = ((curr_p - h_1y['Close'].iloc[0]) / h_1y['Close'].iloc[0]) * 100
        else:
            open_p = info.get('open', 0)
            curr_p = info.get('currentPrice', 0)
            yoy = 0
            
        m1, m2 = st.columns(2)
        m1.metric("開盤價", f"${open_p:,.2f}")
        m1.metric("現價", f"${curr_p:,.2f}", f"{yoy:+.2f}% (YoY)")
        m2.metric("EPS", f"${info.get('trailingEps', 0):.2f}")
        m2.metric("上次股利", f"${info.get('lastDividendValue', 0):.2f}")
    except: st.caption("載入中...")

    st.divider()
    st.subheader("財務報表")
    df_raw = get_financial_data(main_id, market_type)
    if not df_raw.empty:
        df_p = df_raw.pivot_table(index='type', columns='date', values='value').sort_index(axis=1, ascending=False)
        sorted_idx = sorted(df_p.index, key=lambda x: US_STD_ORDER.get(x, 999))
        st.dataframe(df_p.reindex(sorted_idx), height=600, use_container_width=True)