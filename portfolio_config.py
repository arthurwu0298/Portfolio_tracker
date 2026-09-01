# portfolio_config.py
import os

PORTFOLIO = [
    {"code": "2480", "name": "敦陽科", "market": "TWSE", "shares": 65000, "cost_per_share": 153.8, "valuation_method": "yield", "target_yields": {"cheap": 6.0, "fair": 5.0, "target": 4.0}},
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 35000, "cost_per_share": 0.0, "valuation_method": "pe"},
    {"code": "6146", "name": "耕興", "market": "TPEx", "shares": 0, "cost_per_share": 233.3, "valuation_method": "pe"},
    {"code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 100000, "cost_per_share": 40.0, "valuation_method": "pb"},
    {"code": "2884", "name": "玉山金", "market": "TWSE", "shares": 140000, "cost_per_share": 20.0, "valuation_method": "pb"},
    {"code": "2881", "name": "富邦金", "market": "TWSE", "shares": 140000, "cost_per_share": 28.5, "valuation_method": "pb"},
    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 100000, "cost_per_share": 100.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 4.0, "fair": 3.5, "target": 3.0}},
    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 130000, "cost_per_share": 23.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 6.5, "fair": 5.5, "target": 4.5}},
    {"code": "00919", "name": "群益台灣精選高息", "market": "TWSE", "shares": 130000, "cost_per_share": 23.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 6.5, "fair": 5.5, "target": 4.5}},
    {"code": "2597", "name": "潤弘", "market": "TWSE", "shares": 3200, "cost_per_share": 130.0, "valuation_method": "pe"}
    # --- 新增部位 (股數與成本預設為 0，請自行填入真實數據) ---
    {"code": "2408", "name": "南亞科", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pb"},
    {"code": "2344", "name": "華邦電", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pb"},
    {"code": "2451", "name": "創見", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "yield", "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
    {"code": "2812", "name": "台中銀", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pb"},
    {"code": "2330", "name": "台積電", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pe"},
    {"code": "2834", "name": "台企銀", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pb"},
    {"code": "2890", "name": "永豐金", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pb"},
    {"code": "5609", "name": "中菲行", "market": "TPEx", "shares": 0, "cost_per_share": 0.0, "valuation_method": "pe"},
    
    # --- 新增 ETF 部位 ---
    {"code": "0052", "name": "富邦科技", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 3.5, "fair": 3.0, "target": 2.0}},
    {"code": "0050", "name": "元大台灣50", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 4.0, "fair": 3.5, "target": 3.0}},
    {"code": "0056", "name": "元大高股息", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
]

CASH_RESERVE = 50000

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
