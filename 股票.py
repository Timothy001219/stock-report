from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import os
import subprocess
import sys
import webbrowser
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import yfinance as yf

# 檔案名稱設定
REVENUE_CACHE_FILE = 'revenue_cache.json'
INFO_FILE = 'information.txt'

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
        
        # 1. 執行 git add
        subprocess.run(["git", "add", filename], check=True, capture_output=True)
        
        # 2. 執行 git commit
        commit_msg = f"自動更新台股技術分析報告: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True)
        
        # 3. 執行 git push (設定 30 秒逾時)
        result = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            print("✅ GitHub 雲端同步成功！")
            
            # 自動從 git remote 抓取並組合出 GitHub Pages 網址
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
            print(f"⚠️ Git push 失敗或無變更需要推送: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("⚠️ Git 推送連線逾時，請檢查網路狀況。")
    except Exception as e:
        print(f"⚠️ Git 自動推送發生錯誤: {e}")
    return False

def load_revenue_cache():
    if os.path.exists(REVENUE_CACHE_FILE):
        try:
            with open(REVENUE_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_revenue_cache(cache_data):
    try:
        with open(REVENUE_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
    except:
        pass

def get_real_monthly_revenue(stock_id, symbol=None):
    today = datetime.now()
    rev_cache = load_revenue_cache()
    
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
                
                save_revenue_cache(rev_cache)
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

        # 🚀 關鍵優化：改用 cdn 載入 Plotly JS，大幅縮減 HTML 檔案體積
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception as e:
        return f"<div class='error'>圖表產生失敗: {e}</div>"

def get_stock_data(stock_id, stock_name):
    stock_id = stock_id.strip()
    symbol, df = None, pd.DataFrame()
    candidates = [f"{stock_id}.TW", f"{stock_id}.TWO"]

    class Silence:
        def __enter__(self):
            self._original_stderr = sys.stderr
            sys.stderr = open(os.devnull, 'w')
        def __exit__(self, exc_type, exc_val, exc_tb):
            sys.stderr.close()
            sys.stderr = self._original_stderr

    for cand in candidates:
        try:
            with Silence():
                # 🚀 調整為 180天，確保技術指標有足夠資料可以計算
                temp_df = yf.download(cand, period='180d', interval='1d', progress=False)
            if not temp_df.empty and len(temp_df) > 0:
                df = temp_df
                symbol = cand
                break
        except:
            continue

    if df.empty or symbol is None:
        error_card = f"""
        <div class="stock-card error-card">
            <div class="stock-header">
                <span>代碼: <b>{stock_id}</b> | 名稱: <b>{stock_name}</b></span>
                <span class="stock-date">狀態: ❌ 查無資料</span>
            </div>
            <div class="stock-body">
                <p style="color: #ff8a80; margin: 0;">無法從 Yahoo Finance 取得此股票的交易資料。</p>
            </div>
        </div>
        """
        return stock_id, error_card

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    current_price, change_val_str, change_pct_str, change_class = 'N/A', '0.00', '0.00%', 'neutral'
    try:
        if len(df) >= 2:
            latest_close = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2]
            change_val = latest_close - prev_close
            change_pct = (change_val / prev_close) * 100
            current_price = f"{latest_close:.2f}"
            if change_val > 0:
                change_val_str, change_pct_str, change_class = f"+{change_val:.2f}", f"+{change_pct:.2f}%", 'up'
            elif change_val < 0:
                change_val_str, change_pct_str, change_class = f"{change_val:.2f}", f"{change_pct:.2f}%", 'down'
    except:
        pass

    eps_str, pe_str, dividend_str, yield_str, payout_str, raw_yield_val = 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 0.0
    eps_val = 0.0
    div_val = 0.0

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        eps_val = info.get('trailingEps', 0.0) or 0.0
        if eps_val:
            eps_str = f"{eps_val:.2f}"
        pe_val = info.get('trailingPE')
        if pe_val:
            pe_str = f"{pe_val:.2f}"
        div_val = info.get('dividendRate') or info.get('lastDividendValue', 0.0)
        dividend_str = f"{div_val:.2f}元" if div_val else "0.00元"
        price_val = float(current_price) if current_price != 'N/A' else 0.0
        yield_val = info.get('dividendYield')
        if yield_val and yield_val < 1:
            raw_yield_val = yield_val * 100
            yield_str = f"{raw_yield_val:.2f}%"
        elif div_val > 0 and price_val > 0:
            raw_yield_val = (div_val / price_val) * 100
            yield_str = f"{raw_yield_val:.2f}%"
        if div_val > 0 and eps_val and eps_val > 0:
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

    if prev_k <= prev_d and latest_k > latest_d:
        signal, signal_class = "🌟 黃金交叉", "golden"
    elif prev_k >= prev_d and latest_k < latest_d:
        signal, signal_class = "⚠️ 死亡交叉", "death"
    else:
        signal, signal_class = ("多頭", "bull") if latest_k > latest_d else ("空頭", "bear")

    monthly_rev_html = get_real_monthly_revenue(stock_id, symbol)
    chart_html = generate_professional_chart(df, stock_id, stock_name)
    latest_date = df.index[-1].strftime('%Y-%m-%d')

    k_display = f"<span class='oversold-large'>🔥 超賣區 K={latest_k:.2f}</span>" if latest_k <= 20 else f"K值: {latest_k:.2f}"
    yield_display = f"<span class='high-yield-large'><b>{yield_str}</b></span>" if raw_yield_val > 4.5 else f"<b>{yield_str}</b>"

    card_html = f"""
    <div class="stock-card">
        <div class="stock-header">
            <span>代碼: <b>{stock_id}</b> | 名稱: <b>{stock_name}</b></span>
            <span class="stock-date">日期: {latest_date}</span>
        </div>
        <div class="stock-body">
            <div class="price-section">
                限價: <span class="{change_class}">{current_price} &nbsp; {change_val_str} &nbsp; {change_pct_str}</span>
            </div>
            <div class="info-grid">
                <div>💰 EPS: <b>{eps_str}</b></div>
                <div>本益比: <b>{pe_str}</b></div>
                <div>配息: <b>{dividend_str}</b></div>
                <div>殖利率: {yield_display}</div>
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

            <details class="chart-details">
                <summary>📊 點選展開技術分析圖表與指標解說</summary>
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
    return stock_id, card_html

input_filename = 'stocks.txt'
output_filename = 'kd_result.html'
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

print(f"🚀 啟動多執行緒平行查詢，共計 {len(stock_data)} 檔股票...\n")

results_dict = {}
with ThreadPoolExecutor(max_workers=min(10, len(stock_data))) as executor:
    future_to_stock = {executor.submit(get_stock_data, s_id, s_name): (s_id, s_name) for s_id, s_name in stock_data}
    for future in as_completed(future_to_stock):
        s_id, res_str = future.result()
        results_dict[s_id] = res_str

cards_html_content = "".join([results_dict.get(s_id, "") for s_id, _ in stock_data])

html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>台股專業技術分析與估價報告</title>
    <style>
        body {{ background-color: #121212; color: #f0f0f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; font-size: 18px; }}
        h1 {{ text-align: center; color: #ffffff; margin-bottom: 30px; font-size: 28px; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        .stock-card {{ background-color: #1e1e1e; border: 1px solid #444; border-radius: 10px; margin-bottom: 25px; box-shadow: 0 6px 12px rgba(0,0,0,0.4); overflow: hidden; }}
        .error-card {{ border: 1px solid #c62828; background-color: #2c1a1a; }}
        .stock-header {{ background-color: #2c2c2c; padding: 14px 20px; font-size: 20px; border-bottom: 1px solid #444; display: flex; justify-content: space-between; align-items: center; }}
        .stock-date {{ color: #ccc; font-size: 16px; }}
        .stock-body {{ padding: 20px; }}
        .price-section {{ font-size: 22px; font-weight: bold; margin-bottom: 15px; }}
        .up {{ color: #ff5252; }} .down {{ color: #00e676; }} .neutral {{ color: #f0f0f0; }}
        .info-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; background-color: #252525; padding: 15px; border-radius: 8px; margin-bottom: 15px; font-size: 17px; }}
        .valuation-box {{ background-color: #252b3b; border-left: 5px solid #ab47bc; padding: 14px 18px; border-radius: 6px; font-size: 16px; line-height: 1.6; margin-bottom: 15px; color: #e0e0e0; }}
        .kd-section {{ font-size: 19px; margin-bottom: 15px; font-weight: bold; }}
        .oversold-large {{ background-color: #c62828; color: #ffffff; padding: 6px 12px; border-radius: 6px; font-size: 20px; }}
        .high-yield-large {{ background-color: #f57f17; color: #ffffff; padding: 5px 10px; border-radius: 6px; font-size: 19px; }}
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
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 台股專業技術分析與估價報告</h1>
        <div style="text-align: center; color: #aaa; margin-bottom: 25px; font-size: 16px;">更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        {cards_html_content}
    </div>
</body>
</html>
"""

with open(output_filename, 'w', encoding='utf-8') as f:
    f.write(html_template)

print(f'\n🎉 本機報表已暫存完成')

# 透過 Git 自動推送到雲端
online_url = push_to_github_via_git(output_filename)

if online_url and isinstance(online_url, str):
    print('\n==================================================')
    print('🌐 您的【線上永久網址】：')
    print(online_url)
    print('==================================================\n')
    webbrowser.open(online_url)
else:
    print('⚠️ 自動推送 GitHub 失敗（或本機未設定 Git 遠端倉庫），已自動改為開啟本機報表。')
    webbrowser.open(f'file:///{os.path.abspath(output_filename)}')

input('\n請按 Enter 鍵離開程式...')