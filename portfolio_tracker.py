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

from portfolio_config import PORTFOLIO, CASH_RESERVE, GMAIL_ADDRESS, GMAIL_APP_PASSWORD

DB_FILE = "portfolio_history.db"
CHART_FILE = "history_chart.png"

class TaiwanMarketTracker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self.twse_prices = {}
        self.tpex_prices = {}
        self.twse_yields = {}
        self.tpex_yields = {}
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS history (
                date TEXT PRIMARY KEY,
                total_cost REAL,
                total_mkt REAL,
                total_net_worth REAL,
                cash_reserve REAL,
                unrealized_pl REAL,
                return_rate REAL
            )
        ''')
        conn.commit()
        conn.close()

    def fetch_market_data(self):
        # 上市
        res1 = self.session.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=10)
        if res1.status_code == 200:
            for item in res1.json():
                try: self.twse_prices[item["Code"]] = float(item["ClosingPrice"].replace(",", ""))
                except: pass
        
        res2 = self.session.get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d", timeout=10)
        if res2.status_code == 200:
            for item in res2.json():
                try: self.twse_yields[item["Code"]] = float(item["DividendYield"].replace(",", ""))
                except: pass

        # 上櫃
        res3 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", timeout=10)
        if res3.status_code == 200:
            for item in res3.json():
                try: self.tpex_prices[item["SecuritiesCompanyCode"]] = float(item["Close"].replace(",", ""))
                except: pass
                
        res4 = self.session.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", timeout=10)
        if res4.status_code == 200:
            for item in res4.json():
                try: self.tpex_yields[item["SecuritiesCompanyCode"]] = float(item["YieldRatio"].replace(",", ""))
                except: pass

    def get_etf_real_yield(self, code, current_price):
        try:
            ticker = yf.Ticker(f"{code}.TW")
            hist = ticker.dividends
            if not hist.empty:
                one_yr_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=1)
                recent_div = hist[hist.index >= one_yr_ago].sum()
                if current_price > 0:
                    return round((recent_div / current_price) * 100, 2)
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
            
            if "00" in c:
                dyield = self.get_etf_real_yield(c, price)
            else:
                dyield = self.twse_yields.get(c) if m == "TWSE" else self.tpex_yields.get(c)
                dyield = dyield or 0.0
            
            cost = s * cp
            mkt = s * price
            pl = mkt - cost
            
            total_cost += cost
            total_mkt += mkt
            
            records.append({
                "代碼": c, "名稱": item["name"],
                "現價": price, "成本": cp, "股數": s,
                "市值": mkt, "損益": pl,
                "殖利率(%)": dyield
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
        ''', (today, tc, tm, tnw, cash, pl, ret))
        conn.commit()
        conn.close()

    def plot_history(self):
        conn = sqlite3.connect(DB_FILE)
        df_hist = pd.read_sql("SELECT date, total_net_worth FROM history ORDER BY date", conn)
        conn.close()
        
        if len(df_hist) < 1: return
        
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Taipei Sans TC Beta', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        plt.figure(figsize=(10, 5))
        plt.plot(pd.to_datetime(df_hist['date']), df_hist['total_net_worth'], marker='o', color='#1f77b4', linewidth=2)
        plt.title('投資組合總淨值走勢圖 (含現金)', fontsize=14, fontweight='bold')
        plt.xlabel('日期', fontsize=12)
        plt.ylabel('總淨值 (NT$)', fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.tight_layout()
        plt.savefig(CHART_FILE)
        plt.close()

    def send_email_notify(self, df, tm, tnw, pl, ret, today_str):
        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
            print("未設定 GMAIL_ADDRESS 或 GMAIL_APP_PASSWORD，跳過 Email 推播。")
            return

        msg = MIMEMultipart('related')
        msg['Subject'] = f"📊 【投資組合每日報表】 {today_str}"
        msg['From'] = GMAIL_ADDRESS
        msg['To'] = GMAIL_ADDRESS # 寄給自己

        pl_color = "#28a745" if pl >= 0 else "#dc3545"
        
        html = f'''
        <html>
        <head>
          <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
            table {{ border-collapse: collapse; width: 100%; max-width: 600px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .positive {{ color: #28a745; font-weight: bold; }}
            .negative {{ color: #dc3545; font-weight: bold; }}
          </style>
        </head>
        <body>
          <h2>📈 投資組合總覽 ({today_str})</h2>
          <div class="summary">
            <p>股票總市值: <b>NT$ {tm:,.0f}</b></p>
            <p>預備現金: <b>NT$ {CASH_RESERVE:,.0f}</b></p>
            <p>總淨值: <b>NT$ {tnw:,.0f}</b></p>
            <p>未實現損益: <span style="color: {pl_color}; font-weight: bold;">NT$ {pl:,.0f} ({ret:+.2f}%)</span></p>
          </div>
          <h3>📝 個股明細</h3>
          <table>
            <tr>
              <th>標的</th>
              <th>現價</th>
              <th>損益</th>
              <th>殖利率</th>
            </tr>
        '''
        
        for _, row in df.iterrows():
            pl_class = "positive" if row['損益'] > 0 else ("negative" if row['損益'] < 0 else "")
            html += f'''
            <tr>
              <td>{row['名稱']} ({row['代碼']})</td>
              <td>{row['現價']}</td>
              <td class="{pl_class}">${row['損益']:,.0f}</td>
              <td>{row['殖利率(%)']}%</td>
            </tr>
            '''
            
        html += '''
          </table>
          <h3>📊 資產走勢</h3>
          <img src="cid:history_chart" alt="資產走勢圖" style="max-width: 100%; height: auto;">
        </body>
        </html>
        '''

        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html, 'html'))

        # 附加圖片並給定 Content-ID 以便在 HTML 中內嵌顯示
        if os.path.exists(CHART_FILE):
            with open(CHART_FILE, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-ID', '<history_chart>')
                msg.attach(img)

        try:
            # 透過 SMTP SSL 連線寄信
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
