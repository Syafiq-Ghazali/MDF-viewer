"""Windows smoke test: launch the packaged EXE, verify file load, close cleanly."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import time


def main():
    if os.name != "nt":
        raise SystemExit("The packaged executable smoke test requires Windows.")
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / "MDFViewer" / "MDFViewer.exe"
    recording = root / "examples" / "motor_drive.mf4"
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE; do not open a visible test application.
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    process = subprocess.Popen([str(executable), str(recording)], cwd=root, startupinfo=startup, env=environment)
    found = []
    errors = []

    @callback_type
    def read_error(handle, _):
        text = ctypes.create_unicode_buffer(4096)
        user32.GetWindowTextW(handle, text, len(text))
        if text.value:
            errors.append(text.value)
        return True

    user32.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]

    @callback_type
    def visit(handle, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value == process.pid:
            title = ctypes.create_unicode_buffer(1024)
            user32.GetWindowTextW(handle, title, len(title))
            if title.value == "motor_drive.mf4 — MDF Waveform Viewer":
                found.append(handle)
            elif title.value == "Unhandled exception in script":
                user32.EnumChildWindows(handle, read_error, 0)
        return True

    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and process.poll() is None:
            user32.EnumWindows(visit, 0)
            if errors:
                raise RuntimeError("Packaged app failed: " + "; ".join(errors))
            if found:
                user32.PostMessageW(found[0], 0x0010, 0, 0)  # WM_CLOSE
                result = process.wait(timeout=10)
                if result:
                    raise RuntimeError(f"Packaged app exited with code {result}")
                print("PASS: packaged app opened motor_drive.mf4 and closed cleanly.")
                return
            time.sleep(0.1)
        raise RuntimeError(f"Packaged app did not load the recording (exit={process.poll()}).")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
