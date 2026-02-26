from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "release" / "templates"
DIST_DIR = ROOT / "dist"

ROLE_ENTRYPOINT = {
    "client": "vodin.client_entry:main",
    "master": "vodin.master_entry:main",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build standalone release binary for VODIN role")
    parser.add_argument("--role", choices=["client", "master"], required=True)
    parser.add_argument("--onefile", action="store_true", help="Build onefile executable")
    parser.add_argument("--clean", action="store_true", help="Clean build/dist before building")
    return parser.parse_args()


def ensure_pyinstaller() -> None:
    try:
        __import__("PyInstaller")
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyInstaller is not installed. Install it with: pip install pyinstaller"
        ) from exc


def copy_template(role: str, out_dir: Path) -> None:
    src = TEMPLATES_DIR / f"{role}.template.yml"
    dst = out_dir / f"{role}.yml"
    shutil.copy2(src, dst)


def build(role: str, onefile: bool, clean: bool) -> None:
    ensure_pyinstaller()

    if clean:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(DIST_DIR, ignore_errors=True)

    name = f"vodin-{role}"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        name,
        "--noconfirm",
        "--paths",
        str(ROOT / "src"),
    ]

    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    cmd.extend(["--collect-all", "uvicorn", "--collect-all", "fastapi", "--collect-all", "pydantic"])
    cmd.append(str(ROOT / "src" / "vodin" / f"{role}_entry.py"))

    subprocess.run(cmd, check=True, cwd=ROOT)

    role_dist = DIST_DIR / name
    if onefile:
        role_dist.mkdir(parents=True, exist_ok=True)
        suffix = ".exe" if sys.platform.startswith("win") else ""
        binary = DIST_DIR / f"{name}{suffix}"
        shutil.move(str(binary), str(role_dist / binary.name))

    copy_template(role, role_dist)

    print(f"Built release: {role_dist}")


def main() -> None:
    args = parse_args()
    build(args.role, args.onefile, args.clean)


if __name__ == "__main__":
    main()
