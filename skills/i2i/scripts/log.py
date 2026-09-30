#!/usr/bin/env python3
"""手动追加一条信号。仅依赖标准库。

  python log.py choice --context "情境" --options "A|B" --answer "A"
  python log.py correction --context "分身的判断" --answer "我实际的选择和理由"
  python log.py said --to "同事" --context "对方上一句（可省略）" --answer "我发出的原话"
"""
import argparse
import json
import time

from extract import HOME, TEST_PERCENT, sig_id, redact


def main():
    ap = argparse.ArgumentParser(description="追加一条偏好信号")
    ap.add_argument("kind", choices=["choice", "correction", "said"])
    ap.add_argument("--context", default="")
    ap.add_argument("--answer", required=True)
    ap.add_argument("--options", default="", help="选项标签，用 | 分隔（choice 必填）")
    ap.add_argument("--note", default="")
    ap.add_argument("--to", default="", help="said 的对象：上级、同事、朋友、家人等")
    a = ap.parse_args()

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    s = {"id": sig_id("manual", a.kind, a.context, a.answer), "source": "manual", "project": "", "ts": ts,
         "kind": a.kind, "context": redact(a.context), "answer": redact(a.answer), "note": redact(a.note)}
    if a.kind == "said":
        s["to"] = a.to
    if a.kind == "choice":
        labels = [x.strip() for x in a.options.split("|") if x.strip()]
        if a.answer not in labels:
            ap.error("--answer 必须是 --options 中的一项")
        s.update(options=[{"label": l, "description": ""} for l in labels], multi=False, answer=[a.answer])
    # 纠正和发言永远用于学习；快问快答按 id 抽一部分留作评测题
    s["split"] = "test" if a.kind == "choice" and int(s["id"], 16) % 100 < TEST_PERCENT else "train"

    line = json.dumps(s, ensure_ascii=False) + "\n"
    with open(HOME / "signals.jsonl", "a", encoding="utf-8") as fp:
        fp.write(line)
    if s["split"] == "train":
        (HOME / "pending").mkdir(parents=True, exist_ok=True)
        with open(HOME / "pending" / "manual.jsonl", "a", encoding="utf-8") as fp:
            fp.write(line)
    print("已记录：{}（{}）".format(s["id"], "评测题" if s["split"] == "test" else "待提炼"))


if __name__ == "__main__":
    main()
