#!/usr/bin/env python3
"""SessionStart 钩子：有待提炼的新信号时提示一句，其余情况不输出。仅依赖标准库。"""
import os
from pathlib import Path

HOME = Path(os.environ.get("I2I_HOME") or Path.home() / ".i2i")


def main():
    pending = HOME / "pending"
    if not (HOME / "profile.md").exists() or not pending.is_dir():
        return
    n = sum(1 for f in pending.glob("*.jsonl") for l in open(f, encoding="utf-8", errors="ignore") if l.strip())
    if n:
        print("I2I：上次会话后新增 {} 条待学习的信号，说“更新分身”即可让分身学进去。".format(n))


if __name__ == "__main__":
    main()
