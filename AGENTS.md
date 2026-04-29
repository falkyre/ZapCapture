# ZapCapture-NG — Agent Instructions

## Setup & Commands

```bash
uv sync                          # install all deps (desktop + web extras)
uv sync --extra desktop          # desktop only
uv sync --extra web              # web only

python gui_desktop.py            # launch desktop app
python gui_web.py                # launch web app (localhost:8080)

docker build -t zapcapture .     # build Docker image for web
```

Dependencies managed by `uv` (not pip). No virtualenv — use `uv run` or activate `.venv`.

## Architecture

Three files, zero packages. No `zapcapture/` package directory despite README showing one:

```
core.py           — UI-agnostic detection engine (ZapCore class). Shared by both GUIs.
gui_desktop.py    — PySide6 native app entrypoint
gui_web.py        — NiceGUI web app entrypoint (Docker target)
```

Both GUIs import `from core import ZapCore, get_available_fonts`. The engine instance is created once per GUI process.

## Critical Bugs in core.py (do not introduce similar patterns)

- `gif_name_to_save` and `mp4frames_to_save` are referenced in the mid-stream finalize block (line ~352) before being assigned on first strike — causes `UnboundLocalError`. Must initialize to `None`/`[]` before the frame loop.
- `mp4name_to_save` has the same issue — checked in condition on line ~359 before assignment.
- `csv_file = open(...)` at line 314 is not context-managed; leaks on exception.
- Engine state (`progress`, `queue_status`, etc.) is mutated in a worker thread (desktop) / async task (web) without synchronization — race condition with GUI reads.
- Bare `except: pass` on GIF export (line ~357) swallows all errors.

## Key Engine Details

- `ZapCore` defaults: `scale=0.5`, `noise_cutoff=5` (hardcoded, not exposed to UI), `buffer_frames=5`, `export_format='gif'`
- Canny thresholds (100, 200) are hardcoded in `_count_diff()` — not configurable
- GIF/MP4 export FPS is hardcoded to 10
- Preview `get_annotated_preview_frame()` replaces `self.frame0` on every call, so "Diff:" values are meaningless after seeking
- Mask coordinates in `set_mask()` accept any values without bounds validation

## File Conventions

- No tests, no lint/typecheck config, no CI
- `assets/USER_GUIDE.md` — loaded by both GUIs into help tabs
- `assets/fonts/` — watermark fonts (`.ttf`, `.otf`)
- Output dirs: `frames/`, `gifs/`, `mp4s/` created by gallery save
- Temp dir prefix: `zapcapture_` (created via `tempfile.mkdtemp()`)
- `.gitignore` ignores: `.DS_Store`, `.kilo`, `__pycache__`, `.venv`, `pyproject.toml.ori`

## Development Guidelines & Rules

### 1. Versioning (Modified CalVer)
* We follow a date-based versioning scheme, but you must **strictly preserve leading zeros** in the tags (e.g., `2026.02.0`).
* **Do NOT** apply standard CalVer normalization that strips leading zeros. Always use raw tags for version checks and bumps.

### 2. Logging
* All new modules and functions must implement structured logging.
* Use the `rich` library (or `richcolorlog`) for terminal output. 
* Do not use standard `print()` statements for application state or debugging. Ensure log levels (INFO, DEBUG, WARNING, ERROR) are used appropriately.

### 3. Error Handling & Exceptions
* **Separation of Concerns:** Never expose raw stack traces to the end-user during normal operation. 
* **Graceful Degradation:** Catch expected errors (e.g., missing configuration files, network timeouts, invalid inputs) and output a clean, human-readable, friendly error message to the console using `rich`. Provide actionable advice to the user if possible (e.g., "Check your network connection and try again").
* **Developer Troubleshooting:** When an error is caught, log the full exception, stack trace, and relevant local variables using the structured logger at the `DEBUG` or `ERROR` level. Use `rich.traceback` or `Console.print_exception()` to format the internal logs clearly.
* **Custom Exception Classes:** Do not rely on broad `except Exception:` blocks unless absolutely necessary for a top-level crash handler. Create custom domain-specific exceptions (e.g., `ConfigError`, `ConnectionTimeout`) to handle distinct failure states gracefully.
* **Verbose Mode:** Ensure all CLI tools or scripts respect a `--verbose` or `--debug` flag. When active, this flag should elevate the console output to include the developer-level logs and tracebacks.

### 4. Log Output & File Rotation
* **Dual-Output Logging:** All loggers must be configured with at least two handlers.
* **Console Handler:** Use `rich.logging.RichHandler` (or `richcolorlog`) for all terminal output. This output should be clean, colorized, and optimized for immediate user readability. 
* **File Handler:** Implement `logging.handlers.RotatingFileHandler` to write logs to a file. 
* **Rotation Rules:** Default to a maximum file size of 5MB per log file, keeping the last 3 to 5 backup files (`backupCount=3`).
* **File Format:** Ensure the file logs include precise timestamps, module names, line numbers, and the raw exception tracebacks, explicitly stripping any ANSI color codes so the file remains easily searchable.
* **Directory Structure:** Store log files in a dedicated `logs/` directory at the project root, and ensure this directory is added to `.gitignore`.