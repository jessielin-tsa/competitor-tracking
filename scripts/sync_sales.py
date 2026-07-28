#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把三份 Google Sheet 的每日業績／廣告數字，同步成 sales-data.json。

用法：
    python3 scripts/sync_sales.py --inspect     # 只印出各表欄名與自動偵測結果，不寫檔
    python3 scripts/sync_sales.py               # 實際同步並更新 sales-data.json
    python3 scripts/sync_sales.py --dry-run     # 完整跑一遍並印出摘要，但不寫檔

只用標準函式庫，不需要 pip install。
"""

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(ROOT, "scripts", "sales-sources.json")
DATA_PATH = os.path.join(ROOT, "sales-data.json")

FIELDS = ["date", "platform", "revenue", "orders", "adSpend", "adRevenue"]

FIELD_LABELS = {
    "date": "日期", "platform": "平台", "revenue": "營業額",
    "orders": "訂單數", "adSpend": "廣告花費", "adRevenue": "廣告營收",
}
REQUIRED_FIELDS = ("date", "revenue")

# GitHub Actions 會把寫進這個檔案的 Markdown 直接渲染在 workflow 執行頁上，
# 這樣看欄位對應就不必翻 log。
SUMMARY_PATH = os.environ.get("GITHUB_STEP_SUMMARY")


def emit_summary(md):
    if not SUMMARY_PATH:
        return
    try:
        with open(SUMMARY_PATH, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    except OSError:
        pass  # 摘要寫不出來不該讓同步失敗

# 自動偵測欄名用的候選字（全部轉小寫、去空白後做「包含」比對，順序即優先序）
CANDIDATES = {
    "date": ["日期", "統計日期", "訂單日期", "成立日期", "date", "day", "時間"],
    "platform": ["平台", "通路", "渠道", "channel", "platform", "來源"],
    "revenue": [
        "營業額", "銷售額", "營收", "業績", "成交金額", "訂單金額", "銷售金額",
        "實付金額", "實收金額", "gmv", "revenue", "sales", "金額",
    ],
    "orders": [
        "訂單數", "訂單筆數", "成交筆數", "訂單量", "有效訂單", "筆數", "單量",
        "orders", "order", "transactions", "訂單",
    ],
    "adSpend": [
        "廣告花費", "廣告費用", "廣告成本", "廣告費", "花費", "消耗",
        "adspend", "ad spend", "cost", "spend",
    ],
    "adRevenue": [
        "廣告營收", "廣告銷售額", "廣告收入", "廣告成效", "轉換金額",
        "直接成交金額", "conversion value", "adrevenue", "ad revenue", "conv value",
    ],
}

PLATFORM_ALIASES = {
    "shopee": ["蝦皮", "shopee", "蝦"],
    "momo": ["momo", "富邦媒", "摩天商城", "魔魔"],
    "web": ["官網", "官方網站", "自有官網", "品牌官網", "web", "website",
             "shopify", "cyberbiz", "waca", "91app", "easystore", "官方商城"],
}


# --------------------------------------------------------------------------
# 讀取
# --------------------------------------------------------------------------
def fetch_csv(sheet_id, gid):
    url = ("https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=%s"
           % (sheet_id, gid))
    req = urllib.request.Request(url, headers={"User-Agent": "sales-sync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            "讀取失敗 HTTP %s。多半是這份 Sheet 沒有開「知道連結的人皆可檢視」。\n  %s"
            % (e.code, url))
    except urllib.error.URLError as e:
        raise RuntimeError("連線失敗：%s\n  %s" % (e.reason, url))

    text = raw.decode("utf-8-sig", errors="replace")
    # Google 未授權時會導向登入頁，回傳 HTML 而不是 CSV
    if "accounts.google.com" in final_url or text.lstrip()[:15].lower().startswith("<!doctype html"):
        raise RuntimeError(
            "拿到的是 Google 登入頁而不是 CSV。請把這份 Sheet 設為\n"
            "  「共用 → 一般存取權 → 知道連結的任何人 → 檢視者」\n  %s" % url)
    return list(csv.reader(io.StringIO(text)))


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
def norm(s):
    return re.sub(r"[\s　_\-()（）%]", "", str(s or "")).strip().lower()


# 「廣告」類欄位只能對應到 adSpend / adRevenue。少了這道防線，
# 「廣告直接成交金額」會被 revenue 的候選字「成交金額」搶走，整份表的營收就錯位了。
AD_MARKERS = ("廣告", "advert", "adspend", "adrevenue", "ads")
NON_AD_FIELDS = ("date", "platform", "revenue", "orders")


def _score(field, nheader_cell):
    """欄名與某個欄位的契合度；0 = 不匹配。完全相符優先，其次比對到的字串越長越優先。"""
    if not nheader_cell:
        return 0
    if field in NON_AD_FIELDS and any(m in nheader_cell for m in AD_MARKERS):
        return 0
    best = 0
    for cand in CANDIDATES[field]:
        nc = norm(cand)
        if not nc:
            continue
        if nheader_cell == nc:
            best = max(best, 1000 + len(nc))
        elif nc in nheader_cell:
            best = max(best, 500 + len(nc))
    return best


def detect_columns(header, explicit):
    """回傳 {field: column_index or None}，explicit 中已指定的欄名優先。"""
    nheader = [norm(h) for h in header]
    mapping = {}
    used = set()

    for field in FIELDS:
        want = (explicit or {}).get(field)
        if not want:
            continue
        nw = norm(want)
        idx = next((i for i, h in enumerate(nheader) if h == nw), None)
        if idx is None:
            idx = next((i for i, h in enumerate(nheader) if nw and nw in h), None)
        if idx is None:
            raise RuntimeError("找不到你指定的欄位 %r（欄名有：%s）"
                               % (want, "、".join(h for h in header if str(h).strip())))
        mapping[field] = idx
        used.add(idx)

    # 全域貪婪配對：先配契合度最高的組合，避免欄位互搶
    pairs = []
    for field in FIELDS:
        if field in mapping:
            continue
        for i, h in enumerate(nheader):
            if i in used:
                continue
            s = _score(field, h)
            if s:
                pairs.append((s, field, i))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))

    for s, field, i in pairs:
        if field in mapping or i in used:
            continue
        mapping[field] = i
        used.add(i)

    for field in FIELDS:
        mapping.setdefault(field, None)
    return mapping


def parse_number(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in {"-", "—", "–", "N/A", "n/a", "#N/A", "null", "NULL"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in {"-", ".", "-."}:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


ROC_RE = re.compile(r"^(\d{2,3})[/\-.](\d{1,2})[/\-.](\d{1,2})$")


def parse_date(v, default_year=None):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None

    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe_date(y, mo, d)

    # 民國年 115/07/28
    m = ROC_RE.match(s)
    if m:
        y = int(m.group(1))
        if y < 1000:
            y += 1911
        return _safe_date(y, int(m.group(2)), int(m.group(3)))

    # 只有月/日
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})$", s)
    if m and default_year:
        return _safe_date(default_year, int(m.group(1)), int(m.group(2)))

    # Google Sheets 有時匯出成序列數字（1899-12-30 起算）
    n = parse_number(s)
    if n is not None and 20000 < n < 80000:
        base = datetime.date(1899, 12, 30)
        return (base + datetime.timedelta(days=int(n))).isoformat()
    return None


def _safe_date(y, mo, d):
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return None


def normalize_platform(v):
    n = norm(v)
    if not n:
        return None
    for pid, aliases in PLATFORM_ALIASES.items():
        for a in aliases:
            if norm(a) in n:
                return pid
    return None


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def read_source(src, inspect=False):
    rows = fetch_csv(src["sheetId"], src["gid"])
    hdr_idx = max(0, int(src.get("headerRow", 1)) - 1)
    if hdr_idx >= len(rows):
        raise RuntimeError("headerRow=%s 超出這份表的列數（共 %d 列）"
                           % (src.get("headerRow"), len(rows)))
    header = rows[hdr_idx]
    body = rows[hdr_idx + 1 + int(src.get("skipRowsAfterHeader", 0)):]
    mapping = detect_columns(header, src.get("columns"))

    if inspect:
        print("\n" + "=" * 72)
        print("來源 %s（%s）" % (src["id"], src.get("label", "")))
        print("  https://docs.google.com/spreadsheets/d/%s/edit?gid=%s"
              % (src["sheetId"], src["gid"]))
        print("  表格大小：%d 列 × %d 欄" % (len(rows), len(header)))
        print("  第 %d 列欄名：" % (hdr_idx + 1))
        for i, h in enumerate(header):
            if str(h).strip():
                print("    [%2d] %s" % (i, h))
        print("  欄位對應（None = 沒對到，需在 sales-sources.json 手動指定）：")
        for f in FIELDS:
            i = mapping.get(f)
            hit = header[i] if i is not None and i < len(header) else None
            print("    %-10s -> %s" % (f, ("[%d] %s" % (i, hit)) if i is not None else "None"))
        print("  前 3 筆資料列：")
        for r in body[:3]:
            print("    %s" % (r[:12],))

    for f in REQUIRED_FIELDS:
        if mapping.get(f) is None:
            raise RuntimeError(
                "[%s] 找不到%s欄，請在 sales-sources.json 的 columns.%s 填入正確欄名。\n"
                "  這份表的欄名有：%s"
                % (src["id"], FIELD_LABELS[f], f,
                   "、".join(str(x).strip() for x in header if str(x).strip())))

    fixed_platform = src.get("platform", "auto")
    if fixed_platform != "auto":
        if fixed_platform not in PLATFORM_ALIASES:
            raise RuntimeError("[%s] platform 只能是 auto / %s"
                               % (src["id"], " / ".join(PLATFORM_ALIASES)))
    elif mapping.get("platform") is None:
        raise RuntimeError(
            "[%s] platform 設為 auto 但表中找不到「平台／通路」欄。\n"
            "  → 若這份表整份只有一個平台，把 platform 改成 shopee / momo / web。" % src["id"])

    default_year = datetime.date.today().year
    out, skipped = [], 0

    def cell(r, field):
        i = mapping.get(field)
        return r[i] if i is not None and i < len(r) else None

    for r in body:
        if not any(str(c).strip() for c in r):
            continue
        date = parse_date(cell(r, "date"), default_year)
        if not date:
            skipped += 1
            continue
        pid = fixed_platform if fixed_platform != "auto" else normalize_platform(cell(r, "platform"))
        if not pid:
            skipped += 1
            continue
        rec = {"date": date, "platform": pid}
        for f in ("revenue", "orders", "adSpend", "adRevenue"):
            n = parse_number(cell(r, f))
            rec[f] = int(round(n)) if n is not None else 0
        if rec["revenue"] == 0 and rec["orders"] == 0 and rec["adSpend"] == 0:
            skipped += 1
            continue
        out.append(rec)

    return {"rows": out, "skipped": skipped, "mapping": mapping,
            "header": header, "fixedPlatform": fixed_platform}


def merge(existing, incoming):
    """以 date+platform 為鍵 upsert，回傳 (合併結果, 新增數, 更新數)。"""
    idx = {(r["date"], r["platform"]): r for r in existing}
    added = updated = 0
    for r in incoming:
        k = (r["date"], r["platform"])
        if k in idx:
            if idx[k] != r:
                idx[k].update(r)
                updated += 1
        else:
            idx[k] = r
            added += 1
    merged = sorted(idx.values(), key=lambda r: (r["date"], r["platform"]))
    return merged, added, updated


def _mapping_table(res):
    """把欄位偵測結果排成 Markdown 表格，給 GitHub Actions 摘要頁用。"""
    header, mapping = res["header"], res["mapping"]
    lines = ["| 欄位 | 對應到的欄名 | 狀態 |", "|---|---|---|"]
    for f in FIELDS:
        i = mapping.get(f)
        if i is not None and i < len(header):
            cell, state = "`%s`（第 %d 欄）" % (str(header[i]).strip(), i + 1), "✅"
        elif f == "platform" and res["fixedPlatform"] != "auto":
            cell, state = "整份表固定為 `%s`" % res["fixedPlatform"], "✅"
        elif f in REQUIRED_FIELDS:
            cell, state = "—", "❌ 必填，請在設定檔指定欄名"
        else:
            cell, state = "—", "⚠️ 沒對到，這個指標會一律記為 0"
        lines.append("| %s `%s` | %s | %s |" % (FIELD_LABELS[f], f, cell, state))
    names = "、".join("`%s`" % str(h).strip() for h in header if str(h).strip())
    lines += ["", "<details><summary>這份表的全部欄名</summary>",
              "", names or "（沒有讀到任何欄名）", "", "</details>"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true",
                    help="只印出各表欄名與偵測結果，不寫檔")
    ap.add_argument("--dry-run", action="store_true",
                    help="完整解析並印出摘要，但不寫檔")
    args = ap.parse_args()

    with open(SOURCES_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    all_rows, errors = [], []
    emit_summary("## 業績同步報告 %s\n" % datetime.date.today().isoformat())

    for src in cfg["sources"]:
        sheet_url = ("https://docs.google.com/spreadsheets/d/%s/edit?gid=%s"
                     % (src["sheetId"], src["gid"]))
        title = "### %s（%s）" % (src["id"], src.get("label", "未命名"))
        try:
            res = read_source(src, inspect=args.inspect)
            all_rows.extend(res["rows"])
            print("[%s] 取得 %d 筆有效紀錄（略過 %d 列）"
                  % (src["id"], len(res["rows"]), res["skipped"]))
            emit_summary("%s\n\n[開啟這份 Sheet](%s)\n\n%s\n\n取得 **%d** 筆有效紀錄，略過 %d 列。\n"
                         % (title, sheet_url, _mapping_table(res), len(res["rows"]), res["skipped"]))
        except Exception as e:  # noqa: BLE001 - 逐來源回報，不讓一份表壞掉全炸
            errors.append((src["id"], str(e)))
            print("[%s] 失敗：%s" % (src["id"], e), file=sys.stderr)
            emit_summary("%s\n\n[開啟這份 Sheet](%s)\n\n> [!CAUTION]\n> **讀取失敗**\n>\n> ```\n> %s\n> ```\n"
                         % (title, sheet_url, str(e).replace("\n", "\n> ")))

    if args.inspect:
        print("\n--inspect 模式：未寫入任何檔案。")
        emit_summary("---\n\n**檢查模式**：只讀取欄名，沒有寫入任何資料。\n\n"
                     "上表若有 ❌ 或 ⚠️，請修改 `scripts/sales-sources.json` 後再跑一次。")
        return 1 if errors else 0

    if errors:
        print("\n有 %d 個來源失敗，為避免寫入不完整資料，本次不更新 sales-data.json。"
              % len(errors), file=sys.stderr)
        emit_summary("---\n\n> [!WARNING]\n> 有 %d 個來源讀取失敗，**本次未更新 sales-data.json**。\n>\n"
                     "> 只寫入部分平台會讓佔比失真，所以寧可整批不寫。" % len(errors))
        return 1
    if not all_rows:
        print("\n沒有解析到任何資料列，不更新 sales-data.json。", file=sys.stderr)
        emit_summary("---\n\n> [!WARNING]\n> 三份表都讀到了，但沒有解析出任何有效資料列，"
                     "**本次未更新 sales-data.json**。\n>\n"
                     "> 常見原因：日期欄格式不是腳本認得的寫法，或平台欄的寫法不在對照表裡。")
        return 1

    with open(DATA_PATH, encoding="utf-8") as f:
        doc = json.load(f)

    existing = [] if doc.get("isDemo") else list(doc.get("daily", []))
    if doc.get("isDemo"):
        print("\n偵測到目前是示範資料，將整批替換為真實資料。")

    merged, added, updated = merge(existing, all_rows)
    doc["daily"] = merged
    doc["isDemo"] = False
    doc["updatedAt"] = datetime.date.today().isoformat()

    dates = [r["date"] for r in merged]
    print("\n合計 %d 筆（新增 %d、更新 %d），涵蓋 %s → %s"
          % (len(merged), added, updated, min(dates), max(dates)))

    by_plat = {}
    for r in merged:
        by_plat[r["platform"]] = by_plat.get(r["platform"], 0) + r["revenue"]
    plat_lines = "\n".join("| %s | %s |" % (p, "{:,}".format(v)) for p, v in sorted(by_plat.items()))
    emit_summary("---\n\n### 同步結果\n\n"
                 "合計 **%d** 筆平台日紀錄（新增 %d、更新 %d），涵蓋 %s → %s。\n\n"
                 "| 平台 | 期間總營業額 |\n|---|---|\n%s\n"
                 % (len(merged), added, updated, min(dates), max(dates), plat_lines))

    if args.dry_run:
        print("--dry-run：未寫入 sales-data.json。")
        emit_summary("\n**試跑模式**：未寫入 sales-data.json。")
        return 0

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print("已寫入 %s" % DATA_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
