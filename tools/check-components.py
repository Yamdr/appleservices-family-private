"""Check Windows deployment files and load local runtimes without account access."""
import argparse
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys

sys.dont_write_bytecode = True

BINARIES = (
    "dashboard", "trusted-device-gui", "trusted-device", "login", "storeauth",
    "familyinspect", "accountsetupcheck", "nacexchange",
)
SUPPORT_FILES = (
    "tools/mac-push-check.py", "tools/mac-nac-check.py", "tools/skill-store-transport.py",
    "nativeadi/bridge.py", "gsa/apple_root_ca.go", "gsa/apple_root_ca_g3.pem",
    ".cache/activation-source-review/mac-io-encrypt.dll",
    ".cache/mac-nac-runtime/dependencies/unicorn/__init__.py",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pe_amd64(path):
    with path.open("rb") as source:
        if source.read(2) != b"MZ":
            return False
        source.seek(0x3C)
        offset = struct.unpack("<I", source.read(4))[0]
        source.seek(offset)
        return source.read(6) == b"PE\0\0\x64\x86"


def audit(project, cache):
    checks = []

    def check(name, operation):
        try:
            passed = bool(operation())
            checks.append({"component": name, "ok": passed})
        except Exception as error:
            checks.append({"component": name, "ok": False, "error": type(error).__name__})

    check("windows-amd64-python", lambda: os.name == "nt" and struct.calcsize("P") == 8 and sys.version_info >= (3, 10))
    check("gcc", lambda: shutil.which("gcc"))
    for name in BINARIES:
        check("bin/" + name + ".exe", lambda name=name: pe_amd64(project / "bin" / (name + ".exe")))
    for name in SUPPORT_FILES:
        check(name, lambda name=name: (project / name).is_file() and (project / name).stat().st_size > 0)

    manifest = json.loads((Path(__file__).parent / "runtime-components.json").read_text(encoding="utf-8"))
    for spec in manifest["resources"]:
        base = cache if spec["root"] == "cache" else project
        check(spec["group"] + ":" + Path(spec["path"]).name,
              lambda base=base, spec=spec: base is not None and sha256(base / spec["path"]) == spec["sha256"])

    for name in ("requests", "cryptography"):
        check("python:" + name, lambda name=name: importlib.import_module(name))
    check("openbubbles-load", lambda: ctypes.CDLL(str(project / ".cache/openbubbles-store/rust_lib_bluebubbles.dll")))
    check("nac-encryption-export", lambda: getattr(ctypes.CDLL(str(project / ".cache/activation-source-review/mac-io-encrypt.dll")), "mac_io_encrypt"))
    check("windows-dpapi", lambda: getattr(ctypes.WinDLL("crypt32.dll"), "CryptProtectData"))

    def unicorn_check():
        sys.path.insert(0, str(project / ".cache/mac-nac-runtime/dependencies"))
        import unicorn
        from unicorn.x86_const import UC_X86_REG_RAX
        if unicorn.__version__ != "2.1.4":
            return False
        engine = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
        engine.mem_map(0x1000, 0x1000)
        engine.mem_write(0x1000, bytes.fromhex("48c7c02a000000"))
        engine.emu_start(0x1000, 0x1007)
        return engine.reg_read(UC_X86_REG_RAX) == 42

    check("nac-unicorn-load-and-execute", unicorn_check)
    optional = {"icloud_windows_native_push": "not-detected"}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"CLSID\{6812639B-FD61-4329-9901-22CFDBD690FE}"):
            optional["icloud_windows_native_push"] = "registered"
    except OSError:
        pass
    return {"ok": all(item["ok"] for item in checks), "checks": checks, "optional": optional,
            "network_used": False, "account_state_used": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    cache = os.environ.get("APPLESERVICES_CACHE_DIR", "")
    if cache and not Path(cache).is_absolute():
        parser.error("APPLESERVICES_CACHE_DIR must be absolute")
    result = audit(args.project.resolve(), Path(cache) if cache else None)
    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result["ok"]:
        missing = [item["component"] for item in result["checks"] if not item["ok"]]
        print("Missing or invalid local components: " + ", ".join(missing), file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
