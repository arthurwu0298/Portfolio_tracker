# valuation_engine.py
import io
import math
import requests
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta

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
        
        # 🚀 升級：不再用每日浮動的 current_price / current_pe
        # 改用具有 CAPE 均值保護與營運槓桿推算的 Forward EPS，消除循環股暴衝盲點
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
        
        ttm_eps, eps_yoy, eps_ytd_val, eps_ytd_periods, eps_latest_q = 0.0, None, 0.0, 0, 0.0
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
            eps_latest_q = eps_data.iloc[-1]['value']

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
        
        # 🚀 升級：景氣循環股谷底翻揚動能極強，短期成長率上限放寬至 80%
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

    # ==============================================================
    # 🚀 新增 1：葛拉漢公式 (Graham Number) 防呆下限
    # ==============================================================
    def calc_graham_number(self, stock_id, current_price, current_pb):
        # 🚀 升級：以經過平滑處理的 Forward EPS 取代每日跳動的 TTM EPS
        if current_price <= 0 or current_pb <= 0: return 0.0
        eps, _ = self.estimate_forward_eps(stock_id)
        bvps = current_price / current_pb
        if eps > 0 and bvps > 0: return round(math.sqrt(22.5 * eps * bvps), 1)
        return 0.0

    # ==============================================================
    # 🚀 嚴謹版：超額報酬模型 (Residual Income Model) - 絕不造假數據
    # 🛠️ 修正：淨利與股東權益分屬不同報表，不能只查一個資料集
    #    - 淨利 (IncomeAfterTaxes 等) 屬於「綜合損益表」TaiwanStockFinancialStatements
    #    - 股東權益 (Equity 等) 屬於「資產負債表」TaiwanStockBalanceSheet，兩者是 FinMind 上
    #      不同的 dataset；之前只查損益表，導致權益科目幾乎抓不到，ROE 永遠算出 0，
    #      RIM 估值連帶全部歸零。
    # ==============================================================
    def _get_3yr_avg_roe(self, stock_id):
        # 🚀 核心修復：權益 (Equity) 必須從 TaiwanStockBalanceSheet 抓取
        fs_df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=4)
        bs_df = self._fetch_data("TaiwanStockBalanceSheet", stock_id, years_back=4)
        
        if fs_df.empty or bs_df.empty: return 0.0 
        
        # 🚀 升級：使用模糊比對 (str.contains)，一網打盡所有金融股特殊的會計科目名稱
        ni_data = fs_df[fs_df["type"].str.contains('NetIncome|ProfitLoss|淨利|淨損', case=False, na=False)].copy()
        eq_data = bs_df[bs_df["type"].str.contains('Equity|權益', case=False, na=False)].copy()
        
        if ni_data.empty or eq_data.empty: return 0.0 
        
        # 確保每個日期只取一個最具代表性的值 (去除重複科目的干擾)
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

    def calc_residual_income_valuation(self, stock_id, current_price, current_pb):
        if current_price <= 0:
            return 0, 0, 0, None
            
        if current_pb <= 0:
            df_per = self._fetch_data("TaiwanStockPER", stock_id, years_back=1)
            if not df_per.empty and "PBR" in df_per.columns:
                valid_pb = df_per[df_per["PBR"] > 0]["PBR"]
                if not valid_pb.empty:
                    current_pb = valid_pb.iloc[-1]
            
            if current_pb <= 0:
                return 0, 0, 0, None
            
        bvps = current_price / current_pb
        
        # 🚀 終極修復：放棄容易錯亂的絕對金額，改用 EPS 與 BVPS 反推最純粹的 ROE
        fwd_eps, _ = self.estimate_forward_eps(stock_id)
        if fwd_eps <= 0 or bvps <= 0:
            return 0, 0, 0, None
            
        # 核心數學公式：ROE = EPS / BVPS
        roe = fwd_eps / bvps
        # 防呆保護：金融股 ROE 通常在 5%~15% 之間，設定合理上下限
        roe = max(0.04, min(roe, 0.25))
        
        g = 0.02 
        ke_cheap = 0.085
        ke_fair = 0.070
        ke_exp = 0.055
        
        def get_target_pb(ke):
            if ke <= g: return 1.0 
            target_pb = 1 + (roe - ke) / (ke - g)
            # 放寬底線至 0.6，避免過度低估
            return max(0.6, target_pb)
            
        cheap_price = round(bvps * get_target_pb(ke_cheap), 1)
        fair_price = round(bvps * get_target_pb(ke_fair), 1)
        exp_price = round(bvps * get_target_pb(ke_exp), 1)
        
        return cheap_price, fair_price, exp_price, {"roe": roe, "bvps": bvps}