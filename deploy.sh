#!/usr/bin/env bash
set -euo pipefail

# Deploys index.html to the Ring the Bull page on mampersat.com.
S3_PATH="s3://mampersat.com/ringthebull/"

aws s3 cp index.html "$S3_PATH" \
  --acl public-read \
  --content-type "text/html" \
  --cache-control "no-cache"

echo "Deployed to https://mampersat.com/ringthebull/index.html"
