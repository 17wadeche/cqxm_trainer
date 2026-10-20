# Windows installation without Python

For Windows 10/11 x64, distribute **GCH-Check-My-Work-Windows-x64.zip** from the
successful **Build Windows package** workflow. The ZIP includes the Python runtime,
dependencies, application, procedures, and Chrome extension. Users need neither
Python nor pip, and installation does not download packages or require administrator
rights. Corporate application and extension policies still apply.

1. Extract **all** files into a permanent folder writable by the Windows user.
   Keep `GCH-Helper.exe` and the entire `_internal` folder together.
2. Run **Install-Windows.cmd**. **Start-Windows.cmd** performs the same one-time
   registration. Chrome starts the background helper when needed.
3. Load/reload the `extension` folder in Chrome using the approved deployment process,
   then refresh GCH. The existing extension ID is preserved.
4. Enter the Production API token in the extension when prompted. Network access
   to MDT-GPT and a permitted Chrome extension remain necessary for live reviews.

Do not distribute `.venv`, `native-launch.cmd`, or a generated
`com.gch.check_my_work.json` from another computer. Virtual environments contain
machine-specific Python references and are not portable. Do not distribute GitHub's
**Source code** ZIP to end users; it does not contain the built executable.

For upgrades, close Chrome, replace the files in the existing application folder
with the complete new package, run the installer, and reload the extension. If the
folder moves, rerun installation from the new location. Installation refreshes the
per-user registration without deleting stored tokens, source history, or reports in
`%LOCALAPPDATA%\GCHCheckMyWork`.

## Build and verify (maintainers only)

Run the **Build Windows package** GitHub Actions workflow. It also runs for pushes
to `main`, `v*` tags, and relevant pull requests. Download its artifact, then distribute the release
ZIP inside it. The workflow does not publish a GitHub release automatically.

Or build on Windows x64 with 64-bit Python 3.12:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt PyInstaller==6.16.0
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python build_windows.py
```

Outputs are in `dist`. The build runs the packaged `--self-test`, exercising native
messaging in a child process, bundled data, SQLite full-text search, DOCX extraction,
and synthetic Word generation. CI additionally extracts the ZIP into a different
folder with spaces and special characters, removes Python from PATH, installs the
native host, verifies its registry entry, and exercises both CMD launchers.
Validate Chrome end to end on an approved target workstation before rollout.

The executable is unsigned. If company policy requires signed software, IT must
sign and approve the package before distribution; do not disable security controls.
Legacy Office attachments still require LibreOffice or conversion to supported files.

Known separate data defect: the bundled `054-WI198.json` extracted-text digest does
not match its content. Integrity validation rejects it; packaging tests report the
warning. Supply an approved replacement through Documents & settings before live
reviews, or correct the procedure index in a separate change. Packaging does not
override integrity checks or establish live review readiness.

Developers running from source can still install `requirements.txt` in a local
virtual environment and run `python install_native.py` on Windows. The user-facing
CMD launchers intentionally require the portable release.