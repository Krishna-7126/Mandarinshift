# LocalShift v0.14.0 — Release Artifact Manifest

**Release Version:** `v0.14.0`  
**Release Date:** October 26, 2026  
**Build Platform:** Windows 11 Version 10.0.26200 (AMD64)  
**Compiler / Toolchain:** Python 3.14.3, PyInstaller 6.22.3, Inno Setup 6.7.3 (ISCC.exe)  
**License:** MIT License (with LGPL-3.0 and Apache-2.0 third-party dynamic libraries)  

---

## 1. Official Release Binaries

| Artifact Name | Type | Size (Bytes) | Size (MB) | SHA-256 Checksum |
|---|---|---|---|---|
| **`LocalShift-Setup-0.14.0.exe`** | Windows Inno Setup Installer | `97,875,968` | 93.34 MB | `13469bf14d85e1d4d33a616b8b477c7654a5286449eeb25063c74fecdca92974` |
| **`LocalShift-v0.14.0-windows-x64.zip`** | Portable Standalone Bundle | `153,360,020` | 146.26 MB | `de04a9b9f5000a05324760a2355703a06f4f50a15a8070ced464d92a630412d2` |

---

## 2. Integrity Verification Commands

### PowerShell
```powershell
Get-FileHash -Algorithm SHA256 .\dist\installer\LocalShift-Setup-0.14.0.exe
Get-FileHash -Algorithm SHA256 .\dist\LocalShift-v0.14.0-windows-x64.zip
```

### Windows Command Prompt (certutil)
```cmd
certutil -hashfile dist\installer\LocalShift-Setup-0.14.0.exe SHA256
certutil -hashfile dist\LocalShift-v0.14.0-windows-x64.zip SHA256
```

---

## 3. Deployment Instructions

### Windows Installer (`LocalShift-Setup-0.14.0.exe`)
- Installs to `{autopf}\LocalShift` (defaults to `%LOCALAPPDATA%\Programs\LocalShift` for non-admin users, or `C:\Program Files\LocalShift` with UAC elevation).
- Creates Start Menu shortcuts for **LocalShift** and **LocalShift CLI**.
- Installs clean uninstaller `unins000.exe` registered in Windows Settings / Add or Remove Programs.
- **Silent Install:** `.\LocalShift-Setup-0.14.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
- **Silent Uninstall:** `"${env:ProgramFiles}\LocalShift\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`

### Portable Bundle (`LocalShift-v0.14.0-windows-x64.zip`)
- Extract to any folder or USB flash drive.
- Double-click `LocalShift.exe` for the GUI.
- Run `localshift-cli.exe` from PowerShell or Command Prompt for batch processing.
- Zero footprint on the host registry or system directories.

---

## 4. Git Tagging & GitHub Release Publication Guide

When approved to publish, execute the following commands:

```powershell
# 1. Verify working tree status
git status

# 2. Stage and commit release changes
git add .
git commit -m "chore(release): prepare LocalShift v0.14.0 release"

# 3. Create annotated signed or release tag
git tag -a v0.14.0 -m "LocalShift v0.14.0 — Offline-First Windows File Converter & Document Workbench"

# 4. Push branch and tags to GitHub (REQUIRES APPROVAL)
# git push origin main --tags

# 5. Create GitHub Release via GitHub CLI (gh) with binaries attached
# gh release create v0.14.0 .\dist\installer\LocalShift-Setup-0.14.0.exe .\dist\LocalShift-v0.14.0-windows-x64.zip --title "LocalShift v0.14.0 — Offline Windows File Converter" --notes-file docs/GITHUB_RELEASE_v0.14.0.md
```
