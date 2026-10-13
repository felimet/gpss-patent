"""Run: uv run --with "mcp>=2.3,<3" --with pytest --with pypdf pytest -q

Source cross-checks read the original TIPO files in _src/ and skip when absent.
The doc-derived fixture comes from Json_format.pdf example 1; it is NOT a live capture.
The userCode-error body in test_classify_* IS a live capture (2026-10-14).
"""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

import server as s

SRC = Path(__file__).parent / "_src"
CONTROL = {"userCode", "patDB", "patAG", "patTY", "expFld", "expFmt", "expQty", "expSkip"}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(s, "_AUTH_DEAD", None)
    monkeypatch.setenv(s.ENV_CODE, "SECRETCODE")


def pdf_text(name: str) -> str:
    pypdf = pytest.importorskip("pypdf")
    f = SRC / name
    if not f.exists():
        pytest.skip(f"{f} missing")
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(f).pages)


# ---- source cross-checks -------------------------------------------------
def test_search_fields_match_oas():
    f = SRC / "GPSS_OAS.json"
    if not f.exists():
        pytest.skip("OAS missing")
    names = {p["name"] for p in json.loads(f.read_text("utf-8"))["paths"]["/gpss_api"]["get"]["parameters"]}
    assert CONTROL <= names
    assert names - CONTROL == set(s.SEARCH_FIELDS)


def test_databases_match_api_code_pdf():
    t1 = re.split(r"表\s*2", pdf_text("API_code.pdf"))[0]
    found = {}
    for line in t1.splitlines():
        m = re.search(r"(公開|公告|設計|意匠|外觀設計)([(（]無全文[)）])?([A-Z]{2,5})$", re.sub(r"\s+", "", line))
        if m:
            found[m[3]] = (m[1], m[2] is None)
    assert found == {c: (v[1], v[2]) for c, v in s.DATABASES.items()}


def test_field_tables_match_api_code_pdf():
    t2 = re.split(r"表\s*2", pdf_text("API_code.pdf"))[1]
    tokens = set(re.findall(r"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])", t2))
    single = {k for k in s.SEARCH_FIELDS if "/" not in k}
    assert tokens == single | {"PA", "IN"}
    assert set(s.OUTPUT_FIELDS) == tokens - {"AX", "AF", "AY", "AZ", "IV", "IY", "DR", "FC", "TS"}


DOC_URL = ("https://tiponet.tipo.gov.tw/gpss1/gpsskmc/gpss_api?userCode=驗證碼"
           "&patDB=TWA,TWB,USA,USB,EPA,EPB&patAG=A,B&patTY=I,M"
           "&TI=網架結構 or Filter frame&+AB=網架結構 or Filter frame&IY=US&-IC=F24F&ID=20100101:"
           "&expFld=PN,ID,TI,IN,PR,AB,CL&expFmt=xml&expQty=30&expSkip=100")


def test_build_url_reproduces_doc_example():
    squash = lambda x: re.sub(r"\s+", "", x)  # noqa: E731
    assert squash(DOC_URL) in squash(pdf_text("API_instructions.pdf")), "expected URL is not the doc's"
    C = s.Condition
    url = s.build_url(
        "驗證碼", databases=["TWA", "TWB", "USA", "USB", "EPA", "EPB"], case_types=["A", "B"], patent_types=["I", "M"],
        conditions=[C(field="TI", query="網架結構 or Filter frame"), C(field="AB", query="網架結構 or Filter frame", op="OR"),
                    C(field="IY", query="US"), C(field="IC", query="F24F", op="NOT"), C(field="ID", query="20100101:")],
        out=("PN", "ID", "TI", "IN", "PR", "AB", "CL"), fmt="xml", qty=30, skip=100)
    assert unquote(url) == DOC_URL
    assert "&+AB=" in url and "&-IC=" in url and "%2B" not in url  # prefixes must stay raw


# ---- validation ----------------------------------------------------------
@pytest.mark.parametrize("conds,frag", [
    ([], "empty"),
    ([s.Condition(field="TI", query="a", op="NOT")], "first condition"),
    ([s.Condition(field="TI", query="a"), s.Condition(field="TI", query="b", op="OR")], "twice"),
    ([s.Condition(field="ID", query="20200101~20201231")], "bad date"),
    ([s.Condition(field="ID", query="20201331")], "bad date"),
])
def test_validate_rejects(conds, frag):
    with pytest.raises(ToolError, match=frag):
        s.validate_conditions(conds)


@pytest.mark.parametrize("q", ["2020", "202001", "20200131", "20100101:", "2020:2021", "202001:202012"])
def test_validate_accepts_documented_dates(q):
    s.validate_conditions([s.Condition(field="DR", query=q)])


# ---- normalisation (doc-derived fixture) ---------------------------------
EX1 = {"status": "success", "skip": "0", "total-rec": "1", "qty-rec": "30", "patent": {"@create-date": "20210728", "patentcontent": [{
    "@sequence": "1", "@database": "美國設計", "@status": "B", "@type": "新式樣",
    "publication-reference": {"doc-number": "USD0254332S", "date": "19800226"},
    "application-reference": {"doc-number": "US05895783", "date": "19780412"},
    "parties": {"applicants": {"applicant": [{"@sequence": "1", "english-name": "Stanley Electric Co., Ltd.", "country-code": "JP"}]},
                "inventors": {"inventor": [{"@sequence": "1", "english-name": "Nakano; Koji", "country-code": "JP"},
                                           {"@sequence": "2", "english-name": "Maeda; Yoshikazu", "country-code": "JP"}]},
                "agents": {"agent": [{"@sequence": "1", "keyValue": "Flynn, Robert D."}]}},
    "examiners": {"examiner": [{"@sequence": "1", "keyValue": "Lucas; Susan J."}]},
    "priority-claims": {"priority-claim": [{"@sequence": "1", "country": "JP", "doc-number": "52-041542", "date": "19771019"}]},
    "classifications-loc": {"loc": [{"@sequence": "1", "keyValue": "D2606"}]},
    "classifications-national": {"uspc": [{"@sequence": "1", "keyValue": "D48/32A"}]},
    "patent-title": {"english-title": "Lens for a lamp"},
    "references-cited": {"citation": [{"@sequence": "1", "keyValue": "GB649370 19510100"}, {"@sequence": "2", "keyValue": "GB1439011 19760600"}]},
    "claims": {"claim": [{"@num": "1", "claim-text": "The ornamental design for a lens for a lamp, as shown."}]},
}]}}
PC1 = EX1["patent"]["patentcontent"][0]


def unwrap(x):
    """Simulate an XML->JSON converter that drops single-item lists."""
    if isinstance(x, list):
        return unwrap(x[0]) if len(x) == 1 else [unwrap(i) for i in x]
    return {k: unwrap(v) for k, v in x.items()} if isinstance(x, dict) else x


def test_normalize_doc_example():
    r = s.normalize(PC1, 1200)
    assert (r["pn"], r["pub_date"], r["an"], r["app_date"]) == ("USD0254332S", "19800226", "US05895783", "19780412")
    assert r["database"] == "美國設計" and r["title_en"] == "Lens for a lamp"
    assert r["applicants"] == [{"name_en": "Stanley Electric Co., Ltd.", "country_code": "JP"}]
    assert [i["name_en"] for i in r["inventors"]] == ["Nakano; Koji", "Maeda; Yoshikazu"]
    assert r["agents"] == ["Flynn, Robert D."] and r["examiners"] == ["Lucas; Susan J."]
    assert r["priority"] == [{"country": "JP", "number": "52-041542", "date": "19771019"}]
    assert (r["loc"], r["uspc"]) == (["D2606"], ["D48/32A"])
    assert r["cited"] == ["GB649370 19510100", "GB1439011 19760600"]
    assert r["claims"] == [{"num": "1", "text": "The ornamental design for a lens for a lamp, as shown."}]
    assert "claims_truncated" not in r and "abstract" not in r


def test_normalize_tolerates_bare_single_items():
    assert s.normalize(unwrap(PC1), 1200) == s.normalize(PC1, 1200)


def test_text_budget_truncates():
    pc = {"abstract": {"p": ["x" * 300]}, "claims": {"claim": [{"@num": "1", "claim-text": "a" * 30}, {"@num": "2", "claim-text": "b" * 500}]}}
    r = s.normalize(pc, 100)
    assert r["abstract"] == "x" * 100 + "…[+200 chars]"
    assert r["claims_truncated"] is True and [c["num"] for c in r["claims"]] == ["1", "2"]
    assert r["claims"][1]["text"] == "b" * 80 + "…[+420 chars]"
    assert "claims_truncated" not in s.normalize(pc, 0) and len(s.normalize(pc, 0)["abstract"]) == 300


# ---- error classification ------------------------------------------------
def test_classify_live_captured_usercode_error():
    kind, fatal, hint = s.classify({"status": "fail", "message": "userCode not exist"})
    assert (kind, fatal) == ("error", True) and "GPSS_USER_CODE" in hint


def test_classify_empty_and_other():
    assert s.classify({"status": "success", "message": "no record found"})[0] == "empty"
    assert s.classify({"status": "success", "message": "expSkip too much"})[:2] == ("error", False)
    assert s.classify({"status": "success"})[0] is None
    assert s.classify({"status": "weird"})[0] == "error"


# ---- tool behaviour with the network stubbed -----------------------------
C = s.Condition


def test_search_pages_and_normalises(monkeypatch):
    seen = {}
    monkeypatch.setattr(s, "_fetch", lambda url, code: seen.setdefault("url", url) and {**EX1, "total-rec": "95"})
    r = s.gpss_search([C(field="TI", query="lamp")], databases=["USD"], limit=1)
    assert r["total"] == 95 and r["returned"] == 1 and r["next_skip"] == 1
    assert r["patents"][0]["pn"] == "USD0254332S"
    assert "expQty=30" in seen["url"] and "SECRETCODE" in seen["url"]  # min 30 sent, shown slice = limit


def test_search_empty_result(monkeypatch):
    monkeypatch.setattr(s, "_fetch", lambda u, c: {"status": "success", "message": "no record found"})
    r = s.gpss_search([C(field="TI", query="zzzz")])
    assert r["patents"] == [] and r["total"] == 0 and r["notice"] == "no record found"


def test_missing_code_never_hits_network(monkeypatch):
    monkeypatch.delenv(s.ENV_CODE)
    monkeypatch.setattr(s, "_fetch", lambda *a: pytest.fail("network called"))
    with pytest.raises(ToolError, match="API驗證碼線上申請"):
        s.gpss_search([C(field="TI", query="x")])


def test_unexpanded_template_code_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv(s.ENV_CODE, "${user_config.gpss_user_code}")
    monkeypatch.setattr(s, "_fetch", lambda *a: pytest.fail("network called"))
    with pytest.raises(ToolError, match="not set"):
        s.gpss_search([C(field="TI", query="x")])


def test_invalid_code_trips_breaker(monkeypatch):
    calls = []
    monkeypatch.setattr(s, "_fetch", lambda u, c: calls.append(1) or {"status": "fail", "message": "userCode not exist"})
    with pytest.raises(ToolError, match="invalid"):
        s.gpss_search([C(field="TI", query="x")])
    with pytest.raises(ToolError, match="Refusing"):
        s.gpss_search([C(field="TI", query="x")])
    assert len(calls) == 1  # second call must not reach the server (IP-block risk)


def test_error_message_does_not_leak_code(monkeypatch):
    monkeypatch.setattr(s, "_fetch", lambda u, c: {"status": "fail", "message": "boom SECRETCODE"})
    with pytest.raises(ToolError) as e:
        s.gpss_search([C(field="TI", query="x")])
    assert "SECRETCODE" not in str(e.value)


# ---- protocol level: schema + pydantic validation through a real client ---
def test_protocol_roundtrip(monkeypatch):
    async def go():
        async with Client(s.mcp) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert set(tools) == {"gpss_reference", "gpss_search"}
            schema = json.dumps(tools["gpss_search"].input_schema)
            assert "TI/AB/CL" in schema and "EUIPO" in schema
            ref = await c.call_tool("gpss_reference", {})
            assert not ref.is_error
            bad = await c.call_tool("gpss_search", {"conditions": [{"field": "XX", "query": "a"}]})
            assert bad.is_error
    asyncio.run(go())
