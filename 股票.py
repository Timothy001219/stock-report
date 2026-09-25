from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import os
import subprocess
import sys
import webbrowser
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import yfinance as yf

# 檔案名稱設定
REVENUE_CACHE_FILE = 'revenue_cache.json'
FINANCIAL_CACHE_FILE = 'financial_cache.json'        # 財務指標快取
INSTITUTIONAL_CACHE_FILE = 'institutional_cache.json' # 三大法人籌碼快取
INFO_FILE = 'information.txt'
input_filename = 'stocks.txt'
output_filename = 'kd_result.html'

def load_finmind_token():
    finmind_t = ""
    if os.path.exists(INFO_FILE):
        try:
            with open(INFO_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, val = line.split('=', 1)
                            key, val = key.strip().lower(), val.strip()
                            if 'finmind' in key or 'token' in key:
                                finmind_t = val
                        else:
                            finmind_t = line
        except:
            pass
    return finmind_t

FINMIND_TOKEN = load_finmind_token()

def push_to_github_via_git(filename):
    """透過本機 Git 指令自動推送到 GitHub，並自動計算 GitHub Pages 網址"""
    try:
        print("☁️ 正在透過 Git 自動同步至 GitHub 網頁...")
        
        if not os.path.exists(".git"):
            print("⚙️ 偵測到此資料夾尚未初始化 Git，正在自動建立...")
            subprocess.run(["git", "init"], capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], capture_output=True)
        
        subprocess.run(["git", "add", filename], check=True, capture_output=True)
        
        commit_msg = f"自動更新台股技術分析總覽報告: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True)
        
        branch_res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
        current_branch = branch_res.stdout.strip()
        if not current_branch:
            current_branch = "master"
        
        result = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0 and ("no upstream branch" in result.stderr or "set-upstream" in result.stderr):
            print(f"⚙️ 偵測到未設定遠端追蹤分支，正在自動綁定並推送 (origin {current_branch})...")
            result = subprocess.run(["git", "push", "--set-upstream", "origin", current_branch], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ GitHub 雲端同步成功！")
            try:
                remote_res = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True)
                remote_url = remote_res.stdout.strip()
                if "github.com" in remote_url:
                    if remote_url.endswith(".git"):
                        remote_url = remote_url[:-4]
                    if "git@github.com:" in remote_url:
                        path = remote_url.split("git@github.com:")[1]
                    elif "https://github.com/" in remote_url:
                        path = remote_url.split("https://github.com/")[1]
                    else:
                        path = ""
                    
                    if path:
                        parts = path.split("/")
                        if len(parts) >= 2:
                            username, repo = parts[0], parts[1]
                            return f"https://{username}.github.io/{repo}/{filename}"
            except:
                pass
            return True
        else:
            print(f"⚠️ Git push 失敗，詳細錯誤原因：\n{result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("⚠️ Git 推送連線逾時，請檢查網路狀況。")
    except Exception as e:
        print(f"⚠️ Git 自動推送發生錯誤: {e}")
    return False

# ==================== 快取讀寫輔助函數 ====================

def load_json_cache(filename):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_json_cache(filename, cache_data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except:
        pass

# ==================== FinMind 額外資料抓取與區塊生成函數 ====================

def get_financial_statements_data(stock_id):
    """取得最近 4 季財務指標 HTML 表格與計算後的總和 EPS（具備快取機制）"""
    cache = load_json_cache(FINANCIAL_CACHE_FILE)
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    if stock_id in cache and cache[stock_id].get('date') == today_str:
        return cache[stock_id]['html'], cache[stock_id]['eps']

    today = datetime.now()
    start_date = (today - timedelta(days=730)).strftime('%Y-%m-%d')
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockFinancialStatements&data_id={stock_id}&start_date={start_date}"
    if FINMIND_TOKEN:
        url += f"&token={FINMIND_TOKEN}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get('data', [])
            if data:
                df = pd.DataFrame(data)
                target_types = ['Revenue', 'GrossProfit', 'OperatingIncome', 'NetIncome', 'EPS']
                df_filtered = df[df['type'].isin(target_types)]
                if not df_filtered.empty:
                    pivot_df = df_filtered.pivot(index='date', columns='type', values='value').reset_index()
                    pivot_df['date'] = pd.to_datetime(pivot_df['date'])
                    pivot_df = pivot_df.sort_values('date', ascending=False).head(4)
                    
                    total_eps = 0.0
                    if 'EPS' in pivot_df.columns:
                        total_eps = float(pivot_df['EPS'].sum())
                    
                    if 'GrossProfit' in pivot_df.columns and 'Revenue' in pivot_df.columns:
                        pivot_df['毛利率(%)'] = (pivot_df['GrossProfit'] / pivot_df['Revenue'] * 100).round(2)
                    if 'OperatingIncome' in pivot_df.columns and 'Revenue' in pivot_df.columns:
                        pivot_df['營益率(%)'] = (pivot_df['OperatingIncome'] / pivot_df['Revenue'] * 100).round(2)
                        
                    cols = [c for c in ['date', 'Revenue', 'GrossProfit', '毛利率(%)', 'OperatingIncome', '營益率(%)', 'EPS'] if c in pivot_df.columns]
                    pivot_df = pivot_df[cols]
                    
                    html_str = pivot_df.to_html(classes='fin-table', index=False, border=0)
                    
                    cache[stock_id] = {'date': today_str, 'html': html_str, 'eps': total_eps}
                    save_json_cache(FINANCIAL_CACHE_FILE, cache)
                    
                    return html_str, total_eps
    except:
        pass
        
    fallback_html = "<div style='color: #aaa; padding: 15px;'>暫無季別財務指標資料</div>"
    return fallback_html, 0.0

def get_real_monthly_revenue_table(stock_id, df_rev_source=None):
    """右上方表格：取得最近幾個月營收與年成長率 (YoY) 表格"""
    today = datetime.now()
    start_date = (today - timedelta(days=730)).strftime('%Y-%m-%d')
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={stock_id}&start_date={start_date}"
    if FINMIND_TOKEN:
        url += f"&token={FINMIND_TOKEN}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get('data', [])
            if data:
                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date', ascending=False)
                
                table_rows = []
                for _, row in df.head(4).iterrows():
                    curr_date = row['date']
                    curr_revenue = row['revenue'] / 1e8
                    
                    last_year_date = curr_date - pd.DateOffset(years=1)
                    match_ly = df[df['date'] == last_year_date]
                    
                    yoy_str = "N/A"
                    yoy_class = "neutral"
                    if not match_ly.empty:
                        ly_rev = match_ly.iloc[0]['revenue']
                        if ly_rev > 0:
                            yoy = ((row['revenue'] - ly_rev) / ly_rev) * 100
                            yoy_str = f"{yoy:+.2f}%"
                            yoy_class = 'up' if yoy > 0 else ('down' if yoy < 0 else 'neutral')
                    
                    month_label = curr_date.strftime('%Y年%m月')
                    table_rows.append(f"<tr><td>{month_label}</td><td>{curr_revenue:.2f} 億</td><td><span class='yoy-val {yoy_class}'>{yoy_str}</span></td></tr>")
                
                if table_rows:
                    return f"""
                    <table class="fin-table">
                        <thead>
                            <tr><th>月份</th><th>單月營收</th><th>年成長率(YoY)</th></tr>
                        </thead>
                        <tbody>
                            {"".join(table_rows)}
                        </tbody>
                    </table>
                    """
    except:
        pass
    return "<div style='color: #aaa; padding: 15px;'>暫無月營收表格資料</div>"

def create_shareholder_charts(stock_id, df_price):
    """三大法人買賣超資料（具備快取機制）"""
    cache = load_json_cache(INSTITUTIONAL_CACHE_FILE)
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    if stock_id in cache and cache[stock_id].get('date') == today_str:
        return cache[stock_id]['html']

    today = datetime.now()
    start_date = (today - timedelta(days=90)).strftime('%Y-%m-%d')
    
    dates, foreign_net, trust_net = [], [], []
    
    try:
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={stock_id}&start_date={start_date}"
        if FINMIND_TOKEN:
            url += f"&token={FINMIND_TOKEN}"
        
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json().get('data', [])
            if data:
                df_chip = pd.DataFrame(data)
                df_chip['date'] = pd.to_datetime(df_chip['date'])
                df_chip['net'] = df_chip['buy'] - df_chip['sell']
                
                piv = df_chip.pivot_table(index='date', columns='name', values='net', aggfunc='sum').reset_index()
                dates = piv['date'].dt.strftime('%Y-%m-%d').tolist()
                
                if 'Foreign_Investor' in piv.columns:
                    foreign_net = (piv['Foreign_Investor'] / 1000).round(2).tolist()
                else:
                    foreign_net = [0] * len(dates)
                    
                if 'Investment_Trust' in piv.columns:
                    trust_net = (piv['Investment_Trust'] / 1000).round(2).tolist()
                else:
                    trust_net = [0] * len(dates)
    except Exception as e:
        print(f"法人籌碼資料解析錯誤 ({stock_id}): {e}")

    if not dates:
        html_out = f"""
        <div style="background-color: #22252a; border-left: 5px solid #ff5252; padding: 30px 20px; border-radius: 6px; text-align: center; color: #b0bec5; height: 350px; display: flex; flex-direction: column; justify-content: center; align-items: center;">
            <div style="font-size: 18px; color: #ff8a80; font-weight: bold; margin-bottom: 8px;">⚠️ 查無法人買賣超資料 ({stock_id})</div>
            <div style="font-size: 14px; color: #888;">此代號近期無對應的三大法人交易紀錄。</div>
        </div>
        """
        cache[stock_id] = {'date': today_str, 'html': html_out}
        save_json_cache(INSTITUTIONAL_CACHE_FILE, cache)
        return html_out

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=dates,
            y=foreign_net,
            name="外資買賣超(張)",
            marker_color=['#ff5252' if v >= 0 else '#00e676' for v in foreign_net],
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=trust_net,
            name="投信買賣超(張)",
            line=dict(color='#ffeb3b', width=2),
        ),
        secondary_y=True,
    )

    fig.update_layout(
        template='plotly_dark',
        height=380,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
        title_text="<b>三大法人籌碼趨勢 (外資 vs 投信)</b>",
    )

    fig.update_yaxes(title_text="外資買賣超 (張)", secondary_y=False)
    fig.update_yaxes(title_text="投信買賣超 (張)", secondary_y=True)

    html_out = fig.to_html(full_html=False, include_plotlyjs='cdn')
    
    cache[stock_id] = {'date': today_str, 'html': html_out}
    save_json_cache(INSTITUTIONAL_CACHE_FILE, cache)
    
    return html_out

# ==================== 原有快取與繪圖函數 ====================

def get_real_monthly_revenue(stock_id, symbol=None):
    today = datetime.now()
    rev_cache = load_json_cache(REVENUE_CACHE_FILE)
    
    if stock_id in rev_cache and len(rev_cache[stock_id]) > 0:
        revenue_records = []
        sorted_months = sorted(rev_cache[stock_id].keys(), reverse=True)[:3]
        for month_key in sorted_months:
            cached_data = rev_cache[stock_id][month_key]
            yoy_val_str = cached_data.get('yoy', 'N/A')
            yoy_class = 'up' if '+' in yoy_val_str else ('down' if '-' in yoy_val_str else 'neutral')
            revenue_records.append(f"<div style='margin-bottom: 6px;'>📅 {month_key.replace('-', '年')}月: 今年 <b>{cached_data.get('curr', 'N/A')}</b> | 去年 <b>{cached_data.get('ly', 'N/A')}</b> | YoY: <span class='yoy-val {yoy_class}'>{yoy_val_str}</span> <span class='cache-tag'>(快取)</span></div>")
        if revenue_records:
            return "<div class='revenue-box'><b>📊 單月營收對比 (今年 vs 去年 YoY):</b><br><br>" + "".join(revenue_records) + "</div>"

    if stock_id not in rev_cache:
        rev_cache[stock_id] = {}

    try:
        start_date = (today - timedelta(days=730)).strftime('%Y-%m-%d')
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={stock_id}&start_date={start_date}"
        if FINMIND_TOKEN:
            url += f"&token={FINMIND_TOKEN}"
            
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if 'data' in data and len(data['data']) > 0:
                df_rev = pd.DataFrame(data['data'])
                df_rev['date'] = pd.to_datetime(df_rev['date'])
                df_rev = df_rev.sort_values('date', ascending=False)
                
                revenue_records = []
                for _, row in df_rev.head(3).iterrows():
                    curr_date = row['date']
                    month_key = curr_date.strftime('%Y-%m')
                    curr_revenue = row['revenue'] / 1e8
                    
                    last_year_date = curr_date - pd.DateOffset(years=1)
                    match_ly = df_rev[df_rev['date'] == last_year_date]
                    
                    ly_str, yoy_str, yoy_class = "N/A", "N/A", "neutral"
                    if not match_ly.empty:
                        ly_revenue = match_ly.iloc[0]['revenue'] / 1e8
                        ly_str = f"{ly_revenue:.2f}億"
                        if ly_revenue > 0:
                            yoy = ((row['revenue'] - match_ly.iloc[0]['revenue']) / match_ly.iloc[0]['revenue']) * 100
                            yoy_str = f"{yoy:+.2f}%"
                            yoy_class = 'up' if yoy > 0 else ('down' if yoy < 0 else 'neutral')
                    
                    rev_cache[stock_id][month_key] = {
                        'curr': f"{curr_revenue:.2f}億",
                        'ly': ly_str,
                        'yoy': yoy_str
                    }
                    revenue_records.append(f"<div style='margin-bottom: 6px;'>📅 {curr_date.strftime('%Y年%m月')}: 今年 <b>{curr_revenue:.2f}億</b> | 去年 <b>{ly_str}</b> | YoY: <span class='yoy-val {yoy_class}'>{yoy_str}</span></div>")
                
                save_json_cache(REVENUE_CACHE_FILE, rev_cache)
                if revenue_records:
                    return "<div class='revenue-box'><b>📊 單月營收對比 (今年 vs 去年 YoY):</b><br><br>" + "".join(revenue_records) + "</div>"
    except:
        pass

    return "<div class='rev-row'>📊 查無近期單月營收資料</div>"

def generate_professional_chart(df, stock_id, stock_name):
    try:
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        n = 9
        lowest_low = df['Low'].rolling(window=n).min()
        highest_high = df['High'].rolling(window=n).max()
        rsv = (df['Close'] - lowest_low) / (highest_high - lowest_low) * 100
        k_list, d_list = [50.0], [50.0]
        rsv_values = rsv.values
        for i in range(1, len(df)):
            curr_rsv = rsv_values[i]
            if pd.isna(curr_rsv):
                k_list.append(k_list[-1])
                d_list.append(d_list[-1])
            else:
                k_val = (2 / 3) * k_list[-1] + (1 / 3) * curr_rsv
                d_val = (2 / 3) * d_list[-1] + (1 / 3) * k_val
                k_list.append(k_val)
                d_list.append(d_val)
        df['K'], df['D'] = k_list, d_list

        df['EMA12'] = df['Close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['Close'].ewm(span=26, adjust=False).mean()
        df['DIF'] = df['EMA12'] - df['EMA26']
        df['MACD'] = df['DIF'].ewm(span=9, adjust=False).mean()
        df['OSC'] = (df['DIF'] - df['MACD']) * 2

        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.4, 0.2, 0.2, 0.2])

        latest_idx = df.index[-1]
        close_text = [f"{val:.2f}" if idx == latest_idx else "" for idx, val in zip(df.index, df['Close'])]
        k_text = [f"K:{val:.1f}" if idx == latest_idx else "" for idx, val in zip(df.index, df['K'])]
        macd_text = [f"MACD:{val:.2f}" if idx == latest_idx else "" for idx, val in zip(df.index, df['MACD'])]

        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K線', increasing_line_color='#ff5252', decreasing_line_color='#00e676'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='text', text=close_text, textposition='top center', textfont=dict(color='#ffffff', size=12), showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#ffeb3b', width=1), name='MA5'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA10'], line=dict(color='#00bcd4', width=1), name='MA10'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#ab47bc', width=1), name='MA20'), row=1, col=1)

        colors = ['#ff5252' if row['Close'] >= row['Open'] else '#00e676' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume']/1000, marker_color=colors, name='成交量(張)'), row=2, col=1)

        fig.add_trace(go.Scatter(x=df.index, y=df['K'], line=dict(color='#ffeb3b', width=1.2), name='K'), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['K'], mode='text', text=k_text, textposition='top center', textfont=dict(color='#ffeb3b', size=11), showlegend=False), row=3, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['D'], line=dict(color='#00bcd4', width=1.2), name='D'), row=3, col=1)

        osc_colors = ['#ff5252' if val >= 0 else '#00e676' for val in df['OSC']]
        fig.add_trace(go.Bar(x=df.index, y=df['OSC'], marker_color=osc_colors, name='OSC'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['DIF'], line=dict(color='#ffeb3b', width=1.2), name='DIF'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], line=dict(color='#ab47bc', width=1.2), name='MACD'), row=4, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], mode='text', text=macd_text, textposition='top center', textfont=dict(color='#ab47bc', size=11), showlegend=False), row=4, col=1)

        fig.update_layout(template='plotly_dark', height=380, margin=dict(l=10, r=10, t=20, b=10), showlegend=False, xaxis_rangeslider_visible=False)

        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception as e:
        return f"<div class='error'>圖表產生失敗: {e}</div>"

def get_stock_data(stock_id, stock_name):
    stock_id = stock_id.strip()
    symbol, df = None, pd.DataFrame()
    candidates = [f"{stock_id}.TW", f"{stock_id}.TWO"]

    for cand in candidates:
        try:
            temp_df = yf.download(cand, period='1y', interval='1d', progress=False)
            if not temp_df.empty and len(temp_df) > 0:
                df = temp_df
                symbol = cand
                break
        except:
            continue

    if df.empty or symbol is None:
        error_card = f"""
        <div class="stock-card error-card" id="stock-{stock_id}">
            <div class="stock-header">
                <span>代碼: <b>{stock_id}</b> | 名稱: <b>{stock_name}</b></span>
                <span class="stock-date">狀態: ❌ 查無資料</span>
            </div>
            <div class="stock-body">
                <p style="color: #ff8a80; margin: 0;">無法從 Yahoo Finance 取得此股票的交易資料。</p>
            </div>
        </div>
        """
        summary_row = f"""
        <tr>
            <td><a href="#stock-{stock_id}" class="stock-link">{stock_id}</a></td>
            <td><b>{stock_name}</b></td>
            <td>-</td><td>-</td><td>-</td><td>-</td>
            <td><span class="signal death">❌ 無資料</span></td>
        </tr>
        """
        return stock_id, summary_row, error_card

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    current_price, change_val_str, change_pct_str, change_class = 'N/A', '0.00', '0.00%', 'neutral'
    price_val = 0.0
    try:
        if len(df) >= 2:
            latest_close = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            change_val = latest_close - prev_close
            change_pct = (change_val / prev_close) * 100
            current_price = f"{latest_close:.2f}"
            price_val = float(latest_close)
            if change_val > 0:
                change_val_str, change_pct_str, change_class = f"+{change_val:.2f}", f"+{change_pct:.2f}%", 'up'
            elif change_val < 0:
                change_val_str, change_pct_str, change_class = f"{change_val:.2f}", f"{change_pct:.2f}%", 'down'
    except:
        pass

    fin_table_html, eps_val = get_financial_statements_data(stock_id)

    eps_str, pe_str, dividend_str, yield_str, payout_str, raw_yield_val = 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 0.0
    div_val = 0.0

    if eps_val > 0:
        eps_str = f"{eps_val:.2f}"
        if price_val > 0:
            pe_val = price_val / eps_val
            pe_str = f"{pe_val:.2f}"

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        div_val = info.get('dividendRate') or info.get('lastDividendValue', 0.0)
        dividend_str = f"{div_val:.2f}元" if div_val else "0.00元"
        yield_val = info.get('dividendYield')
        if yield_val and yield_val < 1:
            raw_yield_val = yield_val * 100
            yield_str = f"{raw_yield_val:.2f}%"
        elif div_val > 0 and price_val > 0:
            raw_yield_val = (div_val / price_val) * 100
            yield_str = f"{raw_yield_val:.2f}%"
        if div_val > 0 and eps_val > 0:
            payout_str = f"{(div_val / eps_val) * 100:.1f}%"
    except:
        pass

    eps_v12 = eps_val * 12 if eps_val > 0 else 0
    eps_v15 = eps_val * 15 if eps_val > 0 else 0
    eps_v20 = eps_val * 20 if eps_val > 0 else 0
    eps_val_html = f"12倍: <b>{eps_v12:.1f}元</b> | 15倍(中): <b>{eps_v15:.1f}元</b> | 20倍: <b>{eps_v20:.1f}元</b>" if eps_val > 0 else "資料不足"

    val_3pct = div_val / 0.03 if div_val > 0 else 0
    val_4pct = div_val / 0.04 if div_val > 0 else 0
    val_5pct = div_val / 0.05 if div_val > 0 else 0
    yield_val_html = f"3%殖利率(昂貴): <b>{val_3pct:.1f}元</b> | 4%殖利率(合理): <b>{val_4pct:.1f}元</b> | 5%殖利率(便宜): <b>{val_5pct:.1f}元</b>" if div_val > 0 else "資料不足"

    n = 9
    rsv = (df['Close'] - df['Low'].rolling(window=n).min()) / (df['High'].rolling(window=n).max() - df['Low'].rolling(window=n).min()) * 100
    k_list, d_list = [50.0], [50.0]
    for r in rsv.values[1:]:
        k_list.append((2 / 3) * k_list[-1] + (1 / 3) * r if not pd.isna(r) else k_list[-1])
        d_list.append((2 / 3) * d_list[-1] + (1 / 3) * k_list[-1])
    latest_k, latest_d = k_list[-1], d_list[-1]
    prev_k, prev_d = k_list[-2], d_list[-2]

    # 【修改處】：最右側改為直接顯示 KD 數值與對應區塊標籤
    if latest_k <= 20:
        kd_numeric_display = f'<span class="badge-kd-low">K: {latest_k:.2f} / D: {latest_d:.2f}</span>'
    elif latest_k >= 80:
        kd_numeric_display = f'<span class="badge-kd-high">K: {latest_k:.2f} / D: {latest_d:.2f}</span>'
    else:
        kd_numeric_display = f'<span class="badge-neutral">K: {latest_k:.2f} / D: {latest_d:.2f}</span>'

    if prev_k <= prev_d and latest_k > latest_d:
        signal, signal_class = "🌟 黃金交叉", "golden"
    elif prev_k >= prev_d and latest_k < latest_d:
        signal, signal_class = "⚠️ 死亡交叉", "death"
    else:
        signal, signal_class = ("多頭", "bull") if latest_k > latest_d else ("空頭", "bear")

    monthly_rev_html = get_real_monthly_revenue(stock_id, symbol)
    chart_html = generate_professional_chart(df, stock_id, stock_name)
    
    shareholder_charts_html = create_shareholder_charts(stock_id, df)
    rev_table_html = get_real_monthly_revenue_table(stock_id)

    latest_date = df.index[-1].strftime('%Y-%m-%d')
    k_display = f"<span class='oversold-large'>🔥 超賣區 K={latest_k:.2f}</span>" if latest_k <= 20 else f"K值: {latest_k:.2f}"
    
    if raw_yield_val > 4.5:
        yield_table_display = f'<span class="high-yield-table"><b>{yield_str}</b></span>'
        yield_card_display = f'<span class="high-yield-large"><b>{yield_str}</b></span>'
    else:
        yield_table_display = f"<b>{yield_str}</b>"
        yield_card_display = f"<b>{yield_str}</b>"

    summary_row = f"""
    <tr>
        <td><a href="#stock-{stock_id}" class="stock-link">{stock_id}</a></td>
        <td><b><a href="#stock-{stock_id}" class="stock-link">{stock_name}</a></b></td>
        <td>{current_price}</td>
        <td>{latest_k:.2f}</td>
        <td>{latest_d:.2f}</td>
        <td>{yield_table_display}</td>
        <td>{kd_numeric_display}</td>
    </tr>
    """

    card_html = f"""
    <div class="stock-card" id="stock-{stock_id}">
        <div class="stock-header">
            <span>代碼: <b>{stock_id}</b> | 名稱: <b>{stock_name}</b></span>
            <div>
                <a href="#top" class="back-to-top">⬆️ 回頂部總覽</a>
                <span class="stock-date" style="margin-left: 15px;">日期: {latest_date}</span>
            </div>
        </div>
        <div class="stock-body">
            <div class="price-section">
                限價: <span class="{change_class}">{current_price} &nbsp; {change_val_str} &nbsp; {change_pct_str}</span>
            </div>
            <div class="info-grid">
                <div>💰 EPS: <b>{eps_str}</b></div>
                <div>本益比: <b>{pe_str}</b></div>
                <div>配息: <b>{dividend_str}</b></div>
                <div>殖利率: {yield_card_display}</div>
                <div>配息率: <b>{payout_str}</b></div>
            </div>
            
            <div class="valuation-box">
                <div style="margin-bottom: 6px;">🎯 <b>最近四季 EPS 估價法：</b> {eps_val_html}</div>
                <div>💰 <b>殖利率反推合理價：</b> {yield_val_html}</div>
            </div>

            <div class="kd-section">
                -> {k_display} | D值: {latest_d:.2f} | 狀態: <span class="signal {signal_class}">{signal}</span>
            </div>
            
            {monthly_rev_html}

            <div style="margin-top: 20px; background: #22252a; padding: 15px; border-radius: 8px;">
                <div class="block-title" style="margin-bottom: 10px;">📈 <b>三大法人籌碼趨勢圖表區</b></div>
                {shareholder_charts_html}
            </div>

            <div class="tables-grid-container" style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px;">
                <div style="background: #22252a; padding: 15px; border-radius: 8px;">
                    <div class="block-title">📊 <b>近期月營收與年成長率 (YoY)</b></div>
                    {rev_table_html}
                </div>
                <div style="background: #22252a; padding: 15px; border-radius: 8px;">
                    <div class="block-title">📑 <b>季別財務指標 (毛利/營益/淨利)</b></div>
                    {fin_table_html}
                </div>
            </div>

            <details class="chart-details" style="margin-top: 20px;">
                <summary>📊 點選展開詳細技術分析圖表與指標解說</summary>
                <div class="chart-content">
                    <div class="chart-guide">
                        <b>📈 技術分析圖表說明：</b>
                        <ul>
                            <li><b>1. K線與均線 (MA)：</b>顯示每日股價漲跌（紅漲綠跌）與 5日/10日/20日平均趨勢。</li>
                            <li><b>2. 成交量 (VOL)：</b>顯示當日交易張數，量能放大通常代表市場關注度高。</li>
                            <li><b>3. KD 指標：</b>判斷短線超買超賣，低於20代表超賣（可能反彈），高於80代表超買。</li>
                            <li><b>4. MACD 指標：</b>判斷中長期多空動能與趨勢轉折。</li>
                        </ul>
                    </div>
                    <div style="margin-top: 15px;">{chart_html}</div>
                </div>
            </details>

        </div>
    </div>
    """
    print(f"✅ 完成: {stock_id} {stock_name}")
    return stock_id, summary_row, card_html

# ==========================================
# 讀取 stocks.txt 檔案
# ==========================================
stock_data = []
if os.path.exists(input_filename):
    with open(input_filename, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                parts = line.replace(',', ' ').split()
                if len(parts) >= 2:
                    stock_data.append((parts[0], parts[1]))
                elif len(parts) == 1:
                    stock_data.append((parts[0], f"股票{parts[0]}"))
else:
    stock_data = [('6803', '崑鼎'), ('2330', '台積電')]

print(f"🚀 成功從 {input_filename} 載入 {len(stock_data)} 檔股票，啟動多執行緒平行查詢...\n")

summary_rows_dict = {}
cards_dict = {}
with ThreadPoolExecutor(max_workers=min(10, len(stock_data))) as executor:
    future_to_stock = {executor.submit(get_stock_data, s_id, s_name): (s_id, s_name) for s_id, s_name in stock_data}
    for future in as_completed(future_to_stock):
        s_id, s_row, s_card = future.result()
        summary_rows_dict[s_id] = s_row
        cards_dict[s_id] = s_card

summary_table_content = "".join([summary_rows_dict.get(s_id, "") for s_id, _ in stock_data])
cards_html_content = "".join([cards_dict.get(s_id, "") for s_id, _ in stock_data])

html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>台股核心觀察股票監控儀表板</title>
    <style>
        body {{ background-color: #121212; color: #f0f0f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; font-size: 16px; scroll-behavior: smooth; }}
        h1 {{ text-align: center; color: #ffffff; margin-bottom: 10px; font-size: 26px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        
        .table-container {{ background-color: #1e1e1e; border: 1px solid #444; border-radius: 10px; margin-bottom: 40px; box-shadow: 0 6px 12px rgba(0,0,0,0.4); overflow: hidden; padding: 15px; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; }}
        th {{ background-color: #2c2c2c; color: #fff; padding: 12px 15px; font-size: 16px; border-bottom: 2px solid #555; }}
        td {{ padding: 12px 15px; border-bottom: 1px solid #333; font-size: 16px; }}
        tr:hover {{ background-color: #262626; }}
        .stock-link {{ color: #64b5f6; text-decoration: none; font-weight: bold; }}
        .stock-link:hover {{ text-decoration: underline; color: #90caf9; }}
        
        .fin-table {{ width: 100%; border-collapse: collapse; background-color: #22252a; border-radius: 6px; overflow: hidden; font-size: 14px; margin-top: 5px; }}
        .fin-table th {{ background-color: #2a2f38; color: #64b5f6; padding: 8px 10px; font-size: 14px; border-bottom: 1px solid #444; }}
        .fin-table td {{ padding: 8px 10px; border-bottom: 1px solid #333; color: #ddd; }}
        .block-title {{ font-size: 15px; color: #ffb74d; margin-bottom: 6px; }}

        .badge-kd-low {{ background-color: #c62828; color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 14px; font-weight: bold; display: inline-block; }}
        .badge-kd-high {{ background-color: #2e7d32; color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 14px; font-weight: bold; display: inline-block; }}
        .badge-neutral {{ background-color: #424242; color: #ccc; padding: 4px 8px; border-radius: 4px; font-size: 14px; display: inline-block; }}
        
        .high-yield-table {{ background-color: #f57f17; color: #ffffff; padding: 4px 8px; border-radius: 4px; font-size: 16px; display: inline-block; }}
        .high-yield-large {{ background-color: #f57f17; color: #ffffff; padding: 5px 10px; border-radius: 6px; font-size: 19px; }}

        .stock-card {{ background-color: #1e1e1e; border: 1px solid #444; border-radius: 10px; margin-bottom: 35px; box-shadow: 0 6px 12px rgba(0,0,0,0.4); overflow: hidden; scroll-margin-top: 20px; }}
        .error-card {{ border: 1px solid #c62828; background-color: #2c1a1a; }}
        .stock-header {{ background-color: #2c2c2c; padding: 14px 20px; font-size: 20px; border-bottom: 1px solid #444; display: flex; justify-content: space-between; align-items: center; }}
        .stock-date {{ color: #ccc; font-size: 15px; }}
        .back-to-top {{ color: #ffb74d; text-decoration: none; font-size: 14px; background: #3e2723; padding: 4px 10px; border-radius: 4px; border: 1px solid #d7ccc8; }}
        .back-to-top:hover {{ background: #4e342e; }}
        .stock-body {{ padding: 20px; }}
        .price-section {{ font-size: 22px; font-weight: bold; margin-bottom: 15px; }}
        .up {{ color: #ff5252; }} .down {{ color: #00e676; }} .neutral {{ color: #f0f0f0; }}
        .info-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; background-color: #252525; padding: 15px; border-radius: 8px; margin-bottom: 15px; font-size: 17px; }}
        .valuation-box {{ background-color: #252b3b; border-left: 5px solid #ab47bc; padding: 14px 18px; border-radius: 6px; font-size: 16px; line-height: 1.6; margin-bottom: 15px; color: #e0e0e0; }}
        .kd-section {{ font-size: 19px; margin-bottom: 15px; font-weight: bold; }}
        .oversold-large {{ background-color: #c62828; color: #ffffff; padding: 6px 12px; border-radius: 6px; font-size: 20px; }}
        .signal.golden {{ color: #ffd700; }} .signal.death {{ color: #00e676; }} .signal.bull {{ color: #ff5252; }} .signal.bear {{ color: #00e676; }}
        .chart-details {{ margin-top: 15px; background-color: #22252a; border: 1px solid #333; border-radius: 6px; overflow: hidden; }}
        .chart-details summary {{ padding: 12px 18px; font-size: 18px; font-weight: bold; color: #64b5f6; cursor: pointer; background-color: #2a2f38; transition: background 0.2s; }}
        .chart-details summary:hover {{ background-color: #323842; }}
        .chart-content {{ padding: 15px; }}
        .chart-guide {{ background-color: #1a1c20; border-left: 5px solid #ff9800; padding: 12px 18px; border-radius: 6px; font-size: 15px; line-height: 1.5; margin-bottom: 10px; color: #d1d5db; }}
        .chart-guide ul {{ margin: 5px 0 0 20px; padding: 0; }}
        .revenue-box {{ background-color: #22252a; border-left: 5px solid #2196f3; padding: 15px; border-radius: 6px; font-size: 17px; line-height: 1.6; margin-bottom: 15px; }}
        .rev-row {{ background-color: #22252a; padding: 12px 15px; border-radius: 6px; font-size: 17px; color: #b0bec5; margin-bottom: 15px; }}
        .yoy-val {{ font-weight: bold; font-size: 18px; }}
        .cache-tag {{ color: #aaa; font-size: 14px; }}
        .error {{ border-left: 5px solid #f44336; color: #ff8a80; padding: 20px; }}
        
        @media (max-width: 900px) {{
            .tables-grid-container {{ grid-template-columns: 1fr !important; }}
        }}
    </style>
</head>
<body>
    <div class="container" id="top">
        <h1>📊 台股核心觀察股票監控儀表板</h1>
        <div style="text-align: center; color: #aaa; margin-bottom: 20px; font-size: 15px;">更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 點擊下方表格代號可直接檢視詳細技術分析與圖表</div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>代號</th>
                        <th>名稱</th>
                        <th>收盤價</th>
                        <th>K值</th>
                        <th>D值</th>
                        <th>殖利率</th>
                        <th>狀態</th>
                    </tr>
                </thead>
                <tbody>
                    {summary_table_content}
                </tbody>
            </table>
        </div>

        {cards_html_content}
    </div>
</body>
</html>
"""

# ==========================================
# 寫入本機檔案並檢查 GitHub 遠端發布狀態
# ==========================================
with open(output_filename, 'w', encoding='utf-8') as f:
    f.write(html_template)

print(f"🎉 報告已成功生成至本機 {output_filename}")

# 自動嘗試推送到 GitHub
git_result = push_to_github_via_git(output_filename)

github_status_html = ""
github_pages_url = ""

if isinstance(git_result, str):
    github_pages_url = git_result
    print(f"🌐 您的 GitHub Pages 線上報告網址: {github_pages_url}")
    
    try:
        print("🔍 正在檢驗 GitHub 遠端線上檔案是否已同步更新...")
        res = requests.get(github_pages_url + "?t=" + str(datetime.now().timestamp()), timeout=5)
        if res.status_code == 200:
            remote_content = res.text
            with open(output_filename, 'r', encoding='utf-8') as local_f:
                local_content = local_f.read()
            
            if remote_content.strip() == local_content.strip():
                github_status_html = f'<div style="background-color: #1b5e20; color: #a5d6a7; padding: 10px 15px; border-radius: 6px; text-align: center; margin-bottom: 20px; font-weight: bold;">✅ GitHub 狀態：遠端線上版本已完整發布並與本機一致！ (<a href="{github_pages_url}" target="_blank" style="color: #ffffff; text-decoration: underline;">點此查看線上網址</a>)</div>'
            else:
                github_status_html = f'<div style="background-color: #e65100; color: #ffe0b2; padding: 10px 15px; border-radius: 6px; text-align: center; margin-bottom: 20px; font-weight: bold;">⚠️ GitHub 狀態：遠端線上檔案尚未更新完成（可能正在CDN快取同步中），請稍後重新整理。</div>'
        else:
            github_status_html = f'<div style="background-color: #b71c1c; color: #ffcdd2; padding: 10px 15px; border-radius: 6px; text-align: center; margin-bottom: 20px; font-weight: bold;">❌ GitHub 狀態：無法讀取遠端線上網址（狀態碼: {res.status_code}）</div>'
    except Exception as e:
        github_status_html = f'<div style="background-color: #b71c1c; color: #ffcdd2; padding: 10px 15px; border-radius: 6px; text-align: center; margin-bottom: 20px; font-weight: bold;">❌ GitHub 狀態檢查發生例外錯誤: {e}</div>'
else:
    github_status_html = '<div style="background-color: #b71c1c; color: #ffcdd2; padding: 10px 15px; border-radius: 6px; text-align: center; margin-bottom: 20px; font-weight: bold;">❌ GitHub 狀態：Git 自動推送失敗，線上尚未更新！</div>'

with open(output_filename, 'r', encoding='utf-8') as f:
    final_html_content = f.read()

final_html_content = final_html_content.replace(
    '<div class="container" id="top">',
    f'<div class="container" id="top">\n        {github_status_html}'
)

with open(output_filename, 'w', encoding='utf-8') as f:
    f.write(final_html_content)

try:
    webbrowser.open('file://' + os.path.abspath(output_filename))
except:
    pass