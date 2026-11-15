import {OAuthAuthorizationServer,AuthorizationError} from "@cloudflare/workers-oauth-provider";
import {WorkerEntrypoint} from "cloudflare:workers";
import {isTrustedConsentRequest} from "./form-origin.js";
import {normalizeApprovalInput} from "./approval-input.js";

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
  const key=nonce();
  await env.OAUTH_KV.put("shiori:pending:"+key,JSON.stringify({url:request.url,at:Date.now()}),{expirationTtl:300});
  const scopes=approval.scope.filter(s=>SCOPES.includes(s));
  const template='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shiori - Authorize App</title>'+
    '<style>:root{color-scheme:dark}body{background:#0d1117;color:#eef2fc;font:15px system-ui;margin:0}'+
    'main{max-width:420px;margin:8vh auto;padding:26px;border:1px solid #354055;border-radius:16px;background:#161d29}'+
    'p{line-height:1.55;color:#b5bfd2}input[type=password]{padding:12px;width:100%;box-sizing:border-box;background:#0d1117;color:white;border:1px solid #64738b;border-radius:8px}'+
    'button{display:block;margin-top:20px;width:100%;padding:12px;border:0;border-radius:8px;background:#b6cff3;color:#142136;font-weight:700}</style>'+
    '<main><h1>Connect to Shiori</h1><p><strong>'+escaped(client.clientName||approval.clientId)+'</strong> requests access to your personal cloud workspace.</p>'+
    '<p>Permissions: <strong>'+escaped(scopes.join(", ")||"none")+'</strong></p>'+
    '<p>This Cloudflare database is not yet synchronized with your offline Rust tasks.</p>'+
    '<form method="post" action="/authorize"><input type="hidden" name="nonce" value="'+key+'">'+
    '<label>Owner approval code<br><input type="password" name="code" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" minlength="24" maxlength="160" required></label><p><small>Use your separate OAuth owner approval code, not your original MCP bearer token.</small></p>'+
    '<p><label><input type="checkbox" name="approve" value="yes" required> I approve this app and its requested permissions.</label></p>'+
    '<button type="submit">Authorize this app</button></form></main></html>';
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
  if(fields.get("approve")!=="yes")return errorPage("Consent not granted.",403);
  await env.OAUTH_KV.delete("shiori:pending:"+key);
  const api=oauthServer.getOAuthApi(env);
  const original=await api.parseAuthRequest(new Request(pending.url));
  const client=await api.lookupClient(original.clientId);
  if(!client)return errorPage("OAuth client no longer exists.",403);
  const {redirectTo}=await api.completeAuthorization({
    request:original,userId:"shiori-owner",
    metadata:{clientName:client.clientName},
    scope:original.scope.filter(x=>SCOPES.includes(x)),
    props:{userId:"shiori-owner",displayName:"Shiori owner"}
  });
  const response=Response.redirect(redirectTo,302);
  response.headers.set("set-cookie","__Host-shiori_oauth=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0");
  response.headers.set("cache-control","no-store");
  return response;
}
export default class ShioriOAuthAuthorization extends WorkerEntrypoint{
  async fetch(request){
    const url=new URL(request.url);
    try{
      if(url.pathname==="/authorize"){
        if(request.method==="GET")return getAuthorize(request,this.env);
        if(request.method==="POST")return postAuthorize(request,this.env);
        return errorPage("Unsupported method.",405);
      }
      return oauthServer.fetch(request,this.env,this.ctx);
    }catch(e){
      console.error("Shiori OAuth error:",e?.name||"unknown");
      return errorPage("Authorization service unavailable.",500);
    }
  }
  validateToken(resource,token){
    return oauthServer.validateToken(resource,token,this.env);
  }
}