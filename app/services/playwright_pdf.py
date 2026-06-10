"""HTML → PDF über Playwright/Chromium. A4, mit MathJax-Warten."""
from playwright.async_api import async_playwright


PDF_MARGIN = {"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"}


async def render_pdf(html: str) -> bytes:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = await browser.new_page()
            # Konsolen-Fehler einsammeln (z. B. blockiertes MathJax-CDN)
            console_errors: list[str] = []
            page.on("console", lambda msg: console_errors.append(msg.text)
                    if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))
            await page.set_content(html, wait_until="networkidle")
            # MathJax: lädt async aus CDN. Wir warten aktiv (max. 15s),
            # bis startup.promise verfügbar ist und typesetPromise fertig
            # ist. Bei Templates ohne MathJax-Script (z. B. einfache PDFs)
            # gibt es nie ein <script id="MathJax-script">; dann sofort
            # weiter. Bei Netzwerk-Blockade nach 15s ohne Typeset weiter
            # (Formeln bleiben dann roh — nicht schöner, aber kein Hang).
            mathjax_status = await page.evaluate("""
                async () => {
                  if (!document.getElementById('MathJax-script')) return 'no-mathjax';
                  const t0 = Date.now();
                  while (Date.now() - t0 < 15000) {
                    if (window.MathJax && MathJax.startup
                        && MathJax.startup.promise) {
                      try {
                        await MathJax.startup.promise;
                        if (MathJax.typesetPromise) await MathJax.typesetPromise();
                        return 'ok';
                      } catch (e) {
                        return 'error: ' + (e && e.message || e);
                      }
                    }
                    await new Promise(r => setTimeout(r, 80));
                  }
                  return 'timeout';
                }
            """)
            if mathjax_status not in ("ok", "no-mathjax"):
                import logging
                logging.warning(
                    "playwright_pdf: MathJax-Status %r · console-errors=%s",
                    mathjax_status, console_errors[:5])
            pdf_bytes = await page.pdf(
                format="A4",
                margin=PDF_MARGIN,
                print_background=True,
                prefer_css_page_size=False,
            )
            return pdf_bytes
        finally:
            await browser.close()
