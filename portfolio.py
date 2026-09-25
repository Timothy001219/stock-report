from datetime import datetime, timedelta
import json
import os
import re
import pandas as pd
import requests
import streamlit as st

# =========================================================
# Streamlit 基本設定
# =========================================================
st.set_page_config(
    page_title="我的台股持股與損益儀表板",
    page_icon="💰",
    layout="wide",
)

st.title("💰 我的台股持股與損益儀表板（支援對帳單檔案上傳）")
st.caption(
    "支援手動新增、刪除交易、配息紀錄，以及直接上傳券商對帳單 CSV/Excel 檔案自動匯入！"
)

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
DATA_FILE = "portfolio_data.json"


def normalize_stock_id(stock_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(stock_id).strip()).upper()


def finmind_get(dataset: str, stock_id: str, days: int = 30):
    stock_id = normalize_stock_id(stock_id)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
    try:
        response = requests.get(FINMIND_URL, params=params, timeout=10)
        response.raise_for_status()
        return pd.DataFrame(response.json().get("data", []))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def get_latest_price(stock_id: str) -> float:
    """取得最新收盤價作為現價"""
    df = finmind_get("TaiwanStockPrice", stock_id, days=15)
    if not df.empty and "close" in df.columns:
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        if not df.empty:
            return float(df.iloc[-1]["close"])
    return 0.0


# =========================================================
# 資料載入與存檔函式
# =========================================================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                portfolio = []
                for item in saved.get("portfolio", []):
                    item["date"] = datetime.strptime(
                        item["date"], "%Y-%m-%d"
                    ).date()
                    portfolio.append(item)

                dividends = []
                for item in saved.get("dividends", []):
                    item["date"] = datetime.strptime(
                        item["date"], "%Y-%m-%d"
                    ).date()
                    dividends.append(item)
                return portfolio, dividends
        except Exception:
            pass

    default_portfolio = [
        {
            "id": "2330",
            "name": "台積電",
            "date": datetime(2026, 2, 1).date(),
            "shares": 1000,
            "cost_price": 900.0,
        }
    ]
    default_dividends = [
        {
            "id": "2330",
            "name": "台積電",
            "date": datetime(2026, 3, 15).date(),
            "total_dividend": 4500.0,
        }
    ]
    return default_portfolio, default_dividends


def save_data(portfolio, dividends):
    p_serializable = []
    for item in portfolio:
        item_copy = item.copy()
        item_copy["date"] = item_copy["date"].strftime("%Y-%m-%d")
        p_serializable.append(item_copy)

    d_serializable = []
    for item in dividends:
        item_copy = item.copy()
        item_copy["date"] = item_copy["date"].strftime("%Y-%m-%d")
        d_serializable.append(item_copy)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"portfolio": p_serializable, "dividends": d_serializable},
            f,
            ensure_ascii=False,
            indent=4,
        )


if "portfolio" not in st.session_state or "dividends" not in st.session_state:
    st.session_state.portfolio, st.session_state.dividends = load_data()


# =========================================================
# 側邊欄：新增交易紀錄、領息與上傳對帳單
# =========================================================
st.sidebar.header("📝 交易與資料管理")

tab_buy, tab_div, tab_upload = st.sidebar.tabs(
    ["📈 新增買/賣", "💵 記錄領息", "📁 上傳對帳單"]
)

with tab_buy:
    with st.form("add_stock_form"):
        input_text = st.text_input("股票代碼與名稱", placeholder="例如: 2330 台積電")
        trade_date = st.date_input("交易日期", value=datetime.today())
        shares = st.number_input(
            "股數 (買進填正數，賣出填負數)",
            min_value=-1000000,
            value=1000,
            step=1,
        )
        cost_price = st.number_input(
            "成交均價 (元)", min_value=0.0, value=100.0, step=0.1
        )

        submit_btn = st.form_submit_button("💾 儲存交易紀錄", type="primary")

        if submit_btn:
            parts = re.split(r"[\s,[,;；]+", input_text.strip())
            s_id = normalize_stock_id(parts[0]) if parts else ""
            s_name = parts[1] if len(parts) >= 2 else f"股票{s_id}"

            if s_id and shares != 0:
                st.session_state.portfolio.append(
                    {
                        "id": s_id,
                        "name": s_name,
                        "date": trade_date,
                        "shares": int(shares),
                        "cost_price": float(cost_price),
                    }
                )
                save_data(st.session_state.portfolio, st.session_state.dividends)
                action_str = "買進" if shares > 0 else "賣出"
                st.sidebar.success(
                    f"✅ 成功記錄 {action_str} {s_id} {s_name} {abs(shares)} 股！"
                )
                st.rerun()
            else:
                st.sidebar.error("⚠️ 請輸入有效的股票代碼與不為零的股數！")

with tab_div:
    with st.form("add_dividend_form"):
        div_input_text = st.text_input("股票代碼與名稱", placeholder="例如: 2330 台積電")
        div_date = st.date_input("領息日期", value=datetime.today())
        total_dividend = st.number_input(
            "領到現金股利總額 (元)", min_value=0.0, value=1000.0, step=100.0
        )

        div_submit_btn = st.form_submit_button("💵 記錄配息入帳", type="primary")

        if div_submit_btn:
            parts = re.split(r"[\s,[,;；]+", div_input_text.strip())
            s_id = normalize_stock_id(parts[0]) if parts else ""
            s_name = parts[1] if len(parts) >= 2 else f"股票{s_id}"

            if s_id:
                st.session_state.dividends.append(
                    {
                        "id": s_id,
                        "name": s_name,
                        "date": div_date,
                        "total_dividend": float(total_dividend),
                    }
                )
                save_data(st.session_state.portfolio, st.session_state.dividends)
                st.sidebar.success(f"✅ 成功記錄 {s_id} 領息 ${total_dividend:,.2f}！")
                st.rerun()
            else:
                st.sidebar.error("⚠️ 請輸入有效的股票代碼！")

with tab_upload:
    st.markdown("### 📁 上傳券商對帳單")
    st.caption("支援標準 CSV 或 Excel 對帳單檔案。")
    uploaded_file = st.file_uploader(
        "選擇檔案", type=["csv", "xlsx", "xls"], key="statement_uploader"
    )

    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith(".csv"):
                # 嘗試常見編碼
                try:
                    df_upload = pd.read_csv(uploaded_file, encoding="utf-8")
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    df_upload = pd.read_csv(uploaded_file, encoding="cp950")
            else:
                df_upload = pd.read_excel(uploaded_file)

            st.write("檔案預覽：", df_upload.head(3))

            # 讓使用者對應欄位
            cols = list(df_upload.columns)
            col_stock = st.selectbox(
                "股票名稱/代碼欄位",
                cols,
                index=cols.index("股名") if "股名" in cols else 0,
            )
            col_date = st.selectbox(
                "交易日期欄位",
                cols,
                index=cols.index("日期") if "日期" in cols else 0,
            )
            col_shares = st.selectbox(
                "成交股數欄位",
                cols,
                index=cols.index("成交股數") if "成交股數" in cols else 0,
            )
            col_price = st.selectbox(
                "成交單價欄位",
                cols,
                index=cols.index("成交單價") if "成交單價" in cols else 0,
            )
            col_net = (
                st.selectbox(
                    "淨收付/買賣方向判斷欄位 (選填)",
                    ["無"] + cols,
                    index=(
                        cols.index("淨收付") + 1
                        if "淨收付" in cols
                        else 0
                    ),
                )
                if "淨收付" in cols or len(cols) > 0
                else "無"
            )

            default_stock_id_input = st.text_input(
                "若對帳單只有名稱無代碼，請輸入預設代碼或對應表",
                placeholder="例如: 寶雅代碼為 5904",
                value="5904",
            )

            if st.button("🚀 確認匯入對帳單到購買紀錄", type="primary"):
                imported_count = 0
                for _, row in df_upload.iterrows():
                    # 解析股名與代碼
                    raw_stock = str(row[col_stock]).strip().replace("*", "")
                    # 嘗試從字串中萃取數字當作股票代碼，若無則使用預設
                    id_match = re.search(r"(\d+)", raw_stock)
                    s_id = id_match.group(1) if id_match else default_stock_id_input
                    s_name = re.sub(r"\d+", "", raw_stock).strip() or raw_stock

                    # 解析日期
                    date_str = str(row[col_date]).strip()
                    try:
                        # 支援 2026/08/13 或 2026-08-13
                        trade_date = pd.to_datetime(date_str).date()
                    except Exception:
                        trade_date = datetime.today().date()

                    # 解析股數
                    shares_raw = str(row[col_shares]).replace(",", "").strip()
                    try:
                        shares_val = float(shares_raw)
                    except Exception:
                        shares_val = 0.0

                    # 解析單價
                    price_raw = str(row[col_price]).replace(",", "").strip()
                    try:
                        price_val = float(price_raw)
                    except Exception:
                        price_val = 0.0

                    # 判斷買進或賣出 (若淨收付存在且大於0表賣出/收錢，小於0表買進/付錢；或是預設正數為買進)
                    if col_net != "无" and col_net in df_upload.columns:
                        net_val_str = (
                            str(row[col_net]).replace(",", "").strip()
                        )
                        try:
                            net_val = float(net_val_str)
                            # 如果淨收付大於0（賣出），股數轉為負數
                            if net_val > 0:
                                shares_val = -abs(shares_val)
                            else:
                                shares_val = abs(shares_val)
                        except Exception:
                            shares_val = abs(shares_val)
                    else:
                        shares_val = abs(shares_val)

                    if s_id and shares_val != 0:
                        st.session_state.portfolio.append(
                            {
                                "id": normalize_stock_id(s_id),
                                "name": s_name,
                                "date": trade_date,
                                "shares": int(shares_val),
                                "cost_price": float(price_val),
                            }
                        )
                        imported_count += 1

                save_data(st.session_state.portfolio, st.session_state.dividends)
                st.sidebar.success(
                    f"✅ 成功匯入 {imported_count} 筆交易紀錄！"
                )
                st.rerun()

        except Exception as e:
            st.sidebar.error(f"⚠️ 讀取檔案發生錯誤: {e}")


# =========================================================
# 主畫面：彙整持股損益與配息
# =========================================================
if not st.session_state.portfolio:
    st.info("目前尚無持股紀錄，請從左側邊欄新增或上傳對帳單！")
else:
    summary_dict = {}
    for item in st.session_state.portfolio:
        s_id = item["id"]
        s_name = item["name"]
        shares = item["shares"]
        cost_price = item["cost_price"]

        if s_id not in summary_dict:
            summary_dict[s_id] = {
                "id": s_id,
                "name": s_name,
                "total_shares": 0,
                "total_cost_amount": 0.0,
            }

        summary_dict[s_id]["total_shares"] += shares

        if shares > 0:
            summary_dict[s_id]["total_cost_amount"] += shares * cost_price
        else:
            curr_total_shares = summary_dict[s_id]["total_shares"] - shares
            if curr_total_shares > 0:
                current_avg = (
                    summary_dict[s_id]["total_cost_amount"] / curr_total_shares
                )
                summary_dict[s_id]["total_cost_amount"] += shares * current_avg
            else:
                summary_dict[s_id]["total_cost_amount"] = 0.0

    dividend_summary = {}
    for d in st.session_state.dividends:
        s_id = d["id"]
        if s_id not in dividend_summary:
            dividend_summary[s_id] = 0.0
        dividend_summary[s_id] += d["total_dividend"]

    table_data = []
    total_cost_all = 0.0
    total_market_value_all = 0.0
    total_dividend_all = 0.0

    for s_id, data in summary_dict.items():
        total_shares = data["total_shares"]
        if total_shares <= 0:
            continue

        total_cost_amount = max(0.0, data["total_cost_amount"])
        stock_div = dividend_summary.get(s_id, 0.0)

        total_dividend_all += stock_div
        avg_cost_price = (
            total_cost_amount / total_shares if total_shares > 0 else 0.0
        )

        current_price = get_latest_price(s_id)
        if current_price == 0:
            current_price = avg_cost_price

        market_value = total_shares * current_price
        pnl = market_value - total_cost_amount
        total_pnl_with_div = pnl + stock_div
        total_return_pct = (
            (total_pnl_with_div / total_cost_amount * 100)
            if total_cost_amount > 0
            else 0.0
        )

        total_cost_all += total_cost_amount
        total_market_value_all += market_value

        table_data.append(
            {
                "代碼": s_id,
                "名稱": data["name"],
                "累積股數": total_shares,
                "平均買進均價": f"{avg_cost_price:.2f}",
                "即時現價": f"{current_price:.2f}",
                "總成本": f"{total_cost_amount:,.2f}",
                "目前市值": f"{market_value:,.2f}",
                "未實現損益": f"{pnl:+,.2f}",
                "累計領息": f"${stock_div:,.2f}",
                "含息總損益": f"{total_pnl_with_div:+,.2f}",
                "含息總報酬率": f"{total_return_pct:+.2f}%",
            }
        )

    total_pnl_all = total_market_value_all - total_cost_all
    total_pnl_with_div_all = total_pnl_all + total_dividend_all
    total_return_pct_all = (
        (total_pnl_with_div_all / total_cost_all * 100)
        if total_cost_all > 0
        else 0.0
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("總投入成本", f"${total_cost_all:,.2f}")
    col2.metric("目前總市值", f"${total_market_value_all:,.2f}")
    col3.metric("累計領息總額", f"${total_dividend_all:,.2f}")
    col4.metric(
        "含息總損益",
        f"${total_pnl_with_div_all:+,.2f}",
        delta=f"{total_return_pct_all:+.2f}%",
    )

    st.markdown("---")
    st.subheader("📋 現有持股彙整總覽")

    if table_data:
        df_show = pd.DataFrame(table_data)
        display_columns = [
            "代碼",
            "名稱",
            "累積股數",
            "平均買進均價",
            "即時現價",
            "總成本",
            "目前市值",
            "未實現損益",
            "累計領息",
            "含息總損益",
            "含息總報酬率",
        ]
        st.dataframe(
            df_show[display_columns],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("目前沒有持股。")

    # =========================================================
    # 區塊：點選股票查看交易歷史明細、刪除紀錄
    # =========================================================
    st.markdown("---")
    st.subheader("🔍 檢視與管理歷史交易明細紀錄")

    all_traded_stocks = list(
        set([item["id"] for item in st.session_state.portfolio])
    )

    if all_traded_stocks:
        selected_stock_id = st.selectbox(
            "選擇要查看明細的股票",
            options=all_traded_stocks,
        )

        if selected_stock_id:
            tab_dtl_trade, tab_dtl_div = st.tabs(
                ["📈 買進/賣出交易明細", "💵 配息入帳明細"]
            )

            with tab_dtl_trade:
                st.markdown(f"#### 📌 【{selected_stock_id}】所有交易紀錄")

                stock_transactions = [
                    (idx, item)
                    for idx, item in enumerate(st.session_state.portfolio)
                    if item["id"] == selected_stock_id
                ]

                trans_table = []
                for orig_idx, item in stock_transactions:
                    action = "買進" if item["shares"] > 0 else "賣出"
                    trans_table.append(
                        {
                            "索引": orig_idx,
                            "交易日期": item["date"].strftime("%Y-%m-%d"),
                            "動作": action,
                            "股數": item["shares"],
                            "成交價格": f"{item['cost_price']:.2f}",
                            "金額小計": f"{abs(item['shares']) * item['cost_price']:,.2f}",
                        }
                    )

                if trans_table:
                    df_trans = pd.DataFrame(trans_table)
                    st.dataframe(
                        df_trans[["交易日期", "動作", "股數", "成交價格", "金額小計"]],
                        use_container_width=True,
                        hide_index=True,
                    )

                    col_del1, col_del2 = st.columns([2, 1])
                    with col_del1:
                        delete_target_idx = st.selectbox(
                            "選擇要刪除的交易明細",
                            options=[t["索引"] for t in trans_table],
                            format_func=lambda idx: f"日期: {st.session_state.portfolio[idx]['date']} | {'買進' if st.session_state.portfolio[idx]['shares']>0 else '賣出'} {abs(st.session_state.portfolio[idx]['shares'])}股 @ {st.session_state.portfolio[idx]['cost_price']}",
                            key="del_trade_select",
                        )
                    with col_del2:
                        st.write("")
                        st.write("")
                        if st.button("🗑️ 刪除此筆交易", type="secondary"):
                            st.session_state.portfolio.pop(delete_target_idx)
                            save_data(
                                st.session_state.portfolio,
                                st.session_state.dividends,
                            )
                            st.success("✅ 刪除成功！")
                            st.rerun()
                else:
                    st.info("尚無交易明細。")

            with tab_dtl_div:
                st.markdown(f"#### 💵 【{selected_stock_id}】配息紀錄")
                stock_divs = [
                    (idx, d)
                    for idx, d in enumerate(st.session_state.dividends)
                    if d["id"] == selected_stock_id
                ]

                div_table = []
                for orig_idx, d in stock_divs:
                    div_table.append(
                        {
                            "索引": orig_idx,
                            "領息日期": d["date"].strftime("%Y-%m-%d"),
                            "領到股利": f"${d['total_dividend']:,.2f}",
                        }
                    )

                if div_table:
                    df_div = pd.DataFrame(div_table)
                    st.dataframe(
                        df_div[["領息日期", "領到股利"]],
                        use_container_width=True,
                        hide_index=True,
                    )

                    col_ddel1, col_ddel2 = st.columns([2, 1])
                    with col_ddel1:
                        delete_div_idx = st.selectbox(
                            "選擇要刪除的配息明細",
                            options=[t["索引"] for t in div_table],
                            format_func=lambda idx: f"日期: {st.session_state.dividends[idx]['date']} | 金額: ${st.session_state.dividends[idx]['total_dividend']:,.2f}",
                            key="del_div_select",
                        )
                    with col_ddel2:
                        st.write("")
                        st.write("")
                        if st.button("🗑️ 刪除此筆配息", type="secondary"):
                            st.session_state.dividends.pop(delete_div_idx)
                            save_data(
                                st.session_state.portfolio,
                                st.session_state.dividends,
                            )
                            st.success("✅ 刪除成功！", icon="🗑️")
                            st.rerun()
                else:
                    st.info("尚無配息紀錄。")