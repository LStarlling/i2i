#!/usr/bin/env python3
"""SessionEnd 钩子：会话结束时静默抽取本次会话的新信号，留到下次“更新分身”时提炼。仅依赖标准库。"""
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "i2i" / "scripts"))


def main():
    try:
        transcript = (json.load(sys.stdin) or {}).get("transcript_path")
        if not transcript or not Path(transcript).exists():
            return
        import extract
        sys.argv = ["extract.py", "--transcript", transcript]
        sys.stdout = io.StringIO()  # 结束钩子的输出没人看
        extract.main()
    except Exception:  # 学习失败不能影响会话正常结束
        pass


if __name__ == "__main__":
    main()
