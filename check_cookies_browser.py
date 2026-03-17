#!/usr/bin/env python3
"""
Cookie 合规性检测脚本（浏览器级别，含 JavaScript Cookie / GA）
同时检测两个站点：
  - dgbyg Flask 应用: https://dgbyg.drziweidai.com
  - 实验室主网站:      https://drziweidai.com

需要安装: pip install playwright && playwright install chromium
用法: python3 check_cookies_browser.py
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

# ── 站点配置 ────────────────────────────────────────────────────────────────

SITES = [
    {
        "name": "dgbyg Flask 应用",
        "base_url": "https://dgbyg.drziweidai.com",
        "pages": [
            "/",
            "/contact",
            "/gem-dg",
            "/prediction",
            "/api",
            "/citation",
            "/faq",
            "/help",
            "/api/models",
            "/api/reactions",
            "/api/metabolites",
            "/api/genes",
            "/robots.txt",
            "/sitemap.xml",
        ],
    },
    {
        "name": "实验室主网站",
        "base_url": "https://drziweidai.com",
        # 从本地 lab_website 目录自动读取所有 HTML 文件名
        "local_dir": "/zhongj/website/lab_website",
        "pages": None,  # 自动填充
    },
]

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def get_lab_pages(local_dir: str) -> list[str]:
    """从本地目录读取所有 HTML 文件，转换为路由路径"""
    p = Path(local_dir)
    pages = []
    for f in sorted(p.glob("*.html")):
        name = f.name
        pages.append("/" if name == "index.html" else f"/{name}")
    return pages


def format_cookie(c: dict) -> str:
    value_preview = c["value"][:40] + ("..." if len(c["value"]) > 40 else "")
    expires = "永久" if c.get("expires", -1) > 0 else "会话"
    return (
        f"   • {c['name']} = {value_preview}\n"
        f"     domain={c['domain']}  path={c['path']}  expires={expires}"
    )


# ── 主检测逻辑 ────────────────────────────────────────────────────────────────

async def check_site(browser, site: dict) -> bool:
    """检测单个站点，返回是否发现 Cookie"""
    base_url = site["base_url"]

    # 自动填充 lab_website 的页面列表
    if site["pages"] is None:
        site["pages"] = get_lab_pages(site["local_dir"])

    print(f"\n{'━' * 60}")
    print(f"  站点: {site['name']}")
    print(f"  URL:  {base_url}")
    print(f"{'━' * 60}")

    site_found_any = False

    for page_path in site["pages"]:
        url = base_url + page_path

        # 每个页面使用全新的隔离上下文（模拟全新用户，无历史 Cookie）
        ctx = await browser.new_context(
            ignore_https_errors=True,
        )
        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            # 额外等待，确保 GA 等异步脚本完成设置 Cookie
            await page.wait_for_timeout(2500)

            cookies = await ctx.cookies()

            # 过滤掉不属于当前站点域名的 Cookie（避免误报）
            from urllib.parse import urlparse
            host = urlparse(base_url).hostname  # e.g. dgbyg.drziweidai.com
            # GA 可能设置在父域名 .drziweidai.com，也要包含
            parent = ".".join(host.split(".")[-2:])  # drziweidai.com
            relevant = [
                c for c in cookies
                if c["domain"].lstrip(".") in (host, parent)
                or host.endswith(c["domain"].lstrip("."))
            ]

            if relevant:
                site_found_any = True
                print(f"  ⚠️  {page_path}")
                for c in relevant:
                    print(format_cookie(c))
            else:
                print(f"  ✓  {page_path}")

        except Exception as e:
            print(f"  ✗  {page_path}  失败: {e}")
        finally:
            await ctx.close()

    return site_found_any


async def main():
    print("\n" + "=" * 60)
    print("  Cookie 合规性检测（浏览器模式，含 GA 等 JS Cookie）")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        results = {}
        for site in SITES:
            found = await check_site(browser, site)
            results[site["name"]] = found

        await browser.close()

    # ── 汇总报告 ──────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("  检测结论汇总")
    print(f"{'=' * 60}")
    all_clean = True
    for name, found in results.items():
        if found:
            all_clean = False
            print(f"  ⚠️  {name}: 发现 Cookie，需要处理！")
        else:
            print(f"  ✓  {name}: 无 Cookie，合规！")

    print(f"{'=' * 60}")
    if all_clean:
        print("  整体结论：所有站点均无 Cookie，完全合规 ✓")
    else:
        print("  整体结论：存在 Cookie 问题，请按上方提示排查 ⚠️")
    print()


if __name__ == "__main__":
    asyncio.run(main())
