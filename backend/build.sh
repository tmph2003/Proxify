#!/usr/bin/env bash
# ======================================================================
# Proxify Build Script — Nuitka Standalone Native .exe
# ======================================================================
# Compiles Proxify Core + optional Private Extensions
# + React SPA Dashboard into a single encrypted/native standalone .exe
# using Nuitka (Python -> C -> x86_64 machine code).
#
# Usage (Git Bash):
#   cd /c/Users/Administrator/Desktop/MyAim/Proxify/backend
#   bash build.sh
# ======================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================="
echo "  Proxify Nuitka Native Build"
echo "=============================================="

# 1. Build React Frontend SPA (temporarily staging private extension pages/hooks/styles if present)
if [ -d "$REPO_ROOT/frontend" ]; then
    echo "[1/4] Building React Dashboard SPA..."
    STAGED_FILES=()
    cleanup_staged_frontend() {
        for f in "${STAGED_FILES[@]+"${STAGED_FILES[@]}"}"; do
            rm -f "$f"
        done
        rmdir "$REPO_ROOT/frontend/src/styles" 2>/dev/null || true
    }
    trap cleanup_staged_frontend EXIT

    for sub in pages hooks styles; do
        if [ -d "$REPO_ROOT/private/frontend/$sub" ]; then
            mkdir -p "$REPO_ROOT/frontend/src/$sub"
            for src_file in "$REPO_ROOT/private/frontend/$sub/"*; do
                [ -f "$src_file" ] || continue
                dest_file="$REPO_ROOT/frontend/src/$sub/$(basename "$src_file")"
                cp -f "$src_file" "$dest_file"
                STAGED_FILES+=("$dest_file")
            done
        fi
    done

    (
        cd "$REPO_ROOT/frontend"
        npm run build
    )
    cleanup_staged_frontend
    trap - EXIT
fi

# 2. Ensure Nuitka is installed
echo "[2/4] Checking Nuitka installation..."
if ! python -m nuitka --version >/dev/null 2>&1; then
    pip install nuitka ordered-set
fi

# 3. Compile Python -> Native C -> Single Onefile .exe
echo "[3/4] Compiling with Nuitka (ccache incremental enabled)..."
if tasklist //FI "IMAGENAME eq proxify.exe" 2>/dev/null | grep -qi "proxify.exe"; then
    echo "      Stopping running proxify.exe to release file lock..."
    taskkill //F //IM proxify.exe >/dev/null 2>&1 || true
    sleep 1
fi
if command -v cygpath >/dev/null 2>&1; then
    WIN_SCRIPT_DIR="$(cygpath -w "$SCRIPT_DIR")"
    WIN_EXT_DIR="$(cygpath -w "$REPO_ROOT/private/extensions")"
    WIN_SHARED_DIR="$(cygpath -w "$REPO_ROOT/private/shared")"
    export PYTHONPATH="${WIN_SCRIPT_DIR};${WIN_EXT_DIR};${WIN_SHARED_DIR}"
else
    export PYTHONPATH="${SCRIPT_DIR}:${REPO_ROOT}/private/extensions:${REPO_ROOT}/private/shared"
fi

if [ -f "$REPO_ROOT/assets/logo.png" ] && [ ! -f "$REPO_ROOT/assets/logo.ico" ]; then
    echo "      Generating multi-size assets/logo.ico from assets/logo.png..."
    python -c "from PIL import Image; im = Image.open(r'$REPO_ROOT/assets/logo.png').convert('RGBA'); im.save(r'$REPO_ROOT/assets/logo.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])" || true
fi

NUITKA_EXTRA_ARGS=()
COMPILED_PKGS=()
COMPILED_MANIFEST="$SCRIPT_DIR/proxify/_compiled_extensions.py"
cleanup_build_manifest() {
    rm -f "$COMPILED_MANIFEST"
}
trap cleanup_build_manifest EXIT

if [ -d "$REPO_ROOT/private/extensions" ]; then
    for ext_dir in "$REPO_ROOT/private/extensions"/*/; do
        [ -d "$ext_dir" ] || continue
        ext_name="$(basename "$ext_dir")"
        [[ "$ext_name" == .* || "$ext_name" == _* ]] && continue
        NUITKA_EXTRA_ARGS+=(--include-package="$ext_name")
        COMPILED_PKGS+=("$ext_name")
    done
fi

if [ ${#COMPILED_PKGS[@]} -gt 0 ]; then
    PY_TUPLE_ITEMS=""
    for pkg in "${COMPILED_PKGS[@]}"; do
        PY_TUPLE_ITEMS+="\"$pkg\", "
    done
    printf '# Auto-generated at build time by build.sh\nCOMPILED_EXTENSION_PACKAGES = (%s)\n' "$PY_TUPLE_ITEMS" > "$COMPILED_MANIFEST"
fi

if [ -d "$REPO_ROOT/private/shared" ]; then
    for shared_mod in "$REPO_ROOT/private/shared"/*.py; do
        [ -f "$shared_mod" ] || continue
        mod_name="$(basename "$shared_mod" .py)"
        [ "$mod_name" = "__init__" ] && continue
        NUITKA_EXTRA_ARGS+=(--include-module="$mod_name")
    done
fi
if [ -d "$REPO_ROOT/frontend/dist" ]; then
    NUITKA_EXTRA_ARGS+=(--include-data-dir="$REPO_ROOT/frontend/dist=proxify/frontend_dist")
fi
if [ -f "$REPO_ROOT/assets/logo.ico" ]; then
    if command -v cygpath >/dev/null 2>&1; then
        WIN_ICO_PATH="$(cygpath -w "$REPO_ROOT/assets/logo.ico")"
    else
        WIN_ICO_PATH="$REPO_ROOT/assets/logo.ico"
    fi
    NUITKA_EXTRA_ARGS+=(--windows-icon-from-ico="$WIN_ICO_PATH" --include-data-files="$WIN_ICO_PATH=proxify/logo.ico")
fi

python -m nuitka \
    --standalone \
    --onefile \
    --remove-output \
    --assume-yes-for-downloads \
    --output-filename=proxify.exe \
    --include-package=proxify \
    --include-package=aiohttp \
    --include-package=aiosqlite \
    --include-package=mitmproxy \
    --include-package=curl_cffi \
    --include-package=dotenv \
    "${NUITKA_EXTRA_ARGS[@]}" \
    --nofollow-import-to=psycopg2 \
    --nofollow-import-to=asyncpg \
    --nofollow-import-to=pytest \
    --nofollow-import-to=tests \
    --nofollow-import-to=playwright \
    --nofollow-import-to=matplotlib \
    --nofollow-import-to=numpy \
    --nofollow-import-to=PIL \
    --nofollow-import-to=jedi \
    --nofollow-import-to=tkinter \
    --nofollow-import-to=scipy \
    --nofollow-import-to=pandas \
    --windows-console-mode=disable \
    --company-name="tmph2003" \
    --product-name="Proxify" \
    --file-version=2.0.0 \
    --product-version=2.0.0 \
    --file-description="Proxify - Request capture and interception tool" \
    proxify/__main__.py

# 4. Verify output
echo "[4/4] Verifying build..."
if [ -f "proxify.exe" ]; then
    echo "Build successful: $SCRIPT_DIR/proxify.exe"
    ls -lh proxify.exe
else
    echo "Build failed: proxify.exe not found"
    exit 1
fi
