"""HTML → PDF über Playwright/Chromium. A4, mit MathJax-Warten."""
from playwright.async_api import async_playwright


PDF_MARGIN = {"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"}


async def render_pdf(html: str) -> bytes:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            # MathJax: lädt async aus CDN, dann gibt es eine startup-Promise.
            # Wenn MathJax nicht vorkommt, returnt evaluate sofort.
            await page.evaluate("""
                async () => {
                  if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
                    await MathJax.startup.promise;
                    if (MathJax.typesetPromise) await MathJax.typesetPromise();
                  }
                }
            """)
            pdf_bytes = await page.pdf(
                format="A4",
                margin=PDF_MARGIN,
                print_background=True,
                prefer_css_page_size=False,
            )
            return pdf_bytes
        finally:
            await browser.close()
