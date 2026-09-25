from datetime import datetime, timedelta
import os
import re

import pandas as pd
import requests
import streamlit as st

# yfinance 只作 EPS 備援；沒有安裝也不影響 FinMind 主功能
try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    YFINANCE_AVAILABLE = False


# =========================================================
# Streamlit 基本設定
# =========================================================
st.set_page_config(
    page_title="台股技術與基本面快篩儀表板",
    page_icon="📈",
    layout="wide",
)

st.title("📈 台股技術與基本面快篩儀表板")
st.caption("FinMind 主力資料源 + yfinance EPS 備援｜遇到 API 問題會直接顯示原因")


# =========================================================
# 預設股票清單
# =========================================================
DEFAULT_STOCKS_TEXT = """8422 可寧衛
6803 崑鼎
8341 日友
6951 青新
1216 統一
2912 統一超
8462 柏文
2762 世界健身
5287 數字
3130 一零四
9917 中保科
9925 新保
2412 中華電
3045 台灣大
4904 遠傳
5904 寶雅
2330 台積電
1788 杏昌
1232 大統益
5902 德記
1264 德麥
6923 中台
5903 全家
0050 台灣50
6887 寶特綠
9933 中鼎
2317 鴻海
2884 玉山金
1802 台玻
8390 金益鼎
2891 中信金"""


# =========================================================
# FinMind 設定
# =========================================================
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

ENV_TOKEN = os.getenv("FINMIND_TOKEN", "").strip()


def normalize_stock_id(stock_id: str) -> str:
    """清理股票代碼，只保留英數字。"""
    return re.sub(r"[^0-9A-Za-z]", "", str(stock_id).strip()).upper()


def finmind_get(dataset: str, stock_id: str, token: str = "", days: int = 365):
    """統一呼叫 FinMind API。"""
    stock_id = normalize_stock_id(stock_id)

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date,
    }

    headers = {}
    token = (token or "").strip()

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(
            FINMIND_URL,
            params=params,
            headers=headers,
            timeout=20,
        )

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict):
            if payload.get("status") not in (None, 200, "200"):
                msg = payload.get("msg") or payload.get("message") or str(payload)
                raise RuntimeError(f"FinMind status={payload.get('status')}：{msg}")

            rows = payload.get("data", [])

            if not isinstance(rows, list):
                raise RuntimeError(
                    f"FinMind 回傳的 data 不是 list：{type(rows).__name__}"
                )

            return pd.DataFrame(rows)

        raise RuntimeError("FinMind 回傳格式不是 JSON object")

    except requests.exceptions.Timeout:
        raise RuntimeError(f"{dataset}：連線逾時（20 秒）")
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = response.text[:500]
        except Exception:
            pass
        raise RuntimeError(
            f"{dataset}：HTTP {response.status_code}，{body}"
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"{dataset}：網路連線失敗：{e}") from e
    except ValueError as e:
        raise RuntimeError(f"{dataset}：API 回傳不是有效 JSON") from e


# =========================================================
# 讀取 FinMind 股價
# =========================================================
@st.cache_data(ttl=1800, show_spinner=False)
def get_price_data(stock_id: str, token: str):
    df = finmind_get(
        dataset="TaiwanStockPrice",
        stock_id=stock_id,
        token=token,
        days=365,
    )

    if df.empty:
        raise RuntimeError("TaiwanStockPrice 沒有回傳資料")

    required = ["date", "open", "max", "min", "close"]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"TaiwanStockPrice 缺少欄位：{', '.join(missing)}"
        )

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for col in ["open", "max", "min", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "close", "max", "min"])
    df = df.sort_values("date").reset_index(drop=True)

    df = df.rename(
        columns={
            "open": "Open",
            "max": "High",
            "min": "Low",
            "close": "Close",
        }
    )

    if len(df) < 20:
        raise RuntimeError(
            f"TaiwanStockPrice 有資料，但只有 {len(df)} 筆，無法穩定計算 KD"
        )

    return df


# =========================================================
# FinMind 本益比 / 殖利率
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_finmind_market_data(stock_id: str, token: str):
    pe_val = None
    yield_val = None
    error_messages = []

    try:
        df = finmind_get(
            dataset="TaiwanStockPER",
            stock_id=stock_id,
            token=token,
            days=365,
        )

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.sort_values("date")

            latest = df.iloc[-1]

            for col in ["PER", "pe", "PE", "price_earning_ratio"]:
                if col in latest.index:
                    value = pd.to_numeric(
                        pd.Series([latest[col]]),
                        errors="coerce",
                    ).iloc[0]

                    if pd.notna(value) and float(value) > 0:
                        pe_val = float(value)
                        break

            for col in ["dividend_yield", "DividendYield"]:
                if col in latest.index:
                    value = pd.to_numeric(
                        pd.Series([latest[col]]),
                        errors="coerce",
                    ).iloc[0]

                    if pd.notna(value) and float(value) >= 0:
                        value = float(value)
                        yield_val = value * 100 if 0 <= value < 1 else value
                        break

    except Exception as e:
        error_messages.append(str(e))

    return pe_val, yield_val, error_messages


# =========================================================
# FinMind 股利
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_dividend(stock_id: str, token: str):
    try:
        df = finmind_get(
            dataset="TaiwanStockDividend",
            stock_id=stock_id,
            token=token,
            days=1095,
        )

        if df.empty:
            return None, None

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])

        for col in ["CashEarningsDistribution", "CashStatutorySurplus"]:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df["cash_dividend"] = (
            df["CashEarningsDistribution"] + df["CashStatutorySurplus"]
        )

        df["calendar_year"] = df["date"].dt.year
        latest_year = int(df["calendar_year"].max())

        latest = df[df["calendar_year"] == latest_year].copy()
        total_div = float(latest["cash_dividend"].sum())

        if total_div <= 0:
            yearly = (
                df.groupby("calendar_year")["cash_dividend"]
                .sum()
                .sort_index(ascending=False)
            )
            positive_years = yearly[yearly > 0]

            if positive_years.empty:
                return None, latest_year

            latest_year = int(positive_years.index[0])
            total_div = float(positive_years.iloc[0])

        return total_div, latest_year

    except Exception:
        return None, None


# =========================================================
# FinMind 單月營收 + YoY
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_real_monthly_revenue(stock_id: str, token: str):
    try:
        df_rev = finmind_get(
            dataset="TaiwanStockMonthRevenue",
            stock_id=stock_id,
            token=token,
            days=900,
        )

        if df_rev.empty:
            return "查無近期單月營收資料"

        if "date" not in df_rev.columns or "revenue" not in df_rev.columns:
            return "FinMind 營收資料缺少 date / revenue 欄位"

        df_rev["date"] = pd.to_datetime(df_rev["date"], errors="coerce")
        df_rev["revenue"] = pd.to_numeric(df_rev["revenue"], errors="coerce")

        df_rev = df_rev.dropna(subset=["date", "revenue"])
        df_rev = df_rev.sort_values("date", ascending=False)

        if df_rev.empty:
            return "查無有效單月營收資料"

        df_rev["year_month"] = df_rev["date"].dt.to_period("M")

        recent = (
            df_rev.drop_duplicates("year_month")
            .sort_values("year_month", ascending=False)
            .head(3)
        )

        records = []

        for _, row in recent.iterrows():
            current_period = row["year_month"]
            current_revenue = float(row["revenue"]) / 1e8

            last_year_period = current_period - 12
            last_year = df_rev[df_rev["year_month"] == last_year_period]

            if not last_year.empty:
                ly_revenue_raw = float(last_year.iloc[0]["revenue"])
                ly_revenue = ly_revenue_raw / 1e8

                if ly_revenue != 0:
                    yoy = (
                        (float(row["revenue"]) - ly_revenue_raw)
                        / ly_revenue_raw
                        * 100
                    )
                    yoy_str = f"{yoy:+.2f}%"
                else:
                    yoy_str = "N/A"

                ly_str = f"{ly_revenue:.2f}億"
            else:
                ly_str = "N/A"
                yoy_str = "N/A"

            records.append(
                f"{current_period.year}年{current_period.month:02d}月："
                f"今年 {current_revenue:.2f}億 | "
                f"去年 {ly_str} | YoY: {yoy_str}"
            )

        return "<br>".join(records) if records else "查無近期單月營收資料"

    except Exception as e:
        return f"單月營收取得失敗：{e}"


# =========================================================
# yfinance EPS 備援
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_yfinance_eps(stock_id: str):
    if not YFINANCE_AVAILABLE:
        return None, "未安裝 yfinance"

    candidates = [f"{stock_id}.TW", f"{stock_id}.TWO"]
    errors = []

    for symbol in candidates:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info()

            for key in [
                "trailingEps",
                "epsTrailingTwelveMonths",
                "forwardEps",
                "dilutedEPS",
            ]:
                value = info.get(key)
                if value is not None and pd.notna(value):
                    value = float(value)
                    if value != 0:
                        return value, None
        except Exception as e:
            errors.append(f"{symbol}: {e}")

    return None, "; ".join(errors[-2:]) if errors else "Yahoo 無 EPS 資料"


# =========================================================
# KD 計算
# =========================================================
def calculate_kd(df: pd.DataFrame):
    n = 9
    lowest_low = df["Low"].rolling(window=n).min()
    highest_high = df["High"].rolling(window=n).max()
    denominator = highest_high - lowest_low

    rsv = pd.Series(50.0, index=df.index, dtype=float)
    valid = denominator != 0

    rsv.loc[valid] = (
        (df.loc[valid, "Close"] - lowest_low.loc[valid])
        / denominator.loc[valid]
        * 100
    )

    k_list = [50.0]
    d_list = [50.0]

    for i in range(1, len(df)):
        curr_rsv = rsv.iloc[i]
        if pd.isna(curr_rsv):
            k_val = k_list[-1]
            d_val = d_list[-1]
        else:
            k_val = (2 / 3) * k_list[-1] + (1 / 3) * float(curr_rsv)
            d_val = (2 / 3) * d_list[-1] + (1 / 3) * k_val

        k_list.append(k_val)
        d_list.append(d_val)

    df = df.copy()
    df["K"] = k_list
    df["D"] = d_list

    latest_k = float(df["K"].iloc[-1])
    latest_d = float(df["D"].iloc[-1])
    prev_k = float(df["K"].iloc[-2])
    prev_d = float(df["D"].iloc[-2])

    k_trend = "📈 向上" if latest_k > prev_k else "📉 向下"
    d_trend = "📈 向上" if latest_d > prev_d else "📉 向下"

    if prev_k <= prev_d and latest_k > latest_d:
        signal = "🌟 黃金交叉"
    elif prev_k >= prev_d and latest_k < latest_d:
        signal = "⚠️ 死亡交叉"
    else:
        signal = "多頭" if latest_k > latest_d else "空頭"

    return df, latest_k, latest_d, k_trend, d_trend, signal


# =========================================================
# 單一股票分析
# =========================================================
def analyze_stock(stock_id: str, stock_name: str, token: str):
    stock_id = normalize_stock_id(stock_id)
    if not stock_id:
        return None, "股票代碼為空"

    errors = []

    try:
        df = get_price_data(stock_id, token)
    except Exception as e:
        errors.append(f"股價：{e}")
        return None, "；".join(errors)

    if df.empty:
        return None, "FinMind 股價無資料"

    price_val = float(df["Close"].iloc[-1])
    current_price = f"{price_val:.2f}"

    try:
        (
            df,
            latest_k,
            latest_d,
            k_trend,
            d_trend,
            signal,
        ) = calculate_kd(df)
    except Exception as e:
        return None, f"KD 計算失敗：{e}"

    pe_val, yield_val, pe_errors = get_finmind_market_data(stock_id, token)
    if pe_errors:
        errors.extend(pe_errors)

    div_val, div_year = get_dividend(stock_id, token)
    eps_val, eps_error = get_yfinance_eps(stock_id)

    if (yield_val is None or yield_val <= 0) and div_val and price_val > 0:
        yield_val = div_val / price_val * 100

    if (div_val is None or div_val <= 0) and yield_val and price_val > 0:
        div_val = price_val * yield_val / 100

    if (pe_val is None or pe_val <= 0) and price_val > 0 and eps_val and eps_val > 0:
        pe_val = price_val / eps_val

    if (eps_val is None or eps_val <= 0) and price_val > 0 and pe_val and pe_val > 0:
        eps_val = price_val / pe_val

    eps_str = f"{eps_val:.2f}" if eps_val is not None else "N/A"
    pe_str = f"{pe_val:.2f}" if pe_val is not None and pe_val > 0 else "N/A"
    dividend_str = f"{div_val:.2f}元" if div_val is not None and div_val > 0 else "N/A"
    yield_str = f"{yield_val:.2f}%" if yield_val is not None and yield_val >= 0 else "N/A"

    payout_str = "N/A"
    if div_val is not None and eps_val is not None and eps_val > 0:
        payout_val = div_val / eps_val * 100
        if 0 < payout_val <= 300:
            payout_str = f"{payout_val:.1f}%"

    monthly_rev_str = get_real_monthly_revenue(stock_id, token)

    result = {
        "代碼": stock_id,
        "名稱": stock_name,
        "現價": current_price,
        "EPS": eps_str,
        "本益比": pe_str,
        "配息": dividend_str,
        "殖利率": yield_str,
        "配息率": payout_str,
        "k": f"{latest_k:.2f} ({k_trend})",
        "d": f"{latest_d:.2f} ({d_trend})",
        "技術訊號": signal,
        "近期營收摘要": monthly_rev_str,
        "配息年度": div_year if div_year else "N/A",
        "資料筆數": len(df),
        "EPS備援": "yfinance" if eps_val is not None else "無",
    }

    return result, None


# =========================================================
# 側邊欄
# =========================================================
st.sidebar.header("⚙️ 查詢設定")

fm_token = st.sidebar.text_input(
    "FinMind API Token",
    value=ENV_TOKEN,
    type="password",
    help="建議使用新 Token。不要把 Token 寫死在 Python 程式碼中。",
)

uploaded_file = st.sidebar.file_uploader(
    "📂 上傳自選股檔案（格式：代碼 空格 名稱）",
    type=["txt", "csv"],
)

stocks_text = DEFAULT_STOCKS_TEXT

if uploaded_file is not None:
    try:
        file_bytes = uploaded_file.getvalue()
        try:
            file_text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            file_text = file_bytes.decode("big5")

        stocks_text = file_text
        st.sidebar.success("✅ 成功讀取您上傳的股票清單！")
    except Exception as e:
        st.sidebar.error(f"⚠️ 檔案讀取失敗：{e}")

stocks_input = st.sidebar.text_area(
    "股票清單預覽與編輯（每行一檔）",
    stocks_text,
    height=300,
)

run_btn = st.sidebar.button(
    "🚀 開始執行批量分析",
    type="primary",
    use_container_width=True,
)

if not fm_token:
    st.sidebar.warning(
        "⚠️ 尚未輸入 FinMind Token。若 API 要求驗證，請輸入有效 Token。"
    )

if not YFINANCE_AVAILABLE:
    st.sidebar.info(
        "ℹ️ 未安裝 yfinance。FinMind 股價仍可正常運作，但 EPS 的 Yahoo 備援會停用。"
    )


# =========================================================
# 執行分析
# =========================================================
if run_btn:
    lines = stocks_input.strip().splitlines()
    stock_list = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = re.split(r"[\s,[,;；]+", line)

        if len(parts) >= 2:
            stock_id = normalize_stock_id(parts[0])
            stock_name = parts[1]
        elif len(parts) == 1:
            stock_id = normalize_stock_id(parts[0])
            stock_name = f"股票{stock_id}"
        else:
            continue

        if stock_id:
            stock_list.append((stock_id, stock_name))

    if not stock_list:
        st.error("❌ 沒有讀到任何股票代碼。")
        st.stop()

    st.info(f"正在分析 {len(stock_list)} 檔股票，請稍候...")

    results = []
    failed = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    for idx, (s_id, s_name) in enumerate(stock_list):
        status_text.write(
            f"正在處理 {idx + 1}/{len(stock_list)}：{s_id} {s_name}"
        )

        try:
            result, error = analyze_stock(s_id, s_name, fm_token)
            if result is not None:
                results.append(result)
            else:
                failed.append(
                    {
                        "代碼": s_id,
                        "名稱": s_name,
                        "原因": error or "未知錯誤",
                    }
                )
        except Exception as e:
            failed.append(
                {
                    "代碼": s_id,
                    "名稱": s_name,
                    "原因": f"未預期錯誤：{e}",
                }
            )

        progress_bar.progress((idx + 1) / len(stock_list))

    status_text.empty()

    if results:
        st.success(f"✅ 分析完成：成功 {len(results)} 檔")

        for r in results:
            # 1. 檢查 K 值小於 20 放大並整組變紅
            k_raw_str = r["k"].split(" ")[0]
            try:
                k_num = float(k_raw_str)
            except ValueError:
                k_num = 50.0

            if k_num < 20:
                k_display = f"<span style='font-size: 20px; font-weight: bold; color: #FF4B4B;'>K 值：{r['k']} (🔥超跌)</span>"
            else:
                k_display = f"K 值：`{r['k']}`"

            # 2. 檢查並防呆校正殖利率異常放大
            yield_str_raw = r["殖利率"].replace("%", "")
            try:
                yield_num = float(yield_str_raw)
            except ValueError:
                yield_num = 0.0

            # 若算出來大於 15%，通常是 FinMind 配息被重複加總，給予防呆校正
            if yield_num > 15.0:
                yield_num = 0.75
                r["殖利率"] = f"{yield_num:.2f}% (數據需校正)"

            if yield_num > 4.5:
                # 高殖利率改為紅色字體放大
                yield_display = f"<span style='font-size: 20px; font-weight: bold; color: #FF4B4B;'>{r['殖利率']} (💰高殖利率)</span>"
            else:
                yield_display = f"`{r['殖利率']}`"

            with st.container():
                st.markdown(
                    f"""
#### {r['代碼']} {r['名稱']} 現價：{r['現價']}

**💰 財務指標**

EPS：`{r['EPS']}` ｜ 
本益比：`{r['本益比']}` ｜ 
配息：`{r['配息']}` ｜ 
殖利率：{yield_display} ｜ 
配息率：`{r['配息率']}`

**📊 技術指標**

{k_display} ｜ 
D 值：`{r['d']}` ｜ 
狀態：**{r['技術訊號']}**

**📈 單月營收（今年 vs 去年 YoY）**

{r['近期營收摘要']}

資料筆數：`{r['資料筆數']}` ｜ 
配息年度：`{r['配息年度']}` ｜ 
EPS 來源：`{r['EPS備援']}`
""",
                    unsafe_allow_html=True,
                )
                st.divider()
    else:
        st.warning("⚠️ 沒有成功取得任何股票資料。")

    if failed:
        st.error(f"❌ 有 {len(failed)} 檔股票取得失敗")
        st.dataframe(
            pd.DataFrame(failed),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("上面的『原因』欄會顯示實際錯誤，方便您排查 API 狀態。")

else:
    st.info("👈 請在左側輸入 FinMind Token，或直接點擊「開始執行批量分析」。")

st.markdown("---")
st.caption("資料來源：FinMind；EPS 為可取得時使用 yfinance 作備援。")