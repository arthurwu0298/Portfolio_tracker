# valuation_engine.py
import io
import requests
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta


class FinMindValuationEngine:
    """
    負責向 FinMind 拉取歷史本益比/淨值比/營收資料，並計算：
      1. 便宜價 / 合理價 / 目標價（沿用原本的 20/50/80 百分位反推股價）
      2. 現在的本益比或淨值比，落在近5年歷史分布的第幾百分位
         （用來判斷「現價超出模型」是單純波動，還是真正的歷史級異常）
      3. 營收年增率動能，用來交叉驗證估值異常是否有基本面支撐

    新增了輕量 SQLite 快取層：同一檔股票的歷史序列（PER/PBR/月營收）
    在 cache_max_age_days 天內不會重複打 FinMind API，降低免費額度的
    使用量，也讓程式在 API 短暫失效時仍有資料可用。
    """

    def __init__(self, token="", db_file="portfolio_history.db", cache_max_age_days=7):
        self.token = token
        self.base_url = "https://api.finmindtrade.com/api/v4/data"
        self.db_file = db_file
        self.cache_max_age_days = cache_max_age_days
        self._init_cache_table()

    # ---------- 快取層 ----------

    def _init_cache_table(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS finmind_cache (
                stock_id TEXT,
                dataset TEXT,
                fetched_at TEXT,
                data_json TEXT,
                PRIMARY KEY (stock_id, dataset)
            )
        ''')
        conn.commit()
        conn.close()

    def _read_cache(self, dataset, data_id):
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT fetched_at, data_json FROM finmind_cache WHERE stock_id = ? AND dataset = ?",
                (data_id, dataset)
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                return None
            fetched_at, data_json = row
            fetched_time = datetime.fromisoformat(fetched_at)
            if datetime.now() - fetched_time > timedelta(days=self.cache_max_age_days):
                return None
            df = pd.read_json(io.StringIO(data_json))
            return df if not df.empty else None
        except Exception:
            return None

    def _write_cache(self, dataset, data_id, df):
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO finmind_cache (stock_id, dataset, fetched_at, data_json)
                VALUES (?, ?, ?, ?)
            ''', (data_id, dataset, datetime.now().isoformat(), df.to_json()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 快取寫入失敗 ({data_id}/{dataset}): {e}")

    def _fetch_data(self, dataset, data_id, years_back=5, use_cache=True):
        if use_cache:
            cached = self._read_cache(dataset, data_id)
            if cached is not None:
                return cached

        start_date = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y-%m-%d")
        params = {
            "dataset": dataset,
            "data_id": data_id,
            "start_date": start_date
        }
        if self.token:
            params["token"] = self.token

        try:
            res = requests.get(self.base_url, params=params, timeout=15)
            if res.status_code == 200:
                data = res.json().get("data", [])
                df = pd.DataFrame(data)
                if use_cache and not df.empty:
                    self._write_cache(dataset, data_id, df)
                return df
        except Exception as e:
            print(f"FinMind API 請求失敗 ({data_id}): {e}")
        return pd.DataFrame()

    # ---------- 股利 ----------

    def get_recent_dividend(self, stock_id):
        df = self._fetch_data("TaiwanStockDividendResult", stock_id, years_back=2)
        if df.empty or "stock_and_cache_dividend" not in df.columns:
            return 0.0
        try:
            df['date'] = pd.to_datetime(df['date'])
            one_yr_ago = pd.Timestamp.now() - pd.DateOffset(years=1)
            return df[df['date'] >= one_yr_ago]["stock_and_cache_dividend"].sum()
        except Exception:
            return 0.0

    def get_stock_dividend_info(self, stock_id):
        """
        抓取最近一次公告的股利政策(TaiwanStockDividend)，拆出現金股利、股票股利(元，
        面額10元基礎)、以及對應發放年度的EPS加總，供計算「含股票股利的總配發率」使用。

        設計理由：股票股利本質上是把保留盈餘轉列股本、配發新股給股東，公司總市值不會
        因此改變，跟現金股利「公司現金真的減少、股東真的拿到錢」性質不同，不應該直接
        加進現金殖利率內、套用同一組目標殖利率門檻去反推便宜/合理/目標價(那樣會系統性
        高估真實現金報酬)。因此本函式只回傳原始數字，讓呼叫端另外顯示「總配發率」當
        參考資訊，不會混進主要的現金殖利率估值計算。

        回傳 (股票股利元, 現金股利元, 對應年度EPS加總)，抓不到資料時回傳 (0.0, 0.0, 0.0)。
        """
        df = self._fetch_data("TaiwanStockDividend", stock_id, years_back=2)
        if df.empty or "year" not in df.columns:
            return 0.0, 0.0, 0.0
        try:
            df = df.copy()
            df["year_int"] = pd.to_numeric(df["year"], errors="coerce")
            df = df.dropna(subset=["year_int"]).sort_values("year_int")
            if df.empty:
                return 0.0, 0.0, 0.0
            latest = df.iloc[-1]
            div_year = int(latest["year_int"])

            stock_div = float(latest.get("StockEarningsDistribution", 0) or 0) + \
                        float(latest.get("StockStatutorySurplus", 0) or 0)
            cash_div = float(latest.get("CashEarningsDistribution", 0) or 0) + \
                       float(latest.get("CashStatutorySurplus", 0) or 0)

            eps_df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=3)
            year_eps = 0.0
            if not eps_df.empty and "type" in eps_df.columns:
                eps_rows = eps_df[eps_df["type"] == "EPS"].copy()
                if not eps_rows.empty:
                    eps_rows["date"] = pd.to_datetime(eps_rows["date"])
                    year_rows = eps_rows[eps_rows["date"].dt.year == div_year]
                    year_eps = year_rows["value"].sum()

            return round(stock_div, 3), round(cash_div, 3), round(year_eps, 3)
        except Exception:
            return 0.0, 0.0, 0.0

    # ---------- 預估EPS自動年化（取代手動維護 estimated_eps） ----------

    def get_annualized_eps(self, stock_id):
        """
        用 FinMind「綜合損益表」(TaiwanStockFinancialStatements) 的季度EPS，
        把今年至今已公布的季度EPS加總後，依已公布季數年化推算全年EPS。
        例如只公布了上半年(2季)，就用「上半年累計EPS x 2」估全年；
        公布3季就用「前3季累計EPS x 4/3」，以此類推，Q4公布後就是實際全年值。

        若今年一季都還沒公布(通常是1-2月間)，退回去年整年EPS加總當作估計。
        抓不到資料時回傳 0.0，呼叫端應自行退回其他備援方式(如TTM本益比反推)。

        已知限制：若公司當年度有配發股票股利(無償配股)，IAS 33要求追溯調整
        加權平均股數，但FinMind的季度EPS存的是各季公布當下的原始值、不會回頭
        改寫，同一年度內股利發放前後的EPS股數基準可能不一致，用本函式加總會有
        小幅誤差(通常是高估)，發放股票股利比例高的公司(如部分官股銀行)較明顯。
        """
        df = self._fetch_data("TaiwanStockFinancialStatements", stock_id, years_back=2)
        if df.empty or "type" not in df.columns:
            return 0.0
        try:
            eps_df = df[df["type"] == "EPS"].copy()
            if eps_df.empty:
                return 0.0
            eps_df["date"] = pd.to_datetime(eps_df["date"])
            eps_df = eps_df.sort_values("date")

            this_year = datetime.now().year
            this_year_rows = eps_df[eps_df["date"].dt.year == this_year]
            if not this_year_rows.empty:
                ytd_eps = this_year_rows["value"].sum()
                quarters_reported = len(this_year_rows)
                return round(ytd_eps * (4 / quarters_reported), 2)

            # 今年還沒有任何季報(通常是1月初) → 退回去年整年EPS加總
            last_year_rows = eps_df[eps_df["date"].dt.year == this_year - 1]
            if not last_year_rows.empty:
                return round(last_year_rows["value"].sum(), 2)
            return 0.0
        except Exception:
            return 0.0

    # ---------- 估值：本益比 / 淨值比 + 歷史百分位 ----------

    def calc_pe_valuation(self, stock_id, current_price, current_pe):
        """回傳 (便宜價, 合理價, 目標價, 現在PE所在近5年歷史百分位)"""
        if current_price <= 0 or current_pe <= 0:
            return 0, 0, 0, None
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PER" not in df.columns:
            return 0, 0, 0, None
        ttm_eps = current_price / current_pe
        valid_pe = df[df["PER"] > 0]["PER"]
        if valid_pe.empty:
            return 0, 0, 0, None
        pe_20, pe_50, pe_80 = np.percentile(valid_pe, 20), np.percentile(valid_pe, 50), np.percentile(valid_pe, 80)
        # 現在的本益比比歷史上多少比例的觀測值都還高 → 百分位越高代表估值越極端
        current_percentile = round((valid_pe < current_pe).mean() * 100, 1)
        return (round(ttm_eps * pe_20, 1), round(ttm_eps * pe_50, 1),
                round(ttm_eps * pe_80, 1), current_percentile)

    def calc_pb_valuation(self, stock_id, current_price, current_pb):
        """回傳 (便宜價, 合理價, 目標價, 現在PB所在近5年歷史百分位)"""
        if current_price <= 0 or current_pb <= 0:
            return 0, 0, 0, None
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PBR" not in df.columns:
            return 0, 0, 0, None
        current_bvps = current_price / current_pb
        valid_pb = df[df["PBR"] > 0]["PBR"]
        if valid_pb.empty:
            return 0, 0, 0, None
        pb_20, pb_50, pb_80 = np.percentile(valid_pb, 20), np.percentile(valid_pb, 50), np.percentile(valid_pb, 80)
        current_percentile = round((valid_pb < current_pb).mean() * 100, 1)
        return (round(current_bvps * pb_20, 1), round(current_bvps * pb_50, 1),
                round(current_bvps * pb_80, 1), current_percentile)

    # ---------- 營收動能（交叉驗證估值異常是否有基本面支撐） ----------

    def get_revenue_momentum(self, stock_id):
        """
        比較最新月營收年增率 vs 3個月前的年增率，判斷成長是否在加速。
        回傳 {"latest_yoy": 最新年增率, "accelerating": 是否比3個月前加速} 或 None（資料不足）。
        """
        df = self._fetch_data("TaiwanStockMonthRevenue", stock_id, years_back=2)
        if df.empty or "revenue" not in df.columns:
            return None
        try:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            df['yoy'] = df['revenue'].pct_change(periods=12) * 100
            recent = df['yoy'].dropna()
            if len(recent) < 4:
                return None
            return {
                "latest_yoy": round(recent.iloc[-1], 1),
                "accelerating": bool(recent.iloc[-1] > recent.iloc[-4])
            }
        except Exception:
            return None
