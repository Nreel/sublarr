#!/bin/bash
# Build the current tree locally and ship the image to a test server over SSH.
# Config lives in scripts/deploy.local.env (gitignored); copy
# scripts/deploy.local.env.example to start. Environment variables win over the file.
#
# Usage:  ./scripts/deploy.sh [--dry-run]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$SCRIPT_DIR/deploy.local.env"

DRY_RUN=0
for arg in "$@"; do
  [ "$arg" = "--dry-run" ] && DRY_RUN=1
done

if [ -f "$CONFIG_FILE" ]; then
  # Only KEY=value lines, no sourcing (avoids executing the file).
  while IFS='=' read -r key value; do
    case "$key" in
      [A-Za-z_][A-Za-z0-9_]*) value="${value%\"}"; value="${value#\"}"; export "$key=$value" ;;
    esac
  done < "$CONFIG_FILE"
else
  echo "Warning: no scripts/deploy.local.env - copy scripts/deploy.local.env.example and set DEPLOY_HOST." >&2
fi

DEPLOY_HOST="${DEPLOY_HOST:-}"
if [ -z "$DEPLOY_HOST" ]; then
  echo "DEPLOY_HOST is required (deploy.local.env or env var)." >&2
  exit 1
fi

DEPLOY_IMAGE="${DEPLOY_IMAGE:-sublarr}"
DEPLOY_OVERWRITE="${DEPLOY_OVERWRITE:-true}"
DEPLOY_PLATFORM="${DEPLOY_PLATFORM:-}"
DEPLOY_REMOTE_CMD="${DEPLOY_REMOTE_CMD:-}"
DEPLOY_COMPOSE_DIR="${DEPLOY_COMPOSE_DIR:-}"
if [ -z "$DEPLOY_REMOTE_CMD" ] && [ -n "$DEPLOY_COMPOSE_DIR" ]; then
  # Container pins its image ID at creation, so a loaded new image only takes
  # effect after recreation. Fixed tag (overwrite mode) means the compose file
  # never needs editing between builds.
  DEPLOY_REMOTE_CMD="cd $DEPLOY_COMPOSE_DIR && docker compose up -d --force-recreate"
fi

VERSION="0.0.0-dev"
[ -f "$REPO_ROOT/backend/VERSION" ] && VERSION="$(cat "$REPO_ROOT/backend/VERSION" | tr -d '\r\n')"

# DEPLOY_TAG wins; OVERWRITE=true reuses one tag (old image pruned on server),
# OVERWRITE=false tags the exact short git sha so builds never collide.
TAG="${DEPLOY_TAG:-}"
if [ -z "$TAG" ]; then
  if [ "$DEPLOY_OVERWRITE" = "true" ]; then TAG="dev"; else TAG="sha-$(git rev-parse --short HEAD)"; fi
fi
IMAGE="$DEPLOY_IMAGE:$TAG"

cd "$REPO_ROOT"

run() {
  if [ "$DRY_RUN" = "1" ]; then echo "DRY-RUN: $*"; return; fi
  "$@"
}

echo "=== Build $IMAGE (VERSION=$VERSION${DEPLOY_PLATFORM:+, platform=$DEPLOY_PLATFORM}) ==="
if [ -n "$DEPLOY_PLATFORM" ]; then
  run docker buildx build --platform "$DEPLOY_PLATFORM" --load --build-arg "VERSION=$VERSION" -t "$IMAGE" .
else
  run docker build --build-arg "VERSION=$VERSION" -t "$IMAGE" .
fi

echo "=== Ship to $DEPLOY_HOST ==="
if [ "$DRY_RUN" = "1" ]; then
  echo "DRY-RUN: docker save $IMAGE | ssh $DEPLOY_HOST docker load"
else
  docker save "$IMAGE" | ssh "$DEPLOY_HOST" docker load
fi
if [ "$DEPLOY_OVERWRITE" = "true" ]; then
  run ssh "$DEPLOY_HOST" "docker image prune -f"
fi

if [ -n "$DEPLOY_REMOTE_CMD" ]; then
  echo "=== Remote: $DEPLOY_REMOTE_CMD ==="
  run ssh "$DEPLOY_HOST" "$DEPLOY_REMOTE_CMD"
fi

echo "Deployed $IMAGE to $DEPLOY_HOST"
