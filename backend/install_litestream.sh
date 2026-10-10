#!/usr/bin/env bash
# Tải Litestream (công cụ sao lưu SQLite, mã nguồn mở) vào backend/bin khi build trên Render.
set -eu
cd "$(dirname "$0")"
VERSION=v0.3.13
mkdir -p bin
curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/${VERSION}/litestream-${VERSION}-linux-amd64.tar.gz" | tar -xz -C bin litestream
chmod +x bin/litestream
./bin/litestream version
