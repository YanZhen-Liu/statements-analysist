# 📈 台股全方位深度分析系統 (Taiwan Stock Insight Pro)

這是一個基於 **Streamlit** 開發的專業級台股分析儀表板。整合了技術面（yfinance）、基本面與籌碼面（FinMind）數據，並提供如 Windows 檔案管理員般的直覺式收藏夾管理功能。

## ✨ 核心功能

### 1. 🛡️ 戰情控制中心 (側邊欄)

* **全局股票查詢**：輸入台股代號即可同步更新全站數據。
* **檔案管理員式收藏夾**：
* 樹狀目錄結構：點擊資料夾即可展開/收合股票清單。
* 快速管理：支援新建資料夾、刪除資料夾，以及將當前股票一鍵加入/移除。


* **分析維度切換**：自由切換左下角的深度分析圖表。

### 2. 📊 視覺化行情監控 (左上)

* **動態尺度切換**：支援「今日 (分線)」、「1月 (小時線)」、「1年 (日線)」切換。
* **圖表類別**：提供專業 K 線圖與簡潔折線圖。
* **視覺優化**：自動消除週末與節假日空隙，解決 K 線稀疏問題。

### 3. 🧐 深度分析視窗 (左下)

* **三大法人買賣超**：視覺化外資、投信、自營商近一個月的對抗動向。
* **歷年趨勢對比**：自選營收、淨利、EPS 等核心財務指標的年度成長曲線。
* **同業指標對比**：**連動收藏夾**，選取資料夾後可對比該族群內所有個股的 EPS、本益比、股利率等關鍵指標。

### 4. 💎 核心數據與財報 (右側)

* **即時行情卡片**：鎖定今日開盤價、現價、年增率、EPS 與最新股利資訊。
* **歷史財報明細**：自動轉置的財報數據表，完整呈現近兩年的損益科目。

---

## 🛠️ 技術棧

* **Frontend**: [Streamlit](https://streamlit.io/)
* **Data Source**:
* [yfinance](https://github.com/ranaroussi/yfinance) (行情數據)
* [FinMind](https://github.com/FinMind/FinMind) (財報與籌碼數據)


* **Visualization**: [Plotly](https://plotly.com/python/)
* **Storage**: 本地 JSON 持久化存儲

---

## 🚀 快速開始

### 1. 克隆專案

```bash
git clone https://github.com/YanZhen-Liu/statements-analysist.git
cd statements-analysist

```

### 2. 安裝環境需求

請確保已安裝 Python 3.8+，然後執行：

```bash
pip install -r requirements.txt

```

### 3. 啟動應用程式

```bash
streamlit run app.py

```

---

## 📂 專案結構

```text
├── app.py                 # 主程式邏輯
├── requirements.txt       # 必要的 Python 套件清單
├── portfolio_db.json      # 使用者收藏夾設定檔 (自動產生)
└── README.md              # 專案說明文件

```

---

## 📝 使用說明

1. 在側邊欄「股票查詢」輸入 **2330** (台積電)。
2. 在「資料夾管理」建立新資料夾，例如「半導體」。
3. 點選該資料夾後，點擊「將 2330 加入選中」。
4. 切換左下角至「同業指標對比」，即可開始進行族群分析。

---

**Would you like me to help you refine the CSS styles in the code to make it look even closer to a high-end trading terminal?**