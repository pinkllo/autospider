"""Generate remaining benchmark mock site scenarios and data assets."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK_SITE_DIR = ROOT / "mock_site"
SCENARIOS_DIR = ROOT / "scenarios"
GROUND_TRUTH_DIR = ROOT / "ground_truth"

CATEGORIES = {
    "Phones": [
        ("Comet Phone X", 5999.00, "Comet", "6.5-inch OLED, 12GB RAM"),
        ("Halo Phone Pro", 6799.00, "Halo", "6.7-inch AMOLED, 256GB"),
        ("Nova Flip Lite", 5499.00, "Nova", "Foldable shell, 8GB RAM"),
        ("Orbit Max 5G", 6299.00, "Orbit", "Snapdragon X, 512GB"),
        ("Zen One Mini", 3999.00, "Zen", "Compact 6.1-inch display"),
    ],
    "Computers": [
        ("Atlas Laptop 14", 7999.00, "Atlas", "14-inch IPS, 16GB RAM"),
        ("Atlas Desktop S", 8599.00, "Atlas", "Mini tower, RTX 4060"),
        ("BluePeak Book Air", 7399.00, "BluePeak", "13-inch OLED, 1TB SSD"),
        ("Forge Studio Tower", 9999.00, "Forge", "Ryzen 9, 32GB RAM"),
        ("Lumen Workstation", 11299.00, "Lumen", "Xeon class compute"),
    ],
    "Accessories": [
        ("Aero Dock Hub", 899.00, "Aero", "USB-C dock, dual display"),
        ("Clarity Webcam 4K", 1199.00, "Clarity", "4K sensor, AI framing"),
        ("Drift Mouse Pro", 499.00, "Drift", "Ergonomic wireless mouse"),
        ("Echo Keyboard Air", 699.00, "Echo", "Low-profile mechanical keys"),
        ("Pulse Charger 140W", 399.00, "Pulse", "GaN fast charger"),
    ],
}

DYNAMIC_ITEMS = [
    ("Flux Reader 8", 1899.00, "Flux", "8-inch e-ink, warm light"),
    ("Glide Cam Pocket", 2599.00, "Glide", "Pocket gimbal camera"),
    ("Ion Speaker Mini", 799.00, "Ion", "Portable stereo speaker"),
    ("Jade Tracker Tag", 299.00, "Jade", "Ultra-wideband finder"),
    ("Kite Drone SE", 3299.00, "Kite", "4K stabilized drone"),
    ("Lattice Lamp Bar", 599.00, "Lattice", "Ambient smart light"),
    ("Muse Pen Plus", 499.00, "Muse", "Pressure stylus"),
    ("Nimbus Display 27", 2499.00, "Nimbus", "27-inch 165Hz IPS"),
    ("Opal Mic Studio", 999.00, "Opal", "USB/XLR condenser mic"),
]

VARIANT_ITEMS = [
    ("Prism Phone Ultra", 7299.00, "Prism", "6.8-inch LTPO display", "card"),
    ("Quanta Tab Neo", 4399.00, "Quanta", "11-inch productivity tablet", "card"),
    ("Rift Earbuds X", 999.00, "Rift", "Spatial audio earbuds", "card"),
    ("Signal Watch Pro", 2199.00, "Signal", "Dual-band fitness watch", "card"),
    ("Talon Pad Mini", 1899.00, "Talon", "Compact drawing tablet", "card"),
    ("Umbra Router Mesh", 1299.00, "Umbra", "Mesh Wi-Fi 7 router", "table"),
    ("Vivid Cam 360", 1599.00, "Vivid", "360-degree action camera", "table"),
    ("Wave Projector 2", 3799.00, "Wave", "Short-throw projector", "table"),
    ("Xeno Drive 4TB", 1699.00, "Xeno", "External SSD 4TB", "table"),
    ("Yield Keyboard TKL", 899.00, "Yield", "Wireless TKL keyboard", "table"),
]

NESTED_LEAVES = [
    ("Electronics / Phones / Smartphones", ["Aster Smart 1", "Beacon Smart 2", "Cinder Smart 3"]),
    ("Electronics / Phones / Feature Phones", ["Dial Classic", "Echo Classic", "Fable Classic"]),
    ("Electronics / Computers / Laptops", ["Glint Book 13", "Harbor Book 15", "Iris Book Pro"]),
    ("Electronics / Computers / Desktops", ["Jolt Tower", "Kepler Tower", "Lyric Tower"]),
]


def main() -> None:
    write_shared_assets()
    write_categories_assets()
    write_dynamic_assets()
    write_variants_assets()
    write_nested_assets()


def write_shared_assets() -> None:
    write_text(
        MOCK_SITE_DIR / "shared" / "dynamic_load.js",
        "document.addEventListener('DOMContentLoaded',()=>{const btn=document.querySelector('.load-more-btn');if(!btn)return;btn.addEventListener('click',()=>{const next=document.querySelector('.load-batch[hidden]');if(!next){btn.disabled=true;return;}next.hidden=false;if(!document.querySelector('.load-batch[hidden]'))btn.disabled=true;});});\n",
    )
    write_text(
        MOCK_SITE_DIR / "shared" / "tabs.js",
        "document.addEventListener('DOMContentLoaded',()=>{const buttons=[...document.querySelectorAll('[data-tab-target]')];const panels=[...document.querySelectorAll('.tab-panel')];buttons.forEach(btn=>btn.addEventListener('click',()=>{buttons.forEach(item=>item.setAttribute('aria-selected','false'));panels.forEach(panel=>panel.hidden=true);btn.setAttribute('aria-selected','true');const panel=document.querySelector(btn.dataset.tabTarget);if(panel)panel.hidden=false;}));});\n",
    )


def write_categories_assets() -> None:
    records: list[dict[str, object]] = []
    cards: list[str] = []
    detail_index = 1
    for category, items in CATEGORIES.items():
        panel_cards = []
        for product_name, price, brand, specs in items:
            product_url = f"/scenarios/categories/detail_{detail_index}.html"
            panel_cards.append(
                listing_card(product_name, brand, price, f"detail_{detail_index}.html")
            )
            write_detail_page(
                MOCK_SITE_DIR / "scenarios" / "categories" / f"detail_{detail_index}.html",
                product_name,
                price,
                brand,
                specs,
                product_url,
                "index.html",
                extra_rows=[("category", category)],
            )
            records.append(
                record(product_name, price, brand, specs, product_url, category=category)
            )
            detail_index += 1
        panel = tab_panel(category, panel_cards, hidden=(category != "Phones"))
        cards.append(panel)
    index_html = page_shell(
        "TechMart Categories",
        "Explore products by category tabs.",
        '<nav class="tab-nav"><button class="tab-button" data-tab-target="#phones" aria-selected="true">Phones</button><button class="tab-button" data-tab-target="#computers" aria-selected="false">Computers</button><button class="tab-button" data-tab-target="#accessories" aria-selected="false">Accessories</button></nav>'
        + cards[0].replace('id="Phones"', 'id="phones"').replace("Phones", "Phones", 1)
        + cards[1].replace('id="Computers"', 'id="computers"').replace("Computers", "Computers", 1)
        + cards[2]
        .replace('id="Accessories"', 'id="accessories"')
        .replace("Accessories", "Accessories", 1),
        scripts='<script src="/shared/tabs.js" defer></script>',
    )
    write_text(MOCK_SITE_DIR / "scenarios" / "categories" / "index.html", index_html)
    write_yaml(
        "categories",
        "分类分组采集",
        "验证按分类页签分组采集。",
        "采集 {base_url}/scenarios/categories/index.html 中所有产品的 category、product_name、price、brand、specs 和 product_url",
        15,
        ["category", "product_name", "price", "brand", "specs", "product_url"],
        match_key="product_name",
    )
    write_jsonl(GROUND_TRUTH_DIR / "categories.jsonl", records)


def write_dynamic_assets() -> None:
    records: list[dict[str, object]] = []
    visible = [
        listing_card(item[0], item[2], item[1], f"detail_{index}.html")
        for index, item in enumerate(DYNAMIC_ITEMS[:3], start=1)
    ]
    batches = []
    for batch_index, start in enumerate((3, 6), start=1):
        cards = []
        for offset, item in enumerate(DYNAMIC_ITEMS[start : start + 3], start=start + 1):
            cards.append(listing_card(item[0], item[2], item[1], f"detail_{offset}.html"))
        batches.append(
            f'<div class="load-batch"{" hidden" if batch_index else ""}>{"".join(cards)}</div>'
        )
    body = (
        '<section class="product-grid">'
        + "".join(visible)
        + "</section>"
        + "".join(batches)
        + '<button class="load-more-btn" type="button">Load More</button>'
    )
    write_text(
        MOCK_SITE_DIR / "scenarios" / "dynamic" / "index.html",
        page_shell(
            "TechMart Dynamic",
            "Reveal more products progressively.",
            body,
            scripts='<script src="/shared/dynamic_load.js" defer></script>',
        ),
    )
    for index, (product_name, price, brand, specs) in enumerate(DYNAMIC_ITEMS, start=1):
        product_url = f"/scenarios/dynamic/detail_{index}.html"
        extra = '<section class="collapsible"><h2>Technical Details</h2><div class="collapsible-body"><p data-field="specs">{}</p></div></section>'.format(
            specs
        )
        write_text(
            MOCK_SITE_DIR / "scenarios" / "dynamic" / f"detail_{index}.html",
            detail_page(
                product_name, price, brand, specs, product_url, "index.html", extra_section=extra
            ),
        )
        records.append(record(product_name, price, brand, specs, product_url))
    write_yaml(
        "dynamic",
        "动态加载内容",
        "验证加载更多与折叠详情。",
        "采集 {base_url}/scenarios/dynamic/index.html 中所有产品的 product_name、price、brand、specs 和 product_url",
        9,
        ["product_name", "price", "brand", "specs", "product_url"],
        match_key="product_name",
    )
    write_jsonl(GROUND_TRUTH_DIR / "dynamic.jsonl", records)


def write_variants_assets() -> None:
    records: list[dict[str, object]] = []
    links = []
    for index, (product_name, price, brand, specs, layout) in enumerate(VARIANT_ITEMS, start=1):
        page_name = f"{layout}_{index if layout == 'card' else index - 5}.html"
        links.append(listing_card(product_name, brand, price, page_name))
        product_url = f"/scenarios/variants/{page_name}"
        if layout == "card":
            html = variant_card_page(product_name, price, brand, specs, product_url)
        else:
            html = variant_table_page(product_name, price, brand, specs, product_url)
        write_text(MOCK_SITE_DIR / "scenarios" / "variants" / page_name, html)
        records.append(
            record(product_name, price, brand, specs, product_url, layout_variant=layout)
        )
    write_text(
        MOCK_SITE_DIR / "scenarios" / "variants" / "index.html",
        page_shell("TechMart Variants", "Mix card and table detail layouts.", "".join(links)),
    )
    write_yaml(
        "variants",
        "布局变体采集",
        "验证不同 DOM 布局下的字段提取。",
        "采集 {base_url}/scenarios/variants/index.html 中所有产品的 product_name、price、brand、specs 和 product_url",
        10,
        ["product_name", "price", "brand", "specs", "product_url", "layout_variant"],
        match_key="product_name",
    )
    write_jsonl(GROUND_TRUTH_DIR / "variants.jsonl", records)


def write_nested_assets() -> None:
    records: list[dict[str, object]] = []
    leaf_links = []
    detail_index = 1
    for list_index, (category_path, names) in enumerate(NESTED_LEAVES, start=1):
        cards = []
        for name in names:
            price = 1999.00 + detail_index * 111
            brand = name.split()[0]
            specs = f"{category_path} tuned configuration {detail_index}"
            product_url = f"/scenarios/nested/detail_{detail_index}.html"
            cards.append(listing_card(name, brand, price, f"detail_{detail_index}.html"))
            write_detail_page(
                MOCK_SITE_DIR / "scenarios" / "nested" / f"detail_{detail_index}.html",
                name,
                price,
                brand,
                specs,
                product_url,
                f"list_{list_index}.html",
                extra_rows=[("category_path", category_path)],
            )
            records.append(
                record(name, price, brand, specs, product_url, category_path=category_path)
            )
            detail_index += 1
        write_text(
            MOCK_SITE_DIR / "scenarios" / "nested" / f"list_{list_index}.html",
            page_shell(category_path, "Leaf category products.", "".join(cards)),
        )
        leaf_links.append(f'<li><a href="list_{list_index}.html">{category_path}</a></li>')
    tree = '<nav class="tree-nav"><ul>{}</ul></nav>'.format("".join(leaf_links))
    write_text(
        MOCK_SITE_DIR / "scenarios" / "nested" / "index.html",
        page_shell("TechMart Nested", "Browse a three-level tree.", tree),
    )
    write_yaml(
        "nested",
        "嵌套多层导航",
        "验证树形导航与叶子分类采集。",
        "采集 {base_url}/scenarios/nested/index.html 中所有产品的 category_path、product_name、price、brand、specs 和 product_url",
        12,
        ["category_path", "product_name", "price", "brand", "specs", "product_url"],
        match_key="product_name",
    )
    write_jsonl(GROUND_TRUTH_DIR / "nested.jsonl", records)


def page_shell(title: str, description: str, body: str, scripts: str = "") -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        f'<title>{title}</title><link rel="stylesheet" href="/shared/style.css" />{scripts}</head>'
        f'<body><main class="site-shell"><section class="hero"><h1>{title}</h1><p>{description}</p></section>{body}</main></body></html>'
    )


def detail_page(
    product_name: str,
    price: float,
    brand: str,
    specs: str,
    product_url: str,
    back_href: str,
    extra_section: str = "",
) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        f'<title>{product_name}</title><link rel="stylesheet" href="/shared/style.css" /></head><body><main class="site-shell"><article class="detail-panel">'
        f'<h1 data-field="product_name">{product_name}</h1><dl><dt>Price</dt><dd data-field="price">{price:.2f}</dd><dt>Brand</dt><dd data-field="brand">{brand}</dd>'
        f'<dt>Specs</dt><dd data-field="specs">{specs}</dd><dt>Product URL</dt><dd><a data-field="product_url" href="{product_url}">{product_url}</a></dd></dl>{extra_section}'
        f'<div class="detail-actions"><a href="{back_href}">Back</a></div></article></main></body></html>'
    )


def write_detail_page(
    path: Path,
    product_name: str,
    price: float,
    brand: str,
    specs: str,
    product_url: str,
    back_href: str,
    extra_rows: list[tuple[str, str]],
) -> None:
    extra_html = "".join(
        f'<dt>{name}</dt><dd data-field="{name}">{value}</dd>' for name, value in extra_rows
    )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        f'<title>{product_name}</title><link rel="stylesheet" href="/shared/style.css" /></head><body><main class="site-shell"><article class="detail-panel">'
        f'<h1 data-field="product_name">{product_name}</h1><dl><dt>Price</dt><dd data-field="price">{price:.2f}</dd><dt>Brand</dt><dd data-field="brand">{brand}</dd>'
        f'<dt>Specs</dt><dd data-field="specs">{specs}</dd>{extra_html}<dt>Product URL</dt><dd><a data-field="product_url" href="{product_url}">{product_url}</a></dd></dl>'
        f'<div class="detail-actions"><a href="{back_href}">Back</a></div></article></main></body></html>'
    )
    write_text(path, html)


def tab_panel(name: str, cards: list[str], hidden: bool) -> str:
    hidden_attr = " hidden" if hidden else ""
    return f'<section class="tab-panel" id="{name}"{hidden_attr}>{"".join(cards)}</section>'


def listing_card(product_name: str, brand: str, price: float, href: str) -> str:
    return f'<article class="product-card"><h2><a href="{href}">{product_name}</a></h2><p class="listing-meta">{brand}</p><p class="price-tag">{price:.2f}</p></article>'


def variant_card_page(
    product_name: str, price: float, brand: str, specs: str, product_url: str
) -> str:
    body = f'<article class="detail-panel"><h1 data-field="product_name">{product_name}</h1><div class="price-tag" data-field="price">{price:.2f}</div><div data-field="brand">{brand}</div><div data-field="specs">{specs}</div><a data-field="product_url" href="{product_url}">{product_url}</a></article>'
    return page_shell(product_name, "Card layout detail page.", body)


def variant_table_page(
    product_name: str, price: float, brand: str, specs: str, product_url: str
) -> str:
    table = f'<table class="detail-panel"><tr><th>Product</th><td data-field="product_name">{product_name}</td></tr><tr><th>Price</th><td data-field="price">{price:.2f}</td></tr><tr><th>Brand</th><td data-field="brand">{brand}</td></tr><tr><th>Specs</th><td data-field="specs">{specs}</td></tr><tr><th>Product URL</th><td><a data-field="product_url" href="{product_url}">{product_url}</a></td></tr></table>'
    return page_shell(product_name, "Table layout detail page.", table)


def record(
    product_name: str, price: float, brand: str, specs: str, product_url: str, **extra: object
) -> dict[str, object]:
    return {
        "product_name": product_name,
        "price": price,
        "brand": brand,
        "specs": specs,
        "product_url": product_url,
        **extra,
    }


def write_yaml(
    scenario_id: str,
    name: str,
    description: str,
    request: str,
    record_count: int,
    fields: list[str],
    match_key: str,
) -> None:
    field_block = "\n".join(
        f"    - name: \"{field_name}\"\n      type: \"{'number' if field_name == 'price' else 'text' if 'url' not in field_name else 'url'}\"\n      required: true"
        for field_name in fields
    )
    matching = "\n".join(
        f"    {field_name}: {'numeric_tolerance' if field_name == 'price' else 'exact'}"
        for field_name in fields
    )
    content = (
        f'scenario:\n  id: {scenario_id}\n  name: "{name}"\n  description: "{description}"\n\n'
        f'task:\n  request: "{request}"\n  cli_overrides:\n    max_pages: 6\n    serial_mode: true\n    headless: true\n    output_dir: ".tmp/benchmark/{scenario_id}"\n\n'
        f'ground_truth:\n  file: "ground_truth/{scenario_id}.jsonl"\n  record_count: {record_count}\n  fields:\n{field_block}\n\n'
        f'evaluation:\n  match_key: "{match_key}"\n  field_matching:\n{matching}\n  thresholds:\n    min_record_recall: 0.8\n    min_field_f1: 0.7\n    max_steps: 50\n'
    )
    write_text(SCENARIOS_DIR / f"{scenario_id}.yaml", content)


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    write_text(path, "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
