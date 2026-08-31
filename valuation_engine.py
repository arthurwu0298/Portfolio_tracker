# valuation_engine.py
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class FinMindValuationEngine:
    def __init__(self, token=""):
        self.token = token
        self.base_url = "https://api.finmindtrade.com/api/v4/data"

    def _fetch_data(self, dataset, data_id, years_back=5):
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
                return pd.DataFrame(data)
        except Exception as e:
            print(f"FinMind API 請求失敗 ({data_id}): {e}")
        return pd.DataFrame()

    def calc_yield_valuation(self, stock_id, target_yields):
        df = self._fetch_data("TaiwanStockDividendResult", stock_id, years_back=5)
        if df.empty or "stock_and_cache_dividend" not in df.columns:
            return 0, 0, 0
        avg_dividend = df.tail(5)["stock_and_cache_dividend"].mean()
        cheap = round(avg_dividend / (target_yields.get("cheap", 6.0) / 100), 1)
        fair = round(avg_dividend / (target_yields.get("fair", 5.0) / 100), 1)
        target = round(avg_dividend / (target_yields.get("target", 4.0) / 100), 1)
        return cheap, fair, target

    def calc_pe_valuation(self, stock_id, current_price, current_pe):
        if current_price <= 0 or current_pe <= 0: return 0, 0, 0
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PER" not in df.columns: return 0, 0, 0
        ttm_eps = current_price / current_pe
        valid_pe = df[df["PER"] > 0]["PER"]
        pe_20, pe_50, pe_80 = np.percentile(valid_pe, 20), np.percentile(valid_pe, 50), np.percentile(valid_pe, 80)
        return round(ttm_eps * pe_20, 1), round(ttm_eps * pe_50, 1), round(ttm_eps * pe_80, 1)

    def calc_pb_valuation(self, stock_id, current_price, current_pb):
        if current_price <= 0 or current_pb <= 0: return 0, 0, 0
        df = self._fetch_data("TaiwanStockPER", stock_id, years_back=5)
        if df.empty or "PBR" not in df.columns: return 0, 0, 0
        current_bvps = current_price / current_pb
        valid_pb = df[df["PBR"] > 0]["PBR"]
        pb_20, pb_50, pb_80 = np.percentile(valid_pb, 20), np.percentile(valid_pb, 50), np.percentile(valid_pb, 80)
        return round(current_bvps * pb_20, 1), round(current_bvps * pb_50, 1), round(current_bvps * pb_80, 1)
