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
                          │  Access (Google) on everything                    ├─▶ /api/v1/auth/login → 404
                          │  except /health + /api/v1/checkin/*               └─▶ else    → built PWA
```

Cloudflare Access is also the **sign-in**: once it has authenticated a Google account it
attaches a signed `Cf-Access-Jwt-Assertion`, and `GET /api/v1/auth/me` maps the verified
`email` claim to a `users` row and mints the app's own session (spec §12.1). There is no
sign-in form; a parent adds a kid by putting their Google address in *both* the Access
policy and the app.

`cloudflared` authenticates to Cloudflare with a **tunnel token** (a bearer credential —
keep it in `.env`, never commit, rotate on suspicion). It grants no LAN access beyond the
one mapped service.

**There is no remote operator path** (spec §12.2 `[D]`). SSH, Postgres, `llama-server` and
`http://127.0.0.1:8088` are reachable from the LAN or the console only — never through the
tunnel, and no VPN is maintained for them. A fault that needs a shell needs someone at home.

---

## Security implications

- **Attack surface** is one hostname behind Cloudflare's edge. No inbound port, no public
  IP, origin unreachable directly. Cloudflare absorbs L3/4 floods.
- **TLS terminates at Cloudflare.** Photo bytes — a camera pointed at your kids' rooms —
  are briefly in plaintext at their edge in transit. They are never *stored* there and the
  origin stays private. This is spec §12.2's explicitly accepted tradeoff and a stated
  exception to spec §5 ("no image leaves the LAN"). If it ever stops feeling acceptable,
  switch to Tailscale-only — no app changes needed.
- **Google and Cloudflare now hold identity.** They learn who signed in and when — never
  chore content, photos or the ledger. In exchange there is one credential per person
  instead of a password plus an authenticator app, on accounts the family already secures.
- **Access fronts every path but two**, kids included. The exemptions are `/api/v1/health`
  (liveness probe) and `/api/v1/checkin/{token}` (iOS Shortcuts geofence; a Shortcut cannot
  carry an Access session). The check-in path is therefore **the only unauthenticated
  surface left**, and it rests entirely on the per-kid token: high-entropy, revocable, and
  capped at 20 requests/hour. Assume it leaks eventually — rotate it from admin → Kids.
- **The app verifies the assertion itself**, against Cloudflare's JWKS, with the AUD tag and
  issuer pinned (`CF_ACCESS_*`). It never reads `CF-Access-Authenticated-User-Email`, which
  is a plain header anything reaching the origin could set. A tunnel or Access
  misconfiguration alone does not get anyone in.
- **Break-glass is kept off the internet by two independent layers**: the app exempts
  `/api/v1/auth/login` from the Access check so it works on `127.0.0.1:8088`, **and** the
  Caddy front door answers `404` for that path so the tunnel never carries it. Either layer
  alone would leave a password-only door on the public internet, so treat both as load
  bearing — the Caddyfile block carries a comment saying exactly that.
- **Losing Google or Cloudflare locks everyone out.** That is what break-glass exists for;
  it works from the LAN when the edge does not. Keep the password somewhere reachable
  without the app.
- **Access sessions expire while the PWA is open** (1 month by policy). The edge then
  answers an API call with a redirect to Google, which `fetch` cannot usefully follow, so
  the app detects the HTML response and reloads the page — a top-level navigation is the
  only thing that can complete an Access round-trip.
- **One third-party host in the CSP**: `https://*.tile.openstreetmap.org` in `img-src`, for
  the admin geofence map picker (spec §6.2). It loads only when a parent opens a location
  chore's editor, and it tells OSM which coordinates are being viewed — a deliberate,
  documented exception. Drop the directive from [frontend/Caddyfile](../frontend/Caddyfile)
  to disable it; the lat/lon/radius inputs keep working with a blank map.
- **Client-IP trust**: with `TRUST_PROXY_HEADERS=true` the app believes `CF-Connecting-IP`.
  Set it **only** in this deployment — on the LAN a local client would spoof the header to
  dodge the login rate-limit or poison audit logs.
- **Login DoS**: with break-glass unreachable through the tunnel there is no public
  credential endpoint left to flood; the WAF rate-limit now guards `/api/v1/checkin/*`
  instead (step 7). The in-process IP limiter and per-account backoff still guard the
  loopback path.
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
Docker Compose **v2.24+** (for the `!override` tag in the overlay), a Google Cloud project
for the OAuth client (step 5a), and a Google account for every household member.

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

`proxy:80`, **not** `proxy:5173`. `5173` is only the host-side port mapping in
`docker-compose.yml`; inside the compose network Caddy listens on `80`, and pointing the
tunnel at `5173` gets a `connection refused` from `cloudflared` and a 502 in the browser.

Cloudflare creates the `CNAME` automatically. No path routing here — the Access
applications do the admin split.

### 3. Host `.env`

Copy `.env.example` to `.env` on the host and set:

```sh
CLOUDFLARE_TUNNEL_TOKEN=<token from step 1>
PUBLIC_BASE_URL=https://chores.example.com
ALLOWED_HOSTS=chores.example.com
SESSION_SECRET=<openssl rand -hex 32>
TRUST_PROXY_HEADERS=true
ADMIN_EMAIL=you@gmail.com    # read once by the auth migration to seed the admin identity
# CF_ACCESS_* are filled in step 5g
```

`ENVIRONMENT=prod` and `COOKIE_SECURE=true` are set by the overlay — no need to add them.

### 4. Bring it up

```sh
just tunnel-up          # docker compose -f docker-compose.yml -f docker-compose.tunnel.yml up -d --build
just tunnel-logs        # expect "Registered tunnel connection" x4
```

`https://chores.example.com` now serves the PWA. `/docs` returns 404; `/api/v1/health`
returns `{"status":"ok"}`.

### 5. Google sign-in via Cloudflare Access

This is what makes Google the login for everyone (spec §12.1). Do all seven sub-steps —
skipping **5f** breaks the geofence check-ins, and skipping **5g** leaves the app unable to
verify the assertions it is being handed.

#### 5a. Create the Google OAuth client

In the [Google Cloud Console](https://console.cloud.google.com/):

1. Create (or pick) a project.
2. **APIs & Services → OAuth consent screen** → *External*. Fill in app name and support
   email. Under *Test users*, add the parent's address and each kid's — or **Publish** the
   app, which avoids the 100-test-user cap and the weekly re-consent. Nothing sensitive is
   requested; the scopes are the default email/profile.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type **Web
   application**.
4. Under *Authorized redirect URIs* add exactly:

   ```
   https://<yourteam>.cloudflareaccess.com/cdn-cgi/access/callback
   ```

   `<yourteam>` is your Zero Trust team name (Zero Trust → Settings → Custom Pages, or the
   subdomain in the dashboard URL). A wrong or missing redirect URI is the usual cause of
   `redirect_uri_mismatch` on first sign-in.
5. Copy the **Client ID** and **Client secret**.

#### 5b. Add Google as the login method

Zero Trust → **Settings → Authentication → Login methods → Add new → Google**. Paste the
client ID and secret, save, then **Test** — it should round-trip to Google and back.

Then **remove or disable One-time PIN** so Google is the only way in. Leaving it enabled
means anyone whose address is on a policy can sign in by email code alone, which quietly
undoes the point of using Google accounts.

#### 5c. App A — the whole app

**Access → Applications → Add an application → Self-hosted.**

| Field | Value |
|---|---|
| Name | `ChoreKeeper` |
| Domain | `chores.example.com` |
| Path | *(empty — the whole hostname)* |
| Identity providers | **Google only**; turn *Accept all available identity providers* **off** |
| Instant Auth | **On** |
| Session duration | `1 month` (the maximum) |

*Instant Auth* skips Cloudflare's identity-provider chooser and goes straight to Google, so
a kid whose phone is already signed in to Google lands on the chore list without a prompt.
That is what makes an Access wall acceptable in front of a 12-year-old at 07:55.

**Policy** → name it `Household`, Action **Allow**, Include → **Emails** → the parent's
address and every kid's, one per line.

> The 1-month ceiling is shorter than the app's own 90-day kid session, so kids will re-tap
> Google roughly monthly even though the app would have kept them signed in. Expected, not a
> bug.

#### 5d. App B — admin, stricter

A second self-hosted application over the same host, path `admin`, and a third over path
`api/v1/admin` (Cloudflare matches the most specific path first, so these override App A):

| Field | Value |
|---|---|
| Domain / path | `chores.example.com` / `admin`, and again `api/v1/admin` |
| Policy | Action **Allow**, Include → **Emails** → the parent only |
| Session duration | `24 hours` |

#### 5e. App C — the check-in webhook bypass

**Required.** Add one more self-hosted application:

| Field | Value |
|---|---|
| Domain / path | `chores.example.com` / `api/v1/checkin` |
| Policy | Action **Bypass**, Include → **Everyone** |

iOS Shortcuts and Tasker cannot carry an Access session, so without this every geofence
check-in gets a redirect to Google instead of reaching the app. The path stays protected by
the per-kid token and its 20/hour cap (spec §6.2).

#### 5f. Health check

Optionally add a Bypass application for path `api/v1/health` too, if anything outside the
compose network probes it. Container health checks reach it directly and need nothing.

#### 5g. AUD tags → `.env`

Open each application's **Overview** and copy its **Application Audience (AUD) tag**. Every
application issues its own, and a JWT minted by one will not verify against another's, so
list every tag whose traffic reaches the API — App A and the `api/v1/admin` one at minimum:

```sh
CF_ACCESS_TEAM_DOMAIN=<yourteam>.cloudflareaccess.com
CF_ACCESS_AUD=<app-A-aud>,<admin-api-aud>
```

Then `just tunnel-up` again. With these set the app requires a verified assertion on every
`/api/v1` path except `/health`, `/checkin/{token}` and the break-glass `/auth/login`.

**If your Zero Trust team has ever been renamed, add `CF_ACCESS_ISSUER`.** Cloudflare serves
the login page and the JWKS from the *new* team name while still putting the *original* one
in the token's `iss` claim, and the original hostname 404s — so the issuer cannot be derived
from the team domain and must be pinned:

```sh
CF_ACCESS_ISSUER=https://<original-team-name>.cloudflareaccess.com
```

The symptom is `invalid Cloudflare Access token: Invalid issuer` in the browser. Read the
value Cloudflare is actually sending straight out of the log — the rejection line prints
both sides:

```sh
docker compose logs api | grep cf_access.rejected | tail -1
# ... "error":"Invalid issuer","token_iss":"https://misty-grass-1e4b.cloudflareaccess.com",
#     "expected_iss":["https://yourteam.cloudflareaccess.com"] ...
```

`CF_ACCESS_ISSUER` accepts a comma-separated list, so you can keep both the old and the new
name accepted and not get caught again if Cloudflare ever switches.

#### 5h. Adding or removing a kid

Two places, both required, in this order:

1. Cloudflare → App A's `Household` policy → add their Google address.
2. ChoreKeeper → **Kids** → *Add kid* → same address.

Add it only in the app and Cloudflare turns them away at the edge; add it only in Cloudflare
and the app answers *"…is signed in to Google but is not an active member of this
household"*, naming the address so the fix is obvious. To remove someone, reverse the order:
drop the Access policy entry first, then deactivate them in the app.

### 6. Cache rule

Dashboard → **Rules → Caching → Create rule**: *When* `URI Path` `starts with` `/api/` →
*Then* `Bypass cache`. (Belt-and-suspenders with the origin `no-store` header, for media.)

### 7. WAF rate-limit on the check-in webhook

`/api/v1/checkin/*` is the only unauthenticated path left, so it is where the rule belongs.

**Security → WAF → Rate limiting rules → Create rule**:

- Expression: `starts_with(http.request.uri.path, "/api/v1/checkin/")`
- Rate: `30` requests per `1 minute`, characteristic `IP`
- Action: `Block`, duration `1 minute`

There is no longer a public login endpoint to rate-limit: break-glass 404s through the
tunnel, and everything else sits behind Access.

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

### 9b. The LAN door (break-glass)

The tunnel deployment publishes a **second Caddy site on `:81`**, mapped to the host's
`:5173`, reachable only from the home network. cloudflared has no route to it — its ingress
names `proxy:80` and nothing else — so nothing here is exposed to the internet.

It exists for one reason: when Cloudflare or Google is unavailable, nobody can sign in
through the tunnel, and the break-glass password path is deliberately 404ed there. Without a
LAN door the only way back in is a shell on the host.

```
http://<home-ip>:5173/            → the app, with the break-glass sign-in available
https://chores.example.com/       → the app, Google via Access, break-glass 404ed
```

Two things make this safe rather than a bypass:

- **Network separation.** :80 and :81 are different listeners; only :80 is wired to the
  tunnel. This is a fact about the topology, not a header the app has to believe.
- **Fail-closed labelling.** Caddy stamps every proxied request with `X-CK-Door`
  (`tunnel` or `lan`), overwriting anything the client sent. The app skips the Access check
  only on an explicit `lan`; a stripped, misspelled or absent value keeps Access in force.

App auth is unchanged behind the LAN door — session cookie, CSRF, and the same rate limits.
What it grants is the *chance* to enter the admin password, so treat anyone on your wifi as
someone who gets to try. Kids cannot sign in there at all: their identity is Google, and
Google is not in front of this door.

### 10. Operator path — LAN and console only

There is nothing to set up, and that is the decision (spec §12.2 `[D]`). The overlay binds
the API to `127.0.0.1:8088` and Postgres to `127.0.0.1:5432`, so `ssh`, `psql` and
`llama-server` are reachable from the host itself and from nowhere else. No VPN mesh is
maintained for them. The app's own break-glass sign-in is the exception: it has a LAN door
(step 9b), because "get back in when the edge is down" is useless if it needs a shell.

`/admin/jobs` and `/health/llm` remain reachable through the tunnel, gated by the
parent-only Access application and the app's own JWT verification.

**Accepted consequence:** a fault needing a shell cannot be fixed from outside the house.

### 11. Rotating the tunnel token

Dashboard → the tunnel → **Refresh token** (or delete and recreate the tunnel). Update
`CLOUDFLARE_TUNNEL_TOKEN` in `.env` and `just tunnel-up`.

---

## Verify

```sh
H=https://chores.example.com
curl -sI $H | grep -Ei 'content-security-policy|strict-transport|x-frame'
curl -s  $H/api/v1/health                                  # {"status":"ok"} — exempt path
curl -s -o /dev/null -w '%{http_code}\n' $H/docs            # 404
curl -s -o /dev/null -w '%{http_code}\n' $H/api/v1/auth/me  # 403 — Access required now
curl -s -o /dev/null -w '%{http_code}\n' $H/api/v1/auth/login  # 404 — break-glass off the tunnel

# ...and the same break-glass path on the host itself answers for real:
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8088/api/v1/auth/login \
  -H 'content-type: application/json' -d '{"username":"parent","password":"wrong"}'   # 401
```

- Browser, private window → `https://chores.example.com` → Google → the admin dashboard
  renders with **no app password prompt**. The Access page must appear *before* the PWA
  shell, not after.
- A kid's phone, signed in to their own Google account → same URL → lands on `/me`. Hard
  reload (Ctrl+Shift+R) the first time: the installed PWA's service worker will otherwise
  serve the previous bundle.
- Sign in with a Google account that is on no Access policy → turned away at the edge. One
  that is on the policy but not in **Kids** → the app names the address and says it is not
  a member.
- Phone on cell data → install the PWA, capture a photo, submit → appears in the admin
  inbox; approve → ledger credits once.
- `curl -X POST $H/api/v1/checkin/<token> -H 'content-type: application/json' -d
  '{"lat":0,"lon":0,"accuracy":10}'` from outside → 200, no Access prompt. If this
  redirects to Google, the Bypass application (5e) is missing.
- External port scan of the host's public IP → only Cloudflare's 443; `5432` / `8088`
  refused. Those ports answer from the host itself only.
