# gpss-patent

Global patent search for AI agents through the Taiwan IPO GPSS API. A read-only MCP server plus a search-workflow skill, packaged for Claude Code and Codex.

[繁體中文](README-zhTW.md)

Status: the spec was verified against the original TIPO files; a successful live response needs a valid userCode and has not been verified yet (see [Verification](#verification)). Python ≥ 3.10, mcp ≥ 2.3, [uv](https://docs.astral.sh/uv/).

## What it is

GPSS (Global Patent Search System, 全球專利檢索系統) covers 23 databases across TW, US, JP, EP, KR, CN, WIPO, Southeast Asia and others, but offers only a URL-style REST API and PDF documents. Handing that to an LLM invites wrong field codes, a `+`/`-` operator prefix that gets percent-encoded, repeated invalid-userCode requests that get the IP blocked, and unbounded payloads. This server turns those constraints into a typed interface:

- Field and database codes are schema enums, cross-checked against TIPO's own files.
- The userCode is read from the environment only. It never appears in tool arguments, logs, results or error messages.
- `userCode not exist`, `expired` or `IP blocked` trips a circuit breaker: no further network calls that session.
- Results are normalised to compact records; abstracts and claims have a character budget.

## Layout

```
.
├── .claude-plugin/        Claude Code plugin + marketplace manifests
├── .codex-plugin/         Codex plugin manifest
├── .agents/plugins/       Codex marketplace manifest
├── .mcp.json              Claude Code MCP launch (userCode from a sensitive plugin option)
├── .codex-mcp.json        Codex MCP launch (forwards GPSS_USER_CODE)
├── skills/gpss-patent-search/SKILL.md   Agent search workflow and rules
├── server.py              MCP server (PEP 723 script, run by uv)
├── scripts/fetch_sources.py   Download + hash-check TIPO's original documents
├── docs/SOURCES.md        Source versions, hashes, inconsistencies between sources
├── test_server.py  test_packaging.py
└── .github/workflows/ci.yml
```

## Install

You need a GPSS userCode: GPSS → API → 使用說明 → 「API驗證碼線上申請」 (one Email = one code; expired → 「API 驗證碼展期」).

### Claude Code

```bash
claude plugin marketplace add felimet/gpss-patent
claude plugin install gpss-patent@gpss-patent
```

On Claude Code 2.1.275 or later, one step: `/plugin install gpss-patent --marketplace felimet/gpss-patent`.

Then open `/plugin`, select gpss-patent and fill in **GPSS userCode**. It is kept in the platform's secure credential store and passed to the server as `GPSS_USER_CODE`. Restart the session.

### Codex

```bash
codex plugin marketplace add felimet/gpss-patent
codex plugin add gpss-patent@gpss-patent
```

Export the code before starting Codex; Codex forwards only variables an MCP entry lists in `env_vars`, and this plugin lists `GPSS_USER_CODE`:

```powershell
setx GPSS_USER_CODE "<your-code>"     # Windows, then restart the terminal
```
```bash
export GPSS_USER_CODE="<your-code>"   # macOS / Linux
```

Restart Codex after installing. Use the plugin or a hand registration, not both.

### Any other MCP host

```bash
GPSS_USER_CODE=<your-code> uv run /path/to/server.py     # stdio
```

Upgrade: `claude plugin marketplace update gpss-patent` / `codex plugin marketplace upgrade gpss-patent`, then reinstall or update the plugin.

## Tools

| Tool | Purpose |
|---|---|
| `gpss_reference` | Database table (with full-text flags), field table, syntax, quotas, current quota period, known caveats |
| `gpss_search` | `conditions[{field, query, op}]` plus `databases`, `case_types`, `patent_types`, `output_fields`, `limit`, `skip`, `text_chars`, `raw` |

Quotas (from the GPSS API page): 10,000 records per search; work hours (Mon–Fri 08:00–18:00 Taipei) 10,000 records in total per period, off hours 30,000. A request counts at least 30 records. Probe with a small `limit`.

## Verification

Run: `python scripts/fetch_sources.py && uv run --with "mcp>=2.3,<3" --with pytest --with pypdf pytest -q`

The source cross-check tests need TIPO's files, and `tiponet.tipo.gov.tw` answered HTTP 403 to GitHub-hosted runners (US), so CI skips them and runs only the logic and packaging tests. Maintainers run the full suite from a Taiwan network. This also means the API itself may be unreachable from outside Taiwan; that was not tested (see below). `gpss_search` explains an HTTP 403 accordingly.

| Item | Source | How |
|---|---|---|
| 29 search fields | `GPSS_OAS.json` | test: equals the OAS parameter-name set |
| 23 database codes and no-full-text flags | `API_code.pdf` Table 1 | test: parsed from the PDF text layer, equal row by row |
| Output fields and search/output mapping | `API_code.pdf` Table 2 | test: set equality |
| URL grammar (`+`/`-` prefixes, date ranges) | `API_instructions.pdf` p.7 example | test: the example string is first confirmed to exist in the PDF, then compared with `build_url` output |
| Response field mapping | `Json_format.pdf` example 1 | test: document-derived fixture, plus a variant with single-item lists unwrapped |
| Endpoint and error envelope | live probe 2026-10-14 | invalid code → HTTP 200 `{"status":"fail","message":"userCode not exist"}` |
| Rate limits, output-quantity range | GPSS API page and URL-tool page | read by hand; not machine-comparable |
| Packaging | `test_packaging.py`, `claude plugin validate --strict` | versions, names, launch paths, env wiring agree across both plugin formats |
| Test effectiveness | mutation check | 6 data/logic breakages were each caught |

### Not yet verified (needs a valid userCode)

- The real success-response JSON shape (single items bare or in a list, numbers as strings). The normaliser accepts both; `raw=true` returns the untouched response for comparison.
- Server-side handling of the `+`/`-` parameter-name prefixes, and precedence of mixed AND/OR/NOT (assumed left to right).
- Behaviour of `expQty` below 30. The server always sends `max(limit, 30)` and slices locally.
- Exact meaning of the "single case number" quota, and whether holidays count as off hours.
- Whether the API endpoint (as opposed to the document downloads) is reachable from non-Taiwan IPs.

### Source inconsistencies

See [docs/SOURCES.md](docs/SOURCES.md). Most relevant: `API_code.pdf` and `API_instructions.pdf` disagree on whether JPA, KPA and KPB have full text; the stricter one (no full text) is used.

## Design notes

- Single-file `urllib` client, no httpx or requests: mcp 2.x no longer ships httpx and one GET is all that is needed. Rejected: generating a client from the OAS, which omits `keyValue` and contradicts the PDFs on `patent-title`.
- JSON only; XML carries the same data, so the agent does not need to choose.
- `conditions` is an ordered list rather than 29 flat parameters: the OR/NOT prefixes depend on order and combination.
- TIPO's PDFs are not redistributed; `scripts/fetch_sources.py` fetches and hash-pins them.

## License

Apache-2.0, see [LICENSE](LICENSE). GPSS data and the TIPO documents belong to the Taiwan Intellectual Property Office; results are for reference only and are not a basis for any examination or legal decision.
