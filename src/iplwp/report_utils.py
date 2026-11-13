"""Small helpers for writing Markdown reports without extra dependencies."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


def _cell(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def md_table(df: pd.DataFrame, index: bool = False, max_rows: int | None = None) -> str:
    """Render `df` as a GitHub-flavoured Markdown table (optionally including the index)."""
    if index:
        df = df.reset_index()
    if max_rows is not None:
        df = df.head(max_rows)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines)


def md_list(items: Iterable[str]) -> str:
    return "\n".join(f"- {i}" for i in items)
