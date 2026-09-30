#!/usr/bin/env python3
"""生成可分享的分身画像卡片。仅依赖标准库。

  python card.py [card.json]   默认读取 ~/.i2i/card.json，输出 ~/.i2i/card.html

card.json 由 agent 根据 profile.md 撰写：
{
  "persona": "称号（4-10 字）",
  "tagline": "一句话说明（30 字以内）",
  "axes": [{"left": "先想清楚", "right": "先做出来", "value": 30}],   // value 0-100，越大越靠右
  "rules": [{"id": "R1", "text": "规则的短句（26 字以内）"}],
  "words": ["口头禅"]
}
统计数字和命中率由脚本从数据目录直接读取，不接受手填。
"""
import html
import json
import re
import sys

from extract import HOME

REPO = "github.com/LStarlling/i2i"
MIN_QUESTIONS = 10  # 考题少于这个数时分数波动太大，卡片上不显示


def esc(s):
    return html.escape(str(s))


def score(kind):
    path = HOME / "eval" / "history.jsonl"
    rows = []
    if path.exists():
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if not r.get("污染") and r.get("类型", "选择题") == kind]
    n = sum(r["题数"] for r in rows)
    if not n:
        return None
    avg = lambda k: sum(r[k] * r["题数"] for r in rows) / n
    if kind == "选择题":
        return {"n": n, "hit": avg("命中率"), "base": max(avg("只选推荐项命中率"), avg("随机猜命中率")),
                "label": "猜中真实选择", "base_name": "只选推荐"}
    return {"n": n, "hit": avg("命中率"), "base": avg("一律猜多数类命中率"),
            "label": "预判是否打回 AI", "base_name": "一律猜" + rows[-1]["多数类"]}


def stats():
    signals = sum(1 for l in open(HOME / "signals.jsonl", encoding="utf-8") if l.strip())
    profile = (HOME / "profile.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"^- \[(R\d+)\]", profile, re.M))
    formal = len(re.findall(r"^- \[R\d+\]", profile.split("## 待验证")[0], re.M))
    return signals, formal, ids


def render(c):
    signals, formal, ids = stats()
    bad = [r["id"] for r in c.get("rules", []) if r.get("id") not in ids]
    if bad:
        sys.exit("card.json 引用了档案中不存在的规则：" + ", ".join(bad))

    axes = ""
    for a in c.get("axes", [])[:4]:
        v = min(max(int(a["value"]), 0), 100)
        l_on, r_on = (' class="on"', "") if v < 50 else ("", ' class="on"') if v > 50 else ("", "")
        axes += ('<div class="axis"><span{}>{}</span><i class="track"><b class="dot" style="left:{}%"></b></i>'
                 '<span{}>{}</span></div>').format(l_on, esc(a["left"]), v, r_on, esc(a["right"]))
    rules = "".join('<li><code>{}</code><span>{}</span></li>'.format(esc(r["id"]), esc(r["text"]))
                    for r in c.get("rules", [])[:3])
    words = "".join("<span>{}</span>".format(esc(w)) for w in c.get("words", [])[:5])

    metrics = [m for m in (score("选择题"), score("打回题")) if m and m["n"] >= MIN_QUESTIONS]
    foot = "".join(
        '<div class="metric"><p class="label">{}</p><p class="score">{:.0f}<small>%</small></p>'
        '<p class="cmp">{} {:.0f}%<br>{} 道没学过的题</p></div>'.format(
            m["label"], m["hit"] * 100, m["base_name"], m["base"] * 100, m["n"]) for m in metrics)
    if not metrics:
        foot = '<div class="metric"><p class="label">猜中真实选择</p><p class="score">?</p><p class="cmp">考题不足 {} 道<br>暂不显示分数</p></div>'.format(MIN_QUESTIONS)

    return TEMPLATE.format(
        persona=esc(c["persona"]), tagline=esc(c.get("tagline", "")), signals=signals, formal=formal,
        axes=axes, rules=rules, words=words, foot=foot, repo=REPO)


TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>我的数字分身</title>
<style>
:root {{ --ink:#18191b; --sub:#5b5e64; --line:#d9d9d3; --paper:#f7f7f4; --accent:#e0492a; --bg:#e6e6e0; --hint:#6f7278; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141516; --hint:#9a9da3; }} }}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); min-height:100dvh; display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:16px; padding:24px 16px; font-family:"PingFang SC","Noto Sans SC","Microsoft YaHei",system-ui,sans-serif; -webkit-font-smoothing:antialiased; }}
.card {{ width:540px; height:720px; flex:none; background:var(--paper); color:var(--ink); border-radius:20px; padding:40px 40px 30px;
  display:flex; flex-direction:column; box-shadow:0 24px 60px -30px rgb(40 40 30 / .35); }}
.top {{ display:flex; justify-content:space-between; align-items:baseline; font-size:13px; color:var(--sub); }}
.brand {{ font-weight:700; color:var(--ink); font-size:14px; }}
.brand b {{ color:var(--accent); }}
h1 {{ font-size:46px; line-height:1.15; font-weight:800; margin-top:34px; }}
.tag {{ font-size:16px; color:var(--sub); margin-top:12px; line-height:1.55; }}
.axes {{ margin-top:34px; display:grid; gap:18px; }}
.axis {{ display:grid; grid-template-columns:76px 1fr 76px; align-items:center; font-size:13px; color:var(--sub); }}
.axis span:last-child {{ text-align:right; }}
.axis .on {{ color:var(--ink); font-weight:700; }}
.track {{ position:relative; height:1px; background:var(--line); margin:0 12px; }}
.dot {{ position:absolute; top:50%; width:12px; height:12px; border-radius:50%; background:var(--accent); transform:translate(-50%,-50%); }}
.rules {{ list-style:none; margin-top:36px; display:grid; gap:14px; }}
.rules li {{ display:grid; grid-template-columns:40px 1fr; font-size:16px; line-height:1.55; }}
.rules code, .score {{ font-family:"JetBrains Mono",Consolas,ui-monospace,monospace; }}
.rules code {{ font-size:12px; color:var(--accent); padding-top:3px; }}
.words {{ margin-top:26px; display:flex; flex-wrap:wrap; gap:8px; }}
.words span {{ font-size:13px; padding:4px 12px; border:1px solid var(--line); border-radius:999px; }}
.foot {{ margin-top:auto; display:flex; justify-content:space-between; align-items:flex-end; border-top:1px solid var(--line); padding-top:18px; }}
.metrics {{ display:flex; gap:28px; }}
.label {{ font-size:12px; color:var(--sub); }}
.score {{ font-size:44px; font-weight:700; line-height:1.1; color:var(--accent); }}
.score small {{ font-size:20px; margin-left:2px; }}
.cmp {{ font-size:12px; color:var(--sub); line-height:1.6; margin-top:4px; }}
.repo {{ text-align:right; font-size:12px; color:var(--sub); line-height:1.7; }}
.repo b {{ display:block; color:var(--ink); font-size:14px; }}
.hint {{ font-size:13px; color:var(--hint); }}
</style>
</head>
<body>
<article class="card" id="card">
  <header class="top"><span class="brand">I2I <b>数字分身</b></span><span>从 {signals} 条对话里学到 {formal} 条规则</span></header>
  <h1>{persona}</h1>
  <p class="tag">{tagline}</p>
  <section class="axes">{axes}</section>
  <ol class="rules">{rules}</ol>
  <div class="words">{words}</div>
  <footer class="foot"><div class="metrics">{foot}</div><div class="repo"><b>测测你的分身</b>{repo}</div></footer>
</article>
<p class="hint">截图这张卡片即可分享</p>
<script>
  var card = document.getElementById("card");
  function fit() {{ card.style.zoom = Math.min(1, (window.innerWidth - 32) / 540); }}
  fit(); window.addEventListener("resize", fit);
</script>
</body>
</html>
"""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else HOME / "card.json"
    c = json.loads(open(src, encoding="utf-8").read())
    out = HOME / "card.html"
    out.write_text(render(c), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
