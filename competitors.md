# 競品分析設定檔（Routine 每次執行必讀）

> 本檔案定義追蹤對象、資料結構與撰寫規則。新增/移除品類、競品、改網址都改這裡。

---

## 一、資料結構（兩個檔案）

資料拆成兩個檔，讓網頁只需載入最新一筆就能顯示，載入速度不隨歷史累積變慢，同時每次執行也不必把整包歷史讀進 context（省 token）：
- **tracking-data.json**：只放**最新一筆** snapshot → `{ "snapshots": [ {最新} ] }`（網頁優先載入、Routine 讀寫的對象）
- **tracking-history.json**：存放**所有較舊的** snapshot → `{ "snapshots": [ {舊}, {舊}, ... ] }`（網頁在背景載入，Routine 只追加、不需讀取）

每次執行時（**僅在產生新一筆完整 snapshot 時才做，每日查價只更新 price-history.json，不動這兩個檔**）：
1. 取得今天日期作為 `date`（YYYY-MM-DD），算出 `month`（YYYY-MM）
2. **先搬檔、再寫入（保留全部歷史，絕不覆蓋或刪除舊 snapshot）**：
   - 讀取最新一筆時只讀 tracking-data.json（別讀 history）；如需上一筆內容用 `jq '.snapshots[-1]' tracking-data.json`
   - 把 tracking-data.json 現有那筆 snapshot **搬進** tracking-history.json 陣列末端，再把本次新 snapshot 寫成 tracking-data.json 的唯一一筆。可用指令避免整包歷史進 context：
     ```
     jq '.snapshots += input.snapshots' tracking-history.json tracking-data.json > tmp && mv tmp tracking-history.json
     # 接著把本次新產生的 snapshot 寫入 tracking-data.json（只含這一筆）
     ```
3. 每筆 snapshot 結構如下：

```
{
  "date": "YYYY-MM-DD",
  "month": "YYYY-MM",
  "trendGroups": [
    { "id": "consumer",   "label": "消費者需求", "sub": "...", "items": [{title, summary, sources:[{name,url}]}] },
    { "id": "market",     "label": "市場現況",   "sub": "...", "items": [...] },
    { "id": "regulation", "label": "法規動態",   "sub": "...", "items": [...] }
  ],
  "brands": [
    {
      "id": "powerhero", "name": "PowerHero 勁漢英雄", "tagline": "男性運動保健", "accent": "brass",
      "categories": [ {品類物件，見下方} ],
      "recommendations": [ "建議1", ... ],
      "futureMarkets": [ {label, icon, overview, fit} ]
    }
  ]
}
```

品類物件結構：
```
{
  "id": "英文id", "label": "品類名", "icon": "emoji",
  "ownProduct": "我方在本品類的商品與規格描述",
  "competitors": [ {name, product, usp, price, priceBasis, channels, promo} ],
  "strengths": ["本品類優勢1", ...],
  "weaknesses": ["本品類劣勢1", ...],
  "log": [ {date, competitor, change, severity: high|medium|low} ]
}
```

---

## 二、trendGroups 撰寫規則

- 三塊各 **1-3 則**（上限3則），挑當期最重要的講，不要為湊數而編造
- **每一則都必須附真實來源**：在該則物件加 `sources: [{ "name": "來源名稱", "url": "https://..." }]`，url 必須是實際存在、可點開查證的網址（食藥署公告頁、評測文章、新聞連結等）。**查不到可查證的來源就不要寫這一則**，寧缺勿假（呼應第五節誠實原則）
- **消費者需求**：消費者行為、決策方式、溝通語言的變化（搜尋行為、評測依賴、劑量透明要求、時間承諾疲乏等）
- **市場現況**：產業事件、成分典範轉移、競爭格局變化、新品趨勢
- **法規動態**：查詢衛福部食藥署公告（fda.gov.tw）、違規裁罰新聞、廣告認定準則異動。若當期無新公告，可保留仍然有效的重要提醒，但需重新確認內容仍準確
- 若某週無新動態，可保留上期條目但必須重新驗證後才保留，不可無腦複製

---

## 三、品牌與品類追蹤清單

### 執行效率規則（重要）
- 讀取 tracking-data.json 時**只參考最後一筆 snapshot**，不要閱讀全部歷史
- 品類更新分兩級：
  - **每週更新**：男性戰力／精力、紅麴納豆Q10——每次執行都重新查證
  - **每月更新**：攝護腺、護髮養髮、futureMarkets——僅每月第一次執行時重新查證，其他週直接沿用上一筆 snapshot 的內容複製，不重新搜尋
- 每品類 log 最多保留 5 則當期紀錄

### 🟠 PowerHero 勁漢英雄（男性運動保健）
官網：https://www.powerhero.com.tw/

| 品類 | 我方商品 | 追蹤競品 |
|---|---|---|
| 男性戰力／精力 | L-精胺酸祕魯黑瑪卡膠囊(90顆/盒)、久倍戰力勁黑瑪卡粉包(14包/盒) | 大研生醫(精氣神瑪卡粉包)、九五之丹(至尊黑瑪卡)、嚴萃(威猛戰神)、武倍對策、UNIQMAN(紅瑪卡) |
| 攝護腺保健 | 水溶性專利南瓜籽+茄紅素 | 大研生醫(好攝力)、九五之丹(英雄南瓜籽)、UNIQMAN(南瓜籽油)、武倍十攝 |
| 紅麴納豆Q10 | 納豆紅麴Q10膠囊（mybest 2026 納豆紅麴評測第一名，已人工查證） | 大研生醫、悠活原力、豐傑生醫、葡萄王 |
| 護髮養髮 | 強健豐盈養髮液(Procapil®+瑪卡)、洗髮精、曜黑絲 | 落建、莯光Moonlight、艾瑪絲Aromase、生予、台鹽絲易康、呂Ryo |

定價比較基準：瑪卡膠囊以90顆/盒比、粉包以14-30包/盒為單位並註明；查不到明確價格寫「待確認」

### 查找規則
- 紅麴品類對標名單：大研生醫、悠活原力、豐傑生醫、葡萄王
- 每個品類查找重點：定價變動、新品/配方調整、評測排名變化、促銷檔期、通路異動、論壇口碑

---

## 四、recommendations（方向建議）撰寫規則

- 每品牌 3-6 條，每條需對應到某個具體劣勢或競品動作，不寫空泛套話
- 每期重新檢視，不可直接複製上期；若建議未變，需重新驗證依據仍成立
- 優先順序：已被評測點名的產品力差距 > 聲量/口碑缺口 > 定價與促銷 > 通路 > 認證背書

## 五、誠實原則（最重要）

- 查不到的資訊寫「待確認」或「本期無新動態」，**絕不編造數字、排名或評測結果**
- 評測引用需真實存在；聲量高低若為主觀判斷，需在文字中註明依據（如「Dcard討論篇數」）

---

## 維護紀錄

| 日期 | 變更 |
|---|---|
| 2026-07-05 | 全面改版：雙品牌架構（PowerHero+御熹堂）、品類制競品分析、趨勢三分組（消費者需求/市場現況/法規動態）、日期快照累積制 |
| 2026-07-15 | 省額度優化：趨勢每塊上限3則、品類分兩級更新頻率（主力每週/其他每月）、只讀最新snapshot、每日查價僅保留PowerHero瑪卡+御熹堂魚油且只查momo |
| 2026-07-27 | 資料拆檔（tracking-data.json只留最新一筆＋tracking-history.json存歷史，網頁背景載入）加快載入並省token；趨勢每則新增可查證來源欄位sources；前端加入HTML跳脫避免競品文案含特殊符號時炸版 |
| 2026-08-28 | 移除御熹堂品牌：改為 PowerHero 單品牌追蹤，刪除御熹堂全部品類（魚油/蔓越莓益生菌/UC-II葡萄糖胺/膠原蛋白/紅麴）與其每日查價品項；歷史 snapshot 中的御熹堂資料一併移除。註：既有趨勢紀錄與第三方榜單引用中提及「御熹堂」之處予以保留，因屬已註明來源的市場事實，竄改將違反第五節誠實原則 |
