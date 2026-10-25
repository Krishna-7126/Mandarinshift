# LocalShift — LS-BE-016 Work Report
# Final Release & GitHub Publication Readiness

**Milestone:** LS-BE-016  
**Date:** October 26, 2026  
**Status:** Complete & Publication Ready  
**Evaluator:** Senior Release QA Engineer, Windows Compatibility Engineer, and Security Reviewer  
**Final Test Suite:** 566 tests collected (563 passed, 3 skipped on non-admin Windows, 0 failed)  
**Release Artifacts:**
- Windows Setup Installer: `dist/installer/LocalShift-Setup-0.14.0.exe` (93.34 MB, SHA-256: `13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974`)
- Portable Standalone Bundle: `dist/LocalShift-v0.14.0-windows-x64.zip` (146.26 MB, SHA-256: `de04a9b9f5000a05324760a2355703a06f4f50a15a8070ced464d92a630412d2`)

---

## 1. Executive Summary

Milestone **LS-BE-016** performed the final pre-publication audit, licensing review, release documentation preparation, and artifact manifest generation for **LocalShift v0.14.0**.

Every component required for public release has been completed and verified:
- **Version Synchronization:** Synchronized `0.14.0` across `pyproject.toml`, `src/localshift/__init__.py`, `packaging/version_info.txt`, `packaging/localshift.iss`, and all documentation.
- **Third-Party Licensing Audit:** Created [`docs/THIRD_PARTY_LICENSES.md`](file:///Z:/LocalShift/docs/THIRD_PARTY_LICENSES.md) documenting open-source licenses for all bundled runtimes, dynamic libraries, and pre-trained neural network models (PP-OCRv3/v4), with full LGPLv3 dynamic linking disclosures.
- **Release Artifact Generation:** Compiled and verified both the standard Windows Inno Setup 6 installer (`LocalShift-Setup-0.14.0.exe`) and the standalone zero-install portable zip archive (`LocalShift-v0.14.0-windows-x64.zip`).
- **Release Manifest & GitHub Notes:** Prepared official release notes at [`docs/GITHUB_RELEASE_v0.14.0.md`](file:///Z:/LocalShift/docs/GITHUB_RELEASE_v0.14.0.md) and artifact manifest at [`docs/RELEASE_MANIFEST.md`](file:///Z:/LocalShift/docs/RELEASE_MANIFEST.md).
- **Git State:** All modifications are verified and maintained uncommitted in the local working tree. No Git commits, tags, or GitHub releases have been pushed, pending explicit user authorization.

---

## 2. Licensing, Model Notices & Compliance Audit

### 2.1 License Verification
Every runtime dependency and bundled artifact was audited for compatibility with LocalShift's permissive MIT release:
- **LocalShift Core:** MIT License.
- **PySide6 / Qt 6 (Shiboken6):** LGPL-3.0. Compliant via standard dynamic linking (`.dll`, `.pyd`) without static binary modification. Relinking is supported by replacing files in `_internal/PySide6/`.
- **pypdfium2 / Google PDFium:** Apache-2.0 / BSD-3-Clause. Attributions included in third-party notices.
- **RapidOCR & PP-OCR Models:** Apache-2.0. Neural weights (`ch_PP-OCRv3_det_infer.onnx`, `ch_PP-OCRv3_rec_infer.onnx`, `ch_ppocr_mobile_v2.0_cls_infer.onnx`) derived from PaddleOCR are commercially permissive under Apache-2.0.
- **ONNX Runtime:** MIT License.
- **Pillow:** HPND (Historical Permission Notice and Disclaimer) / MIT-like.
- **python-docx & PyYAML:** MIT License.
- **lxml:** BSD-3-Clause.
- **OpenCV Headless:** Apache-2.0.
- **Inno Setup:** Permissive modified BSD-style installer bootloader license.

*Outcome: Zero copyleft (GPL) dependencies exist in the distribution. Full notices compiled in [`docs/THIRD_PARTY_LICENSES.md`](file:///Z:/LocalShift/docs/THIRD_PARTY_LICENSES.md).*

---

## 3. Versioning & Defect Fixes

1. **Version Synchronization Defect:**
   - Prior to this milestone, `pyproject.toml` and `src/localshift/__init__.py` remained at `0.5.0` from early planning milestones.
   - Synchronized `__version__ = "0.14.0"` in `src/localshift/__init__.py` and `version = "0.14.0"` in `pyproject.toml`.
   - Added automated test assertion in `tests/test_packaging.py::test_version_info_metadata`.

---

## 4. Release Artifacts & Checksums

Both distribution channels were verified and hashed:

```text
========================================================================================
LOCALSHIFT v0.14.0 RELEASE ARTIFACTS
========================================================================================
1. Windows Setup Installer:
   File: dist/installer/LocalShift-Setup-0.14.0.exe
   Size: 97,875,968 bytes (93.34 MB)
   SHA-256: 13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974

2. Portable Standalone Archive:
   File: dist/LocalShift-v0.14.0-windows-x64.zip
   Size: 153,360,020 bytes (146.26 MB)
   SHA-256: de04a9b9f5000a05324760a2355703a06f4f50a15a8070ced464d92a630412d2
========================================================================================
```

---

## 5. Quality Gate Final Review

The 37-point Release Quality Gate ([`docs/RELEASE_CHECKLIST.md`](file:///Z:/LocalShift/docs/RELEASE_CHECKLIST.md)) was evaluated:
- **36 PASS / 0 FAIL / 1 NOT VERIFIED**.
- All critical conversion paths (image-to-image, image-to-PDF, PDF-to-image rasterization, PDF-to-DOCX, DOCX-to-PDF, and PDF Workbench operations) pass automated regression and real executable testing.
- Offline OCR neural inference verified through both packaged CLI and installed setup builds.
- Silent enterprise installation and clean uninstallation verified.
- The single unverified item is clean-machine domain VM testing, disclosed honestly due to lack of separate domain infrastructure on this host.

---

## 6. Publication Procedure (Awaiting Approval)

Once approved to publish, run the following sequence:

```powershell
# Step 1: Review uncommitted changes
git status

# Step 2: Stage and commit all release files
git add .
git commit -m "chore(release): release LocalShift v0.14.0"

# Step 3: Create annotated tag
git tag -a v0.14.0 -m "LocalShift v0.14.0 — Offline-First Windows File Converter & Document Workbench"

# Step 4: Push commit and tag to GitHub
git push origin main --tags

# Step 5: Publish GitHub Release with binaries attached
gh release create v0.14.0 `
    .\dist\installer\LocalShift-Setup-0.14.0.exe `
    .\dist\LocalShift-v0.14.0-windows-x64.zip `
    --title "LocalShift v0.14.0 — Offline Windows File Converter" `
    --notes-file docs/GITHUB_RELEASE_v0.14.0.md
```
