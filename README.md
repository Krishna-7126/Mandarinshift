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

- **Raster images**: Any different pair among `PNG`, `JPEG` (`jpg`), `WebP`, `BMP`, `TIFF` (`tif`).
- **Documents (LS-BE-006B)**: `PDF` → `TXT` via `PdfDocumentAdapter` (native text extraction).
  *(Note: OCR and PDF-to-DOCX are deferred to future milestones and not yet available).*

| Behaviour | Detail |
|-----------|--------|
| Source formats | `PNG`, `JPEG`/`JPG`, `WebP`, `BMP`, `TIFF`/`TIF`, `PDF` |
| Target formats | `PNG`, `JPEG`/`JPG`, `WebP`, `BMP`, `TIFF`/`TIF`, `TXT` |
| Extension aliases | `jpg` = `jpeg`, `tif` = `tiff` (accepted everywhere) |
| JPEG transparency | Transparent areas composited to white by default |
| PDF inspection | Page dimensions, rotation, encryption status, and text density classification |
| PDF extraction | Deterministic, page-by-page UTF-8 text extraction with configurable page separators |
| Animated input | First frame only used in MVP |
| Input size limit | 250 MiB maximum (page cap: 2,000 pages for PDF) |
| Output collision | Never overwrites; adds ` (2)`, ` (3)` suffix |
| Original files | Never modified |
| Format detection | Magic bytes preferred over file extension (`%PDF-` sniffing for PDF) |

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
│       ├── __init__.py   Public API surface
│       ├── formats.py    Format registry, normalisation, magic-byte detection
│       ├── converter.py  Core conversion engine (backend, no GUI dependency)
│       ├── jobs.py       Job queue, batch submission, lifecycle management (v0.2)
│       ├── cli.py        Command-line interface
│       └── gui.py        PySide6 desktop UI (frontend — optional dependency)
└── tests/
    ├── conftest.py       Shared pytest fixtures
    ├── test_converter.py Unit + integration + regression tests (62 tests)
    └── test_jobs.py      Job management tests (80 tests)
```

---

## Backend API

### Single-image conversion (v0.1 — unchanged)

```python
from localshift import convert_image, ConversionError, ConversionResult

output_path = convert_image("photo.png", "jpeg", output_dir="./out")
# Returns: Path to the written file.
# Raises: ConversionError on any anticipated failure.
```

### Job Queue API (v0.2)

#### Single job submission

```python
from pathlib import Path
from localshift import JobQueue, JobStatus

q = JobQueue()                                         # max_workers=2, max_pending=200
job = q.submit(Path("photo.png"), "jpeg", output_dir=Path("./out"))
# job.job_id — unique 32-char hex string
# job.source, job.target_format, job.submitted_at available immediately

q.shutdown(wait=True)                                  # wait for all workers to finish

result = q.get_result(job.job_id)
print(result.status)       # JobStatus.SUCCEEDED
print(result.output_path)  # Path to the written file
print(result.output_bytes) # Output file size in bytes
```

#### Context manager (recommended)

```python
from localshift import JobQueue, JobStatus

with JobQueue() as q:
    job = q.submit("photo.png", "webp")
# Shutdown is automatic on exit; all running workers finish before the block exits.
result = q.get_result(job.job_id)
```

#### Batch submission

```python
from localshift import JobQueue, JobStatus, BatchSubmission

items = [
    ("photo1.png", "jpeg"),
    ("photo2.png", "webp"),
    ("photo3.bmp", "tiff"),
]

with JobQueue(max_workers=4) as q:
    batch = q.submit_batch(items, output_dir="./converted")
    # batch.jobs     — ordered list of accepted ConversionJob descriptors
    # batch.rejected — list of (index, reason) for pre-submission failures

for job in batch.jobs:
    result = q.get_result(job.job_id)
    print(result.status, result.output_path)
```

#### Job status query

```python
status = q.get_status(job.job_id)    # JobStatus.PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED
result = q.get_result(job.job_id)    # None if not yet finished; JobResult when terminal
all_jobs = q.all_jobs()              # [(job_id, status), ...]
pending  = q.pending_count()         # int
```

#### Progress reporting

```python
from localshift import JobQueue, ProgressEvent, JobResult
from typing import Optional

def on_progress(job_id: str, event: ProgressEvent, result: Optional[JobResult]) -> None:
    print(f"[{job_id[:8]}] {event.value}")
    if result is not None:
        print(f"  → {result.status.name}: {result.output_path or result.error}")

with JobQueue(progress_callback=on_progress) as q:
    q.submit("photo.png", "webp")
```

**Events:** `queued`, `started`, `succeeded`, `failed`, `cancelled`.

Callback exceptions are caught and logged; they do **not** affect job state.

#### Error handling

```python
from localshift import JobQueue, JobStatus, QueueFullError, JobNotFoundError

try:
    job = q.submit("photo.png", "jpeg")
except ValueError:
    print("Unknown target format")         # caught at submission
except QueueFullError:
    print("Queue full — retry later")

result = q.get_result(job.job_id)
if result.status is JobStatus.FAILED:
    print(f"Conversion failed: {result.error}")

try:
    q.get_status("bad_id")
except JobNotFoundError:
    print("Job not found")
```

#### Cancellation

```python
# Cancel a PENDING job (returns True if successful):
cancelled = q.cancel(job.job_id)

# Cancel a RUNNING job (not interruptible — returns False):
cancelled = q.cancel(running_job.job_id)  # → False
# The running job will complete normally (SUCCEEDED or FAILED).

# Shutdown cancels all PENDING jobs before stopping:
q.shutdown(wait=True)
```

**Cancellation guarantees:**
- `PENDING` jobs: cancelled immediately; marked `CANCELLED`; never executed.
- `RUNNING` jobs: **not interruptible** (Pillow C extensions have no cooperative cancellation point). `cancel()` returns `False`. The job completes as `SUCCEEDED` or `FAILED`.
- A job is **never** marked `CANCELLED` after it has completed successfully.
- No partial output files are left from a cancelled pending job (it never ran).

#### Queue limits

| Parameter | Default | Notes |
|-----------|---------|-------|
| `max_workers` | 2 | Concurrent worker threads |
| `max_pending` | 200 | Max PENDING jobs before `QueueFullError` |

```python
q = JobQueue(max_workers=4, max_pending=500)
```

#### Shutdown semantics

```python
q.shutdown(wait=True)   # Wait for running workers; cancel all PENDING jobs
q.shutdown(wait=False)  # Cancel PENDING; do not wait for running workers
```

After `shutdown()`, new submissions raise `RuntimeError`.

---

---

## Adapter Architecture & Capability Registry (v0.4+)

LocalShift uses a modular adapter architecture to support extensible file conversions. Conversion engines are encapsulated as self-contained adapters conforming to the `ConversionAdapter` protocol, managed by a centralized, thread-safe `AdapterRegistry`.

### 1. The Adapter Protocol

```python
from localshift import ConversionAdapter, ConversionRequest, ConversionContext, ConversionResult

class MyCustomAdapter:
    adapter_id = "my_custom_adapter"
    name = "My Custom Format Adapter"

    @property
    def supported_source_formats(self) -> frozenset[str]:
        return frozenset({"csv"})

    @property
    def supported_target_formats(self) -> frozenset[str]:
        return frozenset({"json"})

    @property
    def supported_routes(self) -> frozenset[tuple[str, str]]:
        return frozenset([("csv", "json")])

    def can_convert(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self.supported_routes

    def convert(self, request: ConversionRequest, context: ConversionContext) -> ConversionResult:
        context.check_cancelled()
        # Read request.source, convert, and write directly to context.temp_output_path
        ...
        return ConversionResult(
            output_path=context.temp_output_path,
            source_format="csv",
            target_format="json",
            input_bytes=request.source.stat().st_size,
            output_bytes=context.temp_output_path.stat().st_size,
            adapter_id=self.adapter_id,
        )
```

### 2. Registration & Capability Discovery

```python
from localshift import default_registry, AdapterRegistry

# Query registered capabilities
routes = default_registry.supported_routes()
sources = default_registry.supported_source_formats()
targets = default_registry.supported_target_formats("png")  # frozenset({'jpeg', 'webp', 'bmp', 'tiff'})

# Register a new adapter
reg = AdapterRegistry()
reg.register(MyCustomAdapter())  # raises AdapterRegistrationError on duplicate ID or conflicting route
reg.register(MyCustomAdapter(), allow_override=True)  # overrides previous route
```

### 3. Conversion Request Lifecycle & Security Boundary

The core engine (`localshift.converter.convert_request`) owns all security boundaries:
1. **Source validation**: Verifies existence, guards against dangling symlinks, and enforces `max_input_bytes`.
2. **Format resolution**: Normalizes aliases (`jpg` → `jpeg`) and detects format via magic bytes.
3. **Route validation**: Checks the registry for an adapter supporting `(source, target)`.
4. **Output reservation**: Atomically reserves a collision-free destination name.
5. **Sandbox context**: Creates a secure temporary file (`.tmp`) and gives the adapter only `context.temp_output_path` to write to.
6. **Result verification**: Verifies that the temporary output exists and is non-empty before committing.
7. **Atomic commit**: Replaces the temporary file onto the reserved destination path via `os.replace`.
8. **Guaranteed cleanup**: Releases reservations and unlinks leftover temp files in `finally:`.

### 4. Error Taxonomy

All conversion exceptions inherit from `ConversionError` (subclass of `RuntimeError`), preserving 100% backward compatibility:

```
ConversionError (Base user-displayable error)
├── UnsupportedFormatError (Unknown format specifier; also inherits from ValueError)
├── UnsupportedConversionError (Route not supported by any registered adapter)
├── InvalidInputError (Input missing, not a regular file, or unreadable)
│   └── InputTooLargeError (Input exceeds size limit)
├── DestinationConflictError (Source and destination point to same file)
├── AdapterUnavailableError (Adapter registered but runtime missing)
├── ConversionCancelledError (Operation cancelled before or during processing)
└── ConversionFailedError (Underlying conversion execution failure)
```

### 5. Supported Routes & Built-in Raster Adapter

LocalShift includes `PillowImageAdapter` (`adapter_id: "pillow_raster"`), providing all 20 pairwise conversion routes between:
`PNG`, `JPEG` (and `jpg`), `WebP`, `BMP`, and `TIFF` (and `tif`).

Identity conversions (e.g. `png` → `png`) and unrecognised format pairs raise `UnsupportedConversionError`.

---

## Planning, Capability Discovery & Preflight Validation (v0.5+)

LocalShift provides an inspection and planning API to explain conversion viability, option schemas, and preflight readiness without executing conversions or modifying the filesystem.

### 1. Capability Discovery

Query supported formats and routes deterministically without accessing internal mutable state:

```python
from localshift import (
    get_supported_source_formats,
    get_supported_target_formats,
    get_supported_routes,
    is_route_supported,
    get_applicable_options,
    get_adapter_info,
)

# List sorted canonical formats
sources = get_supported_source_formats()              # ['bmp', 'jpeg', 'png', 'tiff', 'webp']
targets = get_supported_target_formats("png")         # ['bmp', 'jpeg', 'tiff', 'webp']

# Query route support (normalizes aliases automatically)
supported = is_route_supported("png", "jpg")         # True
supported_noop = is_route_supported("png", "png")    # False

# Inspect route options and adapter metadata
options = get_applicable_options("png", "jpeg")      # (OptionSpec(name='jpeg_background', ...),)
adapter = get_adapter_info("pillow_raster")
```

### 2. Conversion Planning (`plan_conversion` and `plan_route`)

Generate a structured `ConversionPlan` detailing route support, adapter selection, option schemas, and point-in-time readiness:

```python
from pathlib import Path
from localshift import plan_conversion, plan_route

# Plan with physical file (performs point-in-time preflight checks)
plan = plan_conversion(Path("photo.png"), "jpeg", output_dir="./out")
print(plan.source_format)             # 'png'
print(plan.target_format)             # 'jpeg'
print(plan.route_supported)           # True
print(plan.adapter_id)                # 'pillow_raster'
print(plan.available_target_formats)  # ('bmp', 'jpeg', 'tiff', 'webp')
print(plan.applicable_options)        # (OptionSpec(name='jpeg_background', ...),)
print(plan.is_ready)                  # True (ready for execution attempt)

# Plan route without physical file (format-level capability check)
route_plan = plan_route("png", "webp")
print(route_plan.route_supported)     # True
print(route_plan.is_ready)            # True
```

**Guarantees:**
- Planning NEVER executes conversions or submits jobs.
- Planning NEVER creates temporary or destination files.
- Planning NEVER acquires permanent destination reservations.
- Source files are never modified or decoded unnecessarily.

### 3. Preflight Validation (`validate_preflight`)

Perform point-in-time preflight checks on a `ConversionRequest`:

```python
from localshift import ConversionRequest, validate_preflight, FindingSeverity

req = ConversionRequest(source=Path("missing.png"), target_format="jpeg")
findings = validate_preflight(req)

for finding in findings:
    print(finding.code)              # e.g. "SOURCE_NOT_FOUND"
    print(finding.message)           # Human-readable explanation
    print(finding.severity)          # FindingSeverity.ERROR or FindingSeverity.WARNING
    print(finding.blocks_execution)  # True
```

#### Stable Finding Codes:
- `SOURCE_NOT_FOUND`: Input file does not exist.
- `SOURCE_NOT_A_FILE`: Input path is a directory or special device.
- `SOURCE_SYMLINK_BROKEN`: Symlink is dangling or cannot be resolved.
- `SOURCE_EMPTY`: Input file is 0 bytes.
- `SOURCE_TOO_LARGE`: Input file exceeds size limit (`MAX_INPUT_BYTES`).
- `SOURCE_FORMAT_UNKNOWN`: File content and extension could not be identified.
- `SOURCE_FORMAT_UNSUPPORTED`: Declared source format is not recognized.
- `TARGET_FORMAT_INVALID`: Target format specifier is unrecognised.
- `ROUTE_UNSUPPORTED`: No registered adapter supports the route.
- `SAME_FORMAT_NO_OP`: Source and target formats are identical.
- `DESTINATION_CONFLICT`: Output destination resolves to source file.
- `DESTINATION_DIR_INVALID`: Output destination exists and is not a directory.
- `UNKNOWN_OPTION`: Option supplied is not accepted by the route adapter.
- `INVALID_OPTION_VALUE`: Option value is malformed or out of range.
- `ADAPTER_UNAVAILABLE`: Registered adapter is missing or unavailable.

#### Planning vs. Execution Guarantees:
- Preflight findings represent a **point-in-time** assessment, not a guarantee of future conversion success (e.g. source files or disk permissions can change between check and execution).
- `convert_request()` re-validates all critical conditions at execution time and acquires an atomic output reservation. Client-supplied plan objects are never trusted as proof of validity.

---

## Backend independence

The backend (`converter`, `formats`, `cli`, `jobs`, `registry`, `adapters`) has **no dependency** on PySide6 or any
GUI toolkit. It can be imported and used in scripts, CLI tools, or a future
alternative frontend without initialising a display:

```python
from localshift import (
    convert_image,
    convert_request,
    ConversionRequest,
    ConversionError,
    JobQueue,
    default_registry,
)
from localshift.formats import SUPPORTED, route_supported, output_formats_for
```

---

## Dependencies

| Package | Purpose | License |
|---------|---------|---------
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

## Security and reliability notes
 
 - Files are never uploaded anywhere.
 - Originals are never modified.
 - Output is written atomically via temp-file + rename.
 - Format is detected by file content (magic bytes), not just extension.
 - Symlinks to regular files are accepted; dangling symlinks are rejected.
 - Queue is bounded: pending memory growth is bounded by `max_pending` (default 200).
 - Completed job registry is bounded: terminal job records are bounded by `max_completed` (default 1000) with FIFO eviction.
 - Output path reservation: process-level reservation lock and registry prevent concurrent workers or direct conversions from colliding on the same destination filename.
 - Temporary files and path reservations are reliably cleaned up on success, failure, or cancellation.
