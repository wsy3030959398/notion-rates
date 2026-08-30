#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动给 Notion「订阅项目」数据库更新汇率。

逻辑：
1. 读取数据库里每一行的「货币」（原始扣款货币）和「目标货币」（想要折算成的货币）
2. 用 ExchangeRate-API 拿到实时汇率（免费，需要一个免费注册的 API key）
3. 把汇率写回「汇率」字段，把当前时间写回「汇率更新时间」字段

需要的环境变量（在 GitHub Actions 的 Secrets 里配置）：
- NOTION_TOKEN              Notion Integration 的密钥
- NOTION_DATABASE_ID        订阅项目数据库的 ID
- EXCHANGERATE_API_KEY      在 exchangerate-api.com 免费注册拿到的 key
"""

import os
import sys
import datetime
import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
EXCHANGERATE_API_KEY = os.environ["EXCHANGERATE_API_KEY"]

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

EXCHANGE_API = f"https://v6.exchangerate-api.com/v6/{EXCHANGERATE_API_KEY}/latest"


def currency_code(select_value: str) -> str:
    return select_value[:3].strip().upper()


def get_all_pages():
    pages = []
    payload = {"page_size": 100}
    while True:
        resp = requests.post(
            f"{NOTION_API}/databases/{DATABASE_ID}/query",
            headers=HEADERS,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data["results"])
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return pages


def get_rate(base: str, target: str, rate_cache: dict) -> float:
    """带缓存地获取 base -> target 的汇率"""
    if base == target:
        return 1.0
    if base not in rate_cache:
        resp = requests.get(f"{EXCHANGE_API}/{base}", timeout=15)
        data = resp.json()
        if data.get("result") != "success":
            print(
                f"[汇率接口异常] base={base} response={data}",
                file=sys.stderr,
            )
            resp.raise_for_status()
        rate_cache[base] = data["conversion_rates"]
    rates = rate_cache[base]
    if target not in rates:
        raise ValueError(f"{base} -> {target} 汇率不存在，请检查货币代码是否正确")
    return rates[target]


def update_page_rate(page_id: str, rate: float):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload = {
        "properties": {
            "汇率": {"number": round(rate, 3)},
            "汇率更新时间": {"date": {"start": now_iso}},
        }
    }
    resp = requests.patch(
        f"{NOTION_API}/pages/{page_id}", headers=HEADERS, json=payload
    )
    resp.raise_for_status()


def main():
    pages = get_all_pages()
    print(f"共找到 {len(pages)} 条订阅记录")

    rate_cache = {}
    updated, skipped = 0, 0

    for page in pages:
        props = page["properties"]
        page_id = page["id"]

        name_prop = props.get("订阅名称", {}).get("title", [])
        name = name_prop[0]["plain_text"] if name_prop else "(未命名)"

        currency_prop = props.get("货币", {}).get("select")
        target_prop = props.get("目标货币", {}).get("select")

        if not currency_prop or not target_prop:
            print(f"跳过「{name}」：货币或目标货币未填写")
            skipped += 1
            continue

        base = currency_code(currency_prop["name"])
        target = currency_code(target_prop["name"])

        try:
            rate = get_rate(base, target, rate_cache)
            update_page_rate(page_id, rate)
            print(f"「{name}」 {base} -> {target}: {rate}")
            updated += 1
        except Exception as e:
            print(f"「{name}」更新失败: {e}", file=sys.stderr)
            skipped += 1

    print(f"完成：更新 {updated} 条，跳过 {skipped} 条")


if __name__ == "__main__":
    main()
