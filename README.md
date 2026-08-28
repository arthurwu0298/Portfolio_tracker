# 台灣股市投資組合自動追蹤系統 (優化版)

這是一套整合了 TWSE OpenAPI、yfinance、SQLite、Matplotlib 與 GitHub Actions 的全自動化投資組合追蹤工具。

## 系統核心特點
1. **GitHub Actions + LINE Notify**：全自動排程執行，無需自備伺服器。每日收盤後自動將報表與走勢圖推播至你的 LINE。
2. **SQLite 本地/雲端儲存**：每日資產淨值自動寫入 `portfolio_history.db`，並由 GitHub Actions 自動推回儲存庫 (Commit back)，達成無伺服器的歷史追蹤。
3. **動態走勢圖**：利用 `matplotlib` 自動讀取資料庫，繪製並發送資產淨值成長曲線圖。
4. **真實 ETF 殖利率計算**：TWSE API 的 ETF 殖利率有時失真，本系統透過 `yfinance` 抓取近 12 個月實際配息資料，反推 0050、00878 等 ETF 真正的年化殖利率。

## 如何部署 (免伺服器教學)
1. **建立專案**：將此 ZIP 解壓縮後的所有檔案，上傳至你的 GitHub Private Repository (私人儲存庫)。
2. **LINE Notify 申請**：
   - 前往 [LINE Notify 官方網站](https://notify-bot.line.me/zh_TW/) 並登入你的 LINE 帳號。
   - 點選右上角「個人頁面」 -> 「發行權杖 (Generate token)」。
   - 選擇要接收通知的聊天室 (例如「透過1對1聊天接收」)，並將權杖(Token)複製下來。
3. **設定 GitHub Secrets**：
   - 到你的 GitHub Repo，點選 **Settings > Secrets and variables > Actions**。
   - 新增一個 Secret，名稱必須為 `LINE_NOTIFY_TOKEN`，值貼上剛才複製的權杖。
4. **給予 Action 寫入權限 (為了更新 SQLite 資料庫)**：
   - 到 Repo 的 **Settings > Actions > General**。
   - 在 **Workflow permissions** 區塊，勾選 **Read and write permissions** 並儲存。
5. **啟動排程**：
   - 系統已設定為 **每週一到週五的台灣時間下午 17:30** 自動執行。
   - 你也可以在 GitHub Repo 的 **Actions** 頁籤中，點選「Daily Portfolio Tracker」，手動按下「Run workflow」來立即測試推播結果！
