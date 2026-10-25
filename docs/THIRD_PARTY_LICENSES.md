# LocalShift — Third-Party Licenses & Model Notices

LocalShift is open-source software licensed under the **MIT License**.

This document details the open-source software, third-party libraries, and machine-learning models bundled with the LocalShift desktop application and Windows installer distribution.

---

## 1. Summary of Bundled Components & Licenses

| Component | Project / Source | Version | License | Bundled Form |
|---|---|---|---|---|
| **Python** | Python Software Foundation | 3.14.3 | PSF-2.0 | Embedded runtime DLLs & standard library |
| **PySide6 / Qt 6** | The Qt Company / Shiboken | 6.12.0 | LGPL-3.0 | Dynamically linked DLLs & Python extension modules |
| **pypdfium2** | pypdfium2 Team / Google PDFium | 5.14.0 | Apache-2.0 / BSD-3 | Native `pdfium.dll` binary & Python wrapper |
| **RapidOCR** | RapidAI Team | 1.2.3 | Apache-2.0 | Python scripts & inference coordinator |
| **PP-OCRv3/v4 Models** | PaddleOCR / Baidu | PP-OCRv3 | Apache-2.0 | Bundled ONNX neural network model files |
| **ONNX Runtime** | Microsoft Corporation | 1.26.0 | MIT | Native `onnxruntime.dll` CPU execution engine |
| **Pillow** | Jeffrey A. Clark & contributors | 13.0.0 | HPND / MIT-style | Image processing DLLs & Python extension modules |
| **python-docx** | Steve Canny & contributors | 1.2.0 | MIT | Pure Python package & OpenXML document templates |
| **lxml** | lxml Team | 6.1.3 | BSD-3-Clause | C-extension XML parsing module |
| **OpenCV Headless** | OpenCV Team | 5.0.0 | Apache-2.0 | Computer vision image preprocessing module |
| **PyYAML** | Kirill Simonov & contributors | 6.0.3 | MIT | Configuration parser extension |
| **Inno Setup** | Jordan Russell / Martijn Laan | 6.7.3 | Permissive (BSD-style) | Windows installer setup bootloader |

---

## 2. Bundled Machine Learning Models (RapidOCR / PP-OCR)

LocalShift bundles three pre-trained neural network models for offline optical character recognition:
1. `ch_PP-OCRv3_det_infer.onnx` (Text Detection)
2. `ch_PP-OCRv3_rec_infer.onnx` (Text Recognition)
3. `ch_ppocr_mobile_v2.0_cls_infer.onnx` (Text Angle Classification)

**Origin:** PaddleOCR project (Baidu Inc.) via RapidOCR (RapidAI).  
**License:** Apache License, Version 2.0  
**Notice:**
```text
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

## 3. LGPLv3 Compliance Statement (PySide6 / Qt 6)

LocalShift uses **PySide6 (Qt 6 for Python)** under the GNU Lesser General Public License version 3 (LGPL-3.0).

In accordance with LGPL-3.0 Section 4(d):
1. **Dynamic Linking:** LocalShift dynamically links to PySide6 and Qt 6 shared libraries (`.dll`, `.pyd`). The application does not statically compile or incorporate modified Qt source code into proprietary binaries.
2. **Re-linking / Replacement:** Users may replace the bundled PySide6/Qt shared libraries in the `_internal/PySide6/` subfolder with their own custom-built or upgraded compatible versions.
3. **Source Code Availability:** The full source code of LocalShift is available at https://github.com/localshift/localshift under the MIT License.
4. **Qt Source Code:** Upstream Qt and PySide6 source code can be obtained at https://code.qt.io/cgit/pyside/pyside-setup.git.

---

## 4. Google PDFium / pypdfium2 Notice

LocalShift bundles `pdfium.dll` via `pypdfium2`.

**PDFium Copyright & License:**
```text
Copyright 2014 PDFium Authors. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
```

---

## 5. Inno Setup License Notice

The LocalShift Windows installer is compiled using Inno Setup 6.

```text
Inno Setup Copyright (C) 1997-2026 Jordan Russell. Portions Copyright (C) 2000-2026 Martijn Laan.
Inno Setup is free of charge for both commercial and non-commercial use.
```
