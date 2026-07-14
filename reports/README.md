# 📊 專案報告目錄說明與導覽手冊 (Reports Guide)

本目錄存放所有量化分析與黑天鵝預警的產出報告。為了避免混亂，舊版報告格式已全部移除，目前僅保留以下**五大核心新版報告**：

---

## 📂 最新報告 (Latest Reports)
所有最新產出的即時報告皆存放於：`reports/latest/`

### 1. 🏆 [個人持股與觀測整合報告](file:///g:/%E6%88%91%E7%9A%84%E9%9B%B2%E7%AB%AF%E7%A1%AC%E7%A2%9F/dev/twstockals/reports/latest/portfolio_and_watchlist.md)
*   **檔案名稱**：`portfolio_and_watchlist.md`
*   **報告內容**：
    *   **大盤多空濾網**：依據加權指數與 20MA 月線的相對位置，給予整體持倉水位建議。
    *   **持股診斷表**：顯示持有股數、均價成本、現價、累積損益（ROI）以及個股的均線、KD狀態與量化得分。
    *   **觀測個股操作點位**：自動精算觀察股的**初次進場點（5MA）、主力加碼點（20MA）、停損防守點與動態停利對策**。
    *   **個別處置建議**：針對每檔持股與觀察股，給出具體且動態的一句話交易策略與深度解析。

### 2. 🔍 [全市場選股排行榜 - 低危高利防守型](file:///g:/%E6%88%91%E7%9A%84%E9%9B%B2%E7%AB%AF%E7%A1%AC%E7%A2%9F/dev/twstockals/reports/latest/market_screener_low_risk.md)
*   **檔案名稱**：`market_screener_low_risk.md`
*   **報告內容**：
    *   篩選出符合前 20% 強勢產業、股價站上季線、日均量大於 300 張且非權證的前 30 名標的。
    *   依據「獲利機會（籌碼連買/大額吃貨）減去風險分數（乖離過高/KD死叉）」之綜合得分降序排列。
    *   提供前 5 名優質潛力股的深度主要業務解說與防守進場點對策。

### 3. 🚀 [全市場選股排行榜 - 強勢動能型](file:///g:/%E6%88%91%E7%9A%84%E9%9B%B2%E7%AB%AF%E7%A1%AC%E7%A2%9F/dev/twstockals/reports/latest/market_screener_momentum.md)
*   **檔案名稱**：`market_screener_momentum.md`
*   **報告內容**：
    *   限定在前 20% 強勢產業，且股價呈現完美多頭排列（Price > 5MA > 10MA > 20MA > 60MA）的爆發股。
    *   依據法人連買、爆量倍數與 KD 動能加權打分，選出前 30 名強勢個股。
    *   提供前 5 名主升段標的的移動停利點設置建議。

### 4. 🚨 [黑天鵝防禦網即時警報](file:///g:/%E6%88%91%E7%9A%84%E9%9B%B2%E7%AB%AF%E7%A1%AC%E7%A2%9F/dev/twstockals/reports/latest/black_swan_defense.md)
*   **檔案名稱**：`black_swan_defense.md`
*   **報告內容**：
    *   **總經與夜盤先行指標**：即時追蹤新台幣匯率變動、台積電 ADR (`TSM`)、MSCI台灣 (`EWT`)、以及那斯達克期指 (`NQ=F`) 漲跌。
    *   **即時個股波幅**：追蹤您的持股與自選股在盤中/夜間的即時漲跌幅與警戒燈號。
    *   **產業與恐慌新聞**：即時掃描與您持股、觀察股或關聯產業相關的重大黑天鵝恐慌新聞。

### 5. 💬 [社群收集標的評估報告](file:///g:/%E6%88%91%E7%9A%84%E9%9B%B2%E7%AB%AF%E7%A1%AC%E7%A2%9F/dev/twstockals/reports/latest/social_picks_screener.md)
*   **檔案名稱**：`social_picks_screener.md`
*   **報告內容**：
    *   針對您從社群收集並維運的標的（載於 `config/social_picks.json`）進行量化評分與排名。
    *   將您的社群收集備忘原因與 AI 的籌碼/技術打分做跨維度結合。
    *   提供前 5 名潛力社群股的深度主要業務解說、法人吸籌比例、與建議交易進場點及防守對策。

---

## 📂 歷史備份 (Historical Archives)
所有歷史分析與防禦軌跡皆存放於：`reports/history/`

*   每次執行選股器或黑天鵝監控時，系統會自動在最新報告生成後複製一份備份至此，並以日期/時間命名（例如 `portfolio_and_watchlist_20260702.md` 或 `black_swan_defense_20260703_160800.md`）。
*   本資料夾會按日期無限期保留，方便您做歷史回測與對策驗證。
