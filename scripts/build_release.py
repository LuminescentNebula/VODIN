from __future__ import annotations

import argparse
import base64
import io
import importlib.metadata
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "release" / "templates"
DIST_DIR = ROOT / "dist"

ROLE_ENTRYPOINT = {
    "client": "vodin.client_entry:main",
    "master": "vodin.master_entry:main",
}

RUNTIME_DISTRIBUTIONS = [
    "fastapi",
    "pydantic",
    "pydantic-core",
    "uvicorn",
    "httpx",
    "psutil",
    "cryptography",
    "pyyaml",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build standalone release binary for VODIN role")
    parser.add_argument("--role", choices=["client", "master"], required=True)
    parser.add_argument("--onefile", action="store_true", help="Build onefile executable")
    parser.add_argument(
        "--linux-single-py",
        action="store_true",
        help="Build a single Python file for Linux with bundled dependencies",
    )
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


def _collect_dist_files(
    dist_name: str,
    archive: zipfile.ZipFile,
    added: set[str],
    visited: set[str],
    required_top_level: set[str],
) -> None:
    normalized = dist_name.strip().lower().replace("_", "-")
    if not normalized or normalized in visited:
        return
    visited.add(normalized)

    try:
        distribution = importlib.metadata.distribution(normalized)
    except importlib.metadata.PackageNotFoundError:
        if normalized in required_top_level:
            raise SystemExit(
                f"Required dependency '{dist_name}' is not installed in current environment. "
                "Install dependencies before build."
            )
        return

    if distribution.files:
        for relative_file in distribution.files:
            file_path = distribution.locate_file(relative_file)
            if not file_path.exists() or file_path.is_dir():
                continue
            archive_path = relative_file.as_posix()
            if archive_path in added:
                continue
            archive.write(file_path, archive_path)
            added.add(archive_path)

    for raw_requirement in distribution.requires or []:
        parsed = Requirement(raw_requirement)
        if parsed.marker and not parsed.marker.evaluate({"extra": ""}):
            continue
        _collect_dist_files(parsed.name, archive, added, visited, required_top_level)


def build_python_single_file(role: str) -> None:
    role_dist = DIST_DIR / f"vodin-{role}-linux-py"
    role_dist.mkdir(parents=True, exist_ok=True)

    src_zip_bytes = io.BytesIO()
    with zipfile.ZipFile(src_zip_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (ROOT / "src").rglob("*.py"):
            archive.write(path, path.relative_to(ROOT / "src"))

        added_files: set[str] = set()
        visited_dists: set[str] = set()
        required_top_level = {name.lower().replace("_", "-") for name in RUNTIME_DISTRIBUTIONS}
        for distribution in RUNTIME_DISTRIBUTIONS:
            _collect_dist_files(distribution, archive, added_files, visited_dists, required_top_level)

    entrypoint = ROLE_ENTRYPOINT[role]
    encoded = base64.b64encode(src_zip_bytes.getvalue()).decode("ascii")
    runner = textwrap.dedent(
        f'''\
        #!/usr/bin/env python3
        from __future__ import annotations

        import base64
        import runpy
        import sys
        import tempfile
        import zipfile
        from pathlib import Path

        ARCHIVE_B64 = """{encoded}"""

        def main() -> None:
            with tempfile.TemporaryDirectory(prefix="vodin_") as tmp_dir:
                root = Path(tmp_dir)
                src_zip = root / "src.zip"
                src_zip.write_bytes(base64.b64decode(ARCHIVE_B64))
                with zipfile.ZipFile(src_zip, "r") as zf:
                    zf.extractall(root)
                sys.path.insert(0, str(root))
                module_name = "{entrypoint.split(':')[0]}"
                runpy.run_module(module_name, run_name="__main__")

        if __name__ == "__main__":
            main()
        '''
    )

    output_file = role_dist / f"vodin-{role}-linux.py"
    output_file.write_text(runner, encoding="utf-8")
    output_file.chmod(0o755)
    copy_template(role, role_dist)
    print(f"Built Linux single python file: {output_file}")


def build_pyinstaller(role: str, onefile: bool) -> None:
    ensure_pyinstaller()

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


def build(role: str, onefile: bool, linux_single_py: bool, clean: bool) -> None:
    if clean:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(DIST_DIR, ignore_errors=True)

    if linux_single_py:
        build_python_single_file(role)
        return

    build_pyinstaller(role, onefile)


def main() -> None:
    args = parse_args()
    build(args.role, args.onefile, args.linux_single_py, args.clean)


if __name__ == "__main__":
    main()
