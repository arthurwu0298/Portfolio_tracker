# portfolio_config.py
import os

# 優化版 50萬 配置 (核心成長 + 金融防禦 + 指數/高息)
# valuation_method: 'yield' (殖利率法), 'pe' (本益比法), 'pb' (淨值比法), 'manual' (手動設定)
# 若選擇 manual，將會直接讀取 cheap, fair, target 的數值。
# 若選擇其他自動估值，系統將會呼叫 FinMind API 計算歷史區間，自動覆寫這三個價位。

PORTFOLIO = [
    {"code": "2480", "name": "敦陽科", "market": "TWSE", "shares": 650, "cost_per_share": 153.8, "valuation_method": "yield", "target_yields": {"cheap": 6.0, "fair": 5.0, "target": 4.0}},
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 350, "cost_per_share": 200.0, "valuation_method": "pe"},
    {"code": "6146", "name": "耕興", "market": "TPEx", "shares": 300, "cost_per_share": 233.3, "valuation_method": "pe"},
    {"code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 1000, "cost_per_share": 40.0, "valuation_method": "pb"},
    {"code": "2892", "name": "玉山金", "market": "TWSE", "shares": 1400, "cost_per_share": 28.5, "valuation_method": "pb"},
    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 1000, "cost_per_share": 100.0, "valuation_method": "manual", "cheap": 90, "fair": 105, "target": 120},
    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 1300, "cost_per_share": 23.0, "valuation_method": "yield", "target_yields": {"cheap": 6.5, "fair": 5.5, "target": 4.5}},
]

CASH_RESERVE = 50000

# 憑證設定 (由 GitHub Actions 的 Secrets 提供)
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "") # FinMind API Token
