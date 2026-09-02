# portfolio_tracker.py
import os
import sqlite3
import requests
import pandas as pd
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
CHART_FILE = "history_chart.png"

METHOD_MAP = {
    "yield": "預估殖利率",
    "cyclical_yield": "常態殖利率",
    "pe": "本益比法",
    "pb": "淨值比法",
    "etf_yield": "目標殖利率",
    "manual": "手動設定"
}

def safe_float(val):
    try: return float(str(val).replace(",", ""))
    except: return 0.0

class TaiwanMarketTracker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.twse_prices, self.tpex_prices = {}, {}
        self.twse_metrics, self.tpex_metrics = {}, {}
        self.etf_navs = {}
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
        print("📥 捨棄官方 API 與 YFinance，全面切換至 FinMind 抓取最新報價...")
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        for item in PORTFOLIO:
            c, m = item["code"], item["market"]
            
            # 1. 抓取股價 (TaiwanStockPrice)
            try:
                res = self.session.get("https://api.finmindtrade.com/api/v4/data", 
                                       params={"dataset": "TaiwanStockPrice", "data_id": c, "start_date": start_date, "token": FINMIND_TOKEN}, timeout=10)
                if res.status_code == 200:
                    data = res.json().get("data", [])
                    if data:
                        latest_price = safe_float(data[-1].get("close", 0.0))
                        if m == "TWSE": self.twse_prices[c] = latest_price
                        else: self.tpex_prices[c] = latest_price
                    else:
                        self.fetch_errors.append(f"{item['name']}({c}) FinMind 無近期股價資料")
                else:
                    self.fetch_errors.append(f"{item['name']}({c}) FinMind 股價回應異常")
            except Exception as e:
                self.fetch_errors.append(f"{item['name']}({c}) 股價請求失敗: {e}")

            # 2. 抓取估值 (TaiwanStockPER) - 僅限個股
            if "00" not in c:
                try:
                    res_per = self.session.get("https://api.finmindtrade.com/api/v4/data", 
                                           params={"dataset": "TaiwanStockPER", "data_id": c, "start_date": start_date, "token": FINMIND_TOKEN}, timeout=10)
                    if res_per.status_code == 200:
                        data_per = res_per.json().get("data", [])
                        if data_per:
                            latest_per = data_per[-1]
                            metrics = {
                                "pe": safe_float(latest_per.get("PER", 0.0)),
                                "pb": safe_float(latest_per.get("PBR", 0.0)),
                                "yield": safe_float(latest_per.get("dividend_yield", 0.0))
                            }
                            if m == "TWSE": self.twse_metrics[c] = metrics
                            else: self.tpex_metrics[c] = metrics
                        else:
                            self.fetch_errors.append(f"{item['name']}({c}) FinMind 無本益比資料")
                except Exception as e:
                    self.fetch_errors.append(f"{item['name']}({c}) 估值請求失敗: {e}")

        # 3. 抓取 ETF 淨值 (保留 Yahoo 隱藏爬蟲備援，針對單一標的)
        etf_list = [item["code"] for item in PORTFOLIO if item["valuation_method"] == "etf_yield"]
        for etf in etf_list:
            try:
                res_y = self.session.get(f"https://tw.stock.yahoo.com/quote/{etf}.TW", timeout=10)
                if res_y.status_code == 200 and '"nav":' in res_y.text:
                    nav_str = res_y.text.split('"nav":')[1].split(',')[0].replace('"', '').replace('}', '').strip()
                    if safe_float(nav_str) > 0:
                        self.etf_navs[etf] = safe_float(nav_str)
                    else:
                        self.fetch_errors.append(f"{etf} Yahoo備援淨值解析失敗")
            except Exception as e: 
                self.fetch_errors.append(f"{etf} Yahoo淨值請求失敗")

    def calculate(self):
        self.fetch_market_data()
        records = []
        total_mkt, total_cost = 0, 0

        for item in PORTFOLIO:
            c, m, cp, s = item["code"], item["market"], item["cost_per_share"], item["shares"]
            price = self.twse_prices.get(c) if m == "TWSE" else self.tpex_prices.get(c)
            price = price or cp
            nav = self.etf_navs.get(c, 0.0)

            metrics = self.twse_metrics.get(c, {}) if m == "TWSE" else self.tpex_metrics.get(c, {})
            current_pe = metrics.get("pe", 0.0)
            current_pb = metrics.get("pb", 0.0)

            v_method = item.get("valuation_method", "manual")
            method_ch = METHOD_MAP.get(v_method, "手動設定")
            cheap, fair, target = 0, 0, 0
            status = "⚪ 觀望"
            val_percentile = None
            extra_note = item.get("note", "")
            dyield = metrics.get("yield", 0.0)

            if v_method == "etf_yield":
                recent_div = self.valuation_engine.get_recent_dividend(c)
                dyield = round((recent_div / price) * 100, 2) if price > 0 and recent_div > 0 else 0.0

                ty = item.get("target_yields", {})
                y_c, y_f, y_t = ty.get('cheap', 0), ty.get('fair', 0), ty.get('target', 0)

                p_c = round(recent_div / (y_c / 100), 2) if y_c > 0 and recent_div > 0 else 0
                p_f = round(recent_div / (y_f / 100), 2) if y_f > 0 and recent_div > 0 else 0
                p_t = round(recent_div / (y_t / 100), 2) if y_t > 0 and recent_div > 0 else 0

                cheap = f"{p_c} ({y_c}%)" if p_c > 0 else "-"
                fair = f"{p_f} ({y_f}%)" if p_f > 0 else "-"
                target = f"{p_t} ({y_t}%)" if p_t > 0 else "-"

                if dyield >= y_c and y_c > 0: status = "🟢 便宜 (加碼)"
                elif y_f <= dyield < y_c: status = "🔵 合理 (續抱)"
                elif y_t < dyield < y_f: status = "🟡 偏高 (留意)"
                elif dyield <= y_t and y_t > 0: status = "🔴 達標 (停利)"

            elif v_method in ["yield", "cyclical_yield"]:
                ty = item.get("target_yields", {})
                y_c, y_f, y_t = ty.get('cheap', 0), ty.get('fair', 0), ty.get('target', 0)
                payout_ratio = item.get("payout_ratio", 0.8)

                if v_method == "cyclical_yield":
                    # 景氣循環股：採用 5 年平均 EPS
                    projected_eps = self.valuation_engine.get_5yr_average_eps(c)
                else:
                    # 一般股：採用近 4 季年化 EPS
                    projected_eps = self.valuation_engine.get_annualized_eps(c)
                    if projected_eps <= 0: projected_eps = price / current_pe if current_pe > 0 else 0.0

                projected_div = projected_eps * payout_ratio
                dyield = round((projected_div / price) * 100, 2) if price > 0 else 0.0

                p_c = round(projected_div / (y_c / 100), 1) if y_c > 0 else 0
                p_f = round(projected_div / (y_f / 100), 1) if y_f > 0 else 0
                p_t = round(projected_div / (y_t / 100), 1) if y_t > 0 else 0

                cheap = f"{p_c} ({y_c}%)" if p_c > 0 else "-"
                fair = f"{p_f} ({y_f}%)" if p_f > 0 else "-"
                target = f"{p_t} ({y_t}%)" if p_t > 0 else "-"

                if dyield >= y_c and y_c > 0: status = "🟢 便宜 (加碼)"
                elif y_f <= dyield < y_c: status = "🔵 合理 (續抱)"
                elif y_t < dyield < y_f: status = "🟡 偏高 (留意)"
                elif dyield <= y_t and y_t > 0: status = "🔴 達標 (停利)"

            else:
                if v_method == "manual":
                    cheap, fair, target = item.get("cheap", 0), item.get("fair", 0), item.get("target", 0)
                elif v_method == "pe":
                    cheap, fair, target, val_percentile = self.valuation_engine.calc_pe_valuation(c, price, current_pe)
                elif v_method == "pb":
                    cheap, fair, target, val_percentile = self.valuation_engine.calc_pb_valuation(c, price, current_pb)

                if price <= cheap and cheap > 0: status = "🟢 便宜 (加碼)"
                elif cheap < price <= fair: status = "🔵 合理 (續抱)"
                elif fair < price < target: status = "🟡 偏高 (留意)"
                elif price >= target and target > 0: status = "🔴 達標 (停利)"

                if val_percentile is not None and val_percentile >= EXTREME_VALUATION_PERCENTILE:
                    momentum = self.valuation_engine.get_revenue_momentum(c)
                    if momentum and momentum["accelerating"] and momentum["latest_yoy"] > MOMENTUM_YOY_THRESHOLD:
                        status = f"🟣 結構性重估中 (估值第{val_percentile}百分位創新高)"
                    else:
                        yoy_txt = f"{momentum['latest_yoy']}%" if momentum else "無"
                        status = f"🔴 估值第{val_percentile}百分位創新高 (營收動能未達標，防情緒推升)"

            cost = s * cp
            mkt = s * price
            pl = mkt - cost
            total_cost += cost
            total_mkt += mkt

            records.append({
                "代碼": c, "名稱": item["name"],
                "現價": price, "淨值": nav, "成本": cp, "股數": s,
                "市值": mkt, "損益": pl, "殖利率(%)": dyield,
                "便宜價": cheap, "合理價": fair, "目標價": target,
                "狀態": status, "估值法": method_ch, "備註": extra_note
            })

        df = pd.DataFrame(records)
        total_net_worth = total_mkt + CASH_RESERVE
        total_pl = total_mkt - total_cost
        ret_rate = round((total_pl / total_cost) * 100, 2) if total_cost > 0 else 0

        self.save_to_db(total_cost, total_mkt, total_net_worth, CASH_RESERVE, total_pl, ret_rate)
        self.plot_history()

        return df, total_cost, total_mkt, total_net_worth, total_pl, ret_rate

    def save_to_db(self, tc, tm, tnw, cash, pl, ret):
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO history VALUES (?, ?, ?, ?, ?, ?, ?)''', (today, tc, tm, tnw, cash, pl, ret))
        conn.commit()
        conn.close()

    def plot_history(self):
        conn = sqlite3.connect(DB_FILE)
        df_hist = pd.read_sql("SELECT date, total_net_worth FROM history ORDER BY date", conn)
        conn.close()
        if len(df_hist) < 1: return
        plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'Microsoft JhengHei', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        plt.figure(figsize=(10, 5))
        plt.plot(pd.to_datetime(df_hist['date']), df_hist['total_net_worth'], marker='o', color='#1f77b4', linewidth=2)
        plt.title('投資組合總淨值走勢圖 (含現金)', fontsize=14, fontweight='bold')
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.tight_layout()
        plt.savefig(CHART_FILE)
        plt.close()

    def send_email_notify(self, df, tm, tnw, pl, ret, today_str):
        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD: return
        msg = MIMEMultipart('related')
        msg['Subject'] = f"📊 【投資組合每日報表】 {today_str}"
        msg['From'], msg['To'] = GMAIL_ADDRESS, GMAIL_ADDRESS
        pl_color = "#28a745" if pl >= 0 else "#dc3545"

        error_banner = ""
        if self.fetch_errors:
            error_items = "".join([f"<li>{e}</li>" for e in self.fetch_errors])
            error_banner = f'''
            <div style="background-color:#ffeeba; padding:10px; border-radius:5px; margin-bottom:15px; font-size:12px;">
                <b>⚠️ 系統自動切換備援資料源，以下標的可能無最新報價：</b>
                <ul>{error_items}</ul>
            </div>
            '''

        html = f'''
        <html><head><style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            table {{ border-collapse: collapse; width: 100%; max-width: 900px; font-size: 13px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: center; }}
            th {{ background-color: #f2f2f2; white-space: nowrap; }}
            .text-left {{ text-align: left; }}
            .positive {{ color: #28a745; font-weight: bold; }}
            .negative {{ color: #dc3545; font-weight: bold; }}
        </style></head><body>
          <h2>📈 投資組合總覽 ({today_str})</h2>
          {error_banner}
          <div class="summary">
            <p>總淨值: <b>NT$ {tnw:,.0f}</b> | 未實現損益: <span style="color: {pl_color}; font-weight: bold;">NT$ {pl:,.0f} ({ret:+.2f}%)</span></p>
          </div>
          <h3>📝 個股明細與法人動態估值</h3>
          <table>
            <tr><th class="text-left">標的</th><th>現價 / 淨值</th><th>未實現損益</th><th>估值法</th><th>便宜價</th><th>合理價</th><th>目標價</th><th>狀態</th></tr>
        '''
        for _, row in df.iterrows():
            pl_class = "positive" if row['損益'] > 0 else ("negative" if row['損益'] < 0 else "")
            c_val, f_val, t_val = row['便宜價'], row['合理價'], row['目標價']
            c_str = c_val if isinstance(c_val, str) else (f"{c_val:,.1f}" if c_val > 0 else "-")
            f_str = f_val if isinstance(f_val, str) else (f"{f_val:,.1f}" if f_val > 0 else "-")
            t_str = t_val if isinstance(t_val, str) else (f"{t_val:,.1f}" if t_val > 0 else "-")
            
            nav, dyield, v_method, note = row.get('淨值', 0.0), row.get('殖利率(%)', 0.0), row['估值法'], row.get('備註', '')
            price_html = f"<b>{row['現價']}</b>"
            if nav > 0: price_html += f"<br><span style='font-size: 11px; color: #0056b3;'>淨值: {nav}</span>"
            if "殖利率" in v_method and dyield > 0:
                price_html += f"<br><span style='font-size: 11px; color: #d63384;'>預估/最新: {dyield}%</span>"

            html += f'''<tr>
              <td class="text-left">{row['名稱']}<br><span style="font-size: 11px; color: #666;">({row['代碼']})</span></td>
              <td>{price_html}</td><td class="{pl_class}">${row['損益']:,.0f}</td>
              <td style="color: #666; font-weight: bold;">{v_method}</td>
              <td style="color: #28a745;">{c_str}</td><td style="color: #0056b3;">{f_str}</td><td style="color: #dc3545;">{t_str}</td>
              <td>{row['狀態']}</td>
            </tr>'''

        html += '''</table><br><img src="cid:history_chart" style="max-width: 100%; border: 1px solid #eee;"></body></html>'''

        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html, 'html'))
        if os.path.exists(CHART_FILE):
            with open(CHART_FILE, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<history_chart>')
                msg.attach(img)
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
                server.send_message(msg)
            print("Email 推播成功！")
        except Exception as e:
            print(f"Email 推播失敗: {e}")

    def run(self):
        df, tc, tm, tnw, pl, ret = self.calculate()
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"正在處理 {today_str} 的資料...")
        self.send_email_notify(df, tm, tnw, pl, ret, today_str)

if __name__ == "__main__":
    tracker = TaiwanMarketTracker()
    tracker.run()
