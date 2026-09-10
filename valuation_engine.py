# valuation_engine.py
import io
import math
import requests
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class DCFResult:
    enterprise_value: float
    equity_value: float
    value_per_share: float
    terminal_value_ratio: float
    yearly_details: List[Dict]
    warnings: List[str]

class FinMindValuationEngine:
    def __init__(self, token="", db_file="portfolio_history.db", cache_max_age_days=7):
        self.token = token
        self.base_url = "https://api.finmindtrade.com/api/v4/data"
        self.db_file = db_file
        self.cache_max_age_days = cache_max_age_days
        self._init_cache_table()

    def _init_cache_table(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS finmind_cache (stock_id TEXT, dataset TEXT, fetched_at TEXT, data_json TEXT, PRIMARY KEY (stock_id, dataset))''')
        conn.commit()
        conn.close()

    def _read_cache(self, dataset, data_id):
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT fetched_at, data_json FROM finmind_cache WHERE stock_id = ? AND dataset = ?", (data_id, dataset))
            row = cursor.fetchone()
            conn.close()
            if not row: return None
            fetched_at, data_json = row
            if datetime.now() - datetime.fromisoformat(fetched_at) > timedelta(days=self.cache_max_age_days): return None
            df = pd.read_json(io.StringIO(data_json))
            return df if not df.empty else None
        except: return None

    def _write_cache(self, dataset, data_id, df):
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''INSERT OR REPLACE INTO finmind_cache (stock_id, dataset, fetched_at, data_json) VALUES (?, ?, ?, ?)''', (data_id, dataset, datetime.now().isoformat(), df.to_json()))
            conn.commit()
            conn.close()
        except: pass

    def _fetch_data(self, dataset, data_id, years_back=5, use_cache=True):
        if use_cache:
            cached = self._read_cache(dataset, data_id)
            if cached is not None: return cached
        start_date = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y-%m-%d")
        params = {"dataset": dataset, "data_id": data_id, "start_date": start_date}
        if self.token: params["token"] = self.token
        try:
            res = requests.get(self.base_url, params=params, timeout=15)
            if res.status_code == 200:
                data = res.json().get("data", [])
                df = pd.DataFrame(data)
                if use_cache and not df.empty: self._write_cache(dataset, data_id, df)
                return df
        except: pass
        return pd.DataFrame()

    def get_recent_dividend(self, stock_id):
        df = self._fetch_data("TaiwanStockDividendResult", stock_id, years_back=2)
        if df.empty or "stock_and_cache_dividend" not in df.columns: return 0.0
        try:
            df['date'] = pd.to_datetime(df['date'])
            one_yr_ago = pd.Timestamp.now() - pd.DateOffset(years=1)
            return df[df['date'] >= one_yr_ago]["stock_and_cache_dividend"].sum()
        except: return 0.0

    def calc_pe_valuation(self, stock_id, current_price, current_pe):
        if current_price <= 0 or current_pe <= 0: return 0, 0, 0, None
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PER" not in df.columns: return 0, 0, 0, None
        fwd_eps, _ = self.estimate_forward_eps(stock_id)
        if fwd_eps <= 0: return 0, 0, 0, None
        valid_pe = df[df["PER"] > 0]["PER"]
        if valid_pe.empty: return 0, 0, 0, None
        pe_20, pe_50, pe_80 = np.percentile(valid_pe, 20), np.percentile(valid_pe, 50), np.percentile(valid_pe, 80)
        return round(fwd_eps * pe_20, 1), round(fwd_eps * pe_50, 1), round(fwd_eps * pe_80, 1), None

    def calc_pb_valuation(self, stock_id, current_price, current_pb):
        if current_price <= 0 or current_pb <= 0: return 0, 0, 0, None
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PBR" not in df.columns: return 0, 0, 0, None
        current_bvps = current_price / current_pb
        valid_pb = df[df["PBR"] > 0]["PBR"]
        if valid_pb.empty: return 0, 0, 0, None
        pb_20, pb_50, pb_80 = np.percentile(valid_pb, 20), np.percentile(valid_pb, 50), np.percentile(valid_pb, 80)
        return round(current_bvps * pb_20, 1), round(current_bvps * pb_50, 1), round(current_bvps * pb_80, 1), None

    def calc_yield_percentile_bounds(self, stock_id):
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "dividend_yield" not in df.columns: return 0.0, 0.0, 0.0
        try:
            valid_yields = df[df["dividend_yield"] > 0]["dividend_yield"]
            if valid_yields.empty: return 0.0, 0.0, 0.0
            return round(np.percentile(valid_yields, 80), 2), round(np.percentile(valid_yields, 50), 2), round(np.percentile(valid_yields, 20), 2)
        except: return 0.0, 0.0, 0.0

    def calc_price_trend_valuation(self, stock_id, current_price):
        df = self._fetch_data("TaiwanStockPrice", stock_id, years_back=5)
        if df.empty or "close" not in df.columns: return 0, 0, 0, 0.0, None
        try:
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            df["ma200"] = df["close"].rolling(window=200).mean()
            df["deviation"] = (df["close"] - df["ma200"]) / df["ma200"] * 100
            df = df.dropna(subset=["deviation"])
            if df.empty: return 0, 0, 0, 0.0, None
            current_ma200 = df["ma200"].iloc[-1]
            if current_ma200 <= 0: return 0, 0, 0, 0.0, None
            p20, p50, p80 = np.percentile(df["deviation"], 20), np.percentile(df["deviation"], 50), np.percentile(df["deviation"], 80)
            return round(current_ma200 * (1 + p20 / 100), 1), round(current_ma200 * (1 + p50 / 100), 1), round(current_ma200 * (1 + p80 / 100), 1), 0.0, None
        except: return 0, 0, 0, 0.0, None

    def _get_profile(self, stock_id):
        s = str(stock_id)
        if s.startswith('28') or s.startswith('58'): return {'key': 'financial', 'is_cyclical': False}
        if s in ['2408', '2344', '2451', '2603', '2609', '2002']: return {'key': 'cyclical', 'is_cyclical': True}
        if s.startswith('23') or s in ['2480', '6146']: return {'key': 'tech', 'is_cyclical': False}
        return {'key': 'general', 'is_cyclical': False}

    def estimate_forward_eps(self, stock_id):
        fs_df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=4)
        mr_df = self._fetch_data("TaiwanStockMonthRevenue", stock_id, years_back=2)
        
        if fs_df.empty: return 0.0, 0.0
        
        def get_type_series(t_list):
            df = fs_df[fs_df["type"].isin(t_list)].copy()
            if df.empty: return pd.DataFrame()
            df['date'] = pd.to_datetime(df['date'])
            return df.sort_values('date')

        eps_data = get_type_series(['EPS', 'BasicEarningsLossPerShare'])
        rev_data = get_type_series(['Revenue', 'OperatingRevenue', 'NetRevenue'])
        op_data = get_type_series(['OperatingIncome', 'OperatingProfit'])
        tax_data = get_type_series(['IncomeTaxExpense', 'TaxExpense'])
        pretax_data = get_type_series(['IncomeBeforeTax', 'ProfitBeforeTax'])
        net_data = get_type_series(['IncomeAfterTaxes', 'NetIncome'])
        
        ttm_eps, eps_yoy, eps_ytd_val, eps_ytd_periods = 0.0, None, 0.0, 0
        eps_history = []
        if not eps_data.empty:
            eps_history = eps_data['value'].tolist()[-20:] 
            last_8 = eps_data.tail(8)
            if len(last_8) >= 4:
                ttm_eps = last_8.tail(4)['value'].sum()
                if len(last_8) == 8:
                    prev_ttm = last_8.head(4)['value'].sum()
                    if prev_ttm != 0: eps_yoy = (ttm_eps - prev_ttm) / abs(prev_ttm)
            
            curr_year = datetime.now().year
            ytd_rows = eps_data[eps_data['date'].dt.year == curr_year]
            if ytd_rows.empty: 
                curr_year -= 1
                ytd_rows = eps_data[eps_data['date'].dt.year == curr_year]
            eps_ytd_periods = len(ytd_rows)
            eps_ytd_val = ytd_rows['value'].sum()

        rev_ttm_yoy, cagr, rev_ttm = None, None, 0.0
        if not rev_data.empty and len(rev_data) >= 4:
            last_8_rev = rev_data.tail(8)
            rev_ttm = last_8_rev.tail(4)['value'].sum()
            if len(last_8_rev) == 8:
                prev_rev_ttm = last_8_rev.head(4)['value'].sum()
                if prev_rev_ttm != 0: rev_ttm_yoy = (rev_ttm - prev_rev_ttm) / abs(prev_rev_ttm)
            if len(rev_data) >= 16:
                r0 = rev_data.tail(4)['value'].sum()
                r3 = rev_data.iloc[-16:-12]['value'].sum()
                if r0 > 0 and r3 > 0: cagr = (r0 / r3) ** (1/3) - 1

        mr_ytd_yoy, est_full_rev = None, None
        if not mr_df.empty and 'revenue' in mr_df.columns:
            mr_df['date'] = pd.to_datetime(mr_df['date'])
            mr_df = mr_df.sort_values('date')
            cur_y = mr_df['date'].dt.year.max()
            cur_rows = mr_df[mr_df['date'].dt.year == cur_y]
            latest_m = cur_rows['date'].dt.month.max()
            if latest_m:
                cur_ytd = cur_rows[cur_rows['date'].dt.month <= latest_m]['revenue'].sum()
                prev_ytd = mr_df[(mr_df['date'].dt.year == cur_y - 1) & (mr_df['date'].dt.month <= latest_m)]['revenue'].sum()
                if prev_ytd > 0:
                    mr_ytd_yoy = (cur_ytd - prev_ytd) / prev_ytd
                    prev_remain = mr_df[(mr_df['date'].dt.year == cur_y - 1) & (mr_df['date'].dt.month > latest_m)]['revenue'].sum()
                    est_full_rev = cur_ytd + prev_remain * (1 + mr_ytd_yoy)

        purified_eps, net_margin = ttm_eps, 0.0
        if rev_ttm > 0 and not net_data.empty:
            ni4 = net_data.tail(4)['value'].sum()
            net_margin = ni4 / rev_ttm
            if not op_data.empty and not pretax_data.empty and not tax_data.empty:
                op4 = op_data.tail(4)['value'].sum()
                pt4 = pretax_data.tail(4)['value'].sum()
                tax4 = tax_data.tail(4)['value'].sum()
                real_tax = min(0.35, max(0.0, tax4/pt4)) if pt4 > 0 else 0.20
                nopat = op4 * (1 - real_tax)
                shares_out = ni4 / ttm_eps if ttm_eps != 0 else 1
                if shares_out != 0: purified_eps = nopat / shares_out

        candidates = []
        if eps_yoy is not None: candidates.append((eps_yoy, 0.50))
        if mr_ytd_yoy is not None: candidates.append((mr_ytd_yoy, 0.45))
        if rev_ttm_yoy is not None: candidates.append((rev_ttm_yoy, 0.25))
        if cagr is not None: candidates.append((cagr, 0.15))
        
        raw_g = 0.05
        if candidates:
            ws = sum(w for v, w in candidates)
            raw_g = sum(v * w for v, w in candidates) / ws if ws > 0 else 0.05
            
        profile = self._get_profile(stock_id)
        dol = 1.3 if profile['key'] in ['tech', 'hardware'] else (1.1 if profile['key'] in ['consumer', 'utility'] else 1.0)
        leveraged_g = raw_g * dol
        
        cap = 0.35 if profile['key'] in ['tech', 'healthcare'] else (0.12 if profile['key'] == 'utility' else 0.25)
        floor = -0.30 if profile['is_cyclical'] else -0.25
        g = max(floor, min(cap, leveraged_g))

        base_eps = ttm_eps
        if profile['is_cyclical'] and ttm_eps > 0 and len(eps_history) >= 8:
            annuals = [sum(eps_history[i:i+4]) for i in range(0, len(eps_history)-3, 4) if sum(eps_history[i:i+4]) > 0]
            if len(annuals) >= 3:
                mean_eps = sum(annuals) / len(annuals)
                if ttm_eps > mean_eps * 1.5:
                    base_eps = mean_eps

        eps_est = base_eps * (1 + g) if base_eps > 0 else 0
        
        if eps_ytd_val > 0 and eps_ytd_periods > 0 and ttm_eps > 0:
            prev_remain = max(0, ttm_eps - eps_ytd_val)
            eps_est = eps_ytd_val + prev_remain * (1 + g)
        elif est_full_rev and net_margin > 0 and rev_ttm > 0:
            core_eps = purified_eps if purified_eps > 0 else ttm_eps
            eps_rev_ratio = core_eps / rev_ttm
            fwd_eps_from_rev = eps_rev_ratio * est_full_rev
            if ttm_eps <= 0 and fwd_eps_from_rev > 0:
                eps_est = fwd_eps_from_rev
            elif ttm_eps > 0 and abs(fwd_eps_from_rev - ttm_eps) / ttm_eps <= 0.5:
                eps_est = fwd_eps_from_rev

        if ttm_eps > 0:
            eps_est = max(ttm_eps * 0.3, min(eps_est, max(ttm_eps * 1.8, ttm_eps + 3)))
        else:
            eps_est = min(eps_est, 3.0)

        if eps_est <= 0: return 0.0, 0.0
        return eps_est, g

    def calc_ddm_valuation(self, stock_id, current_price, payout_ratio):
        if current_price <= 0 or payout_ratio <= 0: return 0, 0, 0, None
        fwd_eps, g_S = self.estimate_forward_eps(stock_id)
        div_total = self.get_recent_dividend(stock_id)
        
        ttm_eps = fwd_eps / (1 + g_S) if g_S != -1 else 0
        D0 = div_total if div_total > 0 else (ttm_eps * payout_ratio)
        if D0 <= 0: return 0, 0, 0, None

        g_L = 0.02  
        profile = self._get_profile(stock_id)
        cap = 0.80 if profile['is_cyclical'] else 0.35
        g_S = max(-0.25, min(cap, g_S)) 
        
        H = 2.5 
        k_cheap, k_fair, k_exp = 0.075, 0.060, 0.045
        
        if g_L >= k_exp - 0.015:
            shift = g_L - (k_exp - 0.015)
            k_cheap += shift; k_fair += shift; k_exp += shift

        numerator = D0 * (1 + g_L) + D0 * H * (g_S - g_L)
        if numerator <= 0: return 0, 0, 0, None
             
        return round(numerator / (k_cheap - g_L), 1), round(numerator / (k_fair - g_L), 1), round(numerator / (k_exp - g_L), 1), None

    def calc_graham_number(self, stock_id, current_price, current_pb):
        if current_price <= 0 or current_pb <= 0: return 0.0
        eps, _ = self.estimate_forward_eps(stock_id)
        bvps = current_price / current_pb
        if eps > 0 and bvps > 0: return round(math.sqrt(22.5 * eps * bvps), 1)
        return 0.0

    def _get_3yr_avg_roe(self, stock_id):
        fs_df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=4)
        bs_df = self._fetch_data("TaiwanStockBalanceSheet", stock_id, years_back=4)
        
        if fs_df.empty or bs_df.empty: return 0.0 
        
        ni_data = fs_df[fs_df["type"].str.contains('NetIncome|ProfitLoss|淨利|淨損', case=False, na=False)].copy()
        eq_data = bs_df[bs_df["type"].str.contains('Equity|權益', case=False, na=False)].copy()
        
        if ni_data.empty or eq_data.empty: return 0.0 
        
        ni_data['date'] = pd.to_datetime(ni_data['date'])
        eq_data['date'] = pd.to_datetime(eq_data['date'])
        ni_data = ni_data.sort_values(['date', 'value']).drop_duplicates(subset=['date'], keep='last')
        eq_data = eq_data.sort_values(['date', 'value']).drop_duplicates(subset=['date'], keep='last')
        
        last_12_ni = ni_data.tail(12)
        last_12_eq = eq_data.tail(12)
        
        roes = []
        for i in range(3):
            ni_yr = last_12_ni.iloc[-(i*4+4):-i*4] if i > 0 else last_12_ni.iloc[-4:]
            eq_yr = last_12_eq.iloc[-(i*4+4):-i*4] if i > 0 else last_12_eq.iloc[-4:]
            if not ni_yr.empty and not eq_yr.empty:
                ni_sum = ni_yr['value'].sum()
                eq_avg = eq_yr['value'].mean()
                if eq_avg > 0: roes.append(ni_sum / eq_avg)
        
        if not roes: return 0.0
        
        weights = [0.5, 0.3, 0.2][:len(roes)]
        weight_sum = sum(weights)
        avg_roe = sum(r * w for r, w in zip(roes, weights)) / weight_sum
        
        return max(0.01, min(avg_roe, 0.25))

    # ==============================================================
    # 🚀 四層資料驅動超額報酬模型 (RIM) - 真情境矩陣與隱含 ROE 引擎
    # ==============================================================
    def calc_residual_income_valuation(self, stock_id: str, current_price: float, current_pb: float, val_cfg: dict = None):
        if current_price <= 0: return 0, 0, 0, None
        val_cfg = val_cfg or {}
        bv_cfg = val_cfg.get("book_value", {})

        # 1. 抓取最新淨值與資料日期
        latest_bps_date = None
        df_per = self._fetch_data("TaiwanStockPER", stock_id, years_back=1)
        if not df_per.empty and "PBR" in df_per.columns:
            valid_rows = df_per[df_per["PBR"] > 0].sort_values("date")
            if not valid_rows.empty:
                current_pb = valid_rows.iloc[-1]["PBR"]
                latest_bps_date = str(valid_rows.iloc[-1].get("date", ""))[:10]

        if current_pb <= 0: return 0, 0, 0, None
        reported_bps = current_price / current_pb

        # 2. 動態檢驗事件生效日（如 2026-09-01 玉山金合併）
        is_interim = False
        eff_date = bv_cfg.get("effective_date")
        if bv_cfg.get("require_post_event") and eff_date:
            if not latest_bps_date or latest_bps_date < eff_date:
                is_interim = True
            else:
                bv_cfg["status"] = "confirmed"

        # 淨值口徑處理（富邦金 blended 政策）
        policy = bv_cfg.get("policy", "reported")
        if policy == "blended":
            adjusted_weight = bv_cfg.get("adjusted_weight", 0.3)
            adjusted_bps = reported_bps * 1.306
            valuation_bps = (reported_bps * (1 - adjusted_weight)) + (adjusted_bps * adjusted_weight)
        else:
            valuation_bps = reported_bps

        # 3. 讀取三維情境參數
        risk_cfg = val_cfg.get("risk", {})
        growth_cfg = val_cfg.get("growth", {})
        profit_cfg = val_cfg.get("profitability", {})

        ke_fair = risk_cfg.get("ke", 0.075)
        ke_low, ke_high = risk_cfg.get("ke_range", [ke_fair - 0.005, ke_fair + 0.005])

        g_fair = growth_cfg.get("g", 0.020)
        g_low, g_high = growth_cfg.get("g_range", [g_fair - 0.003, g_fair + 0.003])

        # 正常化 ROE（未設定則以三年歷史平滑均值回退）
        roe_fair = profit_cfg.get("normalized_roe", self._get_3yr_avg_roe(stock_id) or 0.10)
        roe_low, roe_high = profit_cfg.get("roe_range", [roe_fair - 0.01, roe_fair + 0.01])

        # Target P/B = (ROE - g) / (Ke - g)
        def calc_pb(r, k, g_val):
            if k <= g_val: return 1.0
            return max(0.6, (r - g_val) / (k - g_val))

        pb_bear = calc_pb(roe_low, ke_high, g_low)   # 悲觀：低 ROE + 高 Ke + 低 g
        pb_base = calc_pb(roe_fair, ke_fair, g_fair) # 基準：正常 ROE + 基準 Ke + 基準 g
        pb_bull = calc_pb(roe_high, ke_low, g_high)  # 樂觀：高 ROE + 低 Ke + 高 g

        cheap_value = valuation_bps * pb_bear
        base_fair = valuation_bps * pb_base
        target_value = valuation_bps * pb_bull

        # 4. 併購整合風險修正 (永豐金控京城銀整合期折價)
        ma_cfg = val_cfg.get("ma_risk", {})
        ma_discount = 0.0
        if ma_cfg.get("enabled", False):
            if datetime.now().strftime("%Y-%m-%d") <= ma_cfg.get("until", "2099-12-31"):
                ma_discount = ma_cfg.get("discount", 0.05)

        final_cheap = round(cheap_value * (1.0 - ma_discount), 1)
        final_fair = round(base_fair * (1.0 - ma_discount), 1)
        final_target = round(target_value * (1.0 - ma_discount), 1)

        # 5. 市場隱含長期 ROE 照妖鏡: Implied ROE = (Current P/B) * (Ke - g) + g
        curr_actual_pb = current_price / valuation_bps if valuation_bps > 0 else current_pb
        implied_roe = (curr_actual_pb * (ke_fair - g_fair)) + g_fair
        implied_roe_pct = round(implied_roe * 100, 1)

        return final_cheap, final_fair, final_target, {
            "valuation_bps": round(valuation_bps, 2),
            "pb_base": round(pb_base, 2),
            "implied_roe": f"{implied_roe_pct}% (基準差:{round((implied_roe - roe_fair)*100, 1):+}%)",
            "confidence": "C" if is_interim else "A",
            "is_interim": is_interim,
            "bps_date_used": latest_bps_date or "現行"
        }

    def calc_peg_valuation(self, stock_id, current_price):
        if current_price <= 0: return 0, 0, 0, None
        fwd_eps, g = self.estimate_forward_eps(stock_id)
        if fwd_eps <= 0 or g <= 0.05: return 0, 0, 0, None
            
        G = g * 100
        G = max(10, min(50, G)) 
        
        eps_cons = fwd_eps * 0.85
        pe_cheap = max(10, G * 0.8) * 0.8
        cheap_price = round(eps_cons * pe_cheap, 1)
        
        eps_fair = fwd_eps
        pe_fair = G * 1.2
        fair_price = round(eps_fair * pe_fair, 1)
        
        eps_opt = fwd_eps * 1.15
        pe_exp = min(60, G * 1.2) * 1.6
        exp_price = round(eps_opt * pe_exp, 1)
        
        return cheap_price, fair_price, exp_price, None

    def _dedupe_by_date_maxvalue(self, df, subset_cols=('date',)):
        if df.empty: return df
        cols = list(subset_cols)
        return df.sort_values(cols + ['value']).drop_duplicates(subset=cols, keep='last')

    def _get_nopat_and_ic(self, stock_id):
        fs_df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=3)
        bs_df = self._fetch_data("TaiwanStockBalanceSheet", stock_id, years_back=3)
        
        if fs_df.empty or bs_df.empty: 
            return 0, 0, 0, 0, 0

        op_data = self._dedupe_by_date_maxvalue(fs_df[fs_df["type"].str.contains('OperatingIncome|營業利益', case=False, na=False)])
        pt_data = self._dedupe_by_date_maxvalue(fs_df[fs_df["type"].str.contains('IncomeBeforeTax|稅前淨利', case=False, na=False)])
        tax_data = self._dedupe_by_date_maxvalue(fs_df[fs_df["type"].str.contains('IncomeTaxExpense|所得稅', case=False, na=False)])
        
        eq_data = self._dedupe_by_date_maxvalue(bs_df[bs_df["type"].str.contains('Equity|權益', case=False, na=False)])
        debt_data = self._dedupe_by_date_maxvalue(bs_df[bs_df["type"].str.contains('Debt|借款|公司債', case=False, na=False)], subset_cols=('date', 'type'))
        cash_data = self._dedupe_by_date_maxvalue(bs_df[bs_df["type"].str.contains('CashAndCashEquivalents|現金及約當現金', case=False, na=False)])
        shares_data = self._dedupe_by_date_maxvalue(bs_df[bs_df["type"].str.contains('OrdinaryShares|CommonStock|CapitalStock|普通股股本|股本', case=False, na=False)])

        try:
            op_ttm = op_data.sort_values('date').tail(4)['value'].sum()
            pt_ttm = pt_data.sort_values('date').tail(4)['value'].sum()
            tax_ttm = tax_data.sort_values('date').tail(4)['value'].sum()
            
            raw_tax_rate = (tax_ttm / pt_ttm) if pt_ttm > 0 else 0.20
            tax_rate = max(0.15, min(0.25, raw_tax_rate))
            nopat = op_ttm * (1 - tax_rate)
            
            equity = eq_data.sort_values('date').iloc[-1]['value'] if not eq_data.empty else 0
            debt = debt_data.sort_values('date').tail(4).groupby('type').last()['value'].sum() if not debt_data.empty else 0
            cash = cash_data.sort_values('date').iloc[-1]['value'] if not cash_data.empty else 0
            
            net_debt = debt - cash
            invested_capital = equity + debt - cash
            
            if shares_data.empty: return 0, 0, 0, 0, 0
            share_capital = shares_data.sort_values('date').iloc[-1]['value']
            if share_capital <= 0: return 0, 0, 0, 0, 0
            diluted_shares = share_capital / 10 
            
            return nopat, invested_capital, net_debt, diluted_shares, tax_rate
        except:
            return 0, 0, 0, 1, 0

    def calc_two_stage_fcff(self, nopat_0: float, high_growth: float, stable_growth: float, 
                            roic_start: float, roic_stable: float, wacc_start: float, 
                            wacc_stable: float, net_debt: float, diluted_shares: float, 
                            forecast_years: int = 5, max_terminal_ratio: float = 0.85) -> Optional[DCFResult]:
        warnings = []
        if nopat_0 <= 0 or diluted_shares <= 0: return None
        if stable_growth >= wacc_stable: return None
        if roic_start <= 0 or roic_stable <= 0: return None
        if stable_growth / roic_stable >= 1.0: return None
            
        pv_fcff, discount_factor = 0.0, 1.0
        nopat = nopat_0
        yearly_details = []
        
        for year in range(1, forecast_years + 1):
            progress = year / forecast_years
            growth = high_growth + (stable_growth - high_growth) * progress
            roic = roic_start + (roic_stable - roic_start) * progress
            wacc = wacc_start + (wacc_stable - wacc_start) * progress
            
            if roic <= 0: return None
            reinvestment_rate = growth / roic
            if reinvestment_rate > 1.0: warnings.append(f"第{year}年再投資率超過100%")
                
            nopat *= (1 + growth)
            fcff = nopat * (1 - reinvestment_rate)
            discount_factor *= (1 + wacc)
            pv = fcff / discount_factor
            pv_fcff += pv
            yearly_details.append({"year": year, "growth": growth, "fcff": fcff, "pv_fcff": pv})
            
        stable_reinvestment_rate = stable_growth / roic_stable
        nopat_next = nopat * (1 + stable_growth)
        terminal_fcff = nopat_next * (1 - stable_reinvestment_rate)
        terminal_value = terminal_fcff / (wacc_stable - stable_growth)
        pv_terminal_value = terminal_value / discount_factor
        
        enterprise_value = pv_fcff + pv_terminal_value
        equity_value = enterprise_value - net_debt
        value_per_share = equity_value / diluted_shares
        terminal_value_ratio = pv_terminal_value / enterprise_value if enterprise_value > 0 else 1.0
        
        return DCFResult(enterprise_value, equity_value, value_per_share, terminal_value_ratio, yearly_details, warnings)

    def calc_dcf_confidence(self, result: DCFResult) -> float:
        score = 1.0
        if result.terminal_value_ratio > 0.85: score -= 0.40
        elif result.terminal_value_ratio > 0.75: score -= 0.20
        if len(result.warnings) >= 3: score -= 0.30
        elif len(result.warnings) >= 1: score -= 0.10
        return max(0.0, min(score, 1.0))

    def calc_reverse_dcf(self, target_price: float, nopat_0: float, stable_growth: float, 
                         roic_start: float, roic_stable: float, wacc_start: float, 
                         wacc_stable: float, net_debt: float, diluted_shares: float) -> Optional[float]:
        low, high = -0.50, 2.00
        implied_g = None
        for _ in range(40):
            mid = (low + high) / 2
            res = self.calc_two_stage_fcff(nopat_0, mid, stable_growth, roic_start, roic_stable, wacc_start, wacc_stable, net_debt, diluted_shares, max_terminal_ratio=1.0)
            if not res: 
                high = mid 
                continue
            if res.value_per_share > target_price: high = mid
            else: low = mid
            implied_g = mid
        return implied_g

    def _calc_fcfe_per_share(self, fwd_eps, g_high, bvps, ke_start=0.095, ke_stable=0.085, stable_growth=0.02, forecast_years=5):
        if fwd_eps <= 0 or bvps <= 0: return None
        roe = fwd_eps / bvps
        roe = max(0.02, min(0.35, roe))
        g_high = max(-0.20, min(0.40, g_high))
        if stable_growth >= ke_stable or (stable_growth / roe >= 1.0): return None

        warnings = []
        eps = fwd_eps
        pv_fcfe, discount_factor = 0.0, 1.0

        for year in range(1, forecast_years + 1):
            progress = year / forecast_years
            growth = g_high + (stable_growth - g_high) * progress
            ke = ke_start + (ke_stable - ke_start) * progress
            reinvestment_rate = min(1.0, max(-0.5, growth / roe))
            eps *= (1 + growth)
            fcfe = eps * (1 - reinvestment_rate)
            discount_factor *= (1 + ke)
            pv_fcfe += fcfe / discount_factor

        stable_reinvestment = stable_growth / roe
        eps_next = eps * (1 + stable_growth)
        terminal_fcfe = eps_next * (1 - stable_reinvestment)
        terminal_value = terminal_fcfe / (ke_stable - stable_growth)
        pv_terminal = terminal_value / discount_factor

        value_per_share = pv_fcfe + pv_terminal
        if value_per_share <= 0: return None
        terminal_ratio = pv_terminal / value_per_share
        return value_per_share, terminal_ratio, roe, warnings

    def _sanity_clamp(self, current_price, cheap, fair, exp, extra):
        if current_price <= 0: return cheap, fair, exp, extra
        FAIR_CAP, EXP_CAP, FLOOR = 2.2, 3.2, 0.25
        clamped = False
        if fair > current_price * FAIR_CAP: fair = round(current_price * FAIR_CAP, 1); clamped = True
        if exp > current_price * EXP_CAP: exp = round(current_price * EXP_CAP, 1); clamped = True
        if exp < fair: exp = round(fair * 1.15, 1); clamped = True
        if cheap > fair: cheap = round(fair * 0.85, 1); clamped = True
        if cheap < current_price * FLOOR: cheap = round(current_price * FLOOR, 1); clamped = True
        extra = dict(extra) if extra else {}
        extra["sanity_clamped"] = clamped
        return cheap, fair, exp, extra

    def calc_blended_valuation(self, stock_id: str, current_price: float, current_pb: float = 0.0):
        if current_price <= 0: return None
        peg_res = self.calc_peg_valuation(stock_id, current_price)
        if not peg_res: return None
        peg_cheap, peg_fair, peg_exp, _ = peg_res
        fwd_eps, fwd_g = self.estimate_forward_eps(stock_id)

        nopat, ic, net_debt, shares, tax_rate = self._get_nopat_and_ic(stock_id)
        implied_g_pct = "N/A"

        if nopat > 0 and ic > 0 and shares > 0:
            wacc_start, wacc_stable, stable_growth = 0.105, 0.09, 0.02
            roic_start = max(0.05, min(0.50, nopat / ic))
            roic_stable = max(wacc_stable + 0.02, stable_growth + 0.01)
            high_growth = max(0.05, min(0.40, fwd_g))

            dcf_res = self.calc_two_stage_fcff(nopat, high_growth, stable_growth, roic_start, roic_stable, wacc_start, wacc_stable, net_debt, shares)
            implied_g = self.calc_reverse_dcf(current_price, nopat, stable_growth, roic_start, roic_stable, wacc_start, wacc_stable, net_debt, shares)
            implied_g_pct = round(implied_g * 100, 2) if implied_g is not None else "N/A"

            if dcf_res:
                dcf_confidence = self.calc_dcf_confidence(dcf_res)
                dcf_weight = 0.40 * dcf_confidence
                peg_weight = 1.0 - dcf_weight
                dcf_fair = dcf_res.value_per_share
                dcf_cheap, dcf_exp = dcf_fair * 0.85, dcf_fair * 1.15

                blended_cheap = round((peg_cheap * peg_weight) + (dcf_cheap * dcf_weight), 1)
                blended_fair = round((peg_fair * peg_weight) + (dcf_fair * dcf_weight), 1)
                blended_exp = round((peg_exp * peg_weight) + (dcf_exp * dcf_weight), 1)

                return self._sanity_clamp(current_price, blended_cheap, blended_fair, blended_exp, {
                    "implied_g": implied_g_pct, "dcf_weight": round(dcf_weight * 100, 1),
                    "peg_weight": round(peg_weight * 100, 1), "fcfe_weight": 0, "model": "FCFF"
                })

        bvps = 0.0
        if current_pb > 0: bvps = current_price / current_pb
        else:
            df_per = self._fetch_data("TaiwanStockPER", stock_id, years_back=1)
            if not df_per.empty and "PBR" in df_per.columns:
                valid_pb = df_per[df_per["PBR"] > 0]["PBR"]
                if not valid_pb.empty: bvps = current_price / valid_pb.iloc[-1]

        fcfe_res = self._calc_fcfe_per_share(fwd_eps, fwd_g, bvps)
        if fcfe_res:
            fcfe_fair, terminal_ratio, roe_used, warnings = fcfe_res
            fcfe_confidence = max(0.0, min(1.0, 1.0 - (0.4 if terminal_ratio > 0.85 else 0.2 if terminal_ratio > 0.75 else 0.0) - (0.2 if len(warnings) >= 2 else 0.0)))
            fcfe_weight = 0.35 * fcfe_confidence
            peg_weight = 1.0 - fcfe_weight

            blended_cheap = round((peg_cheap * peg_weight) + (fcfe_fair * 0.85 * fcfe_weight), 1)
            blended_fair = round((peg_fair * peg_weight) + (fcfe_fair * fcfe_weight), 1)
            blended_exp = round((peg_exp * peg_weight) + (fcfe_fair * 1.15 * fcfe_weight), 1)

            return self._sanity_clamp(current_price, blended_cheap, blended_fair, blended_exp, {
                "implied_g": implied_g_pct, "dcf_weight": 0, "peg_weight": round(peg_weight * 100, 1),
                "fcfe_weight": round(fcfe_weight * 100, 1), "model": "FCFE/share"
            })

        return self._sanity_clamp(current_price, peg_cheap, peg_fair, peg_exp, {
            "implied_g": implied_g_pct, "dcf_weight": 0, "peg_weight": 100, "fcfe_weight": 0, "model": "PEG"
        })