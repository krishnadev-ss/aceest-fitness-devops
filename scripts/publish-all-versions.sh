#!/usr/bin/env bash
# Build every released version of ACEest (git tags v*) and push it to Docker
# Hub, so the registry holds the full version history:
#   <user>/aceest-fitness:1.0.0, 2.0.0, 2.0.1, 2.0.2, 2.1.0, 3.0.0, latest
#
#   docker login                       # once, with a Docker Hub access token
#   DOCKERHUB_USER=<user> scripts/publish-all-versions.sh
set -euo pipefail

: "${DOCKERHUB_USER:?set DOCKERHUB_USER to your Docker Hub username}"
REPO="docker.io/${DOCKERHUB_USER}/aceest-fitness"
ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'git -C "$ROOT" worktree prune; rm -rf "$WORK"' EXIT

tags=$(git -C "$ROOT" tag -l 'v*' --sort=v:refname)
latest=$(echo "$tags" | tail -1)

for tag in $tags; do
    ver="${tag#v}"
    echo "==> ${tag} -> ${REPO}:${ver}"
    git -C "$ROOT" worktree add -f --detach "$WORK/$ver" "$tag" >/dev/null
    commit=$(git -C "$ROOT" rev-list -n1 "$tag")
    docker build -q \
        --build-arg APP_VERSION="$ver" --build-arg GIT_COMMIT="$commit" \
        --label org.opencontainers.image.version="$ver" \
        -t "${REPO}:${ver}" "$WORK/$ver"
    docker build -q --target test -t "${REPO}:${ver}-test" "$WORK/$ver"
    docker push -q "${REPO}:${ver}"
    docker push -q "${REPO}:${ver}-test"
    if [ "$tag" = "$latest" ]; then
        docker tag "${REPO}:${ver}" "${REPO}:latest"
        docker tag "${REPO}:${ver}-test" "${REPO}:latest-test"
        docker push -q "${REPO}:latest"
        docker push -q "${REPO}:latest-test"
    fi
    git -C "$ROOT" worktree remove --force "$WORK/$ver"
done

echo
echo "Published to https://hub.docker.com/r/${DOCKERHUB_USER}/aceest-fitness/tags"
docker image ls "${REPO}"
