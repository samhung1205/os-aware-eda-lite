#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${DATA_DIR:-data/raw/images}"
ZIP_PATH="${ZIP_PATH:-data/raw/coco128.zip}"
COCO128_URL="${COCO128_URL:-https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip}"

mkdir -p "$DATA_DIR"

if [[ ! -f "$ZIP_PATH" ]]; then
  mkdir -p "$(dirname "$ZIP_PATH")"
  curl -L "$COCO128_URL" -o "$ZIP_PATH"
fi

unzip -q -o "$ZIP_PATH" -d "$DATA_DIR"

echo "COCO128 images are available under $DATA_DIR/coco128/images/train2017"
