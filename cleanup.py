"""
System Health Monitor
==================
Module 5: cleanup.py
Responsibility: The cleanup engine - scans target locations, calculates
                real sizes, deletes files safely, and reports results.

How it's used:
    from cleanup import CleanupEngine, CleanupResult
    engine = CleanupEngine(log_callback=print)
    result = engine.run(targets=["trash", "caches", "logs", "downloads"])

Design principles:
    - Never deletes anything without scanning first
    - Every deletion is logged via log_callback
    - Errors are caught per-file - one bad file never stops the run
    - Downloads folder: only files older than DOWNLOADS_AGE_DAYS are removed
    - Runs in a background thread so the UI stays responsive
    - Returns a CleanupResult with full stats
"""

import os
import sys
import platform
import shutil
import threading
import datetime
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from app_config import PATHS, CONSTANTS, _platform_cache_root, _platform_log_root, _platform_trash, _platform_downloads
from utils import bytes_to_human as _bytes_to_human  # canonical; avoids renaming every call-site

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

_SYSTEM = platform.system()   # "Darwin", "Windows", or "Linux"

# Only delete Downloads files older than this many days
DOWNLOADS_AGE_DAYS = CONSTANTS.DOWNLOADS_AGE_DAYS

# Cache subdirectory names — platform-specific (from app_config)
CACHE_SUBDIRS = CONSTANTS.CACHE_SUBDIRS

# Log subdirectories — platform-specific
if _SYSTEM == "Darwin":
    LOG_SUBDIRS = ["DiagnosticReports", "CrashReporter"]
elif _SYSTEM == "Windows":
    LOG_SUBDIRS = ["CrashDumps"]
else:
    # Linux: target common crash/error log dirs under the log root
    LOG_SUBDIRS = ["crash", "errors"]

# How old a log file must be before we delete it (days)
LOG_AGE_DAYS = CONSTANTS.LOG_AGE_DAYS


# ─────────────────────────────────────────────
# CleanupResult  - returned after a run
# ─────────────────────────────────────────────
class CleanupResult:
    """
    Holds the outcome of a cleanup run.

    Attributes
    ----------
    started_at   : datetime when the run began
    finished_at  : datetime when it ended (None if still running)
    freed_bytes  : total bytes successfully deleted
    deleted_files: list of file paths that were removed
    errors       : list of (path, error_message) tuples
    skipped      : list of paths skipped (e.g. too new, unreadable)
    targets_run  : list of target names that were executed
    """

    def __init__(self):
        self.started_at    = datetime.datetime.now()
        self.finished_at   = None
        self.freed_bytes   = 0
        self.deleted_files = []
        self.errors        = []
        self.skipped       = []
        self.targets_run   = []

    def finish(self):
        self.finished_at = datetime.datetime.now()

    def duration_str(self) -> str:
        if not self.finished_at:
            return "In progress"
        delta = self.finished_at - self.started_at
        secs  = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"

    def freed_str(self) -> str:
        return _bytes_to_human(self.freed_bytes)

    def summary(self) -> str:
        return (
            f"Freed {self.freed_str()} · "
            f"{len(self.deleted_files)} files deleted · "
            f"{len(self.errors)} errors · "
            f"{self.duration_str()}"
        )

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict for history storage."""
        return {
            "started_at":    self.started_at.isoformat(),
            "finished_at":   self.finished_at.isoformat() if self.finished_at else None,
            "freed_bytes":   self.freed_bytes,
            "freed_str":     self.freed_str(),
            "deleted_count": len(self.deleted_files),
            "error_count":   len(self.errors),
            "targets_run":   self.targets_run,
            "summary":       self.summary(),
        }


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _dir_size(path: Path) -> int:
    """Return total size in bytes of all files under path."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file() and not entry.is_symlink():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except (OSError, PermissionError):
        pass
    return total


def _file_age_days(path: Path) -> float:
    """Return how many days ago the file was last modified."""
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) / 86400
    except OSError:
        return 0.0


def _win_recycle_bin_size() -> int:
    """
    Return the total size in bytes of the current user's Recycle Bin.
    Uses PowerShell Shell.Application COM object (Namespace 10 = Recycle Bin).
    Returns 0 if PowerShell is unavailable or the bin is empty.
    Only called on Windows.
    """
    script = (
        "$shell = New-Object -ComObject Shell.Application; "
        "$bin = $shell.Namespace(10); "
        "$items = $bin.Items(); "
        "if ($items.Count -eq 0) { Write-Output 0; exit 0 } "
        "$size = ($items | ForEach-Object { $_.ExtendedProperty('Size') } "
        "| Measure-Object -Sum).Sum; "
        "if ($size -eq $null) { Write-Output 0 } else { Write-Output $size }"
    )
    try:
        proc = subprocess.run(
            ["PowerShell", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=15
        )
        output = proc.stdout.decode(errors="replace").strip()
        return int(output) if output.isdigit() else 0
    except Exception:
        return 0


# ─────────────────────────────────────────────
# ScanResult  - pre-cleanup analysis
# ─────────────────────────────────────────────
class ScanResult:
    """
    Result of a pre-cleanup scan.
    Tells the notifier what WILL be cleaned and how much space.
    """

    def __init__(self):
        self.targets: dict[str, int] = {}   # target_name > bytes

    def add(self, target: str, size_bytes: int):
        self.targets[target] = size_bytes

    def total_bytes(self) -> int:
        return sum(self.targets.values())

    def total_mb(self) -> int:
        return int(self.total_bytes() / (1024 ** 2))

    def target_labels(self) -> list:
        """Human-readable list for the notifier UI."""
        label_map = {
            "trash":     "Trash",
            "caches":    "User caches",
            "logs":      "Old log files",
            "downloads": f"Downloads (files > {DOWNLOADS_AGE_DAYS} days old)",
        }
        result = []
        for key, size in self.targets.items():
            label = label_map.get(key, key.title())
            if size > 0:
                result.append(f"{label}  ({_bytes_to_human(size)})")
            else:
                result.append(label)
        return result


# ─────────────────────────────────────────────
# CleanupEngine  - the core engine
# ─────────────────────────────────────────────
class CleanupEngine:
    """
    Scans and cleans target locations on macOS.

    Parameters
    ----------
    log_callback : callable(str) - receives log lines during the run.
                   Called from the background thread; if updating Tkinter
                   widgets, use root.after() or a thread-safe queue.
    dry_run      : if True, scan and log but do NOT delete anything.
                   Useful for testing and previewing.
    """

    def __init__(self,
                 log_callback: Optional[Callable[[str], None]] = None,
                 dry_run: bool = False):
        self.log_callback = log_callback or (lambda msg: None)
        self.dry_run      = dry_run
        self._abort       = threading.Event()

    # ── public API ─────────────────────────────
    def scan(self, targets: list) -> ScanResult:
        """
        Quickly estimate how much space each target occupies.
        Does NOT delete anything. Returns a ScanResult.
        """
        result = ScanResult()
        for target in targets:
            size = self._measure(target)
            result.add(target, size)
        return result

    def run(self, targets: list,
            on_done: Optional[Callable[["CleanupResult"], None]] = None
            ) -> threading.Thread:
        """
        Run cleanup in a background thread.

        Returns the Thread object immediately - the caller can join() it
        if they need to wait, or ignore it for fire-and-forget.

        on_done(result) is called when the thread finishes.
        """
        self._abort.clear()
        thread = threading.Thread(
            target=self._run_thread,
            args=(targets, on_done),
            daemon=True
        )
        thread.start()
        return thread

    def abort(self):
        """Signal the running thread to stop after the current file."""
        self._abort.set()

    # ── measurement (no deletion) ──────────────
    def _measure(self, target: str) -> int:
        """Return estimated bytes for a target without deleting."""
        try:
            if target == "trash":
                return self._measure_trash()
            if target == "caches":
                return self._measure_caches()
            if target == "logs":
                return self._measure_logs()
            if target == "downloads":
                return self._measure_downloads()
        except Exception:
            pass
        return 0

    def _measure_trash(self) -> int:
        if _SYSTEM == "Windows":
            return _win_recycle_bin_size()
        trash = _platform_trash()
        if trash is None or not trash.exists():
            return 0
        return _dir_size(trash)

    def _measure_caches(self) -> int:
        caches_root = _platform_cache_root()
        total = 0
        for subdir in CACHE_SUBDIRS:
            p = caches_root / subdir
            if p.exists():
                total += _dir_size(p)
        return total

    def _measure_logs(self) -> int:
        total = 0
        log_root = _platform_log_root()
        for subdir in LOG_SUBDIRS:
            p = log_root / subdir
            if p.exists():
                for f in p.rglob("*"):
                    if f.is_file() and _file_age_days(f) > LOG_AGE_DAYS:
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
        return total

    def _measure_downloads(self) -> int:
        downloads = _platform_downloads()
        total = 0
        if not downloads.exists():
            return 0
        for f in downloads.iterdir():
            if f.is_file() and _file_age_days(f) > DOWNLOADS_AGE_DAYS:
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        return total

    # ── cleanup thread ─────────────────────────
    def _run_thread(self, targets: list,
                    on_done: Optional[Callable]):
        result = CleanupResult()
        result.targets_run = list(targets)

        self._log("=" * 48)
        self._log(f"[>]  Cleanup started - {result.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.dry_run:
            self._log("[!]   DRY RUN - no files will be deleted")
        self._log(f"Targets: {', '.join(targets)}")
        self._log("=" * 48)

        for target in targets:
            if self._abort.is_set():
                self._log("[STOP]  Cleanup aborted by user")
                break
            self._run_target(target, result)

        result.finish()
        self._log("=" * 48)
        self._log(f"[OK]  Done - {result.summary()}")
        self._log("=" * 48)

        if on_done:
            on_done(result)

    def _run_target(self, target: str, result: CleanupResult):
        self._log(f"\n>  Cleaning: {target.upper()}")
        try:
            if target == "trash":
                self._clean_trash(result)
            elif target == "caches":
                self._clean_caches(result)
            elif target == "logs":
                self._clean_logs(result)
            elif target == "downloads":
                self._clean_downloads(result)
            else:
                self._log(f"   [!]  Unknown target: {target}")
        except Exception as e:
            self._log(f"   [!!]  Target failed: {e}")
            result.errors.append((target, str(e)))

    # ── trash ──────────────────────────────────
    def _clean_trash(self, result: CleanupResult):
        """
        Empty the Trash / Recycle area for the current platform.
        - macOS:  ~/.Trash
        - Linux:  ~/.local/share/Trash/files  (freedesktop spec)
        - Windows: PowerShell Clear-RecycleBin cmdlet
        """
        if _SYSTEM == "Windows":
            self._clean_trash_windows(result)
            return

        trash = _platform_trash()
        if trash is None or not trash.exists():
            self._log("   Trash folder not found - skipping")
            return

        items = list(trash.iterdir())
        if not items:
            self._log("   Trash is already empty")
            return

        for item in items:
            if self._abort.is_set():
                break
            try:
                size = _dir_size(item) if item.is_dir() else item.stat().st_size
                if not self.dry_run:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                result.freed_bytes   += size
                result.deleted_files.append(str(item))
                prefix = "[DRY] " if self.dry_run else ""
                self._log(f"   {prefix}[x]  {item.name}  ({_bytes_to_human(size)})")
            except PermissionError:
                self._log(f"   [!]  Permission denied: {item.name}")
                result.skipped.append(str(item))
            except Exception as e:
                self._log(f"   [!!]  Error removing {item.name}: {e}")
                result.errors.append((str(item), str(e)))

    def _clean_trash_windows(self, result: CleanupResult):
        """
        Empty the Windows Recycle Bin via PowerShell.
        Measures size first so freed_bytes is accurate.
        dry_run: logs what would be freed but does not empty.
        """
        size = _win_recycle_bin_size()

        if size == 0:
            self._log("   Recycle Bin is already empty")
            return

        self._log(f"   Recycle Bin contains {_bytes_to_human(size)}")

        if self.dry_run:
            self._log(f"   [DRY] Would empty Recycle Bin ({_bytes_to_human(size)})")
            result.freed_bytes += size
            result.deleted_files.append("Windows Recycle Bin")
            return

        try:
            proc = subprocess.run(
                ["PowerShell", "-NonInteractive", "-Command",
                 "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=30
            )
            if proc.returncode == 0:
                result.freed_bytes += size
                result.deleted_files.append("Windows Recycle Bin")
                self._log(f"   [x]  Recycle Bin emptied  ({_bytes_to_human(size)})")
            else:
                err = proc.stderr.decode(errors="replace").strip()
                self._log(f"   [!!]  PowerShell returned error: {err or 'unknown'}")
                result.errors.append(("RecycleBin", err or "PowerShell error"))
        except FileNotFoundError:
            self._log("   [!!]  PowerShell not found - cannot empty Recycle Bin")
            result.errors.append(("RecycleBin", "PowerShell not found"))
        except subprocess.TimeoutExpired:
            self._log("   [!!]  PowerShell timed out emptying Recycle Bin")
            result.errors.append(("RecycleBin", "timeout"))

    # ── caches ─────────────────────────────────
    def _clean_caches(self, result: CleanupResult):
        """
        Remove known app cache subdirectories from the platform cache root.
        - macOS:   ~/Library/Caches/<bundle-id>
        - Windows: %LOCALAPPDATA%/<browser-profile-path>
        - Linux:   ~/.cache/<app-name>
        Targets specific subdirs only to avoid breaking apps that rely
        on persistent cache entries.
        """
        caches_root = _platform_cache_root()
        if not caches_root.exists():
            self._log(f"   Cache root not found ({caches_root}) - skipping")
            return

        found_any = False
        for subdir in CACHE_SUBDIRS:
            if self._abort.is_set():
                break
            p = caches_root / subdir
            if not p.exists():
                continue
            found_any = True
            size = _dir_size(p)
            try:
                if not self.dry_run:
                    shutil.rmtree(p)
                result.freed_bytes   += size
                result.deleted_files.append(str(p))
                prefix = "[DRY] " if self.dry_run else ""
                self._log(f"   {prefix}[x]  {subdir}  ({_bytes_to_human(size)})")
            except PermissionError:
                self._log(f"   [!]  Permission denied: {subdir}")
                result.skipped.append(str(p))
            except Exception as e:
                self._log(f"   [!!]  {subdir}: {e}")
                result.errors.append((str(p), str(e)))

        if not found_any:
            self._log("   No matching cache directories found")

    # ── logs ───────────────────────────────────
    def _clean_logs(self, result: CleanupResult):
        """
        Delete log files older than LOG_AGE_DAYS from the platform log root.
        - macOS:   ~/Library/Logs/DiagnosticReports + CrashReporter
        - Windows: %LOCALAPPDATA%/Logs/CrashDumps
        - Linux:   ~/.local/share/logs/crash + errors
        Only files are deleted, never directories.
        """
        log_root = _platform_log_root()
        deleted_count = 0

        for subdir in LOG_SUBDIRS:
            if self._abort.is_set():
                break
            p = log_root / subdir
            if not p.exists():
                continue

            for f in p.rglob("*"):
                if self._abort.is_set():
                    break
                if not f.is_file():
                    continue
                age = _file_age_days(f)
                if age <= LOG_AGE_DAYS:
                    result.skipped.append(str(f))
                    continue
                try:
                    size = f.stat().st_size
                    if not self.dry_run:
                        f.unlink()
                    result.freed_bytes   += size
                    result.deleted_files.append(str(f))
                    deleted_count += 1
                    prefix = "[DRY] " if self.dry_run else ""
                    self._log(
                        f"   {prefix}[x]  {f.name}  "
                        f"({_bytes_to_human(size)}, {age:.0f} days old)"
                    )
                except PermissionError:
                    result.skipped.append(str(f))
                except Exception as e:
                    result.errors.append((str(f), str(e)))

        if deleted_count == 0:
            self._log(f"   No log files older than {LOG_AGE_DAYS} days found")

    # ── downloads ──────────────────────────────
    def _clean_downloads(self, result: CleanupResult):
        """
        Delete files (not folders) from ~/Downloads that are older
        than DOWNLOADS_AGE_DAYS. Folders are never touched - only
        top-level files to avoid accidental data loss.
        """
        downloads = _platform_downloads()
        if not downloads.exists():
            self._log(f"   Downloads folder not found ({downloads}) - skipping")
            return

        deleted_count = 0
        for f in downloads.iterdir():
            if self._abort.is_set():
                break
            if not f.is_file():
                # Skip subdirectories entirely
                result.skipped.append(str(f))
                continue
            age = _file_age_days(f)
            if age <= DOWNLOADS_AGE_DAYS:
                result.skipped.append(str(f))
                continue
            try:
                size = f.stat().st_size
                if not self.dry_run:
                    f.unlink()
                result.freed_bytes   += size
                result.deleted_files.append(str(f))
                deleted_count += 1
                prefix = "[DRY] " if self.dry_run else ""
                self._log(
                    f"   {prefix}[x]  {f.name}  "
                    f"({_bytes_to_human(size)}, {age:.0f} days old)"
                )
            except PermissionError:
                self._log(f"   [!]  Permission denied: {f.name}")
                result.skipped.append(str(f))
            except Exception as e:
                self._log(f"   [!!]  {f.name}: {e}")
                result.errors.append((str(f), str(e)))

        if deleted_count == 0:
            self._log(
                f"   No files older than {DOWNLOADS_AGE_DAYS} days found"
            )

    # ── logger ─────────────────────────────────
    def _log(self, msg: str):
        ts  = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{ts}]  {msg}")


# ─────────────────────────────────────────────
# Standalone runner / dry-run preview
# ─────────────────────────────────────────────
def _run_standalone():
    """
    Prints a dry-run scan + cleanup preview to the terminal.
    No files are deleted.
    """
    print("=" * 52)
    print("System Health Monitor - Cleanup Engine (DRY RUN)")
    print("=" * 52)

    targets = ["trash", "caches", "logs", "downloads"]
    engine  = CleanupEngine(log_callback=print, dry_run=True)

    print("\n[D]  Scanning...")
    scan = engine.scan(targets)
    print(f"\n{'Target':<20} {'Size':>12}")
    print("-" * 34)
    for target, size in scan.targets.items():
        print(f"{target:<20} {_bytes_to_human(size):>12}")
    print("-" * 34)
    print(f"{'TOTAL':<20} {_bytes_to_human(scan.total_bytes()):>12}")

    print("\n\n[>]  Running dry-run cleanup...\n")
    done_event = threading.Event()
    final_result = {}

    def on_done(result):
        final_result["r"] = result
        done_event.set()

    engine.run(targets, on_done=on_done)
    done_event.wait(timeout=60)

    if "r" in final_result:
        r = final_result["r"]
        print(f"\n[L]  Summary: {r.summary()}")


# ─────────────────────────────────────────────
# Test suite  (python cleanup.py --test)
# ─────────────────────────────────────────────
def _run_tests():
    print("=" * 52)
    print("Module 5 - cleanup.py test suite")
    print("=" * 52)
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  [OK]  {name}"); passed += 1
        else:
            print(f"  [!!]  {name}" + (f" > {detail}" if detail else ""))
            failed += 1

    # 1. _bytes_to_human
    check("bytes B",  _bytes_to_human(500)            == "500 B")
    check("bytes KB", _bytes_to_human(2048)            == "2 KB")
    check("bytes MB", _bytes_to_human(5 * 1024**2)     == "5.0 MB")
    check("bytes GB", _bytes_to_human(2 * 1024**3)     == "2.00 GB")

    # 2. _file_age_days - newly created file should be ~0 days old
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tmp_path = Path(tf.name)
    age = _file_age_days(tmp_path)
    check("new file age < 1 day", age < 1, f"got {age:.4f}")
    tmp_path.unlink()

    # 3. CleanupResult
    r = CleanupResult()
    r.freed_bytes = 5 * 1024**2
    r.deleted_files = ["a", "b", "c"]
    r.finish()
    check("freed_str 5MB",    r.freed_str() == "5.0 MB")
    check("duration_str set", len(r.duration_str()) > 0)
    check("summary non-empty", len(r.summary()) > 0)
    d = r.to_dict()
    check("to_dict keys",
          all(k in d for k in ("freed_bytes", "deleted_count", "summary")))
    check("to_dict deleted_count", d["deleted_count"] == 3)

    # 4. ScanResult
    sr = ScanResult()
    sr.add("trash", 1024**2)
    sr.add("caches", 2 * 1024**2)
    check("ScanResult total",  sr.total_bytes() == 3 * 1024**2)
    check("ScanResult total_mb", sr.total_mb() == 3)
    labels = sr.target_labels()
    check("ScanResult labels non-empty", len(labels) == 2)

    # 5. DRY RUN - uses a self-contained temp directory, never touches real files
    import tempfile, shutil as _shutil
    import unittest.mock as mock

    # Build a fake home directory with controlled content
    fake_home = Path(tempfile.mkdtemp())

    # Trash — use the same layout as _platform_trash() but rooted at fake_home
    if _SYSTEM == "Darwin":
        fake_trash = fake_home / ".Trash"
    elif _SYSTEM == "Windows":
        fake_trash = None  # Windows trash uses PowerShell, not a local dir
    else:
        fake_trash = fake_home / ".local" / "share" / "Trash" / "files"

    if fake_trash is not None:
        fake_trash.mkdir(parents=True)
        (fake_trash / "old_doc.pdf").write_text("x" * 1024)
        (fake_trash / "old_img.png").write_text("y" * 2048)

    # Caches — mirror _platform_cache_root() under fake_home
    if _SYSTEM == "Darwin":
        fake_cache_root = fake_home / "Library" / "Caches"
        first_cache_subdir = CACHE_SUBDIRS[0]  # e.g. "com.apple.Safari"
    elif _SYSTEM == "Windows":
        fake_cache_root = fake_home / "AppData" / "Local"
        first_cache_subdir = CACHE_SUBDIRS[0] if CACHE_SUBDIRS else "TestCache"
    else:
        fake_cache_root = fake_home / ".cache"
        first_cache_subdir = CACHE_SUBDIRS[0] if CACHE_SUBDIRS else "test-app"

    fake_caches = fake_cache_root / first_cache_subdir
    fake_caches.mkdir(parents=True)
    (fake_caches / "cache1.db").write_text("z" * 512)

    # Logs — mirror _platform_log_root() under fake_home
    if _SYSTEM == "Darwin":
        fake_log_root = fake_home / "Library" / "Logs"
    elif _SYSTEM == "Windows":
        fake_log_root = fake_home / "AppData" / "Local" / "Logs"
    else:
        fake_log_root = fake_home / ".local" / "share" / "logs"

    first_log_subdir = LOG_SUBDIRS[0] if LOG_SUBDIRS else "crash"
    fake_logs = fake_log_root / first_log_subdir
    fake_logs.mkdir(parents=True)
    old_log = fake_logs / "old.crash"
    old_log.write_text("crash" * 100)
    old_time = time.time() - (LOG_AGE_DAYS + 1) * 86400
    os.utime(old_log, (old_time, old_time))

    # Downloads
    fake_downloads = fake_home / "Downloads"
    fake_downloads.mkdir()

    def fake_platform_downloads():
        return fake_downloads
    old_dl = fake_downloads / "old_installer.dmg"
    old_dl.write_text("old" * 100)
    old_dl_time = time.time() - (DOWNLOADS_AGE_DAYS + 1) * 86400
    os.utime(old_dl, (old_dl_time, old_dl_time))
    new_dl = fake_downloads / "recent_file.zip"
    new_dl.write_text("new" * 100)   # recent - should NOT be deleted

    # Patch both Path.home() and the platform helper functions to use fake_home
    def fake_platform_trash():
        return fake_trash

    def fake_platform_cache_root():
        return fake_cache_root

    def fake_platform_log_root():
        return fake_log_root

    log_lines = []
    engine = CleanupEngine(log_callback=log_lines.append, dry_run=True)

    with mock.patch.object(Path, "home", return_value=fake_home), \
         mock.patch("cleanup._platform_trash", fake_platform_trash), \
         mock.patch("cleanup._platform_cache_root", fake_platform_cache_root), \
         mock.patch("cleanup._platform_log_root", fake_platform_log_root), \
         mock.patch("cleanup._platform_downloads", fake_platform_downloads):

        scan = engine.scan(["trash", "caches", "logs", "downloads"])
        check("scan all 4 targets",   len(scan.targets) == 4)
        if _SYSTEM != "Windows":
            check("scan trash > 0",   scan.targets.get("trash", 0) > 0)
        check("scan caches > 0",      scan.targets.get("caches", 0) > 0)
        check("scan total > 0",       scan.total_bytes() > 0)

        done = threading.Event()
        results_holder = {}

        def on_done(r):
            results_holder["result"] = r
            done.set()

        engine.run(["trash", "caches", "logs", "downloads"], on_done=on_done)
        completed = done.wait(timeout=10)
        check("dry-run completes",    completed, "timed out")

    if completed:
        r = results_holder["result"]
        check("dry-run freed > 0",    r.freed_bytes > 0)
        check("dry-run has log",      len(log_lines) > 0)
        check("dry-run no deletions", old_dl.exists(),
              "file was deleted in dry-run!")
        check("dry-run summary ok",   len(r.summary()) > 0)

    # Real deletion test
    log_lines2 = []
    real_engine = CleanupEngine(log_callback=log_lines2.append, dry_run=False)

    with mock.patch.object(Path, "home", return_value=fake_home), \
         mock.patch("cleanup._platform_trash", fake_platform_trash), \
         mock.patch("cleanup._platform_cache_root", fake_platform_cache_root), \
         mock.patch("cleanup._platform_log_root", fake_platform_log_root), \
         mock.patch("cleanup._platform_downloads", fake_platform_downloads):

        done2 = threading.Event()
        results2 = {}

        def on_done2(r):
            results2["result"] = r
            done2.set()

        real_engine.run(["trash", "downloads"], on_done=on_done2)
        completed2 = done2.wait(timeout=10)
        check("real-run completes",   completed2, "timed out")

    if completed2:
        r2 = results2["result"]
        if _SYSTEM != "Windows" and fake_trash is not None:
            check("trash file deleted", not (fake_trash / "old_doc.pdf").exists())
        check("old download deleted", not old_dl.exists())
        check("new download kept",    new_dl.exists(),
              "recent file was incorrectly deleted!")
        check("freed bytes > 0",      r2.freed_bytes > 0)

    _shutil.rmtree(fake_home, ignore_errors=True)

    # 6. Abort mechanism
    abort_engine = CleanupEngine(log_callback=lambda _: None, dry_run=True)
    abort_engine.abort()
    check("abort sets event", abort_engine._abort.is_set())

    print("-" * 52)
    print(f"  {passed} passed · {failed} failed")
    print("=" * 52)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        _run_tests()
    elif "--dry-run" in sys.argv:
        _run_standalone()
    else:
        # Default: dry run (safety first)
        print("Usage:")
        print("  python cleanup.py --test      run test suite")
        print("  python cleanup.py --dry-run   preview what would be cleaned")
        print()
        print("To actually clean (from your app code):")
        print("  engine = CleanupEngine(log_callback=print, dry_run=False)")
        print("  engine.run(['trash', 'caches', 'logs', 'downloads'])")
