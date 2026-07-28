# 業績整合：怎麼運作、怎麼設定

三個平台（蝦皮／momo／官網）的每日業績與廣告數字，從 Google Sheet 自動同步進 repo，
再由 `sales.html` 提供依日期區間的查詢與分析。

```
三份 Google Sheet
      │  scripts/sync_sales.py（每天 10:00 由 GitHub Action 執行）
      ▼
  sales-data.json        ← 標準化後的「每日 × 平台」扁平資料
      │  瀏覽器 fetch
      ▼
   sales.html            ← 日期區間查詢 / 平台佔比 / 趨勢 / 檔期成效 / 匯出 CSV
```

---

## 一、首次設定（大約 15 分鐘）

### 步驟 1：把三份 Sheet 開成「知道連結的人可檢視」

每份 Sheet → 右上「共用」→ 一般存取權 → **知道連結的任何人** → **檢視者**。

GitHub Action 是以匿名身分抓 CSV 匯出檔，沒開這個權限會拿到登入頁而失敗。
若公司政策不允許，見下方「用服務帳號取代公開連結」。

### 步驟 2：確認欄位對應

在 GitHub 上開 **Actions → Sync sales data → Run workflow**，把 `inspect` 勾起來執行。
（或在本機跑 `python3 scripts/sync_sales.py --inspect`。）

Log 會印出每份表的實際欄名，以及腳本自動猜到的對應，像這樣：

```
來源 sheet_a（待確認（表一））
  表格大小：214 列 × 9 欄
  第 1 列欄名：
    [ 0] 日期
    [ 1] 通路
    [ 2] 銷售額
    [ 3] 訂單筆數
    [ 4] 廣告花費
    [ 5] 廣告轉換金額
  欄位對應（None = 沒對到，需手動指定）：
    date       -> [0] 日期
    platform   -> [1] 通路
    revenue    -> [2] 銷售額
    orders     -> [3] 訂單筆數
    adSpend    -> [4] 廣告花費
    adRevenue  -> [5] 廣告轉換金額
```

### 步驟 3：修正 `scripts/sales-sources.json`

只有猜錯或顯示 `None` 的才需要處理：

- **欄位猜錯** → 把正確欄名字串填進 `columns` 對應的鍵。
- **`platform` 是 None** → 代表這份表沒有「平台」欄，也就是整份表只屬於一個平台。
  把該來源的 `"platform": "auto"` 改成 `"shopee"` / `"momo"` / `"web"`。
- **標題不在第 1 列** → 改 `headerRow`。
- 順手把 `label` 改成看得懂的名字（例如「蝦皮每日業績」）。

範例：

```json
{
  "id": "sheet_a",
  "label": "蝦皮每日業績",
  "sheetId": "1lPHq6...",
  "gid": "1695466955",
  "platform": "shopee",
  "headerRow": 2,
  "columns": {
    "date": "統計日期",
    "platform": null,
    "revenue": "實付金額",
    "orders": "有效訂單",
    "adSpend": "廣告花費",
    "adRevenue": "廣告直接成交金額"
  }
}
```

### 步驟 4：正式跑一次

Actions → Sync sales data → Run workflow（**不要**勾 inspect）。
成功後 `sales-data.json` 的 `isDemo` 會變成 `false`，示範資料被真實資料整批取代，
`sales.html` 上方的黃色警告橫幅也會消失。

之後每天 10:00 自動跑，有變動才 commit。

### 步驟 5：補上活動檔期

檔期是手動維護的，直接編輯 `sales-data.json` 的 `campaigns`：

```json
{ "id": "s1111", "label": "蝦皮雙 11", "from": "2026-11-01", "to": "2026-11-11",
  "platforms": ["shopee"] }
```

`platforms` 留空陣列或省略 = 全平台檔期。加進去之後，趨勢圖會標出底色，
「活動檔期成效」區塊會自動算拉抬倍數。

---

## 二、`sales-data.json` 資料結構

```jsonc
{
  "isDemo": false,              // true = 目前是示範資料，頁面會顯示警告橫幅
  "updatedAt": "2026-07-28",
  "currency": "TWD",
  "platforms": [ { "id": "shopee", "label": "蝦皮", "accent": "brass" }, ... ],
  "campaigns": [ { "id", "label", "from", "to", "platforms": [] }, ... ],
  "daily": [
    { "date": "2026-07-01", "platform": "shopee",
      "revenue": 42300,        // 營業額
      "orders": 37,            // 有效訂單數
      "adSpend": 5920,         // 廣告花費
      "adRevenue": 24800 }     // 廣告直接帶來的營收（算 ROAS 用）
  ]
}
```

`daily` 以 **date + platform** 為唯一鍵。同步採 upsert：同一天同一平台重跑會覆蓋，
不會重複累加，所以隨時可以安全地重跑補資料。

**三個平台的口徑要一致**，否則佔比會失真。建議統一為：

| 欄位 | 建議口徑 |
|---|---|
| `revenue` | 含稅實收金額，已扣退貨與取消 |
| `orders` | 有效訂單數（不含取消） |
| `adSpend` | 該平台站內廣告花費；官網若跑 Meta／Google 廣告也計入 |
| `adRevenue` | 廣告歸因營收（各平台後台的「廣告成效／轉換金額」） |

口徑若真的無法一致，至少要固定不變，這樣「趨勢」和「檔期拉抬」仍然可信，
只有「跨平台佔比」需要打折看。

---

## 三、本機預覽

不能直接雙擊 `sales.html`（瀏覽器會擋本地 fetch）。在 repo 根目錄執行：

```bash
python3 -m http.server 8000
```

然後開 <http://localhost:8000/sales.html>。

---

## 四、頁面上的數字怎麼算

| 指標 | 算法 |
|---|---|
| 平均客單價 | 期間營業額 ÷ 期間訂單數 |
| ROAS | 期間廣告營收 ÷ 期間廣告花費 |
| 廣告佔營收 | 期間廣告花費 ÷ 期間營業額 |
| vs 前期 | 對照「緊鄰在前、同樣天數」的區間（選 7/1–7/31 就對照 6/1–6/30） |
| 檔期拉抬倍數 | 檔期日均營收 ÷ 檔期前 14 天日均營收，已排除與其他檔期重疊的日子 |
| 檔期增額營收 | (檔期日均 − 基準日均) × 檔期天數 |

「vs 前期」只比較同樣長度的區間，所以選任意天數都不會失真。

---

## 五、用服務帳號取代公開連結（選用）

若不能把 Sheet 設為公開連結：

1. 在 Google Cloud 建立服務帳號，啟用 Google Sheets API，下載 JSON 金鑰。
2. 把服務帳號的 email 加入三份 Sheet 的共用清單（檢視者即可）。
3. 金鑰整包存成 GitHub Secret `GSHEET_SA_KEY`。
4. `sync_sales.py` 的 `fetch_csv()` 改用 Sheets API `values.get` 取代 CSV 匯出網址，
   workflow 加上 `env: GSHEET_SA_KEY: ${{ secrets.GSHEET_SA_KEY }}`。

其餘流程完全不變 —— 解析、合併、渲染都不受影響。

---

## 六、常見狀況

**同步失敗說拿到登入頁** → 步驟 1 的共用權限沒開，或 `sheetId`／`gid` 抄錯。

**某個平台整個沒資料** → 多半是 `platform` 設成 `auto` 但該表的通路欄寫法不在
`sync_sales.py` 的 `PLATFORM_ALIASES` 裡。把寫法加進去，或改成固定平台。

**日期整批被略過** → 日期欄格式特殊。腳本支援 `2026-07-28`、`2026/7/28`、`2026年7月28日`、
民國 `115/07/28`、純月日 `7/28`、以及 Sheets 序列數字。都不是的話請統一格式。

**一個來源失敗時會怎樣** → 整次同步中止且不寫檔，避免留下只有部分平台的資料而讓佔比失真。
