#!/bin/bash
# Build wheels for private dependencies
# This script clones the repos and builds wheels needed for Docker deployment

set -e

# Find a supported Python (3.10-3.13), prefer highest
PYTHON=""
for ver in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$ver" &>/dev/null; then
        PYTHON="$ver"
        break
    fi
done
# Fall back to python3 if it's in the supported range
if [ -z "$PYTHON" ] && command -v python3 &>/dev/null; then
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "$PY_MINOR" -ge 10 ] && [ "$PY_MINOR" -le 13 ]; then
        PYTHON="python3"
    fi
fi
if [ -z "$PYTHON" ]; then
    echo "Error: No supported Python (3.10-3.13) found. Install one with: brew install python@3.13"
    exit 1
fi

# On macOS, Homebrew Python may be compiled against Homebrew's libexpat but
# at runtime loads the older system /usr/lib/libexpat.1.dylib (missing newer symbols).
# Fix by putting Homebrew's expat on the library path.
if command -v brew &>/dev/null; then
    EXPAT_PREFIX="$(brew --prefix expat 2>/dev/null || true)"
    if [ -n "$EXPAT_PREFIX" ] && [ -d "$EXPAT_PREFIX/lib" ]; then
        export DYLD_LIBRARY_PATH="${EXPAT_PREFIX}/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
    fi
fi

echo "Using $($PYTHON --version) ($PYTHON)"
echo "Building wheels for tac-azure and twilio-agent-connect..."

# Configuration
TAC_AZURE_REPO="https://github.com/twilio/azure-twilio-agent-connect-python.git"
TAC_AZURE_COMMIT="95ebd2e"

TAC_REPO="https://github.com/twilio/twilio-agent-connect-python.git"
TAC_COMMIT="a79515d11dd04e61e34036f781f3f2aad0ee0beb"

WHEELS_DIR="$(pwd)/wheels"
BUILD_DIR="/tmp/tac-wheels-build"

# Create wheels directory
mkdir -p "$WHEELS_DIR"

# Clean build directory
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo ""
echo "1/4 Cloning tac-azure repository..."
git clone "$TAC_AZURE_REPO" "$BUILD_DIR/tac-azure" --quiet
cd "$BUILD_DIR/tac-azure"
git checkout "$TAC_AZURE_COMMIT" --quiet

echo "2/4 Building tac-azure wheel..."
$PYTHON -m pip wheel --no-deps . -w "$WHEELS_DIR" --quiet
cd -

echo ""
echo "3/4 Cloning twilio-agent-connect repository..."
git clone "$TAC_REPO" "$BUILD_DIR/tac" --quiet
cd "$BUILD_DIR/tac"
git checkout "$TAC_COMMIT" --quiet

echo "4/4 Building twilio-agent-connect wheel..."
$PYTHON -m pip wheel --no-deps . -w "$WHEELS_DIR" --quiet
cd -

# Clean up
rm -rf "$BUILD_DIR"

echo ""
echo "Wheels built successfully!"
echo ""
ls -lh "$WHEELS_DIR"/*.whl | awk '{print "  " $9, "(" $5 ")"}'
echo ""
echo "You can now build the Docker image with: docker build -t tac-voice-live:latest -f Dockerfile ."
