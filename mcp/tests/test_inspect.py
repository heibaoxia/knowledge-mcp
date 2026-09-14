"""Block 5 gates: inspect shows calls/failures; proposals never patch mcp source."""
from pathlib import Path


def test_inspect_sees_recent_calls(kb):
    from knowledge_mcp.retrieve import search
    from knowledge_mcp.inspect import inspect

    search("拖延")
    out = inspect("7d")
    assert "kb_search" in out or "检索" in out
    assert "拖延" in out


def test_inspect_sees_failures(kb):
    from knowledge_mcp.inspect import inspect
    from knowledge_mcp.notes import write_note

    write_note("一段没有抬头的话", action="create")
    out = inspect("7d")
    assert "失败" in out or "False" in out or "ok: false" in out.lower()
    assert "kb_write_note" in out or "写笔记" in out


def test_proposal_lands_in_repair_folder(kb):
    from knowledge_mcp.inspect import inspect

    out = inspect("7d", proposal="想给笔记加一个过期字段。动净化门。对书不改无风险。")
    files = list((kb / "检修" / "提案").glob("*.md"))
    assert files
    assert "过期字段" in files[0].read_text(encoding="utf-8")
    assert "提案" in out


def test_crash_uses_fail_handoff(kb, monkeypatch):
    from knowledge_mcp import retrieve

    monkeypatch.setattr(
        "knowledge_mcp.index._ensure",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(retrieve, "iter_headers", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = retrieve.search("拖延")
    assert out.startswith("失败")
    assert "工具坏了" in out
    assert "卡在哪一步" in out


def test_inspect_does_not_patch_mcp_source(kb):
    from knowledge_mcp.inspect import inspect

    server = Path(__file__).resolve().parents[1] / "knowledge_mcp" / "server.py"
    before = server.read_text(encoding="utf-8")
    inspect("7d", proposal="直接改 server.py 把闸门拆了")
    after = server.read_text(encoding="utf-8")
    assert before == after
    assert not list((kb / "mcp").glob("**/*")) if (kb / "mcp").exists() else True
