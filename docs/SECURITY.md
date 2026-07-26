# Security model

Signal Index assumes one private owner behind HTTPS. It retains authentication because browser sessions, local agents and media URLs cross separate trust boundaries.

## Controls

- Initial account comes only from environment variables; sign-up routes do not exist.
- Passwords use Argon2id. Session JWTs live in HTTP-only SameSite cookies.
- Mutations require a matching readable CSRF cookie and request header.
- Local agent keys are accepted only in the Authorization header and never shipped to the web bundle.
- API/login fixed-window limits use Redis with an in-process safety fallback.
- S3 buckets remain private; media responses are short-lived signed URLs.
- Uploads enforce stream size, byte-signature MIME detection and optional ClamAV scanning before persistence; file extensions are not trusted.
- Fetch adapters accept only HTTP(S), reject URL credentials, validate DNS results, reject non-global addresses, and optionally require a host allowlist.
- Source collection, raw archiving and receiver capture are disabled by default.
- SQL uses SQLAlchemy expressions. FFmpeg/ffprobe use subprocess argument arrays with timeouts.
- Audit logs contain a salted IP hash, action, user, target and request ID.
- Optional WebAuthn registration and authentication use one-time, five-minute Redis challenges and persist only the credential public key and counter.
- Rotatable application secrets are AES-256-GCM encrypted at rest with a deployment-supplied master key; secret-list APIs never return ciphertext or plaintext.
- Large S3 writes use bounded multipart transfer while the bucket remains private.

## Deployment requirements

Set strong random `SESSION_SECRET`, `JWT_SECRET`, `TOOL_API_KEY`, S3 credentials and first-user password. Use HTTPS, a private network for PostgreSQL/Redis/S3, managed secret injection, restricted CORS and host settings, and production malware scanning at the upload boundary.

The repository includes a ClamAV service profile as the integration target; deployments should connect their scanner hook before accepting files from untrusted third parties.

Password login remains available; passkeys are optional and require a correctly configured HTTPS relying-party origin in production.
