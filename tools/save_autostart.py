"""PC-side uploader: back up boot/main, then install a script as main.py."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MARKER = "CYBERBRICK_STARTUP_FILES="


def remote(port, *args):
    result = subprocess.run(
        [sys.executable, "-m", "mpremote", "connect", port, "resume", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=45,
    )
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def read_files(port, names):
    # Transfer in mpremote's small chunks rather than hex-encoding entire files
    # in the board's limited heap. This also works for larger main.py files.
    code = (
        "import os, json, gc\n"
        "gc.collect()\n"
        f"files = {{name: name in os.listdir('/') for name in {names!r}}}\n"
        f"print({MARKER!r} + json.dumps(files))\n"
    )
    output = remote(port, "exec", code)
    for line in output.splitlines():
        if line.startswith(MARKER):
            present = json.loads(line[len(MARKER):])
            break
    else:
        raise RuntimeError("Could not list board files: " + output)
    result = {}
    with tempfile.TemporaryDirectory(prefix="cyberbrick-read-") as directory:
        for name in names:
            if present[name]:
                destination = Path(directory) / name
                remote(port, "fs", "cp", ":/" + name, str(destination))
                result[name] = destination.read_bytes().hex()
            else:
                result[name] = None
    return result


def read_startup(port):
    return read_files(port, ("boot.py", "main.py"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--source", default="blink.py",
                        help="Local application script; relative paths use the project root.")
    args = parser.parse_args()

    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = ROOT / source_path
    source = source_path.read_bytes()
    compile(source, "main.py", "exec")
    boot = b"# User application starts in main.py. Original startup is backed up on PC.\n"

    print("Reading the board's boot.py and main.py...", flush=True)
    original = read_startup(args.port)
    backup = ROOT / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_text(
        json.dumps({"port": args.port, "source": str(source_path),
                    "files": original}, indent=2), encoding="utf-8"
    )
    for name, data in original.items():
        if data is not None:
            (backup / name).write_bytes(bytes.fromhex(data))
    print("Startup backup saved to: " + str(backup), flush=True)

    # Upload a fixed snapshot in chunks; verify before changing startup entries.
    expected = {"boot.py": boot.hex(), "main.py": source.hex()}
    with tempfile.TemporaryDirectory(prefix="cyberbrick-upload-") as directory:
        for name, data in (("main.py", source), ("boot.py", boot)):
            staged = Path(directory) / name
            staged.write_bytes(data)
            remote(args.port, "fs", "cp", str(staged), ":/" + name + ".upload")
    remote(args.port, "exec", "import os\nos.sync()\n")
    actual_staged = read_files(args.port, ("boot.py.upload", "main.py.upload"))
    if actual_staged != {name + ".upload": data for name, data in expected.items()}:
        raise RuntimeError("Staged file verification failed. Backup: " + str(backup))
    # Install main first. Disable the factory boot entry only after main exists.
    remote(args.port, "exec", (
        "import os\n"
        "os.rename('/main.py.upload', '/main.py')\n"
        "os.rename('/boot.py.upload', '/boot.py')\n"
        "os.sync()\n"
    ))
    actual = read_startup(args.port)
    if actual != expected:
        raise RuntimeError("Startup read-back verification failed. Backup: " + str(backup))
    print("Saved and verified: " + source_path.name + " -> /main.py.")
    print("Press RST or reconnect power to start the saved application.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, SyntaxError) as exc:
        print("Upload did not complete: " + str(exc), file=sys.stderr)
        print("Keep any backup path printed above. Close other serial terminals before retrying.",
              file=sys.stderr)
        sys.exit(1)
