# 我的 AI 资讯日报

每天早上 7 点自动抓取信息源 → 大模型生成摘要 → 发布成网页。

## 网址

`https://你的GitHub用户名.github.io/ai-news-daily/`

（在仓库 Settings → Pages 里开启后生效）

## 要配置的东西

仓库 Settings → Secrets and variables → Actions → New repository secret：

| 名称 | 值 | 必填 |
|---|---|---|
| `API_KEY` | 你的 DeepSeek 或智谱 API Key | 是 |
| `API_BASE` | DeepSeek 用 `https://api.deepseek.com`；智谱用 `https://open.bigmodel.cn/api/paas/v4` | 否（不填默认 DeepSeek） |
| `API_MODEL` | DeepSeek 填 `deepseek-chat`；智谱填 `glm-4-flash` | 否（不填默认 deepseek-chat） |

## 想换信息源

改 `fetch_daily.py` 最上面的 `FEEDS` 列表即可。

## 手动跑一次

仓库 Actions 页 → 左边 daily-news → Run workflow。
