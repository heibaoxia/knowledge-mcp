from pathlib import Path

import pytest

from knowledge_mcp.index import map_problems
from knowledge_mcp.paths import repo_root

BOOKS = [
    "book-fe981a7a",
    "book-2cde2fad",
    "19-psychology-and-life-richard-gerrig-etc",
    "1-7",
]


@pytest.mark.parametrize("slug", BOOKS)
def test_real_book_map_ok(slug):
    d = repo_root() / "资料" / "书" / slug
    if not d.is_dir():
        pytest.skip("no book")
    probs = map_problems(d)
    hard = [p for p in probs if "章名" not in p]
    assert hard == []
