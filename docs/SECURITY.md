# Security model

Signal Index assumes one private owner behind HTTPS. It retains authentication because browser sessions, local agents and media URLs cross separate trust boundaries.

## Controls

- Initial account comes only from environment variables; sign-up routes do not exist.
- Passwords use Argon2id. Session JWTs live in HTTP-only SameSite cookies.
- Mutations require a matching readable CSRF cookie and request header.
- Local agent keys are accepted only in the Authorization header and never shipped to the web bundle.
- API/login fixed-window limits use Redis with an in-process safety fallback.
- S3 buckets remain private; media responses are short-lived signed URLs.
- Uploads enforce stream size and known audio signatures before persistence.
- Fetch adapters accept only HTTP(S), reject URL credentials, validate DNS results, reject non-global addresses, and optionally require a host allowlist.
- Source collection, raw archiving and receiver capture are disabled by default.
- SQL uses SQLAlchemy expressions. FFmpeg/ffprobe use subprocess argument arrays with timeouts.
- Audit logs contain a salted IP hash, action, user, target and request ID.

## Deployment requirements

Set strong random `SESSION_SECRET`, `JWT_SECRET`, `TOOL_API_KEY`, S3 credentials and first-user password. Use HTTPS, a private network for PostgreSQL/Redis/S3, managed secret injection, restricted CORS and host settings, and production malware scanning at the upload boundary.

The repository includes a ClamAV service profile as the integration target; deployments should connect their scanner hook before accepting files from untrusted third parties.

Optional WebAuthn/passkey support is an extension point rather than the default login method.
