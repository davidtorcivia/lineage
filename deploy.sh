#!/bin/sh
# Ship the viewer and its exported data to a Docker host over ssh and (re)start the container:  sh deploy.sh
# Set DEPLOY_HOST (an ssh host) and optionally DEPLOY_DIR, in the environment or a local .env (not committed).
# A local compose.override.yaml (not committed) is shipped too, for host-specific ports etc.
# The server's own .env (LINEAGE_PASSWORD=...) lives only on that host.
set -e
cd "$(dirname "$0")"
[ -f .env ] && . ./.env
HOST=${DEPLOY_HOST:?set DEPLOY_HOST}
DIR=${DEPLOY_DIR:-/srv/lineage}
tar cf - serve.py login.html Dockerfile compose.yaml $(ls compose.override.yaml 2>/dev/null) | ssh "$HOST" "mkdir -p $DIR/public && tar xf - -C $DIR"
tar cf - index.html tree.json places.json bios art favicon.svg apple-touch-icon.png og.png | ssh "$HOST" "tar xf - -C $DIR/public && chmod -R a+rX $DIR/public"   # in place: the container's mount keeps pointing at this folder
ssh "$HOST" "cd $DIR && docker compose up -d --build && docker compose ps"
