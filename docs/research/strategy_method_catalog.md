# 策略方法蒐集與適配性目錄（海搜＋社群優先）

產生：2026-07-18  
範圍：本專案商品 GOLD／USDTWD／0050／00631L／VOO／VXUS／QQQ／BTC／ETH  
性質：**研究目錄**。外部勝率／PF **≠** 已勝過本專案 CP；社群宣稱多標 **C／D**。  
本階段**不**改推播、不實作新偵測器。

---

## 0. 證據等級與欄位

| 等級 | 含義 |
|------|------|
| **A** | 學術／可複現論文或監管機構研究 |
| **B** | 獨立量化站長／方法透明的系統回測 |
| **C** | 社群／行銷／工具商回測（存活者偏差、repaint、樣本選擇風險高） |
| **D** | 僅敘事或口耳相傳，無可用數據 |

方法卡欄位：`source_type`｜`community_heat`（高／中／低＝討論熱度，非品質）｜`prog`（可程式化：高／中／低）｜適配（●適合／△半適配／○低適配）

商品縮寫：G=GOLD｜U=USDTWD｜50=0050｜L=00631L｜V=VOO｜X=VXUS｜Q=QQQ｜B=BTC｜E=ETH

---

## 1. 現行基準（本 repo）

| 商品 | 現行核心 | 對照檔 |
|------|----------|--------|
| 黃金 | 台銀換算價進 50MA 區＋峰回撤／年線深度＋短線止穩；**買滿長抱不出場**（50MA 出場 2026-07-18 停用，見 gold_sleeve_backtest） | `scan_multi_asset.grade_gold_buy` |
| 美金 | USD/TWD vs 200MA 乖離階梯（≥A 才囤）；出場乖離≥+1.5% 減一袖 | `grade_usd_fx` |
| 0050 | 5/10/20MA 拉回＋止穩＋大盤 Level；出場破 10MA | `scan_watch_grades` |
| 00631L | 大盤年線閘＋Level；拉回 10/20；出場大盤破年線或破 10MA | 同上 |
| VOO／VXUS | 拉回核心；政策門檻 **S**；出場破 50MA | 同上＋`grade_buy_policy` |
| QQQ | 成長帶／年線深回撤；門檻 B；ladder 可加碼 | 同上 |
| BTC／ETH | 顯示 50/200；**偏重暫停加碼**；破 50MA 可減參考 | `scan_multi_asset` |

既有內部對照：`reports/latest/grade_threshold_backtest.md`（2026-07-15：GOLD≈C+/B、USDTWD/BTC A+、0050/正2/QQQ B+、VOO/VXUS S）。

**結論：** 現行不是「純 MA 交叉」，而是 **均線乖離帶＋止穩（＋台股 Level／黃金峰回撤）**；出場仍偏簡單均線規則。

---

## 2. 海搜管道索引（草稿）

| 管道 | 常出現的方法名 | 代表來源 |
|------|----------------|----------|
| 學術 | 相對／絕對動量、H&S 預測力爭議、技術規則 FX | Jegadeesh & Titman 1993；Savin et al. H&S；Chang & Osler NY Fed |
| 量化站 | 黃金 12 月 MA、Dual Momentum、均值回歸＋趨勢濾網 | quantifiedstrategies.com；Antonacci Dual Momentum |
| Prop／系統站 | 杯柄自動化（商品差異大）、Hurst regime | pinescriptforge.com |
| TradingView／日內社群 | ORB、VWAP、RVOL、Gap-and-Go、ABCD | TradeAlgo／GrandAlgo／ChartMath；r/daytrading |
| 美股成長圈 | CANSLIM、SEPA、VCP、Trend Template、杯柄 | Minervini／O'Neil 社群整理站 |
| 加密社群 | SMC/ICT、Wyckoff、CVD、funding、OI、basis | ICT／SMC 教學；MarketTrace；Finestel（repaint 警告） |
| 台股籌碼社群 | 法人連買、融資減＝籌碼沉澱、月線、土洋合買、阿呆谷 | 聚財／券商部落格／籌碼教學文 |
| Reddit 指標討論 | RSI 背離、布林擠壓、MACD、S/R＋量 | theledgermind 對 Reddit 討論整理（**C**） |

---

## 3. 方法卡（家族 A–I）

### A. 型態／圖形

#### A1. Cup & Handle（杯柄）
- **別名：** 杯柄、O'Neil cup-with-handle  
- **規則摘要：** 圓弧回檔成杯 → 柄部緊縮 → 突破柄高＋量增；停損常在柄低。  
- **適配：** G△ U○ 50○ L○ V△ X○ Q△ B△ E△（個股／成長股敘事強；寬基 ETF／外匯樣本稀）  
- **heat：** 高｜**prog：** 中｜**證據：** B/C — 系統回測隨商品 PF 1.06～2.98、MDD 差異極大；**不可**直接當優於現行。  
- **來源：** https://pinescriptforge.com/rty/cup-and-handle/backtest ；https://tradethatswing.com/the-cup-and-handle-swing-trading-strategy-explosive-consistent-price-moves/  
- **備註：** 對本專案 EOD／袖口操作可作「突破確認」濾網；日線杯柄形成慢。

#### A2. Head & Shoulders／Inverse H&S
- **別名：** 頭肩頂／底、HS  
- **規則摘要：** 三峰／三谷＋頸線突破；常配量能。  
- **適配：** 全商品△（當反轉濾網）；單兵進出 ○  
- **heat：** 高｜**prog：** 中｜**證據：** **A 但結論矛盾** — 有預測超額報酬說（Savin et al.），亦有無利可圖／幻覺相關（RoF）。FX 上常被更簡單規則支配。  
- **來源：** https://doi.org/10.1093/jjfinec/nbl012 ；https://doi.org/10.1093/rof/rfr037  
- **備註：** 建議只當**組合濾網**，勿取代現行乖離評等。

#### A3. Double Top／Bottom
- **適配：** 全△｜**heat：** 高｜**prog：** 中｜**證據：** D/C（經典教科書＋社群）  
- **備註：** 與頭肩同屬反轉家族；誤判多，需量與趨勢濾網。

#### A4. Triangles／Flags／Pennants／Wedges
- **適配：** Q△ B△ E△ 其餘○｜**heat：** 中｜**prog：** 中｜**證據：** D/C  
- **備註：** 短線延續型態；槓桿／加密社群常用，EOD 袖口價值有限。

#### A5. VCP（Volatility Contraction Pattern）
- **別名：** 波動緊縮、Minervini VCP（近杯柄／平台緊縮變體）  
- **規則摘要：** Stage2 多頭內，回撤幅度遞減＋量縮 → 樞紐突破放量；硬停損約 5–8%。  
- **適配：** Q△ V○ 50○ L○（個股成長）；ETF／金／匯 ○  
- **heat：** 高｜**prog：** 中｜**證據：** C/B — 競賽贏家敘事強；系統化定義可測但公開嚴格 OOS 少。  
- **來源：** https://www.financialtechwiz.com/post/mark-minervini-trading-strategy/ ；https://profitvisionlab.com/canslim-sepa-methodology-deep-dive-en/  
- **備註：** 與杯柄可別名合併研究；對本專案「個股殘倉出場」較無關，「QQQ 衛星」可觀察。

#### A6. Rounding Bottom／Saucer
- **適配：** G△｜**heat：** 低｜**prog：** 低｜**證據：** D  
- **備註：** 黃金長週期偶見敘事。

#### A7. Breakout from Consolidation／Base
- **適配：** Q△ B△｜**heat：** 高｜**prog：** 中｜**證據：** C  
- **備註：** 社群「盤整突破」總稱；需量能與偽突破過濾。

---

### B. 趨勢／動能

#### B1. Dual / Triple MA Cross（含黃金交叉）
- **規則摘要：** 短均上穿長均做多，反之空手／做空。  
- **適配：** G△ U△ 50△ L△ V△ X△ Q△ B△ E△  
- **heat：** 高｜**prog：** 高｜**證據：** B — 商品趨勢市有效、震盪市鞭鋸；黃金有長均優於裸抱說法。  
- **來源：** https://www.quantifiedstrategies.com/gold-moving-average-strategy/  
- **vs 現行：** 較現行「乖離帶＋止穩」更粗；可作**空倉濾網**候選。

#### B2. Price vs 200–250 DMA / 12-month SMA（長均趨勢）
- **適配：** G● V● X● Q● L△ 50△ U△ B△  
- **heat：** 中｜**prog：** 高｜**證據：** B（黃金 12 月 MA 敘事）  
- **來源：** 同上 QuantifiedStrategies 黃金文  
- **vs 現行：** 現行黃金已改買滿長抱（50MA 出場 2026-07-18 停用）；長均擇時在 gold_sleeve_backtest 各窗均輸長抱。

#### B3. Donchian / Turtle（N 日高低突破）
- **適配：** G△ B● E● Q△｜**heat：** 中｜**prog：** 高｜**證據：** B（經典趨勢跟隨文獻／書籍）  
- **備註：** 操作次數可能高於本專案「少上班」目標。

#### B4. Supertrend / ATR Channel Trend
- **適配：** B△ E△ Q△｜**heat：** 高｜**prog：** 高｜**證據：** C（TradingView 熱門）  
- **備註：** 參數敏感；易 overnight 鞭鋸。

#### B5. Ichimoku Cloud
- **適配：** 全△｜**heat：** 中｜**prog：** 中｜**證據：** C  
- **備註：** 多線共識；與現行重疊多，增益不明。

#### B6. ADX + DI
- **適配：** 全△（當「有沒有趨勢」開關）｜**heat：** 中｜**prog：** 高｜**證據：** C  
- **備註：** 適合接在 regime switch 前。

#### B7. Time-Series Momentum（12–1 月等）
- **別名：** 絕對動量、Moskowitz 類  
- **適配：** V● X● Q● G△ L△｜**heat：** 中（量化圈高）｜**prog：** 高｜**證據：** **A**  
- **來源：** Jegadeesh & Titman 1993 動量文獻脈絡；絕對動量見 Antonacci／學術延伸  
- **vs 現行：** 月頻再平衡，**極合**「少操作」；可與 VOO/VXUS/QQQ 袖口對照。

#### B8. Dual Momentum（相對＋絕對）
- **別名：** GEM、Antonacci Dual Momentum  
- **規則摘要：** 比較美股／國際股相對強弱；若絕對動量弱則轉債／現金。月頻。  
- **適配：** V● X●（核心對）；Q△ G△｜**heat：** 中｜**prog：** 高｜**證據：** **A/B** — 長期回測常強調降 MDD；短窗可能落後純抱 SPY。  
- **來源：** https://www.quantifiedstrategies.com/dual-momentum-trading-strategy/ ；https://medium.com/@garyantonacci_30463/extended-backtest-of-global-equities-momentum-dual-momentum-eb12902612e0 ；PDF 脈絡 https://www.emiratescapitalassetmanagement.com/uploads/2/5/5/4/25541321/risk_premia_harvesting_through_dual_momentum.pdf  
- **vs 現行：** 與「VOO/VXUS 門檻 S 才買」哲學不同（擇時進出整倉）；值得回測比較 CP。

#### B9. Relative Strength (RS) / Ranking
- **適配：** Q● V△ X△ 50△｜**heat：** 高（成長圈）｜**prog：** 中｜**證據：** C/B（CANSLIM／SEPA）  
- **來源：** Minervini Trend Template 整理 https://www.finermarketpoints.com/post/mark-minervini-s-stock-screener-what-indicators-and-criteria-does-he-use  

#### B10. SEPA Trend Template（8 條件均線堆疊）
- **適配：** Q△（個股邏輯搬到 QQQ 需降維）｜**heat：** 高｜**prog：** 高｜**證據：** C  
- **來源：** 同上  
- **備註：** 對單一 ETF 多數條件常「永遠成立或永不」，效用有限。

---

### C. 均值回歸／震盪

#### C1. RSI(2/3) Mean Reversion + Trend Filter
- **適配：** G△ V△ Q△ 50△｜**heat：** 中｜**prog：** 高｜**證據：** B — 黃金短回歸常**打不贏 B&H**，多頭濾網後仍可能不夠。  
- **來源：** https://setup4alpha.substack.com/p/we-tried-mean-reversion-on-gold-and  
- **vs 現行：** 現行黃金「止穩＋深度」較接近改良版 MR；可當對照模型。

#### C2. Bollinger Band Squeeze → Expansion
- **適配：** B△ E△ Q△｜**heat：** 高｜**prog：** 高｜**證據：** C（Reddit／TV 常見）  
- **來源：** Reddit 指標討論整理 https://theledgermind.com/trading-indicators-reddit/  

#### C3. Stochastic / KD 低檔金叉
- **適配：** 50△（AGENTS 亦提 KD）｜**heat：** 中（台股）｜**prog：** 高｜**證據：** D/C  
- **備註：** 本專案洗盤過濾曾補償 KD 死叉；單用 KD 不建議。

#### C4. Z-score / Mean Reversion to MA
- **適配：** U● G△｜**heat：** 低｜**prog：** 高｜**證據：** B/C  
- **vs 現行：** 美金 200MA 乖離本質接近 Z-score；可測不同閾值（1.5% vs 動態 σ）。

#### C5. VWAP Bounce / Reclaim（日內）
- **適配：** ○（與台銀 EOD／少上班不合）｜**heat：** 高｜**prog：** 中｜**證據：** C  
- **來源：** https://www.tradealgo.com/trading-guides/day-trading/day-trading-strategies  
- **備註：** **標註不合本專案主流程**；僅列出海搜完整性。

---

### D. 波動／狀態

#### D1. ATR Trailing Stop / Chandelier
- **適配：** L● Q△ B△｜**heat：** 中｜**prog：** 高｜**證據：** C/B  
- **備註：** 正2 出場可與「破 10MA／大盤年線」對照。

#### D2. Volatility Compression then Breakout
- **適配：** Q△ B△｜**heat：** 中｜**prog：** 中｜**證據：** C（與 VCP／布林擠壓重疊）

#### D3. Hurst Exponent Regime Switch
- **規則摘要：** H 低→均值回歸；H 高→趨勢；中間空手。  
- **適配：** G● V△ B△｜**heat：** 低｜**prog：** 中｜**證據：** A/B  
- **來源：** https://doi.org/10.28924/apjm/12-109 ；https://pinescriptforge.com/gc/hurst-exponent-reversion/backtest  
- **vs 現行：** **多模型狀態機**核心候選；可決定何時用現行拉回、何時用趨勢突破。

#### D4. VIX / Risk-Off Filter（美股）
- **適配：** V● X● Q● L△｜**heat：** 中｜**prog：** 高｜**證據：** C/B  
- **備註：** Level3／風險偏好代理；正2 加碼禁令可對照。

#### D5. Opening Range Breakout (ORB) + RVOL
- **適配：** ○ 主流程；美股 IB 若恢復日內可△｜**heat：** 高｜**prog：** 高｜**證據：** C/B（有 GitHub walk-forward 案例，仍屬特定宇宙）  
- **來源：** https://grandalgo.com/blog/opening-range-breakout-strategy ；https://github.com/sam-bateman/trading-orb  
- **備註：** 明確**日內**；與 `pause_us_ib`／EOD 哲學衝突 → 短名單放「僅觀察」。

---

### E. 結構／流動性（SMC／ICT／Wyckoff）

#### E1. Smart Money Concepts / ICT 家族
- **別名：** OB、FVG、BOS、CHoCH、EQH/EQL、Killzone、OTE、Power of 3  
- **適配：** B△ E△ U△ G△｜**heat：** 高｜**prog：** 低～中（可程式化子集有限）｜**證據：** **強制 C** — 社群高勝率常見、作者常賣工具；**repaint／look-ahead** 風險高。  
- **來源：** https://tradingwyckoff.com/en/smart-money-concepts/ ；https://medium.com/@space.garaa/i-backtested-2-600-trades-using-smart-money-concepts-heres-what-actually-works-bb3c671098c6 ；工程警告 https://finestel.com/blog/smc-bot-crypto/  
- **vs 現行：** BTC/ETH **已偏重不加碼** → 若納入，優先**減碼／風控**語意，非積極加碼。  
- **備註：** 不可當「已勝過現行」證據。

#### E2. Wyckoff Accumulation / Distribution
- **適配：** B△ E△ G△｜**heat：** 中｜**prog：** 低｜**證據：** C/D  
- **備註：** 與 SMC 敘事重疊；裁量重。

#### E3. Liquidity Sweep / Stop Hunt
- **適配：** B△ E△ U△｜**heat：** 高｜**prog：** 低｜**證據：** C  
- **備註：** 常嵌在 SMC；自動化易過擬合。

---

### F. 量能／微結構

#### F1. Volume Confirmation / RVOL
- **適配：** 50△ Q△ B△｜**heat：** 高｜**prog：** 高｜**證據：** C  
- **來源：** ChartMath VWAP/RVOL/ORB 文 https://chartmath.com/blog/vwap-vs-rvol-vs-orb-which-technical-indicators-work-best  

#### F2. OBV / Volume Divergence
- **適配：** 全△｜**heat：** 中｜**prog：** 高｜**證據：** C  

#### F3. CVD（Cumulative Volume Delta）
- **適配：** B△ E△｜**heat：** 高（加密）｜**prog：** 中｜**證據：** C  
- **來源：** https://markettrace.ai/blog/cumulative-volume-delta ；https://cryptoadventure.com/cumulative-volume-delta-cvd-how-to-read-buyer-vs-seller-aggression-in-crypto/  
- **備註：** 需逐筆／多所數據；與現有 Yahoo 日線管線落差大。

#### F4. Funding Rate Extremes
- **適配：** B● E●｜**heat：** 高｜**prog：** 高｜**證據：** C  
- **備註：** 擁擠多空擠壓敘事；適合**減碼警報**，非現貨加碼。本專案現貨偏重 → 可觀察。

#### F5. Open Interest + Price
- **適配：** B△ E△｜**heat：** 中｜**prog：** 中｜**證據：** C  

#### F6. Perp Basis / Cash-and-Carry 敘事
- **適配：** B△｜**heat：** 中｜**prog：** 中｜**證據：** C  
- **備註：** 套利／結構性，非本專案袖口買點。

---

### G. 總經／跨市濾網

#### G1. Real Yields / USD Strength → Gold
- **適配：** G● U●｜**heat：** 中｜**prog：** 中｜**證據：** C/B（總經共識強，規則化閾值需自定）  
- **vs 現行：** 可當黃金買點的**風險濾網**（美元過強時降級）。

#### G2. DXY / USDTWD Correlation Overlay
- **適配：** U● G△｜**heat：** 低｜**prog：** 中｜**證據：** D/C  

#### G3. Risk-On/Off for Leveraged TW ETF
- **適配：** L●｜**heat：** 中｜**prog：** 中｜**證據：** D — 與現行 Level／年線閘重疊。  

#### G4. Seasonality（月／週效應）
- **適配：** 全△｜**heat：** 中｜**prog：** 高｜**證據：** B/C（視研究）  
- **備註：** 單獨弱；可當次要濾網。

---

### H. 台股籌碼／本土紀律

#### H1. 法人連買＋融資未暴增（籌碼沉澱）
- **適配：** 50△ L○（ETF 弱）；殘股監控△｜**heat：** 高｜**prog：** 中｜**證據：** C  
- **來源：** https://efrontrade.com/2026/02/chip-analysis-foreign-investors-margin-balance-strategy.html ；https://blog.wistock.ai/practical-cases-experience-sharing/chip-concentration-buying-signals-guide/  
- **備註：** **AGENTS 已部分採用**（inst_ratio、融資分流）；選股已降級，勿擴個股池。

#### H2. 土洋合買／投量比
- **適配：** ○（持倉優先策略）｜**heat：** 高｜**prog：** 中｜**證據：** C  
- **來源：** https://x.wearn.com/tid/80f ；https://gorich.tw/institutional-investors-and-chips-analysis-guide/  
- **備註：** 社群警告「連買≠安全」、季底作帳；存活者偏差。

#### H3. 月線防守／大盤月線
- **適配：** 50● L●｜**heat：** 高｜**prog：** 高｜**證據：** C/D  
- **來源：** https://readmo.cmoney.tw/article/15edd4d8-b3f7-43db-9be1-0431d3879d7f  
- **vs 現行：** 與 Level／20MA 濾網高度重疊 → 標「已採用變體」。

#### H4. 兩日不站回／收盤確認
- **適配：** 50● 殘股●｜**heat：** 中｜**prog：** 高｜**證據：** D（本土紀律）  
- **備註：** **已採用**（AGENTS／close_confirm）。

#### H5. 阿呆谷回避（開盤恐慌不砍）
- **適配：** 全台股●｜**heat：** 高｜**prog：** 高｜**證據：** D  
- **備註：** **已採用**（09:00–09:30 freeze；破防守收盤確認）。

#### H6. 槓桿 ETF 衰減意識（正2／反1）
- **適配：** L●｜**heat：** 中｜**prog：** —｜**證據：** D  
- **備註：** 反1 已出清；正2 用年線／Level 控加碼 — **已部分採用**。

#### H7. 外資現貨買超＋期貨避險拆解
- **適配：** L△ 50△｜**heat：** 中｜**prog：** 低｜**證據：** C  
- **來源：** gorich 籌碼攻略（假買超真避險）  
- **備註：** 資料需求高；非優先。

---

### I. 多模型／集成

#### I1. Hierarchical Filter（大週期趨勢 AND 小週期進場）
- **例：** 200DMA 多頭 ∩ 現行乖離評等 ≥B  
- **適配：** G● V● Q●｜**heat：** 中｜**prog：** 高｜**證據：** —（工程模式）  
- **vs 現行：** **最自然的下一步**；回測成本低。

#### I2. Regime Switch Ensemble（Hurst/ADX 選模型）
- **適配：** G● B△｜**prog：** 中｜**證據：** A/B（Hurst 文獻）  

#### I3. Voting / Score Blend
- **適配：** 全△｜**prog：** 中｜**證據：** —  
- **備註：** 易過擬合；需嚴格 walk-forward。

#### I4. Core-Satellite：Dual Momentum 核心 + 現行評等衛星
- **適配：** V/X 核心 + G/U 衛星｜**prog：** 高｜**證據：** 概念  

---

## 4. 商品 × 方法適配矩陣（節選高相關）

圖例：●建議研究適配｜△次要｜○低｜已=本專案已用變體

| 方法 | G | U | 50 | L | V | X | Q | B | E | heat |
|------|---|---|----|---|---|---|---|---|---|------|
| 現行乖離+止穩 | 已 | 已 | 已 | 已 | 已 | 已 | 已 | 監 | 監 | — |
| 長均趨勢濾網 | ● | △ | △ | △ | ● | ● | ● | △ | △ | 中 |
| Dual Momentum | △ | ○ | ○ | ○ | ● | ● | △ | ○ | ○ | 中 |
| 12–1 絕對動量 | △ | ○ | ○ | △ | ● | ● | ● | △ | △ | 中 |
| Hurst regime | ● | △ | △ | △ | △ | △ | △ | △ | △ | 低 |
| 杯柄 / VCP | △ | ○ | ○ | ○ | △ | ○ | △ | △ | △ | 高 |
| H&S | △ | △ | △ | △ | △ | △ | △ | △ | △ | 高 |
| RSI-MR+濾網 | △ | ○ | △ | ○ | △ | △ | △ | ○ | ○ | 中 |
| 美金動態σ乖離 | △ | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | 低 |
| 法人+融資沉澱 | ○ | ○ | △ | ○ | ○ | ○ | ○ | ○ | ○ | 高 |
| Level/月線/阿呆谷 | ○ | ○ | 已 | 已 | ○ | ○ | ○ | ○ | ○ | 高 |
| SMC/ICT | △ | △ | ○ | ○ | ○ | ○ | ○ | △ | △ | 高 |
| Funding/CVD | ○ | ○ | ○ | ○ | ○ | ○ | ○ | △ | △ | 高 |
| ORB/VWAP 日內 | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | 高 |
| 階層濾網 I1 | ● | △ | △ | ● | ● | ● | ● | △ | △ | 中 |

---

## 5. 兩欄短名單

### 5.1 值得先回測（可程式化＋證據較佳或與現行差異性大）

1. **階層濾網：** 200DMA（或 12 月動能）多頭 ∩ 現行 grade ≥ 門檻 — 全商品低成本對照  
2. **Dual Momentum / 絕對動量** — 專攻 VOO／VXUS（±QQQ）vs 現行 S/B 門檻  
3. **Hurst（或 ADX）regime → 切換「拉回評等」vs「突破／空手」** — 優先 GOLD  
4. **USDTWD 動態閾值**（σ 或分位數）vs 固定 +1.5% 減碼 — 驗證減碼穩定度  
5. **黃金：長均空倉濾網 + 現行 B 袖口** vs 現行單模 — 對照 QuantifiedStrategies 敘事  

> **回測狀態（2026-07-18）：** 已跑 `src_scripts/research/run_shortlist_backtest.py` → [`reports/latest/backtest/shortlist_backtest.md`](../../reports/latest/backtest/shortlist_backtest.md)。摘要見 §5.3。

### 5.2 社群熱但僅觀察（C/D 或不合 EOD／持倉優先）

- SMC/ICT 全套、CVD、Killzone（repaint／資料重）  
- ORB／VWAP／Gap-and-Go（日內；與少上班衝突）  
- 杯柄／VCP／H&S 單兵系統（樣本稀或學術爭議）  
- 「法人連買 N 日」標題策略（存活者偏差；且不擴個股池）  
- Supertrend／純指標崇拜帖  

### 5.3 短名單回測結論（首輪・勿直接上線）

| # | 冠軍（全樣本 CP） | 結論 |
|---|-------------------|------|
| 1 階層 | QQQ／VXUS／VOO：`200∩B+` 明顯優於純 B+（減 churn） | 美股拉回評等全日倉會爆操作；階層濾網必要，但 CP 仍多為負 |
| 2 動量 | **VOO／QQQ 絕對 12m 動量** CP 正且 OOS 亦正；Dual VOO↔VXUS 弱於單資產絕對動量 | **唯一值得繼續深挖**；可當 V／X／Q 核心候選，勿取代 G／U 評等 |
| 3 Hurst | 輸給 GOLD baseline B+ | 簡化 Hurst 無增益；擱置 |
| 4 美金賣 | **袖口 50%@+1.5／清倉@+3** 最佳（MDD 大降） | 與現行 live 方向一致；σ／P75 幾乎＝固定 1.5% |
| 5 黃金長均 | longMA 全倉／分批皆略降 MDD，CP 略改善但仍負 | 可作可選濾網實驗，未到寫入 policy |

---

## 6. 下一步

1. ~~短名單 5.1 回測~~ → 見 §5.3；下一步優先：**絕對動量 walk-forward 參數穩健性**（12m vs 6/10m）與 **美金袖口已對齊 live、維持監控**。  
2. 統一 CP；OOS 已附在 `shortlist_backtest.md`。  
3. 美股觀測若續用評等，**禁止**無 200DMA／動能濾網的全日倉回測當決策依據。  
4. 通過穩健性後才考慮寫入 `grade_buy_policy`／掃描器（目前：**不上線**）。

---

## 7. 別名合併表（避免重複 alpha 幻覺）

| 正規名 | 常見別名 |
|--------|----------|
| VCP | 波動緊縮、Minervini base、緊縮杯柄 |
| SMC/ICT | OB、FVG、BOS、CHoCH、OTE、PO3 |
| Dual Momentum | GEM、相對+絕對動量 |
| 長均趨勢 | 黃金交叉家族、200DMA、12-month SMA |
| 籌碼沉澱 | 法人買＋融資減、主力吃貨散戶出場 |

---

*海搜截止註記：2026-07-18。後續可繼續往 TradingView 熱門腳本名、PTT／Mobile01 討論串追加短卡，無需改架構。*
