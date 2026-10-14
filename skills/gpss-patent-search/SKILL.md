---
name: gpss-patent-search
description: 以經濟部智慧財產局 GPSS 全球專利檢索系統 API 檢索 TW/US/JP/EP/KR/CN/WO 等專利（先前技術調查、申請人 / 發明人 / 分類號檢索、取得摘要與請求項）。觸發詞：專利檢索、先前技術、prior art、patent search、GPSS、TIPO、智慧財產局、CPC/IPC 檢索、查某專利號。需 MCP server gpss-patent 與環境變數 GPSS_USER_CODE。
---

# GPSS 專利檢索

工具由 MCP server `gpss-patent` 提供：`gpss_reference`（代碼表、語法、配額，免費）與 `gpss_search`。資料僅含書目、摘要、請求項；無說明書、無法律狀態、無專利家族。

## 前置：userCode

- 缺少 `GPSS_USER_CODE` 時工具會回報錯誤且不連網。此時告知使用者：到 GPSS（https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpssbkm）→ API → 使用說明 → 「API驗證碼線上申請」；一個 Email 一組；過期用「API 驗證碼展期」，忘記用「忘記 API 驗證碼」。
- 申請後 1~3 個工作天審核，通過後於次個工作日寄到信箱；申請表顯示使用期限為申請日起一年。
- GPSS 依政策禁止中港澳地區連線：不可用中港澳地區信箱申請，也不可從中港澳地區 IP 連線。使用者在這些地區時，直接告知無法使用，不要重試。
- 取得後，Claude Code 在 `/plugin` 的 gpss-patent 設定中填入「GPSS userCode」；Codex 與其他 host 則在啟動前設定環境變數 `GPSS_USER_CODE`。請使用者自行設定，不要貼進對話。
- 收到 `userCode not exist` / `expired` / `IP blocked` 後停止呼叫並回報；無效驗證碼重試過多會被封 IP。
- 收到 `HTTP 403` 時停止並回報網路來源問題（中港澳被政策封鎖；GitHub 美國 runner 也曾被拒，原因未公開）。

## 流程

1. 首次使用先呼叫 `gpss_reference`，以其回傳的代碼表為準，不憑記憶填欄位。
2. 把技術概念拆成要素，每個要素列中英同義詞。分類號（`CS`/`IC`）與關鍵字並用：分類號跨語言穩定，關鍵字補足分類之外的細節。
3. 先用預設輸出欄位（PN, ID, AN, AD, TI）與小 `limit` 看 `total`。`total` 過大就加條件收斂（日期、資料庫、分類號），過小就放寬同義詞。
4. 對入圍專利，用 `PN` 條件加 `output_fields="all"` 取摘要與請求項；`text_chars` 控制長度。
5. 翻頁用回傳的 `next_skip`。

## 檢索式規則

- 同欄位內以 `and` / `or` / `not` 連接；跨欄位由 `op` 決定（AND、OR、NOT）。第一個條件必須是 AND；同一欄位不可出現兩次。
- 不支援截斷（萬用字元）與字距（鄰近）運算。要涵蓋詞形變化就列出各形式。
- 日期欄位 `ID`（公開/公告日）、`AD`（申請日）、`DR`（優先權日）：`YYYY`、`YYYYMM`、`YYYYMMDD`；區間 `A:B`，開放式 `A:`。
- 日、韓、東南亞、其他國家的公開案（JPA、KPA、KPB、SEAA、SEAB、OTA、OTB）無全文，`TI/AB/CL` 檢索可能漏檢；改用分類號、申請人、號碼檢索。
- JP/KR/CN 資料庫的 TI/AB/CL 比對原文或英文，文件未說明；兩種都試。

## 配額

單次檢索上限 10,000 筆；每次請求至少計 30 筆。上班時段（週一至五 08:00–18:00，台灣時間）全部檢索合計 10,000 筆，下班時段 30,000 筆。用小 `limit` 探路，別以 10,000 筆開局。`Over download quantity` 表示額度用盡，等下一時段。

## 回報

- 每筆引用附專利號、資料庫、公開/公告日、申請人，必要時附請求項編號。
- `no record found` 只代表在這組條件與涵蓋範圍內沒有命中，不等於沒有先前技術；不得據此下新穎性、進步性或 FTO 結論。
- 轉述結果時附上工具回傳的 disclaimer：資料僅供參考，不作為准駁之依據，以各國專利局公告為準。

## 無 MCP 時的退路

`GET https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api?userCode=<碼>&patDB=TWA,TWB&TI=太陽能&+AB=太陽能&-IC=H01L&ID=20150101:20160101&expFld=PN,ID,TI&expFmt=json&expQty=30&expSkip=0`

`+` 前綴 = OR，`-` 前綴 = NOT，參數名保持原樣不做百分比編碼，值需 UTF-8 百分比編碼。回應一律 HTTP 200，錯誤在 JSON 的 `gpss-API.status` / `message`。
