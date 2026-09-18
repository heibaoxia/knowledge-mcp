from pathlib import Path

import pytest

from knowledge_mcp.index import map_problems
from knowledge_mcp.paths import repo_root

BOOKS = [
    "book-fe981a7a",
    "book-2cde2fad",
    "19-psychology-and-life-richard-gerrig-etc",
    "1-7",
    "book-419c3021",
    "book-d2c01296",
    "book-6a85baa6",
]


@pytest.mark.parametrize("slug", BOOKS)
def test_real_book_map_ok(slug):
    # 3.1：章名已机械补齐，不合格就是真不合格——不再豁免「章名覆盖不足」
    d = repo_root() / "资料" / "书" / slug
    if not d.is_dir():
        pytest.skip("no book")
    assert map_problems(d) == []
