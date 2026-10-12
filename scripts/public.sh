#!/usr/bin/env bash
# Public deployment through the Cloudflare Quick Tunnel (docs/deployment.md, ADR-11.3).
#
#   scripts/public.sh start   build and start the app and the tunnel, print the public address
#   scripts/public.sh stop    kill switch: take the app off the internet (it keeps running locally)
#   scripts/public.sh url     print the current public address again
#   scripts/public.sh down    stop everything (the data in ./data stays)
#   scripts/public.sh stats   usage of the last 7 days, today's totals against the limits
#
# A Quick Tunnel gets a new random address every time the tunnel container starts, so `start`
# after `stop` gives a new address; `start` while the tunnel is running keeps the address.
set -euo pipefail

cd "$(dirname "$0")/.."

# Seconds to wait for the tunnel to report its address, and for the address to answer.
URL_TIMEOUT=60
REACH_TIMEOUT=45
URL_PATTERN='https://[a-z0-9-]+\.trycloudflare\.com'

compose() {
    docker compose -f docker-compose.yml -f docker-compose.public.yml "$@"
}

require_docker() {
    if ! docker info >/dev/null 2>&1; then
        echo "Docker is not running. Start Docker Desktop (with WSL integration on) and try again." >&2
        exit 1
    fi
}

# The address from the logs of the tunnel container's current run only: older runs in the same
# logs had other addresses.
current_url() {
    local id started
    id=$(compose ps -q tunnel 2>/dev/null)
    [[ -n "$id" ]] || return 0
    [[ "$(docker inspect -f '{{.State.Running}}' "$id")" == "true" ]] || return 0
    started=$(docker inspect -f '{{.State.StartedAt}}' "$id")
    compose logs --no-log-prefix --since "$started" tunnel 2>/dev/null \
        | grep -oE "$URL_PATTERN" | grep -v '^https://api\.' | tail -n 1 || true
}

wait_for_url() {
    local url="" waited=0
    while [[ -z "$url" && $waited -lt $URL_TIMEOUT ]]; do
        url=$(current_url)
        [[ -n "$url" ]] && break
        sleep 2
        waited=$((waited + 2))
    done
    echo "$url"
}

# A new address takes a few seconds to resolve in public DNS.
wait_until_reachable() {
    local url=$1 waited=0
    while [[ $waited -lt $REACH_TIMEOUT ]]; do
        if [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url/api/health")" == "200" ]]; then
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
    done
    return 1
}

print_url() {
    local url=$1
    echo
    echo "  ┌──────────────────────────────────────────────────────────────────┐"
    printf "  │  %-64s│\n" "Song Recommender is public at:"
    printf "  │  %-64s│\n" "$url"
    echo "  └──────────────────────────────────────────────────────────────────┘"
    echo
}

start() {
    require_docker
    compose up --build -d
    echo "Waiting for the tunnel address…"
    local url
    url=$(wait_for_url)
    if [[ -z "$url" ]]; then
        echo "The tunnel did not report an address within ${URL_TIMEOUT}s. Its last log lines:" >&2
        compose logs --tail 20 tunnel >&2
        exit 1
    fi
    if wait_until_reachable "$url"; then
        print_url "$url"
    else
        print_url "$url"
        echo "Warning: the address did not answer within ${REACH_TIMEOUT}s; DNS may still be" >&2
        echo "propagating. Try it in a minute, or check: scripts/public.sh url" >&2
    fi
    echo "Kill switch: scripts/public.sh stop"
}

stop() {
    require_docker
    compose stop tunnel
    echo
    echo "The app is OFF the internet. It still runs locally at http://localhost:${APP_PORT:-8080}."
    echo "Back online (with a NEW address): scripts/public.sh start"
}

url() {
    require_docker
    local url
    url=$(current_url)
    if [[ -z "$url" ]]; then
        echo "The tunnel is not running. Start it with: scripts/public.sh start" >&2
        exit 1
    fi
    print_url "$url"
}

down() {
    require_docker
    compose down
    echo "Everything is stopped. The data in ./data is kept."
}

# Read-only summary from data/app.db, run inside the backend container (it has Python and the
# settings; the host may have no sqlite3). Counts only visitors' requests: rows from before
# visitors existed (ADR-11.1) belong to no one.
stats() {
    require_docker
    if [[ -z "$(compose ps -q --status running backend)" ]]; then
        echo "The backend is not running. Start it with: scripts/public.sh start" >&2
        exit 1
    fi
    compose exec -T backend python - <<'PY'
import sqlite3

from app.config import get_settings

settings = get_settings()
db = sqlite3.connect(f"file:{settings.database_path}?mode=ro", uri=True)
DAYS = "date('now', '-6 days')"

print("Last 7 days (UTC), visitors' requests:")
header = ("day", "recommend.", "completed", "failed", "question", "voice", "transcr.", "visitors")
print("  " + " ".join(f"{h:>10}" for h in header))
rows = db.execute(f"""
    SELECT substr(r.created_at, 1, 10) AS day, count(*),
           sum(r.status = 'completed'), sum(r.status = 'failed'),
           sum(r.status = 'needs_clarification'), sum(r.input_mode = 'voice'),
           coalesce((SELECT used FROM daily_usage u WHERE u.visitor_id = '*'
                     AND u.day = substr(r.created_at, 1, 10) AND u.action = 'transcription'), 0),
           count(DISTINCT r.visitor_id)
    FROM recommendations r
    WHERE r.visitor_id IS NOT NULL AND substr(r.created_at, 1, 10) >= {DAYS}
    GROUP BY day ORDER BY day DESC""").fetchall()
for row in rows:
    print("  " + " ".join(f"{v:>10}" for v in row))
if not rows:
    print("  (no recommendations yet)")

today = dict(db.execute(
    "SELECT action, used FROM daily_usage WHERE visitor_id = '*' AND day = date('now')"
).fetchall())

def against(used: int, limit: int) -> str:
    return f"{used}/{limit}" if limit else f"{used} (no limit)"

print()
print("Today, all visitors together:")
print("  recommendations ", against(today.get("recommendation", 0),
                                  settings.daily_total_recommendation_limit))
print("  transcriptions  ", against(today.get("transcription", 0),
                                  settings.daily_total_transcription_limit))

errors = db.execute(f"""
    SELECT error_code, count(*) FROM recommendations
    WHERE visitor_id IS NOT NULL AND error_code IS NOT NULL AND substr(created_at, 1, 10) >= {DAYS}
    GROUP BY 1 ORDER BY 2 DESC""").fetchall()
print()
print("Errors (7 days): " + (", ".join(f"{code} {n}" for code, n in errors) or "none"))

up, down = db.execute(f"""
    SELECT coalesce(sum(f.score > 0), 0), coalesce(sum(f.score < 0), 0)
    FROM feedback f JOIN recommendations r ON r.id = f.recommendation_id
    WHERE r.visitor_id IS NOT NULL AND substr(f.created_at, 1, 10) >= {DAYS}""").fetchone()
print(f"Ratings (7 days): {up} up, {down} down")
print()
print("Texts, traces and costs: LangSmith project", settings.langsmith_project)
PY
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    url) url ;;
    down) down ;;
    stats) stats ;;
    *)
        echo "Usage: scripts/public.sh start | stop | url | down | stats" >&2
        exit 2
        ;;
esac
