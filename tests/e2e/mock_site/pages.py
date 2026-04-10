from __future__ import annotations

import html
import json

from .data import MockDetailRecord, TOTAL_PAGES, get_announcement_page, get_deal_page


def render_home_page(*, base_url: str) -> str:
    return _layout(
        title="智慧城市公共资源交易中心",
        body=f"""
        <section class="hero">
          <div class="hero-content">
            <div class="hero-badge">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
              门户首页
            </div>
            <h1>智慧城市公共资源交易中心</h1>
            <p class="hero-desc">本平台集中发布通知公告与成交结果信息，为各类市场主体提供公开、透明的交易信息服务。</p>
            <div class="hero-actions">
              <a class="primary-link" href="/announcements?page=1">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                进入通知公告列表
              </a>
            </div>
          </div>
          <div class="hero-stats">
            <div class="stat-item">
              <span class="stat-number">7</span>
              <span class="stat-label">通知公告</span>
            </div>
            <div class="stat-item">
              <span class="stat-number">8</span>
              <span class="stat-label">成交结果</span>
            </div>
            <div class="stat-item">
              <span class="stat-number">{TOTAL_PAGES}</span>
              <span class="stat-label">总页数</span>
            </div>
          </div>
        </section>

        <section class="quick-links">
          <a href="/announcements?page=1" class="quick-link-card">
            <div class="ql-icon ql-icon-announce">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
            </div>
            <span>通知公告</span>
          </a>
          <div class="quick-link-card" id="ql-deals-link" style="cursor:pointer">
            <div class="ql-icon ql-icon-deal">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            </div>
            <span>成交结果</span>
          </div>
          <div class="quick-link-card">
            <div class="ql-icon ql-icon-help">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            </div>
            <span>办事指南</span>
          </div>
          <div class="quick-link-card">
            <div class="ql-icon ql-icon-contact">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>
            </div>
            <span>联系我们</span>
          </div>
        </section>

        <section class="tabs-card">
          <div class="section-title-bar">
            <h2 class="section-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
              信息浏览
            </h2>
          </div>
          <div class="tab-bar" role="tablist" aria-label="首页栏目切换">
            <button id="overview-tab" class="tab-button active" type="button" data-panel="overview-panel">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              站点总览
            </button>
            <button id="deals-tab" class="tab-button" type="button" data-panel="deals-panel">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              成交结果
            </button>
          </div>
          <div id="overview-panel" class="tab-panel active">
            <div class="overview-grid">
              <div class="overview-item">
                <div class="overview-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </div>
                <h3>通知公告</h3>
                <p>走独立列表 URL，支持分页浏览和页码跳转。</p>
              </div>
              <div class="overview-item">
                <div class="overview-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                </div>
                <h3>成交结果</h3>
                <p>通过首页 Tab 在同一地址内切换展示，支持动态分页。</p>
              </div>
              <div class="overview-item">
                <div class="overview-icon">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                </div>
                <h3>附件下载</h3>
                <p>每条记录的详情页提供附件下载功能。</p>
              </div>
            </div>
          </div>
          <div id="deals-panel" class="tab-panel">
            <div class="panel-header">
              <h2>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                成交结果公示
              </h2>
              <span id="deals-page-label" class="page-indicator">第 1 页 / 共 {TOTAL_PAGES} 页</span>
            </div>
            <ul id="deals-list" class="item-list"></ul>
            <div class="pager">
              <button id="deals-prev" class="pager-button" type="button">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
                上一页
              </button>
              <button id="deals-next" class="pager-button" type="button">
                下一页
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </button>
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
          list.innerHTML = payload.items.map((item, index) => `
            <li class="item-card" style="animation-delay: ${{index * 0.05}}s">
              <span class="item-date">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                ${{item.publish_date}}
              </span>
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
        // Quick link to deals tab
        const qlDeals = document.getElementById('ql-deals-link');
        if (qlDeals) {{
          qlDeals.addEventListener('click', () => {{
            document.getElementById('deals-tab').click();
            document.querySelector('.tabs-card').scrollIntoView({{ behavior: 'smooth' }});
          }});
        }}
        </script>
        """,
    )

def render_announcements_page(*, base_url: str, page: int) -> str:
    current_page = max(1, min(page, TOTAL_PAGES))
    items = "".join(
        _list_item(record=record, category="announcement", target="_self", index=i)
        for i, record in enumerate(get_announcement_page(current_page))
    )
    next_href = f"/announcements?page={min(TOTAL_PAGES, current_page + 1)}"
    prev_href = f"/announcements?page={max(1, current_page - 1)}"
    disabled_prev = "disabled" if current_page == 1 else ""
    disabled_next = "disabled" if current_page == TOTAL_PAGES else ""

    # Build page number links
    page_numbers = ""
    for p in range(1, TOTAL_PAGES + 1):
        active_cls = "pn-active" if p == current_page else ""
        page_numbers += f'<a class="page-number {active_cls}" href="/announcements?page={p}">{p}</a>'

    return _layout(
        title=f"通知公告 - 第 {current_page} 页 | 智慧城市公共资源交易中心",
        body=f"""
        <nav class="breadcrumb">
          <a href="/">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            首页
          </a>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          <span>通知公告</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          <span class="breadcrumb-current">第 {current_page} 页</span>
        </nav>
        <section class="list-shell">
          <aside class="sidebar">
            <div class="sidebar-section">
              <h2>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                栏目导航
              </h2>
              <ul class="sidebar-nav">
                <li class="sidebar-nav-active">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
                  通知公告
                </li>
                <li>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                  <a href="/">成交结果</a>
                </li>
              </ul>
            </div>
            <div class="sidebar-section sidebar-highlight">
              <h2>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                热门公告
              </h2>
              <p class="sidebar-featured-title">{html.escape(get_announcement_page(1)[0].title)}</p>
              <span class="sidebar-featured-date">{html.escape(get_announcement_page(1)[0].publish_date)}</span>
            </div>
          </aside>
          <main>
            <div class="panel-header">
              <h1>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                通知公告
              </h1>
              <span class="page-indicator">第 {current_page} 页 / 共 {TOTAL_PAGES} 页</span>
            </div>
            <ul class="item-list">{items}</ul>
            <div class="pager">
              <a class="pager-link {disabled_prev}" href="{prev_href}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
                上一页
              </a>
              <div class="page-numbers">{page_numbers}</div>
              <a class="pager-link {disabled_next}" href="{next_href}">
                下一页
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
              </a>
              <form id="jump-form" class="jump-form">
                <label for="jump-page">跳转到</label>
                <input id="jump-page" name="page" type="number" min="1" max="{TOTAL_PAGES}" value="{current_page}" />
                <button type="submit">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
                  确认跳转
                </button>
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
    list_url = "/announcements?page=1" if category == "announcement" else "/"
    budget_display = f"¥ {int(record.budget):,}" if record.budget.isdigit() else record.budget
    return _layout(
        title=f"{record.title} | 智慧城市公共资源交易中心",
        body=f"""
        <nav class="breadcrumb">
          <a href="/">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            首页
          </a>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          <a href="{list_url}">{category_name}</a>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          <span class="breadcrumb-current">{html.escape(record.title[:20])}…</span>
        </nav>
        <section class="detail-shell">
          <aside class="sidebar">
            <div class="sidebar-section">
              <h2>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                信息摘要
              </h2>
              <div class="sidebar-meta">
                <div class="sidebar-meta-item">
                  <span class="meta-label">栏目</span>
                  <span class="meta-value">{category_name}</span>
                </div>
                <div class="sidebar-meta-item">
                  <span class="meta-label">发布时间</span>
                  <span class="meta-value">{html.escape(record.publish_date)}</span>
                </div>
                <div class="sidebar-meta-item">
                  <span class="meta-label">预算金额</span>
                  <span class="meta-value meta-value-highlight">{budget_display}</span>
                </div>
              </div>
            </div>
            <div class="sidebar-section">
              <h2>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                栏目导航
              </h2>
              <ul class="sidebar-nav">
                <li {"class='sidebar-nav-active'" if category == "announcement" else ""}>
                  <a href="/announcements?page=1">通知公告</a>
                </li>
                <li {"class='sidebar-nav-active'" if category == "deal" else ""}>
                  <a href="/">成交结果</a>
                </li>
              </ul>
            </div>
          </aside>
          <main class="detail-card">
            <header class="detail-header">
              <p class="eyebrow">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                {category_name} · 详情
              </p>
              <h1 id="detail-title">{html.escape(record.title)}</h1>
              <div class="detail-meta-bar">
                <span id="detail-date" class="detail-meta-tag">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                  发布日期：{html.escape(record.publish_date)}
                </span>
                <span class="detail-meta-tag">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  来源：智慧城市公共资源交易中心
                </span>
              </div>
            </header>
            <div class="tab-bar" role="tablist" aria-label="详情信息切换">
              <button id="summary-tab" class="tab-button active" type="button">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                公告概览
              </button>
              <button id="project-tab" class="tab-button" type="button">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                项目详情
              </button>
            </div>
            <section id="summary-panel" class="tab-panel active">
              <div class="summary-content">
                <div class="summary-notice">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  <p>正文摘要：本页存在与正文重复的标题和日期文案，便于验证字段消歧能力。</p>
                </div>
                <div class="summary-detail-row">
                  <span class="detail-label">重复标题</span>
                  <p>{html.escape(record.title)}</p>
                </div>
              </div>
            </section>
            <section
              id="project-panel"
              class="tab-panel"
              data-budget="{html.escape(record.budget)}"
              data-attachment-url="{html.escape(attachment_url)}"
            >
              <div id="project-placeholder" class="callout">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <p>点击"项目详情"标签后加载预算与附件链接信息。</p>
              </div>
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
                <div class="detail-grid-item">
                  <div class="detail-grid-icon">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
                  </div>
                  <span class="detail-label">预算金额</span>
                  <p id="budget" class="detail-budget">${{budget}}</p>
                </div>
                <div class="detail-grid-item">
                  <div class="detail-grid-icon">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  </div>
                  <span class="detail-label">附件链接</span>
                  <p id="attachment-url-text" class="detail-value">${{attachmentUrl}}</p>
                  <p><a id="attachment-url" href="${{attachmentUrl}}" target="_blank" rel="noopener noreferrer" class="attachment-link">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    下载附件
                  </a></p>
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

def _list_item(*, record: MockDetailRecord, category: str, target: str, index: int = 0) -> str:
    url = html.escape(record.detail_path(category=category))
    title = html.escape(record.title)
    publish_date = html.escape(record.publish_date)
    return (
        f'<li class="item-card" style="animation-delay: {index * 0.05}s">'
        f'<span class="item-date">'
        f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>'
        f'{publish_date}</span>'
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
    /* ===== CSS Variables & Reset ===== */
    :root {{
      color-scheme: light;
      --primary: #1a56db;
      --primary-dark: #1442a8;
      --primary-light: #e8f0fe;
      --primary-gradient: linear-gradient(135deg, #1a56db, #2970ff);
      --accent: #dc2626;
      --bg: #f0f2f5;
      --bg-page: #ffffff;
      --ink: #1e293b;
      --ink-secondary: #64748b;
      --ink-muted: #94a3b8;
      --card: #ffffff;
      --card-hover: #f8fafc;
      --line: #e2e8f0;
      --line-light: #f1f5f9;
      --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
      --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
      --shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --header-height: 64px;
      --font-sans: "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans SC", sans-serif;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      font-family: var(--font-sans);
      background: var(--bg);
      color: var(--ink);
      line-height: 1.6;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    a {{ color: var(--primary); text-decoration: none; transition: color 0.2s; }}
    a:hover {{ color: var(--primary-dark); }}
    main, section, aside, nav, header, footer {{ display: block; }}
    img {{ max-width: 100%; }}
    button {{ font-family: inherit; }}

    /* ===== Header ===== */
    .site-header {{
      background: var(--primary-gradient);
      color: #fff;
      position: sticky;
      top: 0;
      z-index: 100;
      box-shadow: 0 2px 8px rgba(26, 86, 219, 0.25);
    }}
    .header-inner {{
      width: min(1200px, calc(100% - 32px));
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: var(--header-height);
    }}
    .site-logo {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 18px;
      font-weight: 700;
      color: #fff;
      text-decoration: none;
      letter-spacing: 0.02em;
    }}
    .logo-icon {{
      width: 36px;
      height: 36px;
      background: rgba(255,255,255,0.2);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      backdrop-filter: blur(4px);
    }}
    .header-nav {{
      display: flex;
      align-items: center;
      gap: 4px;
    }}
    .header-nav a {{
      color: rgba(255,255,255,0.85);
      padding: 8px 14px;
      border-radius: var(--radius-sm);
      font-size: 14px;
      transition: all 0.2s;
      text-decoration: none;
    }}
    .header-nav a:hover, .header-nav a.nav-active {{
      background: rgba(255,255,255,0.15);
      color: #fff;
    }}

    /* ===== Subheader (banner bar) ===== */
    .sub-header {{
      background: linear-gradient(135deg, #f8fafc, #eef2ff);
      border-bottom: 1px solid var(--line);
      padding: 10px 0;
      font-size: 13px;
      color: var(--ink-secondary);
    }}
    .sub-header-inner {{
      width: min(1200px, calc(100% - 32px));
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .sub-header-left {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .sub-header svg {{ opacity: 0.5; }}

    /* ===== Page Container ===== */
    .page {{
      width: min(1200px, calc(100% - 32px));
      margin: 24px auto 48px;
      flex: 1;
    }}

    /* ===== Hero Section ===== */
    .hero {{
      background: linear-gradient(135deg, #1e40af 0%, #3b82f6 50%, #60a5fa 100%);
      border-radius: var(--radius-lg);
      padding: 40px 36px;
      display: flex;
      justify-content: space-between;
      gap: 32px;
      align-items: center;
      color: #fff;
      position: relative;
      overflow: hidden;
      box-shadow: var(--shadow-lg);
    }}
    .hero::before {{
      content: '';
      position: absolute;
      top: -50%;
      right: -20%;
      width: 400px;
      height: 400px;
      background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
      border-radius: 50%;
    }}
    .hero::after {{
      content: '';
      position: absolute;
      bottom: -30%;
      left: 10%;
      width: 300px;
      height: 300px;
      background: radial-gradient(circle, rgba(255,255,255,0.08) 0%, transparent 70%);
      border-radius: 50%;
    }}
    .hero-content {{ position: relative; z-index: 1; flex: 1; }}
    .hero-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(255,255,255,0.15);
      backdrop-filter: blur(8px);
      color: #fff;
      font-size: 13px;
      padding: 5px 14px;
      border-radius: 999px;
      margin-bottom: 16px;
      letter-spacing: 0.03em;
    }}
    .hero h1 {{
      font-size: 28px;
      font-weight: 800;
      line-height: 1.3;
      margin-bottom: 10px;
      text-shadow: 0 2px 8px rgba(0,0,0,0.15);
    }}
    .hero-desc {{
      color: rgba(255,255,255,0.85);
      font-size: 15px;
      line-height: 1.7;
      margin-bottom: 20px;
      max-width: 560px;
    }}
    .hero-actions {{ display: flex; gap: 12px; }}
    .hero-stats {{
      position: relative;
      z-index: 1;
      display: flex;
      gap: 20px;
    }}
    .stat-item {{
      background: rgba(255,255,255,0.12);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: var(--radius-md);
      padding: 20px 24px;
      text-align: center;
      min-width: 100px;
      transition: transform 0.2s, background 0.2s;
    }}
    .stat-item:hover {{
      transform: translateY(-2px);
      background: rgba(255,255,255,0.18);
    }}
    .stat-number {{
      display: block;
      font-size: 32px;
      font-weight: 800;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .stat-label {{
      font-size: 13px;
      color: rgba(255,255,255,0.7);
    }}

    /* ===== Quick Links ===== */
    .quick-links {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin: 24px 0;
    }}
    .quick-link-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 24px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      text-align: center;
      font-size: 14px;
      font-weight: 600;
      color: var(--ink);
      text-decoration: none;
      transition: all 0.25s;
      box-shadow: var(--shadow-sm);
    }}
    .quick-link-card:hover {{
      transform: translateY(-3px);
      box-shadow: var(--shadow-md);
      border-color: var(--primary);
      color: var(--primary);
    }}
    .ql-icon {{
      width: 52px;
      height: 52px;
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      transition: transform 0.2s;
    }}
    .quick-link-card:hover .ql-icon {{ transform: scale(1.08); }}
    .ql-icon-announce {{ background: linear-gradient(135deg, #3b82f6, #60a5fa); }}
    .ql-icon-deal {{ background: linear-gradient(135deg, #10b981, #34d399); }}
    .ql-icon-help {{ background: linear-gradient(135deg, #f59e0b, #fbbf24); }}
    .ql-icon-contact {{ background: linear-gradient(135deg, #8b5cf6, #a78bfa); }}

    /* ===== Primary Link & Buttons ===== */
    .primary-link {{
      background: #fff;
      color: var(--primary) !important;
      border: 0;
      border-radius: var(--radius-sm);
      padding: 12px 22px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 14px;
      text-decoration: none;
      transition: all 0.2s;
      box-shadow: var(--shadow-sm);
    }}
    .primary-link:hover {{
      background: var(--primary-light);
      transform: translateY(-1px);
      box-shadow: var(--shadow-md);
    }}

    /* ===== Layout: List & Detail Shells ===== */
    .list-shell, .detail-shell {{
      display: grid;
      gap: 24px;
      grid-template-columns: 260px minmax(0, 1fr);
    }}

    /* ===== Sidebar ===== */
    .sidebar {{
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .sidebar-section {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 20px;
      box-shadow: var(--shadow-sm);
    }}
    .sidebar-section h2 {{
      font-size: 15px;
      font-weight: 700;
      color: var(--ink);
      padding-bottom: 12px;
      margin-bottom: 12px;
      border-bottom: 2px solid var(--primary);
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .sidebar-section h2 svg {{ color: var(--primary); flex-shrink: 0; }}
    .sidebar-nav {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }}
    .sidebar-nav li {{
      padding: 10px 12px;
      border-radius: var(--radius-sm);
      font-size: 14px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--ink-secondary);
      transition: all 0.2s;
      cursor: pointer;
    }}
    .sidebar-nav li:hover {{ background: var(--line-light); color: var(--primary); }}
    .sidebar-nav li a {{ color: inherit; text-decoration: none; }}
    .sidebar-nav-active {{
      background: var(--primary-light) !important;
      color: var(--primary) !important;
      font-weight: 600;
    }}
    .sidebar-highlight {{
      background: linear-gradient(135deg, #eff6ff, #dbeafe) !important;
      border-color: #93c5fd !important;
    }}
    .sidebar-featured-title {{
      font-size: 14px;
      line-height: 1.6;
      color: var(--ink);
      margin-bottom: 8px;
    }}
    .sidebar-featured-date {{
      font-size: 12px;
      color: var(--ink-muted);
      display: flex;
      align-items: center;
      gap: 4px;
    }}
    .sidebar-meta {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .sidebar-meta-item {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px dashed var(--line);
      font-size: 13px;
    }}
    .sidebar-meta-item:last-child {{ border-bottom: 0; }}
    .meta-label {{ color: var(--ink-muted); }}
    .meta-value {{ color: var(--ink); font-weight: 600; }}
    .meta-value-highlight {{ color: var(--accent); }}

    /* ===== Breadcrumb ===== */
    .breadcrumb {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--ink-muted);
      margin-bottom: 20px;
      padding: 12px 16px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      box-shadow: var(--shadow-sm);
    }}
    .breadcrumb a {{ color: var(--ink-secondary); text-decoration: none; display: flex; align-items: center; gap: 4px; }}
    .breadcrumb a:hover {{ color: var(--primary); }}
    .breadcrumb svg {{ flex-shrink: 0; color: var(--ink-muted); }}
    .breadcrumb-current {{ color: var(--primary); font-weight: 600; }}
    .eyebrow {{
      color: var(--ink-muted);
      font-size: 13px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    /* ===== Section Titles ===== */
    .section-title-bar {{
      margin-bottom: 4px;
    }}
    .section-title {{
      font-size: 16px;
      font-weight: 700;
      color: var(--ink);
      display: flex;
      align-items: center;
      gap: 8px;
      padding-bottom: 12px;
      border-bottom: 2px solid var(--primary);
      margin-bottom: 0;
    }}
    .section-title svg {{ color: var(--primary); }}

    /* ===== Cards ===== */
    .tabs-card, .detail-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      padding: 24px;
      box-shadow: var(--shadow-sm);
    }}

    /* ===== Item List ===== */
    .item-list {{ list-style: none; margin: 16px 0; padding: 0; display: grid; gap: 0; }}
    .item-card {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--line-light);
      display: flex;
      align-items: center;
      gap: 16px;
      transition: all 0.2s;
      animation: fadeSlideIn 0.3s ease both;
    }}
    .item-card:last-child {{ border-bottom: 0; }}
    .item-card:hover {{
      background: var(--primary-light);
      padding-left: 24px;
    }}
    .item-card a {{
      font-size: 15px;
      font-weight: 600;
      color: var(--ink);
      transition: color 0.2s;
      line-height: 1.5;
      flex: 1;
    }}
    .item-card:hover a {{ color: var(--primary); }}
    .item-date {{
      color: var(--ink-muted);
      font-size: 13px;
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: var(--line-light);
      padding: 4px 10px;
      border-radius: var(--radius-sm);
      white-space: nowrap;
    }}
    .item-date svg {{ opacity: 0.5; }}

    @keyframes fadeSlideIn {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ===== Tabs ===== */
    .tab-bar {{ display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }}
    .tab-button {{
      border: 1px solid var(--line);
      background: var(--card);
      border-radius: var(--radius-sm);
      padding: 10px 18px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      color: var(--ink-secondary);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }}
    .tab-button:hover {{ background: var(--line-light); color: var(--ink); border-color: var(--primary); }}
    .tab-button.active {{
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
      box-shadow: 0 2px 8px rgba(26, 86, 219, 0.3);
    }}
    .tab-button.active svg {{ color: #fff; }}
    .tab-panel {{ display: none; margin-top: 20px; }}
    .tab-panel.active {{ display: block; animation: fadeSlideIn 0.3s ease; }}

    /* ===== Panel Header & Page Indicator ===== */
    .panel-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
    }}
    .panel-header h1, .panel-header h2 {{
      font-size: 18px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .panel-header h1 svg, .panel-header h2 svg {{ color: var(--primary); }}
    .page-indicator {{
      font-size: 13px;
      color: var(--ink-muted);
      background: var(--line-light);
      padding: 5px 14px;
      border-radius: 999px;
    }}

    /* ===== Pager ===== */
    .pager {{
      display: flex;
      justify-content: center;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 20px;
      padding-top: 20px;
      border-top: 1px solid var(--line);
    }}
    .pager-link, .pager-button {{
      background: var(--primary);
      color: #fff;
      border: 0;
      border-radius: var(--radius-sm);
      padding: 10px 18px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      font-weight: 600;
      text-decoration: none;
      transition: all 0.2s;
    }}
    .pager-link:hover, .pager-button:hover:not(:disabled) {{
      background: var(--primary-dark);
      transform: translateY(-1px);
      box-shadow: 0 2px 6px rgba(26, 86, 219, 0.3);
      color: #fff;
    }}
    .pager-button:disabled {{
      background: var(--line);
      color: var(--ink-muted);
      cursor: not-allowed;
      box-shadow: none;
    }}
    .pager-link.disabled {{
      pointer-events: none;
      opacity: 0.4;
      background: var(--line);
      color: var(--ink-muted);
    }}
    .page-numbers {{
      display: flex;
      gap: 4px;
    }}
    .page-number {{
      width: 36px;
      height: 36px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      font-size: 13px;
      font-weight: 600;
      color: var(--ink-secondary);
      text-decoration: none;
      transition: all 0.2s;
    }}
    .page-number:hover {{ border-color: var(--primary); color: var(--primary); }}
    .pn-active {{
      background: var(--primary) !important;
      color: #fff !important;
      border-color: var(--primary) !important;
    }}

    /* ===== Jump Form ===== */
    .jump-form {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-left: 8px;
      font-size: 13px;
      color: var(--ink-secondary);
    }}
    .jump-form label {{ white-space: nowrap; }}
    .jump-form input {{
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 8px 12px;
      width: 72px;
      font-size: 13px;
      text-align: center;
      background: #fff;
      transition: border-color 0.2s;
    }}
    .jump-form input:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(26, 86, 219, 0.1); }}
    .jump-form button {{
      background: var(--primary);
      color: #fff;
      border: 0;
      border-radius: var(--radius-sm);
      padding: 8px 16px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }}
    .jump-form button:hover {{ background: var(--primary-dark); }}

    /* ===== Overview Grid (Home Tab) ===== */
    .overview-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
    }}
    .overview-item {{
      padding: 20px;
      background: var(--line-light);
      border-radius: var(--radius-md);
      transition: all 0.2s;
    }}
    .overview-item:hover {{
      background: var(--primary-light);
      transform: translateY(-2px);
    }}
    .overview-icon {{
      width: 44px;
      height: 44px;
      background: var(--primary-gradient);
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      margin-bottom: 12px;
    }}
    .overview-item h3 {{ font-size: 15px; font-weight: 700; margin-bottom: 6px; }}
    .overview-item p {{ font-size: 13px; color: var(--ink-secondary); line-height: 1.6; }}

    /* ===== Detail Page ===== */
    .detail-header {{
      padding-bottom: 20px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--line);
    }}
    .detail-header .eyebrow {{ margin-bottom: 12px; }}
    .detail-header h1 {{
      font-size: 22px;
      font-weight: 800;
      line-height: 1.4;
      color: var(--ink);
      margin-bottom: 14px;
    }}
    .detail-meta-bar {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .detail-meta-tag {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: 13px;
      color: var(--ink-muted);
      background: var(--line-light);
      padding: 5px 12px;
      border-radius: 999px;
    }}
    .detail-meta-tag svg {{ opacity: 0.6; }}

    .summary-content {{ padding: 4px 0; }}
    .summary-notice {{
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 14px 18px;
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: var(--radius-sm);
      margin-bottom: 16px;
      font-size: 14px;
      color: #92400e;
      line-height: 1.6;
    }}
    .summary-notice svg {{ flex-shrink: 0; color: #f59e0b; margin-top: 2px; }}
    .summary-detail-row {{
      padding: 12px 0;
      border-bottom: 1px dashed var(--line);
    }}
    .summary-detail-row:last-child {{ border-bottom: 0; }}

    .callout {{
      padding: 20px;
      border-radius: var(--radius-md);
      background: var(--line-light);
      border: 1px dashed var(--line);
      display: flex;
      align-items: center;
      gap: 12px;
      color: var(--ink-secondary);
      font-size: 14px;
    }}
    .callout svg {{ flex-shrink: 0; color: var(--primary); opacity: 0.6; }}

    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
      padding: 4px 0;
    }}
    .detail-grid-item {{
      padding: 20px;
      background: var(--line-light);
      border-radius: var(--radius-md);
      transition: all 0.2s;
    }}
    .detail-grid-item:hover {{
      background: var(--primary-light);
    }}
    .detail-grid-icon {{
      width: 40px;
      height: 40px;
      background: var(--primary-gradient);
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      margin-bottom: 12px;
    }}
    .detail-label {{
      display: inline-block;
      font-size: 12px;
      color: var(--ink-muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .detail-budget {{
      font-size: 20px;
      font-weight: 800;
      color: var(--accent);
      margin: 4px 0;
    }}
    .detail-value {{ margin: 4px 0 8px; word-break: break-all; font-size: 13px; color: var(--ink-secondary); line-height: 1.6; }}
    .attachment-link {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--primary);
      color: #fff !important;
      padding: 8px 16px;
      border-radius: var(--radius-sm);
      font-size: 13px;
      font-weight: 600;
      transition: all 0.2s;
      text-decoration: none;
    }}
    .attachment-link:hover {{
      background: var(--primary-dark);
      transform: translateY(-1px);
      box-shadow: 0 2px 6px rgba(26, 86, 219, 0.3);
    }}

    /* ===== Footer ===== */
    .site-footer {{
      background: #1e293b;
      color: rgba(255,255,255,0.6);
      padding: 32px 0 24px;
      font-size: 13px;
      margin-top: auto;
    }}
    .footer-inner {{
      width: min(1200px, calc(100% - 32px));
      margin: 0 auto;
    }}
    .footer-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding-bottom: 20px;
      margin-bottom: 20px;
      border-bottom: 1px solid rgba(255,255,255,0.1);
      flex-wrap: wrap;
      gap: 24px;
    }}
    .footer-brand {{ font-size: 16px; font-weight: 700; color: #fff; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }}
    .footer-desc {{ max-width: 400px; line-height: 1.7; }}
    .footer-links {{ display: flex; gap: 32px; }}
    .footer-link-group h4 {{ color: rgba(255,255,255,0.8); font-size: 14px; margin-bottom: 10px; }}
    .footer-link-group a {{ display: block; color: rgba(255,255,255,0.5); font-size: 13px; margin-bottom: 6px; text-decoration: none; transition: color 0.2s; }}
    .footer-link-group a:hover {{ color: #fff; }}
    .footer-bottom {{ text-align: center; }}

    /* ===== Responsive ===== */
    @media (max-width: 768px) {{
      .hero {{ flex-direction: column; padding: 28px 20px; }}
      .hero-stats {{ width: 100%; justify-content: center; }}
      .quick-links {{ grid-template-columns: repeat(2, 1fr); }}
      .list-shell, .detail-shell {{ grid-template-columns: 1fr; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
      .overview-grid {{ grid-template-columns: 1fr; }}
      .header-nav {{ display: none; }}
      .pager {{ flex-direction: column; }}
      .page-numbers {{ justify-content: center; }}
    }}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="header-inner">
      <a href="/" class="site-logo">
        <div class="logo-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        </div>
        智慧城市公共资源交易中心
      </a>
      <nav class="header-nav">
        <a href="/" class="nav-active">首页</a>
        <a href="/announcements?page=1">通知公告</a>
        <a href="/">成交结果</a>
        <a href="#">政策法规</a>
        <a href="#">办事指南</a>
      </nav>
    </div>
  </header>
  <div class="sub-header">
    <div class="sub-header-inner">
      <div class="sub-header-left">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        <span>当前时间：<script>document.write(new Date().toLocaleDateString('zh-CN'))</script></span>
      </div>
      <span>服务热线：0755-12345678</span>
    </div>
  </div>
  <div class="page">{body}</div>
  <footer class="site-footer">
    <div class="footer-inner">
      <div class="footer-top">
        <div>
          <div class="footer-brand">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
            智慧城市公共资源交易中心
          </div>
          <p class="footer-desc">为各类市场主体提供公开、公平、公正的公共资源交易信息服务平台。本站所有数据仅用于测试目的。</p>
        </div>
        <div class="footer-links">
          <div class="footer-link-group">
            <h4>信息服务</h4>
            <a href="/announcements?page=1">通知公告</a>
            <a href="/">成交结果</a>
            <a href="#">政策法规</a>
          </div>
          <div class="footer-link-group">
            <h4>帮助中心</h4>
            <a href="#">操作手册</a>
            <a href="#">常见问题</a>
            <a href="#">联系我们</a>
          </div>
        </div>
      </div>
      <div class="footer-bottom">
        <p>© 2026 智慧城市公共资源交易中心 · 本网站为 AutoSpider E2E 测试模拟站点</p>
      </div>
    </div>
  </footer>
</body>
</html>"""
