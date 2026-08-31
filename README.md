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
