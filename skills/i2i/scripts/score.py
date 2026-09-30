#!/usr/bin/env python3
"""校准：用没参与学习的真实记录考分身。仅依赖标准库。

两类考题：
  选择题  你在结构化选择题里的真实选择
  打回题  AI 交出一版产出后，你是接受还是打回

  python score.py sample choice     生成选择题（不含答案）到 eval/questions.jsonl
  python score.py sample reaction   生成打回题（不含答案）到 eval/questions.jsonl
  python score.py label             打回题：预测写完后，输出你的真实回复到 eval/to_label.jsonl 供标注
  python score.py grade             评分，结果追加到 eval/history.jsonl

predictions.jsonl 每行：
  选择题 {"id": "...", "pick": ["选项标签"], "p": 0.72}
  打回题 {"id": "...", "verdict": "打回", "p": 0.7, "reason": "预计会挑的问题"}
label.jsonl 每行（标注时看不到预测）：{"id": "...", "truth": "接受", "complaint": "实际挑的问题"}

评过分的题记入 eval/used.txt，之后不再出题：猜错的题会被学进档案，再考只会虚高。
"""
import json
import sys
import time

from extract import HOME

EVAL = HOME / "eval"
USED = EVAL / "used.txt"
QUESTIONS = EVAL / "questions.jsonl"
PREDICTIONS = EVAL / "predictions.jsonl"
TO_LABEL = EVAL / "to_label.jsonl"
LABELS = EVAL / "label.jsonl"
REACTION_ROUND = 40  # 打回题每轮最多出题数，其余留给以后


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def pool(kind):
    used = set(USED.read_text(encoding="utf-8").split()) if USED.exists() else set()
    rows = [s for s in load(HOME / "signals.jsonl") if s.get("split") == "test" and s["id"] not in used]
    if kind == "choice":
        return [s for s in rows if s.get("options")]
    return [s for s in rows if s.get("kind") == "reaction" and s.get("context")][:REACTION_ROUND]


def write(path, rows):
    with open(path, "w", encoding="utf-8") as fp:
        fp.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def sample(kind):
    EVAL.mkdir(parents=True, exist_ok=True)
    keys = ("id", "project", "ts", "context", "options", "multi") if kind == "choice" else ("id", "project", "ts", "context")
    qs = [dict({k: s.get(k) for k in keys}, type=kind) for s in pool(kind)]
    write(QUESTIONS, qs)
    for p in (PREDICTIONS, TO_LABEL, LABELS):
        if p.exists():
            p.unlink()
    print(json.dumps({"题型": "选择题" if kind == "choice" else "打回题", "考题数": len(qs), "文件": str(QUESTIONS),
                      "提示": "少于 10 题时分数不可靠" if len(qs) < 10 else ""}, ensure_ascii=False, indent=2))


def label():
    if not PREDICTIONS.exists():
        sys.exit("先写完 predictions.jsonl 再标注，标注前不能看到真实回复")
    truth = {s["id"]: s for s in load(HOME / "signals.jsonl")}
    rows = [{"id": q["id"], "context": q["context"], "reply": truth[q["id"]]["answer"]}
            for q in load(QUESTIONS) if q.get("type") == "reaction"]
    write(TO_LABEL, rows)
    print(json.dumps({"待标注": len(rows), "文件": str(TO_LABEL), "写入": str(LABELS)}, ensure_ascii=False, indent=2))


def buckets_of(pairs):
    b = {}
    for prob, hit in pairs:
        k = "{}0%+".format(min(int(prob * 10), 9))
        n, h = b.get(k, (0, 0))
        b[k] = (n + 1, h + hit)
    return {k: "{}/{}".format(h, n) for k, (n, h) in sorted(b.items())}


def grade_choice(qs, preds):
    truth = {s["id"]: s for s in load(HOME / "signals.jsonl")}
    hits, brier, chance, rec, pairs, misses = 0, 0.0, 0.0, 0, [], []
    for p in preds:
        s = truth[p["id"]]
        hit = set(p.get("pick") or []) == set(s["answer"])
        prob = min(max(float(p.get("p", 0.5)), 0.0), 1.0)
        hits += hit
        brier += (prob - hit) ** 2
        chance += 1.0 / (len(s["options"]) + 1)  # 选项数 + “其他”
        rec += [o["label"] for o in s["options"] if "推荐" in o["label"] or "Recommended" in o["label"]] == s["answer"]
        pairs.append((prob, hit))
        if not hit:
            misses.append({"id": p["id"], "题目": s["context"][:80], "分身猜": p.get("pick"),
                           "你选": s["answer"], "你的补充": s.get("note", "")})
    n = len(preds)
    return {"类型": "选择题", "题数": n, "命中率": round(hits / n, 3), "随机猜命中率": round(chance / n, 3),
            "只选推荐项命中率": round(rec / n, 3), "Brier分数(越低越好)": round(brier / n, 3),
            "把握度分档实际命中": buckets_of(pairs)}, {"猜错的题": misses}


def grade_reaction(qs, preds):
    if not LABELS.exists() or LABELS.stat().st_mtime < PREDICTIONS.stat().st_mtime:
        sys.exit("先运行 score.py label 并写好 label.jsonl（必须晚于 predictions.jsonl）")
    labels = {l["id"]: l for l in load(LABELS)}
    preds = [p for p in preds if p["id"] in labels]
    if not preds:
        sys.exit("没有已标注的预测")
    hits, brier, pairs, reasons, misses = 0, 0.0, [], [], []
    for p in preds:
        t = labels[p["id"]]
        hit = p.get("verdict") == t["truth"]
        prob = min(max(float(p.get("p", 0.5)), 0.0), 1.0)
        p_back = prob if p.get("verdict") == "打回" else 1 - prob
        hits += hit
        brier += (p_back - (t["truth"] == "打回")) ** 2
        pairs.append((prob, hit))
        if hit and t["truth"] == "打回":
            reasons.append({"id": p["id"], "分身预计": p.get("reason", ""), "你实际": t.get("complaint", "")})
        if not hit:
            misses.append({"id": p["id"], "分身猜": p.get("verdict"), "你实际": t["truth"], "你挑的问题": t.get("complaint", "")})
    n = len(preds)
    back = sum(labels[p["id"]]["truth"] == "打回" for p in preds) / n
    major = "打回" if back >= 0.5 else "接受"
    return {"类型": "打回题", "题数": n, "命中率": round(hits / n, 3), "多数类": major,
            "一律猜多数类命中率": round(max(back, 1 - back), 3), "Brier分数(越低越好)": round(brier / n, 3),
            "把握度分档实际命中": buckets_of(pairs)}, {"猜对打回时的理由对照": reasons, "猜错的题": misses}


def grade():
    qs = load(QUESTIONS)
    ids = {q["id"] for q in qs}
    preds = [p for p in load(PREDICTIONS) if p.get("id") in ids]
    if not preds:
        sys.exit("没有可评分的预测")
    kind = qs[0].get("type", "choice")
    result, detail = (grade_choice if kind == "choice" else grade_reaction)(qs, preds)
    result = dict({"时间": time.strftime("%Y-%m-%d %H:%M")}, **result)
    with open(EVAL / "history.jsonl", "a", encoding="utf-8") as fp:
        fp.write(json.dumps(result, ensure_ascii=False) + "\n")
    with open(USED, "a", encoding="utf-8") as fp:
        fp.write("".join(p["id"] + "\n" for p in preds))
    result.update(detail)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1:] or [""]
    if cmd[0] == "sample" and len(cmd) > 1 and cmd[1] in ("choice", "reaction"):
        sample(cmd[1])
    elif cmd[0] == "label":
        label()
    elif cmd[0] == "grade":
        grade()
    else:
        sys.exit(__doc__)
