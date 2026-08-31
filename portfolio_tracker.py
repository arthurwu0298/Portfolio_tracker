# portfolio_tracker.py
import os
import sqlite3
import requests
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from portfolio_config import PORTFOLIO, CASH_RESERVE, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, FINMIND_TOKEN
from valuation_engine import FinMindValuationEngine

DB_FILE = "portfolio_history.db"
CHART_FILE = "history_chart.png"

METHOD_MAP = {
    "yield": "殖利率法",
    "pe": "本益比法",
    "pb": "淨值比法",
    "etf_yield": "目標殖利率",
    "manual": "手動設定"
}

def safe_float(val):
    try:
        return float(str(val).replace(",", ""))
    except:
        return 0.0

class TaiwanMarketTracker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.twse_prices, self.tpex_prices = {}, {}
        self.twse_metrics, self.tpex_metrics = {}, {}
        self.etf_navs = {}
        self.valuation_engine = FinMindValuationEngine(token=FINMIND_TOKEN)
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
        print("📥 抓取 TWSE / TPEx 最新報價、本益比與 ETF 淨值資料...")
        res1 = self.session.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10)
        if res1.status_code == 200:
            for item in res1.json(): self.twse_prices[item["Code"]] = safe_float(item.get("ClosingPrice"))
        
        res2 = self.session.get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d", timeout=10)
        if res2.status_code == 200:
            for item in res2.json():
                self.twse_metrics[item["Code"]] = {
                    "yield": safe_float(item.get("DividendYield")),
                    "pe": safe_float(item.get("PEratio")),
                    "pb": safe_float(item.get("PBratio"))
                }

        res3 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10)
        if res3.status_code == 200:
            for item in res3.json(): self.tpex_prices[item["SecuritiesCompanyCode"]] = safe_float(item.get("Close"))
                
        res4 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", timeout=10)
        if res4.status_code == 200:
            for item in res4.json():
                self.tpex_metrics[item["SecuritiesCompanyCode"]] = {
                    "yield": safe_float(item.get("DividendYield")),
                    "pe": safe_float(item.get("PeRatio")),
                    "pb": safe_float(item.get("PbRatio"))
                }
                
        # 抓取 ETF 淨值
        try:
            res_etf = self.session.get("https://openapi.twse.com.tw/v1/opendata/t187ap46_L", timeout=10)
            if res_etf.status_code == 200:
                for item in res_etf.json():
                    self.etf_navs[item.get("SecuritiesCompanyCode")] = safe_float(item.get("NetAssetValue"))
        except:
            print("⚠️ ETF 淨值資料抓取失敗，將略過。")

    def get_etf_real_yield(self, code, current_price):
        try:
            ticker = yf.Ticker(f"{code}.TW")
            hist = ticker.dividends
            if not hist.empty:
                one_yr_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=1)
                recent_div = hist[hist.index >= one_yr_ago].sum()
                if current_price > 0: return round((recent_div / current_price) * 100, 2)
        except: pass
        return 0.0

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
            
            if "00" in c: dyield = self.get_etf_real_yield(c, price)
            else: dyield = metrics.get("yield", 0.0)
            
            v_method = item.get("valuation_method", "manual")
            method_ch = METHOD_MAP.get(v_method, "手動設定")
            cheap, fair, target = 0, 0, 0
            status = "⚪ 觀望"
            
            if v_method == "etf_yield":
                ty = item.get("target_yields", {})
                cheap = f"{ty.get('cheap', 0)}%"
                fair = f"{ty.get('fair', 0)}%"
                target = f"{ty.get('target', 0)}%"
                y_c, y_f, y_t = ty.get('cheap', 0), ty.get('fair', 0), ty.get('target', 0)
                
                if dyield >= y_c and y_c > 0: status = "🟢 便宜 (加碼)"
                elif y_f <= dyield < y_c: status = "🔵 合理 (續抱)"
                elif y_t < dyield < y_f: status = "🟡 偏高 (留意)"
                elif dyield <= y_t and y_t > 0: status = "🔴 達標 (停利)"
            else:
                if v_method == "manual":
                    cheap, fair, target = item.get("cheap",0), item.get("fair",0), item.get("target",0)
                elif v_method == "yield":
                    print(f"🔄 計算 {item['name']} 歷史殖利率區間...")
                    cheap, fair, target = self.valuation_engine.calc_yield_valuation(c, item.get("target_yields", {}))
                elif v_method == "pe":
                    print(f"🔄 計算 {item['name']} 歷史本益比(PE)區間...")
                    cheap, fair, target = self.valuation_engine.calc_pe_valuation(c, price, current_pe)
                elif v_method == "pb":
                    print(f"🔄 計算 {item['name']} 歷史淨值比(PB)區間...")
                    cheap, fair, target = self.valuation_engine.calc_pb_valuation(c, price, current_pb)
                
                if price <= cheap and cheap > 0: status = "🟢 便宜 (加碼)"
                elif cheap < price <= fair: status = "🔵 合理 (續抱)"
                elif fair < price < target: status = "🟡 偏高 (留意)"
                elif price >= target and target > 0: status = "🔴 達標 (停利)"
            
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
                "狀態": status, "估值法": method_ch
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
        cursor.execute('''
            INSERT OR REPLACE INTO history 
            (date, total_cost, total_mkt, total_net_worth, cash_reserve, unrealized_pl, return_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (today, tc, tm, tnw, cash, pl, ret))  # 👈 修正這裡：補上要寫入的 7 個變數
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
            
            nav = row.get('淨值', 0.0)
            price_html = f"<b>{row['現價']}</b>"
            if nav > 0:
                price_html += f"<br><span style='font-size: 11px; color: #0056b3;'>淨值: {nav}</span>"
            
            html += f'''<tr>
              <td class="text-left">{row['名稱']}<br><span style="font-size: 11px; color: #666;">({row['代碼']})</span></td>
              <td>{price_html}</td><td class="{pl_class}">${row['損益']:,.0f}</td>
              <td style="color: #666; font-weight: bold;">{row['估值法']}</td>
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
