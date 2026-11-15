/** Compose the OAuth callback response with headers during construction.
 * Response.redirect() creates immutable headers per the Fetch standard,
 * and adding Set-Cookie afterward throws TypeError in Workers/Node.
 */
export function ownerRedirect(redirectTo) {
  if (typeof redirectTo !== "string" || !redirectTo) {
    throw new TypeError("Missing OAuth redirect");
  }
  const location = new URL(redirectTo).href;
  return new Response(null, {
    status: 302,
    headers: {
      "location": location,
      "set-cookie": "__Host-shiori_oauth=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0",
      "cache-control": "no-store",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff"
    }
  });
}
