#!/usr/bin/env bash
set -euo pipefail

# Deploys the Ring the Bull site (app shell + PWA assets) to mampersat.com.
S3_PATH="s3://mampersat.com/ringthebull/"
CLOUDFRONT_DISTRIBUTION_ID="E1GFON8TFLZUQB"
BUILD_HASH="$(git rev-parse --short HEAD)"

# index.html carries a "local-dev" placeholder for the footer build hash;
# stamp the real commit hash into a temp copy rather than the tracked file.
TMP_HTML="$(mktemp)"
sed "s/local-dev/$BUILD_HASH/" index.html > "$TMP_HTML"
aws s3 cp "$TMP_HTML" "${S3_PATH}index.html" \
  --acl public-read \
  --content-type "text/html" \
  --cache-control "no-cache"
rm -f "$TMP_HTML"

aws s3 sync . "$S3_PATH" \
  --acl public-read \
  --exclude "*" \
  --include "manifest.json" \
  --include "sw.js" \
  --include "icons/*" \
  --include "vendor/*" \
  --cache-control "no-cache"

echo "Deployed to https://mampersat.com/ringthebull/index.html (build $BUILD_HASH)"

aws cloudfront create-invalidation \
  --distribution-id "$CLOUDFRONT_DISTRIBUTION_ID" \
  --paths "/ringthebull/*" >/dev/null

echo "Invalidated CloudFront cache for /ringthebull/*"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
(
  cd "$SCRIPT_DIR/scripts"
  [ -d node_modules ] || npm install --no-audit --no-fund >/dev/null
  node screenshot.js
)
echo "Regenerated images/screenshot.png for the README"
