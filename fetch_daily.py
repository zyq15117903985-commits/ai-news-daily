# -*- coding: utf-8 -*-
"""
AI 资讯日报抓取脚本（个人版 v3）
流程：抓取信息源 RSS → 调用大模型生成中文摘要 → 生成 index.html + 往期存档
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
    ("爱范儿", "https://www.ifanr.com/feed"),
    ("阮一峰科技爱好者周刊", "https://www.ruanyifeng.com/blog/atom.xml"),
]

MAX_PER_FEED = 8       # 每个源最多取几条
MAX_TOTAL = 30         # 总共最多取几条
TIMEOUT = 20           # 网络超时（秒）


def clean_text(s: str, limit: int = 300) -> str:
    """去掉 HTML 标签，截断长度"""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def fetch_all():
    """抓取所有信息源，轮流均匀混合（避免单一来源刷屏），按标题去重"""
    per_feed = []          # 每个源各自的条目列表
    seen = set()
    for name, url in FEEDS:
        got = []
        try:
            feed = feedparser.parse(url)
            for e in feed.entries:
                if len(got) >= MAX_PER_FEED:
                    break
                title = clean_text(getattr(e, "title", ""), 120)
                link = getattr(e, "link", "")
                summary = clean_text(getattr(e, "summary", ""))
                if title and link and title not in seen:
                    seen.add(title)
                    got.append({"source": name, "title": title,
                                "link": link, "summary": summary})
        except Exception as exc:  # 单个源挂掉不影响整体
            print(f"[warn] {name} 抓取失败: {exc}")
        per_feed.append(got)

    # 轮流从各源取：第 1 条、第 2 条……保证来源均衡
    items, idx = [], 0
    while len(items) < MAX_TOTAL:
        added = False
        for got in per_feed:
            if idx < len(got):
                items.append(got[idx])
                added = True
                if len(items) >= MAX_TOTAL:
                    break
        if not added:
            break
        idx += 1

    for name, _ in FEEDS:
        n = sum(1 for it in items if it["source"] == name)
        print(f"  来源 {name}: {n} 条")
    return items


def call_llm(items):
    """调用大模型生成日报正文（Markdown 格式，标题带原文链接）"""
    api_key = os.environ.get("API_KEY", "")
    if not api_key or not items:
        return None

    api_base = os.environ.get("API_BASE") or "https://api.deepseek.com"
    model = os.environ.get("API_MODEL") or "deepseek-chat"

    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it['source']}]\n   标题: {it['title']}\n"
                     f"   链接: {it['link']}\n   摘要: {it['summary']}")
    material = "\n".join(lines)

    today = datetime.date.today().strftime("%Y-%m-%d")
    prompt = f"""你是"AI 资讯日报"的编辑。下面是今天({today})抓取到的原始条目。
请生成一份中文日报，要求：
1. 开头先写一段「## 今日速览」，用 2-3 句话概括今天最值得关注的动向
2. 然后按内容分成 3-5 个栏目（如：AI 趋势 / 产品与工具 / 商业与钱 / 值得一看），栏目用 ## 开头
3. 每条格式必须是：**[标题](链接)**：1-2 句摘要（来源：xxx）——标题要用 [标题](链接) 形式带上原文链接，链接从下面给的条目里原样复制
4. **每个来源至少保留 2 条**（除非该来源的内容确实全是广告），保证来源多样
5. 总共保留 15-20 条；只删除明显软文和一周以上的过期内容，不要因为"不够重要"而删
6. 只输出日报正文，不要解释

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


def list_archive():
    """列出往期存档文件，返回 [(日期, 文件名)]，按日期倒序"""
    result = []
    try:
        if os.path.isdir("archive"):
            for fn in os.listdir("archive"):
                m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", fn)
                if m:
                    result.append((m.group(1), fn))
    except Exception:
        pass
    result.sort(reverse=True)
    return result[:14]


CSS = """
  * { box-sizing: border-box; }
  body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
         margin: 0; padding: 0; background: #f5f7fa; color: #1f2937;
         line-height: 1.75; }
  .wrap { max-width: 780px; margin: 0 auto; padding: 0 16px 40px; }
  header.hero { background: linear-gradient(135deg, #1e3a8a, #2563eb 60%, #3b82f6);
         color: #fff; padding: 36px 16px 28px; }
  header.hero .wrap { padding-bottom: 0; }
  header.hero h1 { margin: 0 0 6px; font-size: 26px; }
  header.hero .date { color: #bfdbfe; font-size: 14px; }
  .card { background: #fff; border-radius: 12px; padding: 22px 24px;
          margin-top: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.06); }
  h2 { font-size: 18px; margin: 26px 0 10px; padding-left: 10px;
       border-left: 4px solid #2563eb; }
  h3 { font-size: 16px; }
  p { margin: 10px 0; }
  a { color: #2563eb; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .tag { display: inline-block; background: #eff6ff; color: #2563eb;
         border-radius: 4px; font-size: 12px; padding: 1px 8px;
         margin-left: 6px; vertical-align: middle; }
  .archive-list { list-style: none; padding: 0; margin: 0; }
  .archive-list li { padding: 4px 0; border-bottom: 1px dashed #e5e7eb; }
  footer { text-align: center; color: #9ca3af; font-size: 13px;
           margin-top: 30px; }
"""


def build_page(title: str, body: str) -> str:
    """组装完整页面（含报头/样式/往期存档）"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    archive = list_archive()
    if archive:
        rows = "".join(
            f'<li>{d} · <a href="archive/{fn}" target="_blank">查看该日日报</a></li>'
            for d, fn in archive if fn != f"{today}.html"
        )
        archive_html = (f'<div class="card"><h2>往期存档</h2>'
                        f'<ul class="archive-list">{rows}</ul></div>') if rows else ""
    else:
        archive_html = ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<header class="hero"><div class="wrap">
  <h1>📰 AI 资讯日报</h1>
  <div class="date">{title} · 每天早上 7 点自动更新</div>
</div></header>
<div class="wrap">
  <div class="card">
{body}
  </div>
{archive_html}
<footer>由 GitHub Actions 每天自动抓取生成 · {title}</footer>
</div>
</body>
</html>"""


def build_fallback(items):
    """没有大模型时的兜底：带链接的标题列表"""
    rows = "".join(
        f"<p><b>[{html.escape(it['source'])}]</b> "
        f'<a href="{html.escape(it["link"])}" target="_blank">'
        f"{html.escape(it['title'])}</a></p>"
        for it in items
    )
    return f"<p>今日共抓到 {len(items)} 条（AI 摘要生成失败，以下为原始标题）：</p>{rows}" if items else "<p>今天没有抓到内容。</p>"


def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    print(f"开始生成 {today} 的日报 ...")
    items = fetch_all()
    print(f"共抓到 {len(items)} 条")

    md = call_llm(items)
    body = md_to_html(md) if md else build_fallback(items)
    title = f"AI 资讯日报 {today}"

    # 当日首页
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(build_page(title, body))

    # 往期存档（今天这份也存一份）
    os.makedirs("archive", exist_ok=True)
    with open(f"archive/{today}.html", "w", encoding="utf-8") as f:
        f.write(build_page(title, body))

    print("已生成 index.html 和往期存档")


if __name__ == "__main__":
    main()
