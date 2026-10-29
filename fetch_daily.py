# -*- coding: utf-8 -*-
"""
AI 资讯日报抓取脚本（个人版）
流程：抓取信息源 RSS → 调用大模型生成中文摘要 → 生成 index.html
每天由 GitHub Actions 自动运行一次，也可本地手动运行：python fetch_daily.py
"""
import os
import re
import html
import datetime

import requests
import feedparser

# ================== 你以后主要改这里：信息源列表 ==================
# (显示名称, RSS 地址)。想换源/加源就改这个列表，其他代码不用动。
FEEDS = [
    ("量子位", "https://www.qbitai.com/feed"),
    ("36氪资讯", "https://36kr.com/feed"),
    ("少数派", "https://sspai.com/feed"),
    ("阮一峰科技爱好者周刊", "https://www.ruanyifeng.com/blog/atom.xml"),
]

MAX_PER_FEED = 8      # 每个源最多取几条
TIMEOUT = 20          # 网络超时（秒）


def clean_text(s: str, limit: int = 300) -> str:
    """去掉 HTML 标签，截断长度"""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def fetch_all():
    """抓取所有信息源，返回条目列表"""
    items = []
    for name, url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:MAX_PER_FEED]:
                title = clean_text(getattr(e, "title", ""), 120)
                link = getattr(e, "link", "")
                summary = clean_text(getattr(e, "summary", ""))
                if title and link:
                    items.append({"source": name, "title": title,
                                  "link": link, "summary": summary})
        except Exception as exc:  # 单个源挂掉不影响整体
            print(f"[warn] {name} 抓取失败: {exc}")
    return items


def call_llm(items):
    """调用大模型生成日报正文（Markdown 格式）"""
    api_key = os.environ.get("API_KEY", "")
    if not api_key or not items:
        return None

    api_base = os.environ.get("API_BASE") or "https://api.deepseek.com"
    model = os.environ.get("API_MODEL") or "deepseek-chat"

    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it['source']}] {it['title']} | {it['summary']}")
    material = "\n".join(lines)

    today = datetime.date.today().strftime("%Y-%m-%d")
    prompt = f"""你是"AI 资讯日报"的编辑。下面是今天({today})抓取到的原始条目。
请生成一份中文日报，要求：
1. 按内容分成 2-4 个栏目（如：AI 趋势 / 产品与工具 / 赚钱与机会 / 值得一看）
2. 每条：**一句话加粗标题** + 1-2 句摘要 + （来源：xxx）
3. 删掉明显是软文、标题党、无实质内容的条目，宁缺毋滥
4. 最多保留 12 条
5. 只输出日报正文，不要解释

原始条目：
{material}"""

    try:
        resp = requests.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"[warn] 大模型调用失败: {exc}")
        return None


def md_to_html(md: str) -> str:
    """极简 Markdown 转 HTML（标题/加粗/链接/换行），够日报用"""
    out = []
    for line in md.splitlines():
        line = line.strip()
        if not line:
            continue
        esc = html.escape(line)
        # 链接 [text](url)
        esc = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
                     r'<a href="\2" target="_blank">\1</a>', esc)
        # 加粗
        esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
        if esc.startswith("### "):
            out.append(f"<h3>{esc[4:]}</h3>")
        elif esc.startswith("## "):
            out.append(f"<h2>{esc[3:]}</h2>")
        elif esc.startswith("# "):
            out.append(f"<h1>{esc[2:]}</h1>")
        else:
            out.append(f"<p>{esc}</p>")
    return "\n".join(out)


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: "Microsoft YaHei", sans-serif; max-width: 760px;
         margin: 0 auto; padding: 24px 16px; color: #222; line-height: 1.7; }}
  h1 {{ font-size: 22px; }} h2 {{ border-left: 4px solid #2563eb;
       padding-left: 8px; font-size: 18px; }} h3 {{ font-size: 16px; }}
  a {{ color: #2563eb; text-decoration: none; }}
  footer {{ color: #888; font-size: 13px; margin-top: 32px;
            border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
{body}
<footer>由 GitHub Actions 每天自动抓取生成 · {title}</footer>
</body>
</html>"""


def build_fallback(items):
    """没有大模型时的兜底：纯标题列表"""
    rows = "".join(
        f"<p><b>[{html.escape(it['source'])}]</b> "
        f'<a href="{html.escape(it["link"])}" target="_blank">'
        f"{html.escape(it['title'])}</a></p>"
        for it in items
    )
    return f"<h1>今日资讯</h1>{rows}" if items else "<p>今天没有抓到内容。</p>"


def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"开始生成 {today} 的日报 ...")
    items = fetch_all()
    print(f"共抓到 {len(items)} 条")

    md = call_llm(items)
    if md:
        body = md_to_html(md)
    else:
        body = build_fallback(items)

    page = PAGE.format(title=f"AI 资讯日报 {today}", body=body)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("已生成 index.html")


if __name__ == "__main__":
    main()
