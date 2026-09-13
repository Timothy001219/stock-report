from datetime import datetime, timedelta
import json
import os
import re
import pandas as pd
import requests

# 這裡直接引用主程式的核心分析邏輯（或獨立出來）
# 為了讓每日排程獨立運作，我們將必要的核心邏輯寫在這裡
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
ENV_TOKEN = os.getenv("FINMIND_TOKEN", "").strip()

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

def normalize_stock_id(stock_id: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(stock_id).strip()).upper()

def finmind_get(dataset: str, stock_id: str, token: str = "", days: int = 365):
    stock_id = normalize_stock_id(stock_id)
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = requests.get(FINMIND_URL, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return pd.DataFrame(payload.get("data", []))

# (此處省略部分重複的計算函式，與 app.py 相同，為節省篇幅主要展示輸出邏輯)
def run_daily_cache_generation():
    print("🚀 開始執行每日自動排程分析...")
    # 讀取內建清單進行分析，並將結果輸出成 JSON 檔案
    lines = DEFAULT_STOCKS_TEXT.strip().splitlines()
    results = []
    
    for line in lines:
        parts = re.split(r"[\s,，;；]+", line.strip())
        if not parts: continue
        s_id = normalize_stock_id(parts[0])
        s_name = parts[1] if len(parts) >= 2 else f"股票{s_id}"
        
        try:
            # 簡化示範：呼叫分析並包裝進 results
            # 實際執行時會帶入與 app.py 相同的 analyze_stock 邏輯
            pass
        except Exception as e:
            print(f"❌ {s_id} 失敗: {e}")

    # 輸出成快取檔案供網頁讀取
    cache_data = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "results": results
    }
    with open("daily_cache.json", "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=4)
    print("✅ 每日快取更新完成！")

if __name__ == "__main__":
    run_daily_cache_generation()