"""Console-free entry point. Diagnostics contain fixed event codes and PIDs only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def record(directory, event):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        log = directory / 'launcher.log'
        if log.exists() and log.stat().st_size > 65536:
            log.replace(directory / 'launcher.previous.log')
        with log.open('a', encoding='utf-8') as stream:
            stream.write(f'{datetime.now(timezone.utc).isoformat()} pid={os.getpid()} {event}\n')
    except OSError:
        pass  # Failure to write diagnostics must not erase or reset app state.


def project_pythonw():
    if getattr(sys, 'frozen', False):
        return None
    environment = ROOT / '.venv-desktop'
    executable = environment / 'Scripts' / 'pythonw.exe'
    if executable.is_file() and Path(sys.prefix).resolve() != environment.resolve():
        return executable
    return None


def main(argv=None, *, prefer_environment=True):
    from app_state import default_data_dir, data_override
    parser = argparse.ArgumentParser(description='Tera quiet GUI launcher')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--self-test', choices=['app', 'desktop'], help='Run an isolated synthetic check; requires --data-dir.')
    args = parser.parse_args(argv)
    override = data_override(args.data_dir)
    directory = override or default_data_dir()
    try:
        if args.self_test:
            if args.data_dir is None:
                raise ValueError('Self-tests require an explicit disposable data directory.')
            directory.mkdir(parents=True, exist_ok=True)
            from contextlib import redirect_stdout, redirect_stderr
            with (directory / 'self-test.log').open('x', encoding='utf-8') as output, redirect_stdout(output), redirect_stderr(output):
                if args.self_test == 'app':
                    from smoke_terabox_gui import main as check
                else:
                    from smoke_desktop import main as check
                from windows_runtime import application_mutex
                with application_mutex():
                    check(directory)
            record(directory, 'self_test_passed')
            return 0
        executable = project_pythonw() if prefer_environment else None
        if executable:
            child = subprocess.Popen([str(executable), str(ROOT / 'Start Tera.pyw'), *(argv if argv is not None else sys.argv[1:])],
                                     cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            record(directory, f'handed_off child_pid={child.pid}')
            return 0
        record(directory, 'started')
        import tkinter as tk
        from tera_gui import gui
        original = tk.Tk.report_callback_exception
        def callback(root, kind, error, trace):
            record(directory, 'callback_failed')
        tk.Tk.report_callback_exception = callback
        try:
            gui(override)
        finally:
            tk.Tk.report_callback_exception = original
        record(directory, 'exited')
        return 0
    except Exception:
        record(directory, 'startup_failed')
        return 1
