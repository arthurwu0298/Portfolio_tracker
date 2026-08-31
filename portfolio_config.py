# portfolio_config.py
import os

# 優化版 50萬 配置 (核心成長 + 金融防禦 + 指數/高息)
PORTFOLIO = [
    {"code": "2480", "name": "敦陽科", "market": "TWSE", "shares": 650, "cost_per_share": 153.8},
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 350, "cost_per_share": 200.0},
    {"code": "6146", "name": "耕興", "market": "TPEx", "shares": 300, "cost_per_share": 233.3},
    {"code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 1000, "cost_per_share": 40.0},
    {"code": "2892", "name": "玉山金", "market": "TWSE", "shares": 1400, "cost_per_share": 28.5},
    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 1000, "cost_per_share": 100.0},
    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 1300, "cost_per_share": 23.0},
]

CASH_RESERVE = 50000

# Gmail 設定 (由 GitHub Actions 的 Secrets 提供)
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
