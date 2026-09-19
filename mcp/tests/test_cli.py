"""CLI is the Skill gate: same functions, no extra doors."""
from pathlib import Path

from tests.conftest import drop_source, stub_convert
from tests.test_lint import plant_book


def test_cli_init(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_ROOT", str(tmp_path / "lib"))
    from knowledge_mcp.cli import main

    assert main(["init"]) == 0
    root = tmp_path / "lib"
    assert (root / "原始资料").is_dir()
    assert (root / "资料" / "书").is_dir()
    assert (root / "资料" / "笔记").is_dir()


def test_cli_search_empty_fails(kb, capsys):
    from knowledge_mcp.cli import main

    assert main(["search", ""]) == 1
    assert capsys.readouterr().out.startswith("失败")


def test_cli_search_and_lint(kb, capsys):
    plant_book(kb)
    from knowledge_mcp.cli import main

    assert main(["search", "拖延"]) == 0
    out = capsys.readouterr().out
    assert "路标" in out
    assert main(["lint", "scan"]) == 0
    scan = capsys.readouterr().out
    assert "在架" in scan
    assert "拖延心理学" in scan


def test_cli_ingest_playbook(kb, monkeypatch, capsys):
    monkeypatch.setattr("knowledge_mcp.ingest.run_markitdown", stub_convert())
    drop_source(kb, "delay.epub")
    from knowledge_mcp.cli import main

    assert main(["ingest"]) == 0
    out = capsys.readouterr().out
    assert "操作流程" in out
    assert "代码已做" in out
