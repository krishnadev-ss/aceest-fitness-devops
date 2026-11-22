#!/usr/bin/env bash
# ACEest Fitness & Gym - Kubernetes deployment strategies.
#
# Used by Jenkins (Deploy stage) and by hand. Every release step checks the
# new version with an in-cluster Pytest smoke Job and rolls back on failure.
#
#   IMAGE_REPO=docker.io/<user>/aceest-fitness scripts/k8s.sh <command> [args]
#
# Commands
#   init                      namespace + all five strategies (stable / new tags)
#   release <tag> [strategy]  progressive release of <tag>; strategy = all |
#                             rolling | bluegreen | canary | ab | shadow
#   rolling <tag>             rolling update, auto 'rollout undo' on failure
#   rolling-rollback          undo the last rolling update
#   bluegreen <tag>           deploy to idle colour, test it, switch traffic
#   bluegreen-rollback        switch traffic back to the other colour
#   canary <tag>              put <tag> on the canary pod (~25% of traffic)
#   canary-promote            stable takes the canary version, canary -> 0
#   canary-rollback           canary back to the stable version
#   ab <tag>                  variant B = <tag>
#   shadow <tag>              shadow = <tag> (receives mirrored traffic)
#   smoke <service> [version] run the smoke-test Job against a Service
#   status | urls | expose    show state / NodePort URLs / port-forward on VM IP
#
# Environment
#   IMAGE_REPO   image repository (required), e.g. docker.io/jdoe/aceest-fitness
#   STABLE_TAG   tag used for the "current" slots on init       (default 2.1.0)
#   NEW_TAG      tag used for the "new" slots on init           (default: app.py)
#   SMOKE_IMAGE  image with the Pytest suite (default $IMAGE_REPO:<tag>-test
#                during a release, $IMAGE_REPO:latest-test otherwise)
set -euo pipefail

NS=aceest
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S="$ROOT/k8s"
APP_VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$ROOT/app.py")"
STABLE_TAG="${STABLE_TAG:-2.1.0}"
NEW_TAG="${NEW_TAG:-$APP_VERSION}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-180s}"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mxx  %s\033[0m\n' "$*" >&2; exit 1; }

need_repo() { [ -n "${IMAGE_REPO:-}" ] || die "set IMAGE_REPO, e.g. docker.io/<user>/aceest-fitness"; }
version_of() { local t="$1"; echo "${t%%-*}"; }   # 3.0.0-b12 -> 3.0.0
image_of()   { kubectl -n "$NS" get deploy "$1" -o jsonpath='{.spec.template.spec.containers[0].image}'; }
tag_of()     { local i; i="$(image_of "$1")"; echo "${i##*:}"; }

render() {
    sed -e "s#__IMAGE_REPO__#${IMAGE_REPO}#g" \
        -e "s#__STABLE_TAG__#${STABLE_TAG}#g" \
        -e "s#__NEW_TAG__#${NEW_TAG}#g" "$@"
}

wait_rollout() { kubectl -n "$NS" rollout status "deploy/$1" --timeout="$ROLLOUT_TIMEOUT"; }

set_image() {   # deployment tag
    local dep="$1" tag="$2"
    kubectl -n "$NS" set image "deploy/$dep" "aceest=${IMAGE_REPO}:${tag}"
    kubectl -n "$NS" annotate "deploy/$dep" --overwrite \
        kubernetes.io/change-cause="release ${tag} (build ${BUILD_NUMBER:-manual})"
}

# ---------------------------------------------------------------------------
smoke() {       # service [expected-version]
    need_repo
    local svc="$1" expected="${2:-}" job image
    job="smoke-${svc#aceest-}-$(date +%s)"
    image="${SMOKE_IMAGE:-${IMAGE_REPO}:${CURRENT_TAG:-latest}-test}"
    log "smoke test ${svc} (expect version '${expected:-any}') with ${image}"
    sed -e "s#__JOB_NAME__#${job}#" -e "s#__SMOKE_IMAGE__#${image}#" \
        -e "s#__BASE_URL__#http://${svc}.${NS}.svc.cluster.local#" \
        -e "s#__EXPECTED_VERSION__#${expected}#" "$K8S/smoke-job.yaml" \
        | kubectl apply -f -
    local s f
    for _ in $(seq 1 90); do
        s="$(kubectl -n "$NS" get job "$job" -o jsonpath='{.status.succeeded}')"
        f="$(kubectl -n "$NS" get job "$job" -o jsonpath='{.status.failed}')"
        [ "${s:-0}" -ge 1 ] && { kubectl -n "$NS" logs "job/$job" | tail -15; return 0; }
        [ "${f:-0}" -ge 1 ] && break
        sleep 2
    done
    kubectl -n "$NS" logs "job/$job" 2>/dev/null | tail -40 || true
    warn "smoke test FAILED for ${svc}"
    return 1
}

# ---------------------------------------------------------------------------
init() {
    need_repo
    log "namespace + all strategies (stable=${STABLE_TAG}, new=${NEW_TAG})"
    kubectl apply -f "$K8S/namespace.yaml"
    for f in rolling/rolling-update.yaml blue-green/blue-green.yaml \
             canary/canary.yaml ab-testing/ab-variants.yaml \
             shadow/shadow-apps.yaml; do
        render "$K8S/$f" | kubectl apply -f -
    done
    # Routers last: NGINX resolves the upstream Services when it starts.
    kubectl apply -f "$K8S/ab-testing/ab-router.yaml" -f "$K8S/shadow/shadow-router.yaml"
    for d in $(kubectl -n "$NS" get deploy -o name); do
        kubectl -n "$NS" rollout status "$d" --timeout="$ROLLOUT_TIMEOUT"
    done
    status
}

ensure_init() {
    kubectl -n "$NS" get deploy aceest-rolling >/dev/null 2>&1 || init
}

# ---------------------------------------------------------------------------
rolling() {
    local tag="$1" prev
    prev="$(tag_of aceest-rolling)"
    log "ROLLING UPDATE aceest-rolling: ${prev} -> ${tag}"
    set_image aceest-rolling "$tag"
    if wait_rollout aceest-rolling && smoke aceest-rolling "$(version_of "$tag")"; then
        log "rolling update to ${tag} OK"
    else
        warn "rolling update failed - rolling back to ${prev}"
        kubectl -n "$NS" rollout undo deploy/aceest-rolling
        wait_rollout aceest-rolling
        return 1
    fi
}

rolling_rollback() {
    log "ROLLBACK aceest-rolling to the previous revision"
    kubectl -n "$NS" rollout history deploy/aceest-rolling | tail -5
    kubectl -n "$NS" rollout undo deploy/aceest-rolling
    wait_rollout aceest-rolling
    echo "now serving $(tag_of aceest-rolling)"
}

# ---------------------------------------------------------------------------
active_colour() {
    kubectl -n "$NS" get svc aceest-bluegreen -o jsonpath='{.spec.selector.track}'
}
point() {       # service colour
    kubectl -n "$NS" patch svc "$1" --type merge \
        -p "{\"spec\":{\"selector\":{\"app\":\"aceest-bg\",\"track\":\"$2\"}}}"
}

bluegreen() {
    local tag="$1" live idle
    live="$(active_colour)"; idle=green; [ "$live" = green ] && idle=blue
    log "BLUE-GREEN: live=${live} ($(tag_of "aceest-$live")), deploying ${tag} to ${idle}"
    set_image "aceest-$idle" "$tag"
    point aceest-bluegreen-preview "$idle"
    if ! { wait_rollout "aceest-$idle" \
            && smoke aceest-bluegreen-preview "$(version_of "$tag")"; }; then
        warn "${idle} failed its checks - traffic stays on ${live} (no switch)"
        return 1
    fi
    log "switching traffic ${live} -> ${idle}"
    point aceest-bluegreen "$idle"
    point aceest-bluegreen-preview "$live"
    if ! smoke aceest-bluegreen "$(version_of "$tag")"; then
        warn "post-switch check failed - switching back to ${live}"
        point aceest-bluegreen "$live"; point aceest-bluegreen-preview "$idle"
        return 1
    fi
    log "blue-green: ${idle} is live with ${tag}; ${live} kept for instant rollback"
}

bluegreen_rollback() {
    local live other
    live="$(active_colour)"; other=green; [ "$live" = green ] && other=blue
    log "BLUE-GREEN ROLLBACK: ${live} -> ${other} ($(tag_of "aceest-$other"))"
    point aceest-bluegreen "$other"
    point aceest-bluegreen-preview "$live"
}

# ---------------------------------------------------------------------------
canary() {
    local tag="$1" stable_tag
    stable_tag="$(tag_of aceest-stable)"
    log "CANARY: stable=${stable_tag} x3, canary=${tag} x1 (~25% of traffic)"
    set_image aceest-canary "$tag"
    kubectl -n "$NS" scale deploy/aceest-canary --replicas=1
    if wait_rollout aceest-canary && smoke aceest-canary-only "$(version_of "$tag")"; then
        log "canary ${tag} healthy - promote with: scripts/k8s.sh canary-promote"
    else
        warn "canary failed - removing it from traffic"
        canary_rollback
        return 1
    fi
}

canary_promote() {
    local tag; tag="$(tag_of aceest-canary)"
    log "CANARY PROMOTE: stable -> ${tag}"
    set_image aceest-stable "$tag"
    wait_rollout aceest-stable
    smoke aceest-canary "$(version_of "$tag")"
}

canary_rollback() {
    local tag; tag="$(tag_of aceest-stable)"
    log "CANARY ROLLBACK: canary back to stable ${tag}"
    set_image aceest-canary "$tag"
    wait_rollout aceest-canary || kubectl -n "$NS" scale deploy/aceest-canary --replicas=0
}

# ---------------------------------------------------------------------------
ab() {
    local tag="$1" prev
    prev="$(tag_of aceest-variant-b)"
    log "A/B: variant A=$(tag_of aceest-variant-a), variant B=${tag}"
    set_image aceest-variant-b "$tag"
    if ! { wait_rollout aceest-variant-b && smoke aceest-variant-b "$(version_of "$tag")"; }; then
        warn "variant B failed - restoring ${prev}"
        kubectl -n "$NS" rollout undo deploy/aceest-variant-b; return 1
    fi
}

shadow() {
    local tag="$1" prev
    prev="$(tag_of aceest-shadow)"
    log "SHADOW: live=$(tag_of aceest-live), shadow=${tag} (mirrored traffic only)"
    set_image aceest-shadow "$tag"
    if ! { wait_rollout aceest-shadow && smoke aceest-shadow "$(version_of "$tag")"; }; then
        warn "shadow failed - restoring ${prev}"
        kubectl -n "$NS" rollout undo deploy/aceest-shadow; return 1
    fi
}

# ---------------------------------------------------------------------------
release() {
    need_repo
    local tag="$1" which="${2:-all}" rc=0
    export CURRENT_TAG="$tag"
    ensure_init
    case "$which" in
        rolling)   rolling "$tag" ;;
        bluegreen) bluegreen "$tag" ;;
        canary)    canary "$tag" ;;
        ab)        ab "$tag" ;;
        shadow)    shadow "$tag" ;;
        all)
            rolling "$tag"   || rc=1
            bluegreen "$tag" || rc=1
            canary "$tag"    || rc=1
            ab "$tag"        || rc=1
            shadow "$tag"    || rc=1
            ;;
        *) die "unknown strategy '$which'" ;;
    esac
    status
    return $rc
}

status() {
    log "deployments"
    kubectl -n "$NS" get deploy -o custom-columns='NAME:.metadata.name,READY:.status.readyReplicas,WANT:.spec.replicas,IMAGE:.spec.template.spec.containers[0].image'
    log "blue-green: live=$(active_colour 2>/dev/null || echo '-')"
    kubectl -n "$NS" get svc -o wide
}

urls() {
    local ip; ip="$(minikube ip 2>/dev/null || kubectl get nodes -o jsonpath='{.items[0].status.addresses[0].address}')"
    cat <<EOF
Rolling update      http://${ip}:30080
Blue-green (live)   http://${ip}:30081
Blue-green preview  http://${ip}:30085
Canary (~25%)       http://${ip}:30082
A/B testing         http://${ip}:30083   (header X-Variant: a|b)
Shadow              http://${ip}:30084
EOF
}

expose() {      # port-forward on all interfaces so other machines can reach them
    local p=8081
    for s in aceest-rolling aceest-bluegreen aceest-canary aceest-ab-router \
             aceest-shadow-router aceest-bluegreen-preview; do
        nohup kubectl -n "$NS" port-forward --address 0.0.0.0 "svc/$s" "$p:80" \
            >"/tmp/pf-$s.log" 2>&1 &
        echo "$s -> http://$(hostname -I | awk '{print $1}'):$p"
        p=$((p + 1))
    done
}

cmd="${1:-}"; shift || true
case "$cmd" in
    init)               init ;;
    release)            release "${1:?tag}" "${2:-all}" ;;
    rolling)            need_repo; CURRENT_TAG="${1:?tag}" rolling "$1" ;;
    rolling-rollback)   need_repo; rolling_rollback ;;
    bluegreen)          need_repo; CURRENT_TAG="${1:?tag}" bluegreen "$1" ;;
    bluegreen-rollback) bluegreen_rollback ;;
    canary)             need_repo; CURRENT_TAG="${1:?tag}" canary "$1" ;;
    canary-promote)     need_repo; canary_promote ;;
    canary-rollback)    need_repo; canary_rollback ;;
    ab)                 need_repo; CURRENT_TAG="${1:?tag}" ab "$1" ;;
    shadow)             need_repo; CURRENT_TAG="${1:?tag}" shadow "$1" ;;
    smoke)              smoke "${1:?service}" "${2:-}" ;;
    status)             status ;;
    urls)               urls ;;
    expose)             expose ;;
    *) sed -n '2,30p' "$0"; exit 1 ;;
esac
