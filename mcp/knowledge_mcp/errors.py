"""Failure handoff. Agent must not skip the gate."""

def fail(step: str, why: str, done: str = "无", next_try: str = "") -> str:
    nxt = next_try or "按正门改输入后再调；不要去直接读资料文件夹里的全书。"
    return (
        f"失败\n"
        f"卡在哪一步：{step}\n"
        f"为什么：{why}\n"
        f"已经做成了什么：{done}\n"
        f"正门上还能怎么试：{nxt}\n"
    )

