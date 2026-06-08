"""HTML renderer for the API landing page."""

from __future__ import annotations

from html import escape

from server.app_metadata import ApiMetadata, get_yunesa_banner


def render_api_homepage(metadata: ApiMetadata, base_url: str) -> str:
    """Render the human-readable API root page."""
    banner = escape(get_yunesa_banner(metadata.version))
    docs_href = escape(metadata.docs_url)
    health_href = escape(metadata.health_url)
    docs_absolute = f"{base_url.rstrip('/')}{metadata.docs_url}"

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(metadata.title)}</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #07110f;
        --panel: rgba(14, 28, 25, 0.82);
        --panel-strong: rgba(18, 38, 33, 0.96);
        --line: rgba(125, 211, 185, 0.22);
        --text: #e7fff8;
        --muted: #9fc7bc;
        --accent: #6ee7b7;
        --accent-2: #38bdf8;
        --warn: #facc15;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        min-height: 100vh;
        margin: 0;
        display: grid;
        place-items: center;
        padding: 32px;
        background:
          radial-gradient(circle at 18% 18%, rgba(56, 189, 248, 0.18), transparent 28%),
          radial-gradient(circle at 82% 12%, rgba(110, 231, 183, 0.18), transparent 30%),
          linear-gradient(145deg, #07110f 0%, #0b1714 48%, #050807 100%);
        color: var(--text);
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      main {{
        width: min(1040px, 100%);
        border: 1px solid var(--line);
        border-radius: 18px;
        background: linear-gradient(180deg, var(--panel-strong), var(--panel));
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.42);
        overflow: hidden;
      }}
      .hero {{
        padding: clamp(24px, 4vw, 44px);
        border-bottom: 1px solid var(--line);
      }}
      pre {{
        margin: 0;
        overflow-x: auto;
        color: var(--accent);
        font: 700 clamp(10px, 1.45vw, 16px) / 1.16 "Cascadia Mono", "Fira Code", Consolas, monospace;
        text-shadow: 0 0 24px rgba(110, 231, 183, 0.28);
      }}
      .content {{
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 24px;
        padding: clamp(22px, 3vw, 34px);
      }}
      h1 {{
        margin: 0 0 10px;
        font-size: clamp(28px, 4vw, 48px);
        letter-spacing: 0;
      }}
      p {{
        margin: 0;
        color: var(--muted);
        line-height: 1.7;
      }}
      .actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-top: 24px;
      }}
      a {{
        color: inherit;
        text-decoration: none;
      }}
      .btn {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 42px;
        padding: 0 16px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.04);
        font-weight: 700;
      }}
      .btn.primary {{
        color: #04251b;
        border-color: transparent;
        background: linear-gradient(135deg, var(--accent), var(--accent-2));
      }}
      .meta {{
        display: grid;
        gap: 10px;
      }}
      .row {{
        display: flex;
        justify-content: space-between;
        gap: 18px;
        padding: 12px 0;
        border-bottom: 1px solid rgba(125, 211, 185, 0.12);
      }}
      .row span:first-child {{
        color: var(--muted);
      }}
      .row span:last-child {{
        text-align: right;
        font-weight: 700;
      }}
      .status {{
        color: var(--accent);
      }}
      code {{
        color: var(--warn);
        font-family: "Cascadia Mono", "Fira Code", Consolas, monospace;
      }}
      @media (max-width: 780px) {{
        body {{ padding: 16px; }}
        .content {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <pre aria-label="Yunesa banner">{banner}</pre>
      </section>
      <section class="content">
        <div>
          <h1>{escape(metadata.title)}</h1>
          <p>
            {escape(metadata.description)} untuk retrieval berbasis Neo4j graph dan Milvus vector context.
            Gunakan dokumentasi interaktif untuk melihat endpoint yang tersedia.
          </p>
          <div class="actions">
            <a class="btn primary" href="{docs_href}">Open API Docs</a>
            <a class="btn" href="{health_href}">Health Check</a>
          </div>
        </div>
        <div class="meta" aria-label="API metadata">
          <div class="row"><span>Status</span><span class="status">{escape(metadata.status)}</span></div>
          <div class="row"><span>Version</span><span>v{escape(metadata.version)}</span></div>
          <div class="row"><span>Environment</span><span>{escape(metadata.environment)}</span></div>
          <div class="row"><span>Docs</span><span><code>{escape(docs_absolute)}</code></span></div>
          <div class="row"><span>Author</span><span>{escape(metadata.author)}</span></div>
          <div class="row"><span>Timestamp</span><span>{escape(metadata.timestamp)}</span></div>
        </div>
      </section>
    </main>
  </body>
</html>"""

