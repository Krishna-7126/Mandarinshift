"""
tests/visual_renderer.py — QA utility for rendering DOCX to PDF/images using installed local tools.

Inspects system for Microsoft Word COM or LibreOffice to render DOCX files to PDF,
then uses pypdfium2 to render pages to raster PNG images for visual QA comparison.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import pypdfium2

log = logging.getLogger(__name__)


class DocxVisualRenderer:
    """Renders DOCX files to PDF and page images using locally installed software."""

    @classmethod
    def is_available(cls) -> bool:
        """Return True if a local Word COM or LibreOffice renderer is detected."""
        return cls.find_renderer() is not None

    @classmethod
    def find_renderer(cls) -> Optional[str]:
        """Return 'word_com', 'libreoffice', or None depending on what is installed."""
        # 1. Check for LibreOffice in PATH or standard install paths
        if shutil.which("soffice") or shutil.which("libreoffice"):
            return "libreoffice"
        lo_paths = [
            Path("C:/Program Files/LibreOffice/program/soffice.exe"),
            Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
        ]
        if any(p.exists() for p in lo_paths):
            return "libreoffice"

        # 2. Check for Microsoft Word
        word_paths = [
            Path("C:/Program Files/Microsoft Office/root/Office16/WINWORD.EXE"),
            Path("C:/Program Files (x86)/Microsoft Office/root/Office16/WINWORD.EXE"),
        ]
        if any(p.exists() for p in word_paths) or os.name == "nt":
            # Test if COM object actually creates
            try:
                ps_cmd = "$w = New-Object -ComObject Word.Application; $w.Visible = $false; $w.Quit()"
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True,
                    timeout=10,
                )
                if res.returncode == 0:
                    return "word_com"
            except Exception:
                pass

        return None

    @classmethod
    def render_docx_to_pdf(cls, docx_path: Path, output_pdf: Path) -> bool:
        """Convert docx_path to output_pdf using available renderer. Returns True on success."""
        renderer = cls.find_renderer()
        if not renderer:
            return False

        docx_path = Path(docx_path).resolve()
        output_pdf = Path(output_pdf).resolve()
        output_pdf.parent.mkdir(parents=True, exist_ok=True)

        if renderer == "word_com":
            # Use PowerShell Word COM
            ps_script = (
                f"$w = New-Object -ComObject Word.Application\n"
                f"$w.Visible = $false\n"
                f"$w.DisplayAlerts = 0\n"
                f"try {{\n"
                f"  $doc = $w.Documents.Open('{docx_path}')\n"
                f"  $doc.SaveAs2('{output_pdf}', 17)\n"
                f"  $doc.Close()\n"
                f"}} finally {{\n"
                f"  $w.Quit()\n"
                f"  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($w) | Out-Null\n"
                f"}}\n"
            )
            for attempt in range(2):
                with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
                    f.write(ps_script)
                    script_path = f.name
                try:
                    res = subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if res.returncode == 0 and output_pdf.exists() and output_pdf.stat().st_size > 0:
                        return True
                    if attempt == 0:
                        import time
                        time.sleep(1.0)
                    else:
                        log.warning("DocxVisualRenderer Word COM output:\n%s\nErrors:\n%s", res.stdout, res.stderr)
                finally:
                    if os.path.exists(script_path):
                        try:
                            os.unlink(script_path)
                        except OSError:
                            pass
            return output_pdf.exists() and output_pdf.stat().st_size > 0

        elif renderer == "libreoffice":
            soffice = shutil.which("soffice") or "soffice"
            cmd = [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_pdf.parent),
                str(docx_path),
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=30)
            return res.returncode == 0 and output_pdf.exists()

        return False

    @classmethod
    def render_docx_to_page_images(cls, docx_path: Path, output_dir: Path, dpi: int = 150) -> list[Path]:
        """Convert docx_path to raster PNG images (one per page)."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_pdf = output_dir / f"{docx_path.stem}_rendered.pdf"
        try:
            success = cls.render_docx_to_pdf(docx_path, temp_pdf)
            if not success or not temp_pdf.exists():
                return []
            pdf_doc = pypdfium2.PdfDocument(temp_pdf)
            scale = dpi / 72.0
            image_paths: list[Path] = []
            try:
                for i, page in enumerate(pdf_doc):
                    img = page.render(scale=scale).to_pil()
                    img_path = output_dir / f"{docx_path.stem}_page_{i + 1}.png"
                    img.save(img_path, format="PNG")
                    image_paths.append(img_path)
                return image_paths
            finally:
                pdf_doc.close()
        finally:
            if temp_pdf.exists():
                temp_pdf.unlink()


if __name__ == "__main__":
    renderer = DocxVisualRenderer.find_renderer()
    print(f"Detected renderer: {renderer}")
