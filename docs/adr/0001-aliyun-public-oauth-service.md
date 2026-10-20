# ADR-0001: Use a standalone public OAuth service for Aliyun Drive

## Status

Accepted

## Context

TaoSync's built-in engine accesses Aliyun Drive directly through the official OpenFile API. The original mount form required every TaoSync user to create an Open Platform application and manually provide a client ID, client secret, and refresh token. This is too difficult for ordinary users and distributes application secrets to every TaoSync instance.

The independent service must not become a file proxy or synchronization engine. TaoSync must retain direct file operations, existing storage driver behavior, token-rotation persistence, and compatibility with mounts that use their own application credentials.

## Decision

Add a standalone Python/Tornado service under `apiServer/`. The service owns the Aliyun Drive Open Platform application credentials, creates short-lived official QR authorization sessions, exchanges authorization codes, and refreshes tokens. It stores authorization sessions only in memory and allows an authorization result to be claimed once.

TaoSync exposes authenticated proxy actions for starting and polling an authorization session. A successful scan fills the Aliyun mount form with the refresh token, short-lived access token, application ID, service URL, and an HMAC refresh proof. The built-in Aliyun driver continues to call `openapi.alipan.com` directly for all drive and file operations. Only token refresh calls the public OAuth service.

The OAuth service URL is administrator configuration (`TAO_ALIYUN_AUTH_SERVER` or `aliyun_auth_server` in `data/config.ini`), not ordinary form input. HTTPS is mandatory except for loopback development URLs. Existing direct-credential mounts remain supported through `auth_mode=direct`.

## Consequences

### Positive

- Ordinary TaoSync users authorize with the Aliyun Drive app instead of creating an application.
- App secrets stay on one controlled service and never enter TaoSync databases or browsers.
- File traffic, synchronization throughput, and storage failure domains remain independent of the OAuth service.
- One-time claims, OAuth state, short TTLs, and refresh proofs reduce token disclosure risk.

### Negative

- New authorizations and future token refreshes depend on the public OAuth service being available.
- In-memory authorization sessions are lost on service restart; users must scan again.
- Changing the OAuth service signing secret requires affected users to reauthorize.
- Multi-instance service deployments need sticky routing or a shared session store.

## Alternatives Considered

**Keep credentials inside each TaoSync instance**

Rejected as the default because it preserves the hard setup flow and distributes app secrets. It remains as an advanced compatibility mode.

**Proxy all Aliyun Drive API and file traffic through the public service**

Rejected because it creates a bandwidth bottleneck, expands privacy exposure, and changes the built-in engine's failure and performance model.

**Store all user refresh tokens persistently on the public service**

Rejected because TaoSync needs the token locally for independent operation and a central token database would materially increase breach impact and operational complexity.
