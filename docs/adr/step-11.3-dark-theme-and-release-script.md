# ADR-11.3: Step 11 — Always-dark theme and the public release script

- Status: Accepted (amended by [ADR-11.4](step-11.4-usage-stats-command.md))
- Date: 2026-10-12
- Step: 11 (additional ADR #3)
- Amends: [ADR-07](step-07-frontend-text-flow-and-i18n.md) (the theme no longer follows
  `prefers-color-scheme`), [ADR-11.2](step-11.2-public-deployment-hardening.md) (release and
  kill switch through `scripts/public.sh`)

## Context

After the first public run (ADR-11.2) two changes were asked for:

1. The app must always be shown in its dark theme, whatever the visitor's system or browser
   setting. Until now the `dark:` variants followed `prefers-color-scheme` (ADR-07).
2. One command to release and one to take the app offline, with the public address printed in
   the terminal. Reading it with `logs tunnel | grep trycloudflare` right after `up -d` showed
   only "Requesting new quick Tunnel…": the address is logged about 5 s after the tunnel starts.

Also asked: whether the address can contain the app's name.

## Decision / What was implemented

### Always dark

- `frontend/src/index.css`: `@custom-variant dark (&:where(.dark, .dark *));` makes Tailwind's
  `dark:` utilities depend on a `dark` class instead of the media query; `color-scheme: dark`
  (was `light dark`) for native controls and scrollbars.
- `frontend/index.html`: `<html class="dark">`, `<meta name="color-scheme" content="dark">`, and
  `<meta name="theme-color" content="#0f172a">` (slate-900) so the browser bar on phones matches.
- No component changed: all of them already had `dark:` variants. Only `lang` on `<html>` is
  changed at runtime (i18n), which leaves the class alone.

### `scripts/public.sh`

| Command | What it does |
|---------|--------------|
| `start` | `docker compose -f docker-compose.yml -f docker-compose.public.yml up --build -d`, waits up to 60 s for the tunnel address, then up to 45 s for `<address>/api/health` to answer 200, and prints the address in a box |
| `stop` | kill switch: `… stop tunnel`; the app keeps running locally |
| `url` | prints the current address again |
| `down` | `… down`; `./data` is kept |

- The address is read only from the logs of the tunnel container's **current run**
  (`logs --since <State.StartedAt>`), so an address from an earlier run is never printed.
- Every command first checks `docker info` and says to start Docker Desktop if it fails.
- `docs/deployment.md`, the README and the comments in `docker-compose.public.yml` use the
  script; the raw `docker compose` commands stay documented next to it.

### The address's name

Not possible with a Quick Tunnel: Cloudflare picks a random `<words>.trycloudflare.com` name,
and a new one at every start. A chosen name (e.g. `song-recommender.<domain>`) needs a named
tunnel on a domain whose DNS is on Cloudflare (Stage 2 in docs/deployment.md). Documented; no
change.

## Deviations from the plan

- ADR-07's light theme stays in the code (the non-`dark:` classes) but is never shown. Removing
  it would touch every component for no visible gain, and keeps the option of a theme switch.

## Issues encountered and how they were solved

- **Tailwind v4 has no `darkMode: 'class'` config.** The v4 way is a `@custom-variant` in the
  CSS. The built CSS was checked: it no longer contains `prefers-color-scheme`.
- **Stale address after a restart.** `logs` returns all runs of a container, so `start` after
  `stop` would find the old address first. Limiting the logs to `--since` the container's
  `StartedAt` solves it; checked against the logs of the first public run, where it returned
  that run's address.
- **The address exists before it resolves.** Public DNS for a new `trycloudflare.com` name can
  lag by seconds, so `start` waits for `/api/health` through the address before printing it,
  and prints it with a warning if that takes more than 45 s.

## Consequences

- Visitors always see the dark theme; light-theme styles are dead code until a theme switch is
  wanted.
- Releasing is `scripts/public.sh start`; going offline is `scripts/public.sh stop`.
- With a named tunnel (Stage 2), `start` finds no `trycloudflare.com` address and says so; the
  address is the configured hostname.

## Verification

```bash
cd frontend
npm test                          # 70 passed
npm run build                     # built CSS has no prefers-color-scheme
npm run format:check
cd ..
bash -n scripts/public.sh         # syntax ok
scripts/public.sh url             # tunnel stopped: "The tunnel is not running…", exit 1
scripts/public.sh foo             # usage, exit 2
```

The `--since <StartedAt>` extraction was run by hand against the stopped tunnel container and
returned its address. `scripts/public.sh start` itself was not run in this step: it would put
the app back on the internet, which the developer had just switched off.
