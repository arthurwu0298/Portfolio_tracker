# portfolio_tracker.py
import os
import sqlite3
import requests
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime
from portfolio_config import PORTFOLIO, CASH_RESERVE, LINE_NOTIFY_TOKEN

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
        '''初始化 SQLite 資料庫'''
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
        '''抓取上市與上櫃股價與官方殖利率'''
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
        '''使用 yfinance 取得 ETF 近12個月真實配息殖利率'''
        try:
            ticker = yf.Ticker(f"{code}.TW")
            hist = ticker.dividends
            if not hist.empty:
                # 取近一年配息加總
                one_yr_ago = pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=1)
                recent_div = hist[hist.index >= one_yr_ago].sum()
                if current_price > 0:
                    return round((recent_div / current_price) * 100, 2)
        except Exception as e:
            print(f"yfinance 抓取 {code} 失敗: {e}")
        return 0.0

    def calculate(self):
        self.fetch_market_data()
        records = []
        total_mkt, total_cost = 0, 0

        for item in PORTFOLIO:
            c = item["code"]
            m = item["market"]
            cp = item["cost_per_share"]
            s = item["shares"]
            
            # 取得股價
            price = self.twse_prices.get(c) if m == "TWSE" else self.tpex_prices.get(c)
            price = price or cp 
            
            # 取得殖利率 (ETF 改用 yfinance 真實配息紀錄)
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
        '''讀取 SQLite 歷史數據繪製淨值走勢圖'''
        conn = sqlite3.connect(DB_FILE)
        df_hist = pd.read_sql("SELECT date, total_net_worth FROM history ORDER BY date", conn)
        conn.close()
        
        if len(df_hist) < 1: return
        
        # 繪圖參數設定 (支援中文)
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

    def send_line_notify(self, msg):
        if not LINE_NOTIFY_TOKEN:
            print("未設定 LINE_NOTIFY_TOKEN，跳過推播。")
            return
        headers = {"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"}
        payload = {"message": msg}
        files = {}
        if os.path.exists(CHART_FILE):
            files = {"imageFile": open(CHART_FILE, "rb")}
        
        res = requests.post("https://notify-api.line.me/api/notify", headers=headers, data=payload, files=files)
        if res.status_code == 200:
            print("LINE Notify 推播成功！")
        else:
            print(f"LINE Notify 推播失敗：{res.status_code}, {res.text}")

    def run(self):
        df, tc, tm, tnw, pl, ret = self.calculate()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 格式化 LINE 訊息
        msg = f"\n📊 【投資組合每日報表】 {today_str}\n"
        msg += f"====================\n"
        msg += f"📈 股票總市值: NT$ {tm:,.0f}\n"
        msg += f"💵 預備現金: NT$ {CASH_RESERVE:,.0f}\n"
        msg += f"💎 總淨值: NT$ {tnw:,.0f}\n"
        msg += f"🎯 未實現損益: NT$ {pl:,.0f} ({ret:+.2f}%)\n"
        msg += f"====================\n"
        
        for _, row in df.iterrows():
            sign = "🔴" if row['損益'] > 0 else ("🟢" if row['損益'] < 0 else "⚪")
            msg += f"{row['名稱']}({row['代碼']}) | 價: {row['現價']}\n"
            msg += f"益: {sign} ${row['損益']:,.0f} | 息: {row['殖利率(%)']}%\n"
            msg += "-"*15 + "\n"
            
        print(msg)
        self.send_line_notify(msg)

if __name__ == "__main__":
    tracker = TaiwanMarketTracker()
    tracker.run()
