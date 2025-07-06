import os
import re
import json
import requests
from datetime import datetime
from collections import defaultdict
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=" + API_KEY

INPUT_JSON = "conversations.json"
OUTPUT_DIR = "output"
FILTER_SUFFIX = "_米国株"
INDEX_HTML = "index.html"

HTML_TEMPLATE = """
<html>
<head>
  <meta charset='utf-8'>
  <title>{title}</title>
  <style>
    body {{
      font-family: sans-serif;
      margin: 40px;
    }}
    pre {{
      white-space: pre-wrap;
      word-break: break-word;
      background-color: #f5f5f5;
      padding: 1em;
      border-radius: 6px;
    }}
    h2 {{
      border-bottom: 1px solid #ccc;
      padding-bottom: 0.2em;
      margin-top: 2em;
    }}
  </style>
</head>
<body>
  <h1>{title} - 分析要約履歴</h1>
  {content}
</body>
</html>
"""

def extract_existing_dates(html_path):
    if not os.path.exists(html_path):
        return set()
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    return {h2.text.strip() for h2 in soup.find_all("h2")}

def extract_date_from_text(text):
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return None

def summarize_with_gemini(text):
    try:
        prompt = f"""
以下は株式銘柄に関する1日分の分析会話の記録です。
この内容をもとに、以下のフォーマットで要点を箇条書きで整理してください。

---

分析結果の要約（300字程度）：

短期的目線の分析（150字程度）：

中期的目線の分析（150字程度）：

長期的目線の分析（150字程度）：

最新の状況（40字程度）：

いつ買うべきか（40字程度）：

---

【会話記録】
{text}
"""
        response = requests.post(
            API_URL,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1024}
            },
            timeout=30
        )
        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print("[エラー] 要約失敗:", e)
        return "要約エラー"

def get_latest_update_date():
    date_pattern = re.compile(r"<h2>(\d{4}-\d{2}-\d{2})</h2>")
    latest = ""
    for file in Path(OUTPUT_DIR).glob("*.html"):
        content = file.read_text(encoding="utf-8")
        dates = date_pattern.findall(content)
        if dates:
            newest = max(dates)
            if newest > latest:
                latest = newest
    return latest

import regex  # ← 追加！

def extract_summary_lines(html_path):
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
        h2_tags = soup.find_all("h2")
        if not h2_tags:
            return "記載なし", "記載なし"
        latest_h2 = h2_tags[-1]
        pre = latest_h2.find_next("pre")
        if not pre:
            return "記載なし", "記載なし"
        text = pre.text

        # 柔軟な正規表現に修正
        latest_status = re.search(r"最新の状況[（(（]?.*?[)））]?[：:]?\s*\n(.+)", text)
        timing_advice = re.search(r"いつ買うべきか[（(（]?.*?[)））]?[：:]?\s*\n(.+)", text)

        return (
            latest_status.group(1).strip() if latest_status else "記載なし",
            timing_advice.group(1).strip() if timing_advice else "記載なし"
        )
    except Exception as e:
        print(f"[警告] 要約抽出失敗: {html_path}: {e}")
        return "記載なし", "記載なし"

def generate_index_html():
    files = sorted(Path(OUTPUT_DIR).glob("*.html"))
    sections = []
    for f in files:
        title = f.stem.replace(FILTER_SUFFIX, "")
        status, timing = extract_summary_lines(f)
        section = f'<li><a href="output/{f.name}">{title}</a><br>最新の状況：{status}<br>いつ買うべきか：{timing}</li>'
        sections.append(section)
        print(f"[DEBUG] index記載: {f.name} → 状況='{status}' | 買うべきか='{timing}'")
    links = "\n".join(sections)
    latest = get_latest_update_date()
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="robots" content="noindex">
  <title>米国株レポート一覧</title>
</head>
<body>
  <h1>米国株レポート</h1>
  <ul>
    {links}
  </ul>
  <p>最終更新日: {latest}</p>
</body>
</html>
"""
    Path(INDEX_HTML).write_text(html, encoding="utf-8")

def main():
    if not os.path.exists(INPUT_JSON):
        print(f"[エラー] {INPUT_JSON} が見つかりません")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    for thread in data:
        title = thread.get("title", "").strip()
        if not title.endswith(FILTER_SUFFIX):
            continue

        html_path = os.path.join(OUTPUT_DIR, f"{title}.html")
        existing_dates = extract_existing_dates(html_path)

        messages = []
        for node in thread.get("mapping", {}).values():
            msg = node.get("message")
            if not msg:
                continue
            role = msg["author"]["role"]
            parts = msg.get("content", {}).get("parts")
            if parts:
                text = parts[0]
                if isinstance(text, dict):
                    text = text.get("value", "")
                messages.append({"role": role, "text": text})

        date_to_group = defaultdict(list)
        current_date = None
        for msg in messages:
            if msg["role"] == "assistant":
                extracted = extract_date_from_text(msg["text"])
                if extracted:
                    current_date = extracted
            if current_date:
                date_to_group[current_date].append(msg)

        print(f"[DEBUG] {title}: 日付検出={list(date_to_group.keys())}")

        for date, grouped_msgs in sorted(date_to_group.items()):
            if date in existing_dates:
                print(f"[SKIP] 既存: {title}（{date}）")
                continue

            full_text = "\n".join([
                ("Q: " if msg["role"] == "user" else "A: ") + msg["text"]
                for msg in grouped_msgs
            ])
            summary = summarize_with_gemini(full_text)
            section = f"<h2>{date}</h2>\n<pre>{summary}</pre>"

            if os.path.exists(html_path):
                with open(html_path, "r", encoding="utf-8") as f:
                    soup = BeautifulSoup(f, "html.parser")
                soup.body.append(BeautifulSoup(section, "html.parser"))
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(str(soup))
            else:
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(HTML_TEMPLATE.format(title=title, content=section))

            print(f"[OK] 更新: {title}（{date}）")

    generate_index_html()
    print("[完了] index.html に最終更新日と要約を記載しました")

if __name__ == "__main__":
    main()