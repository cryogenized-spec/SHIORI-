/**
 * Authorization form request provenance check.
 *
 * A browser can send "Origin: null" for a same-origin HTML form POST
 * when Referrer-Policy is no-referrer (or privacy settings suppress
 * the origin). Never accept an explicit foreign origin or cross-site
 * Fetch Metadata. If Origin is missing/null, demand independent
 * same-origin evidence. The caller MUST ALSO validate the matching
 * host-only HttpOnly SameSite cookie, hidden 256-bit nonce, expiring
 * KV record and owner approval secret before authorizing.
 */
export function isTrustedConsentRequest(request, issuer) {
  const expected = new URL(issuer).origin;
  const origin = request.headers.get("origin");
  const site = request.headers.get("sec-fetch-site");
  const referrer = request.headers.get("referer");

  // A protected form is only valid when submitted from this precise origin,
  // not a sibling workers.dev subdomain (which is merely same-site).
  if (site && site !== "same-origin") return false;
  if (origin && origin !== "null" && origin !== expected) return false;

  if (referrer) {
    try {
      if (new URL(referrer).origin !== expected) return false;
    } catch {
      return false;
    }
  }

  // Strongest case: the browser states our exact HTTPS origin.
  if (origin === expected) return true;

  // Some browsers intentionally supply an opaque/missing Origin for form
  // navigations. Require another browser-provided same-origin signal.
  if (site === "same-origin") return true;
  if (referrer) return true;
  return false;
}
