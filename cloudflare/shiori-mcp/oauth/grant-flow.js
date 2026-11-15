/**
 * Complete Shiori's OAuth authorization after server-side consent validation.
 *
 * This layer has no access to the submitted approval code. It wraps the
 * provider's asynchronous stages so exceptions are observable as a safe
 * stage label, not as Cloudflare Error 1101.
 */
export class GrantStageError extends Error {
  constructor(stage, underlying) {
    super("OAuth grant could not complete");
    this.name="GrantStageError";
    this.stage=stage;
    // Never include the original OAuth URL, client query or secret in output.
    this.underlyingType=underlying?.name || "unknown";
  }
}

export async function completeOwnerGrant(api, storedRequestUrl, allowedScopes) {
  let stage="restore_request";
  try {
    const original=await api.parseAuthRequest(new Request(storedRequestUrl));
    stage="lookup_client";
    const client=await api.lookupClient(original.clientId);
    if (!client) throw new Error("OAuth client no longer exists");
    stage="create_grant";
    const result=await api.completeAuthorization({
      request:original,
      userId:"shiori-owner",
      metadata:{clientName:client.clientName},
      scope:original.scope.filter(x=>allowedScopes.includes(x)),
      props:{userId:"shiori-owner",displayName:"Shiori owner"}
    });
    stage="validate_redirect";
    if (typeof result?.redirectTo!=="string" || !result.redirectTo) {
      throw new Error("Provider did not return a redirect");
    }
    // Provider validates the exact registered redirect URI during parsing.
    // Do not construct redirects from user-supplied form values.
    new URL(result.redirectTo);
    return {redirectTo:result.redirectTo};
  } catch (e) {
    throw new GrantStageError(stage,e);
  }
}
