#!/usr/bin/env python3
"""把分身规则同步到 memory 文件（CLAUDE.md、AGENTS.md 等）。仅依赖标准库。

只维护文件里一对标记之间的区块，标记之外用户手写的内容一律不动。

  python export.py targets                     列出本机可能的 memory 文件
  python export.py write --target <文件>       用 ~/.i2i/export.md 的内容替换（或追加）区块
  python export.py remove --target <文件>      删除区块，其余内容原样保留

export.md 由 agent 根据 profile.md 撰写，只放要导出的规则本身。
"""
import os
import sys
import time
from pathlib import Path

from extract import HOME

START = "<!-- i2i:start 由 I2I 维护，手改会在下次同步时被覆盖；要改请改 ~/.i2i/profile.md -->"
END = "<!-- i2i:end -->"
CANDIDATES = [
    Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "CLAUDE.md",
    Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "AGENTS.md",
    Path.home() / ".gemini" / "GEMINI.md",
]


def split(text):
    """返回 (区块前, 区块后)；没有区块时区块后为 None。"""
    i = text.find(START)
    if i < 0:
        return text, None
    j = text.find(END, i)
    if j < 0:
        sys.exit("memory 文件里有开始标记但没有结束标记，请手动检查后再同步")
    return text[:i], text[j + len(END):]


def targets():
    for p in CANDIDATES:
        state = "不存在"
        if p.exists():
            state = "已有 I2I 区块" if START in p.read_text(encoding="utf-8", errors="ignore") else "存在"
        print("{}\t{}".format(state, p))


def write(target):
    body = (HOME / "export.md").read_text(encoding="utf-8").strip()
    if not body:
        sys.exit("export.md 为空，没有可导出的规则")
    block = "{}\n{}\n\n（同步时间：{}）\n{}".format(START, body, time.strftime("%Y-%m-%d"), END)
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    before, after = split(text)
    if after is None:
        new = text.rstrip() + ("\n\n" if text.strip() else "") + block + "\n"
        action = "已追加区块到"
    else:
        new = before + block + after
        action = "已更新区块："
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new, encoding="utf-8")
    print(action, target)


def remove(target):
    text = target.read_text(encoding="utf-8")
    before, after = split(text)
    if after is None:
        sys.exit("文件里没有 I2I 区块")
    target.write_text((before.rstrip() + "\n" + after.lstrip("\n")).strip() + "\n", encoding="utf-8")
    print("已删除区块：", target)


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else ""
    if cmd == "targets":
        return targets()
    if cmd in ("write", "remove") and len(args) == 3 and args[1] == "--target":
        return (write if cmd == "write" else remove)(Path(args[2]).expanduser())
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
