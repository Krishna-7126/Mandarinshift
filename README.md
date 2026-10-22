# LocalShift

**Free, offline-first Windows file converter. MVP supports raster images: PNG, JPEG, WebP, BMP, TIFF.**

---

## Setup (PowerShell)

> **Note:** PyPI connectivity may be required to install dependencies.
> If `pip install` times out on pypi.org, use the Aliyun mirror (see below).

### Standard setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]" --no-build-isolation
.\.venv\Scripts\python.exe -m pytest
```

### If PyPI is unreachable (use mirror)

```powershell
python -m pip install -e ".[test]" --no-build-isolation `
    -i https://mirrors.aliyun.com/pypi/simple/ `
    --trusted-host mirrors.aliyun.com
```

### Running tests without editable install

```powershell
$env:PYTHONPATH = "src"
py -m pytest tests/ -v
```

### GUI (requires PySide6)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
python -m localshift.gui
```

### CLI

```powershell
localshift convert .\photo.png --to webp --output-dir .\converted
localshift convert .\photo.png --to jpg           # alias accepted
localshift --verbose convert .\photo.png --to bmp  # debug logging
```

---

## Supported conversions

Any **different** pair among: `PNG`, `JPEG` (`jpg`), `WebP`, `BMP`, `TIFF` (`tif`).

| Behaviour | Detail |
|-----------|--------|
| Source formats | `PNG`, `JPEG`/`JPG`, `WebP`, `BMP`, `TIFF`/`TIF` |
| Extension aliases | `jpg` = `jpeg`, `tif` = `tiff` (accepted everywhere) |
| JPEG transparency | Transparent areas composited to white by default |
| Animated input | First frame only used in MVP |
| Input size limit | 250 MiB maximum |
| Output collision | Never overwrites; adds ` (2)`, ` (3)` suffix |
| Original files | Never modified |
| Format detection | Magic bytes preferred over file extension |

---

## Project structure

```text
LocalShift/
├── .gitattributes
├── .gitignore
├── LICENSE               MIT
├── README.md
├── pyproject.toml
├── src/
│   └── localshift/
│       ├── __init__.py   Public API surface (convert_image, ConversionError, ConversionResult)
│       ├── formats.py    Format registry, normalisation, magic-byte detection
│       ├── converter.py  Core conversion engine (backend, no GUI dependency)
│       ├── cli.py        Command-line interface
│       └── gui.py        PySide6 desktop UI (frontend — optional dependency)
└── tests/
    ├── conftest.py       Shared pytest fixtures
    └── test_converter.py Unit + integration + regression tests (60 tests)
```

---

## Backend independence

The backend (`converter`, `formats`, `cli`) has **no dependency** on PySide6 or any
GUI toolkit. It can be imported and used in scripts, CLI tools, or a future
alternative frontend without initialising a display:

```python
from localshift import convert_image, ConversionError
from localshift.formats import SUPPORTED, route_supported, output_formats_for
```

---

## Dependencies

| Package | Purpose | License |
|---------|---------|---------|
| `Pillow>=10.0,<14` | Image decoding/encoding | PIL/HPND |
| `PySide6>=6.7` | Desktop GUI (optional) | LGPL-3 |
| `pytest>=8.0` | Testing (dev only) | MIT |

> PySide6 is LGPL-3 licensed. Review its terms and THIRD_PARTY_NOTICES before
> redistribution. Install dependencies while online; after installation, all
> core conversions work fully offline.

---

## Not yet implemented

SVG, PDF, Office documents, archives, audio, video, and hardened sandboxing are
not implemented. See project roadmap for planned format families.

---

## Security notes

- Files are never uploaded anywhere.
- Originals are never modified.
- Output is written atomically via temp-file + rename.
- Format is detected by file content (magic bytes), not just extension.
- Symlinks to regular files are accepted; dangling symlinks are rejected.
