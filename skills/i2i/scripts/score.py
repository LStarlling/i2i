#!/usr/bin/env python3
"""校准：用留出的真实选择题，测分身猜中你的比例和把握度是否可信。仅依赖标准库。

  python score.py sample   生成考题（不含答案）到 eval/questions.jsonl
  python score.py grade    读取 eval/predictions.jsonl 评分，结果追加到 eval/history.jsonl

评过分的题记入 eval/used.txt，之后不再出题：猜错的题会被学进档案，再考只会虚高。

predictions.jsonl 每行：{"id": "...", "pick": ["选项标签"], "p": 0.72}
"""
import json
import sys
import time

from extract import HOME

EVAL = HOME / "eval"
USED = EVAL / "used.txt"


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def tests():
    used = set(USED.read_text(encoding="utf-8").split()) if USED.exists() else set()
    return [s for s in load(HOME / "signals.jsonl")
            if s.get("split") == "test" and s.get("options") and s["id"] not in used]


def sample():
    EVAL.mkdir(parents=True, exist_ok=True)
    qs = tests()
    with open(EVAL / "questions.jsonl", "w", encoding="utf-8") as fp:
        for s in qs:
            q = {k: s.get(k) for k in ("id", "project", "ts", "context", "options", "multi")}
            fp.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(json.dumps({"考题数": len(qs), "文件": str(EVAL / "questions.jsonl"),
                      "提示": "少于 10 题时分数不可靠，建议先做快问快答" if len(qs) < 10 else ""},
                     ensure_ascii=False, indent=2))


def grade():
    truth = {s["id"]: s for s in tests()}
    preds = [p for p in load(EVAL / "predictions.jsonl") if p.get("id") in truth]
    if not preds:
        sys.exit("没有可评分的预测")
    hits, brier, chance, rec = 0, 0.0, 0.0, 0
    buckets = {}
    for p in preds:
        s = truth[p["id"]]
        hit = set(p.get("pick") or []) == set(s["answer"])
        rec += [o["label"] for o in s["options"] if "推荐" in o["label"] or "Recommended" in o["label"]] == s["answer"]
        prob = min(max(float(p.get("p", 0.5)), 0.0), 1.0)
        hits += hit
        brier += (prob - hit) ** 2
        chance += 1.0 / (len(s["options"]) + 1)  # 选项数 + “其他”
        b = "{}0%+".format(min(int(prob * 10), 9))
        n, h = buckets.get(b, (0, 0))
        buckets[b] = (n + 1, h + hit)
    n = len(preds)
    result = {
        "时间": time.strftime("%Y-%m-%d %H:%M"), "题数": n,
        "命中率": round(hits / n, 3), "随机猜命中率": round(chance / n, 3),
        "只选推荐项命中率": round(rec / n, 3),
        "Brier分数(越低越好)": round(brier / n, 3),
        "把握度分档实际命中": {k: "{}/{}".format(h, c) for k, (c, h) in sorted(buckets.items())},
    }
    with open(EVAL / "history.jsonl", "a", encoding="utf-8") as fp:
        fp.write(json.dumps(result, ensure_ascii=False) + "\n")
    with open(USED, "a", encoding="utf-8") as fp:
        fp.write("".join(p["id"] + "\n" for p in preds))
    misses = [{"id": p["id"], "题目": truth[p["id"]]["context"][:80], "分身猜": p.get("pick"),
               "你选": truth[p["id"]]["answer"], "你的补充": truth[p["id"]].get("note", "")}
              for p in preds if set(p.get("pick") or []) != set(truth[p["id"]]["answer"])]
    result["猜错的题"] = misses
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    {"sample": sample, "grade": grade}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
