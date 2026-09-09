# portfolio_tracker.py
import os
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

from portfolio_config import (
    PORTFOLIO, CASH_RESERVE, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, FINMIND_TOKEN
)
from valuation_engine import FinMindValuationEngine

DB_FILE = "portfolio_history.db"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

METHOD_MAP = {
    "yield": "預估殖利率",
    "pe": "本益比法",
    "pb": "淨值比法",
    "etf_yield": "歷史殖利率",
    "trend": "趨勢乖離法",
    "rim": "超額報酬模型",
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
                except Exception as e: pass

    def calculate_basic_portfolio(self):
        self.fetch_market_data()
        records = []
        total_mkt, total_cost = 0, 0

        for item in PORTFOLIO:
            c, m, cp, s = item["code"], item["market"], item["cost_per_share"], item["shares"]
            price = self.twse_prices.get(c) if m == "TWSE" else self.tpex_prices.get(c)
            price = price or cp

            metrics = self.twse_metrics.get(c, {}) if m == "TWSE" else self.tpex_metrics.get(c, {})
            current_pe = metrics.get("pe", 0.0)
            current_pb = metrics.get("pb", 0.0)
            dyield = metrics.get("yield", 0.0)

            v_method = item.get("valuation_method", "manual")
            method_ch = METHOD_MAP.get(v_method, "手動設定")
            extra_note = item.get("note", "")

            cheap_price, fair_price, target_price = 0.0, 0.0, 0.0
            
            if v_method == "pe":
                res = self.valuation_engine.calc_pe_valuation(c, price, current_pe)
                if res: cheap_price, fair_price, target_price, _ = res
            elif v_method == "pb":
                res = self.valuation_engine.calc_pb_valuation(c, price, current_pb)
                if res: cheap_price, fair_price, target_price, _ = res
            elif v_method == "trend":
                res = self.valuation_engine.calc_price_trend_valuation(c, price)
                if res: cheap_price, fair_price, target_price, _, _ = res
            elif v_method == "rim":
                res = self.valuation_engine.calc_residual_income_valuation(c, price, current_pb)
                if res and len(res) == 4: cheap_price, fair_price, target_price, _ = res
                method_ch = "超額報酬模型(RIM)"
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

                # 嚴格由 Python 判定當前位階
            if price > 0 and fair_price > 0:
                if price <= cheap_price:
                    current_status = "便宜加碼"
                elif price >= target_price:
                    current_status = "達標停利"
                elif price >= fair_price + (target_price - fair_price) * 0.7:
                    current_status = "偏高留意"
                else:
                    current_status = "合理續抱"
            else:
                # 🛑 只要算不出合理價，就誠實標示資料不足，絕不顯示續抱
                current_status = "⚠️ 資料不足/模型失效"

            total_cost += (s * cp)
            total_mkt += (s * price)

            records.append({
                "代碼": c, "名稱": item["name"], "現價": price, 
                "本益比(PE)": current_pe, "淨值比(PB)": current_pb, "殖利率(%)": dyield,
                "指定估價法": method_ch, 
                "便宜價": cheap_price, "合理價": fair_price, "昂貴(目標)價": target_price,
                "當前狀態": current_status, "自訂備註與限制": extra_note
            })

        self.save_to_db(total_cost, total_mkt, total_mkt + CASH_RESERVE, CASH_RESERVE, total_mkt - total_cost, round(((total_mkt - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0)
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

                        # 🚀 完全按照 HTML 中的英文鍵值讀取 FinMind 資料
                        f_net, f_cons, f_score = get_inst_trend('Foreign_Investor')
                        t_net, t_cons, t_score = get_inst_trend('Investment_Trust')
                        
                        # 自營商邏輯
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

    # 🚀 將漏掉的 save_to_db 補在這裡：
    def save_to_db(self, tc, tm, tnw, cash, pl, ret):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO history (date, total_cost, total_mkt, total_net_worth, cash_reserve, unrealized_pl, return_rate) VALUES (?, ?, ?, ?, ?, ?, ?)''', (datetime.now().strftime("%Y-%m-%d"), tc, tm, tnw, cash, pl, ret))
        conn.commit()
        conn.close()

    def get_news_and_analysis(self, df_basic, core_data_dict):
        print("📰 [階段三] 抓取官方公告與媒體新聞，啟動 AI 雙層分析...")
        
        # 🚀 修正 1: 取得核心名單，並保留 market 屬性以分辨上市 (.TW) 或上櫃 (.TWO)
        core_portfolio = [item for item in PORTFOLIO if item.get("is_core", False)]
        
        news_text_for_ai = ""
        for item in core_portfolio:
            code = item["code"]
            name = item["name"]
            market = item["market"]
            try:
                # 判斷上市或上櫃後綴
                suffix = ".TW" if market == "TWSE" else ".TWO"
                tkr = yf.Ticker(f"{code}{suffix}")
                news = tkr.news
                if news:
                    count = 0
                    for n in news:
                        title = n['title']
                        news_text_for_ai += f"[{name} {code}] {title}\n"
                        count += 1
                        if count >= 2: break
            except Exception as e:
                pass
                
        if not news_text_for_ai: news_text_for_ai = "今日暫無重大媒體新聞。"

        official_text_for_ai = ""
        core_tickers = {item["code"]: item["name"] for item in PORTFOLIO}
        try:
            res_twse = self.session.get("[https://openapi.twse.com.tw/v1/opendata/t187ap04_L](https://openapi.twse.com.tw/v1/opendata/t187ap04_L)", timeout=10)
            res_tpex = self.session.get("[https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O)", timeout=10)
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
        except Exception as e: print(f"重大訊息抓取失敗: {e}")
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
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                
                safety_settings = [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
                
                today_str_for_prompt = datetime.now().strftime("%Y 年 %m 月 %d 日")
                
                # 🚀 修正 2: 移除強制聯網要求，改為「嚴格依賴 Python 提供的數據與新聞」
                prompt = f"""
                你是一位頂尖的量化投資經理、實戰交易員與財經專欄主編。請根據下方 Python 引擎計算的「基礎全景數據」、「官方新聞」與「核心股深度量化籌碼」，產出專業盤後報告。
                
                /reset_data
                【系統指令：嚴格數據依賴・歷史上下文隔離・嚴禁腦補推算】

                一、 核心約束規則（違反任一項即判定回答失敗）：
                1. 歷史上下文徹底隔離：完全忽略本對話先前輪次中提及的數字。
                2. 絕對信任 Python 數據：下方的【今日基礎全景數據】是經過嚴格演算法計算的鐵證。你必須 100% 照抄這些價格、估值與狀態填入表格，嚴禁自行推算或竄改！
                3. 依賴提供的新聞：請運用下方提供的【原始官方公告與新聞】進行產業動態剖析。
                4. HTML 語法嚴格限制：全篇報告【嚴禁使用 Markdown 語法】（不可使用 **粗體** 或 | 表格 |），必須完全使用標準的 HTML 標籤渲染。

                二、 查核與分析標的清單：
                1. 記憶體族群：華邦電 (2344)、南亞科 (2408)、創見 (2451)
                2. AI 高 CP 值/前景看好：緯穎 (6669)、奇鋐 (3017)、雙鴻 (3324)
                3. 金融業權值與補漲：富邦金 (2881)、兆豐金 (2886)、玉山金 (2884)、永豐金 (2890)、台中銀 (2812)、臺企銀 (2834)
                4. 高科技廠房營造龍頭：潤弘 (2597)

                三、 請依序輸出以下四個部分，直接輸出完整 HTML 代碼：

                <div style='background-color: #f8f9fa; padding: 20px; border-radius: 8px; font-family: sans-serif; color: #333;'>
                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px;'>【第一部分：量化估價與潛在上漲空間矩陣】</h4>
                  <p style='font-size: 12px; margin-bottom: 10px;'>以 Python 引擎驗證的真實收盤價為基準，列出：</p>
                  <table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; text-align: center;' border='1'>
                    <tr style='background-color: #e9ecef;'>
                      <th style='padding: 8px; border: 1px solid #ccc;'>股票代號與名稱</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>最新市價</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>便宜價</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>公允價值</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>昂貴價</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>當前狀態</th>
                      <th style='padding: 8px; border: 1px solid #ccc;'>潛在上漲空間 (距公允值)</th>
                    </tr>
                    <!-- 嚴格讀取【今日基礎全景數據】填入 TR 標籤。潛在上漲空間請自行以 (公允價值-市價)/市價 計算百分比。 -->
                  </table>

                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px; margin-top: 25px;'>【第二部分：估價模型與計算方法說明】</h4>
                  <ul style='font-size: 13px; line-height: 1.8; padding-left: 20px;'>
                    <li><b>科技成長股 (Forward P/E)：</b>使用預估當年度 EPS 配合歷史 PE 中樞判定。</li>
                    <li><b>景氣循環記憶體 (H-Model)：</b>短期爆發成長率上限放寬至 80%，平滑過渡至 2% 永續成長。</li>
                    <li><b>金融/傳產 (RIM 超額報酬模型)：</b>取近三年 ROE 加權移動平均，推導公允淨值比(Target P/B)。</li>
                  </ul>

                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px; margin-top: 25px;'>【第三部分：最新即時焦點消息面剖析與操作建議】</h4>
                  <ul style='font-size: 13px; line-height: 1.8; padding-left: 20px;'>
                    <!-- 根據提供的【原始官方公告與新聞】，精煉記憶體、AI、金融族群及潤弘的最新動態，並短評對估值的影響。給出關鍵支撐防守價位。 -->
                  </ul>
                  
                  <h4 style='color: #d32f2f; border-bottom: 2px solid #d32f2f; padding-bottom: 5px; margin-top: 30px;'>【第四部分：核心持股深度多空決策矩陣】</h4>
                  <!-- 針對每一檔核心股重複以下結構 -->
                  <div style='background-color: #ffffff; padding: 15px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px;'>
                    <h5 style='color: #333; margin-top: 0;'>[股票名稱] 籌碼與估值矩陣分析</h5>
                    <p style='font-size: 12px; line-height: 1.6; margin-bottom: 15px;'>
                       <b>基本面位階：</b> <!-- 引用上方表格狀態 --><br>
                       <b>籌碼動能：</b> <!-- 引用傳入的籌碼分數與散戶狀態 --><br>
                       <b>技術面：</b> <!-- 簡述技術狀態 -->
                    </p>
                    <h6 style='margin-bottom: 5px;'>走勢決策樹與操作腳本</h6>
                    <pre style='background-color: #2b2b2b; color: #a9b7c6; padding: 10px; font-size: 12px; overflow-x: auto; border-radius: 4px; font-family: monospace;'>
                    <!-- 依據紀律繪製 ASCII 決策樹 (包含籌碼共振/左側下殺/量縮洗盤 等實戰情境) -->
                    </pre>
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
                
                target_models = ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite']
                response = None
                
                for model_name in target_models:
                    try:
                        print(f"嘗試使用模型: {model_name}...")
                        model = genai.GenerativeModel(model_name) # 無工具版本
                        for attempt in range(3):
                            try:
                                response = model.generate_content(prompt, safety_settings=safety_settings, request_options={"timeout": 150})
                                print(f"✅ API 請求成功！")
                                break
                            except Exception as err:
                                err_str = str(err).lower()
                                if "429" in err_str and ("per day" in err_str or "perday" in err_str):
                                    raise err
                                elif ("429" in err_str or "504" in err_str or "deadline" in err_str) and attempt < 2:
                                    time.sleep(25 * (attempt + 1))
                                else: raise err
                        if response: break
                    except: continue

                if not response: raise Exception(f"所有可用模型皆無法產生內容。")
                
                # 🚀 修正 3: 更強壯的 Markdown 標籤清除法
                final_html = response.text.strip()
                if final_html.startswith("```"):
                    lines = final_html.split("\n")
                    if lines[0].startswith("```"): lines = lines[1:]
                    if lines[-1].startswith("```"): lines = lines[:-1]
                    final_html = "\n".join(lines).strip()
                    if final_html.startswith("html"): final_html = final_html[4:].strip()

                return final_html
            except Exception as e:
                print(f"Gemini API 呼叫失敗: {e}")
                return f"<div style='background-color: #ffeeba; color: #dc3545; padding: 15px; font-weight: bold; border-radius: 5px; margin-bottom: 20px;'>⚠️ 系統警告：Gemini AI 生成失敗，原因：{e}</div>"

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