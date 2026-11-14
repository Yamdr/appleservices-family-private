"""Prepare pinned NAC code and libraries only; never read accounts or contact Apple auth."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import requests

PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = PROJECT / ".cache/mac-nac-runtime"
SOURCE = PROJECT / ".cache/activation-source-review"
PYPUSH_REVISION = "f205e86bdf1a4ea5414a78985721c721039ada97"
ENCRYPT_REVISION = "be8d3f83be30a88dca26ee7ad1fb862b8af889e9"
ENCRYPT_SHA256 = "5f6bf2de1d6add2f98513a06b47e2fca0bd643026bee00a2d2ded531c31e73d8"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url, destination, expected):
    if destination.is_file() and digest(destination) == expected:
        return
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != expected:
        raise RuntimeError("Downloaded resource hash mismatch: " + destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name + ".download")
    pending.write_bytes(response.content)
    os.replace(pending, destination)


def main():
    if os.name != "nt" or PROJECT.drive.upper() != "D:":
        raise RuntimeError("This Windows installation must be prepared on D:")
    temp = PROJECT / ".cache/component-prepare-temp"
    temp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp),
               PIP_CACHE_DIR=str(PROJECT / ".cache/pip-cache"), PYTHONDONTWRITEBYTECODE="1")
    compiler = shutil.which("gcc")
    if not compiler:
        raise RuntimeError("Load the D: environment.ps1 before preparing components")
    manifest = json.loads((PROJECT / "tools/runtime-components.json").read_text(encoding="utf-8"))
    records = []
    for item in manifest["resources"]:
        if item["group"] != "nac":
            continue
        name = Path(item["path"]).name
        if name == "IMDAppleServices":
            url = "https://raw.githubusercontent.com/JJTech0130/nacserver/0a2aa2406542fb09c14a37db17ff14865b8aea29/IMDAppleServices"
        else:
            url = f"https://raw.githubusercontent.com/JJTech0130/pypush/{PYPUSH_REVISION}/emulated/{name}"
        fetch(url, PROJECT / item["path"], item["sha256"])
        records.append({"path": item["path"], "sha256": item["sha256"], "url": url})
    # Deliberately do not download upstream data.plist: account-bound data is
    # created by mac-nac-check.py inside the selected account's private copy.
    fetch(f"https://raw.githubusercontent.com/mosessupposeshis/imessage/{ENCRYPT_REVISION}/rustpush/open-absinthe/src/asm/encrypt.s",
          SOURCE / "encrypt.s", ENCRYPT_SHA256)
    dependencies = RUNTIME / "dependencies"
    dependencies.mkdir(parents=True, exist_ok=True)
    probe = "import sys;sys.path.insert(0,sys.argv[1]);import unicorn;assert unicorn.__version__=='2.1.4'"
    available = subprocess.run([sys.executable, "-X", "utf8", "-c", probe, str(dependencies)],
                               env=env, capture_output=True, timeout=20)
    if available.returncode:
        subprocess.run([sys.executable, "-X", "utf8", "-m", "pip", "install", "--disable-pip-version-check",
                        "--no-input", "--no-compile", "--only-binary=:all:", "--no-deps", "--upgrade",
                        "--target", str(dependencies), "unicorn==2.1.4"], env=env, check=True, timeout=180)
    library = SOURCE / "mac-io-encrypt.dll"
    subprocess.run([compiler, "-shared", "-O2", "-Wl,--no-insert-timestamp",
                    str(PROJECT / "tools/mac-io-encrypt.c"), str(SOURCE / "encrypt.s"), "-o", str(library)],
                   env=env, check=True, timeout=60)
    result = {"files": records, "pypush_revision": PYPUSH_REVISION,
              "encrypt_revision": ENCRYPT_REVISION, "encrypt_dll_sha256": digest(library),
              "unicorn_version": "2.1.4", "donor_profile_copied": False}
    (RUNTIME / "runtime-manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "runtime": str(RUNTIME), "account_operations": False}))


if __name__ == "__main__":
    main()
