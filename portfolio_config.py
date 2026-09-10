# portfolio_config.py
import os

PORTFOLIO = [
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 1500, "cost_per_share": 10.0, "valuation_method": "pe"},
    
    # 🏛️ 兆豐金：公股防禦型（低資金成本、成熟保守成長、高配息穩定性）
    {
        "code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 2000, "cost_per_share": 30.0,
        "valuation": {
            "method": "rim",
            "risk": {"ke": 0.070, "ke_range": [0.068, 0.075]},
            "growth": {
                "method": "manual_normalized", "g": 0.018, "g_range": [0.015, 0.020],
                "payout_ratio": 0.74, "g_reinvestment_efficiency": 0.71
            },
            "profitability": {"normalized_roe": 0.098, "roe_range": [0.093, 0.103]},
            "book_value": {"policy": "reported", "status": "confirmed"}
        }
    },
    
    # 🏦 玉山金：併購壽險轉型型（先以現行淨值估算並標記過渡期，新財報公佈時自動無縫升級）
    {
        "code": "2884", "name": "玉山金", "market": "TWSE", "shares": 21000, "cost_per_share": 28.5, "is_core": True,
        "valuation": {
            "method": "rim",
            "risk": {"ke": 0.078, "ke_range": [0.075, 0.083]},
            "growth": {
                "method": "manual_normalized", "g": 0.022, "g_range": [0.018, 0.025],
                "payout_ratio": 0.66, "g_reinvestment_efficiency": 0.48
            },
            "profitability": {"normalized_roe": 0.135, "roe_range": [0.125, 0.140]},
            "book_value": {
                "policy": "reported",
                "require_post_event": True,
                "effective_date": "2026-09-01",
                "status": "transitional"
            }
        }
    },

    # 👑 富邦金：壽險龍頭（Blended BPS 考慮資產重分類，平滑單期景氣峰值至 14% 正常化 ROE）
    {
        "code": "2881", "name": "富邦金", "market": "TWSE", "shares": 100000, "cost_per_share": 50.0, "is_core": True,
        "valuation": {
            "method": "rim",
            "risk": {"ke": 0.082, "ke_range": [0.078, 0.088]},
            "growth": {
                "method": "manual_normalized", "g": 0.023, "g_range": [0.018, 0.025],
                "payout_ratio": 0.50, "g_reinvestment_efficiency": 0.33
            },
            "profitability": {"normalized_roe": 0.140, "roe_range": [0.125, 0.150]},
            "book_value": {"policy": "blended", "adjusted_weight": 0.30, "status": "confirmed"}
        }
    },

    {"code": "2597", "name": "潤弘", "market": "TWSE", "shares": 3200, "cost_per_share": 110.0, "valuation_method": "pe"},

    # 🤖 AI 伺服器與散熱族群
    {"code": "6669", "name": "緯穎", "market": "TWSE", "shares": 1000, "cost_per_share": 1800.0, "is_core": False, "valuation_method": "peg"},
    {"code": "3017", "name": "奇鋐", "market": "TWSE", "shares": 1000, "cost_per_share": 600.0, "is_core": False, "valuation_method": "peg"},
    {"code": "3324", "name": "雙鴻", "market": "TPEx", "shares": 1000, "cost_per_share": 600.0, "is_core": False, "valuation_method": "peg"},

    # 週期與記憶體族群（零成本改為 None 杜絕除以零；創見改採 pb 法）
    {"code": "2408", "name": "南亞科", "market": "TWSE", "shares": 100000, "cost_per_share": None, "cost_basis_status": "unknown", "is_core": False, "valuation_method": "peg"},
    {"code": "2344", "name": "華邦電", "market": "TWSE", "shares": 100000, "cost_per_share": None, "cost_basis_status": "unknown", "is_core": False, "valuation_method": "peg"},
    {"code": "2451", "name": "創見", "market": "TWSE", "shares": 1200, "cost_per_share": 150.0, "is_core": False, "valuation_method": "pb"},

    {"code": "2812", "name": "台中銀", "market": "TWSE", "shares": 40000, "cost_per_share": 16.0, "valuation_method": "rim", "payout_ratio": 0.25},
    {"code": "2330", "name": "台積電", "market": "TWSE", "shares": 30, "cost_per_share": 1900.0, "valuation_method": "peg"},
    {"code": "2834", "name": "台企銀", "market": "TWSE", "shares": 8000, "cost_per_share": None, "cost_basis_status": "unknown", "valuation_method": "rim", "payout_ratio": 0.24},

    # 📈 永豐金：核心銀行穩健 + 證券併購題材（設定 5% 整合期風險折價至 2027-03-31）
    {
        "code": "2890", "name": "永豐金", "market": "TWSE", "shares": 2000, "cost_per_share": 20.0,
        "valuation": {
            "method": "rim",
            "risk": {"ke": 0.076, "ke_range": [0.073, 0.082]},
            "growth": {
                "method": "manual_normalized", "g": 0.022, "g_range": [0.018, 0.025],
                "payout_ratio": 0.56, "g_reinvestment_efficiency": 0.37
            },
            "profitability": {"normalized_roe": 0.135, "roe_range": [0.125, 0.145]},
            "book_value": {"policy": "reported", "status": "confirmed"},
            "ma_risk": {"enabled": True, "discount": 0.05, "until": "2027-03-31"}
        }
    },

    {"code": "5609", "name": "中菲行", "market": "TPEx", "shares": 1000, "cost_per_share": 97.0, "valuation_method": "pe"},

    # 市值型 ETF
    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 5000, "cost_per_share": 100.0, "valuation_method": "trend"},
    {"code": "0052", "name": "富邦科技", "market": "TWSE", "shares": 1500, "cost_per_share": 30.0, "valuation_method": "trend"},
    {"code": "0050", "name": "元大台灣50", "market": "TWSE", "shares": 5000, "cost_per_share": 20.0, "valuation_method": "trend"},

    # 高股息 ETF
    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 32000, "cost_per_share": 23.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 6.5, "fair": 5.5, "target": 4.5}},
    {"code": "0056", "name": "元大高股息", "market": "TWSE", "shares": 2000, "cost_per_share": 20.0, "valuation_method": "etf_yield", "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
]

CASH_RESERVE = 50000
EXTREME_VALUATION_PERCENTILE = 95
MOMENTUM_YOY_THRESHOLD = 20.0

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")