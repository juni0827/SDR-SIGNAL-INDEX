import { api, type Envelope } from "./api";

type PublicKeyOptions = Record<string, unknown>;

function fromBase64url(value: string): ArrayBuffer {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
  const binary = atob(padded);
  return Uint8Array.from(binary, character => character.charCodeAt(0)).buffer;
}

function toBase64url(value: ArrayBuffer | null): string | null {
  if (!value) return null;
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function creationOptions(raw: PublicKeyOptions): PublicKeyCredentialCreationOptions {
  const user = raw.user as Record<string, unknown>;
  const exclude = (raw.excludeCredentials as Array<Record<string, unknown>> | undefined) ?? [];
  return {
    ...raw,
    challenge: fromBase64url(String(raw.challenge)),
    user: { ...user, id: fromBase64url(String(user.id)) },
    excludeCredentials: exclude.map(item => ({ ...item, id: fromBase64url(String(item.id)) })),
  } as PublicKeyCredentialCreationOptions;
}

function requestOptions(raw: PublicKeyOptions): PublicKeyCredentialRequestOptions {
  const allow = (raw.allowCredentials as Array<Record<string, unknown>> | undefined) ?? [];
  return {
    ...raw,
    challenge: fromBase64url(String(raw.challenge)),
    allowCredentials: allow.map(item => ({ ...item, id: fromBase64url(String(item.id)) })),
  } as PublicKeyCredentialRequestOptions;
}

export async function registerPasskey(name: string) {
  if (!window.PublicKeyCredential) throw new Error("passkeys_not_supported");
  const options = await api<Envelope<{challenge_id: string; public_key: PublicKeyOptions}>>(
    "/auth/passkeys/register/options",
    { method: "POST", body: "{}" },
  );
  const credential = await navigator.credentials.create({
    publicKey: creationOptions(options.data.public_key),
  }) as PublicKeyCredential | null;
  if (!credential) throw new Error("passkey_registration_cancelled");
  const response = credential.response as AuthenticatorAttestationResponse;
  return api("/auth/passkeys/register/complete", {
    method: "POST",
    body: JSON.stringify({
      challenge_id: options.data.challenge_id,
      name,
      credential: {
        id: credential.id,
        rawId: toBase64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
          clientDataJSON: toBase64url(response.clientDataJSON),
          attestationObject: toBase64url(response.attestationObject),
          transports: response.getTransports?.() ?? [],
        },
      },
    }),
  });
}

export async function loginWithPasskey(email: string) {
  if (!window.PublicKeyCredential) throw new Error("passkeys_not_supported");
  const options = await api<Envelope<{challenge_id: string; public_key: PublicKeyOptions}>>(
    "/auth/passkeys/login/options",
    { method: "POST", body: JSON.stringify({ email }) },
  );
  const credential = await navigator.credentials.get({
    publicKey: requestOptions(options.data.public_key),
  }) as PublicKeyCredential | null;
  if (!credential) throw new Error("passkey_login_cancelled");
  const response = credential.response as AuthenticatorAssertionResponse;
  return api("/auth/passkeys/login/complete", {
    method: "POST",
    body: JSON.stringify({
      challenge_id: options.data.challenge_id,
      credential: {
        id: credential.id,
        rawId: toBase64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
          clientDataJSON: toBase64url(response.clientDataJSON),
          authenticatorData: toBase64url(response.authenticatorData),
          signature: toBase64url(response.signature),
          userHandle: toBase64url(response.userHandle),
        },
      },
    }),
  });
}
