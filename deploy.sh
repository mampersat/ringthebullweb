#!/usr/bin/env bash
set -euo pipefail

# Deploys the Ring the Bull site (app shell + PWA assets) to mampersat.com.
S3_PATH="s3://mampersat.com/ringthebull/"

aws s3 sync . "$S3_PATH" \
  --acl public-read \
  --exclude "*" \
  --include "index.html" \
  --include "manifest.json" \
  --include "sw.js" \
  --include "icons/*" \
  --cache-control "no-cache"

echo "Deployed to https://mampersat.com/ringthebull/index.html"
