# Remote access — Cloudflare Tunnel

How ChoreKeeper is reached from outside the LAN (spec §12.2, `[D]`). Local `just up`
development is unaffected — everything here is opt-in via `docker-compose.tunnel.yml`.

---

## How it works

`cloudflared` runs as a compose service and dials **outbound** to Cloudflare's edge,
holding the connection open. Cloudflare publishes `chores.example.com` pointing at that
tunnel; inbound requests travel back down the existing connection to `proxy:80` on the
compose network. **No router port is forwarded, no public IP or dynamic DNS is needed, and
the origin never listens on a public socket.**

```
phone / browser ──TLS──▶ Cloudflare edge ──▶ cloudflared ──▶ proxy (Caddy) ──┬─▶ /api/*  → api:8000
                          │  Access on /admin, /api/v1/admin                  └─▶ else    → built PWA
                          │  WAF rate-limit on /api/v1/auth/login
```

`cloudflared` authenticates to Cloudflare with a **tunnel token** (a bearer credential —
keep it in `.env`, never commit, rotate on suspicion). It grants no LAN access beyond the
one mapped service.

**Operator path is separate** (spec §12.2 "two doors"): reach SSH, Postgres, `llama-server`
and `http://127.0.0.1:8088` over **Tailscale**, never through the tunnel.

---

## Security implications

- **Attack surface** is one hostname behind Cloudflare's edge. No inbound port, no public
  IP, origin unreachable directly. Cloudflare absorbs L3/4 floods.
- **TLS terminates at Cloudflare.** Photo bytes — a camera pointed at your kids' rooms —
  are briefly in plaintext at their edge in transit. They are never *stored* there and the
  origin stays private. This is spec §12.2's explicitly accepted tradeoff and a stated
  exception to spec §5 ("no image leaves the LAN"). If it ever stops feeling acceptable,
  switch to Tailscale-only — no app changes needed.
- **Layered admin auth**: Cloudflare Access (operator email OTP / Google) **+** app password
  **+** TOTP **+** the app verifying the `Cf-Access-Jwt-Assertion` header on
  `/api/v1/admin/*` (`CF_ACCESS_*` env). A tunnel or Access misconfiguration alone does not
  expose admin.
- **Kid paths are app-auth only** — long-lived session + strict CSP + the WAF login
  rate-limit + the per-token 20/h check-in cap. Deliberate: an Access wall in front of a
  12-year-old at 07:55 kills adoption.
- **Client-IP trust**: with `TRUST_PROXY_HEADERS=true` the app believes `CF-Connecting-IP`.
  Set it **only** in this deployment — on the LAN a local client would spoof the header to
  dodge the login rate-limit or poison audit logs.
- **Login DoS**: the in-process IP limiter is per-process and restart-wiped. The real
  defense is the **Cloudflare WAF rate-limit rule** on `/api/v1/auth/login` (step 7); the
  per-account exponential backoff (keyed by username) still works.
- **Cache poisoning / signed-URL leakage**: `/api/*` and media must **never** be edge
  cached. Caddy sends `Cache-Control: private, no-store`; add the Cloudflare Cache Rule
  (step 6) as well. A cached signed media URL served to another session is *the* failure
  mode to avoid.
- **Host-header attacks**: `ALLOWED_HOSTS` enables `TrustedHostMiddleware`, rejecting any
  Host that isn't the tunnel hostname (localhost stays allowed for health checks).
- **Debug surface**: `ENVIRONMENT=prod` disables `/docs` + `/openapi.json` and enables HSTS.
- **Cookies**: `Secure` (auto-on in prod), `HttpOnly`, `SameSite=Lax`, host-only. CSRF is a
  header-vs-server double-submit — proxy-safe, independent of `Origin` / client IP.
- **Body size**: Cloudflare's free plan caps request bodies at 100 MB. The app caps uploads
  at 12 MB and downscales client-side to ~300 KB.
- **You are trusting Cloudflare** with all plaintext traffic and your DNS. Accepted for a
  household app — documented so it's a choice, not a surprise.

---

## Setup

**Prerequisites:** a domain on Cloudflare (free plan), a Zero Trust org (free),
Docker Compose **v2.24+** (for the `!override` tag in the overlay), and Tailscale on the
host for the operator path.

### 1. Create the tunnel

Zero Trust dashboard → **Networks → Tunnels → Create a tunnel → Cloudflared**. Name it
`chorekeeper`. On the next screen **copy the token** (the long string after
`cloudflared service install`).

### 2. Add the public hostname

Still in the tunnel config, **Published application routes → Add**:

| Field | Value |
|---|---|
| Subdomain / domain | `chores` / `example.com` |
| Type | `HTTP` |
| URL | `proxy:80` |

Cloudflare creates the `CNAME` automatically. No path routing here — Cloudflare Access does
the admin split.

### 3. Host `.env`

Copy `.env.example` to `.env` on the host and set:

```sh
CLOUDFLARE_TUNNEL_TOKEN=<token from step 1>
PUBLIC_BASE_URL=https://chores.example.com
ALLOWED_HOSTS=chores.example.com
SESSION_SECRET=<openssl rand -hex 32>
TRUST_PROXY_HEADERS=true
# CF_ACCESS_* are filled in step 5
```

`ENVIRONMENT=prod` and `COOKIE_SECURE=true` are set by the overlay — no need to add them.

### 4. Bring it up

```sh
just tunnel-up          # docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d --build
just tunnel-logs        # expect "Registered tunnel connection" x4
```

`https://chores.example.com` now serves the PWA. `/docs` returns 404; `/api/v1/health`
returns `{"status":"ok"}`.

### 5. Cloudflare Access for the admin surface

Zero Trust → **Access → Applications → Add an application → Self-hosted**. Create two
(optionally three):

| Application | Domain | Path |
|---|---|---|
| ChoreKeeper admin UI | `chores.example.com` | `admin` |
| ChoreKeeper admin API | `chores.example.com` | `api/v1/admin` |
| _(optional)_ LLM health | `chores.example.com` | `api/v1/health/llm` |

For each: **Policy** → Action `Allow`, Include → `Emails` → your address. **Identity
providers** → `One-time PIN` (or Google). Session duration `24h`.

After creating them, open each app's **Overview** and copy the **Application Audience (AUD)
tag**. Put it in `.env` as `CF_ACCESS_AUD` (they share one if you scope a single app to
both paths; otherwise use the admin-API one), set
`CF_ACCESS_TEAM_DOMAIN=<yourteam>.cloudflareaccess.com`, and `just tunnel-up` again.

**Do not** add any Access policy that covers the rest of the site — the kid paths stay open
to app auth only.

### 6. Cache rule

Dashboard → **Rules → Caching → Create rule**: *When* `URI Path` `starts with` `/api/` →
*Then* `Bypass cache`. (Belt-and-suspenders with the origin `no-store` header, for media.)

### 7. WAF rate-limit on login

**Security → WAF → Rate limiting rules → Create rule**:

- Expression: `http.request.uri.path eq "/api/v1/auth/login"`
- Rate: `10` requests per `1 minute`, characteristic `IP`
- Action: `Block`, duration `1 minute`

Optionally a looser rule on `starts_with(http.request.uri.path, "/api/v1/checkin/")`.

### 8. Bot Fight Mode (if you enable it)

**Security → WAF → Custom rules → Create rule** → Action `Skip` → *All remaining custom
rules* + *Managed challenge*, for:

```
http.request.uri.path in {"/sw.js" "/registerSW.js" "/manifest.webmanifest"}
or starts_with(http.request.uri.path, "/api/v1/checkin/")
```

The check-in webhook is called by iOS Shortcuts / Tasker with no browser — a JS challenge
would break the geofence automations.

### 9. Edge TLS settings

**SSL/TLS → Edge Certificates**: *Always Use HTTPS* on, *Minimum TLS Version* 1.2. Leave
HSTS to the origin header (Caddy sends it) or enable it here with the same `max-age`.
Turn *Development Mode* off.

### 10. Operator path (Tailscale)

```sh
tailscale up
```

Then reach the box over the tailnet: `ssh`, `psql -h <tailnet-ip>`,
`curl http://<tailnet-ip>:8088/api/v1/health`, and `llama-server`. The overlay binds the
API to `127.0.0.1:8088` and Postgres to `127.0.0.1:5432` so they are **not** on the LAN and
**not** in the tunnel ingress. `/admin/jobs` and `/health/llm` are still reachable through
the tunnel but gated by Access + the app JWT check.

### 11. Rotating the tunnel token

Dashboard → the tunnel → **Refresh token** (or delete and recreate the tunnel). Update
`CLOUDFLARE_TUNNEL_TOKEN` in `.env` and `just tunnel-up`.

---

## Verify

```sh
curl -sI https://chores.example.com | grep -Ei 'content-security-policy|strict-transport|x-frame'
curl -s  https://chores.example.com/api/v1/health                       # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://chores.example.com/docs # 404
curl -s -o /dev/null -w '%{http_code}\n' https://chores.example.com/api/v1/admin/jobs  # 403
```

- Browser → `https://chores.example.com/admin` → Cloudflare Access login → app login →
  TOTP → dashboard renders.
- Phone on cell data → install the PWA, capture a photo, submit → appears in the admin
  inbox; approve → ledger credits once.
- `curl -X POST https://chores.example.com/api/v1/checkin/<token> -H 'content-type:
  application/json' -d '{"lat":0,"lon":0,"accuracy":10}'` from outside → 200, no Access
  prompt.
- External port scan of the host's public IP → only Cloudflare's 443; `5432` / `8088`
  refused. From the tailnet those ports work.
