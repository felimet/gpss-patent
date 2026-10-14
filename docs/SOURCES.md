# Source evidence

Retrieved 2026-10-14 from tiponet.tipo.gov.tw (base `https://tiponet.tipo.gov.tw/gpss1/gpsskm/API/`). The files are TIPO originals and are not committed here because their redistribution terms are not stated. `python scripts/fetch_sources.py` downloads them into `_src/` and verifies the hashes below (exit 1 = TIPO changed a document). `test_server.py` cross-checks `server.py` against `_src/` and skips those tests when it is absent. From GitHub-hosted runners (US) these downloads returned HTTP 403 on 2026-10-14, while the same URLs returned 200 from a Taiwan IP regardless of User-Agent, so the check is run locally. The documented restriction is mainland China, Hong Kong and Macau only (see below); the cause of the runner 403 is not documented.

| File | Version / content | Bytes | SHA-256 |
|---|---|---|---|
| `GPSS_OAS.json` | Swagger 2.0, v1.1. `GET /gpss1/gpsskmc/gpss_api`, 37 query params | 22160 | `19ba9c02d37b077e7faff06dce208380b3a78a89a17767f7c2990a997bee4e73` |
| `API_instructions.pdf` | v1.4 (2024/11/22), 11 pp. URL rules, +/- prefixes, defaults, error messages | 313897 | `ac60046ff14b1ac3a1aae77a857df1663a05ed7221b5efcb2f0f4f9ba2ed40ea` |
| `API_code.pdf` | Table 1 database codes (with 無全文 flags), Table 2 search/output field map | 165764 | `adf848d06099b207246c0b474d04ec835d56af86dcff9892159b23bc0cdaa864` |
| `Json_format.pdf` | JSON output layout + 2 examples | 350595 | `4c38235bda7183064a9d6cda2cfcbd88c7fa20375594a95bda8a9dd64c28f0ae` |
| `Xml_format.pdf` | XML output layout + example | 314367 | `0d68e25d1f8ddd0f228fe0dd8afa6b55c8451c9ee0327f584791adf07f87cf0b` |

Not in a file (read from the live pages with a browser, 2026-10-14):

- API usage page `.../gpssapi?ID=2&SECU=...&PAGE=api_info@@...`: rate limits, userCode application / extension / recovery, "one Email = one code", REST over HTTPS GET, `Content-Type: application/json` for JSON.
- API verification-code application form (`PAGE=apply_code`; text supplied by the user and confirmed identical on the live page 2026-10-14):
  - One Email = one code; renew with 「API 驗證碼展期」, recover with 「忘記 API 驗證碼」.
  - 「驗證碼將於申請日起1~3個工作天內審核完成，申請通過後將於次個工作日發送至您的信箱。」
  - 「目前配合政策禁止中港澳地區連線，如您有需要使用GPSS系統API服務，請勿使用中港澳地區信箱進行API驗證碼申請，亦勿使用中港澳地區IP進行連線。」
  - The form pre-fills 申請日期 20261014 and 使用期限 20271014 (application date + 1 year).
  - Required fields: 姓名, EMAIL, 身分別 (產業界 / 事務所/代理人 / 教育/研究單位 / 個人), 產業別.
- URL tool page (`PAGE=gpssapi`): output quantity "最少30筆，上限10,000筆"; page footer disclaimer.
- Live probe: `GET .../gpss_api?userCode=<invalid>&...&expFmt=json` returned HTTP 200, `application/json; charset=utf-8`, body `{"gpss-API":{"status":"fail","message":"userCode not exist"}}`.

## Known inconsistencies between the sources

| Item | A | B | Used |
|---|---|---|---|
| Full text of JPA / KPA / KPB | `API_code.pdf`: 無全文 | `API_instructions.pdf` p.4: no marker (only SEAA/SEAB/OTA/OTB) | A (stricter) |
| `patent-title` shape | OAS: array | `Json_format.pdf`: object | tolerate both |
| `agents` / `examiners` content | OAS: only `sequence` | `Json_format.pdf`: `keyValue` | `keyValue` (OAS is incomplete) |
| `qty-rec` | `Json_format.pdf` examples: 30 with `total-rec` 1 | n/a | not trusted; server counts `patentcontent` |
| `expQty` minimum | `API_instructions.pdf`: default 30, no minimum stated | URL tool UI: "最少30筆" | send max(limit, 30), slice client-side |
