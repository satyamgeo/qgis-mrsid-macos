#!/bin/bash
# =============================================================================
# build_pkg.sh — Build MrSID-QGIS-Installer.pkg  (v1.0.4)
#
# Usage:
#   chmod +x build_pkg.sh
#   ./build_pkg.sh
#
# Output:
#   dist/MrSID-QGIS-Installer.pkg
#
# Requirements:
#   - macOS with Xcode Command Line Tools  (pkgbuild, productbuild)
#   - Run from the project root directory
# =============================================================================

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PKG_ID="com.satyamgeo.mrsid-qgis-installer"
VERSION="1.0.5"
PKG_NAME="MrSID-QGIS-Installer"
DIST_DIR="dist"
BUILD_DIR="build_tmp"

echo "============================================================"
echo " Building $PKG_NAME v$VERSION"
echo "============================================================"

# ── Verify we're in the right directory ──────────────────────────────────────
if [ ! -f "main.py" ] || [ ! -d "resources" ] || [ ! -d "installer" ]; then
    echo "ERROR: Run this script from the MrSIDInstaller project root."
    exit 1
fi

# ── Verify required resources exist ──────────────────────────────────────────
if [ ! -f "resources/gdalplugins/gdal_MrSID.so" ]; then
    echo "ERROR: resources/gdalplugins/gdal_MrSID.so not found."
    exit 1
fi
if [ ! -d "resources/dylibs" ]; then
    echo "ERROR: resources/dylibs/ not found."
    exit 1
fi

# ── Clean build directories ───────────────────────────────────────────────────
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR/scripts"
mkdir -p "$BUILD_DIR/payload/lib"
mkdir -p "$BUILD_DIR/payload/gdalplugins"
mkdir -p "$DIST_DIR"

# ── Copy payload (resources bundled into the pkg) ─────────────────────────────
echo "Copying resources to payload..."
cp -r resources/gdalplugins/gdal_MrSID.so \
      "$BUILD_DIR/payload/gdalplugins/"
cp -r resources/dylibs/. \
      "$BUILD_DIR/payload/lib/"

# ── Copy postinstall script ───────────────────────────────────────────────────
echo "Copying installer scripts..."
cp installer/postinstall "$BUILD_DIR/scripts/postinstall"
chmod +x "$BUILD_DIR/scripts/postinstall"

# ── Build component package ───────────────────────────────────────────────────
echo "Running pkgbuild..."
pkgbuild \
    --root "$BUILD_DIR/payload" \
    --scripts "$BUILD_DIR/scripts" \
    --identifier "$PKG_ID" \
    --version "$VERSION" \
    --install-location "/Library/Application Support/MrSID-QGIS" \
    "$DIST_DIR/${PKG_NAME}-component.pkg"

# ── Create distribution XML ───────────────────────────────────────────────────
cat > "$BUILD_DIR/distribution.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>Mac MrSID Support Installer</title>
    <welcome file="welcome.html" mime-type="text/html"/>
    <background file="background.png" mime-type="image/png" alignment="center" scaling="proportional"/>
    <options customize="never" require-scripts="true" hostArchitectures="x86_64,arm64"/>
    <domains enable_anywhere="false" enable_currentUserHome="false" enable_localSystem="true"/>
    <choices-outline>
        <line choice="default">
            <line choice="$PKG_ID"/>
        </line>
    </choices-outline>
    <choice id="default"/>
    <choice id="$PKG_ID" visible="false">
        <pkg-ref id="$PKG_ID"/>
    </choice>
    <pkg-ref id="$PKG_ID" version="$VERSION" onConclusion="none">
        ${PKG_NAME}-component.pkg
    </pkg-ref>
</installer-gui-script>
EOF

# ── Create welcome HTML ───────────────────────────────────────────────────────
cat > "$BUILD_DIR/welcome.html" <<'EOF'
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, sans-serif; padding: 20px;">
<h2>Mac MrSID Support Installer v1.0.5</h2>
<p>This installer adds <strong>MrSID (.sid) raster format</strong> support to QGIS on macOS.</p>
<p>Compatible with:</p>
<ul>
  <li>QGIS 3.0 – 4.x</li>
  <li>macOS Intel (x86_64) and Apple Silicon (arm64)</li>
 </ul>
<p>After installation, <strong>restart QGIS</strong> to activate MrSID support.</p>
<p>If installation fails, check the log at:<br>
<code>/tmp/mrsid_installer.log</code></p>
</body>
</html>
EOF

# ── Build final distribution package ─────────────────────────────────────────
echo "Running productbuild..."
productbuild \
    --distribution "$BUILD_DIR/distribution.xml" \
    --package-path "$DIST_DIR" \
    --resources "$BUILD_DIR" \
    "$DIST_DIR/${PKG_NAME}.pkg"

# ── Remove intermediate component pkg ────────────────────────────────────────
rm -f "$DIST_DIR/${PKG_NAME}-component.pkg"

echo ""
echo "============================================================"
echo " ✅ Build COMPLETE"
echo " Output: $DIST_DIR/${PKG_NAME}.pkg"
echo " Size: $(du -sh "$DIST_DIR/${PKG_NAME}.pkg" | cut -f1)"
echo "============================================================"
echo ""
echo "To test the installer locally:"
echo "  sudo installer -pkg $DIST_DIR/${PKG_NAME}.pkg -target /"
echo ""
echo "Upload this file to your GitHub Release as:"
echo "  ${PKG_NAME}.pkg"
