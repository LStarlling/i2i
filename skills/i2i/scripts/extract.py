#!/usr/bin/env python3
"""从本机 AI 对话记录中抽取偏好信号，增量写入 I2I 数据目录。仅依赖标准库。

信号类型：
  choice   你在结构化选择题里做出的选择（有标签，可客观评测）
  reaction 你对 AI 上一条回复的反应（纠正、否决、追加要求）
  said     你本人发出的消息原文（只用于学习表达风格）

导入聊天内容的那条用户消息里夹着别人的话：agent 随后会调用 log.py said，
抽取时据此把这条消息丢掉，不当作 reaction。
"""
import argparse
import csv
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
sys.stderr.reconfigure(encoding="utf-8")

HOME = Path(os.environ.get("I2I_HOME") or Path.home() / ".i2i")
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CHUNK = 120
TEST_PERCENT = 50           # 选择题留作考题的比例
REACTION_TEST_PERCENT = 20  # 对 AI 回复的反应留作打回题的比例

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


IMPORT_MARK = "log.py said"


def claude_code(files=None):
    for f in files or glob.glob(str(CLAUDE_DIR / "projects" / "*" / "*.jsonl")):
        last_ai, held = "", None
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
                if isinstance(content, list) and any(
                        x.get("type") == "tool_use" and IMPORT_MARK in json.dumps(x.get("input"), ensure_ascii=False)
                        for x in content if isinstance(x, dict)):
                    held = None
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
                if held:
                    yield held
                held = reaction("claude-code", d.get("uuid"), project, ts, last_ai, t)
                last_ai = ""
        if held:
            yield held


def codex():
    for f in glob.glob(str(CODEX_DIR / "sessions" / "**" / "*.jsonl"), recursive=True):
        last_ai, project, held = "", "", None
        for line in open(f, encoding="utf-8", errors="ignore"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            p = d.get("payload") or {}
            if d.get("type") == "session_meta":
                project = Path(p.get("cwd") or "").name
            if d.get("type") == "response_item" and p.get("type") in ("function_call", "custom_tool_call")                     and IMPORT_MARK in json.dumps(p, ensure_ascii=False):
                held = None
            if d.get("type") != "event_msg":
                continue
            if p.get("type") == "agent_message":
                last_ai = p.get("message", "")
            elif p.get("type") == "user_message":
                t = (p.get("message") or "").strip()
                if is_noise(t):
                    continue
                if held:
                    yield held
                held = reaction("codex", f + d.get("timestamp", ""), project, d.get("timestamp", ""), last_ai, t)
                last_ai = ""
        if held:
            yield held


def mine(path):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    for t in re.split(r"\n\s*\n", raw):
        t = t.strip()
        if t:
            yield {"id": sig_id("mine", t), "source": "mine", "project": "", "ts": "",
                   "kind": "said", "answer": head(t, 1500)}


def chatgpt(conv):
    """ChatGPT 导出：mapping 是消息树，从 current_node 沿 parent 回溯得到当前分支。"""
    mapping = conv.get("mapping") or {}
    node = conv.get("current_node")
    chain = []
    while node and node in mapping:
        chain.append(mapping[node])
        node = mapping[node].get("parent")
    for n in reversed(chain):
        m = n.get("message") or {}
        role = (m.get("author") or {}).get("role")
        parts = (m.get("content") or {}).get("parts") or []
        text = "\n".join(x for x in parts if isinstance(x, str)).strip()
        if role in ("user", "assistant") and text:
            yield role, m.get("id") or n.get("id"), m.get("create_time"), text


def claude_web(conv):
    """Claude 导出：chat_messages 已按顺序排列，sender 为 human / assistant。"""
    for m in conv.get("chat_messages") or []:
        text = (m.get("text") or "").strip() or "\n".join(
            x.get("text", "") for x in m.get("content") or [] if isinstance(x, dict) and x.get("type") == "text").strip()
        role = {"human": "user", "assistant": "assistant"}.get(m.get("sender"))
        if role and text:
            yield role, m.get("uuid"), m.get("created_at"), text


def ai_export(path):
    """网页版 AI 对话的官方导出文件（conversations.json），自动识别 ChatGPT 或 Claude。"""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        sys.exit("{}：不是对话数组，请提供导出包里的 conversations.json".format(path))
    for conv in data:
        if "mapping" in conv:
            source, walk = "chatgpt", chatgpt(conv)
        elif "chat_messages" in conv:
            source, walk = "claude-web", claude_web(conv)
        else:
            continue
        key = conv.get("id") or conv.get("uuid") or conv.get("conversation_id") or ""
        title = (conv.get("title") or conv.get("name") or "")[:40]
        last_ai = ""
        for role, mid, ts, text in walk:
            if role == "assistant":
                last_ai = text
                continue
            if is_noise(text):
                continue
            ts = ts if isinstance(ts, str) else (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) if ts else "")
            yield reaction(source, key + "/" + str(mid), title, ts, last_ai, text)
            last_ai = ""


COLUMNS = {
    "sender": ("发送人", "发送者", "昵称", "sender", "Sender", "NickName", "talker"),
    "self": ("是否本人", "is_self", "IsSender"),
    "content": ("内容", "消息内容", "content", "StrContent", "message", "text"),
    "time": ("时间", "time", "StrTime", "CreateTime", "timestamp"),
}
PLACEHOLDER = re.compile(r"^\[[^\]]{1,8}\]$")  # [图片] [表情] 这类非文字消息


def chat(path, me, to):
    """通用聊天导出文件（CSV 或 JSON 数组）。只保留本人消息，对方上一句压缩为情境。"""
    p = Path(path)
    if p.suffix.lower() == ".json":
        rows = json.loads(p.read_text(encoding="utf-8-sig"))
    else:
        rows = list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))
    if not rows:
        return
    col = {k: next((c for c in names if c in rows[0]), None) for k, names in COLUMNS.items()}
    if not col["content"] or not (col["self"] or (col["sender"] and me)):
        sys.exit("无法识别 {} 的列：需要内容列，以及“是否本人”列或“发送人”列加 --me。现有列：{}".format(
            p.name, ", ".join(rows[0].keys())))
    prev = ""
    for r in rows:
        text = str(r.get(col["content"]) or "").strip()
        if not text or PLACEHOLDER.match(text) or text.startswith("<"):
            continue
        if col["self"]:
            is_me = str(r.get(col["self"])).strip().lower() in ("1", "true", "是", "yes")
        else:
            is_me = str(r.get(col["sender"]) or "").strip() == me
        if not is_me:
            prev = text
            continue
        ts = str(r.get(col["time"]) or "") if col["time"] else ""
        yield {"id": sig_id("chat", ts, text), "source": "chat", "project": "", "ts": ts, "kind": "said",
               "to": to, "context": tail(prev, 200), "answer": head(text, 1500)}
        prev = ""


def is_test(s):
    bucket = int(s["id"], 16) % 100
    if s["kind"] == "choice":
        return bucket < TEST_PERCENT
    return s["kind"] == "reaction" and bool(s.get("context")) and bucket < REACTION_TEST_PERCENT


def rebuild(store, pending):
    """升级后可选：按当前规则重新划分考题。评过分的考题已经用完，改为训练数据。"""
    used_file = HOME / "eval" / "used.txt"
    used = set(used_file.read_text(encoding="utf-8").split()) if used_file.exists() else set()
    rows = [json.loads(l) for l in open(store, encoding="utf-8") if l.strip()]
    for s in rows:
        s["split"] = "test" if is_test(s) and s["id"] not in used else "train"
    rows.sort(key=lambda s: s.get("ts", ""))
    store.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in rows), encoding="utf-8")
    for f in pending.glob("*.jsonl"):
        f.unlink()
    return [s for s in rows if s["split"] == "train"]


def main():
    ap = argparse.ArgumentParser(description="从本机 AI 对话记录抽取偏好信号")
    ap.add_argument("--mine", help="你本人发出的消息文本文件（消息之间空一行），用于学习表达风格")
    ap.add_argument("--chat", nargs="+", help="聊天导出文件（CSV 或 JSON），一个文件对应一个聊天对象")
    ap.add_argument("--me", default="", help="你在聊天里的昵称（导出文件没有“是否本人”列时必填）")
    ap.add_argument("--to", default="", help="聊天对象：上级、同事、朋友、家人等")
    ap.add_argument("--ai-export", nargs="+", help="网页版 AI 的导出文件 conversations.json（ChatGPT、Claude），可多个")
    ap.add_argument("--transcript", help="只处理这一份 Claude Code 对话记录（会话结束钩子用，追求快）")
    ap.add_argument("--rebuild", action="store_true",
                    help="按当前规则重新划分全部已存信号，并把全部训练信号重新放入待提炼分块（不删除任何数据）")
    a = ap.parse_args()

    pending = HOME / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    inbox = HOME / "inbox"
    inbox.mkdir(exist_ok=True)
    store = HOME / "signals.jsonl"
    seen = set()
    if store.exists():
        seen = {json.loads(l)["id"] for l in open(store, encoding="utf-8") if l.strip()}

    sources = [claude_code([a.transcript])] if a.transcript else [claude_code(), codex()]
    sources += [mine(a.mine)] if a.mine else []
    sources += [chat(f, a.me, a.to) for f in a.chat or []]
    sources += [ai_export(f) for f in a.ai_export or []]
    new = []
    for src in sources:
        for s in src:
            if s["id"] in seen:
                continue
            seen.add(s["id"])
            s["split"] = "test" if is_test(s) else "train"
            new.append(s)
    new.sort(key=lambda s: s["ts"])

    with open(store, "a", encoding="utf-8") as fp:
        for s in new:
            fp.write(json.dumps(s, ensure_ascii=False) + "\n")

    train = [s for s in new if s["split"] == "train"]
    if a.rebuild:
        train = rebuild(store, pending)
    stamp = time.strftime("%Y%m%d%H%M%S")
    for i in range(0, len(train), CHUNK):
        fn = pending / "chunk_{}_{:03d}.jsonl".format(stamp, i // CHUNK)
        fn.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in train[i:i + CHUNK]), encoding="utf-8")

    tests = [json.loads(l) for l in open(store, encoding="utf-8") if '"split": "test"' in l]
    count = {}
    for s in new:
        k = s["source"] + "/" + s["kind"]
        count[k] = count.get(k, 0) + 1
    print(json.dumps({
        "版本": (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip(),
        "数据目录": str(HOME), "本次新增": count, "累计信号": len(seen),
        "待提炼分块": sorted(p.name for p in pending.glob("*.jsonl")),
        "考题（留出集）": {"选择题": sum(1 for s in tests if s["kind"] == "choice"),
                         "打回题": sum(1 for s in tests if s["kind"] == "reaction")},
        "收件箱待导入截图": sum(1 for p in inbox.iterdir() if p.is_file()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
