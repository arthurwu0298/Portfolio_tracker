# portfolio_config.py
import os

PORTFOLIO = [
    {"code": "2480", "name": "敦陽科", "market": "TWSE", "shares": 650, "cost_per_share": 153.8, "valuation_method": "yield", "payout_ratio": 0.92, "target_yields": {"cheap": 6.0, "fair": 5.0, "target": 4.0}},
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 1500, "cost_per_share": 10.0, "valuation_method": "pe"},
    {"code": "6146", "name": "耕興", "market": "TPEx", "shares": 300, "cost_per_share": 233.3, "valuation_method": "pe"},
    {"code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 2000, "cost_per_share": 30.0, "valuation_method": "yield", "payout_ratio": 0.74, "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0}},
    {"code": "2884", "name": "玉山金", "market": "TWSE", "shares": 21000, "cost_per_share": 28.5,"is_core": True , "valuation_method": "yield", "payout_ratio": 0.66, "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0}},
    # ⚠️ 【修正】富邦金：已調整為佔位數字，請依據真實對帳單將 60.0 與 1000 更改為正確的成本與股數
    {"code": "2881", "name": "富邦金", "market": "TWSE", "shares": 100000, "cost_per_share": 50.0, "is_core": True ,"valuation_method": "yield", "payout_ratio": 0.5, "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0}},
    {"code": "2597", "name": "潤弘", "market": "TWSE", "shares": 3200, "cost_per_share": 110.0, "valuation_method": "pe"},
    
    # ⚠️ 【修正】南亞科、華邦電、創見改回機械式年化預估 (yield)
    {"code": "2408", "name": "南亞科", "market": "TWSE", "shares": 0, "cost_per_share": 0.0, "is_core": True ,"valuation_method": "yield", "payout_ratio": 0.70, "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
    {"code": "2344", "name": "華邦電", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,"is_core": True , "valuation_method": "yield", "payout_ratio": 0.57, "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
    {"code": "2451", "name": "創見", "market": "TWSE", "shares": 1200, "cost_per_share": 150.0, "is_core": True ,"valuation_method": "yield", "payout_ratio": 0.90, "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
    
    {"code": "2812", "name": "台中銀", "market": "TWSE", "shares": 40000, "cost_per_share": 16.0, "valuation_method": "yield", "payout_ratio": 0.25, "target_yields": {"cheap": 3.0, "fair": 2.2, "target": 1.5}},
    {"code": "2330", "name": "台積電", "market": "TWSE", "shares": 30, "cost_per_share": 1900.0, "valuation_method": "pe"},
    {"code": "2834", "name": "台企銀", "market": "TWSE", "shares": 8000, "cost_per_share": 0.0, "valuation_method": "yield", "payout_ratio": 0.24, "target_yields": {"cheap": 2.2, "fair": 1.5, "target": 1.0}},
    {"code": "2890", "name": "永豐金", "market": "TWSE", "shares": 2000, "cost_per_share": 20.0, "valuation_method": "yield", "payout_ratio": 0.56, "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0}},
    {"code": "5609", "name": "中菲行", "market": "TPEx", "shares": 1000, "cost_per_share": 97.0, "valuation_method": "pe"},
    
    # ⚠️ 【修正】市值/科技型 ETF 切換為趨勢乖離法
    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 5000, "cost_per_share": 100.0, "valuation_method": "trend"},
    {"code": "0052", "name": "富邦科技", "market": "TWSE", "shares": 1500, "cost_per_share": 30.0, "valuation_method": "trend"},
    {"code": "0050", "name": "元大台灣50", "market": "TWSE", "shares": 5000, "cost_per_share": 20.0, "valuation_method": "trend"},

    # ⚠️ 【維持】高股息 ETF 仍使用歷史殖利率法
    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 32000, "cost_per_share": 23.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 6.5, "fair": 5.5, "target": 4.5}},
    {"code": "0056", "name": "元大高股息", "market": "TWSE", "shares": 2000, "cost_per_share": 20.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
]

CASH_RESERVE = 50000
EXTREME_VALUATION_PERCENTILE = 95
MOMENTUM_YOY_THRESHOLD = 20.0

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
