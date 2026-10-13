"""Download the TIPO GPSS spec files into _src/ and verify their SHA-256 (drift detector).

Run: python scripts/fetch_sources.py
Exit 1 when a file is unreachable or its hash differs from docs/SOURCES.md, i.e. TIPO
changed the document and server.py must be re-checked against it. The files are not
committed because their redistribution terms are not stated.
"""
import hashlib
import logging
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://tiponet.tipo.gov.tw/gpss1/gpsskm/API/"
DEST = Path(__file__).resolve().parent.parent / "_src"
TIMEOUT_S = 60
SHA256 = {
    "GPSS_OAS.json": "19ba9c02d37b077e7faff06dce208380b3a78a89a17767f7c2990a997bee4e73",
    "API_instructions.pdf": "ac60046ff14b1ac3a1aae77a857df1663a05ed7221b5efcb2f0f4f9ba2ed40ea",
    "API_code.pdf": "adf848d06099b207246c0b474d04ec835d56af86dcff9892159b23bc0cdaa864",
    "Json_format.pdf": "4c38235bda7183064a9d6cda2cfcbd88c7fa20375594a95bda8a9dd64c28f0ae",
    "Xml_format.pdf": "0d68e25d1f8ddd0f228fe0dd8afa6b55c8451c9ee0327f584791adf07f87cf0b",
}
log = logging.getLogger("fetch_sources")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    DEST.mkdir(exist_ok=True)
    bad = 0
    for name, want in SHA256.items():
        path = DEST / name
        if not path.exists():
            try:
                with urllib.request.urlopen(BASE + name, timeout=TIMEOUT_S) as r:
                    path.write_bytes(r.read())
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log.error("%s: download failed: %s", name, e)
                bad += 1
                continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got == want:
            log.info("%s: ok", name)
        else:
            log.error("%s: HASH MISMATCH (got %s). TIPO changed the document; re-check server.py.", name, got)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
