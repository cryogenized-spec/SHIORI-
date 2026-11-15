import {OAuthResourceServer,insufficientScope} from "@cloudflare/workers-oauth-provider";
import legacy from "../src/worker.js";

/**
 * OAuth-protected facade. The original bearer-gated alpha Worker remains
 * deployed separately. Clients never receive SHIO_AUTH_TOKEN.
 */
const ENDPOINT="https://shiori-mcp-oauth.cryogenized.workers.dev/mcp";
const ISSUER="https://shiori-auth.cryogenized.workers.dev";
const readOnly=new Set([
 "shiori_system_capabilities_read","shiori_tasks_list","shiori_tasks_get",
 "shiori_tasks_dependencies_list","shiori_spatial_scene_read"
]);
const isWrite=id=>!readOnly.has(id);
const oauthResource=new OAuthResourceServer({
 resourceMetadata:{
  resource:ENDPOINT,authorization_servers:[ISSUER],
  resource_name:"Shiori MCP"
 },
 requiredScopes:["mcp:read"],
 validateToken:env=>env.AUTH_SERVER.validateToken,
 handler:{
  async fetch(request,env,ctx){
   if(ctx.props?.userId!=="shiori-owner")return new Response("Forbidden",{status:403});
   const u=new URL(request.url),isMcp=u.pathname==="/mcp";
   if(!isMcp&&!u.pathname.startsWith("/api/v1/ops/"))return new Response("Not found",{status:404});
   let needed=["mcp:read"];
   if(isMcp && request.method==="POST"){
    let rpc;
    try{rpc=await request.clone().json();}catch{return new Response("Invalid JSON",{status:400});}
    if(rpc?.method==="tools/call" && isWrite(rpc?.params?.name))needed=["mcp:read","mcp:write"];
   } else if(u.pathname.startsWith("/api/v1/ops/")){
    const operation=u.pathname.slice("/api/v1/ops/".length);
    if(!readOnly.has("shiori_"+operation.replaceAll(".","_")))needed=["mcp:read","mcp:write"];
   }
   if(!needed.every(s=>ctx.auth.scope.includes(s)))return insufficientScope(ctx.auth,needed);
   if(!env.DB)return new Response("Shiori backend unconfigured",{status:503});
   // The old alpha handler has its own legacy credential check. After
   // OAuth validation, satisfy that *internal* check with a fresh random,
   // per-request value that is never accepted at the public MCP boundary.
   // No persistent legacy bearer secret is shared with the OAuth Worker.
   const internalKey=crypto.randomUUID()+crypto.randomUUID();
   const internalEnv={...env,SHIO_AUTH_TOKEN:internalKey};
   const h=new Headers(request.headers);
   h.set("authorization","Bearer "+internalKey);
   h.delete("cookie");
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