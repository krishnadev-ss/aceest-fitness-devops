#!/usr/bin/env bash
# Build every released version of ACEest (git tags v*) and push it to Docker
# Hub, so the registry holds the full version history:
#   <user>/aceest-fitness:1.0.0, 2.0.0, 2.0.1, 2.0.2, 2.1.0, 3.0.0, latest
# plus a "-test" image per version (the Pytest suite, used by smoke Jobs).
#
#   docker login                       # once, with a Docker Hub access token
#   DOCKERHUB_USER=<user> scripts/publish-all-versions.sh
#
# PLATFORMS (default linux/amd64,linux/arm64) builds multi-architecture images
# with docker buildx, so the same tag runs on an x86 lab VM / Minikube and on
# an Apple-silicon laptop. PLATFORMS="" falls back to a plain single-arch build.
set -euo pipefail

: "${DOCKERHUB_USER:?set DOCKERHUB_USER to your Docker Hub username}"
REPO="docker.io/${DOCKERHUB_USER}/aceest-fitness"
PLATFORMS="${PLATFORMS-linux/amd64,linux/arm64}"
ROOT="$(git rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
trap 'git -C "$ROOT" worktree prune; rm -rf "$WORK"' EXIT

if [ -n "$PLATFORMS" ]; then
    docker buildx inspect aceest-multi >/dev/null 2>&1 \
        || docker buildx create --name aceest-multi --driver docker-container >/dev/null
    docker buildx use aceest-multi
fi

build() {   # context target tag [extra tag]
    local ctx="$1" target="$2" tag="$3" extra="${4:-}" commit
    commit=$(git -C "$ctx" rev-parse HEAD)
    local args=(--target "$target" --build-arg "APP_VERSION=${tag%%-*}"
                --build-arg "GIT_COMMIT=$commit" -t "${REPO}:${tag}")
    [ -n "$extra" ] && args+=(-t "${REPO}:${extra}")
    if [ -n "$PLATFORMS" ]; then
        docker buildx build --platform "$PLATFORMS" --push "${args[@]}" "$ctx"
    else
        docker build "${args[@]}" "$ctx"
        docker push "${REPO}:${tag}"
        [ -n "$extra" ] && docker push "${REPO}:${extra}"
    fi
}

tags=$(git -C "$ROOT" tag -l 'v*' --sort=v:refname)
latest=$(echo "$tags" | tail -1)

for tag in $tags; do
    ver="${tag#v}"
    echo "==> ${tag} -> ${REPO}:${ver}"
    git -C "$ROOT" worktree add -f --detach "$WORK/$ver" "$tag" >/dev/null
    if [ "$tag" = "$latest" ]; then
        build "$WORK/$ver" runtime "$ver" latest
        build "$WORK/$ver" test "${ver}-test" latest-test
    else
        build "$WORK/$ver" runtime "$ver"
        build "$WORK/$ver" test "${ver}-test"
    fi
    git -C "$ROOT" worktree remove --force "$WORK/$ver"
done

echo
echo "Published: https://hub.docker.com/r/${DOCKERHUB_USER}/aceest-fitness/tags"
