from __future__ import annotations

import html
import json

from .data import MockDetailRecord, TOTAL_PAGES, get_announcement_page, get_deal_page

def render_home_page(*, base_url: str) -> str:
    return _layout(
        title="AutoSpider Mock Portal",
        body=f"""
        <section class="hero">
          <div>
            <p class="eyebrow">闭环测试门户</p>
            <h1>AutoSpider 本地模拟网站</h1>
            <p>首页同时提供独立列表入口和同 URL tab 切换入口。</p>
          </div>
          <a class="primary-link" href="/announcements?page=1">进入通知公告列表</a>
        </section>
        <section class="tabs-card">
          <div class="tab-bar" role="tablist" aria-label="首页栏目切换">
            <button id="overview-tab" class="tab-button active" type="button" data-panel="overview-panel">站点总览</button>
            <button id="deals-tab" class="tab-button" type="button" data-panel="deals-panel">成交结果</button>
          </div>
          <div id="overview-panel" class="tab-panel active">
            <h2>总站说明</h2>
            <p>通知公告走独立列表 URL；成交结果通过首页 tab 在同一地址内切换展示。</p>
          </div>
          <div id="deals-panel" class="tab-panel">
            <div class="panel-header">
              <h2>成交结果</h2>
              <span id="deals-page-label">第 1 页 / 共 {TOTAL_PAGES} 页</span>
            </div>
            <ul id="deals-list" class="item-list"></ul>
            <div class="pager">
              <button id="deals-prev" class="pager-button" type="button">上一页</button>
              <button id="deals-next" class="pager-button" type="button">下一页</button>
            </div>
          </div>
        </section>
        <script>
        const dealState = {{ page: 1, loaded: false }};
        const tabs = [...document.querySelectorAll('.tab-button')];
        const panels = [...document.querySelectorAll('.tab-panel')];
        async function renderDeals(page) {{
          const response = await fetch('/api/deals?page=' + page, {{ headers: {{ 'Accept': 'application/json' }} }});
          const payload = await response.json();
          const list = document.getElementById('deals-list');
          list.innerHTML = payload.items.map((item) => `
            <li class="item-card">
              <span class="item-date">${{item.publish_date}}</span>
              <a href="${{item.url}}" target="_blank" rel="noopener noreferrer">${{item.title}}</a>
            </li>
          `).join('');
          document.getElementById('deals-page-label').textContent = `第 ${{payload.page}} 页 / 共 ${{payload.total_pages}} 页`;
          document.getElementById('deals-prev').disabled = !payload.has_previous;
          document.getElementById('deals-next').disabled = !payload.has_next;
          dealState.page = payload.page;
          dealState.loaded = true;
        }}
        tabs.forEach((tab) => {{
          tab.addEventListener('click', async () => {{
            tabs.forEach((item) => item.classList.remove('active'));
            panels.forEach((panel) => panel.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.dataset.panel).classList.add('active');
            if (tab.id === 'deals-tab' && !dealState.loaded) {{
              await renderDeals(1);
            }}
          }});
        }});
        document.getElementById('deals-prev').addEventListener('click', async () => {{
          if (dealState.page > 1) {{
            await renderDeals(dealState.page - 1);
          }}
        }});
        document.getElementById('deals-next').addEventListener('click', async () => {{
          if (dealState.page < {TOTAL_PAGES}) {{
            await renderDeals(dealState.page + 1);
          }}
        }});
        </script>
        """,
    )

def render_announcements_page(*, base_url: str, page: int) -> str:
    current_page = max(1, min(page, TOTAL_PAGES))
    items = "".join(
        _list_item(record=record, category="announcement", target="_self")
        for record in get_announcement_page(current_page)
    )
    next_href = f"/announcements?page={min(TOTAL_PAGES, current_page + 1)}"
    prev_href = f"/announcements?page={max(1, current_page - 1)}"
    disabled_prev = "disabled" if current_page == 1 else ""
    disabled_next = "disabled" if current_page == TOTAL_PAGES else ""
    return _layout(
        title=f"通知公告 - 第 {current_page} 页",
        body=f"""
        <nav class="breadcrumb">首页 / 通知公告 / 第 {current_page} 页</nav>
        <section class="list-shell">
          <aside class="sidebar">
            <h2>栏目提示</h2>
            <p>当前栏目：通知公告</p>
            <p>热门标题示例：{html.escape(get_announcement_page(1)[0].title)}</p>
          </aside>
          <main>
            <div class="panel-header">
              <h1>通知公告</h1>
              <span>第 {current_page} 页 / 共 {TOTAL_PAGES} 页</span>
            </div>
            <ul class="item-list">{items}</ul>
            <div class="pager">
              <a class="pager-link {disabled_prev}" href="{prev_href}">上一页</a>
              <a class="pager-link {disabled_next}" href="{next_href}">下一页</a>
              <form id="jump-form" class="jump-form">
                <label for="jump-page">跳转页码</label>
                <input id="jump-page" name="page" type="number" min="1" max="{TOTAL_PAGES}" value="{current_page}" />
                <button type="submit">确认跳转</button>
              </form>
            </div>
          </main>
        </section>
        <script>
        document.getElementById('jump-form').addEventListener('submit', (event) => {{
          event.preventDefault();
          const page = document.getElementById('jump-page').value || '1';
          window.location.href = '/announcements?page=' + page;
        }});
        </script>
        """,
    )

def render_detail_page(*, base_url: str, category: str, record: MockDetailRecord) -> str:
    attachment_url = f"{base_url}{record.attachment_path(category=category)}"
    category_name = "通知公告" if category == "announcement" else "成交结果"
    return _layout(
        title=record.title,
        body=f"""
        <nav class="breadcrumb">首页 / {category_name} / {html.escape(record.title)}</nav>
        <section class="detail-shell">
          <aside class="sidebar">
            <h2>侧栏推荐</h2>
            <p>推荐阅读：{html.escape(record.title)}</p>
            <p>发布时间：{html.escape(record.publish_date)}</p>
          </aside>
          <main class="detail-card">
            <header>
              <p class="eyebrow">{category_name}详情页</p>
              <h1 id="detail-title">{html.escape(record.title)}</h1>
              <p id="detail-date">发布日期：{html.escape(record.publish_date)}</p>
            </header>
            <div class="tab-bar" role="tablist" aria-label="详情信息切换">
              <button id="summary-tab" class="tab-button active" type="button">公告概览</button>
              <button id="project-tab" class="tab-button" type="button">项目详情</button>
            </div>
            <section id="summary-panel" class="tab-panel active">
              <p>正文摘要：本页存在与正文重复的标题和日期文案，便于验证字段消歧能力。</p>
              <p>重复标题：{html.escape(record.title)}</p>
            </section>
            <section
              id="project-panel"
              class="tab-panel"
              data-budget="{html.escape(record.budget)}"
              data-attachment-url="{html.escape(attachment_url)}"
            >
              <div id="project-placeholder" class="callout">点击“项目详情”后加载预算与附件链接。</div>
            </section>
          </main>
        </section>
        <script>
        const summaryTab = document.getElementById('summary-tab');
        const projectTab = document.getElementById('project-tab');
        const summaryPanel = document.getElementById('summary-panel');
        const projectPanel = document.getElementById('project-panel');
        function showSummary() {{
          summaryTab.classList.add('active');
          projectTab.classList.remove('active');
          summaryPanel.classList.add('active');
          projectPanel.classList.remove('active');
        }}
        function showProject() {{
          summaryTab.classList.remove('active');
          projectTab.classList.add('active');
          summaryPanel.classList.remove('active');
          projectPanel.classList.add('active');
          if (!projectPanel.dataset.loaded) {{
            const budget = projectPanel.dataset.budget;
            const attachmentUrl = projectPanel.dataset.attachmentUrl;
            projectPanel.innerHTML = `
              <div class="detail-grid">
                <div><span class="detail-label">预算金额</span><p id="budget">${{budget}}</p></div>
                <div>
                  <span class="detail-label">附件链接</span>
                  <p id="attachment-url-text" class="detail-value">${{attachmentUrl}}</p>
                  <p><a id="attachment-url" href="${{attachmentUrl}}" target="_blank" rel="noopener noreferrer">查看附件</a></p>
                </div>
              </div>
            `;
            projectPanel.dataset.loaded = 'true';
          }}
        }}
        summaryTab.addEventListener('click', showSummary);
        projectTab.addEventListener('click', showProject);
        </script>
        """,
    )

def render_deals_payload(*, base_url: str, page: int) -> bytes:
    current_page = max(1, min(page, TOTAL_PAGES))
    payload = {
        "page": current_page,
        "total_pages": TOTAL_PAGES,
        "has_previous": current_page > 1,
        "has_next": current_page < TOTAL_PAGES,
        "items": [
            {
                "title": record.title,
                "publish_date": record.publish_date,
                "url": f"{base_url}{record.detail_path(category='deal')}",
            }
            for record in get_deal_page(current_page)
        ],
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

def render_download(*, category: str, slug: str) -> bytes:
    content = (
        "%PDF-1.4\n"
        f"% Mock attachment for {category}:{slug}\n"
        "1 0 obj<</Type/Catalog>>endobj\n"
        "trailer<</Root 1 0 R>>\n"
        "%%EOF\n"
    )
    return content.encode("utf-8")

def _list_item(*, record: MockDetailRecord, category: str, target: str) -> str:
    url = html.escape(record.detail_path(category=category))
    title = html.escape(record.title)
    publish_date = html.escape(record.publish_date)
    return (
        '<li class="item-card">'
        f'<span class="item-date">{publish_date}</span>'
        f'<a href="{url}" target="{target}">{title}</a>'
        "</li>"
    )

def _layout(*, title: str, body: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escaped_title}</title>
  <style>
    :root {{ color-scheme: light; --bg: #f5f1e8; --ink: #1f2933; --accent: #0f766e; --card: #fffdf8; --line: #d7c9ad; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Microsoft YaHei", sans-serif; background: radial-gradient(circle at top, #fff7e3, var(--bg) 60%); color: var(--ink); }}
    a {{ color: #0b5c8c; text-decoration: none; }}
    main, section, aside, nav, header {{ display: block; }}
    .page {{ width: min(1120px, calc(100% - 32px)); margin: 24px auto 48px; }}
    .hero, .tabs-card, .detail-card, .sidebar, .item-card {{ background: var(--card); border: 1px solid var(--line); border-radius: 18px; box-shadow: 0 12px 28px rgba(31, 41, 51, 0.08); }}
    .hero {{ padding: 28px; display: flex; justify-content: space-between; gap: 20px; align-items: center; }}
    .tabs-card, .detail-card {{ padding: 24px; }}
    .primary-link, .pager-link, .pager-button, .jump-form button {{ background: var(--accent); color: #fff; border: 0; border-radius: 999px; padding: 10px 16px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }}
    .list-shell, .detail-shell {{ display: grid; gap: 20px; grid-template-columns: 280px minmax(0, 1fr); }}
    .sidebar {{ padding: 20px; }}
    .breadcrumb, .eyebrow {{ color: #6b7280; font-size: 14px; letter-spacing: 0.04em; text-transform: uppercase; }}
    .item-list {{ list-style: none; margin: 20px 0; padding: 0; display: grid; gap: 14px; }}
    .item-card {{ padding: 16px 18px; }}
    .item-card a {{ display: block; font-size: 18px; font-weight: 700; margin-top: 6px; }}
    .item-date {{ color: #6b7280; font-size: 14px; }}
    .tab-bar {{ display: flex; gap: 12px; margin-top: 16px; }}
    .tab-button {{ border: 1px solid var(--line); background: #efe6d2; border-radius: 999px; padding: 10px 14px; cursor: pointer; }}
    .tab-button.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .tab-panel {{ display: none; margin-top: 18px; }}
    .tab-panel.active {{ display: block; }}
    .panel-header, .pager {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }}
    .jump-form {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .jump-form input {{ border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; width: 100px; background: #fff; }}
    .pager-link.disabled {{ pointer-events: none; opacity: 0.45; }}
    .callout {{ padding: 14px 16px; border-radius: 14px; background: #f7efe0; border: 1px dashed var(--line); }}
    .detail-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; padding-top: 4px; }}
    .detail-label {{ display: inline-block; font-size: 13px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.04em; }}
    .detail-value {{ margin: 8px 0 10px; word-break: break-all; }}
    @media (max-width: 760px) {{
      .hero, .list-shell, .detail-shell {{ grid-template-columns: 1fr; display: grid; }}
      .hero {{ justify-content: start; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">{body}</div>
</body>
</html>"""
