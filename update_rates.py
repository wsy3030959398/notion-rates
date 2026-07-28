#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动给 Notion「订阅管理」数据库更新汇率。
"""

import os
import sys
import datetime
import requests

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

EXCHANGE_API = "https://api.exchangerate.fun/latest"


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
    if base == target:
        return 1.0
    if base not in rate_cache:
        resp = requests.get(EXCHANGE_API, params={"base": base}, timeout=15)
        resp.raise_for_status()
        rate_cache[base] = resp.json()["rates"]
    rates = rate_cache[base]
    if target not in rates:
        raise ValueError(f"{base} -> {target} 汇率不存在，请检查货币代码是否正确")
    return rates[target]


def update_page_rate(page_id: str, rate: float):
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    payload = {
        "properties": {
            "汇率": {"number": round(rate, 6)},
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
