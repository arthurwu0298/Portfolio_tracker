# 台灣股市投資組合自動追蹤系統 (Gmail 版)

這是一套整合了 TWSE OpenAPI、yfinance、SQLite、Matplotlib 與 GitHub Actions 的全自動化投資組合追蹤工具。

## 為什麼選擇 Gmail？
相較於通訊軟體 (LINE、Telegram、Discord)，Email 是最穩定、最不依賴第三方平台 API 的終極解法。本系統使用 Python 內建函式庫，自動生成精美的 HTML 表格，並將資產走勢圖內嵌於信件中，每天自動寄送到你的信箱。

## 如何部署 (免伺服器教學)
1. **建立專案**：將此 ZIP 解壓縮後的所有檔案，上傳至你的 GitHub Private Repository (私人儲存庫)。
2. **申請 Gmail 應用程式密碼 (App Password)**：
   - 登入你的 Google 帳號，前往 **「管理你的 Google 帳號」**。
   - 選擇左側選單的 **安全性 (Security)**。
   - 確認你已經開啟 **兩步驟驗證 (2-Step Verification)**。
   - 在搜尋列搜尋 **「應用程式密碼 (App passwords)」**。
   - 建立一個新的應用程式名稱 (例如 "Portfolio Tracker")，系統會產生一組 **16 位數的英文字母密碼**，請複製下來。
3. **設定 GitHub Secrets**：
   - 到你的 GitHub Repo，點選 **Settings > Secrets and variables > Actions**。
   - 新增第一個 Secret，名稱為 `GMAIL_ADDRESS`，填入你的 Gmail 信箱 (例如 `yourname@gmail.com`)。
   - 新增第二個 Secret，名稱為 `GMAIL_APP_PASSWORD`，貼上剛才產生的 16 碼應用程式密碼。
4. **給予 Action 寫入權限 (為了更新 SQLite 資料庫)**：
   - 到 Repo 的 **Settings > Actions > General**。
   - 在 **Workflow permissions** 區塊，勾選 **Read and write permissions** 並儲存。
5. **啟動排程**：
   - 系統已設定為 **每週一到週五的台灣時間下午 17:30** 自動執行。
   - 你也可以在 GitHub Repo 的 **Actions** 頁籤中，點選「Daily Portfolio Tracker」，手動按下「Run workflow」來立即測試，你的信箱馬上就會收到報表！

## 本次更新：估值邏輯強化

針對「本益比法／淨值比法用固定價格門檻判斷停利，無法區分『剛過線一點點』跟『歷史級噴出』」的問題，做了以下強化：

1. **歷史百分位判斷**（`valuation_engine.py`）
   `calc_pe_valuation` / `calc_pb_valuation` 現在會多回傳一個值：現在的本益比／淨值比，落在近 5 年歷史資料的第幾百分位。價格門檻（便宜價/合理價/目標價）的計算方式不變，但判斷「是否為統計異常」改用百分位，不受個股股價絕對水位影響。

2. **營收動能交叉驗證**
   新增 `get_revenue_momentum()`，比對最新月營收年增率是否比 3 個月前更快。當估值百分位超過 `portfolio_config.py` 裡的 `EXTREME_VALUATION_PERCENTILE`（預設 95）時，會再檢查營收是否同步加速（`MOMENTUM_YOY_THRESHOLD`，預設年增 20%）：
   - 估值破新高 **且** 營收同步加速 → 🟣 標記為「結構性重估中」，提醒這不是一般的停利訊號。
   - 估值破新高 **但** 營收未同步加速 → 🔴 標記為更嚴格的警示，慎防情緒推升。
   - 沒有落在極端百分位（例如剛好過線一點點的個股）→ 維持原本的燈號邏輯，不受影響。

3. **個股質化備註欄位**（`portfolio_config.py` 的 `note` 欄位）
   讓模型看不到的質化風險（法律訴訟、合併綜效、ETF報酬結構與殖利率脫鉤等）可以直接附註在對應個股上，並顯示在信件的狀態欄位下方。

4. **資料抓取異常警示**
   所有 API／備援抓取的例外現在都會被收集到 `self.fetch_errors`，並在 email 最上方顯示黃色警示條，避免把「資料抓不到」誤讀成「模型判斷為觀望」。

5. **FinMind API 輕量快取**
   歷史 PER/PBR/月營收資料現在會快取進 `portfolio_history.db` 的 `finmind_cache` 表，預設 7 天內不重複抓取，降低免費額度用量，也讓 API 短暫異常時仍有舊資料可用。

> 以上調整僅供輔助判斷，不構成投資建議；`EXTREME_VALUATION_PERCENTILE` 與 `MOMENTUM_YOY_THRESHOLD` 兩個門檻都可以在 `portfolio_config.py` 依個人風險偏好調整。
