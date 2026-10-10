#!/usr/bin/env bash
# Khởi động backend trên Render.
# Có cấu hình Litestream (LITESTREAM_BUCKET...) thì: lấy lại database từ bản sao lưu, chạy sao lưu liên tục ở nền,
# rồi chạy app. Sao lưu lỗi cũng không làm app ngừng chạy.
set -u
cd "$(dirname "$0")"
DB="${DATABASE_PATH:-./data/dongdieu.db}"
mkdir -p "$(dirname "$DB")"
LS=./bin/litestream
if [ -n "${LITESTREAM_BUCKET:-}" ] && [ -x "$LS" ]; then
  export DATABASE_PATH="$DB"
  if [ ! -f "$DB" ]; then
    echo "[start] Khôi phục database từ bản sao lưu..."
    "$LS" restore -config litestream.yml -if-replica-exists "$DB" || echo "[start] Không khôi phục được, chạy với database mới."
  fi
  "$LS" replicate -config litestream.yml &
  echo "[start] Đang sao lưu liên tục lên ${LITESTREAM_BUCKET}."
else
  echo "[start] Chưa cấu hình sao lưu (LITESTREAM_BUCKET trống): dữ liệu sẽ mất khi server khởi động lại."
fi
# Mặc định cho bản chạy thật: AI chia việc dùng danh mục chuẩn Data 1, coach v2, vòng đo mỗi giờ.
# Đặt biến cùng tên trên Render thì giá trị trên Render được dùng.
export PLAN_LLM_PROVIDER="${PLAN_LLM_PROVIDER:-openai_compatible}"
export PLAN_CATALOG_PATH="${PLAN_CATALOG_PATH:-data/concepts/plan_catalog.json}"
export PLAN_COACH_V2_ENABLED="${PLAN_COACH_V2_ENABLED:-true}"
export MATCH_RERANK_ENABLED="${MATCH_RERANK_ENABLED:-true}"
export LOOP_INTERVAL_MINUTES="${LOOP_INTERVAL_MINUTES:-60}"
# Bạn học mẫu + 2 tài khoản thử cho demo. Khi chạy thực nghiệm với người thật: đặt DEMO_MODE=false trên Render.
export DEMO_MODE="${DEMO_MODE:-true}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
