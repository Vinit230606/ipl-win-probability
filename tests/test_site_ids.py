"""Every element id a page script writes to exists in that page's HTML."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGES = {"about.js": "about.html", "results.js": "results.html", "replay.js": "index.html",
         "calculator.js": "calculator.html", "edge_cases.js": "edge-cases.html"}


@pytest.mark.parametrize("script,page", PAGES.items())
def test_ids_exist(script, page):
    src = (DOCS / "assets" / "js" / script).read_text(encoding="utf-8")
    used = set(re.findall(r'\$\("([\w-]+)"\)', src)) | set(re.findall(r'getElementById\("([\w-]+)"\)', src))
    have = set(re.findall(r'id="([\w-]+)"', (DOCS / page).read_text(encoding="utf-8")))
    assert not used - have - {"load-error"}, f"{script}: missing ids {sorted(used - have)}"


def test_every_page_links_every_page():
    pages = ["index.html", "calculator.html", "edge-cases.html", "results.html", "about.html"]
    for p in pages:
        html = (DOCS / p).read_text(encoding="utf-8")
        for q in pages:
            assert f'href="{q}"' in html, f"{p} has no nav link to {q}"
