"""
localshift.documents.docx_renderer — Offline DOCX to PDF Document Rendering Subsystem.

Supported Backends:
1. LibreOffice Headless (soffice.exe --headless --convert-to pdf)
2. Microsoft Word COM Automation (Word.Application via PowerShell on Windows)

Guarantees:
- 100% offline local processing (zero cloud calls, zero runtime downloads).
- Source document immutability (opened ReadOnly, never modified or rewritten in place).
- Sandboxed execution: processes run against isolated temporary copies.
- Timeout handling and cooperative cancellation.
- Complete temporary file cleanup on both success and failure.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional

from ..exceptions import (
    AdapterUnavailableError,
    ConversionCancelledError,
    ConversionFailedError,
    InvalidInputError,
)

log = logging.getLogger(__name__)

# Cached availability of Word COM to avoid repeated COM server startup checks
_WORD_COM_AVAILABLE_CACHE: Optional[bool] = None


class DocxToPdfRenderer:
    """Document rendering subsystem translating Microsoft Word (.docx) to PDF."""

    DEFAULT_TIMEOUT_SECONDS: int = 60

    @classmethod
    def find_libreoffice_binary(cls) -> Optional[Path]:
        """Return the Path to soffice executable, or None if not installed."""
        # 1. Explicit environment variable override
        custom_env = os.environ.get("LOCALSHIFT_LIBREOFFICE_PATH")
        if custom_env:
            p = Path(custom_env)
            if p.is_file():
                return p

        # 2. Check PATH
        which_soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if which_soffice:
            return Path(which_soffice)

        # 3. Standard Windows install paths
        candidates = [
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "LibreOffice/program/soffice.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "LibreOffice/program/soffice.exe",
        ]
        for c in candidates:
            if c.is_file():
                return c

        return None

    @classmethod
    def is_word_com_available(cls) -> bool:
        """Return True if Microsoft Word COM automation is functional on Windows."""
        global _WORD_COM_AVAILABLE_CACHE
        if _WORD_COM_AVAILABLE_CACHE is not None:
            return _WORD_COM_AVAILABLE_CACHE

        if os.name != "nt":
            _WORD_COM_AVAILABLE_CACHE = False
            return False

        # Quick check for Word executable on disk
        word_candidates = [
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft Office/root/Office16/WINWORD.EXE",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Office/root/Office16/WINWORD.EXE",
        ]
        has_winword_exe = any(p.is_file() for p in word_candidates)

        # Test COM instantiation via PowerShell with a strict 8-second timeout
        try:
            ps_test = (
                "$w = New-Object -ComObject Word.Application; "
                "$w.Visible = $false; "
                "$w.Quit(); "
                "[System.Runtime.InteropServices.Marshal]::ReleaseComObject($w) | Out-Null"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_test],
                capture_output=True,
                text=True,
                timeout=8,
            )
            available = (res.returncode == 0)
        except Exception as exc:
            log.debug("Word COM availability test failed: %s", exc)
            available = False

        _WORD_COM_AVAILABLE_CACHE = available
        return available

    @classmethod
    def find_available_backend(cls) -> Optional[str]:
        """Return 'libreoffice', 'word_com', or None depending on available backends."""
        if cls.find_libreoffice_binary() is not None:
            return "libreoffice"
        if cls.is_word_com_available():
            return "word_com"
        return None

    @classmethod
    def is_backend_available(cls) -> bool:
        """Return True if at least one valid rendering backend is installed."""
        return cls.find_available_backend() is not None

    @classmethod
    def render_docx_to_pdf(
        cls,
        source_docx: Path,
        output_pdf: Path,
        *,
        renderer: str = "auto",
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Convert source_docx to output_pdf using an offline rendering backend.

        Parameters
        ----------
        source_docx:
            Path to the source .docx document.
        output_pdf:
            Destination path for the rendered .pdf.
        renderer:
            'auto', 'libreoffice', or 'word_com'.
        timeout:
            Maximum rendering time in seconds (clamped 5 to 300).
        cancel_check:
            Optional callback returning True if cancellation was requested.

        Returns
        -------
        Path
            Path to the verified output PDF.
        """
        if cancel_check and cancel_check():
            raise ConversionCancelledError("Conversion cancelled before rendering started.")

        source_docx = Path(source_docx).resolve()
        output_pdf = Path(output_pdf).resolve()

        # 1. Validate source file exists and is regular file
        if not source_docx.is_file():
            raise InvalidInputError(f"Source file does not exist or is not a regular file: {source_docx}")

        # 2. Validate DOCX format integrity (magic bytes + valid zip containing word/document.xml)
        try:
            with open(source_docx, "rb") as f:
                header = f.read(4)
            if header != b"PK\x03\x04":
                raise InvalidInputError(f"Input file is not a valid DOCX container (missing PK zip header): {source_docx}")

            if not zipfile.is_zipfile(source_docx):
                raise InvalidInputError(f"Input file is a damaged or corrupted zip archive: {source_docx}")

            with zipfile.ZipFile(source_docx, "r") as zf:
                if "word/document.xml" not in zf.namelist():
                    raise InvalidInputError(
                        f"Zip archive is not a Word document (missing word/document.xml): {source_docx}"
                    )
        except InvalidInputError:
            raise
        except Exception as exc:
            raise InvalidInputError(f"Could not read DOCX file structure: {exc}") from exc

        # 3. Resolve rendering backend
        selected_backend: Optional[str] = None
        norm_renderer = renderer.lower().strip()

        if norm_renderer == "auto":
            selected_backend = cls.find_available_backend()
            if not selected_backend:
                raise AdapterUnavailableError(
                    "DOCX to PDF conversion requires an offline document rendering backend "
                    "(LibreOffice or Microsoft Word). None was detected on this system."
                )
        elif norm_renderer == "libreoffice":
            if cls.find_libreoffice_binary() is None:
                raise AdapterUnavailableError(
                    "Selected renderer 'libreoffice' is not installed or not found on PATH / Program Files."
                )
            selected_backend = "libreoffice"
        elif norm_renderer == "word_com":
            if not cls.is_word_com_available():
                raise AdapterUnavailableError(
                    "Selected renderer 'word_com' (Microsoft Word) is not available on this system."
                )
            selected_backend = "word_com"
        else:
            raise InvalidInputError(
                f"Unknown renderer option {renderer!r}. Expected 'auto', 'libreoffice', or 'word_com'."
            )

        timeout_sec = max(5, min(300, int(timeout)))

        if cancel_check and cancel_check():
            raise ConversionCancelledError("Conversion cancelled before backend process launch.")

        # 4. Execute rendering inside isolated sandboxed temp folder
        with tempfile.TemporaryDirectory(prefix="localshift_docx_render_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            sandbox_docx = tmp_dir / "document_input.docx"
            sandbox_pdf = tmp_dir / "document_input.pdf"

            # Copy source file to sandbox (never touch the user's source file)
            shutil.copyfile(source_docx, sandbox_docx)

            if selected_backend == "libreoffice":
                cls._execute_libreoffice(
                    sandbox_docx,
                    tmp_dir,
                    timeout=timeout_sec,
                    cancel_check=cancel_check,
                )
            elif selected_backend == "word_com":
                cls._execute_word_com(
                    sandbox_docx,
                    sandbox_pdf,
                    timeout=timeout_sec,
                    cancel_check=cancel_check,
                )

            if cancel_check and cancel_check():
                raise ConversionCancelledError("Conversion cancelled after rendering completed.")

            # 5. Verify produced PDF
            if not sandbox_pdf.is_file() or sandbox_pdf.stat().st_size == 0:
                raise ConversionFailedError(
                    f"Renderer {selected_backend!r} completed without producing a valid PDF output file."
                )

            # 6. Copy rendered output to final destination
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sandbox_pdf, output_pdf)

        return output_pdf

    @classmethod
    def _execute_libreoffice(
        cls,
        sandbox_docx: Path,
        out_dir: Path,
        *,
        timeout: int,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Execute headless LibreOffice conversion."""
        lo_bin = cls.find_libreoffice_binary()
        if not lo_bin:
            raise AdapterUnavailableError("LibreOffice binary not found.")

        # Create isolated LibreOffice user installation directory to prevent concurrent lockups
        user_profile_dir = out_dir / "lo_profile"
        user_profile_dir.mkdir(parents=True, exist_ok=True)
        user_install_arg = f"-env:UserInstallation={user_profile_dir.as_uri()}"

        cmd = [
            str(lo_bin),
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            user_install_arg,
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(out_dir),
            str(sandbox_docx),
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Wait with polling to support cooperative cancellation
            poll_interval = 0.2
            elapsed = 0.0
            while elapsed < timeout:
                if cancel_check and cancel_check():
                    proc.kill()
                    proc.wait()
                    raise ConversionCancelledError("Conversion cancelled during LibreOffice rendering.")
                ret = proc.poll()
                if ret is not None:
                    break
                import time
                time.sleep(poll_interval)
                elapsed += poll_interval

            if proc.poll() is None:
                proc.kill()
                proc.wait()
                raise ConversionFailedError(f"LibreOffice rendering timed out after {timeout} seconds.")

            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise ConversionFailedError(
                    f"LibreOffice conversion failed with exit code {proc.returncode}: {stderr or stdout}"
                )
        except (ConversionCancelledError, ConversionFailedError):
            raise
        except Exception as exc:
            raise ConversionFailedError(f"Failed to execute LibreOffice process: {exc}") from exc

    @classmethod
    def _execute_word_com(
        cls,
        sandbox_docx: Path,
        sandbox_pdf: Path,
        *,
        timeout: int,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Execute Microsoft Word COM automation via PowerShell."""
        script_content = (
            "$ErrorActionPreference = 'Stop'\n"
            f"$docx = '{str(sandbox_docx.resolve())}'\n"
            f"$pdf = '{str(sandbox_pdf.resolve())}'\n"
            "$w = New-Object -ComObject Word.Application\n"
            "$w.Visible = $false\n"
            "$w.DisplayAlerts = 0\n"
            "try {\n"
            "  $doc = $w.Documents.Open($docx, $false, $true)\n"
            "  $doc.SaveAs2($pdf, 17)\n"
            "  $doc.Close([ref]$false)\n"
            "} finally {\n"
            "  $w.Quit([ref]$false)\n"
            "  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($w) | Out-Null\n"
            "}\n"
        )

        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as ps_f:
            ps_f.write(script_content)
            ps_script_path = Path(ps_f.name)

        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps_script_path),
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            poll_interval = 0.2
            elapsed = 0.0
            while elapsed < timeout:
                if cancel_check and cancel_check():
                    proc.kill()
                    proc.wait()
                    raise ConversionCancelledError("Conversion cancelled during Word COM rendering.")
                ret = proc.poll()
                if ret is not None:
                    break
                import time
                time.sleep(poll_interval)
                elapsed += poll_interval

            if proc.poll() is None:
                proc.kill()
                proc.wait()
                raise ConversionFailedError(f"Microsoft Word COM rendering timed out after {timeout} seconds.")

            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                raise ConversionFailedError(
                    f"Microsoft Word COM conversion failed with exit code {proc.returncode}: {stderr or stdout}"
                )
        except (ConversionCancelledError, ConversionFailedError):
            raise
        except Exception as exc:
            raise ConversionFailedError(f"Failed to execute Word COM conversion: {exc}") from exc
        finally:
            if ps_script_path.is_file():
                try:
                    ps_script_path.unlink()
                except OSError:
                    pass
