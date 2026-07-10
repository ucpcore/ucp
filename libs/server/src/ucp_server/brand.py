"""Rangor product branding (protocol remains ucpcore/UCP)."""
from __future__ import annotations

PRODUCT_NAME = "Rangor"
PRODUCT_DOMAIN = "rangor.io"
TAGLINE = "full range of context, right when you need it"
MCP_SERVER_KEY = "rangor"
MCP_ICON_URL = f"https://app.{PRODUCT_DOMAIN}/brand/mark.svg"

# Inline SVG for HTML consent / landing pages (currentColor = black/white via CSS).
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" aria-hidden="true">
  <path d="M16 2.5 27.75 9.25v13.5L16 29.5 4.25 22.75v-13.5L16 2.5Z" stroke="currentColor" stroke-width="1.75"/>
  <path d="M16 9v14M9.2 12.5l13.6 7.8M22.8 12.5 9.2 20.3" stroke="currentColor" stroke-width="1.65" stroke-linecap="round"/>
</svg>"""
