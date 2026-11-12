#!/bin/sh
set -eu
nginx
# Docker restart policies do not enforce Compose dependency order after VM boot.
until node /opt/postiz-readiness.cjs; do sleep 5; done
pm2 ping
pnpm --filter ./apps/orchestrator run pm2
pnpm --filter ./apps/backend run pm2
pnpm --filter ./apps/frontend run pm2
pm2 logs
