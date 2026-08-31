# portfolio_config.py
import os

# 優化版 50萬 配置 (核心成長 + 金融防禦 + 指數/高息)
# 新增 cheap(便宜價), fair(合理價), target(目標價) 供系統判斷狀態
PORTFOLIO = [
    {"code": "2480", "name": "敦陽科", "market": "TWSE", "shares": 650, "cost_per_share": 153.8, "cheap": 140, "fair": 160, "target": 180},
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 350, "cost_per_share": 200.0, "cheap": 190, "fair": 210, "target": 230},
    {"code": "6146", "name": "耕興", "market": "TPEx", "shares": 300, "cost_per_share": 233.3, "cheap": 200, "fair": 240, "target": 280},
    {"code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 1000, "cost_per_share": 40.0, "cheap": 35, "fair": 40, "target": 45},
    {"code": "2892", "name": "玉山金", "market": "TWSE", "shares": 1400, "cost_per_share": 28.5, "cheap": 25, "fair": 28, "target": 32},
    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 1000, "cost_per_share": 100.0, "cheap": 90, "fair": 105, "target": 120},
    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 1300, "cost_per_share": 23.0, "cheap": 21, "fair": 23, "target": 26},
]

CASH_RESERVE = 50000

# Gmail 設定 (由 GitHub Actions 的 Secrets 提供)
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
