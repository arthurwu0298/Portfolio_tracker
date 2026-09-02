# portfolio_config.py
import os

PORTFOLIO = [
    {"code": "2480", "name": "敦陽科", "market": "TWSE", "shares": 650, "cost_per_share": 153.8,
     "valuation_method": "yield", "payout_ratio": 0.92,
     "target_yields": {"cheap": 6.0, "fair": 5.0, "target": 4.0}},

    {"code": "3130", "name": "一零四", "market": "TWSE", "shares": 350, "cost_per_share": 200.0,
     "valuation_method": "pe"},

    {"code": "6146", "name": "耕興", "market": "TPEx", "shares": 300, "cost_per_share": 233.3,
     "valuation_method": "pe"},

    # 金融股改用「去年現金配息率 x 今年預估EPS」推算現金殖利率法，取代淨值比法。
    # payout_ratio 為 2025年度實際現金股利/EPS(固定值，需等下次股利公告才會變動)。
    # 沒有設定 estimated_eps 時，程式會自動用 get_annualized_eps() 抓當年度已公布
    # 季報的EPS加總年化，每次新一季財報公布就會自動更新，不需要手動維護這個數字。
    {"code": "2886", "name": "兆豐金", "market": "TWSE", "shares": 1000, "cost_per_share": 40.0,
     "valuation_method": "yield", "payout_ratio": 0.74,
     "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0},
     "note": "改用殖利率法：配息率取自2025年度(現金1.75/EPS2.36≈74%)，預估EPS改為自動依季報年化，實際配息率仍待下次董事會正式公告更新"},

    {"code": "2884", "name": "玉山金", "market": "TWSE", "shares": 1400, "cost_per_share": 28.5,
     "valuation_method": "yield", "payout_ratio": 0.66,
     "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0},
     "note": "改用殖利率法：配息率取自2025年度(現金1.4/EPS2.12≈66%)，預估EPS改為自動依季報年化，實際配息率仍待下次董事會正式公告更新"},

    {"code": "2597", "name": "潤弘", "market": "TWSE", "shares": 1000, "cost_per_share": 130.0,
     "valuation_method": "pe"},

    {"code": "006208", "name": "富邦台50", "market": "TWSE", "shares": 1000, "cost_per_share": 100.0,
     "valuation_method": "etf_yield", "target_yields": {"cheap": 4.0, "fair": 3.5, "target": 3.0},
     "note": "殖利率法僅供參考；報酬主要來自台積電等權值股資本利得，殖利率壓縮不必然代表偏貴"},

    {"code": "00878", "name": "國泰永續高股息", "market": "TWSE", "shares": 1300, "cost_per_share": 23.0,
     "valuation_method": "etf_yield", "target_yields": {"cheap": 6.5, "fair": 5.5, "target": 4.5}},

    {"code": "2408", "name": "南亞科", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "yield", "payout_ratio": 0.70, "estimated_eps": 40.0,
     "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0},
     "note": "改用與創見相同的景氣財殖利率法：配息率取自2025年度(現金1.5/EPS2.13≈70%)。estimated_eps手動設為法人(Factset)2026年共識中位數約40元(而非自動年化)，因記憶體循環股獲利加速度極快，機械式年化上半年數字容易低估；想改用自動年化，把這個欄位刪掉或設成0即可。記憶體循環反轉時獲利與配息可能大幅回落，估值僅供參考"},

    {"code": "2344", "name": "華邦電", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "yield", "payout_ratio": 0.57, "estimated_eps": 21.0,
     "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0},
     "note": "改用與創見相同的景氣財殖利率法：配息率取自2025年度(現金0.5/EPS0.88≈57%)。estimated_eps手動設為法人(Factset)2026年共識中位數約21元(而非自動年化)，理由同南亞科；想改用自動年化，把這個欄位刪掉或設成0即可。記憶體循環反轉時獲利與配息可能大幅回落，估值僅供參考"},

    {"code": "2451", "name": "創見", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "yield", "payout_ratio": 0.90,
     "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0},
     "note": "本波為記憶體超級循環帶來的景氣財，非穩定配息型公司，股利波動風險較高"},

    {"code": "2812", "name": "台中銀", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "yield", "payout_ratio": 0.25,
     "target_yields": {"cheap": 3.0, "fair": 2.2, "target": 1.5},
     "note": "改用殖利率法：配息率取自2025年度(現金0.39/EPS1.53≈25%，偏好股票股利)，預估EPS改為自動依季報年化；先前涉及洗錢案件，法律/商譽風險未反映於本模型，估值僅供參考"},

    {"code": "2330", "name": "台積電", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "pe"},

    {"code": "2834", "name": "台企銀", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "yield", "payout_ratio": 0.24,
     "target_yields": {"cheap": 2.2, "fair": 1.5, "target": 1.0},
     "note": "改用殖利率法：配息率取自2025年度(現金0.3/EPS1.26≈24%，偏好股票股利)，預估EPS改為自動依季報年化"},

    {"code": "2890", "name": "永豐金", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "yield", "payout_ratio": 0.56,
     "target_yields": {"cheap": 5.0, "fair": 4.0, "target": 3.0},
     "note": "改用殖利率法：配息率取自2025年度(現金1.1/EPS1.97≈56%)，預估EPS改為自動依季報年化，已反映京城銀合併綜效帶動的獲利跳升"},

    {"code": "5609", "name": "中菲行", "market": "TPEx", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "pe"},

    {"code": "0052", "name": "富邦科技", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "etf_yield", "target_yields": {"cheap": 3.5, "fair": 3.0, "target": 2.0},
     "note": "殖利率法僅供參考；成分股偏科技成長股，報酬主要來自資本利得而非股利"},

    {"code": "0050", "name": "元大台灣50", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "etf_yield", "target_yields": {"cheap": 4.0, "fair": 3.5, "target": 3.0},
     "note": "殖利率法僅供參考；報酬主要來自台積電等權值股資本利得，殖利率壓縮不必然代表偏貴"},

    {"code": "0056", "name": "元大高股息", "market": "TWSE", "shares": 0, "cost_per_share": 0.0,
     "valuation_method": "etf_yield", "target_yields": {"cheap": 7.0, "fair": 6.0, "target": 5.0}},
]

CASH_RESERVE = 50000

# 估值百分位判斷門檻：現在的PE/PB落在近5年歷史分布的第幾百分位以上，
# 視為統計上的極端值，觸發「模型基期可能落後」的提醒與營收動能交叉驗證。
EXTREME_VALUATION_PERCENTILE = 95

# 交叉驗證用的營收年增率門檻：極端估值 + 營收年增率高於此門檻且持續加速，
# 才會被標記為「結構性重估」而非單純的情緒推升。
MOMENTUM_YOY_THRESHOLD = 20.0

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
