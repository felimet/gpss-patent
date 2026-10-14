# gpss-patent

供 AI Agent 使用的全球專利檢索工具，介接經濟部智慧財產局 GPSS API。唯讀 MCP server 加檢索流程 skill，同時封裝為 Claude Code 與 Codex 外掛。

[English](README.md)

狀態：規格已對照 TIPO 原始檔驗證；需有效 userCode 的實機成功回應尚未驗證（見[驗證](#驗證)）。Python ≥ 3.10、mcp ≥ 2.3、[uv](https://docs.astral.sh/uv/)。

## 這是什麼

GPSS（全球專利檢索系統）涵蓋 TW / US / JP / EP / KR / CN / WIPO / 東南亞 / 其他共 23 個資料庫，官方只提供 URL 式 REST API 與 PDF 文件。直接交給 LLM 會出現欄位代碼記錯、`+` / `-` 運算子前綴被百分比編碼、無效驗證碼重試導致 IP 被封、回傳量失控。本 server 把這些約束寫成結構化介面：

- 欄位與資料庫代碼為 schema enum，並與 TIPO 原始檔交叉比對。
- userCode 只讀環境變數，不出現在工具參數、日誌、回傳與錯誤訊息。
- 遇 `userCode not exist`、`expired`、`IP blocked` 即熔斷，同一 session 不再連網。
- 回傳正規化為精簡紀錄，摘要與請求項有字元預算。

## 結構

```
.
├── .claude-plugin/        Claude Code 外掛與 marketplace manifest
├── .codex-plugin/         Codex 外掛 manifest
├── .agents/plugins/       Codex marketplace manifest
├── .mcp.json              Claude Code MCP 啟動（userCode 來自敏感外掛選項）
├── .codex-mcp.json        Codex MCP 啟動（轉送 GPSS_USER_CODE）
├── skills/gpss-patent-search/SKILL.md   Agent 檢索流程與規則
├── server.py              MCP server（PEP 723 腳本，由 uv 執行）
├── scripts/fetch_sources.py   下載並以雜湊驗證 TIPO 原始文件
├── docs/SOURCES.md        來源版本、雜湊、來源間矛盾
├── test_server.py  test_packaging.py
└── .github/workflows/ci.yml
```

## 安裝

需要 GPSS userCode：GPSS → API → 使用說明 → 「API驗證碼線上申請」。

- 一個 Email 只能申請一組。申請日起 1~3 個工作天內審核完成，通過後於次個工作日寄到信箱。申請表顯示使用期限為申請日起一年；過期請按「API 驗證碼展期」，忘記請按「忘記 API 驗證碼」。
- GPSS 依政策禁止中港澳地區連線：請勿使用中港澳地區信箱申請，亦勿從中港澳地區 IP 連線。

### Claude Code

```bash
claude plugin marketplace add felimet/gpss-patent
claude plugin install gpss-patent@gpss-patent
```

Claude Code 2.1.275 以上可一步完成：`/plugin install gpss-patent --marketplace felimet/gpss-patent`。

接著開啟 `/plugin`，選 gpss-patent，填入 **GPSS userCode**。驗證碼存放於平台的安全憑證儲存區，並以 `GPSS_USER_CODE` 傳給 server。重啟 session。

### Codex

```bash
codex plugin marketplace add felimet/gpss-patent
codex plugin add gpss-patent@gpss-patent
```

啟動 Codex 前先設定環境變數。Codex 只轉送 MCP 項目在 `env_vars` 列出的變數，本外掛列出 `GPSS_USER_CODE`：

```powershell
setx GPSS_USER_CODE "<你的驗證碼>"     # Windows，之後重開終端機
```
```bash
export GPSS_USER_CODE="<你的驗證碼>"   # macOS / Linux
```

安裝後重啟 Codex。外掛與手動註冊擇一，不要並用。

### 其他 MCP host

```bash
GPSS_USER_CODE=<你的驗證碼> uv run /path/to/server.py     # stdio
```

升級：`claude plugin marketplace update gpss-patent` / `codex plugin marketplace upgrade gpss-patent`，再重裝或更新外掛。

## 工具

| Tool | 用途 |
|---|---|
| `gpss_reference` | 資料庫表（含無全文旗標）、欄位表、語法、配額、當前配額時段、已知限制 |
| `gpss_search` | `conditions[{field, query, op}]` + `databases` / `case_types` / `patent_types` / `output_fields` / `limit` / `skip` / `text_chars` / `raw` |

配額（來自 GPSS API 說明頁）：單次檢索上限 10,000 筆；上班時段（週一至五 08:00–18:00 台灣時間）每時段合計 10,000 筆，下班時段 30,000 筆。每次請求至少計 30 筆。請用小 `limit` 探路。

## 驗證

跑法：`python scripts/fetch_sources.py && uv run --with "mcp>=2.3,<3" --with pytest --with pypdf pytest -q`

來源交叉比對測試需要 TIPO 原始檔，而 `tiponet.tipo.gov.tw` 對 GitHub 託管的 runner（美國）回 HTTP 403，因此 CI 跳過這些測試，只跑邏輯與封裝測試；完整測試由維護者在台灣網路執行。文件載明的限制只有中港澳；美國 runner 被拒的原因沒有文件說明，API 端點本身（相對於文件下載）是否也拒絕未測試。`gpss_search` 遇 HTTP 403 會說明此情況。

| 項目 | 依據 | 方式 |
|---|---|---|
| 29 個檢索欄位 | `GPSS_OAS.json` | 測試：與 OAS 參數名集合相等 |
| 23 個資料庫代碼與無全文旗標 | `API_code.pdf` Table 1 | 測試：解析 PDF 文字層後逐筆相等 |
| 輸出欄位與檢索 / 輸出對照 | `API_code.pdf` Table 2 | 測試：集合相等 |
| URL 語法（`+` / `-` 前綴、日期區間） | `API_instructions.pdf` p.7 範例 | 測試：先確認範例字串確實存在於 PDF，再與 `build_url` 輸出比對 |
| 回傳欄位對應 | `Json_format.pdf` 範例 1 | 測試：文件衍生 fixture，含單筆省略陣列的變體 |
| 端點與錯誤包裝 | 2026-10-14 實測 | 無效碼 → HTTP 200 `{"status":"fail","message":"userCode not exist"}` |
| 流量限制、輸出數量範圍 | GPSS API 說明頁與網址工具頁 | 人工讀取，無法機器比對 |
| 封裝 | `test_packaging.py`、`claude plugin validate --strict` | 兩種外掛格式的版本、名稱、啟動路徑、環境變數接線一致 |
| 測試有效性 | 突變測試 | 6 種資料 / 邏輯破壞皆被測試擊殺 |

### 尚未驗證（需有效 userCode）

- 成功回應的真實 JSON 形狀（單筆是否省略陣列、數字是否為字串）。normalizer 兩種形態都容忍，`raw=true` 可取原始回應核對。
- 伺服器端對 `+` / `-` 參數名前綴的解析，以及混合 AND / OR / NOT 的優先順序（假設由左至右）。
- `expQty` 小於 30 的行為。server 一律送 `max(limit, 30)` 再於本地截取。
- 「單筆案號」配額的確切定義、假日是否算下班時段。
- API 端點（相對於文件下載）從台灣以外、且不在中港澳的網路是否可連線；中港澳已載明禁止。

### 來源間矛盾

見 [docs/SOURCES.md](docs/SOURCES.md)。最重要的一項：JPA / KPA / KPB 是否有全文，`API_code.pdf` 與 `API_instructions.pdf` 不一致，採較嚴格者（無全文）。

## 設計取捨

- 單檔 `urllib` 實作，不引入 httpx / requests：mcp 2.x 已不再附帶 httpx，且僅需一個 GET。排除方案：由 OAS 產生客戶端，因 OAS 缺 `keyValue` 且 `patent-title` 形狀與 PDF 矛盾。
- 僅輸出 JSON：XML 為同一資料，agent 不需選擇。
- `conditions` 為有序清單而非 29 個平面參數：OR / NOT 前綴依賴順序與組合。
- 不再散布 TIPO 的 PDF；`scripts/fetch_sources.py` 負責下載並以雜湊固定版本。

## 授權

Apache-2.0，見 [LICENSE](LICENSE)。GPSS 資料與 TIPO 文件屬經濟部智慧財產局；結果僅供參考，不作為任何審查或法律判斷之依據。
