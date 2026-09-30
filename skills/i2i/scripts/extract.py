#!/usr/bin/env python3
"""从本机 AI 对话记录中抽取偏好信号，增量写入 I2I 数据目录。仅依赖标准库。

信号类型：
  choice   你在结构化选择题里做出的选择（有标签，可客观评测）
  reaction 你对 AI 上一条回复的反应（纠正、否决、追加要求）
  said     你本人发出的消息原文（只用于学习表达风格）
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

# Windows 控制台默认编码打印中文会报错；log.py、score.py 导入本模块时同样生效
sys.stdout.reconfigure(encoding="utf-8")

HOME = Path(os.environ.get("I2I_HOME") or Path.home() / ".i2i")
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CHUNK = 120
TEST_PERCENT = 50

SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|xox[abp]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|\b[A-Fa-f0-9]{40,}\b)"
)
NOISE = (
    "<command-", "<local-command", "<system-reminder", "<environment_context",
    "<user_instructions", "<task-notification", "[Request interrupted", "Caveat:",
)


def sig_id(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:12]


def redact(s):
    return SECRET.sub("[已脱敏]", s.strip())


def head(s, cap):
    s = redact(s)
    return s if len(s) <= cap else s[:cap] + "…"


def tail(s, cap):
    s = redact(s)
    return s if len(s) <= cap else "…" + s[-cap:]


def is_noise(t):
    return not t or t.lstrip().startswith(NOISE)


def texts(content):
    if isinstance(content, str):
        return [content]
    return [x.get("text", "") for x in content or [] if isinstance(x, dict) and x.get("type") == "text"]


def reaction(source, key, project, ts, last_ai, text):
    return {
        "id": sig_id(source, key, text[:200]), "source": source, "project": project, "ts": ts,
        "kind": "reaction", "context": tail(last_ai, 600), "answer": head(text, 1500),
    }


def choice(source, key, project, ts, q, answer, note):
    labels = [o.get("label", "") for o in q.get("options", [])]
    picked = [l for l in labels if l and l in answer] or ["其他"]
    return {
        "id": sig_id(source, key, q.get("question", "")), "source": source, "project": project, "ts": ts,
        "kind": "choice", "context": redact(q.get("question", "")),
        "options": [{"label": o.get("label", ""), "description": o.get("description", "")} for o in q.get("options", [])],
        "multi": bool(q.get("multiSelect")), "answer": picked,
        "note": head(answer, 800) if picked == ["其他"] else head(note or "", 400),
    }


def claude_code():
    for f in glob.glob(str(CLAUDE_DIR / "projects" / "*" / "*.jsonl")):
        last_ai = ""
        for line in open(f, encoding="utf-8", errors="ignore"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            content = (d.get("message") or {}).get("content")
            project = Path(d.get("cwd") or "").name
            ts = d.get("timestamp", "")
            if d.get("type") == "assistant":
                for t in texts(content):
                    if t.strip():
                        last_ai = t
            elif d.get("type") == "user":
                r = d.get("toolUseResult")
                if isinstance(r, dict) and isinstance(r.get("answers"), dict) and r.get("questions"):
                    notes = r.get("annotations") or {}
                    for q in r["questions"]:
                        ans = r["answers"].get(q.get("question"))
                        if ans:
                            note = (notes.get(q.get("question")) or {}).get("notes", "")
                            yield choice("claude-code", d.get("uuid"), project, ts, q, ans, note)
                    continue
                if d.get("isMeta"):
                    continue
                t = "\n".join(texts(content)).strip()
                if is_noise(t):
                    continue
                yield reaction("claude-code", d.get("uuid"), project, ts, last_ai, t)
                last_ai = ""


def codex():
    for f in glob.glob(str(CODEX_DIR / "sessions" / "**" / "*.jsonl"), recursive=True):
        last_ai, project = "", ""
        for line in open(f, encoding="utf-8", errors="ignore"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            p = d.get("payload") or {}
            if d.get("type") == "session_meta":
                project = Path(p.get("cwd") or "").name
            if d.get("type") != "event_msg":
                continue
            if p.get("type") == "agent_message":
                last_ai = p.get("message", "")
            elif p.get("type") == "user_message":
                t = (p.get("message") or "").strip()
                if is_noise(t):
                    continue
                yield reaction("codex", f + d.get("timestamp", ""), project, d.get("timestamp", ""), last_ai, t)
                last_ai = ""


def mine(path):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    for t in re.split(r"\n\s*\n", raw):
        t = t.strip()
        if t:
            yield {"id": sig_id("mine", t), "source": "mine", "project": "", "ts": "",
                   "kind": "said", "answer": head(t, 1500)}


def main():
    ap = argparse.ArgumentParser(description="从本机 AI 对话记录抽取偏好信号")
    ap.add_argument("--mine", help="你本人发出的消息文本文件（消息之间空一行），用于学习表达风格")
    a = ap.parse_args()

    pending = HOME / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    store = HOME / "signals.jsonl"
    seen = set()
    if store.exists():
        seen = {json.loads(l)["id"] for l in open(store, encoding="utf-8") if l.strip()}

    sources = [claude_code(), codex()] + ([mine(a.mine)] if a.mine else [])
    new = []
    for src in sources:
        for s in src:
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            s["split"] = "test" if s["kind"] == "choice" and int(s["id"], 16) % 100 < TEST_PERCENT else "train"
            new.append(s)
    new.sort(key=lambda s: s["ts"])

    with open(store, "a", encoding="utf-8") as fp:
        for s in new:
            fp.write(json.dumps(s, ensure_ascii=False) + "\n")

    train = [s for s in new if s["split"] == "train"]
    stamp = time.strftime("%Y%m%d%H%M%S")
    for i in range(0, len(train), CHUNK):
        fn = pending / "chunk_{}_{:03d}.jsonl".format(stamp, i // CHUNK)
        fn.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in train[i:i + CHUNK]), encoding="utf-8")

    count = {}
    for s in new:
        k = s["source"] + "/" + s["kind"]
        count[k] = count.get(k, 0) + 1
    print(json.dumps({
        "数据目录": str(HOME), "本次新增": count, "累计信号": len(seen),
        "待提炼分块": sorted(p.name for p in pending.glob("*.jsonl")),
        "评测题（留出集）": sum(1 for l in open(store, encoding="utf-8")
                          if '"split": "test"' in l),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
