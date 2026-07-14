import os
import sys
import json
import time
import urllib.request
import pandas as pd
import numpy as np
import shutil
from datetime import datetime

WORKSPACE = r"g:\我的雲端硬碟\dev\twstockals"
CACHE_DIR = os.path.join(WORKSPACE, "market_crawled_cache", "market_cache")

# 全體上市/上櫃類股代碼對照表
INDUSTRY_MAP = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "07": "化學工業", "08": "玻璃陶瓷",
    "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業",
    "13": "電子工業", "14": "建材營造", "15": "航運業",   "16": "觀光事業",
    "17": "金融保險", "18": "百貨貿易", "19": "綜合",     "20": "其他",
    "21": "化學工業", "22": "生技醫療業", "23": "油電燃氣業", "24": "半導體業",
    "25": "電腦及週邊設備業", "26": "光電業", "27": "通信網路業", "28": "電子零組件業",
    "29": "電子通路業", "30": "資訊服務業", "31": "其他電子業",
    "32": "文化創意業", "33": "農業科技業", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "其他業"
}

# 全市場熱門標的主要業務對照字典
BUSINESS_FALLBACK = {
    "2442": "建材營造業 (由電子零件轉型優質建商，專注大台北精華區建案開發)",
    "2611": "航運業/客運業 (貨櫃車貨運運輸及物流，轉投資大佳商旅與土地開發)",
    "4746": "生技醫療業 (原料藥 API 大廠，專注降血脂、抗癌及防曬劑原料)",
    "1810": "玻璃陶瓷業 (衛浴設備龍頭，轉投資國防軍工抗彈陶瓷板與碳纖維複合材料)",
    "2352": "電腦及週邊設備業 (明基 BenQ 集團旗艦，發展醫療器材、明基醫院與智能解決方案)",
    "2547": "建材營造業 (捷運聯開案指標建商，經營地上權建案與垃圾焚化發電綠能業務)",
    "2812": "金融保險業 (中南部龍頭地方商業銀行，深耕中小企業融資與信託業務)",
    "3051": "光電業 (偏光板製造大廠，近年積極發展車用顯示器與利基型液晶代工)",
    "3652": "電腦及週邊設備業 (自動辨識系統大廠，以工業行動電腦、條碼與 RFID 設備為主)",
    "3624": "電子零組件業 (全球薄膜精密電阻大廠，高頻感測與積層電阻製造銷售)",
    "6163": "資訊服務業 (寬頻網路與資通訊安全整合服務，發展智慧交通與雲端系統)",
    "6510": "半導體業 (半導體測試晶圓針測卡與 IC 載板龍頭，台積電供應鏈成員)",
    "1313": "化學工業 (DOP 可塑劑與 PA 鄰苯二甲酸酐全球龍頭，佈局電子化學品)",
    "1409": "紡織纖維業 (新光集團旗下聚酯纖維、瓶片及工程塑膠大廠)",
    "1597": "電機機械業 (微型線性滑軌全球大廠，高精度線性馬達與智慧定位模組)",
    "2377": "電腦及週邊設備業 (全球電競筆電與高階顯示卡巨頭，發展 AI 伺服器與充電樁)",
    "2390": "其他電子業 (智慧家庭無線監控系統、物聯網感測與防盜安全設備)",
    "2414": "資訊服務業 (科技產品通路代理及大型物流整合服務，兼營工業型 PDA)",
    "2417": "電腦及週邊設備業 (影音擷取卡與網路攝影機龍頭，發展 AI 邊緣運算模組)",
    "2420": "電子零組件業 (微動開關與軍規高安全備援電源供應器大廠)",
    "5469": "電子零組件業 (全球多層 PCB 印刷電路版龍頭大廠，深耕伺服器與筆電板)",
    "3706": "電腦及週邊設備業 (神達投控，主攻 AI/雲端伺服器、邊緣運算與智慧車用電子)",
    "3484": "電子零組件業 (全球 AC 電源插座與連接器龍頭，切入 AI 工具機與電動車充電槍)"
}

def get_latest_trading_dates(n=90):
    """從現有 TAIEX 數據中獲取最近 n 個交易日"""
    data_dir = os.path.join(WORKSPACE, "market_crawled_cache")
    dirs = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d)) and d.isdigit()]
    if not dirs:
        raise FileNotFoundError("找不到任何歷史數據資料夾")
    latest_folder = sorted(dirs)[-1]
    
    taiex_path = os.path.join(data_dir, latest_folder, "TAIEX_kline.csv")
    if not os.path.exists(taiex_path):
        raise FileNotFoundError(f"找不到大盤資料: {taiex_path}")
        
    df = pd.read_csv(taiex_path).sort_values("date").reset_index(drop=True)
    dates = df["date"].tail(n).tolist()
    return dates

def fetch_json_with_cache(url, filename):
    """帶快取機制的 JSON 下載器，防禦性加入下載延遲"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filepath = os.path.join(CACHE_DIR, filename)
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
            
    if not url:
        return None
        
    print(f"  正在下載: {filename} ...")
    time.sleep(2.0)
    
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read().decode('utf-8')
            data = json.loads(content)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
    except Exception as e:
        print(f"  下載失敗 {url}: {e}")
        return None

def download_market_data(dates):
    """下載指定日期列表的所有上市/上櫃行情、法人、外資持股比例與信用餘額數據"""
    print(f"啟動全市場快取下載環，目標天數: {len(dates)} 天...")
    for date in dates:
        date_no_dash = date.replace("-", "")
        dt = datetime.strptime(date, "%Y-%m-%d")
        roc_year = dt.year - 1911
        roc_date = f"{roc_year}/{dt.month:02d}/{dt.day:02d}"
        
        # 1. 上市收盤行情
        url_tse_price = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_no_dash}&type=ALLBUT0999"
        fetch_json_with_cache(url_tse_price, f"tse_price_{date_no_dash}.json")
        
        # 2. 上市三大法人
        url_tse_inst = f"https://www.twse.com.tw/fund/T86?response=json&date={date_no_dash}&selectType=ALLBUT0999"
        fetch_json_with_cache(url_tse_inst, f"tse_inst_{date_no_dash}.json")
        
        # 3. 上櫃收盤行情
        url_tpex_price = f"https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d={roc_date}&s=0,asc,0&o=json"
        fetch_json_with_cache(url_tpex_price, f"tpex_price_{date_no_dash}.json")
        
        # 4. 上櫃三大法人
        url_tpex_inst = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&d={roc_date}&se=EW&t=D&o=json"
        fetch_json_with_cache(url_tpex_inst, f"tpex_inst_{date_no_dash}.json")

    # 下載最新一天的外資持股比例大檔
    latest_date = dates[-1]
    latest_date_no_dash = latest_date.replace("-", "")
    
    url_tse_qfii = f"https://www.twse.com.tw/fund/MI_QFIIS?response=json&date={latest_date_no_dash}&selectType=ALLBUT0999"
    fetch_json_with_cache(url_tse_qfii, f"tse_qfiis_{latest_date_no_dash}.json")
    
    url_tpex_qfii = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_qfii"
    fetch_json_with_cache(url_tpex_qfii, f"tpex_qfiis_{latest_date_no_dash}.json")
    
    # 下載最近 5 個交易日的上市/上櫃信用交易（融資）明細
    print("下載最近 5 個交易日的信用交易（融資）明細...")
    for date in dates[-5:]:
        date_no_dash = date.replace("-", "")
        dt = datetime.strptime(date, "%Y-%m-%d")
        roc_year = dt.year - 1911
        roc_date = f"{roc_year}/{dt.month:02d}/{dt.day:02d}"
        
        url_tse_margin = f"https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={date_no_dash}&selectType=ALL"
        fetch_json_with_cache(url_tse_margin, f"tse_margin_{date_no_dash}.json")
        
        url_tpex_margin = f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={roc_date}&f=json"
        fetch_json_with_cache(url_tpex_margin, f"tpex_margin_{date_no_dash}.json")
        
    print("全市場快取下載與核對完成！")

def load_company_profiles():
    """下載並載入上市與上櫃公司的基本資料（類股與經營業務）"""
    print("正在加載上市櫃公司基本資料大檔...")
    
    tse_profiles = {}
    tse_file = os.path.join(CACHE_DIR, "tse_profiles.json")
    if not os.path.exists(tse_file):
        try:
            print("  正在下載: tse_profiles.json ...")
            url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8-sig'))
                with open(tse_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("下載 TSE 公司基本資料失敗:", e)
            
    if os.path.exists(tse_file):
        try:
            with open(tse_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for r in data:
                code = r.get("公司代號", "").strip()
                tse_profiles[code] = {
                    "industry_code": r.get("產業別", "").strip(),
                    "business": r.get("主要經營業務", "").strip()
                }
        except Exception as e:
            print("解析 TSE 公司基本資料失敗:", e)
            
    tpex_profiles = {}
    tpex_file = os.path.join(CACHE_DIR, "tpex_profiles.json")
    if not os.path.exists(tpex_file):
        try:
            print("  正在下載: tpex_profiles.json ...")
            url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8-sig'))
                with open(tpex_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("下載 TPEx 公司基本資料失敗:", e)
            
    if os.path.exists(tpex_file):
        try:
            with open(tpex_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for r in data:
                code = r.get("SecuritiesCompanyCode", "").strip()
                tpex_profiles[code] = {
                    "industry_code": r.get("SecuritiesIndustryCode", "").strip(),
                    "business": ""
                }
        except Exception as e:
            print("解析 TPEx 公司基本資料失敗:", e)
            
    profiles = {}
    profiles.update(tse_profiles)
    profiles.update(tpex_profiles)
    return profiles

# ----------------- JSON 解析器 -----------------

def parse_tse_price(data):
    rows = []
    if not data or "tables" not in data:
        return rows
    for t in data["tables"]:
        fields = t.get("fields", [])
        if "證券代號" in fields and "收盤價" in fields:
            idx_code = fields.index("證券代號")
            idx_name = fields.index("證券名稱")
            idx_close = fields.index("收盤價")
            idx_open = fields.index("開盤價")
            idx_high = fields.index("最高價")
            idx_low = fields.index("最低價")
            idx_vol = fields.index("成交股數")
            
            for r in t.get("data", []):
                code = r[idx_code].strip()
                name = r[idx_name].strip()
                
                # 放行 4, 5, 6 碼代號，並排除 6 碼純數字且非 00 開頭的權證
                if len(code) not in [4, 5, 6]:
                    continue
                if len(code) == 6 and code.isdigit() and not code.startswith("00"):
                    continue
                    
                try:
                    close = float(r[idx_close].replace(",", ""))
                    open_p = float(r[idx_open].replace(",", ""))
                    high = float(r[idx_high].replace(",", ""))
                    low = float(r[idx_low].replace(",", ""))
                    vol = float(r[idx_vol].replace(",", ""))
                    
                    rows.append({
                        "code": code, "name": name, "open": open_p, "high": high, "low": low,
                        "close": close, "volume": vol, "market": "TSE"
                    })
                except ValueError:
                    continue
            break
    return rows

def parse_tpex_price(data):
    rows = []
    if not data or "tables" not in data:
        return rows
    for t in data["tables"]:
        fields = t.get("fields", [])
        if "代號" in fields and "收盤" in fields:
            idx_code = fields.index("代號")
            idx_name = fields.index("名稱")
            idx_close = fields.index("收盤")
            idx_open = fields.index("開盤")
            idx_high = fields.index("最高")
            idx_low = fields.index("最低")
            idx_vol = fields.index("成交股數")
            
            for r in t.get("data", []):
                code = r[idx_code].strip()
                name = r[idx_name].strip()
                
                # 放行 4, 5, 6 碼代號，並排除 6 碼純數字且非 00 開頭的權證
                if len(code) not in [4, 5, 6]:
                    continue
                if len(code) == 6 and code.isdigit() and not code.startswith("00"):
                    continue
                    
                try:
                    close = float(r[idx_close].replace(",", ""))
                    open_p = float(r[idx_open].replace(",", ""))
                    high = float(r[idx_high].replace(",", ""))
                    low = float(r[idx_low].replace(",", ""))
                    vol = float(r[idx_vol].replace(",", ""))
                    
                    rows.append({
                        "code": code, "name": name, "open": open_p, "high": high, "low": low,
                        "close": close, "volume": vol, "market": "OTC"
                    })
                except ValueError:
                    continue
            break
    return rows

def parse_tse_inst(data):
    inst_data = {}
    if not data or "data" not in data:
        return inst_data
    fields = data.get("fields", [])
    if "證券代號" in fields:
        idx_code = fields.index("證券代號")
        idx_foreign = -1
        idx_trust = -1
        for idx, f in enumerate(fields):
            if "外陸資買賣超股數(不含外資自營商)" in f or "外資及陸資買賣超股數" in f:
                idx_foreign = idx
            elif "投信買賣超股數" in f:
                idx_trust = idx
                
        if idx_foreign != -1 and idx_trust != -1:
            for r in data["data"]:
                code = r[idx_code].strip()
                try:
                    f_buy = int(r[idx_foreign].replace(",", ""))
                    t_buy = int(r[idx_trust].replace(",", ""))
                    inst_data[code] = {
                        "foreign_buy": f_buy,
                        "trust_buy": t_buy
                    }
                except ValueError:
                    continue
    return inst_data

def parse_tpex_inst(data):
    inst_data = {}
    if not data or "tables" not in data or not data["tables"]:
        return inst_data
    t = data["tables"][0]
    fields = t.get("fields", [])
    if "代號" in fields:
        idx_code = fields.index("代號")
        idx_foreign = 4
        idx_trust = 10
        for r in t.get("data", []):
            code = r[idx_code].strip()
            try:
                f_buy = int(r[idx_foreign].replace(",", ""))
                t_buy = int(r[idx_trust].replace(",", ""))
                inst_data[code] = {
                    "foreign_buy": f_buy,
                    "trust_buy": t_buy
                }
            except (ValueError, IndexError):
                continue
    return inst_data

def load_monthly_revenues():
    """下載並載入全市場上市櫃月營收數據"""
    revenues = {}
    tse_url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    tpex_url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
    
    tse_cache = os.path.join(CACHE_DIR, "tse_revenue_latest.json")
    tpex_cache = os.path.join(CACHE_DIR, "tpex_revenue_latest.json")
    
    def download_cache_url(url, filepath):
        if os.path.exists(filepath):
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            if mtime.date() == datetime.today().date():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
        print(f"  下載最新營收數據: {os.path.basename(filepath)} ...")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8-sig'))
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
        except Exception as e:
            print(f"  下載營收失敗: {e}")
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
            return []
            
    tse_data = download_cache_url(tse_url, tse_cache)
    tpex_data = download_cache_url(tpex_url, tpex_cache)
    
    for row in tse_data + tpex_data:
        code = row.get("公司代號", "").strip()
        if not code:
            continue
        try:
            mom = float(row.get("營業收入-上月比較增減(%)", 0.0))
            yoy = float(row.get("營業收入-去年同月增減(%)", 0.0))
            revenues[code] = {"mom": mom, "yoy": yoy}
        except (ValueError, TypeError):
            revenues[code] = {"mom": 0.0, "yoy": 0.0}
            
    return revenues

def load_foreign_ratios(date_no_dash):
    ratios = {}
    issued_shares = {}
    tse_path = os.path.join(CACHE_DIR, f"tse_qfiis_{date_no_dash}.json")
    if os.path.exists(tse_path):
        try:
            with open(tse_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data and "data" in data:
                fields = data.get("fields", [])
                idx_code = fields.index("證券代號")
                idx_ratio = -1
                idx_issued = -1
                for idx, fld in enumerate(fields):
                    if "持股比率" in fld:
                        idx_ratio = idx
                    elif "發行股數" in fld:
                        idx_issued = idx
                if idx_ratio != -1:
                    for r in data["data"]:
                        code = r[idx_code].strip()
                        try:
                            val_str = str(r[idx_ratio]).replace(",", "")
                            ratios[code] = float(val_str)
                            if idx_issued != -1:
                                issued_shares[code] = float(str(r[idx_issued]).replace(",", ""))
                        except ValueError:
                            pass
        except Exception as e:
            print("解析上市外資比率與發行股數失敗:", e)
            
    tpex_path = os.path.join(CACHE_DIR, f"tpex_qfiis_{date_no_dash}.json")
    if os.path.exists(tpex_path):
        try:
            with open(tpex_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for r in data:
                code = r.get("SecuritiesCompanyCode", "").strip()
                ratio_val = r.get("ShareholdingRatio", "0")
                issued_val = r.get("IssuedShares", "0")
                try:
                    val_str = str(ratio_val).replace(",", "")
                    ratios[code] = float(val_str)
                    issued_shares[code] = float(str(issued_val).replace(",", ""))
                except ValueError:
                    pass
        except Exception as e:
            print("解析上櫃外資比率與發行股數失敗:", e)
    return ratios, issued_shares

def parse_tse_margin(data):
    margin_data = {}
    if not data or "tables" not in data or len(data["tables"]) < 2:
        return margin_data
    t = data["tables"][1]
    fields = t.get("fields", [])
    idx_code = 0
    idx_balance = 6
    idx_limit = 7
    
    for idx, f in enumerate(fields):
        if "代號" in f or "股票代號" in f:
            idx_code = idx
        elif "融資今日餘額" in f or "今日餘額" in f or "lB" in f:
            idx_balance = idx
        elif "融資限額" in f or "限額" in f or "魭B" in f:
            idx_limit = idx
            
    for r in t.get("data", []):
        if len(r) <= max(idx_code, idx_balance, idx_limit):
            continue
        code = r[idx_code].strip()
        try:
            val_balance = str(r[idx_balance]).replace(",", "")
            val_limit = str(r[idx_limit]).replace(",", "")
            balance = float(val_balance)
            limit = float(val_limit)
            margin_data[code] = {
                "margin_balance": balance,
                "margin_limit": limit
            }
        except ValueError:
            continue
    return margin_data

def parse_tpex_margin(data):
    margin_data = {}
    if not data or "tables" not in data or not data["tables"]:
        return margin_data
    t = data["tables"][0]
    fields = t.get("fields", [])
    idx_code = 0
    idx_balance = 6
    idx_limit = 9
    
    for idx, f in enumerate(fields):
        if "代號" in f:
            idx_code = idx
        elif "資餘額" in f or "餘額" in f:
            idx_balance = idx
        elif "資限額" in f or "限額" in f:
            idx_limit = idx
            
    for r in t.get("data", []):
        if len(r) <= max(idx_code, idx_balance, idx_limit):
            continue
        code = r[idx_code].strip()
        try:
            val_balance = str(r[idx_balance]).replace(",", "")
            val_limit = str(r[idx_limit]).replace(",", "")
            balance = float(val_balance)
            limit = float(val_limit)
            margin_data[code] = {
                "margin_balance": balance,
                "margin_limit": limit
            }
        except ValueError:
            continue
    return margin_data

def calculate_kd(df):
    df = df.copy()
    df['low_9'] = df['low'].rolling(window=9).min()
    df['high_9'] = df['high'].rolling(window=9).max()
    df['rsv'] = 0.0
    denom = df['high_9'] - df['low_9']
    non_zero = denom != 0
    df.loc[non_zero, 'rsv'] = ((df.loc[non_zero, 'close'] - df.loc[non_zero, 'low_9']) / denom[non_zero]) * 100
    
    k, d = 50.0, 50.0
    k_list, d_list = [], []
    for rsv in df['rsv']:
        if pd.isna(rsv):
            k_list.append(50.0)
            d_list.append(50.0)
        else:
            k = (2/3) * k + (1/3) * rsv
            d = (2/3) * d + (1/3) * k
            k_list.append(k)
            d_list.append(d)
    df['K'] = k_list
    df['D'] = d_list
    return df

# ----------------- 核心二階段篩選 -----------------

def run_screener(dates, profiles, write_reports=True):
    print("\n開始聚合歷史快取並運行篩選器...")
    
    # 載入使用者的持股與自選股代碼
    targets_path = os.path.join(WORKSPACE, "config", "my_targets.json")
    target_codes = set()
    if os.path.exists(targets_path):
        try:
            with open(targets_path, 'r', encoding='utf-8') as f:
                tgt_data = json.load(f)
            for item in tgt_data.get("portfolio", []):
                if item.get("market") != "US":
                    target_codes.add(item["code"])
            for item in tgt_data.get("watchlist", []):
                if item.get("market") != "US":
                    target_codes.add(item["code"])
            print(f"成功載入自選/持股標的共 {len(target_codes)} 檔: {target_codes}")
        except Exception as e:
            print("載入 targets 配置失敗:", e)
            
    # 新增載入社群收集標的至免過濾名單，確保它們被篩選器完整計算
    social_picks_path = os.path.join(WORKSPACE, "config", "social_picks.json")
    if os.path.exists(social_picks_path):
        try:
            with open(social_picks_path, 'r', encoding='utf-8') as f:
                sp_data = json.load(f)
            for item in sp_data.get("tracked_stocks", []):
                target_codes.add(item["code"])
            print(f"成功將社群標的併入免過濾清單，共計 {len(target_codes)} 檔")
        except Exception as e:
            print("載入 social_picks 配置失敗:", e)

    latest_date_no_dash = dates[-1].replace("-", "")
    foreign_ratios, issued_shares = load_foreign_ratios(latest_date_no_dash)
    
    # 下載並加載最新月營收申報資料
    print("正在下載並加載最新月營收申報資料...")
    monthly_revenues = load_monthly_revenues()
    
    daily_margins = {}
    for d in dates[-5:]:
        d_no_dash = d.replace("-", "")
        tse_marg_json = fetch_json_with_cache("", f"tse_margin_{d_no_dash}.json")
        tpex_marg_json = fetch_json_with_cache("", f"tpex_margin_{d_no_dash}.json")
        
        day_m = {}
        for code, val in parse_tse_margin(tse_marg_json).items():
            day_m[code] = val
        for code, val in parse_tpex_margin(tpex_marg_json).items():
            day_m[code] = val
        daily_margins[d] = day_m
    
    stock_history = {}
    for date in dates:
        date_no_dash = date.replace("-", "")
        
        tse_price = fetch_json_with_cache("", f"tse_price_{date_no_dash}.json")
        tpex_price = fetch_json_with_cache("", f"tpex_price_{date_no_dash}.json")
        
        daily_prices = {}
        for r in parse_tse_price(tse_price):
            daily_prices[r["code"]] = r
        for r in parse_tpex_price(tpex_price):
            daily_prices[r["code"]] = r
            
        tse_inst = fetch_json_with_cache("", f"tse_inst_{date_no_dash}.json")
        tpex_inst = fetch_json_with_cache("", f"tpex_inst_{date_no_dash}.json")
        
        daily_inst = {}
        for code, val in parse_tse_inst(tse_inst).items():
            daily_inst[code] = val
        for code, val in parse_tpex_inst(tpex_inst).items():
            daily_inst[code] = val
            
        for code, p in daily_prices.items():
            if code not in stock_history:
                stock_history[code] = {
                    "name": p["name"],
                    "market": p["market"],
                    "history": []
                }
            inst = daily_inst.get(code, {"foreign_buy": 0, "trust_buy": 0})
            stock_history[code]["history"].append({
                "date": date,
                "open": p["open"],
                "high": p["high"],
                "low": p["low"],
                "close": p["close"],
                "volume": p["volume"],
                "foreign_buy": inst["foreign_buy"],
                "trust_buy": inst["trust_buy"]
            })

    # ========== 第一階段：計算所有個股 5 日漲幅並篩選前 20% 強勢類股 ==========
    print(f"\n[第一階段] 正在計算全市場類股動能，共載入 {len(stock_history)} 檔標的...")
    all_stocks_data = {}
    for code, info in stock_history.items():
        hist = info["history"]
        if len(hist) < 5:
            continue
        df = pd.DataFrame(hist).sort_values("date").reset_index(drop=True)
        latest = df.iloc[-1]
        close = float(latest["close"])
        close_5d = float(df['close'].iloc[-5])
        change_5d = ((close - close_5d) / close_5d) * 100 if close_5d > 0 else 0.0
        
        prof = profiles.get(code, {})
        ind_code = prof.get("industry_code", "")
        industry = INDUSTRY_MAP.get(ind_code, "其他")
        
        all_stocks_data[code] = {
            "info": info,
            "df": df,
            "close": close,
            "change_5d": change_5d,
            "industry": industry,
            "prof": prof
        }
        
    # 群組計算產業 5日平均漲幅
    industry_returns = {}
    for code, sd in all_stocks_data.items():
        ind = sd["industry"]
        if ind == "其他" or not ind or ind == "綜合":
            continue
        if ind not in industry_returns:
            industry_returns[ind] = []
        industry_returns[ind].append(sd["change_5d"])
        
    industry_scores = {}
    for ind, rets in industry_returns.items():
        if len(rets) >= 2:
            industry_scores[ind] = np.mean(rets)
            
    # 篩選前 20% 的類股
    sorted_industries = sorted(industry_scores.items(), key=lambda x: x[1], reverse=True)
    top_n = max(1, int(len(sorted_industries) * 0.20))
    strong_sectors = [ind for ind, score in sorted_industries[:top_n]]
    print(f"🔥 當前全市場前 20% 強勢產業 (共 {len(strong_sectors)} 個)：")
    for rank, (ind, score) in enumerate(sorted_industries[:top_n], 1):
        print(f"  第 {rank} 名: {ind} (5日均幅: {score:+.2f}%)")

    # ========== 第二階段：只在強勢產業與使用者標的中進行評分過濾 ==========
    print("\n[第二階段] 開始套用強勢產業過濾與量化評分...")
    results = []
    
    for code, sd in all_stocks_data.items():
        is_target = code in target_codes
        is_etf = len(code) == 6 or code.startswith("00")
        
        # 第一層：如果不是使用者標的，且不屬於強勢類股，則過濾
        if not is_target:
            if sd["industry"] not in strong_sectors:
                continue
                
        df = sd["df"]
        if len(df) < 60:
            if not is_target:
                continue
                
        df['5MA'] = df['close'].rolling(5).mean()
        df['10MA'] = df['close'].rolling(10).mean()
        df['20MA'] = df['close'].rolling(20).mean()
        df['60MA'] = df['close'].rolling(60).mean()
        df = calculate_kd(df)
        
        latest = df.iloc[-1]
        close = latest["close"]
        ma60 = latest["60MA"] if pd.notna(latest["60MA"]) else close
        ma20 = latest["20MA"] if pd.notna(latest["20MA"]) else close
        ma10 = latest["10MA"] if pd.notna(latest["10MA"]) else close
        ma5 = latest["5MA"] if pd.notna(latest["5MA"]) else close
        
        bias_20 = ((close - ma20) / ma20) * 100 if ma20 else 0.0
        bias_5 = ((close - ma5) / ma5) * 100 if ma5 else 0.0
        
        if 'volume' in df.columns:
            avg_vol_20d_lots = df['volume'].tail(20).mean() / 1000.0
            avg_vol_5d_lots = df['volume'].tail(5).mean() / 1000.0
        else:
            avg_vol_20d_lots = 0.0
            avg_vol_5d_lots = 0.0
        vol_surge = avg_vol_5d_lots / avg_vol_20d_lots if avg_vol_20d_lots > 0 else 1.0
        
        # 第二層：如果不是使用者標的，則套用 veto 過濾
        if not is_target:
            if close < 10.0:
                continue
            if pd.notna(ma60) and ma60 > 0 and close < ma60:
                continue
            if avg_vol_20d_lots < 300.0:
                continue
                
        # 籌碼與打分
        foreign_buy_5d = df['foreign_buy'].tail(5).sum() / 1000.0
        trust_buy_5d = df['trust_buy'].tail(5).sum() / 1000.0
        inst_buy_5d = foreign_buy_5d + trust_buy_5d
        inst_ratio = (inst_buy_5d / avg_vol_20d_lots) * 100 if avg_vol_20d_lots else 0.0
        
        consecutive_buy = 0
        for i in range(1, len(df)+1):
            day_net = (df['foreign_buy'].iloc[-i] + df['trust_buy'].iloc[-i]) / 1000.0
            if day_net > 0:
                consecutive_buy += 1
            else:
                break
                
        ma_alignment = "整理"
        if close > ma5 > ma10 > ma20:
            ma_alignment = "多頭排列"
            
        k_val = latest["K"] if "K" in latest else 50.0
        d_val = latest["D"] if "D" in latest else 50.0
        kd_status = "黃金交叉" if k_val > d_val else "死亡交叉"
        
        # 融資
        margin_balances = []
        margin_limits = []
        for d in dates[-5:]:
            val = daily_margins.get(d, {}).get(code, {})
            if val:
                margin_balances.append(val["margin_balance"])
                margin_limits.append(val["margin_limit"])
        margin_diff_5d = margin_balances[-1] - margin_balances[0] if len(margin_balances) >= 2 else 0.0
        margin_usage = (margin_balances[-1] / margin_limits[-1]) * 100 if len(margin_balances) >= 1 and margin_limits[-1] > 0 else 0.0
        
        # 提取月營收數據與計算投信累積持股比率
        rev = monthly_revenues.get(code, {"mom": 0.0, "yoy": 0.0})
        mom_val = rev["mom"]
        yoy_val = rev["yoy"]
        
        trust_buy_20d_shares = df['trust_buy'].tail(20).sum()
        issued = issued_shares.get(code, 0.0)
        trust_ratio_20d = (trust_buy_20d_shares / issued) * 100 if issued > 0 else 0.0

        # 開始計算綜合評分 (70%籌碼 + 30%技術)
        p_score = 50.0
        p_reasons = []
        
        if is_etf:
            # ETF 簡化計分
            p_score = 60.0
            if ma_alignment == "多頭排列":
                p_score += 15
                p_reasons.append("ETF均線多頭")
            if k_val > d_val:
                p_score += 10
                p_reasons.append("ETF KD黃金交叉")
        else:
            # 正常個股
            if inst_ratio >= 15.0:
                p_score += 25
                p_reasons.append(f"5日法人大買超(佔均量{inst_ratio:.1f}%)")
            elif inst_ratio >= 5.0:
                p_score += 15
                p_reasons.append(f"5日法人買超(佔均量{inst_ratio:.1f}%)")
            elif inst_ratio > 0.0:
                p_score += 5
                p_reasons.append(f"5日法人微買(佔均量{inst_ratio:.1f}%)")
                
            if consecutive_buy >= 3:
                p_score += 15
                p_reasons.append(f"法人連買{consecutive_buy}天")
                
            is_major_margin = False
            if margin_diff_5d > 0 and close > ma20 and inst_buy_5d > 0 and margin_usage < 25.0:
                is_major_margin = True
                
            if is_major_margin:
                p_score += 5
                margin_tag = "主力鎖碼"
                p_reasons.append(f"🔥 主力資增建倉鎖碼(5日資增{margin_diff_5d:.0f}張)")
            elif margin_diff_5d > 0:
                margin_tag = "散戶過熱"
            elif margin_diff_5d < -500:
                p_score += 10
                margin_tag = "資減沉澱"
                p_reasons.append(f"資減沉澱(5日資減{margin_diff_5d:.0f}張)")
            elif margin_diff_5d < 0:
                p_score += 5
                margin_tag = "資減沉澱"
                p_reasons.append(f"資減沉澱(5日資減{margin_diff_5d:.0f}張)")
            else:
                margin_tag = "無顯著變動"
                
            # 💡 投信鎖碼作帳特別加權 (累積吸籌 >= 1.5% 且連續買超 >= 3天 且低乖離 <= 6%)
            if trust_ratio_20d >= 1.5 and consecutive_buy >= 3 and bias_20 <= 6.0:
                p_score += 25
                p_reasons.append(f"🔥 投信鎖碼作帳股(20日吸籌{trust_ratio_20d:.2f}%)")
                
            # 💡 營收雙增籌碼潛伏特別加權 (YoY >= 30% 且 MoM >= 10% 且法人提前潛伏 且低乖離 <= 6%)
            if yoy_val >= 30.0 and mom_val >= 10.0 and inst_ratio >= 5.0 and bias_20 <= 6.0:
                p_score += 20
                p_reasons.append(f"📈 營收雙增籌碼潛伏(YoY {yoy_val:.1f}%, MoM {mom_val:.1f}%)")
                
        p_score = min(100.0, p_score)
        
        # 風險評估
        r_score = 30.0
        r_reasons = []
        
        if ma_alignment == "多頭排列":
            r_score -= 10
        else:
            r_score += 15
            r_reasons.append("均線非多頭排列")
            
        # 散戶過熱融資飆升檢查 (依據 AGENTS.md 融資特性分流規則)
        if not is_etf and margin_diff_5d > 0 and not is_major_margin:
            r_score += 15
            r_reasons.append("🔴 融資飆升")
            
        if bias_20 <= 4.0 and bias_20 >= -2.0:
            r_score -= 10
            r_reasons.append("🟢 安全低乖離(<4%)")
        elif bias_20 > 25.0:
            r_score += 45
            r_reasons.append("🔴 月線超高乖離(>25%)")
        elif bias_20 > 15.0:
            r_score += 30
            r_reasons.append("🔴 月線高乖離(>15%)")
            
        f_ratio = foreign_ratios.get(code, 15.0)
        if f_ratio >= 40.0:
            r_score += 15
            r_reasons.append(f"🚨 外資主導({f_ratio:.1f}%)")
        elif f_ratio <= 15.0:
            r_score -= 10
            r_reasons.append(f"✅ 內資主導({f_ratio:.1f}%)")
            
        if k_val < d_val:
            r_score += 10
            r_reasons.append("🔴 KD死亡交叉")
            
        r_score = max(5.0, min(100.0, r_score))
        rank_score = p_score - r_score
        
        # 業務說明
        business = BUSINESS_FALLBACK.get(code, "").strip()
        if not business:
            business = sd["prof"].get("business", "").strip()
        if not business:
            business = f"主要經營 {sd['industry']} 相關業務"
            
        results.append({
            "code": code,
            "name": sd["info"]["name"],
            "market": sd["info"]["market"],
            "industry": sd["industry"],
            "business": business,
            "close": close,
            "bias_20": bias_20,
            "bias_5": bias_5,
            "ma60": ma60,
            "foreign_ratio": f_ratio,
            "inst_buy_5d": inst_buy_5d,
            "inst_ratio": inst_ratio,
            "consecutive_buy": consecutive_buy,
            "ma_alignment": ma_alignment,
            "kd_status": f"{kd_status} (K:{k_val:.1f}/D:{d_val:.1f})",
            "k_val": k_val,
            "d_val": d_val,
            "vol_surge": vol_surge,
            "margin_diff_5d": margin_diff_5d,
            "margin_usage": margin_usage,
            "margin_tag": margin_tag if not is_etf else "ETF不計融資",
            "p_score": p_score,
            "r_score": r_score,
            "rank_score": rank_score,
            "p_reasons": p_reasons,
            "r_reasons": r_reasons,
            "ma5": float(ma5),
            "ma10": float(ma10),
            "ma20": float(ma20),
            "low_5d": float(df['low'].tail(5).min()) if 'low' in df.columns else float(close),
            "trust_ratio_20d": trust_ratio_20d,
            "revenue_yoy": yoy_val,
            "revenue_mom": mom_val
        })

    if not write_reports:
        return results

    # ========== 5. 輸出報告 (低危高利 與 高動能 分流) ==========
    latest_date_str = dates[-1]
    
    os.makedirs(os.path.join(WORKSPACE, "reports", "latest"), exist_ok=True)
    os.makedirs(os.path.join(WORKSPACE, "reports", "history"), exist_ok=True)
    
    # ---------------- B2. 低危高利選股報告 ----------------
    results.sort(key=lambda x: x["rank_score"], reverse=True)
    top_30_low_risk = results[:30]
    top_30_codes = {x["code"] for x in top_30_low_risk}
    extra_targets_low_risk = [x for x in results if x["code"] in target_codes and x["code"] not in top_30_codes]
    
    report_low_risk = os.path.join(WORKSPACE, "reports", "latest", "market_screener_low_risk.md")
    with open(report_low_risk, 'w', encoding='utf-8') as f:
        f.write("# 🔍 全市場量化選股排行榜 - 低危高利防守型 (Low Risk Ranking)\n\n")
        f.write(f"分析基準日：{latest_date_str}  \n")
        f.write("篩選標準：**綜合性價比得分 = 獲利可能性(籌碼+技術) - 風險得分**  \n")
        f.write("*(評分已排除非前20%強勢產業類股、20日均量 < 300張、收盤價 < 10元、及低於 60MA 季線之標的；持股/自選目標強制保留對照)*  \n\n")
        
        f.write("### 🏆 低危高利評估前 30 名標的\n\n")
        f.write("| 排名 | 股號 | 股名 | 市場/類股 | 最新收盤 | 綜合得分 | 20MA乖離 | 5日融資變動 | 吃貨比例 | 籌碼屬性 | 核心評估因子 |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        
        for idx, r in enumerate(top_30_low_risk, 1):
            char_tag = "🚨 外資主導" if r["foreign_ratio"] >= 40 else "✅ 內資主導" if r["foreign_ratio"] <= 15 else "中等"
            margin_str = f"{r['margin_diff_5d']:+.0f}張" if "ETF" not in r["margin_tag"] else r["margin_tag"]
            f.write(f"| {idx} | `{r['code']}` | **{r['name']}** | {r['market']}<br>{r['industry']} | {r['close']:.2f} | **{r['rank_score']:.1f}** | {r['bias_20']:+.1f}% | {margin_str} | {r['inst_ratio']:.1f}% | {char_tag} | 獲利因: {', '.join(r['p_reasons'][:2]) if r['p_reasons'] else '無'} <br> 風險因: {', '.join(r['r_reasons'][:2]) if r['r_reasons'] else '安全'} |\n")
            
        if extra_targets_low_risk:
            f.write("\n### 🎯 已持有/觀測標的之評估對照 (強制納入)\n\n")
            f.write("| 股號 | 股名 | 市場/類股 | 最新收盤 | 綜合得分 | 20MA乖離 | 5日融資變動 | 吃貨比例 | 籌碼屬性 | 核心評估因子 |\n")
            f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
            for r in extra_targets_low_risk:
                char_tag = "🚨 外資主導" if r["foreign_ratio"] >= 40 else "✅ 內資主導" if r["foreign_ratio"] <= 15 else "中等"
                margin_str = f"{r['margin_diff_5d']:+.0f}張" if "ETF" not in r["margin_tag"] else r["margin_tag"]
                f.write(f"| `{r['code']}` | **{r['name']}** | {r['market']}<br>{r['industry']} | {r['close']:.2f} | **{r['rank_score']:.1f}** | {r['bias_20']:+.1f}% | {margin_str} | {r['inst_ratio']:.1f}% | {char_tag} | 獲利因: {', '.join(r['p_reasons'][:2]) if r['p_reasons'] else '無'} <br> 風險因: {', '.join(r['r_reasons'][:2]) if r['r_reasons'] else '安全'} |\n")

        f.write("\n\n## 💡 前 5 名潛力股深度解析與建議交易對策\n\n")
        for idx, r in enumerate(top_30_low_risk[:5], 1):
            f.write(f"### {idx}. `{r['code']}` {r['name']} (綜合得分: **{r['rank_score']:.1f}**)\n")
            f.write(f"* **市場類股**: {r['market']} / {r['industry']}\n")
            f.write(f"* **主要業務**: {r['business']}\n")
            f.write(f"* **20MA 乖離率**: **{r['bias_20']:+.2f}%** | **5MA 週線乖離率**: **{r['bias_5']:+.2f}%**\n")
            f.write(f"* **外資持股比**: {r['foreign_ratio']:.2f}% ({'🚨 外資主導' if r['foreign_ratio']>=40 else '✅ 內資主導' if r['foreign_ratio']<=15 else '中等'})\n")
            f.write(f"* **5日法人吃貨比**: **{r['inst_ratio']:.1f}%** (5日大買 **{r['inst_buy_5d']:.0f}** 張)\n")
            f.write(f"* **5日融資變動**: **{r['margin_diff_5d']:+.0f}** 張 (屬性: **{r['margin_tag']}**)\n")
            f.write(f"* **利多支撐**: {', '.join(r['p_reasons']) if r['p_reasons'] else '暫無'}\n")
            f.write(f"* **風險警告**: {', '.join(r['r_reasons']) if r['r_reasons'] else '安全無虞'}\n")
            
            # 策略
            strategy_parts = []
            if r['bias_5'] > 5.0:
                strategy_parts.append(f"⚠️ 股價偏離週線已達 {r['bias_5']:.1f}%，短線防守空間大，切勿追高。")
            else:
                strategy_parts.append("🟢 目前偏離週線尚在合理區間，具備低乖離安全優勢。")
            if r['bias_20'] > 12.0:
                strategy_parts.append(f"且月線乖離率偏大（{r['bias_20']:.1f}%），建議拉回踩 5MA 或 10MA 再行佈局。")
            else:
                strategy_parts.append("若盤中拉回踩 5MA 附近可分批建立基本持股。")
            f.write(f"* **💡 AI 建議進場點與防守對策**: {''.join(strategy_parts)}\n\n")
            f.write("--- \n\n")

    # ---------------- B3. 高動能選股報告 ----------------
    momentum_results = []
    for r in results:
        m_score = 0.0
        m_reasons = []
        
        is_aligned = r["ma_alignment"] == "多頭排列" or r["ma_alignment"] == "🟢 多頭排列"
        if is_aligned:
            m_score += 30
            m_reasons.append("均線完美多頭排列")
        else:
            if r["code"] not in target_codes:
                continue
            m_reasons.append("均線非多頭排列")
            
        if r["consecutive_buy"] >= 7:
            m_score += 25
            m_reasons.append(f"法人狂買連{r['consecutive_buy']}天")
        elif r["consecutive_buy"] >= 5:
            m_score += 20
            m_reasons.append(f"法人連買{r['consecutive_buy']}天")
        elif r["consecutive_buy"] >= 3:
            m_score += 10
            m_reasons.append(f"法人連買{r['consecutive_buy']}天")
            
        if r["vol_surge"] >= 3.0:
            m_score += 20
            m_reasons.append(f"5日爆量{r['vol_surge']:.1f}倍")
        elif r["vol_surge"] >= 2.0:
            m_score += 15
            m_reasons.append(f"5日放量{r['vol_surge']:.1f}倍")
        elif r["vol_surge"] >= 1.5:
            m_score += 10
            m_reasons.append(f"5日溫和放量{r['vol_surge']:.1f}倍")
            
        if r["inst_ratio"] >= 50.0:
            m_score += 15
            m_reasons.append(f"法人瘋狂吸籌{r['inst_ratio']:.0f}%")
        elif r["inst_ratio"] >= 15.0:
            m_score += 10
            m_reasons.append(f"法人大買{r['inst_ratio']:.0f}%")
            
        if r["k_val"] > 60 and r["k_val"] > r["d_val"]:
            m_score += 10
            m_reasons.append(f"KD強勢(K:{r['k_val']:.0f}>D:{r['d_val']:.0f})")
            
        if r["bias_20"] >= 5.0:
            m_score += 5
            m_reasons.append(f"月線正乖離{r['bias_20']:+.1f}%")
            
        if r["bias_20"] > 25.0:
            m_score -= 20
            m_reasons.append(f"🔴 超高乖離{r['bias_20']:+.1f}%")
        elif r["bias_20"] > 15.0:
            m_score -= 10
            m_reasons.append(f"⚠️ 高乖離{r['bias_20']:+.1f}%")
            
        if r["margin_tag"] == "散戶過熱":
            m_score -= 15
            m_reasons.append("🔴 融資過熱")
            
        momentum_results.append({
            **r,
            "m_score": m_score,
            "m_reasons": m_reasons
        })
        
    momentum_results.sort(key=lambda x: x["m_score"], reverse=True)
    top_30_momentum = momentum_results[:30]
    top_30_m_codes = {x["code"] for x in top_30_momentum}
    extra_targets_momentum = [x for x in momentum_results if x["code"] in target_codes and x["code"] not in top_30_m_codes]
    
    report_momentum = os.path.join(WORKSPACE, "reports", "latest", "market_screener_momentum.md")
    with open(report_momentum, 'w', encoding='utf-8') as f:
        f.write("# 🚀 全市場量化選股排行榜 - 強勢動能型 (Momentum Ranking)\n\n")
        f.write(f"分析基準日：{latest_date_str}  \n")
        f.write("篩選標準：**均線多頭排列** 為門檻，依法人連買、爆量比、吃貨比、KD動能加權  \n")
        f.write("*(評分已排除非前20%強勢產業類股、20日均量 < 300張、收盤價 < 10元、及低於 60MA 季線之標的；持股/自選目標強制保留對照)*  \n\n")
        
        f.write("### 🏆 強勢動能評估前 30 名標的\n\n")
        f.write("| 排名 | 股號 | 股名 | 市場/類股 | 最新收盤 | 動能得分 | 20MA乖離 | 爆量比 | 連買天數 | 吃貨比 | 動能因子 |\n")
        f.write("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        
        for idx, r in enumerate(top_30_momentum, 1):
            f.write(f"| {idx} | `{r['code']}` | **{r['name']}** | {r['market']}<br>{r['industry']} | {r['close']:.2f} | **{r['m_score']:.0f}** | {r['bias_20']:+.1f}% | {r['vol_surge']:.1f}x | {r['consecutive_buy']}天 | {r['inst_ratio']:.1f}% | {', '.join(r['m_reasons'][:3])} |\n")
            
        if extra_targets_momentum:
            f.write("\n### 🎯 已持有/觀測標的之評估對照 (強制納入)\n\n")
            f.write("| 股號 | 股名 | 市場/類股 | 最新收盤 | 動能得分 | 20MA乖離 | 爆量比 | 連買天數 | 吃貨比 | 動能因子 |\n")
            f.write("| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
            for r in extra_targets_momentum:
                f.write(f"| `{r['code']}` | **{r['name']}** | {r['market']}<br>{r['industry']} | {r['close']:.2f} | **{r['m_score']:.0f}** | {r['bias_20']:+.1f}% | {r['vol_surge']:.1f}x | {r['consecutive_buy']}天 | {r['inst_ratio']:.1f}% | {', '.join(r['m_reasons'][:3])} |\n")

        f.write("\n\n## 💡 前 5 名潛力股深度解析與建議交易對策\n\n")
        for idx, r in enumerate(top_30_momentum[:5], 1):
            f.write(f"### {idx}. `{r['code']}` {r['name']} (動能得分: **{r['m_score']:.0f}**)\n")
            f.write(f"* **市場類股**: {r['market']} / {r['industry']}\n")
            f.write(f"* **主要業務**: {r['business']}\n")
            f.write(f"* **20MA 乖離率**: **{r['bias_20']:+.2f}%** | **5MA 週線乖離率**: **{r['bias_5']:+.2f}%**\n")
            f.write(f"* **外資持股比**: {r['foreign_ratio']:.2f}% ({'🚨 外資主導' if r['foreign_ratio']>=40 else '✅ 內資主導' if r['foreign_ratio']<=15 else '中等'})\n")
            f.write(f"* **5日法人吃貨比**: **{r['inst_ratio']:.1f}%** (5日大買 **{r['inst_buy_5d']:.0f}** 張)\n")
            f.write(f"* **5日融資變動**: **{r['margin_diff_5d']:+.0f}** 張 (屬性: **{r['margin_tag']}**)\n")
            f.write(f"* **動能因子**: {', '.join(r['m_reasons'])}\n")
            
            # 策略
            strategy_parts = []
            if r['bias_5'] > 5.0:
                strategy_parts.append(f"⚠️ 股價已在主升段，且偏離 5MA 週線達 {r['bias_5']:.1f}%，請勿盲目追高。")
            else:
                strategy_parts.append("🟢 目前偏離週線尚在合理區間。")
            strategy_parts.append(f"建議順勢操作，防守停利線設定為：**收盤跌破 5MA ({r['close'] * (1 - r['bias_5']/100):.2f} 元)**，破則波段了結。")
            f.write(f"* **💡 AI 建議進場點與防守對策**: {''.join(strategy_parts)}\n\n")
            f.write("--- \n\n")

    # ---------------- 複製歷史備份 ----------------
    date_compact = latest_date_str.replace("-", "")
    shutil.copy(report_low_risk, os.path.join(WORKSPACE, "reports", "history", f"market_screener_low_risk_{date_compact}.md"))
    shutil.copy(report_momentum, os.path.join(WORKSPACE, "reports", "history", f"market_screener_momentum_{date_compact}.md"))
    
    print(f"低危高利選股報告已生成於: reports/latest/market_screener_low_risk.md")
    print(f"強勢動能選股報告已生成於: reports/latest/market_screener_momentum.md")
    return results

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        dates = get_latest_trading_dates(90)
        print("解析最近 90 個交易日:", dates)
        download_market_data(dates)
        profiles = load_company_profiles()
        results = run_screener(dates, profiles, write_reports=True)
        
        # 一鍵聯動：自動調用個人持倉與觀測深度診斷分析，以及社群標的量化評估！
        today_str = dates[-1].replace("-", "")
        
        print("\n正在一鍵生成個人持倉與觀測股深度整合報告...")
        import analyze_portfolio_deep
        analyze_portfolio_deep.generate_integrated_report(results, today_str)
        
        print("\n正在一鍵生成社群收集標的量化評估報告...")
        import analyze_social_picks
        analyze_social_picks.generate_social_report(results, today_str)
        
    except Exception as e:
        print("執行出錯:", e)
