import os
import json
import shutil
import sys

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
REPORT_PATH = os.path.join(WORKSPACE, "reports", "latest", "social_picks_screener.md")

def generate_social_report(results, today_str):
    social_picks_path = os.path.join(WORKSPACE, "config", "social_picks.json")
    if not os.path.exists(social_picks_path):
        print("找不到社群標的設定檔 config/social_picks.json，略過生成。")
        return
        
    with open(social_picks_path, 'r', encoding='utf-8') as f:
        social_data = json.load(f)
        
    tracked = social_data.get("tracked_stocks", [])
    if not tracked:
        print("社群標的列表為空，略過報告生成。")
        return
        
    # 建立 code -> result 的快速查找字典
    results_map = {r["code"]: r for r in results}
    
    analyzed_picks = []
    for s in tracked:
        code = s["code"]
        r = results_map.get(code)
        if r:
            analyzed_picks.append({
                **r,
                "social_reason": s.get("reason", "無"),
                "dates": s.get("dates", [])
            })
        else:
            # 容錯處理：如果某個代碼在快取中漏掉，顯示為未知
            analyzed_picks.append({
                "code": code,
                "name": s.get("name", "未知"),
                "market": s.get("market", "TSE"),
                "industry": "未知",
                "business": "無資料",
                "close": 0.0,
                "bias_20": 0.0,
                "bias_5": 0.0,
                "foreign_ratio": 0.0,
                "inst_ratio": 0.0,
                "inst_buy_5d": 0.0,
                "consecutive_buy": 0,
                "ma_alignment": "未知",
                "kd_status": "未知",
                "vol_surge": 1.0,
                "margin_diff_5d": 0.0,
                "margin_usage": 0.0,
                "margin_tag": "未知",
                "rank_score": -99.0,
                "p_score": 0.0,
                "r_score": 100.0,
                "p_reasons": [],
                "r_reasons": ["無歷史交易快取資料"],
                "social_reason": s.get("reason", "無"),
                "dates": s.get("dates", [])
            })
            
    # 依據綜合得分 (rank_score) 降序排列
    analyzed_picks.sort(key=lambda x: x["rank_score"], reverse=True)
    
    # 生成 Markdown 報告內容
    lines = []
    lines.append("# 💬 社群收集標的量化評估報告 (Social Picks Screener)")
    lines.append(f"\n分析基準日：{today_str[:4]}-{today_str[4:6]}-{today_str[6:]}  ")
    lines.append("本報告針對您從社群收集並維運的標的進行量化評分與排名。  ")
    lines.append("*(評分已排除非前20%強勢產業類股等限制，強制保留進行穿透分析與排名對照)*  \n")
    
    lines.append("> [!NOTE]")
    lines.append("> **💡 評等準則**：採用與「低危高利選股器」相同的 **綜合性價比得分 = 獲利可能性(籌碼+技術) - 風險得分** 進行排序，幫助您從社群熱門股中篩選出安全且具備籌碼優勢的進場機會。  \n")
    
    lines.append("## 🏆 社群標的量化評估排名 (共 {} 檔)\n".format(len(analyzed_picks)))
    lines.append("| 排名 | 股號 | 股名 | 最新收盤 | 綜合得分 | 20MA乖離 | 5日融資變動 | 吃貨比例 | 籌碼屬性 | 社群收集原因 / 核心評估因子 |")
    lines.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
    
    for idx, r in enumerate(analyzed_picks, 1):
        if r["rank_score"] == -99.0:
            lines.append(f"| {idx} | `{r['code']}` | **{r['name']}** | N/A | **N/A** | N/A | N/A | N/A | N/A | **社群原因**: {r['social_reason']}<br>🚨 **量化評估**: 無法取得市場報價資料 |")
            continue
            
        char_tag = "🚨 外資主導" if r["foreign_ratio"] >= 40 else "✅ 內資主導" if r["foreign_ratio"] <= 15 else "中等"
        margin_str = f"{r['margin_diff_5d']:+.0f}張" if "ETF" not in r["margin_tag"] else r["margin_tag"]
        
        dates_tag = f" (收集日期: {', '.join(r['dates'])})" if r['dates'] else ""
        
        lines.append(f"| {idx} | `{r['code']}` | **{r['name']}** | {r['close']:.2f} | **{r['rank_score']:.1f}** | {r['bias_20']:+.1f}% | {margin_str} | {r['inst_ratio']:.1f}% | {char_tag} | **社群原因**: {r['social_reason']}{dates_tag}<br>獲利因: {', '.join(r['p_reasons'][:2]) if r['p_reasons'] else '無'} / 風險因: {', '.join(r['r_reasons'][:2]) if r['r_reasons'] else '安全'} |")
        
    lines.append("\n\n## 💡 前 5 名社群潛力股深度解析與建議交易對策\n")
    
    valid_picks = [x for x in analyzed_picks if x["rank_score"] != -99.0]
    for idx, r in enumerate(valid_picks[:5], 1):
        lines.append(f"### {idx}. `{r['code']}` {r['name']} (綜合得分: **{r['rank_score']:.1f}**)")
        lines.append(f"* **社群收集原因**: {r['social_reason']}")
        lines.append(f"* **主要業務**: {r['business']}")
        lines.append(f"* **20MA 乖離率**: **{r['bias_20']:+.2f}%** | **5MA 週線乖離率**: **{r['bias_5']:+.2f}%**")
        lines.append(f"* **外資持股比**: {r['foreign_ratio']:.2f}% ({'🚨 外資主導' if r['foreign_ratio']>=40 else '✅ 內資主導' if r['foreign_ratio']<=15 else '中等'})")
        lines.append(f"* **5日法人吃貨比**: **{r['inst_ratio']:.1f}%** (5日大買 **{r['inst_buy_5d']:.0f}** 張)")
        lines.append(f"* **5日融資變動**: **{r['margin_diff_5d']:+.0f}** 張 (屬性: **{r['margin_tag']}**)")
        lines.append(f"* **利多支撐**: {', '.join(r['p_reasons']) if r['p_reasons'] else '暫無'}")
        lines.append(f"* **風險警告**: {', '.join(r['r_reasons']) if r['r_reasons'] else '安全無虞'}")
        
        # 策略對策
        strategy_parts = []
        if r['bias_5'] > 5.0:
            strategy_parts.append(f"⚠️ 股價偏離週線已達 {r['bias_5']:.1f}%，短線防守空間大，切勿追高。")
        else:
            strategy_parts.append("🟢 目前偏離週線尚在合理區間，具備低乖離安全優勢。")
        if r['bias_20'] > 12.0:
            strategy_parts.append(f"且月線乖離率偏大（{r['bias_20']:.1f}%），建議拉回踩 5MA 或 10MA 再行佈局。")
        else:
            strategy_parts.append("若盤中拉回踩 5MA 附近可分批建立基本持股。")
        lines.append(f"* **💡 AI 建議進場點與防守對策**: {''.join(strategy_parts)}\n")
        lines.append("--- \n")
        
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
        
    # 複製歷史備份
    history_file = os.path.join(WORKSPACE, "reports", "history", f"social_picks_screener_{today_str}.md")
    shutil.copy(REPORT_PATH, history_file)
    print(f"社群收集標的量化報告已成功生成於: reports/latest/social_picks_screener.md")

if __name__ == "__main__":
    # 測試獨立執行
    pass
