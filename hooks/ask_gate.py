#!/usr/bin/env python3
"""PreToolUse 钩子（AskUserQuestion）：agent 要问用户之前，先让分身判断。

有分身档案时拦下第一次提问，把档案交给 agent：把握高的问题按档案直接选，
没把握的再问用户，并在问题开头加“【分身没把握】”。带该标记的提问直接放行，
快问快答的提问（带“快问快答”）和 I2I 自身流程的提问（带“【I2I】”）也放行。仅依赖标准库。
"""
import json
import os
import re
import sys
from pathlib import Path

HOME = Path(os.environ.get("I2I_HOME") or Path.home() / ".i2i")
PASS = ("分身没把握", "快问快答", "【I2I】")
CAP = 9000

GUIDE = """I2I 分身拦截了这次提问。请先按下面的分身档案逐个判断问题：
- 有把握度为“高”的规则直接覆盖的问题：不要问用户，按规则选择并继续，在最终回复里用一行注明“已按你的习惯选了 X（规则编号）”，用户不认可会自己纠正。
- 其余问题：再次调用 AskUserQuestion 只问这些问题，每个 question 的开头加“【分身没把握】”。
- 不要为了绕过拦截而给问题加标记，只有确实没把握的问题才加。

===== 分身档案（~/.i2i/profile.md 节选）=====
"""


def excerpt(text):
    """只取决策原则、工作偏好、常打回的问题三节，去掉证据 id。"""
    keep, out = False, []
    for line in text.splitlines():
        if line.startswith("## "):
            keep = any(k in line for k in ("决策原则", "工作偏好", "常打回"))
        if keep:
            out.append(re.sub(r"｜证据：[^｜\n]*", "", line))
    body = "\n".join(out).strip()
    return body if len(body) <= CAP else body[:CAP] + "\n…（已截断）"


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    raw = json.dumps(data.get("tool_input") or {}, ensure_ascii=False)
    if any(k in raw for k in PASS):
        return
    profile = HOME / "profile.md"
    if not profile.exists():
        return
    body = excerpt(profile.read_text(encoding="utf-8", errors="ignore"))
    if not body:
        return
    sys.stderr.write(GUIDE + body + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
