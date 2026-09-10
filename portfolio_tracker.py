# portfolio_tracker.py
import os
import re
import time
import sqlite3
import requests
import pandas as pd
import yfinance as yf
import pandas_ta as ta  
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import urllib.parse
import xml.etree.ElementTree as ET

from portfolio_config import (
    PORTFOLIO, CASH_RESERVE, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, FINMIND_TOKEN
)
from valuation_engine import FinMindValuationEngine

DB_FILE = "portfolio_history.db"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

METHOD_MAP = {
    "yield": "預估殖利率",
    "pe": "歷史本益比法",
    "pb": "淨值比法",
    "etf_yield": "歷史殖利率",
    "trend": "趨勢乖離法",
    "rim": "超額報酬模型",
    "peg": "本益成長比(PEG)",
    "manual": "手動設定"
}

def safe_float(val):
    try: return float(str(val).replace(",", ""))
    except Exception: return 0.0

class TaiwanMarketTracker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.twse_prices, self.tpex_prices = {}, {}
        self.twse_metrics, self.tpex_metrics = {}, {}
        self.fetch_errors = []
        self.valuation_engine = FinMindValuationEngine(token=FINMIND_TOKEN, db_file=DB_FILE)
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                date TEXT PRIMARY KEY, total_cost REAL, total_mkt REAL,
                total_net_worth REAL, cash_reserve REAL, unrealized_pl REAL, return_rate REAL
            )
        ''')
        conn.commit()
        conn.close()

    def fetch_market_data(self):
        print("📥 [階段一] 抓取 TWSE / TPEx 最新報價與客觀指標(PE/PB/Yield)...")
        try:
            res1 = self.session.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=15)
            if res1.status_code == 200:
                for item in res1.json(): self.twse_prices[item["Code"]] = safe_float(item.get("ClosingPrice"))
        except Exception as e: self.fetch_errors.append(f"TWSE股價API請求失敗: {e}")

        try:
            res2 = self.session.get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d", timeout=15)
            if res2.status_code == 200:
                for item in res2.json():
                    self.twse_metrics[item["Code"]] = {
                        "yield": safe_float(item.get("DividendYield")),
                        "pe": safe_float(item.get("PEratio")),
                        "pb": safe_float(item.get("PBratio"))
                    }
        except Exception as e: self.fetch_errors.append(f"TWSE估值API請求失敗: {e}")

        try:
            res3 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
            if res3.status_code == 200:
                for item in res3.json(): self.tpex_prices[item["SecuritiesCompanyCode"]] = safe_float(item.get("Close"))
        except Exception as e: self.fetch_errors.append(f"TPEx股價API請求失敗: {e}")

        try:
            res4 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", timeout=15)
            if res4.status_code == 200:
                for item in res4.json():
                    lower_item = {k.lower(): v for k, v in item.items()}
                    sec_code = lower_item.get("securitiescompanycode")
                    if sec_code:
                        self.tpex_metrics[sec_code] = {
                            "yield": safe_float(lower_item.get("perdividendyield", lower_item.get("dividendyield"))),
                            "pe": safe_float(lower_item.get("peratio")),
                            "pb": safe_float(lower_item.get("pbratio"))
                        }
        except Exception as e: self.fetch_errors.append(f"TPEx估值API請求失敗: {e}")

        for item in PORTFOLIO:
            c, m = item["code"], item["market"]
            p = self.twse_prices.get(c) if m == "TWSE" else self.tpex_prices.get(c)
            mets = self.twse_metrics.get(c) if m == "TWSE" else self.tpex_metrics.get(c)

            if not p or not mets or mets.get('pe', 0.0) == 0.0:
                try:
                    yf_ticker = f"{c}.TW" if m == "TWSE" else f"{c}.TWO"
                    info = yf.Ticker(yf_ticker).info
                    if not p:
                        fallback_p = safe_float(info.get("currentPrice", info.get("regularMarketPrice", 0.0)))
                        if fallback_p > 0:
                            if m == "TWSE": self.twse_prices[c] = fallback_p
                            else: self.tpex_prices[c] = fallback_p
                    if not mets or mets.get('pe', 0.0) == 0.0:
                        dy = safe_float(info.get("dividendYield", 0.0))
                        if dy > 0 and dy < 1: dy *= 100
                        new_metrics = {"pe": safe_float(info.get("trailingPE", 0.0)), "pb": safe_float(info.get("priceToBook", 0.0)), "yield": dy}
                        if m == "TWSE": self.twse_metrics[c] = new_metrics
                        else: self.tpex_metrics[c] = new_metrics
                except Exception: pass

    def calculate_basic_portfolio(self):
        self.fetch_market_data()
        records = []
        total_mkt, total_cost = 0.0, 0.0

        for item in PORTFOLIO:
            c, m = item["code"], item["market"]
            cp = item.get("cost_per_share")
            s = item["shares"]

            market_price = self.twse_prices.get(c) if m == "TWSE" else self.tpex_prices.get(c)
            price = market_price if (market_price is not None and market_price > 0) else None

            metrics = self.twse_metrics.get(c, {}) if m == "TWSE" else self.tpex_metrics.get(c, {})
            current_pe = metrics.get("pe", 0.0)
            current_pb = metrics.get("pb", 0.0)

            val_cfg = item.get("valuation", {})
            v_method = val_cfg.get("method") or item.get("valuation_method", "manual")
            method_ch = METHOD_MAP.get(v_method, "手動設定")
            extra_note = item.get("note", "")

            cheap_price, fair_price, target_price = 0.0, 0.0, 0.0
            implied_display = "N/A"
            sanity_clamped = False
            is_interim = False

            if not price:
                current_status = "⚠️ 行情資料不足"
            else:
                if v_method == "pe":
                    res = self.valuation_engine.calc_pe_valuation(c, price, current_pe)
                    if res: cheap_price, fair_price, target_price, _ = res
                elif v_method == "peg":
                    res = self.valuation_engine.calc_blended_valuation(c, price, current_pb)
                    if res and len(res) == 4: 
                        cheap_price, fair_price, target_price, extra = res
                        if extra:
                            implied_g_val = extra.get("implied_g", "N/A")
                            implied_display = f"{implied_g_val}%" if implied_g_val != "N/A" else "N/A"
                            dcf_w = extra.get("dcf_weight", 0)
                            fcfe_w = extra.get("fcfe_weight", 0)
                            peg_w = extra.get("peg_weight", 100)
                            if dcf_w > 0: method_ch = f"混合估值(PEG {peg_w}%/DCF {dcf_w}%)"
                            elif fcfe_w > 0: method_ch = f"混合估值(PEG {peg_w}%/每股FCFE {fcfe_w}%)"
                            else: method_ch = "混合估值(純PEG)"
                            if extra.get("sanity_clamped"):
                                method_ch += " ⚠️強制修正"
                                sanity_clamped = True
                elif v_method == "pb":
                    res = self.valuation_engine.calc_pb_valuation(c, price, current_pb)
                    if res: cheap_price, fair_price, target_price, _ = res
                elif v_method == "trend":
                    res = self.valuation_engine.calc_price_trend_valuation(c, price)
                    if res: cheap_price, fair_price, target_price, _, _ = res
                elif v_method == "rim":
                    res = self.valuation_engine.calc_residual_income_valuation(c, price, current_pb, val_cfg=val_cfg)
                    if res and len(res) == 4: 
                        cheap_price, fair_price, target_price, rim_extra = res
                        method_ch = "超額報酬模型(RIM)"
                        if rim_extra:
                            implied_display = rim_extra.get("implied_roe", "N/A")
                            is_interim = rim_extra.get("is_interim", False)
                elif v_method == "yield":
                    payout_ratio = item.get("payout_ratio", 0.5) 
                    res = self.valuation_engine.calc_ddm_valuation(c, price, payout_ratio)
                    if res and len(res) == 4: cheap_price, fair_price, target_price, _ = res
                    method_ch = "H-Model 雙階折現"
                elif v_method == "etf_yield":
                    div_total = self.valuation_engine.get_recent_dividend(c)
                    y_cheap, y_fair, y_target = self.valuation_engine.calc_yield_percentile_bounds(c)
                    if "target_yields" in item:
                        y_cheap = item["target_yields"].get("cheap", y_cheap)
                        y_fair = item["target_yields"].get("fair", y_fair)
                        y_target = item["target_yields"].get("target", y_target)
                    if div_total > 0 and y_cheap > 0:
                        cheap_price = round(div_total / (y_cheap / 100), 1)
                        fair_price = round(div_total / (y_fair / 100), 1)
                        target_price = round(div_total / (y_target / 100), 1)

                is_financial_or_etf = str(c).startswith('28') or str(c).startswith('58') or str(c).startswith('00')
                if not is_financial_or_etf and v_method not in ["trend", "etf_yield", "manual"] and price > 0:
                    graham_floor = self.valuation_engine.calc_graham_number(c, price, current_pb)
                    if graham_floor > 0 and (cheap_price < graham_floor or cheap_price == 0):
                        cheap_price = max(cheap_price, graham_floor)
                        fair_price = max(fair_price, graham_floor * 1.2)
                        target_price = max(target_price, graham_floor * 1.5)
                        extra_note += f"[葛拉漢保護: {graham_floor}]"

                if price > 0 and fair_price > 0:
                    if price <= cheap_price: current_status = "便宜加碼"
                    elif price >= target_price: current_status = "達標停利"
                    elif price >= fair_price + (target_price - fair_price) * 0.7: current_status = "偏高留意"
                    elif price > fair_price: current_status = "合理偏高"
                    else: current_status = "合理續抱"
                else:
                    current_status = "⚠️ 資料不足/模型失效"

                if sanity_clamped: current_status += "（估值已校正）"
                if is_interim: current_status += " ⚠️(待新淨值)"

            if price:
                total_mkt += (s * price)
            if cp is not None and cp > 0:
                total_cost += (s * cp)

            records.append({
                "代碼": c, "名稱": item["name"], "現價": price if price else "查無報價", 
                "便宜價(保守)": cheap_price, "公允價(基準)": fair_price, "昂貴價(樂觀)": target_price,
                "當前狀態": current_status, 
                "指定估價法": method_ch, 
                "市場隱含成長/ROE": implied_display
            })

        ret_rate = round(((total_mkt - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0.0
        self.save_to_db(total_cost, total_mkt, total_mkt + CASH_RESERVE, CASH_RESERVE, total_mkt - total_cost, ret_rate)
        return pd.DataFrame(records)

    def fetch_advanced_quant_data(self):
        print("🔍 [階段二] 掃描核心持股 (is_core=True) 並啟動籌碼動能計分引擎...")
        core_data = {}
        start_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
        
        for item in PORTFOLIO:
            if not item.get("is_core", False): continue
            
            c = item["code"]
            ticker_name = item["name"]
            print(f"  -> 處理核心標的: {ticker_name} ({c})")
            quant_info = {"name": ticker_name, "code": c}
            
            price, ma20, chg_pct, vol_ratio = 0.0, 0.0, 0.0, 1.0
            try:
                yf_ticker = f"{c}.TW" if item["market"] == "TWSE" else f"{c}.TWO"
                hist = yf.Ticker(yf_ticker).history(period="3mo")
                if not hist.empty and len(hist) > 25:
                    hist.ta.kd(append=True)
                    hist.ta.rsi(length=14, append=True)
                    hist.ta.sma(length=20, append=True)
                    
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2]
                    
                    price = float(latest['Close'])
                    ma20 = float(latest.get('SMA_20', price))
                    chg_pct = (price - prev['Close']) / prev['Close'] if prev['Close'] > 0 else 0
                    
                    vols = hist['Volume'].tolist()
                    rv = sum(vols[-5:]) / 5
                    pv = sum(vols[-25:-5]) / 20
                    vol_ratio = rv / pv if pv > 0 else 1.0
                    
                    quant_info["技術面狀態"] = f"現價:{price:.1f}, MA20:{ma20:.1f}, 近日變化:{chg_pct*100:.1f}%, 量能比:{vol_ratio:.2f}x"
                    quant_info["技術指標"] = f"RSI(14): {latest.get('RSI_14', 0):.1f}"
            except: pass

            if FINMIND_TOKEN:
                f_net, t_net, d_net, all_net = 0, 0, 0, 0
                f_cons, t_cons = 0, 0
                f_score, t_score, d_score = 50, 50, 50
                try:
                    res_inst = requests.get(
                        "https://api.finmindtrade.com/api/v4/data",
                        params={"dataset": "InstitutionalInvestorsBuySell", "data_id": c, "start_date": start_date, "token": FINMIND_TOKEN},
                        timeout=10
                    ).json()
                    if res_inst.get("data"):
                        df_inst = pd.DataFrame(res_inst["data"]).sort_values('date', ascending=False)
                        
                        def get_inst_trend(name):
                            rows = df_inst[df_inst['name'] == name]
                            if rows.empty: return 0, 0, 50
                            dates = sorted(rows['date'].unique(), reverse=True)
                            series = []
                            for dt in dates[:20]:
                                d_rows = rows[rows['date'] == dt]
                                net = (pd.to_numeric(d_rows['buy']).sum() - pd.to_numeric(d_rows['sell']).sum())
                                series.append(net)
                            
                            curr_net = round(series[0] / 1000) if series else 0
                            days = 0
                            if series and series[0] > 0:
                                for v in series:
                                    if v > 0: days += 1
                                    else: break
                            elif series and series[0] < 0:
                                for v in series:
                                    if v < 0: days -= 1
                                    else: break
                                    
                            score = 100 if days >= 3 else 80 if days > 0 else 50 if days == 0 else 20 if days > -3 else 0
                            return curr_net, days, score

                        f_net, f_cons, f_score = get_inst_trend('Foreign_Investor')
                        t_net, t_cons, t_score = get_inst_trend('Investment_Trust')
                        
                        d_self_rows = df_inst[df_inst['name'] == 'Dealer_self']
                        d_hedg_rows = df_inst[df_inst['name'] == 'Dealer_Hedging']
                        d_series = []
                        dates = sorted(df_inst['date'].unique(), reverse=True)[:10]
                        for dt in dates:
                            s_rows = d_self_rows[d_self_rows['date'] == dt]
                            h_rows = d_hedg_rows[d_hedg_rows['date'] == dt]
                            s_net = (pd.to_numeric(s_rows['buy']).sum() - pd.to_numeric(s_rows['sell']).sum()) if not s_rows.empty else 0
                            h_net = (pd.to_numeric(h_rows['buy']).sum() - pd.to_numeric(h_rows['sell']).sum()) if not h_rows.empty else 0
                            d_series.append(s_net + h_net)

                        d_net = round(d_series[0] / 1000) if d_series else 0
                        d_days = 0
                        if d_series and d_series[0] > 0:
                            for v in d_series:
                                if v > 0: d_days += 1
                                else: break
                            d_score = 90 if d_days >= 2 else 70
                        elif d_series and d_series[0] < 0:
                            for v in d_series:
                                if v < 0: d_days -= 1
                                else: break
                            d_score = 10 if d_days <= -2 else 30
                        else: d_score = 50
                        
                        all_net = f_net + t_net + d_net
                except: pass

                mg_chg, ss_chg, sr_ratio = 0, 0, 0
                try:
                    res_margin = requests.get(
                        "https://api.finmindtrade.com/api/v4/data",
                        params={"dataset": "TaiwanStockMarginPurchaseShortSale", "data_id": c, "start_date": start_date, "token": FINMIND_TOKEN},
                        timeout=10
                    ).json()
                    if res_margin.get("data"):
                        df_mg = pd.DataFrame(res_margin["data"]).sort_values('date', ascending=False)
                        if not df_mg.empty:
                            latest_mg = df_mg.iloc[0]
                            mg_bal = float(latest_mg.get('MarginPurchaseTodayBalance', 0))
                            mg_prev = float(latest_mg.get('MarginPurchaseYesterdayBalance', mg_bal))
                            mg_chg = mg_bal - mg_prev
                            
                            ss_bal = float(latest_mg.get('ShortSaleTodayBalance', 0))
                            ss_prev = float(latest_mg.get('ShortSaleYesterdayBalance', ss_bal))
                            ss_chg = ss_bal - ss_prev
                            sr_ratio = (ss_bal / mg_bal * 100) if mg_bal > 0 else 0
                except: pass

                cost_dist = ((price - ma20) / ma20 * 100) if ma20 > 0 else 0
                inst_score = round((f_score * 0.6) + (t_score * 0.3) + (d_score * 0.1))
                
                accum, dist = 0, 0
                if abs(chg_pct) < 0.02: accum += 20
                if vol_ratio < 1.1: accum += 20
                if all_net > 0: accum += 30
                if mg_chg < 0: accum += 30
                if chg_pct < 0 and vol_ratio > 1.2: dist += 30
                if all_net < 0: dist += 30
                if mg_chg > 0: dist += 40
                radar_score = accum if accum > dist else (100 - dist)
                
                cost_score = 20
                if 0 <= cost_dist < 5: cost_score = 100
                elif 5 <= cost_dist < 10: cost_score = 80
                elif 10 <= cost_dist < 15: cost_score = 60
                elif 15 <= cost_dist < 20: cost_score = 40
                elif cost_dist >= 20: cost_score = 20
                elif -5 < cost_dist < 0: cost_score = 60
                
                retail_score, retail_msg = 0, "無明顯特徵"
                if chg_pct >= 0 and mg_chg <= 0: retail_score = 100; retail_msg = "籌碼沉澱(價↑資↓)"
                elif chg_pct < 0 and mg_chg <= 0: retail_score = 80; retail_msg = "恐慌出場(價↓資↓)"
                elif chg_pct < 0 and mg_chg > 0: retail_score = 40; retail_msg = "攤平套牢(價↓資↑)"
                elif chg_pct >= 0 and mg_chg > 0: retail_score = 20; retail_msg = "散戶追價(價↑資↑)"
                
                short_score = 40
                if sr_ratio > 20: short_score = 100
                elif sr_ratio > 10: short_score = 80
                elif sr_ratio > 5: short_score = 60
                if ss_chg > 0: short_score = min(100, short_score + 10)
                
                contrib = {"inst": round(inst_score * 0.30), "radar": round(radar_score * 0.25), "cost": round(cost_score * 0.20), "retail": round(retail_score * 0.15), "short": round(short_score * 0.10)}
                final_chip_score = sum(contrib.values())
                
                foreign_penalty = 0
                if f_cons <= -8: foreign_penalty = 25
                elif f_cons <= -5: foreign_penalty = 15
                elif f_cons <= -3: foreign_penalty = 8
                
                final_chip_score = max(0, final_chip_score - foreign_penalty)
                chip_status = "✅ 極佳" if final_chip_score >= 81 else "🟢 良好" if final_chip_score >= 61 else "🟡 中性" if final_chip_score >= 41 else "🟠 偏弱" if final_chip_score >= 21 else "🔴 惡化"
                
                quant_info["籌碼總分"] = f"{final_chip_score}/100 ({chip_status})"
                quant_info["籌碼細項結構"] = f"法人共識度:{contrib['inst']}/30分, 主力雷達:{contrib['radar']}/25分, 均線安全帶:{contrib['cost']}/20分, 散戶動向:{contrib['retail']}/15分, 軋空潛力:{contrib['short']}/10分"
                quant_info["散戶狀態判定"] = retail_msg
                
                f_dir = "連買" if f_cons > 0 else "連賣" if f_cons < 0 else "無連續動向"
                t_dir = "連買" if t_cons > 0 else "連賣" if t_cons < 0 else "無連續動向"
                
                quant_info["外資連續動向"] = f"{f_dir} {abs(f_cons)} 日 (扣分:{foreign_penalty})"
                quant_info["投信連續動向"] = f"{t_dir} {abs(t_cons)} 日"

            core_data[c] = quant_info
            time.sleep(1.5)

        return core_data

    def save_to_db(self, tc, tm, tnw, cash, pl, ret):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO history (date, total_cost, total_mkt, total_net_worth, cash_reserve, unrealized_pl, return_rate) VALUES (?, ?, ?, ?, ?, ?, ?)''', (datetime.now().strftime("%Y-%m-%d"), tc, tm, tnw, cash, pl, ret))
        conn.commit()
        conn.close()

    def get_news_and_analysis(self, df_basic, core_data_dict):
        print("📰 [階段三] 啟動自製 Google 新聞引擎與官方公告抓取，準備 AI 雙層分析...")
        core_portfolio = [item for item in PORTFOLIO if item.get("is_core", False)]
        news_text_for_ai = ""
        
        for item in core_portfolio:
            code, name = item["code"], item["name"]
            try:
                keyword = f"{name} {code} 營收 OR 法說會 OR 產能 OR 財報"
                query = urllib.parse.quote(keyword)
                url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
                res = self.session.get(url, timeout=10)
                if res.status_code == 200:
                    root = ET.fromstring(res.text)
                    count = 0
                    for news_item in root.findall('.//item'):
                        title = news_item.find('title').text
                        pub_date = news_item.find('pubDate').text
                        news_text_for_ai += f"[{name} {code}] {title} (發布時間: {pub_date})\n"
                        count += 1
                        if count >= 2: break
            except: pass
            time.sleep(0.5)
                
        if not news_text_for_ai: news_text_for_ai = "今日暫無重大媒體新聞。"

        official_text_for_ai = ""
        core_tickers = {item["code"]: item["name"] for item in PORTFOLIO}
        try:
            res_twse = self.session.get("https://openapi.twse.com.tw/v1/opendata/t187ap04_L", timeout=10)
            res_tpex = self.session.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O", timeout=10)
            mops_data = []
            if res_twse.status_code == 200: mops_data.extend(res_twse.json())
            if res_tpex.status_code == 200: mops_data.extend(res_tpex.json())
            
            mops_data.sort(key=lambda x: str(x.get("發言日期", "")) + str(x.get("發言時間", "")), reverse=True)
            official_news_count = {code: 0 for code in core_tickers}
            
            for item in mops_data:
                code = str(item.get("公司代號", item.get("SecuritiesCompanyCode", "")))
                if code in core_tickers and official_news_count[code] < 2:
                    date_str = str(item.get("發言日期", ""))
                    time_str = str(item.get("發言時間", ""))
                    raw_content = " ".join([str(v) for k, v in item.items() if k not in ["公司代號", "SecuritiesCompanyCode", "符合條款", "事實發生日"]])
                    if len(raw_content) > 500: raw_content = raw_content[:500] 
                    official_text_for_ai += f"[{core_tickers[code]} {code}] 日期: {date_str} 時間: {time_str} 內容: {raw_content}\n"
                    official_news_count[code] += 1
        except: pass
        if not official_text_for_ai: official_text_for_ai = "無官方重大公告。"

        core_data_text = ""
        if core_data_dict:
            for code, data in core_data_dict.items():
                core_data_text += f"\n--- 【{data.get('name')} ({code}) 深度量化籌碼與技術面】 ---\n"
                for k, v in data.items():
                    if k not in ["name", "code"]: core_data_text += f"{k}: {v}\n"
        else:
            core_data_text = "今日無指定核心持股進行深度推演。"

        if GEMINI_API_KEY:
            print("🤖 正在呼叫 Gemini API 進行決策矩陣運算...")
            try:
                # 🚀 升級點 1：全面導入最新 google.genai 官方架構
                from google import genai
                from google.genai import types
                
                client = genai.Client(api_key=GEMINI_API_KEY)
                
                # 🚀 升級點 2：使用最新強型別 SafetySettings
                safety_settings = [
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE)
                ]
                
                config = types.GenerateContentConfig(
                    safety_settings=safety_settings,
                    temperature=0.3
                )
                
                core_portfolio_names = [f"{item['name']}({item['code']})" for item in PORTFOLIO if item.get("is_core", False)]
                core_portfolio_str = "、".join(core_portfolio_names)
                core_count = len(core_portfolio_names)
                
                prompt = f"""
                你是一位頂尖的量化投資經理、實戰交易員與財經專欄主編。請根據下方 Python 引擎計算的「基礎全景數據」、「官方新聞」與「核心股深度量化籌碼」，產出專業盤後報告。
                
                /reset_data
                【系統指令：嚴格數據依賴・歷史上下文隔離・嚴禁腦補推算・反偷懶強制機制】

                一、 核心約束規則（違反任一項即判定回答失敗）：
                1. 歷史上下文徹底隔離：完全忽略本對話先前輪次中提及的數字。
                2. 絕對信任 Python 數據：下方的【今日基礎全景數據】是經過嚴格演算法計算的鐵證。你必須 100% 照抄這些價格、估值與狀態填入表格，嚴禁自行推算或竄改！【第一部分】表格必須涵蓋【今日基礎全景數據】裡「每一列」標的，一檔都不能少。
                3. 依賴提供的新聞：請運用下方提供的【原始官方公告與新聞】進行產業動態剖析。
                4. HTML 語法嚴格限制：全篇報告【嚴禁使用 Markdown 語法】，必須完全使用標準的 HTML 標籤渲染。範本中以 <!-- --> 包起來的說明文字絕對不要複製到輸出結果裡。
                5. 決策樹強制標示機率：在情境推演中，【必須】明確標註你預估的「發生機率」(如：機率 60%)。
                6. 🔴 絕對反偷懶機制：本次【核心股深度量化籌碼】中共有 {core_count} 檔核心股（{core_portfolio_str}）。你在第四部分【必須】產出 {core_count} 個獨立的 <div> 區塊，一檔都不能少！

                二、 重點類股分類（僅供第三部分新聞剖析參考）：
                1. 記憶體族群：華邦電 (2344)、南亞科 (2408)、創見 (2451)
                2. AI 高 CP 值/前景看好：緯穎 (6669)、奇鋐 (3017)、雙鴻 (3324)
                3. 金融業權值與補漲：富邦金 (2881)、兆豐金 (2886)、玉山金 (2884)、永豐金 (2890)、台中銀 (2812)、臺企銀 (2834)
                4. 高科技廠房營造龍頭：潤弘 (2597)

                三、 請依序輸出以下四個部分，直接輸出完整 HTML 代碼：

                <div style='background-color: #f8f9fa; padding: 20px; border-radius: 8px; font-family: sans-serif; color: #333;'>
                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px;'>【第一部分：量化估價與潛在上漲空間矩陣】</h4>
                  <table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; text-align: center;' border='1'>
                    <tr style='background-color: #e9ecef;'>
                      <th style='padding: 8px; border: 1px solid #ccc;'>股票代號與名稱</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>最新市價</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>便宜價(保守)</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>公允價值(基準)</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>昂貴價(樂觀)</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>當前狀態</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>市場隱含成長/ROE</th>
                    </tr>
                    <!-- 嚴格讀取【今日基礎全景數據】填入 -->
                  </table>

                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px; margin-top: 25px;'>【第二部分：估價模型與計算方法說明】</h4>
                  <ul style='font-size: 13px; line-height: 1.8; padding-left: 20px;'>
                    <li><b>科技與 AI 成長股（動態 PEG、基本面隱含 DCF 與反向估值檢核）：</b>採 Forward EPS 與可持續成長率計算動態 PEG，並以 NOPAT、ROIC、再投資率建構二階段 FCFF 模型交叉驗證；另以 Reverse DCF 反推市場隱含成長率。</li>
                    <li><b>景氣循環與記憶體類股（正常化淨值比估值）：</b>排除單年高峰暴衝本益比，改採歷史 P/B 與資產淨值進行週期位階評估。</li>
                    <li><b>金融業（四層資料驅動 RIM 超額報酬模型）：</b>以公司別設定正常化 ROE、差異化股權成本 (Ke) 與永續成長率 (g)，構建 Bear/Base/Bull 三維情境 Target P/B，並反推「市場隱含長期 ROE」作為客觀照妖鏡。</li>
                    <li><b>營造與一般傳產：</b>依在手訂單能見度、工程認列進度搭配歷史本益比區間估算。</li>
                  </ul>

                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px; margin-top: 25px;'>【第三部分：最新即時焦點消息面剖析】</h4>
                  <ul style='font-size: 13px; line-height: 1.8; padding-left: 20px;'>
                      <!-- 根據提供的【原始官方公告與新聞】，客觀剖析新聞事件對目前股價位階的影響。不提供買賣操作建議。 -->
                  </ul>
                  
                  <h4 style='color: #d32f2f; border-bottom: 2px solid #d32f2f; padding-bottom: 5px; margin-top: 30px;'>【第四部分：核心持股深度多空決策矩陣】</h4>
                  <!-- 本次共有 {core_count} 檔核心股：{core_portfolio_str}。針對每一檔重複以下 <div> 結構 -->
                  <div style='background-color: #ffffff; padding: 15px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px;'>
                    <h5 style='color: #333; margin-top: 0;'>[股票名稱] 籌碼與估值矩陣分析</h5>
                    <p style='font-size: 12px; line-height: 1.6; margin-bottom: 15px;'>
                       <b>基本面位階：</b> ...<br>
                       <b>籌碼動能：</b> ...<br>
                       <b>技術面：</b> ...
                    </p>
                    <h6 style='margin-bottom: 5px;'>走勢推演與操作情境</h6>
                    <ul style='font-size: 12px; line-height: 1.6; margin-top: 0;'>
                      <li><b>情境 A (機率 X%)：</b> ...</li>
                      <li><b>情境 B (機率 Y%)：</b> ...</li>
                      <li><b>情境 C (機率 Z%)：</b> ...</li>
                    </ul>
                  </div>
                </div>
                
                【今日基礎全景數據】
                {df_basic.to_string(index=False)}
                
                【原始官方公告與新聞】
                {official_text_for_ai}
                {news_text_for_ai}
                
                【核心股深度量化籌碼】
                {core_data_text}
                """
                
                # 🚀 升級點 3：修復導致系統崩潰的無效模型名稱，替換為官方正式端點
                target_models = [
                                    "gemini-3.8-flash",
                                    "gemini-3.7-flash",
                                    "gemini-3.6-flash",
                                    "gemini-3.5-flash",
                                    "gemini-3.5-flash-lite",
                                ]
                #target_models = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
                response = None
                
                for model_name in target_models:
                    try:
                        print(f"嘗試使用模型: {model_name}...")
                        for attempt in range(3):
                            try:
                                # 🚀 升級點 4：新的 Generate Content 呼叫語法
                                response = client.models.generate_content(
                                    model=model_name,
                                    contents=prompt,
                                    config=config
                                )
                                print(f"✅ API 請求成功 ({model_name})！")
                                break
                            except Exception as err:
                                # 🚀 升級點 5：不再靜音吞噬錯誤，印出真實阻擋原因
                                print(f"  [Attempt {attempt+1}] 呼叫錯誤: {err}")
                                if ("429" in str(err) or "504" in str(err) or "quota" in str(err).lower()) and attempt < 2: 
                                    time.sleep(15 * (attempt + 1))
                                else: 
                                    raise err
                        if response: break
                    except Exception as loop_err: 
                        print(f"❌ 模型 {model_name} 完全失敗: {loop_err}")
                        continue

                if not response: raise Exception("所有可用模型皆無法產生內容。請檢查 API Key 權限或配額。")
                
                final_html = response.text.strip()
                match = re.search(r"(<div.*?</div>)", final_html, re.DOTALL | re.IGNORECASE)
                if match: final_html = match.group(1)
                else:
                    final_html = re.sub(r"^```(?:html)?\n?", "", final_html, flags=re.IGNORECASE)
                    final_html = re.sub(r"\n?```$", "", final_html).strip()

                try:
                    def _has_real_analysis_block(html, name):
                        pattern = re.escape(name) + r".{0,10}(籌碼與估值矩陣分析|決策矩陣分析)"
                        return re.search(pattern, html) is not None

                    missing = [
                        item for item in PORTFOLIO
                        if item.get("is_core", False) and not _has_real_analysis_block(final_html, item["name"])
                    ]
                    if missing:
                        print(f"⚠️ 偵測到核心持股決策矩陣缺漏：{[m['name'] for m in missing]}，啟動針對性補寫...")
                        missing_data_text = ""
                        for item in missing:
                            data = core_data_dict.get(item["code"])
                            if not data: continue
                            missing_data_text += f"\n--- 【{data.get('name')} ({item['code']}) 深度量化籌碼與技術面】 ---\n"
                            for k, v in data.items():
                                if k not in ["name", "code"]: missing_data_text += f"{k}: {v}\n"

                        if missing_data_text:
                            fixup_prompt = f"""
                            你是量化投資經理。請只針對下方【核心股深度量化籌碼】列出的每一檔標的，各自產出一個獨立的 <div> 決策矩陣區塊（{len(missing)} 檔都要有，一檔都不能少），格式如下：

                            <div style='background-color: #ffffff; padding: 15px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px;'>
                              <h5 style='color: #333; margin-top: 0;'>[股票名稱] 籌碼與估值矩陣分析</h5>
                              <p style='font-size: 12px; line-height: 1.6; margin-bottom: 15px;'>
                                 <b>基本面位階：</b> ...<br>
                                 <b>籌碼動能：</b> ...<br>
                                 <b>技術面：</b> ...
                              </p>
                              <h6 style='margin-bottom: 5px;'>走勢推演與操作情境</h6>
                              <ul style='font-size: 12px; line-height: 1.6; margin-top: 0;'>
                                <li><b>情境 A (機率 X%)：</b> ...</li>
                                <li><b>情境 B (機率 Y%)：</b> ...</li>
                                <li><b>情境 C (機率 Z%)：</b> ...</li>
                              </ul>
                            </div>

                            嚴禁使用 Markdown 語法，只能輸出 HTML。

                            【核心股深度量化籌碼】
                            {missing_data_text}
                            """
                            for model_name in target_models:
                                try:
                                    print(f"嘗試補寫模型: {model_name}...")
                                    fixup_resp = client.models.generate_content(
                                        model=model_name,
                                        contents=fixup_prompt,
                                        config=config
                                    )
                                    fixup_html = fixup_resp.text.strip()
                                    fixup_match = re.search(r"(<div.*</div>)", fixup_html, re.DOTALL | re.IGNORECASE)
                                    if fixup_match: fixup_html = fixup_match.group(1)
                                    last_div_idx = final_html.rfind("</div>")
                                    if last_div_idx != -1 and fixup_html.strip().startswith("<div"):
                                        final_html = final_html[:last_div_idx] + fixup_html + final_html[last_div_idx:]
                                        print(f"✅ 補寫成功：{[m['name'] for m in missing]}")
                                    break
                                except Exception as fix_err: 
                                    print(f"  [補寫錯誤] 模型 {model_name}: {fix_err}")
                                    continue
                except Exception as e:
                    print(f"完整性檢查例外，略過不影響主報告: {e}")

                return final_html
            except Exception as e:
                return f"<div style='background-color: #ffeeba; color: #dc3545; padding: 15px; font-weight: bold; border-radius: 5px;'>⚠️ 系統警告：Gemini AI 生成失敗，原因：{e}</div>"

    def send_email_notify(self, df_basic, core_data_dict, today_str):
        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD: return
        analysis_html = self.get_news_and_analysis(df_basic, core_data_dict)
        msg = MIMEMultipart('related')
        msg['Subject'] = f"📊 【AI 量化投資組合決策矩陣】 {today_str}"
        msg['From'], msg['To'] = GMAIL_ADDRESS, GMAIL_ADDRESS
        html = f"<html><head><style>body {{ font-family: Arial, sans-serif; color: #333; }}</style></head><body><h2>📈 AI 投資組合動態儀表板 ({today_str})</h2>{analysis_html}</body></html>"
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html, 'html'))
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.send_message(msg)
            print("📤 Email 推播成功！")
        except Exception as e: print(f"📤 Email 推播失敗: {e}")

    def run(self):
        df_basic = self.calculate_basic_portfolio()
        core_data_dict = self.fetch_advanced_quant_data()
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"✅ 資料處理完畢，產出 {today_str} 估值報表與深度決策矩陣")
        self.send_email_notify(df_basic, core_data_dict, today_str)

if __name__ == "__main__":
    TaiwanMarketTracker().run()