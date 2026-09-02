# portfolio_tracker.py
import os
import sqlite3
import requests
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from portfolio_config import (
    PORTFOLIO, CASH_RESERVE, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, FINMIND_TOKEN,
    EXTREME_VALUATION_PERCENTILE, MOMENTUM_YOY_THRESHOLD
)
from valuation_engine import FinMindValuationEngine

DB_FILE = "portfolio_history.db"
CHART_FILE = "valuation_chart.png"

# 新增：接收 Gemini API Key
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
        print("📥 抓取 TWSE / TPEx 最新報價與本益比資料...")
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

    def calculate(self):
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

            v_method = item.get("valuation_method", "manual")
            method_ch = METHOD_MAP.get(v_method, "手動設定")
            cheap, fair, target = 0, 0, 0
            status, extra_note = "⚪ 觀望", item.get("note", "")
            dyield = metrics.get("yield", 0.0)

            if v_method == "etf_yield":
                recent_div = self.valuation_engine.get_recent_dividend(c)
                dyield = round((recent_div / price) * 100, 2) if price > 0 and recent_div > 0 else dyield
                ty = item.get("target_yields", {})
                if ty: y_c, y_f, y_t = ty.get('cheap', 0), ty.get('fair', 0), ty.get('target', 0)
                else: y_c, y_f, y_t = self.valuation_engine.calc_yield_percentile_bounds(c)

                p_c = round(recent_div / (y_c / 100), 2) if y_c > 0 and recent_div > 0 else 0
                p_f = round(recent_div / (y_f / 100), 2) if y_f > 0 and recent_div > 0 else 0
                p_t = round(recent_div / (y_t / 100), 2) if y_t > 0 and recent_div > 0 else 0
                cheap, fair, target = f"{p_c} ({y_c}%)" if p_c > 0 else "-", f"{p_f} ({y_f}%)" if p_f > 0 else "-", f"{p_t} ({y_t}%)" if p_t > 0 else "-"

                if dyield >= y_c and y_c > 0: status = "🟢 便宜 (加碼)"
                elif y_f <= dyield < y_c: status = "🔵 合理 (續抱)"
                elif y_t < dyield < y_f: status = "🟡 偏高 (留意)"
                elif dyield <= y_t and y_t > 0: status = "🔴 達標 (停利)"

            elif v_method == "trend":
                recent_div = self.valuation_engine.get_recent_dividend(c)
                dyield = round((recent_div / price) * 100, 2) if price > 0 and recent_div > 0 else dyield
                cheap, fair, target, current_dev, pct = self.valuation_engine.calc_price_trend_valuation(c, price)
                if pct is not None:
                    if pct <= 20: status = f"🟢 相對趨勢偏弱 (乖離率第{pct}百分位)"
                    elif 20 < pct <= 80: status = f"🔵 相對趨勢正常 (乖離率第{pct}百分位)"
                    elif 80 < pct <= 95: status = f"🟡 相對趨勢偏熱 (乖離率第{pct}百分位)"
                    else: status = f"🟠 乖離創高 (乖離率第{pct}百分位，留意非賣訊)"
                    dynamic_note = f"現在乖離率 {current_dev}%"
                    extra_note = f"{extra_note}；{dynamic_note}" if extra_note else dynamic_note
                else: status = "⚪ 資料不足"

            elif v_method == "yield":
                ty = item.get("target_yields", {})
                if ty: y_c, y_f, y_t = ty.get('cheap', 0), ty.get('fair', 0), ty.get('target', 0)
                else: y_c, y_f, y_t = self.valuation_engine.calc_yield_percentile_bounds(c)

                projected_eps = self.valuation_engine.get_annualized_eps(c)
                if projected_eps <= 0: projected_eps = price / current_pe if current_pe > 0 else 0.0

                projected_div = projected_eps * item.get("payout_ratio", 0.8)
                dyield = round((projected_div / price) * 100, 2) if price > 0 else 0.0

                p_c = round(projected_div / (y_c / 100), 1) if y_c > 0 else 0
                p_f = round(projected_div / (y_f / 100), 1) if y_f > 0 else 0
                p_t = round(projected_div / (y_t / 100), 1) if y_t > 0 else 0
                cheap, fair, target = f"{p_c} ({y_c}%)" if p_c > 0 else "-", f"{p_f} ({y_f}%)" if p_f > 0 else "-", f"{p_t} ({y_t}%)" if p_t > 0 else "-"

                if dyield >= y_c and y_c > 0: status = "🟢 便宜 (加碼)"
                elif y_f <= dyield < y_c: status = "🔵 合理 (續抱)"
                elif y_t < dyield < y_f: status = "🟡 偏高 (留意)"
                elif dyield <= y_t and y_t > 0: status = "🔴 達標 (停利)"
                
                # ⬇️ 請替換為以下放寬條件的新寫法 ⬇️
                stock_div, actual_cash_div, div_year_eps = self.valuation_engine.get_stock_dividend_info(c)
                if stock_div > 0:
                    stock_note = f"另有股票股利 {stock_div} 元 (未列入估值)"
                    if div_year_eps > 0:
                        total_payout_pct = round((actual_cash_div + stock_div) / div_year_eps * 100, 1)
                        stock_note = f"另有股票股利 {stock_div} 元；總配發率約 {total_payout_pct}% (未列入估值)"
                    extra_note = f"{extra_note}；{stock_note}" if extra_note else stock_note
            else:
                val_percentile = None
                if v_method == "manual": cheap, fair, target = item.get("cheap", 0), item.get("fair", 0), item.get("target", 0)
                elif v_method == "pe": cheap, fair, target, val_percentile = self.valuation_engine.calc_pe_valuation(c, price, current_pe)
                elif v_method == "pb": cheap, fair, target, val_percentile = self.valuation_engine.calc_pb_valuation(c, price, current_pb)

                if price <= cheap and cheap > 0: status = "🟢 便宜 (加碼)"
                elif cheap < price <= fair: status = "🔵 合理 (續抱)"
                elif fair < price < target: status = "🟡 偏高 (留意)"
                elif price >= target and target > 0: status = "🔴 達標 (停利)"

                if val_percentile is not None and val_percentile >= EXTREME_VALUATION_PERCENTILE:
                    momentum = self.valuation_engine.get_revenue_momentum(c)
                    if momentum and momentum["accelerating"] and momentum["latest_yoy"] > MOMENTUM_YOY_THRESHOLD:
                        status = f"🟣 結構多頭 (估值第{val_percentile}百分位，營收同步加速)"
                    else:
                        status = f"🔴 估值偏熱 (估值第{val_percentile}百分位，慎防情緒推升)"

            total_cost += (s * cp)
            total_mkt += (s * price)

            records.append({
                "代碼": c, "名稱": item["name"], "現價": price, "殖利率(%)": dyield,
                "便宜價": cheap, "合理價": fair, "目標價": target,
                "狀態": status, "估值法": method_ch, "備註": extra_note
            })

        df = pd.DataFrame(records)
        self.save_to_db(total_cost, total_mkt, total_mkt + CASH_RESERVE, CASH_RESERVE, total_mkt - total_cost, round(((total_mkt - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0)
        self.plot_valuation_discount(df)
        return df

    def save_to_db(self, tc, tm, tnw, cash, pl, ret):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO history (date, total_cost, total_mkt, total_net_worth, cash_reserve, unrealized_pl, return_rate) VALUES (?, ?, ?, ?, ?, ?, ?)''', (datetime.now().strftime("%Y-%m-%d"), tc, tm, tnw, cash, pl, ret))
        conn.commit()
        conn.close()

    def plot_valuation_discount(self, df):
        if df.empty: return
        plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'Microsoft JhengHei', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False

        data = []
        for _, row in df.iterrows():
            f_val = row.get('合理價', 0)
            price = row.get('現價', 0)
            try:
                if isinstance(f_val, str): f_val = float(f_val.split(' ')[0].replace(',', ''))
                else: f_val = float(f_val)
            except: f_val = 0
            
            if f_val > 0 and price > 0:
                diff_pct = (price - f_val) / f_val * 100
                data.append({'Name': row['名稱'], 'Diff': diff_pct})

        if not data: return
        df_plot = pd.DataFrame(data).sort_values('Diff')
        plt.figure(figsize=(10, 8))
        colors = ['#28a745' if x <= 0 else '#dc3545' for x in df_plot['Diff']]
        bars = plt.barh(df_plot['Name'], df_plot['Diff'], color=colors, alpha=0.8)

        plt.axvline(0, color='black', linewidth=1.2, linestyle='--')
        plt.title('現價與「合理價」之折溢價幅度 (%)', fontsize=15, fontweight='bold', pad=15)
        plt.xlabel('← 便宜 (折價) ｜ 偏高/熱 (溢價) →', fontsize=12)

        for bar in bars:
            width = bar.get_width()
            label_x_pos = width + 1.5 if width > 0 else width - 1.5
            ha = 'left' if width > 0 else 'right'
            plt.text(label_x_pos, bar.get_y() + bar.get_height()/2, f'{width:+.1f}%', va='center', ha=ha, fontsize=10, fontweight='bold')

        plt.margins(x=0.2)
        plt.grid(axis='x', linestyle='--', alpha=0.4)
        plt.tight_layout()
        plt.savefig(CHART_FILE, dpi=120)
        plt.close()

    # --- 新增：動態抓取「官方公告」+「媒體新聞」，並生成 AI 評估 ---
    def get_news_and_analysis(self, df):
        print("📰 正在動態抓取投資組合標的最新官方公告與媒體新聞...")
        
        core_tickers = {item["code"]: item["name"] for item in PORTFOLIO}
        
        # 1. 抓取 Yahoo 媒體新聞 (市場情緒與前瞻)
        news_text_for_ai = ""
        news_html = "<h3 style='margin-top: 30px;'>📰 媒體最新市場消息 (近3日)</h3><ul style='font-size: 13px; line-height: 1.6;'>"
        has_news = False
        
        for code, name in core_tickers.items():
            try:
                tkr = yf.Ticker(f"{code}.TW")
                news = tkr.news
                if news:
                    ticker_news_count = 0
                    for n in news:
                        pub_time = datetime.fromtimestamp(n['providerPublishTime'])
                        if datetime.now() - pub_time < timedelta(days=3):
                            pub_time_str = pub_time.strftime('%Y-%m-%d')
                            title = n['title']
                            link = n['link']
                            
                            news_html += f"<li><b>[{name} {code}]</b> {pub_time_str} - <a href='{link}'>{title}</a></li>"
                            news_text_for_ai += f"[{name} {code}] {title}\n"
                            
                            ticker_news_count += 1
                            if ticker_news_count >= 2: break
                    if ticker_news_count > 0: has_news = True
            except Exception:
                pass
                
        news_html += "</ul>"
        if not has_news:
            news_html = "<h3 style='margin-top: 30px;'>📰 媒體最新市場消息</h3><p style='font-size: 13px;'>投資組合標的近 3 日暫無重大新聞。</p>"
            news_text_for_ai = "今日暫無重大媒體新聞。"

        # 2. 抓取公開資訊觀測站 (官方絕對事實)
        official_text_for_ai = ""
        official_html = "<h3 style='margin-top: 20px;'>🏛️ 官方重大訊息公告 (公開資訊觀測站)</h3><ul style='font-size: 13px; line-height: 1.6;'>"
        has_official = False
        
        try:
            # 同時抓取上市 (TWSE) 與上櫃 (TPEx) 的最新重大訊息
            res_twse = self.session.get("https://openapi.twse.com.tw/v1/opendata/t187ap04_L", timeout=10)
            res_tpex = self.session.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O", timeout=10)
            
            mops_data = []
            if res_twse.status_code == 200: mops_data.extend(res_twse.json())
            if res_tpex.status_code == 200: mops_data.extend(res_tpex.json())
            
            for item in mops_data:
                code = item.get("公司代號", item.get("SecuritiesCompanyCode", ""))
                if code in core_tickers:
                    date_str = item.get("發言日期", "")
                    time_str = item.get("發言時間", "")
                    title = item.get("主旨", "")
                    
                    official_html += f"<li><b>[{core_tickers[code]} {code}]</b> {date_str} {time_str} - {title}</li>"
                    official_text_for_ai += f"[{core_tickers[code]} {code}] {date_str} {title}\n"
                    has_official = True
        except Exception as e:
            print(f"重大訊息抓取失敗: {e}")
            
        official_html += "</ul>"
        if not has_official:
            official_html = "<h3 style='margin-top: 20px;'>🏛️ 官方重大訊息公告</h3><p style='font-size: 13px;'>近期暫無官方重大訊息。</p>"
            official_text_for_ai = "無官方重大公告。"

        # 3. 呼叫 Gemini 進行綜合交叉比對
        ai_html = ""
        if GEMINI_API_KEY:
            print("🤖 正在呼叫 Gemini API 撰寫今日盤後分析...")
            try:
                import google.generativeai as genai
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel('gemini-1.5-flash')
                
                ai_df = df[['名稱', '現價', '狀態', '估值法']].copy()
                
                # 提示詞升級：要求嚴格比對官方公告與媒體報導
                prompt = f"""
                你是一位量化投資經理。請根據以下「今日投資組合估值狀態」、「官方重大公告」與「媒體最新新聞」，寫出大約 250 字的每日重點分析與操作建議。
                語氣要冷靜、客觀、紀律嚴明。不要寒暄，直接以條列式給出洞察重點。
                
                特別指令：若「官方重大公告」與「媒體新聞」描述同一事件（例如營收開出 vs 媒體預測），請進行交叉比對，判斷市場情緒是否過度反應或忽略了事實。
                
                【今日估值狀態 (折溢價燈號)】
                {ai_df.to_string(index=False)}
                
                【官方重大公告 (公開資訊觀測站之絕對事實)】
                {official_text_for_ai}
                
                【媒體最新新聞 (市場情緒與預期)】
                {news_text_for_ai}
                """
                response = model.generate_content(prompt)
                ai_html = f"<h3>🤖 系統自動化盤後評估</h3><div style='background-color: #f4f8fb; padding: 15px; border-left: 4px solid #0056b3; font-size: 13px; line-height: 1.6;'>{response.text.replace(chr(10), '<br>')}</div>"
            except Exception as e:
                print(f"Gemini API 呼叫失敗: {e}")
        
        return official_html, news_html, ai_html

    def send_email_notify(self, df, today_str):
        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD: return
        
        # 接收三項回傳值
        official_html, news_html, ai_html = self.get_news_and_analysis(df)

        msg = MIMEMultipart('related')
        msg['Subject'] = f"📊 【投資組合動態追蹤】 {today_str}"
        msg['From'], msg['To'] = GMAIL_ADDRESS, GMAIL_ADDRESS

        error_banner = ""
        if self.fetch_errors:
            error_items = "".join([f"<li>{e}</li>" for e in self.fetch_errors])
            error_banner = f'''<div style="background-color:#fff3cd; border:1px solid #ffeeba; padding:10px 15px; border-radius:5px; margin-bottom:15px; font-size:12px;"><b>⚠️ 本次執行有資料抓取異常：</b><ul style="margin:6px 0 0 20px;">{error_items}</ul></div>'''

        html = f'''
        <html><head><style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            table {{ border-collapse: collapse; width: 100%; max-width: 950px; font-size: 13px; margin-bottom: 20px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
            th {{ background-color: #f2f2f2; white-space: nowrap; }}
            .text-left {{ text-align: left; }}
        </style></head><body>
          <h2>📈 標的估值動態儀表板 ({today_str})</h2>
          {error_banner}
          {ai_html}
          <h3 style='margin-top: 20px;'>📝 個股狀態與折溢價明細</h3>
          <table>
            <tr><th class="text-left">標的</th><th>現價</th><th>估值法</th><th>便宜價</th><th>合理價</th><th>目標價</th><th>狀態與備註</th></tr>
        '''
        for _, row in df.iterrows():
            c_val, f_val, t_val = row['便宜價'], row['合理價'], row['目標價']
            c_str = c_val if isinstance(c_val, str) else (f"{c_val:,.1f}" if c_val > 0 else "-")
            f_str = f_val if isinstance(f_val, str) else (f"{f_val:,.1f}" if f_val > 0 else "-")
            t_str = t_val if isinstance(t_val, str) else (f"{t_val:,.1f}" if t_val > 0 else "-")
            
            dyield, v_method, note = row.get('殖利率(%)', 0.0), row['估值法'], row.get('備註', '')
            price_html = f"<b>{row['現價']}</b>"
            if v_method in ["目標殖利率", "預估殖利率"] and dyield > 0: price_html += f"<br><span style='font-size: 11px; color: #d63384;'>預估/最新: {dyield}%</span>"
            elif v_method == "趨勢乖離法" and dyield > 0: price_html += f"<br><span style='font-size: 11px; color: #d63384;'>參考: {dyield}%</span>"
            elif dyield > 0: price_html += f"<br><span style='font-size: 11px; color: #d63384;'>殖利率: {dyield}%</span>"

            status_html = row['狀態']
            if note: status_html += f"<br><span style='font-size: 10px; color: #999; display: block; margin-top: 4px; text-align: left;'>{note}</span>"

            html += f'''<tr>
              <td class="text-left">{row['名稱']}<br><span style="font-size: 11px; color: #666;">({row['代碼']})</span></td>
              <td>{price_html}</td><td style="color: #666; font-weight: bold;">{v_method}</td>
              <td style="color: #28a745;">{c_str}</td><td style="color: #0056b3;">{f_str}</td><td style="color: #dc3545;">{t_str}</td>
              <td class="text-left">{status_html}</td>
            </tr>'''

        html += f'''</table>
            <img src="cid:valuation_chart" style="max-width: 100%; border: 1px solid #eee; border-radius: 5px;">
            {official_html}
            {news_html}
            </body></html>'''

        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html, 'html'))
        if os.path.exists(CHART_FILE):
            with open(CHART_FILE, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<valuation_chart>')
                msg.attach(img)
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.send_message(msg)
            print("Email 推播成功！")
        except Exception as e: print(f"Email 推播失敗: {e}")

    def run(self):
        df = self.calculate()
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"處理完畢，產出 {today_str} 估值報表")
        self.send_email_notify(df, today_str)

if __name__ == "__main__":
    tracker = TaiwanMarketTracker()
    tracker.run()