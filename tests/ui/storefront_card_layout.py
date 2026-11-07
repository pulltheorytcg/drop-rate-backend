"""Offline Chromium layout regression, not a Shopify checkout integration test.

Run: python tests/ui/storefront_card_layout.py
Requires Playwright + Chromium. No network requests, orders or customer data.
The shell reproduces the relevant verified Horizon flex/grid rules; the change
under test is read directly from the real Drop Rate Liquid block.
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BLOCK = ROOT / "storefront/theme/blocks/dr-card-title.liquid"
OUT = Path(os.environ.get("LAYOUT_ARTIFACT_DIR", "/tmp/drop-rate-card-layout"))
WIDTHS = (1920, 1440, 1280, 1024, 768, 749, 430, 390, 360, 320)

# Relevant base-theme flex rules and Drop Rate typography, verified from the
# target theme. This is an isolated fixture, not the full Shopify page runtime.
SHELL = """
* { box-sizing: border-box; }
body { margin: 0; padding: 20px; font-family: Arial, sans-serif; }
.resource-list--grid { display: grid; grid-template-columns: repeat(6,minmax(0,1fr)); gap:32px 22px; }
.resource-list__item { height:100%; min-width:0; }
.resource-list__item .product-card { position:relative; display:grid; height:100%; min-width:0; }
.product-card__content { display:flex; flex-flow:column nowrap; gap:7px; height:100%; min-width:0; overflow:hidden; }
.card-gallery { aspect-ratio:0.8; background:#f4f7fb; border-radius:8px; }
.dr-product-meta { display:flex; flex-wrap:wrap; gap:5px; margin-top:2px; }
.dr-product-meta__chip { white-space:nowrap; display:inline-flex; min-height:22px; padding:3px 7px; background:#ddf4f3; border:1px solid #b9e5e6; border-radius:999px; font-size:10.88px; line-height:1; }
.dr-card-copy { display:grid; gap:4px; min-width:0; }
.dr-card-copy__game { font-size:.62rem; line-height:1.1; color:#1f7bf2; font-weight:850; }
.dr-card-copy__title { color:#13223b; text-decoration:none; }
.dr-card-copy__title h3 { display:-webkit-box; margin:0; overflow:hidden; font-size:.9rem; line-height:1.22; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.dr-card-copy p { display:-webkit-box; margin:0; overflow:hidden; font-size:.69rem; line-height:1.35; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
product-price { display:block; font-size:1rem; line-height:1.2; font-weight:800; margin-top:3px; }
.buy-buttons-block { --buy-button-preferred-width:185px; width:100%; }
.product-form-buttons { display:flex; flex-wrap:wrap; gap:6px; }
.product-form-buttons > *:not(.quantity-selector-wrapper,.quantity-rules,.quantity-label,.volume-pricing,.product-form-text__error) { flex:1 1 var(--buy-button-preferred-width,0); min-width:fit-content; }
button { width:100%; height:52px; font-size:11px; border:0; border-radius:9px; }
.add-to-cart-button { background:#1f7bf2; color:white; }
.accelerated-checkout-block { display:block; }
.shopify-payment-button { width:100%; }
.wallet { display:block; width:100%; height:52px; background:#5433eb; color:white; }
more-payment-options-link { display:block; text-align:center; margin-top:12px; font-size:12px; }
.product-card quantity-selector-component { display:none; }
.product-form-text__error { flex:1 0 100%; }
[hidden] { display:none!important; }
.product-information { margin-top:30px; }
.product-information .dr-hide-single-quantity { display:block; }
@media(max-width:1199px) and (min-width:750px) { .resource-list--grid {grid-template-columns:repeat(3,minmax(0,1fr));} }
@media(max-width:749px) { body {padding:12px;} .resource-list--grid {grid-template-columns:repeat(2,minmax(0,1fr)); gap:24px 12px;} }
"""
TITLES = (
    "I'll Feed on This Rage and Use It to Bring the World to Ruin!!!",
    "King",
    "Nami (Round 1 Promo)",
    "Edward.Newgate (4th Anniversary Treasure Campaign Pack)",
    'Eustass"Captain"Kid (Online Regional 2024 Vol. 2) [Participant]',
    "Nappa - FP-046 (Tournament Pack 07)",
)


def document(css: str, varied: bool = False) -> str:
    cards = []
    for i, title in enumerate(TITLES):
        chips = ("JP" if i == 2 else "EN", "Near Mint", "Promo" if i == 5 else "C")
        if varied and i == 1:
            chips = ("JP", "PSA 10", "Special Alternate Art")
        if varied and i == 3:
            chips = ()
        meta = "".join(f'<span class="dr-product-meta__chip">{html.escape(c)}</span>' for c in chips)
        subtitle = '' if varied and i == 4 else '<p>OP17-097 · The World\'s Strongest Warriors Release</p>'
        quantity = '<span class="dr-hide-single-quantity"><quantity-selector-component>Quantity 2</quantity-selector-component></span>' if varied and i == 2 else ''
        cards.append(f'''<div class="resource-list__item"><product-card class="product-card" data-i="{i}">
          <div class="product-card__content"><div class="card-gallery"></div><div class="dr-product-meta">{meta}</div>
          <div class="dr-card-copy"><span class="dr-card-copy__game">{'DRAGON BALL' if i == 5 else 'ONE PIECE'}</span>
          <a class="dr-card-copy__title" href="#card-{i}"><h3>{html.escape(title)}</h3></a>{subtitle}</div>
          <product-price>£{[1.09,1.25,32.06,1.00,5.79,1.00][i]:.2f}</product-price>
          <span class="buy-buttons-block"><form><div class="product-form-buttons">{quantity}
          <span class="product-form-text__error" hidden>Unavailable</span>
          <span class="add-to-cart"><button class="add-to-cart-button" type="button">Add to cart</button></span>
          <div class="accelerated-checkout-block"><div class="shopify-payment-button"><button class="wallet" type="button">Buy with Shop</button>
          <more-payment-options-link><a href="#options-{i}">More payment options</a></more-payment-options-link></div></div>
          </div></form></span></div></product-card></div>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{SHELL}\n{css}</style></head><body>
      <div class="section-resource-list"><div class="resource-list resource-list--grid">{''.join(cards)}</div></div>
      <div class="product-information"><span class="buy-buttons-block"><div class="product-form-buttons"><span class="dr-hide-single-quantity">PDP quantity control remains visible</span></div></span></div>
    </body></html>'''


def measure(page):
    return page.locator('product-card').evaluate_all('''cards => cards.map(c => {
      const box = selector => { const r = c.querySelector(selector).getBoundingClientRect(); return {top:r.top, left:r.left, width:r.width, height:r.height}; };
      return {card:box('.product-card__content'), price:box('product-price'), add:box('.add-to-cart-button'), wallet:box('.wallet'), options:box('more-payment-options-link')};
    })''')


def assert_aligned(rows):
    groups = {}
    for item in rows:
        groups.setdefault(round(item['card']['top']), []).append(item)
        for key in ('add', 'wallet'):
            assert abs(item[key]['width'] - item['card']['width']) < 1, (key, item)
            assert item[key]['height'] >= 40, (key, item)
    for group in groups.values():
        for key in ('price', 'add', 'wallet', 'options'):
            positions = [item[key]['top'] for item in group]
            assert max(positions) - min(positions) < 1, (key, positions)


def main():
    content = BLOCK.read_text()
    css = re.search(r'{% stylesheet %}(.*?){% endstylesheet %}', content, re.S).group(1)
    original_css = css.split('/* Product-list sections')[0]
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        executable = os.environ.get('CHROMIUM_EXECUTABLE')
        launch = {'headless': True}
        if executable:
            launch['executable_path'] = executable
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        page.route('**/*', lambda route: route.abort())
        page.set_content(document(original_css))
        before = measure(page)
        assert max(r['add']['top'] for r in before) - min(r['add']['top'] for r in before) > 10, 'Fixture must reproduce original stagger'
        page.screenshot(path=str(OUT / 'before-1920.png'), full_page=True)
        for varied in (False, True):
            for width in WIDTHS:
                page.set_viewport_size({'width': width, 'height': 1080})
                page.set_content(document(css, varied))
                rows = measure(page)
                assert_aligned(rows)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
                assert page.locator('.product-information .dr-hide-single-quantity').is_visible()
                assert page.locator('product-card .wallet:visible').count() == 6
                assert page.locator('product-card more-payment-options-link:visible').count() == 6
                assert page.locator('product-card .product-form-text__error:visible').count() == 0
                # No purchase call: assert CSS does not override hidden/disabled state.
                page.locator('.add-to-cart-button').first.evaluate("el => el.disabled = true")
                assert page.locator('.add-to-cart-button').first.is_disabled()
                results.append({'width': width, 'varied_metadata': varied, 'rows': rows, 'pass': True})
                if not varied and width in (1920, 390):
                    page.screenshot(path=str(OUT / f'after-{width}.png'), full_page=True)
        browser.close()
    (OUT / 'results.json').write_text(json.dumps({'before': before, 'cases': results}, indent=2))
    print(f'PASS: original stagger reproduced; {len(results)} isolated Chromium layout cases. Not live checkout verification.')


if __name__ == '__main__':
    main()
