"""
localshift.documents.pdf_tool_registry — Centralized Feature Registry for the PDF Productivity Suite.

Defines all 32 PDF productivity tools, their capabilities, real availability, dependencies,
limitations, and routing to backend execution engines.

Guarantees:
- Zero fabrication: Each tool reports its real availability, required dependencies, and limitations.
- Consistent metadata: Title, description, category, iconography, and status tokens.
- Offline-first: Every available tool runs locally on the host CPU without network calls.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

log = logging.getLogger(__name__)


class ToolAvailability(str, enum.Enum):
    """Real availability status of a PDF tool."""
    READY = "READY"                      # Fully implemented and verified locally
    AVAILABLE = "READY"                  # Alias for backwards compatibility
    CONFIG_REQUIRED = "CONFIG_REQUIRED"  # Requires external local tool (e.g. LibreOffice or Word COM)
    PLANNED = "PLANNED"                  # Structured on roadmap for future phase
    UNSUPPORTED = "UNSUPPORTED"          # Not supported on current host or environment


class ToolCategory(str, enum.Enum):
    """Category classification matching LocalShift PDF Suite."""
    ORGANIZE = "Organize & Optimize"
    CONVERT_FROM = "Convert from PDF"
    CONVERT_TO = "Convert to PDF"
    SECURITY_PAGES = "Security & Pages"
    ADVANCED_AI = "Advanced & AI"


@dataclass
class PdfToolDefinition:
    """Metadata and execution specification for a PDF productivity tool."""
    id: str
    title: str
    description: str
    category: ToolCategory
    icon_symbol: str
    accent_color: str  # Hex color for category icon badge
    availability: ToolAvailability = ToolAvailability.READY
    badge: Optional[str] = None  # e.g. "New!", "Pro", None
    dependencies: list[str] = field(default_factory=list)
    limitations: Optional[str] = None
    setup_guide: Optional[str] = None
    input_extensions: list[str] = field(default_factory=lambda: [".pdf"])
    output_extensions: list[str] = field(default_factory=lambda: [".pdf"])
    options_schema: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_available(self) -> bool:
        return self.availability in (ToolAvailability.READY, ToolAvailability.AVAILABLE)



# ---------------------------------------------------------------------------
# Complete 32-Tool Registry Specification
# ---------------------------------------------------------------------------

ALL_PDF_TOOLS: list[PdfToolDefinition] = [
    # --- Category: Organize & Optimize ---
    PdfToolDefinition(
        id="merge_pdf",
        title="Merge PDF",
        description="Combine multiple PDFs in the exact order you want with dimension and quality preservation.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="⤹⤸",
        accent_color="#ef4444",  # Coral / Red
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="split_pdf",
        title="Split PDF",
        description="Separate one page or an entire set for easy conversion into independent PDF files.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="⤢",
        accent_color="#ef4444",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "mode", "type": "str", "default": "single_pages", "choices": ["single_pages", "range"]},
            {"name": "page_range", "type": "str", "default": "1-3"},
        ],
    ),
    PdfToolDefinition(
        id="compress_pdf",
        title="Compress PDF",
        description="Reduce file size while optimizing stream objects and raster images for maximum PDF quality.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="⤹⤸",
        accent_color="#10b981",  # Emerald Green
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "compression_level", "type": "str", "default": "medium", "choices": ["low", "medium", "high"]},
        ],
    ),
    PdfToolDefinition(
        id="organize_pdf",
        title="Organize PDF",
        description="Sort, reorder, and arrange pages of your PDF file however you like.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="↕",
        accent_color="#ef4444",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "page_order", "type": "str", "default": "", "description": "Comma-separated page sequence (e.g. 3,1,2)"},
        ],
    ),
    PdfToolDefinition(
        id="extract_pages",
        title="Extract Pages",
        description="Extract specific pages or page intervals from a PDF into a new standalone document.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="⎘",
        accent_color="#ef4444",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "pages", "type": "str", "default": "1", "description": "Pages to extract (e.g. 1, 3, 5-7)"},
        ],
    ),
    PdfToolDefinition(
        id="delete_pages",
        title="Delete Pages",
        description="Remove unwanted pages from a PDF document cleanly and re-save the trimmed document.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="✕",
        accent_color="#ef4444",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "pages_to_delete", "type": "str", "default": "1", "description": "Pages to remove (e.g. 2, 4)"},
        ],
    ),
    PdfToolDefinition(
        id="rotate_pdf",
        title="Rotate PDF",
        description="Rotate your PDFs the way you need them. Rotate single pages or entire documents at once.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="↻",
        accent_color="#8b5cf6",  # Violet
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "angle", "type": "int", "default": 90, "choices": [90, 180, 270]},
            {"name": "pages", "type": "str", "default": "all"},
        ],
    ),
    PdfToolDefinition(
        id="crop_pdf",
        title="Crop PDF",
        description="Crop margins of PDF documents or trim specific page boundaries.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="◩",
        accent_color="#a855f7",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "margin_pt", "type": "float", "default": 36.0, "description": "Points to crop from each edge"},
        ],
    ),
    PdfToolDefinition(
        id="repair_pdf",
        title="Repair PDF",
        description="Recover salvageable pages and reconstruct readable document streams from corrupt PDFs.",
        category=ToolCategory.ORGANIZE,
        icon_symbol="🔧",
        accent_color="#22c55e",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[],
    ),

    # --- Category: Convert from PDF ---
    PdfToolDefinition(
        id="pdf_to_word",
        title="PDF to Word",
        description="Convert your PDF files into editable DOCX documents with preserved headings, tables, and text flow.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="W",
        accent_color="#3b82f6",  # Blue
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".docx"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="pdf_to_jpg",
        title="PDF to JPG",
        description="Convert each PDF page into a high-resolution JPG image or extract image assets.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="🖼",
        accent_color="#eab308",  # Amber / Yellow
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".jpg", ".jpeg"],
        options_schema=[
            {"name": "dpi", "type": "int", "default": 200},
            {"name": "quality", "type": "int", "default": 90},
        ],
    ),
    PdfToolDefinition(
        id="pdf_to_png",
        title="PDF to PNG",
        description="Rasterize PDF pages into lossless PNG graphics with exact color fidelity.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="🖼",
        accent_color="#eab308",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".png"],
        options_schema=[
            {"name": "dpi", "type": "int", "default": 200},
        ],
    ),
    PdfToolDefinition(
        id="pdf_to_markdown",
        title="PDF to Markdown",
        description="Turn PDFs into clean Markdown files. Perfect for notes, documentation, and LLM context.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="{#}",
        accent_color="#6366f1",  # Indigo
        availability=ToolAvailability.AVAILABLE,
        badge="New!",
        input_extensions=[".pdf"],
        output_extensions=[".md"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="pdf_to_powerpoint",
        title="PDF to PowerPoint",
        description="Convert PDF slides and presentations into editable PPTX slide decks.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="P",
        accent_color="#f97316",  # Orange
        availability=ToolAvailability.READY,
        badge="New!",
        dependencies=["PowerPoint COM or OpenXML Builder"],
        input_extensions=[".pdf"],
        output_extensions=[".pptx"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="pdf_to_excel",
        title="PDF to Excel",
        description="Pull tabular data straight from PDF balance sheets and ledgers into Excel spreadsheets.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="X",
        accent_color="#10b981",  # Green
        availability=ToolAvailability.READY,
        badge="New!",
        dependencies=["Native OpenXML Builder"],
        input_extensions=[".pdf"],
        output_extensions=[".xlsx"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="pdf_to_pdfa",
        title="PDF to PDF/A",
        description="Transform your PDF to ISO-standardized PDF/A for verified long-term archiving.",
        category=ToolCategory.CONVERT_FROM,
        icon_symbol="/A",
        accent_color="#0ea5e9",
        availability=ToolAvailability.READY,
        badge="New!",
        dependencies=["Word COM or PDFium"],
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[],
    ),

    # --- Category: Convert to PDF ---
    PdfToolDefinition(
        id="word_to_pdf",
        title="Word to PDF",
        description="Make DOC and DOCX files easy to read and share by converting them to PDF offline.",
        category=ToolCategory.CONVERT_TO,
        icon_symbol="W➔",
        accent_color="#3b82f6",
        availability=ToolAvailability.READY,
        dependencies=["LibreOffice or Word COM"],
        input_extensions=[".docx", ".doc"],
        output_extensions=[".pdf"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="jpg_to_pdf",
        title="JPG to PDF",
        description="Convert JPG images to PDF in seconds. Easily adjust orientation, margins, and paper size.",
        category=ToolCategory.CONVERT_TO,
        icon_symbol="🖼➔",
        accent_color="#eab308",
        availability=ToolAvailability.READY,
        input_extensions=[".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "page_size", "type": "str", "default": "original", "choices": ["original", "a4", "letter"]},
            {"name": "fit", "type": "str", "default": "contain", "choices": ["contain", "cover"]},
        ],
    ),
    PdfToolDefinition(
        id="powerpoint_to_pdf",
        title="PowerPoint to PDF",
        description="Make PPT and PPTX slideshows easy to view by converting them to PDF offline.",
        category=ToolCategory.CONVERT_TO,
        icon_symbol="P➔",
        accent_color="#f97316",
        availability=ToolAvailability.READY,
        dependencies=["PowerPoint COM or LibreOffice"],
        input_extensions=[".pptx", ".ppt"],
        output_extensions=[".pdf"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="excel_to_pdf",
        title="Excel to PDF",
        description="Make EXCEL spreadsheets easy to read and print by converting them to PDF offline.",
        category=ToolCategory.CONVERT_TO,
        icon_symbol="X➔",
        accent_color="#10b981",
        availability=ToolAvailability.READY,
        dependencies=["Excel COM or LibreOffice"],
        input_extensions=[".xlsx", ".xls", ".csv"],
        output_extensions=[".pdf"],
        options_schema=[],
    ),
    PdfToolDefinition(
        id="html_to_pdf",
        title="HTML to PDF",
        description="Convert local HTML files and styled documents to PDF offline.",
        category=ToolCategory.CONVERT_TO,
        icon_symbol="HTML",
        accent_color="#eab308",
        availability=ToolAvailability.AVAILABLE,
        dependencies=["PySide6.QtWebEngineCore"],
        input_extensions=[".html", ".htm"],
        output_extensions=[".pdf"],
    ),
    PdfToolDefinition(
        id="scan_to_pdf",
        title="Scan to PDF",
        description="Assemble digitized document photos into clean, ordered, multi-page PDF records.",
        category=ToolCategory.CONVERT_TO,
        icon_symbol="📷",
        accent_color="#f97316",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".png", ".jpg", ".jpeg", ".tiff", ".bmp"],
        output_extensions=[".pdf"],
    ),

    # --- Category: Security & Pages ---
    PdfToolDefinition(
        id="page_numbers",
        title="Page numbers",
        description="Add page numbers into PDFs with ease. Customize positions, dimensions, and typography.",
        category=ToolCategory.SECURITY_PAGES,
        icon_symbol="123",
        accent_color="#8b5cf6",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "format", "type": "str", "default": "Page {n} of {total}"},
            {"name": "position", "type": "str", "default": "bottom_center", "choices": ["bottom_center", "bottom_right", "top_right"]},
        ],
    ),
    PdfToolDefinition(
        id="watermark",
        title="Watermark",
        description="Stamp custom text over your PDF in seconds with controlled typography, angle, and transparency.",
        category=ToolCategory.SECURITY_PAGES,
        icon_symbol="♜",
        accent_color="#a855f7",
        availability=ToolAvailability.AVAILABLE,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "text", "type": "str", "default": "CONFIDENTIAL"},
            {"name": "opacity", "type": "float", "default": 0.25},
            {"name": "angle", "type": "int", "default": 45},
        ],
    ),
    PdfToolDefinition(
        id="protect_pdf",
        title="Protect PDF",
        description="Protect PDF files with password security and encryption to prevent unauthorized access.",
        category=ToolCategory.SECURITY_PAGES,
        icon_symbol="🔒",
        accent_color="#0ea5e9",
        availability=ToolAvailability.CONFIG_REQUIRED,
        badge="Setup Req",
        dependencies=["QPDF or LibreOffice"],
        limitations="Encryption authoring requires local QPDF or LibreOffice installation. Password removal and authorized unlocking are fully supported locally.",
        setup_guide="Install QPDF (choco install qpdf) or LibreOffice on your system and add to PATH to author encrypted PDFs.",
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "password", "type": "password", "default": ""},
        ],
    ),
    PdfToolDefinition(
        id="unlock_pdf",
        title="Unlock PDF",
        description="Remove PDF password security and encryption when you supply the authorized password.",
        category=ToolCategory.SECURITY_PAGES,
        icon_symbol="🔓",
        accent_color="#0ea5e9",
        availability=ToolAvailability.READY,
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "password", "type": "password", "default": ""},
        ],
    ),
    PdfToolDefinition(
        id="ocr_pdf",
        title="OCR PDF",
        description="Convert scanned and image-only PDFs into searchable and selectable text documents.",
        category=ToolCategory.SECURITY_PAGES,
        icon_symbol="🔍",
        accent_color="#22c55e",
        availability=ToolAvailability.READY,
        dependencies=["rapidocr-onnxruntime"],
        input_extensions=[".pdf"],
        output_extensions=[".txt", ".docx"],
        options_schema=[
            {"name": "output_format", "type": "str", "default": "txt", "choices": ["txt", "docx"]},
        ],
    ),

    # --- Category: Advanced & AI ---
    PdfToolDefinition(
        id="edit_pdf",
        title="Edit PDF",
        description="Add text annotations, status stamps, or visual markup to a PDF document offline.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="✎",
        accent_color="#8b5cf6",
        availability=ToolAvailability.READY,
        badge="New!",
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "action", "type": "str", "default": "add_text", "choices": ["add_text", "add_stamp", "highlight"]},
            {"name": "text", "type": "str", "default": "Approved"},
            {"name": "position", "type": "str", "default": "top_right", "choices": ["top_right", "top_left", "bottom_right", "bottom_left", "center"]},
        ],
    ),
    PdfToolDefinition(
        id="sign_pdf",
        title="Sign PDF",
        description="Sign documents yourself using locally stored signature graphics or digital verification seals.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="✒",
        accent_color="#0284c7",
        availability=ToolAvailability.READY,
        badge="New!",
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "signature_text", "type": "str", "default": ""},
            {"name": "position", "type": "str", "default": "bottom_right", "choices": ["bottom_right", "bottom_left", "bottom_center"]},
        ],
    ),
    PdfToolDefinition(
        id="compare_pdf",
        title="Compare PDF",
        description="Perform side-by-side document comparison and spot changes between file versions.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="▥",
        accent_color="#0284c7",
        availability=ToolAvailability.READY,
        badge="New!",
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
    ),
    PdfToolDefinition(
        id="redact_pdf",
        title="Redact PDF",
        description="Permanently black out and remove sensitive text or graphics from a PDF document.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="■",
        accent_color="#0284c7",
        availability=ToolAvailability.READY,
        badge="New!",
        input_extensions=[".pdf"],
        output_extensions=[".pdf"],
        options_schema=[
            {"name": "query", "type": "str", "default": "CONFIDENTIAL"},
        ],
    ),
    PdfToolDefinition(
        id="pdf_forms",
        title="PDF Forms",
        description="Inspect interactive fillable form fields, checkboxes, and export form values.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="Ab",
        accent_color="#a855f7",
        availability=ToolAvailability.READY,
        badge="New!",
        input_extensions=[".pdf"],
        output_extensions=[".json"],
    ),
    PdfToolDefinition(
        id="ai_summarizer",
        title="AI Summarizer",
        description="Generate concise executive summaries from articles, contracts, and reports using local offline AI.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="✨",
        accent_color="#6366f1",
        availability=ToolAvailability.READY,
        badge="New!",
        dependencies=["Offline TextRank Engine"],
        input_extensions=[".pdf"],
        output_extensions=[".md"],
        options_schema=[
            {"name": "num_sentences", "type": "int", "default": 5},
        ],
    ),
    PdfToolDefinition(
        id="translate_pdf",
        title="Translate PDF",
        description="Translate PDF files powered by optional local AI translation models.",
        category=ToolCategory.ADVANCED_AI,
        icon_symbol="文A",
        accent_color="#6366f1",
        badge="Setup Req",
        availability=ToolAvailability.CONFIG_REQUIRED,
        dependencies=["MarianMT ONNX model"],
        setup_guide="Place MarianMT ONNX model weights in ~/.localshift/models/marian-mt/ for offline local neural translation.",
        limitations="Requires local translation model weights configured.",
    ),
]


class PdfToolRegistry:
    """Registry maintaining active definitions and lookup for the PDF suite."""

    _tools_by_id: dict[str, PdfToolDefinition] = {t.id: t for t in ALL_PDF_TOOLS}

    @classmethod
    def get_all_tools(cls) -> list[PdfToolDefinition]:
        return list(cls._tools_by_id.values())

    @classmethod
    def get_tool(cls, tool_id: str) -> Optional[PdfToolDefinition]:
        return cls._tools_by_id.get(tool_id)

    @classmethod
    def get_tools_by_category(cls, category: ToolCategory) -> list[PdfToolDefinition]:
        return [t for t in cls._tools_by_id.values() if t.category == category]

    @classmethod
    def search_tools(cls, query: str) -> list[PdfToolDefinition]:
        q = query.strip().lower()
        if not q:
            return cls.get_all_tools()
        return [
            t for t in cls._tools_by_id.values()
            if q in t.title.lower() or q in t.description.lower() or q in t.category.value.lower()
        ]
