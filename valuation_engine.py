# valuation_engine.py
import io
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS finmind_cache (
                stock_id TEXT, dataset TEXT, fetched_at TEXT, data_json TEXT, PRIMARY KEY (stock_id, dataset)
            )
        ''')
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
            cursor.execute('''INSERT OR REPLACE INTO finmind_cache (stock_id, dataset, fetched_at, data_json) VALUES (?, ?, ?, ?)''', 
                           (data_id, dataset, datetime.now().isoformat(), df.to_json()))
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

    def get_stock_dividend_info(self, stock_id):
        df = self._fetch_data("TaiwanStockDividend", stock_id, years_back=2)
        if df.empty or "year" not in df.columns: return 0.0, 0.0, 0.0
        try:
            df = df.copy()
            df["year_int"] = pd.to_numeric(df["year"], errors="coerce")
            df = df.dropna(subset=["year_int"]).sort_values("year_int")
            if df.empty: return 0.0, 0.0, 0.0
            latest = df.iloc[-1]
            div_year = int(latest["year_int"])
            stock_div = float(latest.get("StockEarningsDistribution", 0) or 0) + float(latest.get("StockStatutorySurplus", 0) or 0)
            cash_div = float(latest.get("CashEarningsDistribution", 0) or 0) + float(latest.get("CashStatutorySurplus", 0) or 0)
            eps_df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=3)
            year_eps = 0.0
            if not eps_df.empty and "type" in eps_df.columns:
                eps_rows = eps_df[eps_df["type"] == "EPS"].copy()
                if not eps_rows.empty:
                    eps_rows["date"] = pd.to_datetime(eps_rows["date"])
                    year_eps = eps_rows[eps_rows["date"].dt.year == div_year]["value"].sum()
            return round(stock_div, 3), round(cash_div, 3), round(year_eps, 3)
        except: return 0.0, 0.0, 0.0

    def get_annualized_eps(self, stock_id):
        df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=2)
        if df.empty or "type" not in df.columns: return 0.0
        try:
            eps_df = df[df["type"] == "EPS"].copy()
            if eps_df.empty: return 0.0
            eps_df["date"] = pd.to_datetime(eps_df["date"])
            eps_df = eps_df.sort_values("date")
            this_year = datetime.now().year
            this_year_rows = eps_df[eps_df["date"].dt.year == this_year]
            if not this_year_rows.empty:
                ytd_eps = this_year_rows["value"].sum()
                return round(ytd_eps * (4 / len(this_year_rows)), 2)
            last_year_rows = eps_df[eps_df["date"].dt.year == this_year - 1]
            if not last_year_rows.empty: return round(last_year_rows["value"].sum(), 2)
            return 0.0
        except: return 0.0

    def get_5yr_average_eps(self, stock_id):
        df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=6)
        if df.empty or "type" not in df.columns: return 0.0
        try:
            eps_df = df[df["type"] == "EPS"].copy()
            if eps_df.empty: return 0.0
            eps_df["date"] = pd.to_datetime(eps_df["date"])
            eps_df = eps_df.sort_values("date")
            last_20_q = eps_df.tail(20)
            if len(last_20_q) > 0:
                avg_yearly_eps = (last_20_q["value"].sum() / len(last_20_q)) * 4
                return round(avg_yearly_eps, 2)
            return 0.0
        except: return 0.0

    def calc_pe_valuation(self, stock_id, current_price, current_pe):
        if current_price <= 0 or current_pe <= 0: return 0, 0, 0, None
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PER" not in df.columns: return 0, 0, 0, None
        ttm_eps = current_price / current_pe
        valid_pe = df[df["PER"] > 0]["PER"]
        if valid_pe.empty: return 0, 0, 0, None
        pe_20, pe_50, pe_80 = np.percentile(valid_pe, 20), np.percentile(valid_pe, 50), np.percentile(valid_pe, 80)
        current_percentile = round((valid_pe < current_pe).mean() * 100, 1)
        return round(ttm_eps * pe_20, 1), round(ttm_eps * pe_50, 1), round(ttm_eps * pe_80, 1), current_percentile

    def calc_pb_valuation(self, stock_id, current_price, current_pb):
        if current_price <= 0 or current_pb <= 0: return 0, 0, 0, None
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PBR" not in df.columns: return 0, 0, 0, None
        current_bvps = current_price / current_pb
        valid_pb = df[df["PBR"] > 0]["PBR"]
        if valid_pb.empty: return 0, 0, 0, None
        pb_20, pb_50, pb_80 = np.percentile(valid_pb, 20), np.percentile(valid_pb, 50), np.percentile(valid_pb, 80)
        current_percentile = round((valid_pb < current_pb).mean() * 100, 1)
        return round(current_bvps * pb_20, 1), round(current_bvps * pb_50, 1), round(current_bvps * pb_80, 1), current_percentile

    def get_revenue_momentum(self, stock_id):
        df = self._fetch_data("TaiwanStockMonthRevenue", stock_id, years_back=2)
        if df.empty or "revenue" not in df.columns: return None
        try:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df['yoy'] = df['revenue'].pct_change(periods=12) * 100
            recent = df['yoy'].dropna()
            if len(recent) < 4: return None
            return {"latest_yoy": round(recent.iloc[-1], 1), "accelerating": bool(recent.iloc[-1] > recent.iloc[-4])}
        except: return None

    # ---------- 新增：動態抓取歷史殖利率區間 ----------
    def calc_yield_percentile_bounds(self, stock_id):
        """
        自動抓近5年歷史殖利率，回傳 20/50/80 百分位數作為 便宜/合理/目標 殖利率
        (殖利率越高代表越便宜，所以便宜價對應 80 百分位)
        回傳: (便宜殖利率, 合理殖利率, 目標殖利率)
        """
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "dividend_yield" not in df.columns: return 0.0, 0.0, 0.0
        try:
            valid_yields = df[df["dividend_yield"] > 0]["dividend_yield"]
            if valid_yields.empty: return 0.0, 0.0, 0.0
            
            y_target = round(np.percentile(valid_yields, 20), 2)
            y_fair = round(np.percentile(valid_yields, 50), 2)
            y_cheap = round(np.percentile(valid_yields, 80), 2)
            return y_cheap, y_fair, y_target
        except: return 0.0, 0.0, 0.0

    # ---------- 新增：趨勢乖離法 ----------
    def calc_price_trend_valuation(self, stock_id, current_price):
        """
        給0050、006208、0052這類「報酬主要來自成分股資本利得」的市值/科技型ETF使用。
        """
        df = self._fetch_data("TaiwanStockPrice", stock_id, years_back=5)
        if df.empty or "close" not in df.columns:
            return 0, 0, 0, 0.0, None
        try:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])
            df["ma200"] = df["close"].rolling(window=200).mean()
            df["deviation"] = (df["close"] - df["ma200"]) / df["ma200"] * 100
            df = df.dropna(subset=["deviation"])
            if df.empty:
                return 0, 0, 0, 0.0, None

            current_ma200 = df["ma200"].iloc[-1]
            if current_ma200 <= 0:
                return 0, 0, 0, 0.0, None

            p20_dev = np.percentile(df["deviation"], 20)
            p50_dev = np.percentile(df["deviation"], 50)
            p80_dev = np.percentile(df["deviation"], 80)
            cheap_price = round(current_ma200 * (1 + p20_dev / 100), 1)
            fair_price = round(current_ma200 * (1 + p50_dev / 100), 1)
            target_price = round(current_ma200 * (1 + p80_dev / 100), 1)

            current_deviation = round((current_price - current_ma200) / current_ma200 * 100, 2)
            current_percentile = round((df["deviation"] < current_deviation).mean() * 100, 1)
            return cheap_price, fair_price, target_price, current_deviation, current_percentile
        except Exception:
            return 0, 0, 0, 0.0, None