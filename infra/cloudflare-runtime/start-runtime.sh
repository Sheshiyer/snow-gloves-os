#!/bin/sh
set -eu

if [ -z "${STORAGE_ENCRYPTION_KEY:-}" ]; then
  echo "STORAGE_ENCRYPTION_KEY must be set" >&2
  exit 1
fi

if [ "${DATA_DIR}" != "/data" ]; then
  echo "DATA_DIR must be /data" >&2
  exit 1
fi

if [ -L "${DATA_DIR}" ]; then
  echo "DATA_DIR must not be a symlink" >&2
  exit 1
fi

if [ ! -d "${DATA_DIR}" ] || [ ! -w "${DATA_DIR}" ]; then
  echo "DATA_DIR must be a writable directory" >&2
  exit 1
fi

dir_owner=$(stat -c '%u' "${DATA_DIR}")
if [ "${dir_owner}" != "$(id -u)" ]; then
  echo "DATA_DIR must be owned by current user" >&2
  exit 1
fi

exec node /usr/local/lib/node_modules/omniroute/dist/server.js
