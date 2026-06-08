# docker/console — Aegion SOC Console image

Static React SPA (Vite build) served by nginx, with a server-side `/v1` reverse
proxy that injects the Usage-Plan `x-api-key`. The key is **never** shipped to the
browser (WS-22 security requirement).

## Build (context = repo root)
```bash
docker build -f docker/console/Dockerfile -t sentra/console:latest .
```

## Run locally
```bash
docker run --rm -p 8080:80 \
  -e SENTRA_API_KEY="<usage-plan-key>" \
  sentra/console:latest
# open http://localhost:8080  — /v1/* is proxied to the public API Gateway with the key injected
```

## Runtime env
| Var | Default | Purpose |
|-----|---------|---------|
| `SENTRA_API_KEY` | *(required)* | Usage-Plan API key, injected as `x-api-key` on the proxied hop. In ECS this comes from a Secrets Manager secret (WS-22 Task 22.19). |
| `SENTRA_API_BASE` | `https://iw3limi4k7….amazonaws.com/prod` | API Gateway origin **incl. `/prod` stage** (WS-16). nginx appends `/v1/`. |
| `SENTRA_API_HOST` | execute-api host | `Host`/SNI for the proxied request. |

nginx substitutes only `SENTRA_*` vars (`NGINX_ENVSUBST_FILTER=SENTRA_`), so
nginx runtime vars (`$uri`, `$host`) are preserved.

## Notes
- The production build runs with `VITE_DATA_SOURCE` unset → real `/v1` (the
  code-level mock adapter is dead-code-eliminated).
- CSP baseline is `default-src 'self'` (same-origin `/v1` + Chart.js). The Tabler
  webfont/Google Fonts `<link>`s in `index.html` should be self-hosted before
  tightening `style-src`/`font-src` further (WS-22 Task 22.17).
