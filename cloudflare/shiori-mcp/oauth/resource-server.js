import {OAuthResourceServer,insufficientScope} from "@cloudflare/workers-oauth-provider";
import legacy from "../src/worker.js";
import {INITIAL_CONSENT_SCOPES,requiredScopesForRpc,hasRequiredScopes,normalizeGrantedScopes} from "./scope-policy.js";

/**
 * OAuth-protected facade. The original bearer-gated alpha Worker remains
 * deployed separately. Clients never receive SHIO_AUTH_TOKEN.
 */
const ENDPOINT="https://shiori-mcp-oauth.cryogenized.workers.dev/mcp";
const ISSUER="https://shiori-auth.cryogenized.workers.dev";
const oauthResource=new OAuthResourceServer({
 resourceMetadata:{
  resource:ENDPOINT,authorization_servers:[ISSUER],
  resource_name:"Shiori MCP"
 },
 // This is the single-owner task-management plugin. Request both scopes
 // on first connection so clients that cannot perform OAuth step-up can
 // obtain an explicitly consented read/write grant. The handler continues
 // to enforce read-only tokens safely for non-mutating calls.
 requiredScopes:INITIAL_CONSENT_SCOPES,
 validateToken:env=>env.AUTH_SERVER.validateToken,
 handler:{
  async fetch(request,env,ctx){
   if(ctx.props?.userId!=="shiori-owner")return new Response("Forbidden",{status:403});
   const u=new URL(request.url),isMcp=u.pathname==="/mcp";
   // This resource's token audience is specifically /mcp. The existing
   // separate bearer-alpha API retains dedicated JSON/HTTP routes.
   if(!isMcp)return new Response("Not found",{status:404});
   let rpc;
   if(request.method==="POST"){
    try{rpc=await request.clone().json();}catch{return new Response("Invalid JSON",{status:400});}
   }
   // Exact mcp:write is mandatory for all mutations (unknown tools fail closed).
   const needed=requiredScopesForRpc(rpc);
   if(!hasRequiredScopes(ctx.auth?.scope,needed))return insufficientScope(ctx.auth,needed);
   if(!env.DB)return new Response("Shiori backend unconfigured",{status:503});
   // The old alpha handler has its own legacy credential check. After
   // OAuth validation, satisfy that *internal* check with a fresh random,
   // per-request value that is never accepted at the public MCP boundary.
   // No persistent legacy bearer secret is shared with the OAuth Worker.
   const internalKey=crypto.randomUUID()+crypto.randomUUID();
   const internalEnv={...env,SHIO_AUTH_TOKEN:internalKey,SHIO_AUTH_MODE:"oauth",SHIO_OAUTH_SCOPES:normalizeGrantedScopes(ctx.auth.scope)};
   const h=new Headers(request.headers);
   h.set("authorization","Bearer "+internalKey);
   h.delete("cookie");
   h.delete("origin"); // OAuth bearer authorization is not cookie-based CSRF.
   return legacy.fetch(new Request(request,{headers:h}),internalEnv);
  }
 }
});
export default {
 async fetch(request,env,ctx){
  if(new URL(request.url).pathname==="/health" && request.method==="GET"){
   return Response.json({
    service:"shiori-mcp-oauth",oauth:"configured",
    cloud_dataset:"isolated-d1",local_rust_sync:false
   },{headers:{"cache-control":"no-store"}});
  }
  return oauthResource.fetch(request,env,ctx);
 }
};