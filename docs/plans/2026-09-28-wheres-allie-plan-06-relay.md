# wheres_allie AWS Relay (phase 7) Implementation Plan

**Goal:** Alexa+ reaches the box at home with no home network setup. The box dials out to a small relay on AWS. The relay handles Alexa account linking (Login with Amazon plus a 6-digit pairing code) and passes MCP requests through to the box. When the box can't be reached, the relay answers with a spoken "Allie's home hub is offline" tool result instead of an HTTP error.

**Architecture:**

- **`relay/`** is a separate uv project, `wheres-allie-relay`, built on FastAPI:
  - `store.py`: DynamoDB access through boto3, plus in-memory tables that tests and local dev use instead.
  - `pairing.py`: pairing codes and rate limits.
  - `boxes.py`: the WebSocket registry and request correlation, using asyncio futures with an 8 s timeout.
  - `auth.py`: the OAuth 2.0 authorization server that Alexa talks to (PKCE S256, refresh tokens, `client_credentials`). It uses LWA to identify the user.
  - `app.py`: `WS /box`, `POST /mcp`, `GET /healthz`.
- **Box side:** `relaylink/client.py` keeps an outbound WSS link open and runs each forwarded MCP request in-process through plan 05's `handle_mcp_request`. `POST /api/pairing/code` gets a code over that link.
- **`relay/infra/`** is a CDK (Python) stack containing:
  - a VPC across 2 AZs with public subnets only and no NAT;
  - an ALB with HTTPS (ACM certificate, Route 53) and a 3600 s idle timeout;
  - one Fargate task, arm64, 0.25 vCPU / 0.5 GB;
  - 4 on-demand DynamoDB tables with TTL;
  - a Secrets Manager secret;
  - CloudWatch logs holding metadata only.

**Latency budget:** the Alexa → relay → box → relay round trip must stay under 500 ms. Task 9 builds the measurement tool and Task 20 measures p50/p95 on the real deployment. The design keeps latency low in four ways:
- **The WebSocket stays warm.** It is opened once and kept alive with 20 s pings, so no request pays for a TCP, TLS or WebSocket handshake to the box.
- **The relay runs in us-east-1**, where the Alexa+ MCP Toolkit is offered (US only).
- **No cold starts.** One Fargate task is always running; nothing is Lambda or scale-to-zero.
- **Little work per request:** two DynamoDB `GetItem` calls, about 5 ms each. `ponytail:` no cache; if Task 20 shows DynamoDB mattering, add a 60 s in-process cache of token → box.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, websockets ≥13 (asyncio API), httpx, boto3, pydantic-settings, python-multipart; pytest, pytest-asyncio, respx; AWS CDK v2 (`aws-cdk-lib`, run with `npx aws-cdk@2`); Login with Amazon; Alexa+ MCP Toolkit (`alexa-ai` CLI).

**Depends on:** plans 01–05 are executed.
- From plan 01, this plan uses:
  - the `box/` package;
  - `wheres_allie.db.connect/migrate` and `db.get_setting(conn, key, default=None)` / `db.set_setting(conn, key, value)`;
  - `Settings.relay_url` (`WA_RELAY_URL`, default `""`);
  - `api/app.py`'s `create_app(settings=None, conn=None, start_background=True)`, whose `app.state` holds `settings`, `conn`, `bus`, `ingestor` and `relay_status` (starts as `"offline"`);
  - the `@asynccontextmanager` lifespan that appends background tasks to a `tasks` list under `if start_background:` and cancels them after `yield`;
  - routers declared as `router = APIRouter()` with paths without `/api`, registered with `app.include_router(x.router, prefix="/api")`;
  - `GET /api/health` in `api/app.py`, which already returns `"relay": app.state.relay_status if settings.relay_url else "disabled"`.
- From plan 05, it uses `wheres_allie.mcp.server.handle_mcp_request`: `async (method, path, headers, body) -> (status, headers, body)`.

| Task | Description | Status | Tested | Pushed |
|------|-------------|--------|--------|--------|
| 1 | Scaffold `relay/` uv project + `config.py` | pending | no | no |
| 2 | `store.py`: DynamoDB tables + in-memory fake + expiry-on-read | pending | no | no |
| 3 | `pairing.py`: 6-digit codes, single use, 10 min; `Limiter` | pending | no | no |
| 4 | `boxes.py`: TOFU box auth, `BoxHub` correlation, offline answer | pending | no | no |
| 5 | `app.py`: `GET /healthz`, `WS /box` (hello, ping/pong, pair_request) | pending | no | no |
| 6 | `auth.py` part 1: well-known metadata + `POST /oauth/token` (code+PKCE, refresh rotation, client_credentials) | pending | no | no |
| 7 | `auth.py` part 2: `/oauth/authorize` → LWA → pairing form → redirect to Alexa | pending | no | no |
| 8 | `app.py`: `POST /mcp` bearer check + forward to the linked box | pending | no | no |
| 9 | `relay.bench`: p50/p95 latency tool for `tools/call where_is` | pending | no | no |
| 10 | Relay `Dockerfile` + local run smoke test | pending | no | no |
| 11 | Box: `relaylink/client.py` (`RelayLink`, `ensure_identity`) | pending | no | no |
| 12 | Box: start the link in the lifespan (keeps `app.state.relay_status` current), `POST /api/pairing/code` | pending | no | no |
| 13 | Box ↔ real relay integration test | pending | no | no |
| 14 | `relay/infra/` CDK stack + synth assertions | pending | no | no |
| 15 | Manual: LWA security profile | pending | no | no |
| 16 | Manual: bootstrap + deploy + fill the secret + verify | pending | no | no |
| 17 | Manual: connect the real box, get a pairing code | pending | no | no |
| 18 | Manual: register the Alexa+ MCP add-on + account linking | pending | no | no |
| 19 | Manual: end to end on the simulator, then a real device; offline check; verify assumptions | pending | no | no |
| 20 | Manual: measure round-trip latency against the 500 ms budget | pending | no | no |
| 21 | `docs/aws-integration.md` (AWS Builder mini-challenge write-up, cost, teardown) | pending | no | no |
| 22 | Phase exit: full test run + push | pending | no | no |

## Interface additions

These add to conventions §1, §2, §3 and §12. They don't change anything already defined there.

1. **Relay configuration.** Environment variables use the prefix `RELAY_`, not `WA_`, because the relay is a separate service. The class is `relay.config.Settings`.

   | Var | Default | Meaning |
   |---|---|---|
   | `RELAY_PUBLIC_URL` | (required) | e.g. `https://relay.example.com`, no trailing slash |
   | `RELAY_STORE` | `dynamodb` | `dynamodb` or `memory` (tests, local dev) |
   | `RELAY_ALEXA_CLIENT_ID` / `RELAY_ALEXA_CLIENT_SECRET` | (required) | the OAuth client that Alexa uses against *our* server |
   | `RELAY_ALEXA_REDIRECT_PREFIXES` | `https://pitangui.amazon.com/,https://layla.amazon.com/,https://alexa.amazon.co.jp/` | allowed `redirect_uri` prefixes (comma-separated) |
   | `RELAY_LWA_CLIENT_ID` / `RELAY_LWA_CLIENT_SECRET` | (required) | the LWA security profile the relay uses to identify the Amazon user |
   | `RELAY_REQUEST_TIMEOUT_S` | `8.0` | how long the relay waits for a box to answer an MCP request |

   Run it with `uvicorn --factory relay.app:create_app`. The signature is `create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI`.

2. **Extra relay HTTP routes**, beyond conventions §12:
   - `GET /oauth/lwa/callback`: the LWA return URL.
   - `POST /oauth/pair`: the pairing-code form.
   - `GET /.well-known/oauth-protected-resource` and `GET /.well-known/oauth-protected-resource/mcp` (RFC 9728, required by the Alexa+ toolkit).
   - `GET /.well-known/oauth-authorization-server` (RFC 8414).

   `/oauth/token` accepts `authorization_code` (with PKCE S256), `refresh_token` (rotating: each use returns a new refresh token and invalidates the old one) and `client_credentials`. Clients authenticate with HTTP Basic or with the POST body.

   **RFC 8707 `resource`.** The relay's single resource is `RELAY_PUBLIC_URL + "/mcp"`.
   - `GET /oauth/authorize` requires `resource` to equal it; otherwise it shows a 400 page and never redirects.
   - `POST /oauth/token` requires it for `authorization_code` and `client_credentials`, and returns `{"error":"invalid_target"}` if it is missing or different. `refresh_token` may omit it (Alexa doesn't send it there); if present, it must match.
   - Every `code`, `access`, `refresh` and `service` token stores `resource`. `POST /mcp` accepts a token only when its stored `resource` equals the relay's own.

   **Unauthenticated `POST /mcp`** returns `401` with an empty body and **no `WWW-Authenticate` header**. The toolkit's Authentication page lists "`WWW-Authenticate` headers in 401 responses" as unsupported: https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html

3. **Contents of the `tokens` table** (conventions §12). `kind` is one of:
   - `login`: an in-progress linking session. The value is a nonce, also set as the `wa_login` cookie. Attributes: `redirect_uri`, `state`, `code_challenge`, `resource`, and `amazon_user_id` once LWA has returned. Expires after 900 s.
   - `code`: our authorization code. Attributes: `amazon_user_id`, `redirect_uri`, `code_challenge`, `resource`. Expires after 300 s.
   - `access`: 3600 s, with `amazon_user_id` and `resource`.
   - `refresh`: 180 days, with `amazon_user_id` and `resource`.
   - `service`: a `client_credentials` token, 3600 s, with `resource` and no user.

   Helper signatures in `relay.auth`: `issue_tokens(store, amazon_user_id, resource) -> dict` and `lookup_access(store, token, resource) -> dict | None`.

   `token_hash` is always `sha256(token)` as hex, and `expires_at` is integer epoch seconds. DynamoDB table names are `wheres-allie-<table>`. `pair_codes.code` is stored in plaintext, because 6 digits aren't worth hashing. Rate limits protect it instead: 5 wrong codes per Amazon user per 10 min, and 30 attempts per minute globally. `boxes.secret_hash` is `sha256(box_secret)`.

4. **Relay protocol additions** (conventions §12):
   - The relay's `{"type":"error"}` reply to a `pair_request` carries the request's `req_id`, for example `{"type":"error","req_id":"…","reason":"rate_limited"}`. Each box gets 5 codes per minute.
   - The box sends `ping` every 20 s. Both sides answer `ping` with `pong`. Either side drops the link after 60 s with no frame.
   - The relay forwards only these request headers: `content-type`, `accept`, `mcp-protocol-version`, `mcp-session-id`. It never forwards `authorization`.
   - It returns only these response headers: `content-type`, `mcp-session-id`.

5. **Offline answer.** When the box isn't connected, or doesn't answer within `RELAY_REQUEST_TIMEOUT_S`, the relay replies with HTTP 200 and a JSON body:
   - For `tools/call`: `{"jsonrpc":"2.0","id":<id>,"result":{"content":[{"type":"text","text":OFFLINE_TEXT}],"isError":false}}`.
   - For other requests: `{"jsonrpc":"2.0","id":<id>,"error":{"code":-32000,"message":OFFLINE_TEXT}}`.
   - For notifications: HTTP 202 with an empty body.

   `OFFLINE_TEXT` is `"Allie's home hub is offline right now. Check that the box at home is plugged in and online, then ask again."`

6. **Service tokens** (`client_credentials`) may call only the catalog methods: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `resources/list`, `resources/templates/list`, `resources/read`, `prompts/list`. The relay forwards these to any connected box, because the catalog is the same on every box. Any other method gets 403.

7. **Box additions:**
   - `wheres_allie.relaylink.client`:
     - `RelayLink(url, box_id, box_secret, handler, version, on_status=…)` with `.run()`, `.status` (`"connected"` or `"offline"`, also reported through `on_status(status)` on every change) and `async .request_pair_code() -> {code, expires_at}`.
     - `RelayUnavailable`.
     - `ensure_identity(conn) -> (box_id, box_secret)`. It uses `db.get_setting`/`db.set_setting` with keys `box_id` (uuid4) and `box_secret` (`secrets.token_hex(16)`), generated once.
     - `start_relay_link(app, url, conn) -> asyncio.Task | None`. It sets `app.state.relay` (None when `url` is empty), and the link keeps plan 01's `app.state.relay_status` current. `/api/health` needs no change.
   - `POST /api/pairing/code` returns 409 when `WA_RELAY_URL` is empty and 503 when the relay is offline.

8. **Latency tool.** `relay.bench.bench(mcp_url, token, n=50) -> {n, p50_ms, p95_ms, max_ms}`. It sends a warm-up call first, and raises `RuntimeError` if the box answers with OFFLINE_TEXT. The CLI is `uv run python -m relay.bench --url https://<domain> --box-id <uuid> [-n 50]`. It links a throwaway user `bench:<box_id>`, mints a 10-minute access token directly in DynamoDB (you need AWS credentials), and deletes both afterwards.

9. **Dependencies.** The relay adds `python-multipart` (for form parsing). The relay's `pyproject.toml` has a dependency group `infra = ["aws-cdk-lib>=2.150", "constructs>=10"]`, used only by `relay/infra` and `tests/test_infra.py`.

## Assumptions about Alexa+ account linking

Sources, read on 2026-09-28:
- Authentication: https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html
- Account linking: https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html
- Overview: https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html
- Login with Amazon authorization code grant: https://developer.amazon.com/docs/login-with-amazon/authorization-code-grant.html

Task 19 verifies every item below against real traffic, using the relay's metadata logs.

- **Documented:**
  - Authorization-code grant only, and PKCE S256 is mandatory (deployment is blocked otherwise).
  - A refresh token must come back with every access token.
  - `/.well-known/oauth-protected-resource` is required.
  - Alexa has several redirect URIs, and the server must use exactly the value Alexa sends.
  - `resource` is sent on authorize and on the code exchange, but not on refresh. It is the "canonical URI of the MCP server (prevents token misuse)" and must match the registered MCP server URI. We enforce it and bind tokens to it (RFC 8707).
  - Tokens arrive as `Authorization: Bearer`, and a tool call without a valid token must get 401 or 403.
  - "`WWW-Authenticate` headers in 401 responses" are listed as unsupported, so our 401 has no such header (tested in Task 8).
  - A separate `client_credentials` "service tier" (scope `mcp:service`, HTTP Basic client authentication, no refresh token) is described as "foundational" and is used for `initialize` and `tools/list`.
- **Not documented, so assumed:**
  - (A1) The exact redirect-URI hosts. We assume they are the classic account-linking hosts `pitangui.amazon.com`, `layla.amazon.com` and `alexa.amazon.co.jp`. You can override them with the CDK context `redirect_prefixes`. Every `redirect_uri` that reaches `/oauth/authorize` is logged.
  - (A2) Whether `client_credentials` is actually called for an add-on that also has account linking. We support it anyway.
  - (A3) Whether the toolkit reads `/.well-known/oauth-authorization-server` or asks for the endpoints in the CLI. We serve the metadata and also give the URLs to the CLI.
  - (A4) Alexa's own tool-call timeout. We assume it is longer than 8 s.
  - (A5) A result with `isError: false` and plain text gets spoken.
  - (A6) The exact `resource` string Alexa sends. We assume it is exactly `https://<domain>/mcp`, the URL registered in Task 18, with no trailing slash. A mismatch shows up as "Unknown resource" on the authorize page, and every value is logged (`grep "authorize redirect_uri"`).
  - (A7) The CLI prompts. The package name `@alexa-ai/cli` and the `configure` / `new mcp` / `deploy` flow come from plan 01's doc research, not from the pages above. `configure-account-linking` does appear on the Account Linking page.
  - (A8) Latency. The docs give no response-time limit. The team's budget is under 500 ms round trip, and Task 20 measures it.

---

### Task 1: Scaffold `relay/` uv project + `config.py`

**Files:**
- Create: `relay/pyproject.toml`, `relay/src/relay/__init__.py`, `relay/src/relay/config.py`, `relay/tests/conftest.py`, `relay/tests/test_config.py`

**Step 1: Write failing test**

Create `relay/pyproject.toml`:
```toml
[project]
name = "wheres-allie-relay"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]",
  "websockets>=13",
  "httpx",
  "boto3",
  "pydantic-settings",
  "python-multipart",
]

[dependency-groups]
dev = ["pytest", "pytest-asyncio", "respx", "ruff"]
infra = ["aws-cdk-lib>=2.150", "constructs>=10"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/relay"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

Create an empty `relay/src/relay/__init__.py`.

`relay/tests/conftest.py`:
```python
import pytest

from relay.config import Settings


@pytest.fixture
def settings():
    return Settings(
        public_url="https://relay.test",
        store="memory",
        alexa_client_id="alexa-client",
        alexa_client_secret="alexa-secret",
        lwa_client_id="lwa-client",
        lwa_client_secret="lwa-secret",
        request_timeout_s=0.5,
    )
```

`relay/tests/test_config.py`:
```python
from relay.config import Settings


def test_settings_from_env(monkeypatch):
    for k, v in {
        "RELAY_PUBLIC_URL": "https://r.example",
        "RELAY_ALEXA_CLIENT_ID": "a",
        "RELAY_ALEXA_CLIENT_SECRET": "b",
        "RELAY_LWA_CLIENT_ID": "c",
        "RELAY_LWA_CLIENT_SECRET": "d",
    }.items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert s.public_url == "https://r.example"
    assert s.store == "dynamodb"
    assert s.request_timeout_s == 8.0
    assert s.alexa_redirect_prefixes.startswith("https://pitangui.amazon.com/")
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv sync && uv run pytest -q
```
Expected: `ModuleNotFoundError: No module named 'relay.config'`.

**Step 3: Implement**

`relay/src/relay/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELAY_")

    public_url: str  # e.g. https://relay.example.com (no trailing slash)
    store: str = "dynamodb"  # "dynamodb" | "memory" (tests, local dev)
    alexa_client_id: str
    alexa_client_secret: str
    # Alexa has several redirect URIs (one per device region); accept any under these prefixes.
    alexa_redirect_prefixes: str = (
        "https://pitangui.amazon.com/,https://layla.amazon.com/,https://alexa.amazon.co.jp/"
    )
    lwa_client_id: str
    lwa_client_secret: str
    request_timeout_s: float = 8.0
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q
```
Expected: `1 passed`.

**Step 5: Commit**
```bash
git add relay/pyproject.toml relay/uv.lock relay/src relay/tests
git commit -m "feat: scaffold relay uv project and settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: `store.py`

**Files:**
- Create: `relay/src/relay/store.py`, `relay/tests/test_store.py`

**Step 1: Write failing test**

`relay/tests/test_store.py`:
```python
import time

from relay.store import Store, sha256


def test_put_get_delete():
    s = Store.memory()
    s.put("links", {"amazon_user_id": "amzn1.u", "box_id": "b1"})
    assert s.get("links", "amzn1.u") == {"amazon_user_id": "amzn1.u", "box_id": "b1"}
    s.delete("links", "amzn1.u")
    assert s.get("links", "amzn1.u") is None


def test_expired_items_are_invisible():
    s = Store.memory()
    s.put("pair_codes", {"code": "123456", "box_id": "b", "expires_at": int(time.time()) - 1})
    assert s.get("pair_codes", "123456") is None


def test_sha256_is_hex():
    assert sha256("x") == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_store.py
```
Expected: `ModuleNotFoundError: No module named 'relay.store'`.

**Step 3: Implement**

`relay/src/relay/store.py`. `MemoryTable` implements the same three boto3 `Table` methods that `Store` calls, so prod and tests run the same code:
```python
"""DynamoDB persistence (conventions §12). Tests and local dev use the in-memory tables."""

import hashlib
import time

# table -> partition key. Deployed table names are f"wheres-allie-{table}" (infra/stack.py).
TABLES = {"boxes": "box_id", "pair_codes": "code", "links": "amazon_user_id", "tokens": "token_hash"}


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class MemoryTable:
    """The three boto3 Table methods Store uses (boto3 argument spelling), backed by a dict."""

    def __init__(self, key: str):
        self.key = key
        self.items: dict[str, dict] = {}

    def get_item(self, Key: dict) -> dict:
        item = self.items.get(Key[self.key])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item: dict) -> None:
        self.items[Item[self.key]] = dict(Item)

    def delete_item(self, Key: dict) -> None:
        self.items.pop(Key[self.key], None)


class Store:
    def __init__(self, tables: dict):
        self.tables = tables

    @classmethod
    def memory(cls) -> "Store":
        return cls({name: MemoryTable(key) for name, key in TABLES.items()})

    @classmethod
    def dynamodb(cls) -> "Store":
        import boto3

        db = boto3.resource("dynamodb")
        return cls({name: db.Table(f"wheres-allie-{name}") for name in TABLES})

    def get(self, table: str, key: str) -> dict | None:
        item = self.tables[table].get_item(Key={TABLES[table]: key}).get("Item")
        # DynamoDB TTL deletes lazily (up to ~48 h late), so expiry is always checked on read.
        if item and "expires_at" in item and int(item["expires_at"]) <= time.time():
            return None
        return item

    def put(self, table: str, item: dict) -> None:
        self.tables[table].put_item(Item=item)

    def delete(self, table: str, key: str) -> None:
        self.tables[table].delete_item(Key={TABLES[table]: key})
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q tests/test_store.py
```
Expected: `3 passed`.

**Step 5: Commit**
```bash
git add relay/src/relay/store.py relay/tests/test_store.py
git commit -m "feat: relay store with DynamoDB tables and in-memory fake

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: `pairing.py`

**Files:**
- Create: `relay/src/relay/pairing.py`, `relay/tests/test_pairing.py`

**Step 1: Write failing test**

`relay/tests/test_pairing.py`:
```python
import time

from relay.pairing import Limiter, issue_code, redeem_code
from relay.store import Store


def test_issue_and_redeem_once():
    s = Store.memory()
    code, expires_at = issue_code(s, "box-1")
    assert len(code) == 6 and code.isdigit()
    assert 590 <= expires_at - time.time() <= 600
    assert redeem_code(s, code) == "box-1"
    assert redeem_code(s, code) is None


def test_expired_code_fails():
    s = Store.memory()
    code, _ = issue_code(s, "box-1")
    s.tables["pair_codes"].items[code]["expires_at"] = int(time.time()) - 1
    assert redeem_code(s, code) is None


def test_limiter():
    lim = Limiter(max_hits=2, window_s=60)
    assert lim.hit("u") and lim.hit("u")
    assert not lim.hit("u")
    assert lim.hit("other")
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_pairing.py
```
Expected: `ModuleNotFoundError: No module named 'relay.pairing'`.

**Step 3: Implement**

`relay/src/relay/pairing.py`:
```python
"""6-digit pairing codes (box -> GUI -> user types it on the account-linking page)."""

import secrets
import time

from relay.store import Store

CODE_TTL_S = 600


def issue_code(store: Store, box_id: str) -> tuple[str, int]:
    while True:
        code = f"{secrets.randbelow(10**6):06d}"
        if store.get("pair_codes", code) is None:
            break
    expires_at = int(time.time()) + CODE_TTL_S
    store.put("pair_codes", {"code": code, "box_id": box_id, "expires_at": expires_at})
    return code, expires_at


def redeem_code(store: Store, code: str) -> str | None:
    """Single use: returns the box_id and deletes the code, or None."""
    item = store.get("pair_codes", code)
    if item is None:
        return None
    store.delete("pair_codes", code)
    return item["box_id"]


class Limiter:
    """Sliding-window rate limit.

    ponytail: in-memory and per-process; correct for the single Fargate task. Move to a
    DynamoDB counter if the service ever runs more than one task.
    """

    def __init__(self, max_hits: int, window_s: float):
        self.max_hits, self.window_s = max_hits, window_s
        self.hits: dict[str, list[float]] = {}

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self.hits.get(key, []) if now - t < self.window_s]
        allowed = len(recent) < self.max_hits
        if allowed:
            recent.append(now)
        self.hits[key] = recent
        return allowed
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q tests/test_pairing.py
```
Expected: `3 passed`.

**Step 5: Commit**
```bash
git add relay/src/relay/pairing.py relay/tests/test_pairing.py
git commit -m "feat: relay pairing codes and rate limiter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `boxes.py`

**Files:**
- Create: `relay/src/relay/boxes.py`, `relay/tests/test_boxes.py`

**Step 1: Write failing test**

`relay/tests/test_boxes.py`:
```python
import asyncio
import base64
import json

from relay.boxes import OFFLINE_TEXT, BoxHub, check_box, offline_response
from relay.store import Store

CALL = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                   "params": {"name": "where_is", "arguments": {}}}).encode()


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def test_check_box_trust_on_first_use():
    s = Store.memory()
    assert check_box(s, "b1", "a" * 32)
    assert check_box(s, "b1", "a" * 32)
    assert not check_box(s, "b1", "b" * 32)
    assert s.get("boxes", "b1")["secret_hash"] != "a" * 32  # hashed at rest


def test_offline_tool_call_is_a_spoken_result():
    status, headers, body = offline_response(CALL)
    assert status == 200 and headers["content-type"] == "application/json"
    msg = json.loads(body)
    assert msg["id"] == 7
    assert msg["result"]["content"][0]["text"] == OFFLINE_TEXT


def test_offline_other_method_is_jsonrpc_error_and_notification_is_202():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    assert json.loads(offline_response(body)[2])["error"]["message"] == OFFLINE_TEXT
    note = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
    assert offline_response(note) == (202, {}, b"")


async def test_forward_round_trip():
    hub, ws = BoxHub(timeout_s=1), FakeWs()
    hub.attach("b1", ws)
    task = asyncio.create_task(hub.forward("b1", {"accept": "application/json"}, CALL))
    await asyncio.sleep(0)
    req = ws.sent[0]
    assert req["type"] == "mcp_request" and base64.b64decode(req["body_b64"]) == CALL
    hub.resolve("b1", {"type": "mcp_response", "id": req["id"], "status": 200,
                       "headers": {"content-type": "application/json"},
                       "body_b64": base64.b64encode(b'{"ok":1}').decode()})
    assert await task == (200, {"content-type": "application/json"}, b'{"ok":1}')
    assert hub.pending == {}


async def test_forward_ignores_response_from_other_box_and_times_out():
    hub, ws = BoxHub(timeout_s=0.1), FakeWs()
    hub.attach("b1", ws)
    task = asyncio.create_task(hub.forward("b1", {}, CALL))
    await asyncio.sleep(0)
    hub.resolve("b2", {"id": ws.sent[0]["id"], "status": 200, "body_b64": ""})
    status, _, body = await task
    assert status == 200 and OFFLINE_TEXT in body.decode()


async def test_forward_unknown_box_is_offline():
    _, _, body = await BoxHub().forward(None, {}, CALL)
    assert OFFLINE_TEXT in body.decode()


def test_detach_only_removes_same_socket():
    hub, a, b = BoxHub(), FakeWs(), FakeWs()
    hub.attach("b1", a)
    assert hub.attach("b1", b) is a
    hub.detach("b1", a)
    assert hub.boxes["b1"] is b
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_boxes.py
```
Expected: `ModuleNotFoundError: No module named 'relay.boxes'`.

**Step 3: Implement**

`relay/src/relay/boxes.py`:
```python
"""Connected boxes: registry, request/response correlation, offline answers."""

import asyncio
import base64
import hmac
import json
import logging
import time
import uuid

from starlette.websockets import WebSocketDisconnect

from relay.store import Store, sha256

log = logging.getLogger("relay.boxes")

OFFLINE_TEXT = (
    "Allie's home hub is offline right now. "
    "Check that the box at home is plugged in and online, then ask again."
)


def check_box(store: Store, box_id: str, box_secret: str) -> bool:
    """Trust on first use: the first hello registers the secret, later hellos must match it.

    ponytail: plain put, no conditional write; a race needs two boxes with the same random UUID.
    """
    secret_hash = sha256(box_secret)
    item = store.get("boxes", box_id)
    if item is not None and not hmac.compare_digest(item["secret_hash"], secret_hash):
        return False
    store.put("boxes", {"box_id": box_id, "secret_hash": secret_hash, "last_seen": int(time.time())})
    return True


def offline_response(body: bytes) -> tuple[int, dict, bytes]:
    """A JSON-RPC answer that Alexa can speak, instead of an HTTP error."""
    try:
        req = json.loads(body)
    except ValueError:
        req = None
    if not isinstance(req, dict) or "id" not in req:  # notification or junk: nothing to answer
        return 202, {}, b""
    if req.get("method") == "tools/call":
        payload = {"jsonrpc": "2.0", "id": req["id"],
                   "result": {"content": [{"type": "text", "text": OFFLINE_TEXT}], "isError": False}}
    else:
        payload = {"jsonrpc": "2.0", "id": req["id"],
                   "error": {"code": -32000, "message": OFFLINE_TEXT}}
    return 200, {"content-type": "application/json"}, json.dumps(payload).encode()


class BoxHub:
    def __init__(self, timeout_s: float = 8.0):
        self.timeout_s = timeout_s
        self.boxes: dict[str, object] = {}  # box_id -> starlette WebSocket
        self.pending: dict[str, tuple[str, asyncio.Future]] = {}  # request id -> (box_id, future)

    def attach(self, box_id: str, ws) -> object | None:
        """Register a connection; returns the connection it replaced, if any."""
        old = self.boxes.get(box_id)
        self.boxes[box_id] = ws
        return old

    def detach(self, box_id: str, ws) -> None:
        if self.boxes.get(box_id) is ws:
            del self.boxes[box_id]

    def any_box(self) -> str | None:
        return next(iter(self.boxes), None)

    def resolve(self, box_id: str, frame: dict) -> None:
        entry = self.pending.get(frame.get("id"))
        if entry and entry[0] == box_id and not entry[1].done():
            entry[1].set_result(frame)

    async def forward(self, box_id: str | None, headers: dict, body: bytes) -> tuple[int, dict, bytes]:
        ws = self.boxes.get(box_id) if box_id else None
        if ws is None:
            return offline_response(body)
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = (box_id, fut)
        try:
            await ws.send_json({"type": "mcp_request", "id": rid, "method": "POST", "path": "/mcp",
                                "headers": headers, "body_b64": base64.b64encode(body).decode()})
            frame = await asyncio.wait_for(fut, self.timeout_s)
        except (TimeoutError, OSError, RuntimeError, WebSocketDisconnect) as e:
            log.warning("box %s: no answer (%s)", box_id, type(e).__name__)
            return offline_response(body)
        finally:
            self.pending.pop(rid, None)
        return frame["status"], frame.get("headers", {}), base64.b64decode(frame.get("body_b64", ""))
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q tests/test_boxes.py
```
Expected: `7 passed`.

**Step 5: Commit**
```bash
git add relay/src/relay/boxes.py relay/tests/test_boxes.py
git commit -m "feat: relay box registry, request correlation, offline answer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: `app.py`: `/healthz` + `WS /box`

**Files:**
- Create: `relay/src/relay/app.py`, `relay/tests/test_app_box.py`

**Step 1: Write failing test**

`relay/tests/test_app_box.py`:
```python
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from relay.app import create_app
from relay.store import Store

BOX = str(uuid.uuid4())
SECRET = "ab" * 16


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings, Store.memory()))


def hello(ws, box_id=BOX, secret=SECRET):
    ws.send_json({"type": "hello", "box_id": box_id, "box_secret": secret, "version": "0.1.0"})
    return ws.receive_json()


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True, "boxes": 0}


def test_hello_welcome_ping_and_registry(client):
    with client.websocket_connect("/box") as ws:
        assert hello(ws) == {"type": "welcome"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        assert client.get("/healthz").json()["boxes"] == 1
    assert client.get("/healthz").json()["boxes"] == 0


def test_wrong_secret_rejected(client):
    with client.websocket_connect("/box") as ws:
        assert hello(ws) == {"type": "welcome"}
    with client.websocket_connect("/box") as ws:
        assert hello(ws, secret="cd" * 16) == {"type": "error", "reason": "bad hello"}
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_bad_box_id_rejected(client):
    with client.websocket_connect("/box") as ws:
        assert hello(ws, box_id="not-a-uuid")["type"] == "error"


def test_pair_request_returns_code_and_rate_limits(client):
    with client.websocket_connect("/box") as ws:
        hello(ws)
        for i in range(5):
            ws.send_json({"type": "pair_request", "req_id": f"r{i}"})
            msg = ws.receive_json()
            assert msg["type"] == "pair_code" and msg["req_id"] == f"r{i}"
            assert len(msg["code"]) == 6
        ws.send_json({"type": "pair_request", "req_id": "r5"})
        assert ws.receive_json() == {"type": "error", "req_id": "r5", "reason": "rate_limited"}
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_app_box.py
```
Expected: `ModuleNotFoundError: No module named 'relay.app'`.

**Step 3: Implement**

`relay/src/relay/app.py` (Task 6 adds the auth router, and Task 8 adds `/mcp`):
```python
"""Relay HTTP + WebSocket app. Run: uvicorn --factory relay.app:create_app"""

import asyncio
import contextlib
import logging
import uuid

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from relay.boxes import BoxHub, check_box
from relay.config import Settings
from relay.pairing import Limiter, issue_code
from relay.store import Store

log = logging.getLogger("relay")
LINK_ERRORS = (WebSocketDisconnect, TimeoutError, OSError, RuntimeError, ValueError, AttributeError)

def _valid_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = settings or Settings()
    store = store or (Store.memory() if settings.store == "memory" else Store.dynamodb())
    app = FastAPI(title="wheres_allie relay", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.store = settings, store
    app.state.hub = hub = BoxHub(settings.request_timeout_s)
    pair_limiter = Limiter(max_hits=5, window_s=60)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "boxes": len(hub.boxes)}

    @app.websocket("/box")
    async def box_link(ws: WebSocket):
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), 10)
            box_id, secret = str(hello.get("box_id", "")), str(hello.get("box_secret", ""))
            ok = (hello.get("type") == "hello" and _valid_uuid(box_id) and len(secret) >= 32
                  and await asyncio.to_thread(check_box, store, box_id, secret))
        except LINK_ERRORS:
            ok = False
        if not ok:
            await ws.send_json({"type": "error", "reason": "bad hello"})
            await ws.close(code=1008)
            return
        await ws.send_json({"type": "welcome"})
        old = hub.attach(box_id, ws)
        if old is not None:
            with contextlib.suppress(*LINK_ERRORS):
                await old.close(code=1000)
        log.info("box connected box_id=%s version=%s", box_id, hello.get("version"))
        try:
            while True:
                # The box pings every 20 s; 60 s of silence means the link is dead.
                msg = await asyncio.wait_for(ws.receive_json(), 60)
                kind = msg.get("type")
                if kind == "ping":
                    await ws.send_json({"type": "pong"})
                elif kind == "mcp_response":
                    hub.resolve(box_id, msg)
                elif kind == "pair_request":
                    if pair_limiter.hit(box_id):
                        code, expires_at = await asyncio.to_thread(issue_code, store, box_id)
                        await ws.send_json({"type": "pair_code", "req_id": msg.get("req_id"),
                                            "code": code, "expires_at": expires_at})
                    else:
                        await ws.send_json({"type": "error", "req_id": msg.get("req_id"),
                                            "reason": "rate_limited"})
        except LINK_ERRORS as e:  # disconnect, 60 s silence, or a malformed frame
            log.info("box link closed box_id=%s (%s)", box_id, type(e).__name__)
        finally:
            hub.detach(box_id, ws)

    return app
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q tests/test_app_box.py
```
Expected: `5 passed`. A Starlette `httpx` deprecation warning is fine.

**Step 5: Commit**
```bash
git add relay/src/relay/app.py relay/tests/test_app_box.py
git commit -m "feat: relay box websocket endpoint and healthz

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: `auth.py` part 1: metadata + token endpoint

**Files:**
- Create: `relay/src/relay/auth.py`, `relay/tests/test_auth_token.py`
- Modify: `relay/src/relay/app.py` (include the router)

**Step 1: Write failing test**

`relay/tests/test_auth_token.py`:
```python
import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from relay import auth
from relay.app import create_app
from relay.store import Store

VERIFIER = "v" * 50
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
REDIRECT = "https://pitangui.amazon.com/api/skill/link/M123"
RESOURCE = "https://relay.test/mcp"
BASIC = {"Authorization": "Basic " + base64.b64encode(b"alexa-client:alexa-secret").decode()}


@pytest.fixture
def store():
    return Store.memory()


@pytest.fixture
def client(settings, store):
    return TestClient(create_app(settings, store))


def make_code(store):
    return auth._put_token(store, "code", 300, amazon_user_id="amzn1.u",
                           redirect_uri=REDIRECT, code_challenge=CHALLENGE, resource=RESOURCE)


def test_well_known(client):
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm == {"resource": "https://relay.test/mcp",
                   "authorization_servers": ["https://relay.test"],
                   "scopes_supported": ["mcp:tools", "mcp:resources"]}
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["token_endpoint"] == "https://relay.test/oauth/token"
    assert asm["code_challenge_methods_supported"] == ["S256"]


def test_code_exchange_then_refresh(client, store):
    code = make_code(store)
    r = client.post("/oauth/token", headers=BASIC, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER, "resource": RESOURCE})
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["token_type"] == "Bearer" and tok["expires_in"] == 3600
    assert auth.lookup_access(store, tok["access_token"], RESOURCE)["amazon_user_id"] == "amzn1.u"
    assert auth.lookup_access(store, tok["access_token"], "https://other/mcp") is None
    # tokens are stored hashed only
    assert tok["access_token"] not in str(store.tables["tokens"].items)
    # the code is single use
    r = client.post("/oauth/token", headers=BASIC, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER, "resource": RESOURCE})
    assert r.json() == {"error": "invalid_grant"}
    # refresh, with client credentials in the body this time
    r = client.post("/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        "client_id": "alexa-client", "client_secret": "alexa-secret"})
    assert r.status_code == 200 and r.json()["refresh_token"] != tok["refresh_token"]
    assert auth.lookup_access(store, r.json()["access_token"], RESOURCE) is not None  # inherited
    r = client.post("/oauth/token", headers=BASIC, data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    assert r.json() == {"error": "invalid_grant"}


def test_bad_pkce_and_redirect_rejected(client, store):
    r = client.post("/oauth/token", headers=BASIC, data={
        "grant_type": "authorization_code", "code": make_code(store), "redirect_uri": REDIRECT,
        "code_verifier": "wrong", "resource": RESOURCE})
    assert r.json() == {"error": "invalid_grant"}
    r = client.post("/oauth/token", headers=BASIC, data={
        "grant_type": "authorization_code", "code": make_code(store),
        "redirect_uri": "https://evil.example/cb", "code_verifier": VERIFIER,
        "resource": RESOURCE})
    assert r.json() == {"error": "invalid_grant"}


def test_resource_must_match(client, store):
    for resource in ("", "https://evil.example/mcp"):
        r = client.post("/oauth/token", headers=BASIC, data={
            "grant_type": "authorization_code", "code": make_code(store), "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER, "resource": resource})
        assert r.json() == {"error": "invalid_target"}
    r = client.post("/oauth/token", headers=BASIC, data={"grant_type": "client_credentials"})
    assert r.json() == {"error": "invalid_target"}


def test_bad_client_rejected(client, store):
    r = client.post("/oauth/token", data={"grant_type": "client_credentials",
                                          "client_id": "alexa-client", "client_secret": "nope"})
    assert r.status_code == 401 and r.json() == {"error": "invalid_client"}


def test_client_credentials_gives_service_token(client, store):
    r = client.post("/oauth/token", headers=BASIC, data={
        "grant_type": "client_credentials", "scope": "mcp:service", "resource": RESOURCE})
    tok = r.json()
    assert "refresh_token" not in tok
    assert auth.lookup_access(store, tok["access_token"], RESOURCE)["kind"] == "service"


def test_unknown_grant(client):
    r = client.post("/oauth/token", headers=BASIC, data={"grant_type": "password"})
    assert r.json() == {"error": "unsupported_grant_type"}
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_auth_token.py
```
Expected: `ImportError: cannot import name 'auth' from 'relay'`.

**Step 3: Implement**

`relay/src/relay/auth.py`:
```python
"""OAuth 2.0 authorization server for Alexa+ account linking.

Alexa -> GET /oauth/authorize (PKCE S256) -> Login with Amazon -> GET /oauth/lwa/callback
-> pairing-code form -> POST /oauth/pair -> redirect to Alexa with our code
-> Alexa POST /oauth/token (authorization_code | refresh_token | client_credentials).
Every token, code and login nonce is random and stored only as its sha256 (tokens table).
Tokens are bound to the MCP resource URI (RFC 8707 `resource`), which Alexa must send on
authorize, code exchange and client_credentials; refresh inherits it.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse

from relay.store import Store, sha256

router = APIRouter()
log = logging.getLogger("relay.auth")

ACCESS_TTL_S = 3600
REFRESH_TTL_S = 180 * 86400
CODE_TTL_S = 300


def _now() -> int:
    return int(time.time())


def _put_token(store: Store, kind: str, ttl_s: int, **attrs) -> str:
    token = secrets.token_urlsafe(32)
    store.put("tokens", {"token_hash": sha256(token), "kind": kind,
                         "expires_at": _now() + ttl_s, **attrs})
    return token


def _take(store: Store, token: str, kind: str) -> dict | None:
    """Fetch a single-use token of the given kind and delete it."""
    item = store.get("tokens", sha256(token)) if token else None
    if item is None or item["kind"] != kind:
        return None
    store.delete("tokens", item["token_hash"])
    return item


def resource_uri(request: Request) -> str:
    """The one MCP resource this relay protects; every token is bound to it."""
    return f"{request.app.state.settings.public_url}/mcp"


def issue_tokens(store: Store, amazon_user_id: str, resource: str) -> dict:
    user = {"amazon_user_id": amazon_user_id, "resource": resource}
    return {
        "access_token": _put_token(store, "access", ACCESS_TTL_S, **user),
        "refresh_token": _put_token(store, "refresh", REFRESH_TTL_S, **user),
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL_S,
    }


def lookup_access(store: Store, token: str, resource: str) -> dict | None:
    """The tokens item for a bearer token (kind 'access' or 'service') bound to resource."""
    item = store.get("tokens", sha256(token)) if token else None
    if item and item["kind"] in ("access", "service") and item.get("resource") == resource:
        return item
    return None


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource(request: Request):
    url = request.app.state.settings.public_url
    return {"resource": f"{url}/mcp", "authorization_servers": [url],
            "scopes_supported": ["mcp:tools", "mcp:resources"]}


@router.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request):
    url = request.app.state.settings.public_url
    return {
        "issuer": url,
        "authorization_endpoint": f"{url}/oauth/authorize",
        "token_endpoint": f"{url}/oauth/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "scopes_supported": ["mcp:tools", "mcp:resources"],
    }


def _client_ok(request: Request, form_id: str, form_secret: str) -> bool:
    s = request.app.state.settings
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            form_id, _, form_secret = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return False
    return (hmac.compare_digest(form_id, s.alexa_client_id)
            and hmac.compare_digest(form_secret, s.alexa_client_secret))


def _oauth_error(error: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/oauth/token")
def token(request: Request, grant_type: str = Form(""), code: str = Form(""),
          redirect_uri: str = Form(""), code_verifier: str = Form(""),
          refresh_token: str = Form(""), client_id: str = Form(""),
          client_secret: str = Form(""), resource: str = Form("")):
    store, expected = request.app.state.store, resource_uri(request)
    log.info("oauth token grant=%s client_auth=%s", grant_type,
             "basic" if request.headers.get("authorization") else "post")
    if not _client_ok(request, client_id, client_secret):
        return _oauth_error("invalid_client", 401)
    # RFC 8707: required on code exchange and client_credentials, optional on refresh.
    needs_resource = grant_type in ("authorization_code", "client_credentials")
    if (needs_resource or resource) and resource != expected:
        return _oauth_error("invalid_target")
    if grant_type == "authorization_code":
        item = _take(store, code, "code")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        if (item is None or item["redirect_uri"] != redirect_uri
                or not hmac.compare_digest(challenge, item["code_challenge"])):
            return _oauth_error("invalid_grant")
        body = issue_tokens(store, item["amazon_user_id"], item["resource"])
    elif grant_type == "refresh_token":
        item = _take(store, refresh_token, "refresh")  # rotated: the old one stops working
        if item is None:
            return _oauth_error("invalid_grant")
        body = issue_tokens(store, item["amazon_user_id"], item["resource"])
    elif grant_type == "client_credentials":
        body = {"access_token": _put_token(store, "service", ACCESS_TTL_S, resource=expected),
                "token_type": "Bearer", "expires_in": ACCESS_TTL_S}
    else:
        return _oauth_error("unsupported_grant_type")
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
```

In `relay/src/relay/app.py`, add the import on the line above `from relay.boxes import BoxHub, check_box`:
```python
from relay import auth
```
and include the router right after the `pair_limiter = Limiter(max_hits=5, window_s=60)` line in `create_app`:
```python
    app.include_router(auth.router)
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q
```
Expected: `26 passed`.

**Step 5: Commit**
```bash
git add relay/src/relay/auth.py relay/src/relay/app.py relay/tests/test_auth_token.py
git commit -m "feat: relay OAuth token endpoint with PKCE, refresh rotation, client credentials

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: `auth.py` part 2: authorize → LWA → pairing code → Alexa

**Files:**
- Modify: `relay/src/relay/auth.py`
- Create: `relay/tests/test_auth_link.py`

**Step 1: Write failing test**

LWA is mocked with respx. `relay/tests/test_auth_link.py`:
```python
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from relay import auth
from relay.app import create_app
from relay.pairing import issue_code
from relay.store import Store

REDIRECT = "https://layla.amazon.com/api/skill/link/M123"
AUTHZ = {"client_id": "alexa-client", "redirect_uri": REDIRECT, "response_type": "code",
         "state": "alexa-state", "code_challenge": "abc", "code_challenge_method": "S256",
         "scope": "mcp:tools", "resource": "https://relay.test/mcp"}


@pytest.fixture
def store():
    return Store.memory()


@pytest.fixture
def client(settings, store):
    auth.user_limiter.hits.clear()
    auth.global_limiter.hits.clear()
    return TestClient(create_app(settings, store), base_url="https://relay.test")


@pytest.fixture
def lwa():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(auth.LWA_TOKEN).mock(return_value=httpx.Response(200, json={
            "access_token": "lwa-at", "token_type": "bearer"}))
        mock.get(auth.LWA_PROFILE).mock(return_value=httpx.Response(200, json={
            "user_id": "amzn1.account.ALLIE"}))
        yield mock


def login(client):
    r = client.get("/oauth/authorize", params=AUTHZ)
    assert r.status_code == 200 and "Login with Amazon" in r.text
    nonce = client.cookies.get("wa_login")
    assert nonce and f"state={nonce}" in r.text
    return nonce


def test_authorize_rejects_bad_redirect_pkce_or_resource(client):
    assert client.get("/oauth/authorize", params={**AUTHZ, "redirect_uri": "https://evil.example/"}
                      ).status_code == 400
    assert client.get("/oauth/authorize", params={**AUTHZ, "code_challenge_method": "plain"}
                      ).status_code == 400
    assert client.get("/oauth/authorize", params={**AUTHZ, "resource": "https://evil.example/mcp"}
                      ).status_code == 400


def test_full_link_flow(client, store, lwa):
    nonce = login(client)
    r = client.get("/oauth/lwa/callback", params={"code": "lwa-code", "state": nonce})
    assert r.status_code == 200 and "pairing code" in r.text
    assert lwa.calls[0].request.content.decode().count("client_secret=lwa-secret") == 1
    code, _ = issue_code(store, "box-1")
    r = client.post("/oauth/pair", data={"code": code}, follow_redirects=False)
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == REDIRECT
    q = parse_qs(loc.query)
    assert q["state"] == ["alexa-state"]
    assert store.get("links", "amzn1.account.ALLIE") == {
        "amazon_user_id": "amzn1.account.ALLIE", "box_id": "box-1"}
    item = store.get("tokens", auth.sha256(q["code"][0]))
    assert item["kind"] == "code" and item["code_challenge"] == "abc"
    assert item["resource"] == "https://relay.test/mcp"
    assert item["expires_at"] <= time.time() + 300


def test_callback_needs_matching_cookie(client, lwa):
    login(client)
    r = client.get("/oauth/lwa/callback", params={"code": "lwa-code", "state": "forged"})
    assert r.status_code == 400


def test_wrong_code_then_rate_limit(client, store, lwa):
    nonce = login(client)
    client.get("/oauth/lwa/callback", params={"code": "lwa-code", "state": nonce})
    for _ in range(5):
        r = client.post("/oauth/pair", data={"code": "000000"})
        assert r.status_code == 400 and "expire after 10 minutes" in r.text
    code, _ = issue_code(store, "box-1")
    r = client.post("/oauth/pair", data={"code": code}, follow_redirects=False)
    assert r.status_code == 429


def test_pair_without_login_fails(client):
    assert client.post("/oauth/pair", data={"code": "123456"}).status_code == 400
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_auth_link.py
```
Expected: `AttributeError: module 'relay.auth' has no attribute 'LWA_TOKEN'`.

**Step 3: Implement**

In `relay/src/relay/auth.py`, replace the import block (everything from `import base64` down to `from relay.store import Store, sha256`) with:
```python
import base64
import hashlib
import hmac
import html
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from relay.pairing import Limiter, redeem_code
from relay.store import Store, sha256

router = APIRouter()
```

Then append this to the end of `relay/src/relay/auth.py`:
```python
LOGIN_TTL_S = 900
LWA_AUTHORIZE = "https://www.amazon.com/ap/oa"
LWA_TOKEN = "https://api.amazon.com/auth/o2/token"
LWA_PROFILE = "https://api.amazon.com/user/profile"
COOKIE = "wa_login"

# ponytail: in-memory limits, fine for one task. 5 wrong codes per Amazon user per 10 min,
# 30 attempts per minute across everyone (10^6 codes, so guessing stays hopeless).
user_limiter = Limiter(max_hits=5, window_s=600)
global_limiter = Limiter(max_hits=30, window_s=60)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{title}</title>"
        "<style>body{font-family:system-ui;max-width:28rem;margin:3rem auto;padding:0 1rem;"
        "color:#1b1f24}a.btn,button{display:inline-block;background:#006fff;color:#fff;border:0;"
        "border-radius:8px;padding:.7rem 1.2rem;font-size:1rem;text-decoration:none}"
        "input{font-size:1.6rem;letter-spacing:.3rem;width:9rem;padding:.4rem}"
        ".err{color:#e5484d}</style></head>"
        f"<body><h1>{title}</h1>{body}</body></html>",
        status_code=status,
    )


def _pair_form(error: str = "", status: int = 200) -> HTMLResponse:
    err = f"<p class=err>{html.escape(error)}</p>" if error else ""
    return _page("Enter your pairing code", err + (
        "<p>On your Where's Allie box, open <b>Settings → Alexa</b> and press "
        "<b>Get pairing code</b>. Type the 6 digits here.</p>"
        "<form method=post action=/oauth/pair><input name=code inputmode=numeric "
        "pattern='[0-9]{6}' maxlength=6 required autofocus> <button>Link</button></form>"), status)


@router.get("/oauth/authorize")
def authorize(request: Request, client_id: str = "", redirect_uri: str = "",
              response_type: str = "", state: str = "", code_challenge: str = "",
              code_challenge_method: str = "", resource: str = ""):
    s = request.app.state.settings
    log.info("authorize redirect_uri=%s resource=%s", redirect_uri, resource)
    prefixes = [p for p in s.alexa_redirect_prefixes.split(",") if p]
    # Never redirect to an unchecked URI: bad requests get a plain 400 page.
    if client_id != s.alexa_client_id or not any(redirect_uri.startswith(p) for p in prefixes):
        return _page("Link failed", "<p>Unknown client or redirect URI.</p>", 400)
    if response_type != "code" or not code_challenge or code_challenge_method != "S256":
        return _page("Link failed", "<p>PKCE (S256) authorization code flow required.</p>", 400)
    if resource != resource_uri(request):
        return _page("Link failed", "<p>Unknown resource.</p>", 400)
    nonce = _put_token(request.app.state.store, "login", LOGIN_TTL_S, redirect_uri=redirect_uri,
                       state=state, code_challenge=code_challenge, resource=resource)
    lwa = LWA_AUTHORIZE + "?" + urlencode({
        "client_id": s.lwa_client_id, "scope": "profile:user_id", "response_type": "code",
        "redirect_uri": f"{s.public_url}/oauth/lwa/callback", "state": nonce})
    resp = _page("Link Where's Allie to Alexa", (
        "<p>First sign in with the Amazon account you use with Alexa. "
        "Then enter the pairing code shown by your Where's Allie box.</p>"
        f"<p><a class=btn href='{html.escape(lwa)}'>Login with Amazon</a></p>"))
    resp.set_cookie(COOKIE, nonce, max_age=LOGIN_TTL_S, httponly=True, secure=True,
                    samesite="lax", path="/oauth")
    return resp


@router.get("/oauth/lwa/callback")
async def lwa_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    s, store = request.app.state.settings, request.app.state.store
    nonce = request.cookies.get(COOKIE, "")
    login = store.get("tokens", sha256(nonce)) if nonce else None
    if error or not code or not hmac.compare_digest(nonce, state) or not login \
            or login["kind"] != "login":
        return _page("Link failed", "<p>Sign-in was cancelled or expired. "
                     "Start linking again from the Alexa app.</p>", 400)
    async with httpx.AsyncClient(timeout=10) as http:
        tok = await http.post(LWA_TOKEN, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": f"{s.public_url}/oauth/lwa/callback",
            "client_id": s.lwa_client_id, "client_secret": s.lwa_client_secret})
        if tok.status_code != 200:
            return _page("Link failed", "<p>Login with Amazon did not accept the sign-in.</p>", 502)
        prof = await http.get(LWA_PROFILE, headers={
            "Authorization": f"Bearer {tok.json()['access_token']}"})
        if prof.status_code != 200:
            return _page("Link failed", "<p>Could not read your Amazon profile.</p>", 502)
    store.put("tokens", {**login, "amazon_user_id": prof.json()["user_id"]})
    return _pair_form()


@router.post("/oauth/pair")
def pair(request: Request, code: str = Form("")):
    store = request.app.state.store
    nonce = request.cookies.get(COOKIE, "")
    login = store.get("tokens", sha256(nonce)) if nonce else None
    if not login or login["kind"] != "login" or not login.get("amazon_user_id"):
        return _page("Link failed", "<p>Your sign-in expired. "
                     "Start linking again from the Alexa app.</p>", 400)
    user = login["amazon_user_id"]
    if not (user_limiter.hit(user) and global_limiter.hit("*")):
        return _pair_form("Too many attempts. Wait a few minutes and try again.", 429)
    box_id = redeem_code(store, code.strip())
    if box_id is None:
        return _pair_form("That code didn't work. Codes expire after 10 minutes; "
                          "get a new one from your box.", 400)
    store.put("links", {"amazon_user_id": user, "box_id": box_id})
    store.delete("tokens", login["token_hash"])
    our_code = _put_token(store, "code", CODE_TTL_S, amazon_user_id=user,
                          redirect_uri=login["redirect_uri"],
                          code_challenge=login["code_challenge"], resource=login["resource"])
    sep = "&" if "?" in login["redirect_uri"] else "?"
    resp = RedirectResponse(login["redirect_uri"] + sep + urlencode(
        {"code": our_code, "state": login["state"]}), status_code=302)
    resp.delete_cookie(COOKIE, path="/oauth")
    return resp
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q && uv run ruff check src tests
```
Expected: `31 passed`, `All checks passed!`.

**Step 5: Commit**
```bash
git add relay/src/relay/auth.py relay/tests/test_auth_link.py
git commit -m "feat: relay account linking via Login with Amazon and pairing code

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: `POST /mcp` proxy

**Files:**
- Modify: `relay/src/relay/app.py` (full file below)
- Create: `relay/tests/test_app_mcp.py`

**Step 1: Write failing test**

This test runs a real uvicorn server on a free port and a fake box made with `websockets`. Starlette's `TestClient` can't serve a WebSocket and an HTTP request concurrently from two threads. `relay/tests/test_app_mcp.py`:
```python
"""/mcp proxy against a real uvicorn server and a fake box speaking the relay protocol."""

import asyncio
import base64
import json
import socket
import uuid

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect

from relay import auth
from relay.app import create_app
from relay.boxes import OFFLINE_TEXT
from relay.store import Store

BOX = str(uuid.uuid4())
CALL = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "where_is", "arguments": {}}}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
ACCEPT = "application/json, text/event-stream"
RESOURCE = "https://relay.test/mcp"  # conftest public_url + /mcp


@pytest.fixture
def store():
    return Store.memory()


@pytest.fixture
async def base_url(settings, store):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, store), port=port,
                                           log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    await task


@pytest.fixture
def user_token(store):
    store.put("links", {"amazon_user_id": "amzn1.u", "box_id": BOX})
    return auth.issue_tokens(store, "amzn1.u", RESOURCE)["access_token"]


async def fake_box(base_url, seen, answer=True):
    """Connects, then answers every mcp_request with a canned tool result."""
    async with connect(f"ws://{base_url}/box") as ws:
        await ws.send(json.dumps({"type": "hello", "box_id": BOX, "box_secret": "ab" * 16,
                                  "version": "t"}))
        assert json.loads(await ws.recv()) == {"type": "welcome"}
        seen.append("connected")
        async for raw in ws:
            req = json.loads(raw)
            seen.append(req)
            if not answer:
                continue
            reply = {"jsonrpc": "2.0", "id": json.loads(base64.b64decode(req["body_b64"]))["id"],
                     "result": {"content": [{"type": "text", "text": "Allie is on her bed"}]}}
            await ws.send(json.dumps({
                "type": "mcp_response", "id": req["id"], "status": 200,
                "headers": {"content-type": "application/json", "x-internal": "drop-me"},
                "body_b64": base64.b64encode(json.dumps(reply).encode()).decode()}))


async def with_box(base_url, answer=True):
    seen = []
    task = asyncio.create_task(fake_box(base_url, seen, answer))
    while not seen:
        await asyncio.sleep(0.02)
    return task, seen


async def post(base_url, token, msg):
    async with httpx.AsyncClient() as http:
        return await http.post(f"http://{base_url}/mcp", json=msg, headers={
            "accept": ACCEPT, "authorization": f"Bearer {token}"})


async def test_no_or_bad_token_is_401_without_www_authenticate(base_url, store):
    async with httpx.AsyncClient() as http:
        r = await http.post(f"http://{base_url}/mcp", json=CALL)
    assert r.status_code == 401 and "www-authenticate" not in r.headers
    assert (await post(base_url, "nope", CALL)).status_code == 401
    other = auth.issue_tokens(store, "amzn1.u", "https://elsewhere/mcp")["access_token"]
    assert (await post(base_url, other, CALL)).status_code == 401  # bound to another resource


async def test_forwards_to_linked_box(base_url, user_token):
    task, seen = await with_box(base_url)
    r = await post(base_url, user_token, CALL)
    task.cancel()
    assert r.status_code == 200
    assert r.json()["result"]["content"][0]["text"] == "Allie is on her bed"
    assert r.headers["content-type"] == "application/json" and "x-internal" not in r.headers
    fwd = seen[1]
    assert fwd["type"] == "mcp_request" and fwd["path"] == "/mcp"
    assert "authorization" not in fwd["headers"] and fwd["headers"]["accept"] == ACCEPT


async def test_box_offline_gives_spoken_tool_result(base_url, user_token):
    r = await post(base_url, user_token, CALL)
    assert r.status_code == 200
    assert r.json() == {"jsonrpc": "2.0", "id": 3, "result": {
        "content": [{"type": "text", "text": OFFLINE_TEXT}], "isError": False}}


async def test_box_silent_times_out_to_offline(base_url, user_token):
    task, _ = await with_box(base_url, answer=False)  # settings.request_timeout_s = 0.5
    r = await post(base_url, user_token, CALL)
    task.cancel()
    assert r.json()["result"]["content"][0]["text"] == OFFLINE_TEXT


async def test_service_token_catalog_only(base_url, store):
    service = auth._put_token(store, "service", 3600, resource=RESOURCE)
    assert (await post(base_url, service, CALL)).status_code == 403
    task, seen = await with_box(base_url)
    r = await post(base_url, service, LIST)
    task.cancel()
    assert r.status_code == 200 and seen[1]["type"] == "mcp_request"

```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_app_mcp.py
```
Expected: the tests fail with `assert 404 == 401` (and similar), because `/mcp` doesn't exist yet.

**Step 3: Implement**

Replace `relay/src/relay/app.py` with:
```python
"""Relay HTTP + WebSocket app. Run: uvicorn --factory relay.app:create_app"""

import asyncio
import contextlib
import json
import logging
import time
import uuid

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from relay import auth
from relay.boxes import BoxHub, check_box
from relay.config import Settings
from relay.pairing import Limiter, issue_code
from relay.store import Store

log = logging.getLogger("relay")
LINK_ERRORS = (WebSocketDisconnect, TimeoutError, OSError, RuntimeError, ValueError, AttributeError)

# What a service (client_credentials) token may call: discovery only, no pet data.
CATALOG_METHODS = {"initialize", "notifications/initialized", "ping", "tools/list",
                   "resources/list", "resources/templates/list", "resources/read", "prompts/list"}
FORWARD_REQUEST_HEADERS = ("content-type", "accept", "mcp-protocol-version", "mcp-session-id")
FORWARD_RESPONSE_HEADERS = ("content-type", "mcp-session-id")


def _rpc(body: bytes) -> tuple[str, str]:
    """(method, tool name) of a JSON-RPC request, for routing and metadata-only logs."""
    try:
        msg = json.loads(body)
        return str(msg.get("method", "")), str((msg.get("params") or {}).get("name", ""))
    except (ValueError, AttributeError):
        return "", ""


def _valid_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = settings or Settings()
    store = store or (Store.memory() if settings.store == "memory" else Store.dynamodb())
    app = FastAPI(title="wheres_allie relay", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.store = settings, store
    app.state.hub = hub = BoxHub(settings.request_timeout_s)
    pair_limiter = Limiter(max_hits=5, window_s=60)
    resource = f"{settings.public_url}/mcp"
    app.include_router(auth.router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "boxes": len(hub.boxes)}

    @app.post("/mcp")
    async def mcp(request: Request):
        started = time.monotonic()
        header = request.headers.get("authorization", "")
        bearer = header[7:] if header.lower().startswith("bearer ") else ""
        item = await asyncio.to_thread(auth.lookup_access, store, bearer, resource)
        if item is None:
            return Response(status_code=401)  # no WWW-Authenticate: Alexa+ doesn't support it
        body = await request.body()
        method, tool = _rpc(body)
        if item["kind"] == "service":
            if method not in CATALOG_METHODS:
                return Response(status_code=403)  # user tools need a linked account
            box_id = hub.any_box()  # ponytail: catalog is identical on every box
        else:
            link = await asyncio.to_thread(store.get, "links", item["amazon_user_id"])
            box_id = link["box_id"] if link else None
        headers = {k: v for k, v in request.headers.items() if k in FORWARD_REQUEST_HEADERS}
        status, out_headers, out = await hub.forward(box_id, headers, body)
        log.info("mcp box_id=%s method=%s tool=%s status=%s ms=%d", box_id, method, tool,
                 status, (time.monotonic() - started) * 1000)
        return Response(out, status_code=status, headers={
            k: v for k, v in out_headers.items() if k.lower() in FORWARD_RESPONSE_HEADERS})

    @app.websocket("/box")
    async def box_link(ws: WebSocket):
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), 10)
            box_id, secret = str(hello.get("box_id", "")), str(hello.get("box_secret", ""))
            ok = (hello.get("type") == "hello" and _valid_uuid(box_id) and len(secret) >= 32
                  and await asyncio.to_thread(check_box, store, box_id, secret))
        except LINK_ERRORS:
            ok = False
        if not ok:
            await ws.send_json({"type": "error", "reason": "bad hello"})
            await ws.close(code=1008)
            return
        await ws.send_json({"type": "welcome"})
        old = hub.attach(box_id, ws)
        if old is not None:
            with contextlib.suppress(*LINK_ERRORS):
                await old.close(code=1000)
        log.info("box connected box_id=%s version=%s", box_id, hello.get("version"))
        try:
            while True:
                # The box pings every 20 s; 60 s of silence means the link is dead.
                msg = await asyncio.wait_for(ws.receive_json(), 60)
                kind = msg.get("type")
                if kind == "ping":
                    await ws.send_json({"type": "pong"})
                elif kind == "mcp_response":
                    hub.resolve(box_id, msg)
                elif kind == "pair_request":
                    if pair_limiter.hit(box_id):
                        code, expires_at = await asyncio.to_thread(issue_code, store, box_id)
                        await ws.send_json({"type": "pair_code", "req_id": msg.get("req_id"),
                                            "code": code, "expires_at": expires_at})
                    else:
                        await ws.send_json({"type": "error", "req_id": msg.get("req_id"),
                                            "reason": "rate_limited"})
        except LINK_ERRORS as e:  # disconnect, 60 s silence, or a malformed frame
            log.info("box link closed box_id=%s (%s)", box_id, type(e).__name__)
        finally:
            hub.detach(box_id, ws)

    return app
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q && uv run ruff check src tests
```
Expected: `36 passed`, `All checks passed!`.

**Step 5: Commit**
```bash
git add relay/src/relay/app.py relay/tests/test_app_mcp.py
git commit -m "feat: relay MCP proxy with bearer auth and offline fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: `relay.bench` latency tool

**Files:**
- Create: `relay/src/relay/bench.py`
- Modify: `relay/tests/test_app_mcp.py` (append)

**Step 1: Write failing test**

Add `from relay.bench import bench` to the imports of `relay/tests/test_app_mcp.py`, right after `from relay.app import create_app`. Then append:
```python
async def test_bench_reports_percentiles(base_url, user_token):
    task, _ = await with_box(base_url)
    result = await bench(f"http://{base_url}/mcp", user_token, n=20)
    task.cancel()
    assert result["n"] == 20
    assert 0 < result["p50_ms"] <= result["p95_ms"] <= result["max_ms"] < 500  # local budget


async def test_bench_refuses_offline_box(base_url, user_token):
    with pytest.raises(RuntimeError, match="offline"):
        await bench(f"http://{base_url}/mcp", user_token, n=2)
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run pytest -q tests/test_app_mcp.py
```
Expected: `ModuleNotFoundError: No module named 'relay.bench'`.

**Step 3: Implement**

`relay/src/relay/bench.py`:
```python
"""Round-trip latency of Alexa -> relay -> box -> relay for `tools/call where_is`.

Budget: p95 < 500 ms. Against the deployed relay (needs AWS credentials for DynamoDB):
    uv run python -m relay.bench --url https://relay.example.com --box-id <uuid> -n 50
It links a throwaway user `bench:<box_id>` to the box, mints a 10-minute access token,
and deletes both afterwards.
"""

import argparse
import asyncio
import statistics
import time

import httpx

from relay import auth
from relay.boxes import OFFLINE_TEXT
from relay.store import Store, sha256

WHERE_IS = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "where_is", "arguments": {}}}


async def bench(mcp_url: str, token: str, n: int = 50) -> dict:
    headers = {"authorization": f"Bearer {token}",
               "accept": "application/json, text/event-stream"}
    samples = []
    async with httpx.AsyncClient(timeout=15) as http:
        for i in range(n + 1):  # the first call is a warm-up and isn't counted
            started = time.perf_counter()
            r = await http.post(mcp_url, json=WHERE_IS, headers=headers)
            elapsed = (time.perf_counter() - started) * 1000
            r.raise_for_status()
            if OFFLINE_TEXT in r.text:
                raise RuntimeError("box is offline; latency would be meaningless")
            if i:
                samples.append(elapsed)
    q = statistics.quantiles(samples, n=20)
    return {"n": n, "p50_ms": round(q[9], 1), "p95_ms": round(q[18], 1),
            "max_ms": round(max(samples), 1)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", required=True, help="relay base URL, e.g. https://relay.example.com")
    p.add_argument("--box-id", required=True)
    p.add_argument("-n", type=int, default=50)
    args = p.parse_args()
    store, user, resource = Store.dynamodb(), f"bench:{args.box_id}", f"{args.url}/mcp"
    store.put("links", {"amazon_user_id": user, "box_id": args.box_id})
    token = auth._put_token(store, "access", 600, amazon_user_id=user, resource=resource)
    try:
        print(asyncio.run(bench(resource, token, args.n)))
    finally:
        store.delete("tokens", sha256(token))
        store.delete("links", user)


if __name__ == "__main__":
    main()
```

**Step 4: Run test, verify pass**
```bash
cd relay && uv run pytest -q && uv run ruff check src tests && uv run python -m relay.bench --help
```
Expected: `38 passed`, `All checks passed!`, and a usage line `usage: bench.py [-h] --url URL --box-id BOX_ID [-n N]`.

**Step 5: Commit**
```bash
git add relay/src/relay/bench.py relay/tests/test_app_mcp.py
git commit -m "feat: relay latency bench for tools/call round trips

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Relay `Dockerfile` + local smoke test

**Files:**
- Create: `relay/Dockerfile`, `relay/.dockerignore`

**Step 1: Write failing test**

The check is a smoke command:
```bash
cd relay && docker build -t wheres-allie-relay . 
```
Expected before implementing: `failed to read dockerfile`.

**Step 2: Run test, verify failure.** Run the command above and confirm that it fails.

**Step 3: Implement**

`relay/Dockerfile`:
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
EXPOSE 8000
USER nobody
CMD ["/app/.venv/bin/uvicorn", "--factory", "relay.app:create_app", "--host", "0.0.0.0", \
     "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
```

`relay/.dockerignore`:
```
.venv
infra
tests
**/__pycache__
```

**Step 4: Run test, verify pass**
```bash
cd relay && docker build -t wheres-allie-relay . && \
docker run -d --rm --name wa-relay -p 18000:8000 -e RELAY_PUBLIC_URL=http://localhost:18000 \
  -e RELAY_STORE=memory -e RELAY_ALEXA_CLIENT_ID=a -e RELAY_ALEXA_CLIENT_SECRET=b \
  -e RELAY_LWA_CLIENT_ID=c -e RELAY_LWA_CLIENT_SECRET=d wheres-allie-relay && sleep 3 && \
curl -s localhost:18000/healthz && echo && \
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:18000/mcp; docker stop wa-relay
```
Expected: `{"ok":true,"boxes":0}` followed by `401`. If Docker isn't running (WSL), run the same check without Docker:
`cd relay && RELAY_PUBLIC_URL=http://localhost:18000 RELAY_STORE=memory RELAY_ALEXA_CLIENT_ID=a RELAY_ALEXA_CLIENT_SECRET=b RELAY_LWA_CLIENT_ID=c RELAY_LWA_CLIENT_SECRET=d uv run uvicorn --factory relay.app:create_app --port 18000`, then run the two `curl`s in another shell.

**Step 5: Commit**
```bash
git add relay/Dockerfile relay/.dockerignore
git commit -m "feat: relay container image

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Box `relaylink/client.py`

**Files:**
- Create: `box/src/wheres_allie/relaylink/__init__.py` (empty, if plan 01 didn't create it), `box/src/wheres_allie/relaylink/client.py`, `box/tests/relaylink/__init__.py` (empty, only if other test packages in `box/tests/` have one), `box/tests/relaylink/test_client.py`

**Step 1: Write failing test**

This fake relay uses `websockets.asyncio.server.serve` and speaks conventions §12. `box/tests/relaylink/test_client.py`:
```python
import asyncio
import base64
import json
import uuid

import pytest
from websockets.asyncio.server import serve

from wheres_allie.db import connect, migrate
from wheres_allie.relaylink.client import RelayLink, RelayUnavailable, ensure_identity

BOX, SECRET = str(uuid.uuid4()), "ab" * 16


class FakeRelay:
    """Speaks the relay side of conventions §12."""

    def __init__(self, welcome=True):
        self.welcome, self.frames, self.conns = welcome, [], []

    async def handler(self, ws):
        hello = json.loads(await ws.recv())
        self.frames.append(hello)
        if not self.welcome:
            await ws.send(json.dumps({"type": "error", "reason": "bad hello"}))
            return
        await ws.send(json.dumps({"type": "welcome"}))
        self.conns.append(ws)
        async for raw in ws:
            msg = json.loads(raw)
            self.frames.append(msg)
            if msg["type"] == "pair_request":
                await ws.send(
                    json.dumps(
                        {
                            "type": "pair_code",
                            "req_id": msg["req_id"],
                            "code": "123456",
                            "expires_at": 99,
                        }
                    )
                )


@pytest.fixture
async def relay():
    fake = FakeRelay()
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        fake.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/box"
        yield fake


async def echo_handler(method, path, headers, body):
    return 200, {"content-type": "application/json"}, body


async def start(link):
    task = asyncio.create_task(link.run())
    for _ in range(100):
        if link.status == "connected":
            return task
        await asyncio.sleep(0.02)
    raise AssertionError("never connected")


async def test_hello_and_mcp_round_trip(relay):
    link = RelayLink(relay.url, BOX, SECRET, echo_handler, "0.1.0")
    task = await start(link)
    assert relay.frames[0] == {
        "type": "hello",
        "box_id": BOX,
        "box_secret": SECRET,
        "version": "0.1.0",
    }
    body = base64.b64encode(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}').decode()
    await relay.conns[0].send(
        json.dumps(
            {
                "type": "mcp_request",
                "id": "r1",
                "method": "POST",
                "path": "/mcp",
                "headers": {},
                "body_b64": body,
            }
        )
    )
    await relay.conns[0].send(json.dumps({"type": "ping"}))
    for _ in range(100):
        if len(relay.frames) >= 3:
            break
        await asyncio.sleep(0.02)
    resp = next(f for f in relay.frames if f["type"] == "mcp_response")
    assert resp == {
        "type": "mcp_response",
        "id": "r1",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body_b64": body,
    }
    assert {"type": "pong"} in relay.frames
    task.cancel()


async def test_handler_crash_returns_500_and_keeps_link(relay):
    async def boom(*_):
        raise RuntimeError("tool bug")

    link = RelayLink(relay.url, BOX, SECRET, boom)
    task = await start(link)
    await relay.conns[0].send(
        json.dumps(
            {
                "type": "mcp_request",
                "id": "r2",
                "method": "POST",
                "path": "/mcp",
                "headers": {},
                "body_b64": "",
            }
        )
    )
    for _ in range(100):
        if any(f["type"] == "mcp_response" for f in relay.frames):
            break
        await asyncio.sleep(0.02)
    resp = next(f for f in relay.frames if f["type"] == "mcp_response")
    assert resp["status"] == 500 and link.status == "connected"
    task.cancel()


async def test_pair_code(relay):
    link = RelayLink(relay.url, BOX, SECRET, echo_handler)
    task = await start(link)
    assert await link.request_pair_code() == {"code": "123456", "expires_at": 99}
    task.cancel()


async def test_pair_code_when_offline():
    link = RelayLink("ws://127.0.0.1:9/box", BOX, SECRET, echo_handler)
    with pytest.raises(RelayUnavailable):
        await link.request_pair_code()


async def test_reconnects_after_drop(relay, monkeypatch):
    monkeypatch.setattr("wheres_allie.relaylink.client.random.random", lambda: 0.0)
    link = RelayLink(relay.url, BOX, SECRET, echo_handler)
    task = await start(link)
    await relay.conns[0].close()
    for _ in range(200):
        if len(relay.conns) == 2 and link.status == "connected":
            break
        await asyncio.sleep(0.02)
    assert len(relay.conns) == 2 and link.status == "connected"
    task.cancel()


async def test_rejected_hello_stays_offline():
    fake = FakeRelay(welcome=False)
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/box"
        link = RelayLink(url, BOX, SECRET, echo_handler)
        task = asyncio.create_task(link.run())
        await asyncio.sleep(0.3)
        assert link.status == "offline" and fake.frames
        task.cancel()


def test_ensure_identity_is_generated_once():
    conn = connect(":memory:")
    migrate(conn)
    box_id, secret = ensure_identity(conn)
    assert str(uuid.UUID(box_id)) == box_id
    assert len(secret) == 32 and int(secret, 16) >= 0
    assert ensure_identity(conn) == (box_id, secret)

```

**Step 2: Run test, verify failure**
```bash
cd box && uv run pytest -q tests/relaylink/test_client.py
```
Expected: `ModuleNotFoundError: No module named 'wheres_allie.relaylink.client'`.

**Step 3: Implement**

`box/src/wheres_allie/relaylink/client.py`:
```python
"""Outbound WebSocket link to the AWS relay (conventions §12). The box always dials out."""

import asyncio
import base64
import json
import logging
import random
import secrets
import sqlite3
import uuid
from collections.abc import Awaitable, Callable

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from wheres_allie.db import get_setting, set_setting

log = logging.getLogger("wheres_allie.relaylink")

PING_S = 20
DEAD_S = 60  # no frame for this long -> reconnect
MAX_BACKOFF_S = 60

# mcp.server.handle_mcp_request(method, path, headers, body) -> (status, headers, body)
McpHandler = Callable[[str, str, dict, bytes], Awaitable[tuple[int, dict, bytes]]]


def ensure_identity(conn: sqlite3.Connection) -> tuple[str, str]:
    """(box_id, box_secret) from the settings table, generated on first boot."""
    if get_setting(conn, "box_id") is None:
        set_setting(conn, "box_id", str(uuid.uuid4()))
    if get_setting(conn, "box_secret") is None:
        set_setting(conn, "box_secret", secrets.token_hex(16))
    return get_setting(conn, "box_id"), get_setting(conn, "box_secret")


class RelayUnavailable(Exception):
    pass


class RelayLink:
    def __init__(self, url: str, box_id: str, box_secret: str, handler: McpHandler,
                 version: str = "0", on_status: Callable[[str], None] = lambda status: None):
        self.url, self.box_id, self.box_secret = url, box_id, box_secret
        self.handler, self.version, self.on_status = handler, version, on_status
        self.status = "offline"  # "connected" | "offline"
        self._ws: ClientConnection | None = None
        self._pairs: dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        """Connect forever, with exponential backoff plus jitter between attempts."""
        delay = 1.0
        while True:
            try:
                async with connect(self.url, open_timeout=10, ping_interval=None) as ws:
                    await ws.send(json.dumps({"type": "hello", "box_id": self.box_id,
                                              "box_secret": self.box_secret,
                                              "version": self.version}))
                    reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if reply.get("type") != "welcome":
                        raise RelayUnavailable(reply.get("reason", "rejected"))
                    self._ws, delay = ws, 1.0
                    self._set_status("connected")
                    log.info("relay link up")
                    await self._serve(ws)
            except (OSError, TimeoutError, ValueError, WebSocketException, RelayUnavailable) as e:
                log.warning("relay link down: %s", e)
            finally:
                self._ws = None
                self._set_status("offline")
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, MAX_BACKOFF_S)

    def _set_status(self, status: str) -> None:
        self.status = status
        self.on_status(status)

    async def _serve(self, ws: ClientConnection) -> None:
        pinger = asyncio.create_task(self._ping(ws))
        try:
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), DEAD_S))
                kind = msg.get("type")
                if kind == "mcp_request":
                    task = asyncio.create_task(self._mcp(ws, msg))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                elif kind == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                elif kind in ("pair_code", "error") and msg.get("req_id") in self._pairs:
                    self._pairs[msg["req_id"]].set_result(msg)
        finally:
            pinger.cancel()

    async def _ping(self, ws: ClientConnection) -> None:
        while True:
            await asyncio.sleep(PING_S)
            await ws.send(json.dumps({"type": "ping"}))

    async def _mcp(self, ws: ClientConnection, msg: dict) -> None:
        try:
            status, headers, body = await self.handler(
                msg.get("method", "POST"), msg.get("path", "/mcp"), msg.get("headers", {}),
                base64.b64decode(msg["body_b64"]))
        except Exception:  # a broken tool must not kill the link
            log.exception("mcp request failed")
            status, headers, body = 500, {}, b""
        await ws.send(json.dumps({"type": "mcp_response", "id": msg["id"], "status": status,
                                  "headers": dict(headers),
                                  "body_b64": base64.b64encode(body).decode()}))

    async def request_pair_code(self) -> dict:
        """Ask the relay for a 6-digit pairing code -> {code, expires_at}."""
        ws = self._ws
        if ws is None:
            raise RelayUnavailable("offline")
        req_id = uuid.uuid4().hex
        self._pairs[req_id] = fut = asyncio.get_running_loop().create_future()
        try:
            await ws.send(json.dumps({"type": "pair_request", "req_id": req_id}))
            msg = await asyncio.wait_for(fut, 10)
        except (TimeoutError, WebSocketException) as e:
            raise RelayUnavailable(str(e) or "timeout") from e
        finally:
            self._pairs.pop(req_id, None)
        if msg["type"] != "pair_code":
            raise RelayUnavailable(msg.get("reason", "error"))
        return {"code": msg["code"], "expires_at": msg["expires_at"]}


```

**Step 4: Run test, verify pass**
```bash
cd box && uv run pytest -q tests/relaylink/test_client.py
```
Expected: `7 passed`. The reconnect test takes about 1–2 s.

**Step 5: Commit**
```bash
git add box/src/wheres_allie/relaylink box/tests/relaylink
git commit -m "feat: box relay link client with reconnect, ping and pairing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: Box wiring: lifespan + `POST /api/pairing/code`

**Files:**
- Modify: `box/src/wheres_allie/relaylink/client.py` (append), `box/tests/relaylink/test_client.py` (append), `box/src/wheres_allie/api/app.py`
- Create: `box/src/wheres_allie/api/routes/pairing.py`, `box/tests/api/test_pairing.py`. Put the test wherever plan 01's API route tests live, and follow its `__init__.py` convention.

**Step 1: Write failing test**

`box/tests/api/test_pairing.py` mounts the router exactly as plan 01 does, with `prefix="/api"`:
```python
import httpx
from fastapi import FastAPI

from wheres_allie.api.routes.pairing import router
from wheres_allie.relaylink.client import RelayUnavailable


class StubLink:
    def __init__(self, result=None):
        self.result = result

    async def request_pair_code(self):
        if self.result is None:
            raise RelayUnavailable("offline")
        return self.result


def make_app(link):
    app = FastAPI()
    app.include_router(router, prefix="/api")  # as plan 01 registers routers
    app.state.relay = link
    return app


async def post(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://box"
    ) as c:
        return await c.post("/api/pairing/code")


async def test_code_from_relay():
    r = await post(make_app(StubLink({"code": "123456", "expires_at": 1759100000})))
    assert r.status_code == 200 and r.json() == {"code": "123456", "expires_at": 1759100000}


async def test_disabled_and_offline():
    assert (await post(make_app(None))).status_code == 409
    assert (await post(make_app(StubLink(None)))).status_code == 503

```

Append to `box/tests/relaylink/test_client.py`:
```python
async def test_start_relay_link(relay):
    from fastapi import FastAPI

    from wheres_allie.relaylink.client import start_relay_link

    conn = connect(":memory:")
    migrate(conn)
    app = FastAPI()
    app.state.relay_status = "offline"  # plan 01's create_app sets this
    assert start_relay_link(app, "", conn) is None and app.state.relay is None
    task = start_relay_link(app, relay.url, conn)
    for _ in range(100):
        if app.state.relay_status == "connected":
            break
        await asyncio.sleep(0.02)
    assert app.state.relay_status == "connected"
    assert relay.frames[0]["box_id"] == ensure_identity(conn)[0]
    task.cancel()
    await asyncio.sleep(0.05)
    assert app.state.relay_status == "offline"
```

**Step 2: Run test, verify failure**
```bash
cd box && uv run pytest -q tests/api/test_pairing.py tests/relaylink/test_client.py
```
Expected: `ModuleNotFoundError: No module named 'wheres_allie.api.routes.pairing'` and `ImportError: cannot import name 'start_relay_link'`.

**Step 3: Implement**

a) In `box/src/wheres_allie/relaylink/client.py`, add `from importlib.metadata import version` after `from collections.abc import Awaitable, Callable`, and add `from wheres_allie.mcp.server import handle_mcp_request` directly under `from wheres_allie.db import get_setting, set_setting`. Then append:
```python
def start_relay_link(app, url: str, conn: sqlite3.Connection) -> asyncio.Task | None:
    """Set app.state.relay (None when WA_RELAY_URL is empty) and start the link task.

    The link keeps app.state.relay_status ("connected" | "offline") current for GET /api/health.
    """
    app.state.relay = None
    if not url:
        return None
    box_id, box_secret = ensure_identity(conn)
    app.state.relay = RelayLink(url, box_id, box_secret, handle_mcp_request, version("wheres-allie"),
                                on_status=lambda status: setattr(app.state, "relay_status", status))
    return asyncio.create_task(app.state.relay.run())
```

b) Create `box/src/wheres_allie/api/routes/pairing.py`:
```python
from fastapi import APIRouter, HTTPException, Request

from wheres_allie.relaylink.client import RelayUnavailable

router = APIRouter()


@router.post("/pairing/code")  # mounted with prefix="/api"
async def pairing_code(request: Request) -> dict:
    """A 6-digit code from the relay; the owner types it on the Alexa account-linking page."""
    link = getattr(request.app.state, "relay", None)
    if link is None:
        raise HTTPException(409, "Alexa link is disabled (WA_RELAY_URL is empty)")
    try:
        return await link.request_pair_code()
    except RelayUnavailable as e:
        raise HTTPException(503, "Alexa link offline") from e
```

c) Wire it into `box/src/wheres_allie/api/app.py` (plan 01's `create_app`):
- Imports:
  ```python
  from wheres_allie.api.routes import pairing
  from wheres_allie.relaylink.client import start_relay_link
  ```
- Register the router next to the other routers, above the final static mount:
  ```python
  app.include_router(pairing.router, prefix="/api")
  ```
- In `create_app`, next to where `app.state.relay_status = "offline"` is set, add `app.state.relay = None`. `POST /api/pairing/code` then answers 409, not 500, when background tasks are off.
- In the lifespan, under `if start_background:`, and *inside* the `async with srv.session_manager.run():` block that plan 05 added (`handle_mcp_request` only works while it runs), append the link task to plan 01's `tasks` list:
  ```python
  relay_task = start_relay_link(app, app.state.settings.relay_url, app.state.conn)
  if relay_task:
      tasks.append(relay_task)
  ```
  The existing shutdown loop after `yield` cancels it. Nothing else is needed. `GET /api/health` already reports `app.state.relay_status if settings.relay_url else "disabled"`, and the link keeps `app.state.relay_status` set to `"connected"` or `"offline"`.

**Step 4: Run test, verify pass**
```bash
cd box && uv run pytest -q && uv run ruff check src tests
```
Expected: the whole box suite passes, including 2 new tests in `test_pairing.py` and `test_start_relay_link`. Ruff prints `All checks passed!`.

**Step 5: Commit**
```bash
git add box/src/wheres_allie box/tests
git commit -m "feat: box starts relay link, reports relay status, serves pairing codes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Box ↔ real relay integration test

**Files:**
- Create: `box/tests/relaylink/test_relay_integration.py`

**Step 1: Write failing test**

The relay is a separate uv project. Its runtime dependencies are a subset of the box's (`boto3` is imported lazily and never needed with the memory store), so the test imports `relay/src` straight from the repo checkout. `box/tests/relaylink/test_relay_integration.py`:
```python
"""Box RelayLink against the real relay app (relay/src on sys.path, in-memory store)."""

import asyncio
import json
import socket
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn

from wheres_allie.relaylink.client import RelayLink

# The relay is a separate uv project; its deps are a subset of the box's, so import it from source.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "relay" / "src"))
relay_app = pytest.importorskip("relay.app")
relay_auth = pytest.importorskip("relay.auth")
Settings = pytest.importorskip("relay.config").Settings
Store = pytest.importorskip("relay.store").Store

CALL = {
    "jsonrpc": "2.0",
    "id": 9,
    "method": "tools/call",
    "params": {"name": "where_is", "arguments": {}},
}


async def fake_mcp(method, path, headers, body):
    req = json.loads(body)
    out = {
        "jsonrpc": "2.0",
        "id": req["id"],
        "result": {"content": [{"type": "text", "text": "Allie is in the kitchen"}]},
    }
    return 200, {"content-type": "application/json"}, json.dumps(out).encode()


async def test_box_answers_alexa_through_relay():
    store = Store.memory()
    settings = Settings(
        public_url="https://relay.test",
        store="memory",
        alexa_client_id="a",
        alexa_client_secret="b",
        lwa_client_id="c",
        lwa_client_secret="d",
        request_timeout_s=2,
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(relay_app.create_app(settings, store), port=port, log_level="warning")
    )
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    box_id = str(uuid.uuid4())
    link = RelayLink(f"ws://127.0.0.1:{port}/box", box_id, "ab" * 16, fake_mcp, "test")
    link_task = asyncio.create_task(link.run())
    while link.status != "connected":
        await asyncio.sleep(0.02)

    # the GUI's pairing code comes from the relay and redeems to this box
    pair = await link.request_pair_code()
    assert store.get("pair_codes", pair["code"])["box_id"] == box_id

    store.put("links", {"amazon_user_id": "amzn1.u", "box_id": box_id})
    token = relay_auth.issue_tokens(store, "amzn1.u", "https://relay.test/mcp")["access_token"]
    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"http://127.0.0.1:{port}/mcp",
            json=CALL,
            headers={
                "authorization": f"Bearer {token}",
                "accept": "application/json, text/event-stream",
            },
        )
    assert r.status_code == 200
    assert r.json()["result"]["content"][0]["text"] == "Allie is in the kitchen"

    link_task.cancel()
    server.should_exit = True
    await server_task
```

**Step 2: Run test, verify failure**

To prove that the test really checks something, temporarily break the box side. In `client.py`, change `"type": "mcp_response"` to `"type": "mcp_responsX"`, then run:
```bash
cd box && uv run pytest -q tests/relaylink/test_relay_integration.py
```
Expected: `AssertionError` on the `"Allie is in the kitchen"` line. The relay times out and returns OFFLINE_TEXT. Revert the typo.

**Step 3: Implement.** Nothing to implement: this test only covers Tasks 5–12.

**Step 4: Run test, verify pass**
```bash
cd box && uv run pytest -q tests/relaylink/test_relay_integration.py
```
Expected: `1 passed`.

**Step 5: Commit**
```bash
git add box/tests/relaylink/test_relay_integration.py
git commit -m "test: box relay link against the real relay app

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 14: CDK stack

**Files:**
- Create: `relay/infra/app.py`, `relay/infra/stack.py`, `relay/infra/cdk.json`, `relay/tests/test_infra.py`
- Modify: `.gitignore` (add `relay/infra/cdk.out/`)

**Step 1: Write failing test**

`relay/tests/test_infra.py` skips unless the `infra` group is installed:
```python
import importlib
import sys
from pathlib import Path

import pytest

cdk = pytest.importorskip("aws_cdk")  # installed only by `uv run --group infra`
assertions = pytest.importorskip("aws_cdk.assertions")
Match, Template = assertions.Match, assertions.Template
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra"))
RelayStack = importlib.import_module("stack").RelayStack


@pytest.fixture(scope="module")
def template():
    app = cdk.App()
    stack = RelayStack(app, "T", domain="relay.example.com", zone_name="example.com",
                       zone_id="Z123", env=cdk.Environment(account="111111111111",
                                                           region="us-east-1"))
    return Template.from_stack(stack)


def test_no_nat_and_public_subnets(template):
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::EC2::Subnet", 2)


def test_fargate_small_arm64(template):
    template.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Cpu": "256", "Memory": "512",
        "RuntimePlatform": {"CpuArchitecture": "ARM64", "OperatingSystemFamily": "LINUX"}})
    template.has_resource_properties("AWS::ECS::Service", {
        "DesiredCount": 1,
        "NetworkConfiguration": {"AwsvpcConfiguration": Match.object_like(
            {"AssignPublicIp": "ENABLED"})}})


def test_alb_https_and_long_idle_timeout(template):
    template.has_resource_properties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
        "LoadBalancerAttributes": Match.array_with([
            {"Key": "idle_timeout.timeout_seconds", "Value": "3600"}])})
    template.has_resource_properties("AWS::ElasticLoadBalancingV2::Listener",
                                     {"Protocol": "HTTPS", "Port": 443})


def test_tables_on_demand_with_ttl(template):
    template.resource_count_is("AWS::DynamoDB::Table", 4)
    for name in ("pair_codes", "tokens"):
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "TableName": f"wheres-allie-{name}", "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True}})


def test_secrets_injected_not_plain(template):
    template.has_resource_properties("AWS::ECS::TaskDefinition", {
        "ContainerDefinitions": [Match.object_like({
            "Secrets": Match.array_with([Match.object_like({"Name": "RELAY_LWA_CLIENT_SECRET"})]),
            "Environment": Match.array_with([{"Name": "RELAY_STORE", "Value": "dynamodb"}])})]})
```

**Step 2: Run test, verify failure**
```bash
cd relay && uv run --group infra pytest -q tests/test_infra.py
```
Expected: `ModuleNotFoundError: No module named 'stack'`. The first run downloads `aws-cdk-lib`, which takes about a minute.

**Step 3: Implement**

`relay/infra/stack.py`:
```python
"""One stack: VPC (public subnets, no NAT) + ALB/HTTPS + Fargate (arm64) + DynamoDB + secret."""

import json
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_secretsmanager as sm
from aws_cdk.aws_ecr_assets import Platform
from constructs import Construct

# Mirrors relay.store.TABLES (kept literal so the infra app doesn't import the service).
TABLES = {"boxes": "box_id", "pair_codes": "code", "links": "amazon_user_id", "tokens": "token_hash"}
TTL_TABLES = {"pair_codes", "tokens"}
SECRET_KEYS = ("alexa_client_id", "alexa_client_secret", "lwa_client_id", "lwa_client_secret")
RELAY_DIR = Path(__file__).resolve().parent.parent


class RelayStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, domain: str, zone_name: str,
                 zone_id: str, redirect_prefixes: str | None = None, **kwargs):
        super().__init__(scope, cid, **kwargs)
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=0, subnet_configuration=[
            ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)])
        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=zone_id, zone_name=zone_name)
        cert = acm.Certificate(self, "Cert", domain_name=domain,
                               validation=acm.CertificateValidation.from_dns(zone))

        tables = [
            ddb.Table(self, f"Table-{name}", table_name=f"wheres-allie-{name}",
                      partition_key=ddb.Attribute(name=key, type=ddb.AttributeType.STRING),
                      billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                      time_to_live_attribute="expires_at" if name in TTL_TABLES else None,
                      removal_policy=RemovalPolicy.DESTROY)
            for name, key in TABLES.items()
        ]
        # LWA values are filled in after the first deploy (docs/aws-integration.md).
        secret = sm.Secret(self, "Secret", secret_name="wheres-allie/relay",
                           generate_secret_string=sm.SecretStringGenerator(
                               secret_string_template=json.dumps({
                                   "alexa_client_id": "wheres-allie-alexa",
                                   "lwa_client_id": "set-me", "lwa_client_secret": "set-me"}),
                               generate_string_key="alexa_client_secret",
                               exclude_punctuation=True, password_length=40))

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Relay", vpc=vpc, cpu=256, memory_limit_mib=512, desired_count=1,
            min_healthy_percent=0, max_healthy_percent=100,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            assign_public_ip=True, task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            public_load_balancer=True, certificate=cert, domain_name=domain, domain_zone=zone,
            redirect_http=True, idle_timeout=Duration.seconds(3600),
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(str(RELAY_DIR), platform=Platform.LINUX_ARM64),
                container_port=8000,
                environment={"RELAY_PUBLIC_URL": f"https://{domain}", "RELAY_STORE": "dynamodb",
                             "AWS_DEFAULT_REGION": self.region,
                             **({"RELAY_ALEXA_REDIRECT_PREFIXES": redirect_prefixes}
                                if redirect_prefixes else {})},
                secrets={f"RELAY_{k.upper()}": ecs.Secret.from_secrets_manager(secret, k)
                         for k in SECRET_KEYS},
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="relay", log_retention=logs.RetentionDays.TWO_WEEKS)),
        )
        service.target_group.configure_health_check(path="/healthz")
        service.target_group.set_attribute("deregistration_delay.timeout_seconds", "10")
        for table in tables:
            table.grant_read_write_data(service.task_definition.task_role)

        CfnOutput(self, "RelayUrl", value=f"https://{domain}")
        CfnOutput(self, "BoxRelayUrl", value=f"wss://{domain}/box")
        CfnOutput(self, "ClusterName", value=service.cluster.cluster_name)
        CfnOutput(self, "ServiceName", value=service.service.service_name)
        CfnOutput(self, "SecretName", value="wheres-allie/relay")
```

`relay/infra/app.py`:
```python
import os

import aws_cdk as cdk
from stack import RelayStack

app = cdk.App()
RelayStack(
    app, "WheresAllieRelay",
    domain=app.node.get_context("domain"),        # e.g. relay.example.com
    zone_name=app.node.get_context("zone_name"),  # e.g. example.com
    zone_id=app.node.get_context("zone_id"),      # Route 53 hosted zone id, e.g. Z0123…
    redirect_prefixes=app.node.try_get_context("redirect_prefixes"),  # optional override
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-1"),
)
app.synth()
```

`relay/infra/cdk.json`:
```json
{
  "app": "uv run --group infra python app.py"
}
```

Then run `echo "relay/infra/cdk.out/" >> .gitignore` from the repo root.

**Step 4: Run test, verify pass**
```bash
cd relay && uv run --group infra pytest -q tests/test_infra.py && uv run ruff check infra tests
```
Expected: `5 passed`, `All checks passed!`. Plain `uv run pytest -q` still passes; it skips `test_infra.py` when the group isn't installed. `npx aws-cdk@2 synth` needs AWS credentials, because the VPC looks up the region's AZs. Without credentials it prints `Need to perform AWS calls … no credentials`, which is expected.

**Step 5: Commit**
```bash
git add relay/infra relay/tests/test_infra.py .gitignore
git commit -m "feat: CDK stack for the relay (Fargate arm64, ALB, DynamoDB, secret)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: Manual: LWA security profile

**Files:** none.

1. Open https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html and click **Create a New Security Profile**.
   - Name: `Where's Allie relay`
   - Description: `Identifies the Amazon account during Alexa account linking`
   - Privacy notice URL: `https://github.com/Seiraiyu/wheres_allie#privacy`
2. Open the profile, go to **Web Settings**, and click **Edit**.
   - **Allowed Origins:** `https://<domain>`, for example `https://relay.example.com`.
   - **Allowed Return URLs:** `https://<domain>/oauth/lwa/callback`.
3. Copy the **Client ID** (`amzn1.application-oa2-client.…`) and the **Client Secret** into a password manager. **Never commit them.**

Expected: the profile appears in the list with Web Settings saved. Task 16 puts these values in Secrets Manager.

### Task 16: Manual: deploy

**Files:** none.

**Prerequisites** (each line shows the expected output):
```bash
aws sts get-caller-identity --query Account --output text        # 12-digit account id
aws route53 list-hosted-zones-by-name --dns-name example.com \
  --query "HostedZones[0].[Id,Name]" --output text               # /hostedzone/Z0123…  example.com.
docker info --format '{{.ServerVersion}}'                        # a version, i.e. Docker is running
docker run --privileged --rm tonistiigi/binfmt --install arm64   # "installing: arm64 OK" (x86 hosts only)
```
You need a domain whose DNS is a Route 53 hosted zone in this account. Either:
- register one in Route 53 (Registered domains → Register; about $3–15 a year), or
- delegate a subdomain of a domain you already own: create a hosted zone for `relay.example.com` and add its 4 NS records at your current DNS provider.

Alexa needs a publicly trusted HTTPS certificate, so a bare ALB hostname won't work.

**Deploy:**
```bash
cd relay/infra
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
npx aws-cdk@2 bootstrap aws://$CDK_DEFAULT_ACCOUNT/us-east-1
npx aws-cdk@2 deploy --require-approval never \
  -c domain=relay.example.com -c zone_name=example.com -c zone_id=Z0123456789ABC
```
Expected: this takes 5–15 min, and most of that is ACM DNS validation. The output ends with:
```
Outputs:
WheresAllieRelay.BoxRelayUrl = wss://relay.example.com/box
WheresAllieRelay.ClusterName = WheresAllieRelay-…
WheresAllieRelay.RelayUrl = https://relay.example.com
WheresAllieRelay.SecretName = wheres-allie/relay
WheresAllieRelay.ServiceName = WheresAllieRelay-…
```

**Fill in the LWA values** from Task 15, then restart the task so it picks them up:
```bash
export AWS_REGION=us-east-1
read -rsp "LWA client id: " LWA_ID; echo; read -rsp "LWA client secret: " LWA_SECRET; echo
CUR=$(aws secretsmanager get-secret-value --secret-id wheres-allie/relay --query SecretString --output text)
aws secretsmanager put-secret-value --secret-id wheres-allie/relay --secret-string \
  "$(jq -c --arg i "$LWA_ID" --arg s "$LWA_SECRET" '.lwa_client_id=$i | .lwa_client_secret=$s' <<<"$CUR")"
aws ecs update-service --cluster <ClusterName> --service <ServiceName> --force-new-deployment \
  --query service.serviceName --output text
aws ecs wait services-stable --cluster <ClusterName> --services <ServiceName>
```
Expected: the service name is printed, and `wait` returns after 1–3 min.

**Verify:**
```bash
curl -s https://relay.example.com/healthz; echo
curl -s https://relay.example.com/.well-known/oauth-protected-resource; echo
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://relay.example.com/mcp
aws logs describe-log-groups --log-group-name-prefix WheresAllieRelay --query "logGroups[].logGroupName" --output text
```
Expected:
- `{"ok":true,"boxes":0}`
- `{"resource":"https://relay.example.com/mcp","authorization_servers":["https://relay.example.com"],…}`
- `401`
- one log group name. Save it as `LOG_GROUP` for Tasks 17–20.

### Task 17: Manual: connect the real box and get a pairing code

**Files:** none (`deploy/.env` is local and git-ignored).

```bash
cd deploy
grep -q '^WA_RELAY_URL=' .env && sed -i 's#^WA_RELAY_URL=.*#WA_RELAY_URL=wss://relay.example.com/box#' .env \
  || echo 'WA_RELAY_URL=wss://relay.example.com/box' >> .env
docker compose -f compose.yml up -d
sleep 10
curl -s http://wheres-allie.local/api/health; echo
curl -s -X POST http://wheres-allie.local/api/pairing/code; echo
curl -s https://relay.example.com/healthz; echo
aws logs tail "$LOG_GROUP" --since 5m | grep "box connected"
```
Expected:
- `{"ok":true,…,"relay":"connected"}`
- `{"code":"<6 digits>","expires_at":<epoch>}`
- `{"ok":true,"boxes":1}`
- a `box connected box_id=<uuid> version=…` line.

Then restart the box (`docker compose restart wheres-allie`). `/api/health` should show `offline` briefly and then `connected` again, which confirms reconnect.

### Task 18: Manual: register the Alexa+ MCP add-on with account linking

**Files:** none. Record the add-on id in `docs/friction-log.md`.

1. Read the Alexa client secret that the stack generated:
   ```bash
   aws secretsmanager get-secret-value --secret-id wheres-allie/relay --query SecretString --output text \
     | jq -r '.alexa_client_id, .alexa_client_secret'
   ```
   Expected: `wheres-allie-alexa`, then a 40-character secret.
2. Install and configure the CLI (skip this if plan 01's spike already did it on this machine), then create the add-on:
   ```bash
   npm i -g @alexa-ai/cli
   alexa-ai --version
   alexa-ai configure          # signs in with your Amazon developer account
   alexa-ai new mcp
   ```
   Expected: `alexa-ai --version` prints a version, and `configure` ends with a success message. For `new mcp`, answer the prompts:
   - add-on type: MCP server
   - server URL: `https://relay.example.com/mcp`
   - account linking: **yes**

   If the spike's add-on already exists, reuse it and change its server URL instead.
3. Configure account linking. The CLI prompts for the client secret in masked input, so paste the value from step 1 there. Never pass it as a flag.
   ```bash
   alexa-ai configure-account-linking --addon-id <id> --stage development --client-id wheres-allie-alexa
   ```
   If it also asks for endpoints, use:
   - authorization URI: `https://relay.example.com/oauth/authorize`
   - token URI: `https://relay.example.com/oauth/token`
   - client authentication: HTTP Basic
   - scopes: `mcp:tools mcp:resources`
4. `alexa-ai deploy`

   Expected: the deploy succeeds. It is blocked if PKCE S256 isn't advertised, and our metadata advertises it.
5. Note whether the CLI asked for the authorize and token URLs. If it did not, it discovered them from `/.well-known/oauth-protected-resource`, then `/.well-known/oauth-authorization-server` (assumption A3).

### Task 19: Manual: end to end, simulator → real device

**Files:** Modify `docs/friction-log.md` (append findings).

1. **Link.** In the Alexa app (same Amazon account), go to the add-on and choose **Link account**.
   - The relay page shows **Login with Amazon**. Sign in.
   - The pairing form appears.
   - On the box, open Settings → Alexa → Get pairing code (or `curl -X POST http://wheres-allie.local/api/pairing/code`) and type the code.

   Expected: "Account successfully linked". Logs: `oauth token grant=authorization_code client_auth=basic|post`.
   If the page shows **"Unknown client or redirect URI"**, run `aws logs tail "$LOG_GROUP" --since 5m | grep "authorize "`, copy the `redirect_uri` host, and redeploy:
   ```bash
   npx aws-cdk@2 deploy … -c redirect_prefixes="https://pitangui.amazon.com/,https://layla.amazon.com/,https://alexa.amazon.co.jp/,https://<new-host>/"
   ```
   This is assumption A1.
2. **Simulator.** In the developer console **Test** tab (Alexa+ simulator), ask each of the 6 intents. Each must answer from real data:
   - "Where's Allie?"
   - "What did Allie do today?"
   - "Show me Allie's timeline this morning."
   - "When did Allie last go to her water bowl?"
   - "Did Allie do anything unusual today?"
   - "Allie is on her bed now." (mark_location)

   The logs should show `mcp box_id=… method=tools/call tool=<name> status=200 ms=<n>`. Note the largest `ms`.
3. **Offline.** Run `docker compose -f deploy/compose.yml stop wheres-allie`, then ask "Where's Allie?". Expected: Alexa says the hub is offline (assumption A5). Then start the box again.
4. **Refresh.** Wait more than 1 hour, or change `ACCESS_TTL_S` temporarily in a dev deploy, and ask again. The logs show `oauth token grant=refresh_token`, and the answer still works.
5. **Real device.** Repeat step 2 on an Echo (Show, if you have one) that uses the same account. Success criterion 2 is met when all 6 intents work there.
6. **Record the assumptions** in `docs/friction-log.md` under a heading "Alexa+ account linking (relay)", with what was observed for each:
   - A1: redirect hosts seen
   - A2: was `client_credentials` called? (`grep "grant=client_credentials"`)
   - A3: did the CLI ask for the endpoints?
   - A4: largest latency that still got an answer
   - A5: offline phrasing spoken?
   - A6: `resource` value (`grep "authorize redirect_uri"`)
   - A7: CLI prompts
   - A8: see Task 20

   Then commit:
```bash
git add docs/friction-log.md
git commit -m "docs: record Alexa+ account-linking findings from relay end-to-end test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 20: Manual: measure round-trip latency (budget < 500 ms)

**Files:** Modify `docs/friction-log.md` (append a "Relay latency" table).

Run this with the real box connected (Task 17) and the relay deployed in us-east-1.

1. **Relay → box → relay, as the relay sees it.** This is the number the budget applies to, because the Alexa → relay leg is inside AWS. Drive 50 `where_is` calls through the relay. Run this from `relay/`, with AWS credentials for the relay's account:
   ```bash
   BOX_ID=$(docker compose -f ../deploy/compose.yml exec -T wheres-allie \
     sqlite3 /data/wheres_allie.db "SELECT value FROM settings WHERE key='box_id'")
   uv run python -m relay.bench --url https://relay.example.com --box-id "$BOX_ID" -n 50
   ```
   Expected: something like `{'n': 50, 'p50_ms': …, 'p95_ms': …, 'max_ms': …}`. These client-side numbers also include your internet round trip to us-east-1.

   If `sqlite3` isn't in the image, use `docker compose -f ../deploy/compose.yml exec -T wheres-allie python -c "import sqlite3; print(sqlite3.connect('/data/wheres_allie.db').execute(\"SELECT value FROM settings WHERE key='box_id'\").fetchone()[0])"` instead.

   Then read the relay's own measurement from the metadata log line `mcp … tool=where_is … ms=<n>`:
   ```bash
   QID=$(aws logs start-query --log-group-name "$LOG_GROUP" \
     --start-time $(date -d '-15 min' +%s) --end-time $(date +%s) \
     --query-string 'filter @message like /tool=where_is status=200/ | parse @message "ms=*" as ms | stats count() as n, pct(ms, 50) as p50, pct(ms, 95) as p95, max(ms) as worst' \
     --query queryId --output text)
   sleep 5; aws logs get-query-results --query-id "$QID" --query results --output table
   ```
   Expected: `n` ≥ 50, and **`p95` < 500**. Relay-side time is the relay → box → relay leg plus the box's own `where_is` work.

2. **With Alexa.** Ask "Where's Allie?" 10 times on the simulator, re-run the query above with `--start-time` set to cover that window, and record p50/p95. Also note how long the spoken answer takes to start, measured by ear or stopwatch; that number covers Alexa's own LLM time too.

3. **If p95 ≥ 500 ms**, find out where the time goes before changing anything:
   - Box time: time a call to the box's `where_is` directly on the LAN, e.g. `time curl -s -H "Authorization: Bearer $WA_LAN_TOKEN" -H 'accept: application/json, text/event-stream' -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"where_is","arguments":{}}}' http://wheres-allie.local/mcp`. If this is slow, the fix belongs in the box (plan 05), not here.
   - Home uplink: `ping` your router's WAN gateway and an AWS us-east-1 endpoint (e.g. `ping dynamodb.us-east-1.amazonaws.com`) from the box.
   - Relay: the `ms` log minus box time minus the uplink RTT. If this is above ~20 ms, add the `ponytail:` token → box cache mentioned in the header.

4. Record in `docs/friction-log.md` a table with rows `bench (client)`, `relay log (bench)` and `relay log (Alexa)`, and columns `n`, `p50`, `p95`, `max`. Include the date and where the box is (home ISP). Then commit:
```bash
git add docs/friction-log.md
git commit -m "docs: record relay round-trip latency against the 500 ms budget

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 21: `docs/aws-integration.md`

**Files:**
- Create: `docs/aws-integration.md`

**Step 1: Write failing test**
```bash
test -f docs/aws-integration.md && grep -c "^## " docs/aws-integration.md
```
**Step 2: Run test, verify failure.** Expected: exit status 1, because the file doesn't exist yet.

**Step 3: Implement.** `docs/aws-integration.md`:
````markdown
# AWS integration: the wheres_allie relay

wheres_allie runs at home, on a box on the LAN. Alexa+ needs a public HTTPS MCP endpoint. The relay on AWS connects the two without any router, DNS or tunnel setup at home: the box dials out to AWS, and AWS never dials in.

## What it does
- **Box link.** The home box opens an outbound WebSocket to `wss://<domain>/box` and authenticates with a `box_id` and `box_secret` that it generated at first boot. The relay trusts that secret on first use.
- **Account linking.** Alexa+ sends the owner to the relay's OAuth 2.0 authorization server (PKCE S256).
  - The owner signs in with **Login with Amazon**, which tells the relay their Amazon user id.
  - The owner then types the 6-digit pairing code that the box's web GUI shows.
  - The relay stores `amazon_user_id ↔ box_id` and issues its own access and refresh tokens to Alexa.
- **MCP proxy.** Alexa+ calls `POST https://<domain>/mcp` with a bearer token.
  - The relay finds the linked box and forwards the request over that box's WebSocket.
  - It waits up to 8 s and returns the box's answer unchanged.
  - If the box is offline, the relay returns a normal tool result that says so, and Alexa reads it out.

## Architecture
```
Alexa+ ──HTTPS──▶ Route 53 ─▶ ALB (ACM cert, idle timeout 3600 s)
                                 │
                                 ▼
                       ECS Fargate task (arm64, 0.25 vCPU / 0.5 GB)
                       FastAPI: /oauth/*, /mcp, /box (WebSocket), /healthz
                         │                 ▲
          DynamoDB (4 tables, on-demand)   │ outbound WSS, kept open by 20 s pings
          Secrets Manager (LWA + Alexa     │
          client credentials)          home box (docker compose)
          CloudWatch Logs (metadata)
```
The whole stack is one CDK app, `relay/infra/stack.py`. The VPC spans 2 AZs and has public subnets only; the task has a public IP, so there is no NAT gateway. That saves about $32/month for a service that only needs outbound access to ECR, DynamoDB and LWA.

Latency is budgeted at under 500 ms for Alexa → relay → box → relay. The box's WebSocket stays open (20 s pings), so no request pays for a handshake. The task always runs, so there are no cold starts. The relay lives in us-east-1, next to the US-only Alexa+ MCP Toolkit. `uv run python -m relay.bench` and a CloudWatch Logs Insights query measure p50/p95 (plan 06, Task 20).

## AWS services used
| Service | Why |
|---|---|
| ECS Fargate (Graviton/arm64) | runs the relay container with no servers to patch; arm64 is about 20% cheaper |
| Application Load Balancer | TLS termination, and WebSocket support with a 1-hour idle timeout |
| ACM + Route 53 | a free, auto-renewing certificate validated by DNS, plus the domain Alexa calls |
| DynamoDB (on-demand, TTL) | `boxes`, `pair_codes`, `links`, `tokens`. TTL expires codes and tokens without a cron job |
| Secrets Manager | the LWA client secret and Alexa client secret, injected as task environment variables |
| CloudWatch Logs | metadata logs, kept for 2 weeks |
| CDK (Python) | the whole stack in about 100 lines, deployed with `npx aws-cdk@2 deploy` |

## Security and privacy
- **No pet data at rest.** The relay stores only pairings (Amazon user id ↔ box id) and hashed tokens. Location data passes through in memory and is never written or logged.
- **Hashed secrets.** Every token, auth code, login nonce and box secret is stored as `sha256` only. Tokens are 256-bit random values.
- **Codes and tokens are short-lived and single-use.**
  - Pairing codes: 10 minutes, single use, and rate limited (5 wrong tries per user per 10 min, 30 per minute globally).
  - Auth codes: 5 minutes, single use.
  - Refresh tokens rotate on every use.
- **OAuth checks.**
  - PKCE S256 is required.
  - Every token is bound to the MCP resource `https://<domain>/mcp` (RFC 8707 `resource`). A token issued for any other resource is rejected.
  - `redirect_uri` must match an allow-list of Alexa hosts.
  - The LWA callback is bound to the browser with an HttpOnly cookie, which blocks login CSRF.
- **Logs** hold only timestamp, box_id, JSON-RPC method, tool name, status, latency and OAuth grant type. Uvicorn access logs are off.

## Deploy
Prerequisites:
- AWS CLI v2 with credentials
- Node (for `npx`)
- Docker (plus arm64 emulation on x86: `docker run --privileged --rm tonistiigi/binfmt --install arm64`)
- a Route 53 hosted zone
- an LWA security profile whose allowed return URL is `https://<domain>/oauth/lwa/callback`

```bash
cd relay/infra
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
npx aws-cdk@2 bootstrap aws://$CDK_DEFAULT_ACCOUNT/us-east-1
npx aws-cdk@2 deploy -c domain=relay.example.com -c zone_name=example.com -c zone_id=Z0123456789ABC
```
After the first deploy:
1. Put the LWA client id and secret into the `wheres-allie/relay` secret, then run `aws ecs update-service … --force-new-deployment`. `docs/plans/2026-09-28-wheres-allie-plan-06-relay.md` Task 15 has the exact commands.
2. Set `WA_RELAY_URL=wss://relay.example.com/box` for the box.
3. Register `https://relay.example.com/mcp` as the add-on's MCP server with the `alexa-ai` CLI, with account linking set to client id `wheres-allie-alexa` and the generated secret.

## Cost
These are approximate us-east-1 prices, for one box, running all month:

| Item | $/month |
|---|---|
| ALB (hours + minimal LCU) | ~17 |
| Public IPv4 addresses (2 for the ALB + 1 for the task, $0.005/h each) | ~11 |
| Fargate arm64, 0.25 vCPU + 0.5 GB | ~7 |
| Route 53 hosted zone | 0.50 |
| Secrets Manager (1 secret) | 0.40 |
| DynamoDB on-demand, CloudWatch Logs, ECR storage | < 1 |
| **Total** | **~36** (about $1.20/day) |

The design estimate was $20–25. The difference is AWS's public IPv4 charge. For a longer-lived deployment, replace the ALB with API Gateway (HTTP API for `/mcp` and `/oauth`, WebSocket API for `/box`) and move the task behind it. That removes about $28/month.

## Teardown
```bash
cd relay/infra
npx aws-cdk@2 destroy -c domain=relay.example.com -c zone_name=example.com -c zone_id=Z0123456789ABC
# Before redeploying under the same name, remove leftovers the stack does not delete immediately:
aws secretsmanager delete-secret --secret-id wheres-allie/relay --force-delete-without-recovery --region us-east-1
aws logs describe-log-groups --log-group-name-prefix WheresAllieRelay --query "logGroups[].logGroupName" --output text \
  | xargs -r -n1 aws logs delete-log-group --region us-east-1 --log-group-name
```
The DynamoDB tables use `RemovalPolicy.DESTROY` and are deleted with the stack. The `CDKToolkit` bootstrap stack remains and costs cents per month. Delete it from the CloudFormation console if you want nothing left.

## Why this counts for the AWS Builder mini-challenge
The AWS side is a real part of the product. It is what lets a typical pet owner say "Alexa, where's Allie?" from anywhere without touching their router. It is built only from managed AWS services (Fargate, ALB, ACM, Route 53, DynamoDB, Secrets Manager, CloudWatch) and defined in one reproducible CDK stack, with tests (`relay/tests/test_infra.py` asserts no NAT, arm64, HTTPS, a 3600 s idle timeout, TTL tables, and secrets that aren't plain environment variables). This document, the cost table and the teardown commands are the documentation the mini-challenge asks for.
````

**Step 4: Run test, verify pass**
```bash
test -f docs/aws-integration.md && grep -c "^## " docs/aws-integration.md
```
Expected: `8`.

**Step 5: Commit**
```bash
git add docs/aws-integration.md
git commit -m "docs: AWS relay integration write-up (AWS Builder mini-challenge)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 22: Phase exit: full test run + push

**Files:** Modify this plan's status table.

1. ```bash
   cd relay && uv run --group infra pytest -q && uv run ruff check src tests infra
   cd ../box && uv run pytest -q && uv run ruff check src tests
   ```
   Expected: relay `43 passed`; box suite all green; ruff `All checks passed!` twice.
2. Set every row of the status table to `done | yes | yes`. Rows 15–20 get `yes` only once they were really exercised on AWS or Alexa.
3. ```bash
   git add docs/plans/2026-09-28-wheres-allie-plan-06-relay.md
   git commit -m "docs: mark plan 06 (relay) complete

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   git push origin main
   ```
   Expected: the push succeeds, and CI (plan 07's workflow, if already present) is green.

## Phase exit criteria

- `relay/`: `uv run --group infra pytest -q` gives 43 passed, and ruff is clean.
- `box/`: the full suite passes, including `tests/relaylink/*` and `tests/api/test_pairing.py`.
- The relay is deployed. `https://<domain>/healthz` returns `{"ok":true,"boxes":1}` while the home box is running.
- The box's `GET /api/health` reports `"relay":"connected"`. `POST /api/pairing/code` returns a 6-digit code that expires in 10 minutes.
- Account linking (LWA sign-in, then pairing code) succeeds from the Alexa app, and a token refresh has been seen in the logs.
- All 6 tools answer by voice on the simulator and on a real Alexa+ device through the relay (success criterion 2). With the box stopped, Alexa speaks the offline message.
- The relay's CloudWatch logs contain only metadata: box_id, method, tool, status, latency, grant type, redirect_uri/resource. They contain no request or response bodies, no tokens and no query strings, because the uvicorn access log is off.
- Task 20 measured round-trip latency for `where_is`, and relay → box → relay p95 is under 500 ms. The numbers are recorded in `docs/friction-log.md`.
- `docs/aws-integration.md` is committed, and the A1–A8 findings are in `docs/friction-log.md`.
