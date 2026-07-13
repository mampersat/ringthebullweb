#!/usr/bin/env bash
set -euo pipefail

# Deploys the Ring the Bull site (app shell + PWA assets) to mampersat.com.
S3_PATH="s3://mampersat.com/ringthebull/"
CLOUDFRONT_DISTRIBUTION_ID="E1GFON8TFLZUQB"

aws s3 sync . "$S3_PATH" \
  --acl public-read \
  --exclude "*" \
  --include "index.html" \
  --include "manifest.json" \
  --include "sw.js" \
  --include "icons/*" \
  --cache-control "no-cache"

echo "Deployed to https://mampersat.com/ringthebull/index.html"

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
