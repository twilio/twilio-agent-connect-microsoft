#!/bin/bash
# Build wheels for private dependencies
# This script clones the repos and builds wheels needed for Docker deployment

set -e

echo "Building wheels for tac-azure and twilio-agent-connect..."

# Configuration
TAC_AZURE_REPO="https://github.com/twilio-innovation/azure-twilio-agent-connect-python.git"
TAC_AZURE_COMMIT="0869192"

TAC_REPO="https://github.com/twilio-innovation/twilio-agent-connect-python.git"
TAC_COMMIT="436ff9b"

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
python3 -m pip wheel --no-deps . -w "$WHEELS_DIR" --quiet
cd -

echo ""
echo "3/4 Cloning twilio-agent-connect repository..."
git clone "$TAC_REPO" "$BUILD_DIR/tac" --quiet
cd "$BUILD_DIR/tac"
git checkout "$TAC_COMMIT" --quiet

echo "4/4 Building twilio-agent-connect wheel..."
python3 -m pip wheel --no-deps . -w "$WHEELS_DIR" --quiet
cd -

# Clean up
rm -rf "$BUILD_DIR"

echo ""
echo "Wheels built successfully!"
echo ""
ls -lh "$WHEELS_DIR"/*.whl | awk '{print "  " $9, "(" $5 ")"}'
echo ""
echo "You can now build the Docker image with: docker build -t tac-agent-framework:latest -f Dockerfile ."
