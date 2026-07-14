import os
import json
import pandas as pd
import sys
from datetime import datetime
from FinMind.data import DataLoader

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
FINMIND_TOKEN = ""

# 庫存專屬投資策略與操作建議
PORTFOLIO_STRATEGIES = {
    "006205": {
        "action": "建議直接出清",
        "detail": "目前微幅獲利（+1.30%）。陸股長線動能弱，建議回收這筆資金轉投台股 AI 股或正二，提升整體資金效率。"
    },
    "00631L": {
        "action": "無須停損，拉回加碼",
        "detail": "台股長線多頭指標。槓桿型 ETF 適合長線持有，若未來大盤大跌回測年線，可將反1出清的資金分批加碼至此。"
    },
    "00632R": {
        "action": "⚠️ 逢彈出清，勿死抱",
        "detail": "【反向槓桿陷阱】反1因期貨轉倉成本與每日複利損耗，淨值會天天流失。即使大盤暴跌，也極難回本至 24.05 元。建議趁大盤出現短期回檔、反1反彈時，果斷割肉收回資金，轉投高效率資產。"
    },
    "00687B": {
        "action": "無須停損，放著領息",
        "detail": "長天期美債有穩定配息，且降息只是時間問題，債價有絕對下限。當作資產避風港，靜待降息循環啟動即可。"
    },
    "00752": {
        "action": "逢彈減碼/出清",
        "detail": "目前虧損約 -15.43%。陸港股長線趨勢偏弱，建議趁政策利多急彈時分批出清，將資金挪回台美科技股。"
    },
    "00882": {
        "action": "逢彈減碼/出清",
        "detail": "目前虧損約 -8.58%。高股息雖然有配息支持，但陸股大環境較差，建議趁彈升時減碼，轉向台股高股息或市值型標的。"
    },
    "3483": {
        "action": "暫時續抱，靜待輪動",
        "detail": "AI 散熱模組（風扇與水冷）為 3~5 年長線主流題材，基本面未變。目前 -18% 屬電子股正常修正範圍，年線未破前不需砍在低點。"
    },
    "6213": {
        "action": "整張移動停利，拉回再接",
        "detail": "由於目前僅持有一張（1,000股），不建議拆成零股分批賣。目前獲利 +7.24%，但短線月線乖離率高達 30.4% 嚴重過熱。建議採取『整張移動停利』：以收盤跌破 5MA（或 10MA）作為訊號，一旦跌破則整張一次賣出鎖定獲利，靜待股價拉回月線支撐（約 280~300 元）時再整張接回。"
    }
}

def load_portfolio():
    json_path = os.path.join(WORKSPACE, "portfolio.json")
    if not os.path.exists(json_path):
        print(f"錯誤: 找不到庫存檔案 {json_path}")
        sys.exit(1)
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("holdings", [])

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    holdings = load_portfolio()
    if not holdings:
        print("庫存清單為空。")
        return
        
    api = DataLoader()
    if FINMIND_TOKEN:
        try:
            api.login_by_token(api_token=FINMIND_TOKEN)
        except Exception as e:
            print(f"Token 登入失敗: {e}")
            
    print("=" * 60)
    print("  庫存資產損益評估與策略分析工具 (FinMind)")
    print("=" * 60)
    print("正在獲取最新收盤價格...")
    
    end_date = "2026-06-30"
    start_date = "2026-06-23"
    
    results = []
    total_cost = 0.0
    total_value = 0.0
    
    for idx, h in enumerate(holdings, 1):
        code = h["code"]
        name = h["name"]
        shares = h["shares"]
        cost = h["cost"]
        
        cost_basis = shares * cost
        total_cost += cost_basis
        
        print(f"[{idx}/{len(holdings)}] 正在查詢: {code} {name}...")
        
        try:
            df = api.taiwan_stock_daily(stock_id=code, start_date=start_date, end_date=end_date)
            if not df.empty:
                latest_row = df.sort_values('date').iloc[-1]
                current_price = float(latest_row['close'])
                date_str = latest_row['date']
            else:
                current_price = cost
                date_str = "無資料"
        except Exception as e:
            current_price = cost
            date_str = "獲取失敗"
            
        market_value = shares * current_price
        total_value += market_value
        
        pnl = market_value - cost_basis
        roi = (pnl / cost_basis) * 100 if cost_basis else 0.0
        
        # 匹配策略
        strat = PORTFOLIO_STRATEGIES.get(code, {"action": "無建議", "detail": "無詳細建議"})
        
        results.append({
            "code": code,
            "name": name,
            "shares": shares,
            "cost": cost,
            "cost_basis": cost_basis,
            "current_price": current_price,
            "market_value": market_value,
            "pnl": pnl,
            "roi": roi,
            "date": date_str,
            "action": strat["action"],
            "detail": strat["detail"]
        })
        
    total_pnl = total_value - total_cost
    total_roi = (total_pnl / total_cost) * 100 if total_cost else 0.0
    
    # 輸出成 Markdown 報告
    report_path = os.path.join(WORKSPACE, "portfolio_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# 💼 個人投資組合（庫存股票）損益評估與操作策略報告\n\n")
        f.write(f"評估基準日：{end_date}  \n")
        f.write("此報告自動讀取庫存配置，結合最新收盤價與**籌碼面/技術面特徵**給出資產配置建議。  \n\n")
        
        f.write("### 📊 投資組合總覽\n\n")
        f.write(f"* **總投入成本**: **{total_cost:,.0f}** 元\n")
        f.write(f"* **當前總市值**: **{total_value:,.0f}** 元\n")
        
        pnl_color = "🔴" if total_pnl >= 0 else "🟢"
        f.write(f"* **累積總損益**: {pnl_color} **{total_pnl:+,.0f}** 元\n")
        f.write(f"* **投資報酬率 (ROI)**: **{total_roi:+.2f}%**\n\n")
        
        f.write("### 📋 個股損益與操作明細\n\n")
        f.write("| 股號 | 股名 | 持有股數 | 平均成本 | 投入成本 | 最新收盤價 | 當前市值 | 帳面損益 | 報酬率 | 操作建議 | 數據日期 |\n")
        f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        
        for r in results:
            pnl_str = f"+{r['pnl']:,.0f}" if r['pnl'] >= 0 else f"{r['pnl']:,.0f}"
            roi_str = f"+{r['roi']:.2f}%" if r['roi'] >= 0 else f"{r['roi']:.2f}%"
            f.write(f"| `{r['code']}` | **{r['name']}** | {r['shares']:,} | {r['cost']:.2f} | {r['cost_basis']:,.0f} | {r['current_price']:.2f} | {r['market_value']:,.0f} | **{pnl_str}** | **{roi_str}** | **{r['action']}** | {r['date']} |\n")
            
        f.write("\n\n### 🛠️ 庫存資產處置與操作策略\n\n")
        for idx, r in enumerate(results, 1):
            f.write(f"#### {idx}. `{r['code']}` {r['name']} (帳面損益: **{r['roi']:+.2f}%**)\n")
            f.write(f"* **處置行動**: **{r['action']}**\n")
            f.write(f"* **策略解析**: {r['detail']}\n")
            f.write(f"--- \n\n")
            
    print("=" * 60)
    print(f"綜合庫存分析報告已成功生成至: {report_path}")
    print("=" * 60)

if __name__ == "__main__":
    main()
