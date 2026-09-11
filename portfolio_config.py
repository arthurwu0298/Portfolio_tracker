# portfolio_config.py
import os

# ==============================================================================
# 🏛️ 金控四大分類原型規格定義 (Financial Holding Company Archetypes)
# ==============================================================================
FHC_ARCHETYPES = {
    "BANK_DOMINANT": {
        "description": "銀行型金控：以存放款利差與手續費為核心，獲利波動低、資本要求相對明確",
        "default_ke_range": [0.068, 0.075],
        "default_g_range": [0.015, 0.020],
        "default_book_value_policy": "reported",
        "confidence_ceiling": "A",
        "default_observation_quarters": 0
    },
    "INSURANCE_DOMINANT": {
        "description": "壽險型金控：資產負債具高利率與市場敏感性，需考慮 OCI 與資產重分類權重",
        "default_ke_range": [0.078, 0.088],
        "default_g_range": [0.018, 0.025],
        "default_book_value_policy": "blended",
        "confidence_ceiling": "A",
        "default_observation_quarters": 0
    },
    "TRANSITION_MA": {
        "description": "併購整合/過渡期金控：處於換股增資、股本膨脹或業務整併期，資料存在期別錯配",
        "default_ke_range": [0.075, 0.085],
        "default_g_range": [0.018, 0.025],
        "default_book_value_policy": "reported",
        "confidence_ceiling": "B",  # 整合完成前限制最高評級
        # 新淨值確認納入後，仍需觀察N季（91天/季）才升級到原型上限評級，
        # 避免「資料剛到位」被誤判成「整合風險已解除」
        "default_observation_quarters": 2
    },
    "MIXED_FHC": {
        "description": "綜合型金控：銀行、證券、創投多引擎，獲利與資本市場高度連動",
        "default_ke_range": [0.073, 0.082],
        "default_g_range": [0.018, 0.023],
        "default_book_value_policy": "reported",
        "confidence_ceiling": "A",
        "default_observation_quarters": 0
    }
}

# ==============================================================================
# 📊 投資組合標的配置
# ==============================================================================
PORTFOLIO = [
    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 1500, "cost_per_share": 10.0, "valuation_method": "pe"},

    # 🏛️ 兆豐金 (2886) - BANK_DOMINANT
    {
        "code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 2000, "cost_per_share": 30.0,
        "valuation": {
            "method": "rim",
            "archetype": "BANK_DOMINANT",
            "risk": {
                "ke": 0.070,
                "ke_range": [0.068, 0.075]
            },
            "growth": {
                "method": "manual_normalized",
                "g": 0.018,
                "g_range": [0.015, 0.020],
                "payout_ratio": 0.74,
                "g_reinvestment_efficiency": 0.71
            },
            "profitability": {
                "normalized_roe": 0.098,
                "roe_range": [0.093, 0.103]
            },
            "book_value": {
                "policy": "reported",
                "status": "confirmed"
            }
        }
    },

    # 🏦 玉山金 (2884) - TRANSITION_MA
    {
        "code": "2884", "name": "玉山金", "market": "TWSE", "shares": 21000, "cost_per_share": 28.5, "is_core": True,
        "valuation": {
            "method": "rim",
            "archetype": "TRANSITION_MA",
            "risk": {
                "ke": 0.078,
                "ke_range": [0.075, 0.083]
            },
            "growth": {
                "method": "manual_normalized",
                "g": 0.022,
                "g_range": [0.018, 0.025],
                "payout_ratio": 0.66,
                "g_reinvestment_efficiency": 0.48
            },
            "profitability": {
                "normalized_roe": 0.135,
                "roe_range": [0.125, 0.140]
            },
            "book_value": {
                "policy": "reported",
                "require_post_event": True,
                "effective_date": "2026-09-01",
                "status": "transitional"  # 過渡期：先以現行淨值計算並標記示警，新財報進入後自動升級
            }
        }
    },

    # 👑 富邦金 (2881) - INSURANCE_DOMINANT
    {
        "code": "2881", "name": "富邦金", "market": "TWSE", "shares": 100000, "cost_per_share": 50.0, "is_core": True,
        "valuation": {
            "method": "rim",
            "archetype": "INSURANCE_DOMINANT",
            "risk": {
                "ke": 0.082,
                "ke_range": [0.078, 0.088]
            },
            "growth": {
                "method": "manual_normalized",
                "g": 0.023,
                "g_range": [0.018, 0.025],
                "payout_ratio": 0.50,
                "g_reinvestment_efficiency": 0.33
            },
            "profitability": {
                # 2025 年報實際 ROE 12.51%（法說會揭露）。原假設 14.0% 偏樂觀，
                # 下修中樞並將區間下緣貼齊實際值；2026H1 獲利明顯回升，若動能延續可再上修。
                "normalized_roe": 0.140,
                "roe_range": [0.120, 0.145]
            },
            "book_value": {
                "policy": "blended",
                "adjusted_weight": 0.30,
                # 此係數為富邦金專屬校準值（參考其歷史財報口徑比值 109.3 / 83.7 估算），
                # 不會被其他 INSURANCE_DOMINANT 原型股票沿用；新增壽險型持股須各自校準。
                "adjustment_ratio": 1.306,
                "status": "confirmed"
            }
        }
    },

    {"code": "2597", "name": "潤弘", "market": "TWSE", "shares": 3200, "cost_per_share": 110.0, "valuation_method": "pe"},

    # 🤖 AI 伺服器與散熱族群
    {"code": "6669", "name": "緯穎", "market": "TWSE", "shares": 1000, "cost_per_share": 1800.0, "is_core": False, "valuation_method": "peg"},
    {"code": "3017", "name": "奇鋐", "market": "TWSE", "shares": 1000, "cost_per_share": 600.0, "is_core": False, "valuation_method": "peg"},
    {"code": "3324", "name": "雙鴻", "market": "TPEx", "shares": 1000, "cost_per_share": 600.0, "is_core": False, "valuation_method": "peg"},

    # 週期與記憶體族群（零成本設為 None 防呆；創見改用 pb 循環估值）
    {"code": "2408", "name": "南亞科", "market": "TWSE", "shares": 100000, "cost_per_share": None, "cost_basis_status": "unknown", "is_core": False, "valuation_method": "peg"},
    {"code": "2344", "name": "華邦電", "market": "TWSE", "shares": 100000, "cost_per_share": None, "cost_basis_status": "unknown", "is_core": False, "valuation_method": "peg"},
    {"code": "2451", "name": "創見", "market": "TWSE", "shares": 1200, "cost_per_share": 150.0, "is_core": False, "valuation_method": "pb"},

    # 🏦 台中銀 (2812) - BANK_DOMINANT
    # FYI: 2025/6/19 董事會決議現金增資1億股，屬股本膨脹事件，
    # 但 ROE 走勢穩定（2024: 10.46% → 2025 年化約 10.49%），未觀察到明顯稀釋衝擊，
    # 暫不需比照玉山金/永豐金改列 TRANSITION_MA；後續增資若影響獲利可再重新評估。
    {
        "code": "2812", "name": "台中銀", "market": "TWSE", "shares": 40000, "cost_per_share": 16.0,
        "valuation": {
            "method": "rim",
            "archetype": "BANK_DOMINANT",
            "risk": {"ke": 0.072, "ke_range": [0.068, 0.076]},
            "growth": {"method": "manual_normalized", "g": 0.018, "g_range": [0.015, 0.020], "payout_ratio": 0.25},
            "profitability": {"normalized_roe": 0.105, "roe_range": [0.098, 0.112]},
            "book_value": {"policy": "reported", "status": "confirmed"}
        }
    },

    {"code": "2330", "name": "台積電", "market": "TWSE", "shares": 30, "cost_per_share": 1900.0, "valuation_method": "peg"},

    # 🏛️ 台企銀 (2834) - BANK_DOMINANT
    {
        "code": "2834", "name": "台企銀", "market": "TWSE", "shares": 8000, "cost_per_share": 14, "cost_basis_status": "unknown",
        "valuation": {
            "method": "rim",
            "archetype": "BANK_DOMINANT",
            "risk": {"ke": 0.072, "ke_range": [0.068, 0.076]},
            "growth": {"method": "manual_normalized", "g": 0.016, "g_range": [0.012, 0.020], "payout_ratio": 0.24},
            "profitability": {"normalized_roe": 0.092, "roe_range": [0.085, 0.098]},
            "book_value": {"policy": "reported", "status": "confirmed"}
        }
    },

    # 📈 永豐金 (2890) - TRANSITION_MA
    {
        "code": "2890", "name": "永豐金", "market": "TWSE", "shares": 2000, "cost_per_share": 20.0,
        "valuation": {
            "method": "rim",
            "archetype": "TRANSITION_MA",
            "risk": {
                "ke": 0.076,
                "ke_range": [0.073, 0.082]
            },
            "growth": {
                "method": "manual_normalized",
                "g": 0.022,
                "g_range": [0.018, 0.025],
                "payout_ratio": 0.56,
                "g_reinvestment_efficiency": 0.37
            },
            "profitability": {
                # 2026/1/8 自結公告年化 ROE 11.5%（EPS 1.97元）。原假設 13.5% 偏樂觀，
                # 下修中樞至實際值附近；京城銀行併入綜效若逐步顯現可再評估上修。
                "normalized_roe": 0.115,
                "roe_range": [0.105, 0.128]
            },
            "book_value": {
                "policy": "reported",
                "status": "confirmed"
            },
            "ma_risk": {
                "enabled": True,
                "discount": 0.05,
                "until": "2027-03-31"
            }
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