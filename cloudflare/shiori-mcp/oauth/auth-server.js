import {OAuthAuthorizationServer,AuthorizationError} from "@cloudflare/workers-oauth-provider";
import {WorkerEntrypoint} from "cloudflare:workers";
import {isTrustedConsentRequest} from "./form-origin.js";
import {normalizeApprovalInput} from "./approval-input.js";
import {completeOwnerGrant,GrantStageError} from "./grant-flow.js";
import {ownerRedirect} from "./owner-redirect.js";
import {renderConsentPage,validateConsentSelections} from "./consent-form.js";

/** Isolated single-owner OAuth issuer. Never shares Google Master secrets. */
const ISSUER="https://shiori-auth.cryogenized.workers.dev";
const RESOURCE="https://shiori-mcp-oauth.cryogenized.workers.dev/mcp";
const SCOPES=["mcp:read","mcp:write"];
const oauthServer=new OAuthAuthorizationServer({
  issuer:ISSUER,resources:[RESOURCE],scopesSupported:SCOPES,
  clientIdMetadataDocumentEnabled:true,clientRegistrationEndpoint:"/oauth/register"
});
const securityHeaders={"cache-control":"no-store","x-content-type-options":"nosniff",
  "referrer-policy":"strict-origin","content-security-policy":"default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; style-src 'unsafe-inline'"};
const escaped=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function html(s,status=200,cookie){
  const headers=new Headers({...securityHeaders,"content-type":"text/html;charset=utf-8"});
  if(cookie)headers.set("set-cookie",cookie);
  return new Response(s,{status,headers});
}
const errorPage=(s,status=400)=>html("<!doctype html><title>Shiori OAuth</title><main style='font:16px system-ui;margin:12vh auto;max-width:36rem'><h1>Shiori OAuth</h1><p>"+escaped(s)+"</p></main>",status);
async function secureEqual(left,right){
  const enc=new TextEncoder();
  const [a,b]=await Promise.all([crypto.subtle.digest("SHA-256",enc.encode(left)),crypto.subtle.digest("SHA-256",enc.encode(right))]);
  const x=new Uint8Array(a),y=new Uint8Array(b);
  let delta=left.length===right.length?0:1;
  for(let i=0;i<x.length;i++)delta|=x[i]^y[i];
  return delta===0;
}
const nonce=()=>Array.from(crypto.getRandomValues(new Uint8Array(32)),b=>b.toString(16).padStart(2,"0")).join("");
function readCookie(request){
  const match=(request.headers.get("cookie")||"").match(/(?:^|;\s*)__Host-shiori_oauth=([a-f0-9]{64})(?:;|$)/);
  return match?.[1]||"";
}
async function getAuthorize(request,env){
  if(!env.OAUTH_KV||!env.OWNER_APPROVAL_SECRET)return errorPage("Owner approval is not configured.",503);
  const api=oauthServer.getOAuthApi(env);
  let approval;
  try{approval=await api.parseAuthRequest(request);}
  catch(e){
    if(e instanceof AuthorizationError){
      if(e.redirectTo)return Response.redirect(e.redirectTo,302);
      return errorPage(e.description,400);
    }
    throw e;
  }
  const client=await api.lookupClient(approval.clientId);
  if(!client)return errorPage("Unknown client.",400);
  // A read grant is a prerequisite for opening an MCP workspace.
  const scopes=approval.scope.filter(s=>SCOPES.includes(s));
  if(!scopes.includes("mcp:read"))return errorPage("Shiori requires mcp:read permission.",400);
  const key=nonce();
  await env.OAUTH_KV.put("shiori:pending:"+key,JSON.stringify({url:request.url,at:Date.now()}),{expirationTtl:300});
  const template=renderConsentPage({clientName:client.clientName||approval.clientId,requestedScopes:scopes,nonce:key});
  return html(template,200,"__Host-shiori_oauth="+key+"; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=300");
}
async function postAuthorize(request,env){
  if(!isTrustedConsentRequest(request,ISSUER))return errorPage("Invalid form origin.",403);
  if(!env.OAUTH_KV||!env.OWNER_APPROVAL_SECRET)return errorPage("Owner approval is not configured.",503);
  const data=await request.text();
  if(data.length>1200)return errorPage("Form too large.",413);
  const fields=new URLSearchParams(data),key=fields.get("nonce")||"";
  if(!/^[a-f0-9]{64}$/.test(key)||readCookie(request)!==key)return errorPage("The approval page expired.",403);
  const raw=await env.OAUTH_KV.get("shiori:pending:"+key);
  if(!raw)return errorPage("Approval expired.",403);
  const pending=JSON.parse(raw);
  if(Date.now()-pending.at>300000)return errorPage("Approval expired.",403);
  if(!await secureEqual(normalizeApprovalInput(fields.get("code")),normalizeApprovalInput(env.OWNER_APPROVAL_SECRET)))return errorPage("Invalid approval code. Use the private Shiori OAuth owner code saved on your laptop, not the older MCP access token. Restart the connection to retry.",403);
  const consent=validateConsentSelections(fields);
  if(!consent.ok)return errorPage(consent.error,403);
  const writeApproved=consent.writeApproved;
  let result;
  try {
    const api=oauthServer.getOAuthApi(env);
    // Explicit, limited provider methods for the grant-stage wrapper.
    result=await completeOwnerGrant({
      parseAuthRequest:(request)=>api.parseAuthRequest(request),
      lookupClient:(clientId)=>api.lookupClient(clientId),
      completeAuthorization:(options)=>api.completeAuthorization(options)
    },pending.url,SCOPES,writeApproved);
  } catch(e) {
    const stage=e instanceof GrantStageError?e.stage:"unknown";
    const type=e instanceof GrantStageError?e.underlyingType:"unknown";
    // Log only a fixed stage identifier and exception class. Never log
    // approval codes, client callbacks, access tokens or request URLs.
    console.error("Shiori OAuth grant failure",stage,type);
    return errorPage(
      "Authorization could not finish (stage: "+stage+"). "+
      "This is a Shiori server error, not an invalid approval code.",
      500
    );
  }
  // Keep the pending record until the provider has successfully issued a
  // grant. A transient grant failure must not silently consume consent.
  // Response.redirect() returns an immutable Headers object. Adding the
  // cookie after construction threw TypeError and surfaced as an OAuth 500.
  const response=ownerRedirect(result.redirectTo);
  await env.OAUTH_KV.delete("shiori:pending:"+key);
  return response;
}
export default class ShioriOAuthAuthorization extends WorkerEntrypoint{
  async fetch(request){
    const url=new URL(request.url);
    try{
      if(url.pathname==="/authorize"){
        if(request.method==="GET")return await getAuthorize(request,this.env);
        if(request.method==="POST")return await postAuthorize(request,this.env);
        return errorPage("Unsupported method.",405);
      }
      return await oauthServer.fetch(request,this.env,this.ctx);
    }catch(e){
      console.error("Shiori OAuth error:",e?.name||"unknown");
      return errorPage("Authorization service unavailable.",500);
    }
  }
  validateToken(resource,token){
    return oauthServer.validateToken(resource,token,this.env);
  }
}