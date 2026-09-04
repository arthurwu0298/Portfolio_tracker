# portfolio_tracker.py
import os
import time
import sqlite3
import requests
import pandas as pd
import yfinance as yf
import pandas_ta as ta  # 新增：用於精準計算 KD、RSI 等技術指標
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from portfolio_config import (
    PORTFOLIO, CASH_RESERVE, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, FINMIND_TOKEN
)
from valuation_engine import FinMindValuationEngine

DB_FILE = "portfolio_history.db"
TREND_CHART_FILE = "trend_chart.png"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

METHOD_MAP = {
    "yield": "預估殖利率",
    "pe": "本益比法",
    "pb": "淨值比法",
    "etf_yield": "歷史殖利率",
    "trend": "趨勢乖離法",
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
            else: self.fetch_errors.append(f"TWSE股價API回應異常 (HTTP {res1.status_code})")
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
            else: self.fetch_errors.append(f"TWSE估值API回應異常 (HTTP {res2.status_code})")
        except Exception as e: self.fetch_errors.append(f"TWSE估值API請求失敗: {e}")

        try:
            res3 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=15)
            if res3.status_code == 200:
                for item in res3.json(): self.tpex_prices[item["SecuritiesCompanyCode"]] = safe_float(item.get("Close"))
            else: self.fetch_errors.append(f"TPEx股價API回應異常 (HTTP {res3.status_code})")
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
            else: self.fetch_errors.append(f"TPEx估值API回應異常 (HTTP {res4.status_code})")
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
                        else: self.fetch_errors.append(f"{item['name']}({c}) YF備援無法取得價格")
                    if not mets or mets.get('pe', 0.0) == 0.0:
                        dy = safe_float(info.get("dividendYield", 0.0))
                        if dy > 0 and dy < 1: dy *= 100
                        new_metrics = {"pe": safe_float(info.get("trailingPE", 0.0)), "pb": safe_float(info.get("priceToBook", 0.0)), "yield": dy}
                        if m == "TWSE": self.twse_metrics[c] = new_metrics
                        else: self.tpex_metrics[c] = new_metrics
                except Exception as e: self.fetch_errors.append(f"{item['name']}({c}) YF備援抓取失敗: {e}")

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

            total_cost += (s * cp)
            total_mkt += (s * price)

            records.append({
                "代碼": c, "名稱": item["name"], "現價": price, 
                "本益比(PE)": current_pe, "淨值比(PB)": current_pb, "殖利率(%)": dyield,
                "指定估價法": method_ch, "自訂備註與限制": extra_note
            })

        self.save_to_db(total_cost, total_mkt, total_mkt + CASH_RESERVE, CASH_RESERVE, total_mkt - total_cost, round(((total_mkt - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0)
        self.plot_historical_trend()
        return pd.DataFrame(records)

    def fetch_advanced_quant_data(self):
        print("🔍 [階段二] 掃描核心持股 (is_core=True) 並抓取深度量化/籌碼數據...")
        core_data = {}
        # 設定抓取近期範圍，確保能涵蓋到最新交易日
        start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        
        for item in PORTFOLIO:
            if not item.get("is_core", False):
                continue
            
            c = item["code"]
            ticker_name = item["name"]
            print(f"  -> 處理核心標的: {ticker_name} ({c})")
            quant_info = {"name": ticker_name, "code": c}
            
            # 1. 技術面與動能 (使用 yfinance + pandas_ta)
            try:
                yf_ticker = f"{c}.TW" if item["market"] == "TWSE" else f"{c}.TWO"
                hist = yf.Ticker(yf_ticker).history(period="3mo")
                if not hist.empty:
                    hist.ta.kd(append=True)
                    hist.ta.rsi(length=14, append=True)
                    hist.ta.sma(length=20, append=True)
                    
                    latest = hist.iloc[-1]
                    quant_info["KD值"] = f"K: {latest.get('STOCHk_14_3_3', 0):.1f} / D: {latest.get('STOCHd_14_3_3', 0):.1f}"
                    quant_info["RSI(14)"] = f"{latest.get('RSI_14', 0):.1f}"
                    sma20 = latest.get('SMA_20', 1)
                    bias = ((latest['Close'] - sma20) / sma20) * 100
                    quant_info["20MA乖離率(BIAS)"] = f"{bias:.2f}%"
                    quant_info["最新成交量"] = f"{latest['Volume']/1000:.0f} 張"
            except Exception as e:
                quant_info["技術面抓取異常"] = str(e)

            # 2. 法人與信用籌碼 (使用 FinMind)
            if FINMIND_TOKEN:
                try:
                    # 抓取三大法人買賣超
                    res_inst = requests.get(
                        "https://api.finmindtrade.com/api/v4/data",
                        params={"dataset": "InstitutionalInvestorsBuySell", "data_id": c, "start_date": start_date, "token": FINMIND_TOKEN},
                        timeout=10
                    ).json()
                    if res_inst.get("msg") == "success" and res_inst.get("data"):
                        df_inst = pd.DataFrame(res_inst["data"])
                        latest_date = df_inst['date'].max()
                        latest_inst = df_inst[df_inst['date'] == latest_date]
                        net_buy = latest_inst.groupby('name')['buy_sell'].sum().to_dict()
                        # 處理不同券商命名差異
                        foreign = net_buy.get('外資及陸資投資', net_buy.get('外資及陸資(不含外資自營商)', 0))
                        trust = net_buy.get('投信', 0)
                        quant_info["三大法人最新動向日期"] = latest_date
                        quant_info["外資買賣超(張)"] = f"{foreign / 1000:.0f}"
                        quant_info["投信買賣超(張)"] = f"{trust / 1000:.0f}"
                except Exception as e:
                    self.fetch_errors.append(f"{ticker_name} 法人籌碼抓取失敗: {e}")

                try:
                    # 抓取融資券餘額
                    res_margin = requests.get(
                        "https://api.finmindtrade.com/api/v4/data",
                        params={"dataset": "TaiwanStockMarginPurchaseShortSale", "data_id": c, "start_date": start_date, "token": FINMIND_TOKEN},
                        timeout=10
                    ).json()
                    if res_margin.get("msg") == "success" and res_margin.get("data"):
                        df_margin = pd.DataFrame(res_margin["data"])
                        latest_margin = df_margin.iloc[-1]
                        quant_info["融資餘額(張)"] = f"{latest_margin.get('MarginPurchaseBalance', 0)}"
                        quant_info["融券餘額(張)"] = f"{latest_margin.get('ShortSaleBalance', 0)}"
                except Exception as e:
                    self.fetch_errors.append(f"{ticker_name} 融資券抓取失敗: {e}")

            core_data[c] = quant_info
            time.sleep(1.5) # 降低 FinMind 請求頻率避免被鎖

        return core_data

    def save_to_db(self, tc, tm, tnw, cash, pl, ret):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO history (date, total_cost, total_mkt, total_net_worth, cash_reserve, unrealized_pl, return_rate) VALUES (?, ?, ?, ?, ?, ?, ?)''', (datetime.now().strftime("%Y-%m-%d"), tc, tm, tnw, cash, pl, ret))
        conn.commit()
        conn.close()

    def plot_historical_trend(self):
        print("📊 繪製走勢對比圖 (前五大強勢股 vs 大盤基準)...")
        plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'Microsoft JhengHei', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        
        df_plot = pd.DataFrame()
        for item in PORTFOLIO:
            tkr = f"{item['code']}.TW" if item['market'] == "TWSE" else f"{item['code']}.TWO"
            try:
                hist = yf.Ticker(tkr).history(period="6mo")
                if not hist.empty and len(hist) > 10:
                    base_price = hist['Close'].iloc[0]
                    # 計算累積報酬率
                    df_plot[item['name']] = (hist['Close'] / base_price - 1) * 100
            except Exception as e:
                print(f"抓取 {item['name']} 歷史資料失敗: {e}")
                
        if not df_plot.empty:
            # 取得最後一天報酬並排序，篩選出最強 5 檔與 0050 基準
            final_returns = df_plot.iloc[-1].sort_values(ascending=False)
            benchmark = next((col for col in df_plot.columns if '0050' in col), None)
            top_5 = [name for name in final_returns.index if name != benchmark][:5]
            plot_targets = top_5 + ([benchmark] if benchmark else [])

            plt.figure(figsize=(10, 6))
            for column in plot_targets:
                if column == benchmark:
                    plt.plot(df_plot.index, df_plot[column], label=f"基準 ({column})", linewidth=3.0, color='#d62728', linestyle='-')
                else:
                    plt.plot(df_plot.index, df_plot[column], label=column, linewidth=1.5, alpha=0.85)
                    
            plt.title('投資組合動能最強 Top 5 vs 大盤基準 (近半年累積報酬率 %)', fontsize=15, fontweight='bold', pad=15)
            plt.xlabel('日期', fontsize=12)
            plt.ylabel('累積報酬率 (%)', fontsize=12)
            plt.axhline(0, color='black', linewidth=1.2, linestyle='--')
            
            plt.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=10)
            plt.grid(axis='y', linestyle='--', alpha=0.5)
            plt.tight_layout()
            plt.savefig(TREND_CHART_FILE, dpi=120)
            plt.close()

    def get_news_and_analysis(self, df_basic, core_data_dict):
        print("📰 [階段三] 抓取官方公告與媒體新聞，啟動 AI 雙層分析...")
        core_tickers = {item["code"]: item["name"] for item in PORTFOLIO}
        
        # 抓取新聞與重訊 (維持原有邏輯)
        news_text_for_ai = ""
        for code, name in core_tickers.items():
            try:
                tkr = yf.Ticker(f"{code}.TW")
                news = tkr.news
                if news:
                    count = 0
                    for n in news:
                        title = n['title']
                        news_text_for_ai += f"[{name} {code}] {title}\n"
                        count += 1
                        if count >= 2: break
            except Exception: pass
        if not news_text_for_ai: news_text_for_ai = "今日暫無重大媒體新聞。"

        official_text_for_ai = ""
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
        except Exception as e: print(f"重大訊息抓取失敗: {e}")
        if not official_text_for_ai: official_text_for_ai = "無官方重大公告。"

        # 整理核心股量化數據字串供 AI 推演
        core_data_text = ""
        if core_data_dict:
            for code, data in core_data_dict.items():
                core_data_text += f"\n--- 【{data.get('name')} ({code}) 深度量化籌碼與技術面】 ---\n"
                for k, v in data.items():
                    if k not in ["name", "code"]:
                        core_data_text += f"{k}: {v}\n"
        else:
            core_data_text = "今日無指定核心持股 (未於 config 設定 is_core: True) 進行深度推演。"

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
                
                prompt = f"""
                你是一位頂尖的量化投資經理與實戰交易員。請根據提供的「基礎全景數據」與「核心股深度量化籌碼」，產出專屬的雙層盤後決策報告。
                
                【絕對輸出格式要求】
                請嚴格依照下方 HTML 與文字結構輸出，不要使用 markdown 語法 (```html) 包裝，直接輸出 HTML：

                <div style='background-color: #f8f9fa; padding: 20px; border-radius: 8px; font-family: sans-serif; color: #333;'>
                  <p style='font-size: 14px; margin-bottom: 20px;'><b>截至 {today_str_for_prompt} 最新盤後，投資組合綜合評估：</b><br>
                  <!-- 根據大盤趨勢與投資組合整體狀態，寫約 100 字摘要 --></p>

                  <h4 style='color: #0056b3; border-bottom: 2px solid #0056b3; padding-bottom: 5px; margin-top: 25px;'>一、 全投組基礎估值掃描</h4>
                  <table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; text-align: center;'>
                    <tr style='background-color: #e9ecef;'>
                      <th style='border: 1px solid #ccc; padding: 8px;'>標的</th>
                      <th style='border: 1px solid #ccc; padding: 8px;'>現價</th>
                      <th style='border: 1px solid #ccc; padding: 8px;'>便宜價</th>
                      <th style='border: 1px solid #ccc; padding: 8px;'>合理價</th>
                      <th style='border: 1px solid #ccc; padding: 8px;'>昂貴(目標)價</th>
                      <th style='border: 1px solid #ccc; padding: 8px;'>當前狀態</th>
                    </tr>
                    <!-- 根據【基礎全景數據】生成所有標的表格。必須填寫明確估算數字與狀態(如: 便宜加碼、合理續抱、偏高留意) -->
                  </table>

                  <h4 style='color: #d32f2f; border-bottom: 2px solid #d32f2f; padding-bottom: 5px; margin-top: 30px;'>二、 核心持股深度多空決策矩陣</h4>
                  <!-- 針對每一檔【核心股深度量化籌碼】裡的股票，重複以下結構 -->
                  <div style='background-color: #ffffff; padding: 15px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px;'>
                    <h5 style='color: #333; margin-top: 0;'>[填寫股票名稱與代號] 量化籌碼、估值與多空交易決策矩陣</h5>
                    
                    <p style='font-size: 12px; line-height: 1.6; margin-bottom: 15px;'>
                       <b>基本面估值：</b> <!-- 簡述 PB/PE 位置與盈虧比 --><br>
                       <b>技術動能：</b> <!-- 根據傳入的 KD/RSI/乖離率 判斷是否過熱或超賣 --><br>
                       <b>籌碼結構：</b> <!-- 根據傳入的外資/投信買賣超與融資券，判斷籌碼流向 -->
                    </p>
                    
                    <h6 style='margin-bottom: 5px;'>下週走勢決策樹與操作腳本</h6>
                    <pre style='background-color: #2b2b2b; color: #a9b7c6; padding: 10px; font-size: 12px; overflow-x: auto; border-radius: 4px; font-family: monospace;'>
                    <!-- 根據數據，繪製 ASCII Art 決策樹 (包含強勢軋空/量縮換手/籌碼背離 三種情境) -->
                    </pre>
                    
                    <ul style='font-size: 13px; line-height: 1.6; padding-left: 20px;'>
                      <!-- 給出這三種情境對應的觸發訊號、防守點位與停利建議 -->
                    </ul>
                  </div>
                  
                </div>
                
                【今日基礎全景數據 (包含 PE/PB/Yield)】
                {df_basic.to_string(index=False)}
                
                【原始官方公告與新聞】
                {official_text_for_ai}
                {news_text_for_ai}
                
                【核心股深度量化籌碼】
                {core_data_text}
                """
                
                # 雙模型輪詢 + 重試機制
                target_models = ['gemini-2.5-flash', 'gemini-3.8-flash', 'gemini-flash-latest', 'gemini-1.5-flash']
                response = None
                api_call_count = 0 

                for model_name in target_models:
                    try:
                        print(f"嘗試使用模型: {model_name}...")
                        model = genai.GenerativeModel(model_name)
                        for attempt in range(3):
                            try:
                                api_call_count += 1
                                print(f"➡️ 正在發送第 {api_call_count} 次 API 請求 (目標模型: {model_name}, 重試次數: {attempt})...")
                                response = model.generate_content(prompt, safety_settings=safety_settings)
                                print(f"✅ API 請求成功！本次排程總共消耗了 {api_call_count} 次 API 額度。")
                                break
                            except Exception as err:
                                if "429" in str(err) and attempt < 2:
                                    wait_seconds = 25 * (attempt + 1)
                                    print(f"⚠️ 觸發頻率限制 (429)，等待 {wait_seconds} 秒後重試...")
                                    time.sleep(wait_seconds)
                                else:
                                    raise err
                        if response:
                            break
                    except Exception as model_err:
                        if "404" in str(model_err) or "429" in str(model_err):
                            print(f"⚠️ 模型 {model_name} 無法使用 (404/429)，嘗試切換下一個備援模型...")
                            continue
                        raise model_err

                if not response:
                    raise Exception(f"所有可用模型皆無法產生內容。總共嘗試呼叫了 {api_call_count} 次 API。")

                final_html = response.text.strip()
                if final_html.startswith("```html"): final_html = final_html[7:]
                if final_html.endswith("```"): final_html = final_html[:-3]
                
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

        error_banner = ""
        if self.fetch_errors:
            error_items = "".join([f"<li>{e}</li>" for e in self.fetch_errors])
            error_banner = f'''<div style="background-color:#fff3cd; border:1px solid #ffeeba; padding:10px 15px; border-radius:5px; margin-bottom:15px; font-size:12px;"><b>⚠️ 本次執行有資料抓取異常 (AI 將以備援數據推估)：</b><ul style="margin:6px 0 0 20px;">{error_items}</ul></div>'''

        html = f'''
        <html><head><style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
        </style></head><body>
          <h2>📈 AI 投資組合動態儀表板 ({today_str})</h2>
          {error_banner}
          {analysis_html}
          <div style="margin-top: 30px; text-align: center;">
            <img src="cid:trend_chart" style="max-width: 100%; border: 1px solid #eee; border-radius: 8px; padding: 10px; background-color: #fff;">
          </div>
        </body></html>
        '''

        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html, 'html'))
        
        if os.path.exists(TREND_CHART_FILE):
            with open(TREND_CHART_FILE, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<trend_chart>')
                msg.attach(img)
                
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
    tracker = TaiwanMarketTracker()
    tracker.run()