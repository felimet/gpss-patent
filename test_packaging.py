"""Packaging invariants for the dual Claude Code / Codex plugin layout.

Run: uv run --with "mcp>=2.3,<3" --with pytest pytest -q test_packaging.py
"""
import importlib.util
import json
import re
from pathlib import Path

import server as s

ROOT = Path(__file__).parent
NAME = "gpss-patent"


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text("utf-8"))


def test_names_versions_and_marketplaces_agree():
    cc, cx = load(".claude-plugin/plugin.json"), load(".codex-plugin/plugin.json")
    assert cc["name"] == cx["name"] == NAME
    assert cc["version"] == cx["version"] == s.VERSION
    mk_cc, mk_cx = load(".claude-plugin/marketplace.json"), load(".agents/plugins/marketplace.json")
    assert [p["name"] for p in mk_cc["plugins"]] == [p["name"] for p in mk_cx["plugins"]] == [NAME]
    assert mk_cc["plugins"][0]["source"] == mk_cx["plugins"][0]["source"]["path"] == "./"


def test_claude_mcp_launches_server_and_injects_secret_option():
    srv = load(".mcp.json")["mcpServers"][NAME]
    assert srv["args"][-1] == "${CLAUDE_PLUGIN_ROOT}/server.py"
    assert srv["env"] == {s.ENV_CODE: "${user_config.gpss_user_code}"}
    opt = load(".claude-plugin/plugin.json")["userConfig"]["gpss_user_code"]
    assert opt["sensitive"] is True and opt["type"] == "string"


def test_codex_mcp_launches_server_and_forwards_env():
    assert load(".codex-plugin/plugin.json")["mcpServers"] == "./.codex-mcp.json"
    srv = load(".codex-mcp.json")["mcpServers"][NAME]
    assert srv["cwd"] == "." and srv["args"][-1] == "server.py" and (ROOT / "server.py").is_file()
    assert srv["env_vars"] == [s.ENV_CODE]


def test_skill_is_discoverable_and_names_real_tools():
    f = ROOT / "skills" / "gpss-patent-search" / "SKILL.md"
    text = f.read_text("utf-8")
    m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
    assert m and m[1] == f.parent.name
    assert load(".codex-plugin/plugin.json")["skills"] == "./skills/"
    for tool in ("gpss_search", "gpss_reference"):
        assert tool in text


def test_pinned_source_hashes_are_documented():
    spec = importlib.util.spec_from_file_location("fetch_sources", ROOT / "scripts" / "fetch_sources.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    md = (ROOT / "docs" / "SOURCES.md").read_text("utf-8")
    assert mod.SHA256 and all(name in md and sha in md for name, sha in mod.SHA256.items())
