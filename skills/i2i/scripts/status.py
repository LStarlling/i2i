#!/usr/bin/env python3
"""输出分身当前状态（JSON），供入口菜单使用。仅依赖标准库。"""
import json
import re
from pathlib import Path

from extract import HOME

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}


def header(profile, key):
    m = re.search(r"^- {}[：:]\s*(.*)$".format(re.escape(key)), profile, re.M)
    return (m.group(1).strip() if m else "") or ""


def main():
    profile_path = HOME / "profile.md"
    st = {"版本": (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip(),
          "已建档": profile_path.exists()}
    profile = profile_path.read_text(encoding="utf-8", errors="ignore") if st["已建档"] else ""
    formal = profile.split("## 待验证")[0]
    st["规则数"] = len(re.findall(r"^- \[R\d+\]", formal, re.M))
    st["最近校准"] = {"选择题": header(profile, "最近校准（选择题）") or header(profile, "最近校准"),
                    "打回题": header(profile, "最近校准（打回题）")}
    st["memory文件"] = header(profile, "memory 文件")
    st["本人昵称"] = header(profile, "本人昵称")
    pending = HOME / "pending"
    st["待学习信号"] = sum(1 for f in pending.glob("*.jsonl") for l in open(f, encoding="utf-8", errors="ignore")
                       if l.strip()) if pending.is_dir() else 0
    inbox = HOME / "inbox"
    st["收件箱截图"] = sum(1 for p in inbox.iterdir() if p.suffix.lower() in IMAGES) if inbox.is_dir() else 0
    used_file = HOME / "eval" / "used.txt"
    used = set(used_file.read_text(encoding="utf-8").split()) if used_file.exists() else set()
    tests = {"选择题": 0, "打回题": 0}
    store = HOME / "signals.jsonl"
    if store.exists():
        for l in open(store, encoding="utf-8", errors="ignore"):
            if '"split": "test"' not in l:
                continue
            s = json.loads(l)
            if s["id"] not in used:
                tests["选择题" if s.get("options") else "打回题"] += 1
    st["可用考题"] = tests
    st["已有卡片"] = (HOME / "card.json").exists()
    print(json.dumps(st, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
