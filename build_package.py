#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Registry Center Offline Package Builder

Builds a self-extracting .run installer for Linux (x86_64 / aarch64).
The target machine must have Python 3.12+, PostgreSQL, and Milvus pre-installed.

Usage:
    python build_package.py [--version VERSION] [--output-dir DIR] [--skip-download]

Output:
    dist/registry-center-<version>-linux-universal.run
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.resolve()
DEFAULT_VERSION = "1.0.0"
PYTHON_VERSION_TAG = "312"

# Directories to include in the package
INCLUDE_DIRS = [
    "agent_registry",
    "common",
    "etc/conf",
    "etc/systemd",
    "bin",
]

# Directories/patterns to exclude
EXCLUDE_DIRS = {"tests", "docs", ".git", "__pycache__", ".github", "dist", "node_modules"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}

# Test dependencies to exclude from requirements
TEST_DEPS = {"pytest", "pytest-asyncio"}

# Platforms for wheel download
PLATFORMS = {
    "x86_64": [
        "manylinux2014_x86_64",
        "manylinux_2_17_x86_64",
        "manylinux_2_28_x86_64",
        "linux_x86_64",
    ],
    "aarch64": [
        "manylinux2014_aarch64",
        "manylinux_2_17_aarch64",
        "manylinux_2_28_aarch64",
        "linux_aarch64",
    ],
}


# ---------------------------------------------------------------------------
# Installer script template (embedded in the .run file)
# ---------------------------------------------------------------------------

INSTALLER_SCRIPT = r'''#!/bin/bash
# Registry Center Self-Extracting Installer
# Supports: Linux x86_64 / aarch64, Python 3.12+
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Defaults
TARGET_DIR="/opt/registry-center"
INSTALL_SERVICE=false
SKIP_INIT=false
LOCAL_MODE=false

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --target DIR          Installation directory (default: /opt/registry-center)"
    echo "  --local               Install to ./registry-center (for testing without root)"
    echo "  --install-service     Install systemd service after setup"
    echo "  --skip-init           Skip interactive initialization"
    echo "  --help                Show this help message"
    exit 0
}

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --target)
            TARGET_DIR="$2"
            shift 2
            ;;
        --local)
            LOCAL_MODE=true
            TARGET_DIR="$(pwd)/registry-center"
            shift
            ;;
        --install-service)
            INSTALL_SERVICE=true
            shift
            ;;
        --skip-init)
            SKIP_INIT=true
            shift
            ;;
        --help)
            usage
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
    esac
done

echo -e "${CYAN}"
echo "============================================================"
echo "   Registry Center Installer"
echo "   A2A-T AgentCard Registry - Offline Deployment"
echo "============================================================"
echo -e "${NC}"

# --- Step 1: Detect architecture ---
echo -e "${CYAN}[1/7] Detecting system architecture...${NC}"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)
        ARCH="x86_64"
        ;;
    aarch64|arm64)
        ARCH="aarch64"
        ;;
    *)
        echo -e "${RED}Error: Unsupported architecture '$ARCH'. Only x86_64 and aarch64 are supported.${NC}"
        exit 1
        ;;
esac
echo -e "${GREEN}  Architecture: $ARCH${NC}"

# --- Step 2: Check Python version ---
echo -e "${CYAN}[2/7] Checking Python version...${NC}"
PYTHON_CMD=""
for cmd in python3.12 python3.13 python3.14 python3; do
    if command -v "$cmd" &>/dev/null; then
        PY_VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 12 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}Error: Python 3.12+ is required but not found.${NC}"
    echo "Please install Python 3.12 or later and try again."
    exit 1
fi
echo -e "${GREEN}  Python: $PYTHON_CMD ($($PYTHON_CMD --version))${NC}"

# --- Pre-check: verify write permission to target parent directory ---
TARGET_PARENT=$(dirname "$TARGET_DIR")
if [ ! -d "$TARGET_PARENT" ]; then
    echo -e "${RED}Error: Parent directory '$TARGET_PARENT' does not exist.${NC}"
    exit 1
fi
if [ ! -w "$TARGET_PARENT" ] && [ ! -w "$TARGET_DIR" ]; then
    echo -e "${RED}Error: Permission denied - cannot write to '$TARGET_DIR'${NC}"
    echo ""
    echo "  Solutions:"
    echo "    1) Run with sudo:    sudo $0 $*"
    echo "    2) Use --local:      $0 --local    (installs to ./registry-center)"
    echo "    3) Specify a path:   $0 --target ~/registry-center"
    echo ""
    exit 1
fi

# --- Step 3: Extract files ---
echo -e "${CYAN}[3/7] Extracting files to $TARGET_DIR ...${NC}"
if [ -d "$TARGET_DIR" ] && [ "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]; then
    echo -e "${YELLOW}  Warning: Target directory is not empty.${NC}"
    read -p "  Overwrite? (y/n): " choice
    if [ "$choice" != "y" ] && [ "$choice" != "Y" ]; then
        echo "Installation cancelled."
        exit 0
    fi
fi

mkdir -p "$TARGET_DIR"

# Find the archive line marker
ARCHIVE_LINE=$(awk '/^__ARCHIVE_BELOW__$/{print NR + 1; exit 0; }' "$0")
tail -n +"$ARCHIVE_LINE" "$0" | tar xz -C "$TARGET_DIR"
echo -e "${GREEN}  Files extracted successfully.${NC}"

# --- Step 4: Create virtual environment ---
echo -e "${CYAN}[4/7] Creating Python virtual environment...${NC}"
VENV_DIR="$TARGET_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}  Existing venv found, recreating...${NC}"
    rm -rf "$VENV_DIR"
fi
$PYTHON_CMD -m venv "$VENV_DIR"
echo -e "${GREEN}  Virtual environment created at $VENV_DIR${NC}"

# --- Step 5: Install dependencies offline ---
echo -e "${CYAN}[5/7] Installing Python dependencies (offline)...${NC}"
VENV_PIP="$VENV_DIR/bin/pip"
WHEELS_ARCH="$TARGET_DIR/wheels/$ARCH"
WHEELS_COMMON="$TARGET_DIR/wheels/common"
REQ_FILE="$TARGET_DIR/requirements.txt"

$VENV_PIP install --upgrade pip --no-index --find-links "$WHEELS_COMMON" 2>/dev/null || true
$VENV_PIP install --no-index \
    --find-links "$WHEELS_ARCH" \
    --find-links "$WHEELS_COMMON" \
    -r "$REQ_FILE"

echo -e "${GREEN}  Dependencies installed successfully.${NC}"

# --- Step 6: Create runtime directories ---
echo -e "${CYAN}[6/7] Creating runtime directories...${NC}"
mkdir -p "$TARGET_DIR/log"
mkdir -p "$TARGET_DIR/run"
mkdir -p "$TARGET_DIR/data"
mkdir -p "$TARGET_DIR/etc/ssl"
mkdir -p "$TARGET_DIR/etc/sign_cert"
chmod +x "$TARGET_DIR/bin/"*.sh 2>/dev/null || true
echo -e "${GREEN}  Runtime directories created.${NC}"

# --- Step 7: Interactive initialization ---
echo -e "${CYAN}[7/7] Starting interactive configuration...${NC}"
echo ""

if [ "$SKIP_INIT" = "false" ]; then
    cd "$TARGET_DIR"
    export OPENSSL_CONF="$TARGET_DIR/etc/conf/custom_openssl.cnf"
    "$VENV_DIR/bin/python" -m agent_registry.init
else
    echo -e "${YELLOW}  Skipped interactive initialization (--skip-init).${NC}"
    echo "  Run later: cd $TARGET_DIR && ./venv/bin/python -m agent_registry.init"
fi

# --- Optional: Install systemd service ---
if [ "$INSTALL_SERVICE" = "true" ]; then
    echo ""
    echo -e "${CYAN}Installing systemd service...${NC}"
    if [ "$(id -u)" -ne 0 ]; then
        echo -e "${YELLOW}  Warning: systemd installation requires root. Skipping.${NC}"
        echo "  Run later: sudo $TARGET_DIR/bin/install_service.sh install"
    else
        "$TARGET_DIR/bin/install_service.sh" install --dir="$TARGET_DIR" --python="$VENV_DIR/bin/python3" --no-deps
    fi
fi

# --- Done ---
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}   Installation Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Install directory: $TARGET_DIR"
echo "  Python venv:       $VENV_DIR"
echo ""
echo "  Quick start:"
echo "    cd $TARGET_DIR"
echo "    ./bin/start.sh"
echo ""
echo "  Systemd service:"
echo "    sudo ./bin/install_service.sh install"
echo "    sudo systemctl start registry-center"
echo ""
echo "  Re-run configuration:"
echo "    cd $TARGET_DIR && ./venv/bin/python -m agent_registry.init"
echo ""

exit 0
__ARCHIVE_BELOW__
'''


# ---------------------------------------------------------------------------
# Build functions
# ---------------------------------------------------------------------------


def parse_requirements(req_file: Path) -> list[str]:
    """Parse requirements.txt, excluding test dependencies."""
    lines = []
    with open(req_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Extract package name (before any version specifier)
            pkg_name = line.split(">=")[0].split("~=")[0].split("==")[0].split("[")[0].strip()
            if pkg_name.lower() in TEST_DEPS:
                continue
            lines.append(line)
    return lines


def download_wheels(requirements: list[str], output_dir: Path, arch: str) -> bool:
    """Download platform-specific wheels for a given architecture."""
    print(f"\n  Downloading wheels for {arch}...")
    output_dir.mkdir(parents=True, exist_ok=True)

    platforms = PLATFORMS[arch]
    cmd = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(output_dir),
        "--python-version", PYTHON_VERSION_TAG,
        "--only-binary=:all:",
        "--implementation", "cp",
        "--abi", f"cp{PYTHON_VERSION_TAG}",
    ]
    for p in platforms:
        cmd.extend(["--platform", p])
    cmd.extend(requirements)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Retry without abi constraint for pure-python packages
        print(f"    First pass done, retrying remaining packages...")
        cmd_fallback = [
            sys.executable, "-m", "pip", "download",
            "--dest", str(output_dir),
            "--python-version", PYTHON_VERSION_TAG,
            "--only-binary=:all:",
        ]
        for p in platforms:
            cmd_fallback.extend(["--platform", p])
        cmd_fallback.extend(requirements)
        result2 = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if result2.returncode != 0:
            print(f"    Warning: Some packages may not have been downloaded for {arch}")
            print(f"    {result2.stderr[:500]}")
            return False
    return True


def download_common_wheels(requirements: list[str], output_dir: Path) -> bool:
    """Download pure Python (architecture-independent) wheels."""
    print(f"\n  Downloading common (pure Python) wheels...")
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(output_dir),
        "--no-deps",
        "--only-binary=:all:",
        "--platform", "any",
        "--python-version", PYTHON_VERSION_TAG,
        "--implementation", "cp",
    ]
    cmd.extend(requirements)
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Also try without platform constraint for pure python
    cmd2 = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(output_dir),
        "--no-deps",
        "--only-binary=:all:",
    ]
    cmd2.extend(requirements)
    subprocess.run(cmd2, capture_output=True, text=True)

    return True


def should_exclude(path: Path) -> bool:
    """Check if a path should be excluded from the package."""
    parts = path.parts
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def collect_project_files(staging_dir: Path):
    """Copy project files to the staging directory."""
    print("\n  Collecting project files...")

    for dir_rel in INCLUDE_DIRS:
        src_dir = PROJECT_ROOT / dir_rel
        if not src_dir.exists():
            print(f"    Warning: {dir_rel} not found, skipping")
            continue
        dst_dir = staging_dir / dir_rel
        dst_dir.mkdir(parents=True, exist_ok=True)

        for item in src_dir.rglob("*"):
            rel = item.relative_to(src_dir)
            if should_exclude(rel):
                continue
            dst_item = dst_dir / rel
            if item.is_dir():
                dst_item.mkdir(parents=True, exist_ok=True)
            else:
                dst_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst_item)

    # Copy requirements.txt (filtered)
    req_file = PROJECT_ROOT / "requirements.txt"
    if req_file.exists():
        requirements = parse_requirements(req_file)
        dst_req = staging_dir / "requirements.txt"
        with open(dst_req, "w", encoding="utf-8") as f:
            f.write("# Registry Center production dependencies\n")
            for line in requirements:
                f.write(line + "\n")

    print(f"    Project files collected.")


def build_tarball(staging_dir: Path, tarball_path: Path):
    """Create a tar.gz from the staging directory."""
    print(f"\n  Creating tarball...")
    with tarfile.open(tarball_path, "w:gz") as tar:
        for item in staging_dir.iterdir():
            tar.add(item, arcname=item.name)
    size_mb = tarball_path.stat().st_size / (1024 * 1024)
    print(f"    Tarball created: {size_mb:.1f} MB")


def create_run_file(installer_script: str, tarball_path: Path, output_path: Path):
    """Combine installer script and tarball into a self-extracting .run file."""
    print(f"\n  Creating self-extracting installer...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as out:
        # Write shell header
        out.write(installer_script.encode("utf-8"))
        # Append binary tarball
        with open(tarball_path, "rb") as tar:
            shutil.copyfileobj(tar, out)

    # Make executable
    os.chmod(output_path, 0o755)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"    Installer created: {output_path.name} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Build Registry Center offline deployment package"
    )
    parser.add_argument(
        "--version", default=DEFAULT_VERSION,
        help=f"Package version (default: {DEFAULT_VERSION})"
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory (default: <project>/dist)"
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Skip wheel download (use existing wheels in build directory)"
    )
    args = parser.parse_args()

    version = args.version
    output_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "dist"
    output_file = output_dir / f"registry-center-{version}-linux-universal.run"

    print("=" * 60)
    print("  Registry Center Package Builder")
    print(f"  Version: {version}")
    print(f"  Output:  {output_file}")
    print("=" * 60)

    # Check build environment
    if platform.system() != "Linux" and platform.system() != "Windows":
        print(f"Warning: Building on {platform.system()}, target is Linux.")

    # Parse requirements
    req_file = PROJECT_ROOT / "requirements.txt"
    if not req_file.exists():
        print("Error: requirements.txt not found in project root.")
        sys.exit(1)
    requirements = parse_requirements(req_file)
    print(f"\n  Production dependencies ({len(requirements)} packages):")
    for r in requirements:
        print(f"    - {r}")

    # Use a temporary build directory
    build_dir = PROJECT_ROOT / "dist" / "build_tmp"
    staging_dir = build_dir / "payload"

    try:
        # Clean previous build
        if build_dir.exists():
            shutil.rmtree(build_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Download wheels
        if not args.skip_download:
            print("\n[Step 1/4] Downloading Python wheels...")
            wheels_dir = staging_dir / "wheels"

            success_x86 = download_wheels(requirements, wheels_dir / "x86_64", "x86_64")
            success_arm = download_wheels(requirements, wheels_dir / "aarch64", "aarch64")
            download_common_wheels(requirements, wheels_dir / "common")

            if not success_x86 or not success_arm:
                print("\n  Warning: Some wheels may be missing. The installer will")
                print("  attempt installation with available packages.")
        else:
            print("\n[Step 1/4] Skipping wheel download (--skip-download)")
            wheels_dir = staging_dir / "wheels"
            if not wheels_dir.exists():
                print("  Error: No wheels directory found. Run without --skip-download first.")
                sys.exit(1)

        # Step 2: Collect project files
        print("\n[Step 2/4] Collecting project files...")
        collect_project_files(staging_dir)

        # Step 3: Create tarball
        print("\n[Step 3/4] Creating package archive...")
        tarball_path = build_dir / "payload.tar.gz"
        build_tarball(staging_dir, tarball_path)

        # Step 4: Create self-extracting .run file
        print("\n[Step 4/4] Building self-extracting installer...")
        create_run_file(INSTALLER_SCRIPT, tarball_path, output_file)

        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL")
        print("=" * 60)
        print(f"\n  Output: {output_file}")
        print(f"\n  Usage on target machine:")
        print(f"    chmod +x {output_file.name}")
        print(f"    ./{output_file.name} --target /opt/registry-center")
        print()

    finally:
        # Cleanup build directory
        if build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
