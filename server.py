# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3"]
# ///
"""MCP server for the TIPO GPSS (Global Patent Search System) API.

Spec sources (retrieved 2026-10-14, hashes in _src/SOURCES.md):
  GPSS_OAS.json (Swagger 2.0 v1.1), API_instructions.pdf (v1.4, 2024/11/22),
  API_code.pdf, Json_format.pdf, Xml_format.pdf, and the GPSS API usage page
  (rate limits, userCode application).
Auth: userCode comes from env GPSS_USER_CODE only. It is never a tool argument,
never logged and never returned.
Run: uv run server.py   (stdio transport)
"""
# Must equal the plugin manifests' version; test_packaging.py enforces it.
VERSION = "0.1.0"

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from urllib.parse import quote

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

log = logging.getLogger("gpss")

BASE_URL = "https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api"
ENV_CODE = "GPSS_USER_CODE"
TIMEOUT_S = 60
MAX_BODY_BYTES = 50_000_000
QTY_MIN, QTY_MAX = 30, 10_000  # GPSS URL tool UI: "最少30筆，上限10,000筆"
DEFAULT_OUT = ("PN", "ID", "AN", "AD", "TI")  # API_instructions.pdf p.6
DISCLAIMER = "本系統資料僅供參考，不作為准駁之依據，所有資料以各國專利局或組織公告為準。"
TW = timezone(timedelta(hours=8))  # Taiwan has no DST

# code -> (country, kind, has_full_text, approx_start_year)
# full-text flag: API_code.pdf Table 1. start year: API_instructions.pdf p.4,
# which itself says "僅提供資料概況參考".
DATABASES: dict[str, tuple[str, str, bool, int]] = {
    "TWA": ("TW", "公開", True, 2003), "TWB": ("TW", "公告", True, 1950),
    "TWD": ("TW", "設計", True, 1964),
    "USA": ("US", "公開", True, 2001), "USB": ("US", "公告", True, 1790),
    "USD": ("US", "設計", True, 1976),
    "JPA": ("JP", "公開", False, 1971), "JPB": ("JP", "公告", True, 1913),
    "JPD": ("JP", "意匠", True, 2000),
    "EPA": ("EP", "公開", True, 1978), "EPB": ("EP", "公告", True, 1980),
    "EUIPO": ("EU", "設計", True, 2003),
    "KPA": ("KR", "公開", False, 1999), "KPB": ("KR", "公告", False, 1974),
    "KPD": ("KR", "設計", True, 1998),
    "CNA": ("CN", "公開", True, 1985), "CNB": ("CN", "公告", True, 1985),
    "CND": ("CN", "外觀設計", True, 1985),
    "WO": ("WIPO", "公開", True, 1978),
    "SEAA": ("SEA", "公開", False, 1953), "SEAB": ("SEA", "公告", False, 1975),
    "OTA": ("OTHER", "公開", False, 1782), "OTB": ("OTHER", "公告", False, 1827),
}

SEARCH_FIELDS = {
    "PN": "公開/公告號", "ID": "公開/公告日", "AN": "申請號", "AD": "申請日",
    "AX": "申請人名", "AF": "第一申請人名", "AY": "申請人國別", "AZ": "第一申請人國別",
    "IV": "發明人名", "IY": "發明人國別", "LX": "代理人名", "EX": "審查委員",
    "PR": "優先權", "DR": "優先權日", "IC": "IPC", "FC": "第一IPC",
    "CS": "CPC", "TS": "第一CPC", "IQ": "LOC", "FI": "FI", "FT": "F-TERM",
    "IR": "D-TERM", "UC": "USPC", "TI": "專利名稱", "AB": "摘要", "CL": "專利範圍",
    "CI": "引用專利", "TI/AB": "專利名稱/摘要", "TI/AB/CL": "專利名稱/摘要/專利範圍",
}
DATE_FIELDS = frozenset({"ID", "AD", "DR"})
OUTPUT_FIELDS = {
    "PN": "公開/公告號", "ID": "公開/公告日", "AN": "申請號", "AD": "申請日",
    "TI": "專利名稱", "PA": "申請人(含國別)", "IN": "發明人(含國別)", "LX": "代理人",
    "EX": "審查委員", "PR": "優先權", "AB": "摘要", "IC": "IPC", "IQ": "LOC",
    "CS": "CPC", "UC": "USPC", "FI": "FI", "FT": "F-TERM", "IR": "D-TERM",
    "CI": "引用專利", "CL": "專利範圍",
}

DbCode = Literal[tuple(DATABASES)]  # type: ignore[valid-type]
SearchField = Literal[tuple(SEARCH_FIELDS)]  # type: ignore[valid-type]
OutField = Literal[tuple(OUTPUT_FIELDS)]  # type: ignore[valid-type]

_D = r"\d{4}(?:(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])?)?"  # YYYY | YYYYMM | YYYYMMDD
_DATE_RE = re.compile(rf"^{_D}(?::(?:{_D})?)?$")
_OP_PREFIX = {"AND": "", "OR": "+", "NOT": "-"}  # API_instructions.pdf p.7

# (message substring lowercased, fatal, hint). Messages: API_instructions.pdf p.11.
_ERRORS = (
    ("usercode not exist", True, f"userCode invalid. Check env {ENV_CODE}; apply at GPSS > API > 使用說明 > API驗證碼線上申請."),
    ("usercode expired", True, "userCode expired. Extend it via GPSS API page 「API 驗證碼展期」."),
    ("ip blocked", True, "IP blocked after too many invalid-userCode requests. Stop retrying; contact TIPO 專利商標資料服務台 (02)2376-7165."),
    ("expskip too much", False, "skip is beyond total-rec; lower skip."),
    ("no search command", False, "No search condition reached the server."),
    ("truncated and kerning", False, "Truncation (wildcards) and proximity operators are not supported; use exact terms with and/or/not."),
    ("unknow field", False, "Server rejected a field name (spelling 'unknow' is the server's)."),
    ("exceeded search condition length", False, "Query too long; split it into several searches."),
    ("over download quantity", False, "Rate/quota limit reached; retry in the next period or lower limit."),
)
_AUTH_DEAD: str | None = None  # circuit breaker: invalid codes risk an IP block


class Condition(BaseModel):
    field: SearchField = Field(description="Search field code, e.g. TI, AB, IC, CS, AX, ID.")
    query: str = Field(min_length=1, description=(
        "Terms for this field. Inside one field combine with and/or/not "
        "(e.g. '無線 or 藍牙'). Dates (ID/AD/DR): YYYY, YYYYMM or YYYYMMDD, "
        "range 'A:B' or open-ended 'A:' (e.g. '20100101:', '2020:2021'). "
        "No wildcards / proximity operators."))
    op: Literal["AND", "OR", "NOT"] = Field(
        "AND", description="How this field combines with the previous conditions.")


def validate_conditions(conds: list[Condition]) -> None:
    if not conds:
        raise ToolError("conditions is empty; GPSS rejects queries without a search condition.")
    if conds[0].op != "AND":
        raise ToolError("The first condition must use op=AND (OR/NOT only make sense after another condition).")
    seen: set[str] = set()
    for c in conds:
        if c.field in seen:
            raise ToolError(f"Field {c.field} appears twice; combine terms inside one condition with and/or/not.")
        seen.add(c.field)
        if "\n" in c.query or "\r" in c.query:
            raise ToolError(f"Condition {c.field}: newline in query.")
        if c.field in DATE_FIELDS and not _DATE_RE.match(c.query.strip()):
            raise ToolError(f"Condition {c.field}: bad date '{c.query}'. Use YYYY[MM[DD]] or 'A:B' / 'A:' (colon, not ~).")


def build_url(code: str, *, databases=None, case_types=None, patent_types=None,
              conditions=(), out=DEFAULT_OUT, fmt="json", qty=QTY_MIN, skip=0) -> str:
    """Param names are sent raw: '+AB' / '-IC' / 'TI/AB' must not be percent-encoded."""
    p = [f"userCode={quote(code, safe='')}"]
    if databases:
        p.append("patDB=" + ",".join(databases))
    if case_types:
        p.append("patAG=" + ",".join(case_types))
    if patent_types:
        p.append("patTY=" + ",".join(patent_types))
    for c in conditions:
        p.append(f"{_OP_PREFIX[c.op]}{c.field}={quote(c.query.strip(), safe='/:,')}")
    p.append("expFld=" + ",".join(out))
    p.append(f"expFmt={fmt}")
    p.append(f"expQty={qty}")
    p.append(f"expSkip={skip}")
    return BASE_URL + "?" + "&".join(p)


def _redact(s: str, code: str) -> str:
    return s.replace(code, "***") if code else s


def _user_code() -> str:
    code = os.environ.get(ENV_CODE, "").strip()
    # "${" = a host left its config template unexpanded; sending it would count as an
    # invalid-userCode request (IP-block risk), so treat it as missing.
    if not code or "${" in code:
        raise ToolError(
            f"Env {ENV_CODE} is not set. A GPSS API userCode is required: "
            "GPSS (tiponet.tipo.gov.tw/gpss1/gpsskmc/gpssbkm) > API > 使用說明 > API驗證碼線上申請 "
            "(one Email = one code; expired -> 展期; forgotten -> 忘記 API 驗證碼). "
            f"Claude Code: set the plugin option 'GPSS userCode' (/plugin, gpss-patent, configure). "
            f"Codex and other hosts: export {ENV_CODE} before starting the host.")
    return code


def classify(doc: dict) -> tuple[str | None, bool, str]:
    """-> (kind, fatal, hint). kind None = clean, 'empty' = no record, 'error' = known failure."""
    msg = str(doc.get("message") or "")
    low = msg.lower()
    if "no record found" in low:
        return "empty", False, msg
    for needle, fatal, hint in _ERRORS:
        if needle in low:
            return "error", fatal, f"{hint} (server: {msg})"
    if str(doc.get("status", "")).lower() != "success":
        return "error", False, f"GPSS status={doc.get('status')!r} message={msg!r}"
    return None, False, msg


def _fetch(url: str, code: str) -> dict:
    log.info("GET %s", _redact(url, code))
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "gpss-mcp/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read(MAX_BODY_BYTES + 1)
    except urllib.error.HTTPError as e:
        log.warning("GPSS HTTP %s", e.code)
        # tiponet.tipo.gov.tw answered 403 to GitHub-hosted (US) runners for its document downloads.
        hint = " TIPO appears to restrict some non-Taiwan IP ranges; try from a Taiwan network or VPN." if e.code == 403 else ""
        raise ToolError(f"GPSS HTTP {e.code}.{hint}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        msg = _redact(str(e), code)
        log.warning("GPSS network error: %s", msg)
        raise ToolError(f"GPSS network error: {msg}") from None
    if len(raw) > MAX_BODY_BYTES:
        raise ToolError("Response exceeds 50 MB; lower limit or request fewer output_fields.")
    try:
        return json.loads(raw.decode("utf-8-sig"))["gpss-API"]
    except (ValueError, KeyError, TypeError):
        log.warning("Unparseable GPSS response (%d bytes)", len(raw))
        raise ToolError(f"Unparseable GPSS response: {_redact(raw[:200].decode('utf-8', 'replace'), code)}") from None


# ---- response normalisation (JSON shape per Json_format.pdf; single item may arrive bare or in a list)
def _aslist(x: Any) -> list:
    return [] if x is None or x == "" else x if isinstance(x, list) else [x]


def _items(node: Any, key: str) -> list:
    out: list = []
    for n in _aslist(node):
        if isinstance(n, dict):
            out.extend(_aslist(n.get(key)))
    return out


def _val(x: Any) -> str | None:
    if isinstance(x, dict):
        x = x.get("keyValue", x.get("#text"))
    return None if x is None else str(x).strip()


def _one(x: Any) -> dict:
    return next((n for n in _aslist(x) if isinstance(n, dict)), {})


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _clip(s: str, n: int) -> str:
    return s if not n or len(s) <= n else f"{s[:n]}…[+{len(s) - n} chars]"


def _person(p: dict) -> dict:
    return _compact({"name": p.get("name"), "name_en": p.get("english-name"),
                     "country": p.get("country"), "country_code": p.get("country-code")})


def normalize(pc: dict, text_chars: int) -> dict:
    pub, app = _one(pc.get("publication-reference")), _one(pc.get("application-reference"))
    parties, title = _one(pc.get("parties")), _one(pc.get("patent-title"))
    nat = pc.get("classifications-national")
    claims, used, cut = [], 0, False
    for c in _items(pc.get("claims"), "claim"):
        t = "\n".join(str(x) for x in _aslist(c.get("claim-text")))
        if text_chars and used + len(t) > text_chars:
            claims.append({"num": c.get("@num"), "text": _clip(t, max(text_chars - used, 80))})
            cut = True
            break
        used += len(t)
        claims.append({"num": c.get("@num"), "text": t})
    abstract = "\n".join(str(p) for p in _items(pc.get("abstract"), "p"))
    return _compact({
        "database": pc.get("@database"), "case_type": pc.get("@status"), "patent_type": pc.get("@type"),
        "pn": pub.get("doc-number"), "pub_date": pub.get("date"),
        "an": app.get("doc-number"), "app_date": app.get("date"),
        "title": title.get("title"), "title_en": title.get("english-title"),
        "applicants": [_person(p) for p in _items(parties.get("applicants"), "applicant")],
        "inventors": [_person(p) for p in _items(parties.get("inventors"), "inventor")],
        "agents": [_val(a) for a in _items(parties.get("agents"), "agent")],
        "examiners": [_val(a) for a in _items(pc.get("examiners"), "examiner")],
        "priority": [_compact({"country": p.get("country"), "number": p.get("doc-number"), "date": p.get("date")})
                     for p in _items(pc.get("priority-claims"), "priority-claim")],
        "ipc": [_val(x) for x in _items(pc.get("classifications-ipc"), "ipc")],
        "cpc": [_val(x) for x in _items(pc.get("classifications-cpc"), "cpc")],
        "loc": [_val(x) for x in _items(pc.get("classifications-loc"), "loc")],
        "fi": [_val(x) for x in _items(nat, "fi")],
        "f_term": [_val(x) for x in _items(nat, "f-term")],
        "d_term": [_val(x) for x in _items(nat, "d-term")],
        "uspc": [_val(x) for x in _items(nat, "uspc")],
        "abstract": _clip(abstract, text_chars),
        "cited": [_val(x) for x in _items(pc.get("references-cited"), "citation")],
        "claims": claims, "claims_truncated": cut or None,
    })


def _int(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


# ---- MCP surface
mcp = MCPServer(
    "gpss-patent",
    version=VERSION,
    instructions=(
        "Global patent search via Taiwan IPO GPSS (TW/US/JP/EP/KR/CN/WO + others). Read-only. "
        "Call gpss_reference once to see database codes, field codes, syntax and quota limits. "
        "Search with gpss_search; page with skip/next_skip. Results are bibliographic data, "
        "abstract and claims only (no legal status, no description). " + DISCLAIMER),
)
_RO = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)


@mcp.tool(annotations=_RO)
def gpss_reference() -> dict[str, Any]:
    """Authoritative code tables, query syntax, quota limits and known caveats for gpss_search."""
    now = datetime.now(TW)
    work = now.weekday() < 5 and 8 <= now.hour < 18
    return {
        "source": "TIPO GPSS API docs: API_instructions v1.4 (2024/11/22), GPSS_OAS v1.1, API_code, Json_format; usage page; retrieved 2026-10-14",
        "databases": [{"code": c, "country": v[0], "kind": v[1], "full_text": v[2], "since_approx": v[3]}
                      for c, v in DATABASES.items()],
        "case_types": {"A": "公開案", "B": "公告案"},
        "patent_types": {"I": "發明", "M": "新型", "D": "設計"},
        "search_fields": SEARCH_FIELDS,
        "date_fields": sorted(DATE_FIELDS),
        "output_fields": OUTPUT_FIELDS,
        "default_output_fields": list(DEFAULT_OUT),
        "syntax": [
            "Within a field: and / or / not between terms.",
            "Across fields: default AND; op=OR becomes '+FIELD', op=NOT becomes '-FIELD' in the URL.",
            "Dates: YYYY, YYYYMM, YYYYMMDD; range 'A:B', open-ended 'A:'.",
            "Truncation and proximity operators are rejected by the server.",
            "Omitted databases / case_types / patent_types = all.",
        ],
        "limits": {
            "per_search_max_records": QTY_MAX,
            "work_hours (Mon-Fri 08:00-18:00 Asia/Taipei)": {"search_period_total": 10_000, "single_number_per_hour": 300, "single_number_period_total": 3_000},
            "off_hours": {"search_period_total": 30_000, "single_number_per_hour": 1_000, "single_number_period_total": 10_000},
            "current_period": "work_hours" if work else "off_hours",
            "note": "'單筆案號' = single-number lookups; exact definition and holiday handling are not documented.",
        },
        "caveats": [
            "Docs conflict: API_code.pdf marks JPA/KPA/KPB as 無全文, API_instructions.pdf marks only SEAA/SEAB/OTA/OTB. API_code (flags above) is used. TI/AB/CL searches on 無全文 databases may miss.",
            "Live-verified 2026-10-14: endpoint reachable; bad userCode -> HTTP 200 + {status:'fail', message:'userCode not exist'}.",
            "NOT live-verified (needs valid userCode): success payload shape, '+'/'-' prefix handling, expQty below 30, precedence of mixed AND/OR/NOT (assumed left to right).",
            "Native-language vs English matching of TI/AB/CL on JP/KR/CN databases is undocumented; try both.",
            "qty-rec in the docs' examples equals the requested expQty, not the returned count; this server reports its own count.",
        ],
        "disclaimer": DISCLAIMER,
    }


@mcp.tool(annotations=_RO)
def gpss_search(
    conditions: Annotated[list[Condition], Field(min_length=1, description="Search conditions, evaluated in the given order.")],
    databases: Annotated[list[DbCode] | None, Field(description="Databases to search; omit for all.")] = None,
    case_types: Annotated[list[Literal["A", "B"]] | None, Field(description="A=公開案, B=公告案; omit for both.")] = None,
    patent_types: Annotated[list[Literal["I", "M", "D"]] | None, Field(description="I=發明, M=新型, D=設計; omit for all.")] = None,
    output_fields: Annotated[list[OutField] | Literal["all"] | None, Field(
        description="Fields to return. Default PN,ID,AN,AD,TI. Use 'all' for the full record (heavy).")] = None,
    limit: Annotated[int, Field(ge=1, le=QTY_MAX, description="Records to return. GPSS minimum per request is 30, so smaller values still count 30 against the quota.")] = 30,
    skip: Annotated[int, Field(ge=0, description="Records to skip (paging).")] = 0,
    text_chars: Annotated[int, Field(ge=0, description="Max characters kept for abstract and for all claims together per record; 0 = unlimited.")] = 1200,
    raw: Annotated[bool, Field(description="Return the untouched gpss-API object (debugging).")] = False,
) -> dict[str, Any]:
    """Search patents in TIPO GPSS. Returns normalised records plus total/next_skip for paging."""
    global _AUTH_DEAD
    if _AUTH_DEAD:
        raise ToolError(f"Refusing to call GPSS again this session: {_AUTH_DEAD}")
    validate_conditions(conditions)
    code = _user_code()
    out = tuple(OUTPUT_FIELDS) if output_fields == "all" else tuple(output_fields or DEFAULT_OUT)
    url = build_url(code, databases=databases, case_types=case_types, patent_types=patent_types,
                    conditions=conditions, out=out, qty=max(limit, QTY_MIN), skip=skip)
    doc = _fetch(url, code)
    kind, fatal, hint = classify(doc)
    if raw:
        return {"raw": doc}
    patents = [normalize(pc, text_chars) for pc in _items(doc.get("patent"), "patentcontent")]
    if kind == "error" and (fatal or not patents):
        if fatal:
            _AUTH_DEAD = hint
        raise ToolError(_redact(hint, code))
    total = _int(doc.get("total-rec"))
    shown = patents[:limit]
    result: dict[str, Any] = {"status": "success", "total": total, "skip": skip,
                              "returned": len(shown), "patents": shown, "disclaimer": DISCLAIMER}
    if skip + len(shown) < total:
        result["next_skip"] = skip + len(shown)
    if hint:
        result["notice"] = hint
    return result


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    mcp.run(transport="stdio")
