"""
pdf_parser.py — Extract character data from D&D Beyond PDF exports.

Renders PDF pages to images and sends them to Claude's vision API
for reliable character sheet reading. D&D Beyond PDFs use form fields
that standard text extraction can't read, but Claude can read the
rendered pages visually.
"""

import base64
import aiohttp
import fitz  # PyMuPDF


async def download_pdf(url: str) -> bytes:
    """Download a PDF from a URL and return raw bytes."""
    if not url.startswith("http"):
        url = "https://" + url

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                raise ValueError(f"Failed to download PDF — HTTP {resp.status}")
            return await resp.read()


def render_pages_to_images(pdf_bytes: bytes, dpi: int = 200) -> list[str]:
    """
    Render each PDF page to a PNG image and return as base64 strings.
    Caps at 6 pages (standard D&D Beyond sheet length).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []

    for page_num in range(min(len(doc), 6)):
        page = doc[page_num]
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix)
        png_bytes = pixmap.tobytes("png")
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        images.append(b64)

    doc.close()
    return images


async def pdf_to_images_from_url(url: str) -> list[str]:
    """Download a PDF and render all pages as base64 PNG images."""
    pdf_bytes = await download_pdf(url)
    return render_pages_to_images(pdf_bytes)


async def pdf_to_images_from_bytes(pdf_bytes: bytes) -> list[str]:
    """Render a PDF from raw bytes as base64 PNG images."""
    return render_pages_to_images(pdf_bytes)
