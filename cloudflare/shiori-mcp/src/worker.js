/**
 * SHIORI Cloudflare MCP Phase A — single-user, token-protected remote alpha.
 *
 * Cloudflare D1 is an ISOLATED REMOTE STORE. It is not yet synchronized with
 * the canonical local Rust/SQLite database. No ClickUp/Gmail/LLM access.
 *
 * This Worker intentionally registers ONLY implemented operations.
 * The 113-operation registry remains a design document, not a live API.
 */
const SERVER="shiori-mcp-cloudflare", VERSION="0.1.0-alpha";
const PROTOCOL="2025-06-18", MAX_BODY=32768, MAX_LIMIT=100;
const allowedStatuses=new Set(["todo","in_progress","done"]);
const allowedStyles=new Set(["circuit","curved","straight"]);
const W=()=>({type:"string",minLength:1,maxLength:128});
const S=(max=160)=>({type:"string",minLength:1,maxLength:max});
const I=(max)=>({type:"integer",minimum:0,...(max?{maximum:max}:{})});
const F={workspace_id:W(),task_id:S(),node_id:S(),title:S(),body:{type:"string",maxLength:65536},status:{enum:["todo","in_progress","done"]},style:{enum:["circuit","curved","straight"]},idempotency_key:{type:"string",minLength:8,maxLength:128},expected_revision:I(),limit:{type:"integer",minimum:1,maximum:100},cursor:{type:"string",maxLength:64},x:{type:"number",minimum:-1000000,maximum:1000000},y:{type:"number",minimum:-1000000,maximum:1000000}};
const op=(id,fields,required=[],description="",write=false)=>({
 id,name:"shiori_"+id.replaceAll(".","_"),description,
 inputSchema:{type:"object",additionalProperties:false,required:["workspace_id",...required,...(write?["idempotency_key"]:[])],
 properties:Object.fromEntries(["workspace_id",...fields,...(write?["idempotency_key"]:[])].map(k=>[k,F[k]]))}
});
const OPERATIONS=[
 op("system.capabilities.read",[] ,[],"Read actual deployed capabilities and isolation status"),
 op("tasks.list",["cursor","limit"],[],"List tasks in this isolated Cloudflare workspace"),
 op("tasks.get",["task_id"],["task_id"],"Read one task from the remote D1 workspace"),
 op("tasks.create",["title","body"],["title"],"Create remote-only task (local Rust sync not enabled)",true),
 op("tasks.status.set",["task_id","status","expected_revision"],["task_id","status","expected_revision"],"Update remote task status with revision guard",true),
 op("tasks.dependencies.list",["task_id"],["task_id"],"Read remote task prerequisite links"),
 op("spatial.scene.read",["limit","cursor"],[],"Read remote spatial task scene (not local Rust SQLite)"),
 op("spatial.node.position.set",["node_id","x","y","expected_revision"],["node_id","x","y","expected_revision"],"Persist visual-only node position in remote D1",true),
 op("spatial.edge.style.set",["style","expected_revision"],["style","expected_revision"],"Persist visual-only connector style",true)
];
const BY_ID=new Map(OPERATIONS.map(o=>[o.id,o]));
const BY_TOOL=new Map(OPERATIONS.map(o=>[o.name,o]));
class ServiceError extends Error {constructor(status,code,message){super(message);this.status=status;this.code=code;}}
const E=(status,code,msg)=>{throw new ServiceError(status,code,msg);};
const json=(o,status=200,headers={})=>new Response(JSON.stringify(o),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff",...headers}});
const field=(v,k,required=false)=>{if(required && v[k]===undefined)E(400,"VALIDATION_FAILED",k+" is required");};
const object=o=>o!==null&&typeof o==="object"&&!Array.isArray(o);
function validate(def,args,env){
 if(!object(args))E(400,"VALIDATION_FAILED","Arguments must be a JSON object");
 const schema=def.inputSchema;
 for(const k of Object.keys(args))if(!Object.hasOwn(schema.properties,k))E(400,"VALIDATION_FAILED","Unknown field: "+k);
 for(const k of schema.required)field(args,k,true);
 for(const [k,v] of Object.entries(args)){
  const p=schema.properties[k];
  if(p.enum && !p.enum.includes(v))E(400,"VALIDATION_FAILED","Invalid "+k);
  if(p.type==="string" && (typeof v!=="string" || v.length>(p.maxLength??99999) || v.length<(p.minLength??0)))E(400,"VALIDATION_FAILED","Invalid "+k);
  if(p.type==="integer" && (!Number.isSafeInteger(v)||v<(p.minimum??-Infinity)||v>(p.maximum??Infinity)))E(400,"VALIDATION_FAILED","Invalid "+k);
  if(p.type==="number" && (typeof v!=="number"||!Number.isFinite(v)||v<(p.minimum??-Infinity)||v>(p.maximum??Infinity)))E(400,"VALIDATION_FAILED","Invalid "+k);
 }
 if(args.workspace_id!==(env.WORKSPACE_ID||"personal"))E(403,"FORBIDDEN","Workspace not granted by this credential");
 return args;
}
async function readRequest(request){
 if(Number(request.headers.get("content-length")||0)>MAX_BODY)E(413,"VALIDATION_FAILED","Payload too large");
 const raw=await request.text();
 if(raw.length>MAX_BODY)E(413,"VALIDATION_FAILED","Payload too large");
 try{return JSON.parse(raw);}catch{E(400,"VALIDATION_FAILED","Invalid JSON");}
}
async function sha256(s){return new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(s)));}
async function safeEqual(a,b){
 const aa=await sha256(a),bb=await sha256(b);let x=0;
 for(let i=0;i<aa.length;i++)x|=aa[i]^bb[i];
 return x===0 && a.length===b.length;
}
async function authenticate(request,env){
 if(!env.SHIO_AUTH_TOKEN||!env.DB)E(503,"UNAVAILABLE","Shiori auth/database bindings not configured");
 const auth=request.headers.get("authorization")||"";
 if(!auth.startsWith("Bearer ")||auth.length>240)E(401,"UNAUTHENTICATED","Bearer token required");
 if(!await safeEqual(auth.slice(7),env.SHIO_AUTH_TOKEN))E(401,"UNAUTHENTICATED","Invalid token");
 const origin=request.headers.get("origin");
 if(origin && new URL(origin).host!==new URL(request.url).host)E(403,"FORBIDDEN","Cross-origin browser writes disabled");
}
async function rateLimit(db){
 const window=Math.floor(Date.now()/60000);
 await db.prepare("INSERT INTO access_limits(bucket,window_min,count) VALUES('owner',?,1) ON CONFLICT(bucket,window_min) DO UPDATE SET count=count+1").bind(window).run();
 const row=await db.prepare("SELECT count FROM access_limits WHERE bucket='owner' AND window_min=?").bind(window).first();
 if(row.count>90)E(429,"RATE_LIMITED","Temporary request limit reached");
}
function listParams(v){let n=Number.parseInt(v.cursor||"0",10);if(!Number.isSafeInteger(n)||n<0||n>100000)E(400,"VALIDATION_FAILED","Invalid cursor");return {offset:n,limit:Math.min(v.limit||50,MAX_LIMIT)};}
function formatTask(row){return {id:row.id,title:row.title,body:row.notes,project:row.project,status:row.status,priority:row.priority,version:row.version,created_at:row.created_at,updated_at:row.updated_at,origin:"cloudflare-d1-remote-alpha"};}
async function getTask(db,w,id){const row=await db.prepare("SELECT * FROM remote_tasks WHERE workspace_id=? AND id=? AND deleted_at IS NULL").bind(w,id).first();if(!row)E(404,"NOT_FOUND","Task not found in remote workspace");return row;}
async function duplicate(db,w,id,key){
 const row=await db.prepare("SELECT result_json FROM idempotency WHERE workspace_id=? AND operation_id=? AND token=?").bind(w,id,key).first();
 return row?JSON.parse(row.result_json):null;
}
function idemp(db,w,id,key,result){
 return db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) VALUES(?,?,?,?,?)").bind(w,id,key,JSON.stringify(result),new Date().toISOString());
}
async function writeOnce(env,w,id,key,result,statement){
 const saved=await duplicate(env.DB,w,id,key);if(saved)return saved;
 try{await env.DB.batch([statement,idemp(env.DB,w,id,key,result)]);}
 catch(err){const after=await duplicate(env.DB,w,id,key);if(after)return after;throw err;}
 return result;
}
async function run(id,arg,env){
 const def=BY_ID.get(id);if(!def)E(404,"UNSUPPORTED_CAPABILITY","Operation not deployed");
 const a=validate(def,arg,env),db=env.DB,w=a.workspace_id;
 if(id==="system.capabilities.read")return {server:SERVER,version:VERSION,workspace_id:w,backend:"isolated-cloudflare-d1",local_rust_sync:false,oauth:false,authentication:"single-user-bearer",operations:OPERATIONS.map(o=>o.id),planned_total:113};
 if(id==="tasks.list"){
  const {offset,limit}=listParams(a);
  const rows=await db.prepare("SELECT * FROM remote_tasks WHERE workspace_id=? AND deleted_at IS NULL ORDER BY created_at DESC,id LIMIT ? OFFSET ?").bind(w,limit,offset).all();
  const items=rows.results.map(formatTask);return {items,next_cursor:items.length===limit?String(offset+limit):null,source:"isolated-cloudflare-d1"};
 }
 if(id==="tasks.get")return {item:formatTask(await getTask(db,w,a.task_id))};
 if(id==="tasks.create"){
  let cached=await duplicate(db,w,id,a.idempotency_key);if(cached)return cached;
  if(a.title.trim().length===0||a.title.length>160)E(400,"VALIDATION_FAILED","Title must contain 1–160 characters");
  const taskId=crypto.randomUUID(),now=new Date().toISOString();
  const task={id:taskId,title:a.title.trim(),body:a.body||"",project:"Remote alpha",status:"todo",priority:"medium",version:1,created_at:now,updated_at:now,origin:"cloudflare-d1-remote-alpha"};
  const result={changed:true,resource_id:taskId,revision:1,item:task};
  return writeOnce(env,w,id,a.idempotency_key,result,db.prepare("INSERT INTO remote_tasks(id,workspace_id,title,notes,project,status,priority,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)").bind(taskId,w,task.title,task.body,task.project,task.status,task.priority,1,now,now));
 }
 if(id==="tasks.status.set"){
  const cached=await duplicate(db,w,id,a.idempotency_key);if(cached)return cached;
  const current=await getTask(db,w,a.task_id);if(current.version!==a.expected_revision)E(409,"CONFLICT","Task revision has changed");
  if(!allowedStatuses.has(a.status))E(400,"VALIDATION_FAILED","Invalid status");
  const result={changed:true,resource_id:a.task_id,revision:a.expected_revision+1,status:a.status};
  const now=new Date().toISOString();
  const updates=await db.batch([
    db.prepare("UPDATE remote_tasks SET status=?,version=version+1,updated_at=? WHERE workspace_id=? AND id=? AND version=? AND deleted_at IS NULL").bind(a.status,now,w,a.task_id,a.expected_revision),
    db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) SELECT ?,?,?,?,? WHERE changes()=1").bind(w,id,a.idempotency_key,JSON.stringify(result),now)
  ]);
  if(updates[0].meta.changes!==1){const again=await duplicate(db,w,id,a.idempotency_key);if(again)return again;E(409,"CONFLICT","Task was modified concurrently");}
  return result;
 }
 if(id==="tasks.dependencies.list"){
  await getTask(db,w,a.task_id);
  const rows=await db.prepare("SELECT depends_on_id FROM remote_dependencies WHERE workspace_id=? AND task_id=? ORDER BY depends_on_id").bind(w,a.task_id).all();
  return {items:rows.results.map(x=>({task_id:a.task_id,depends_on_id:x.depends_on_id})),source:"isolated-cloudflare-d1"};
 }
 if(id==="spatial.scene.read"){
  const {offset,limit}=listParams(a);
  const rows=(await db.prepare("SELECT t.*,p.x,p.y,p.revision AS position_revision FROM remote_tasks t LEFT JOIN remote_positions p ON p.workspace_id=t.workspace_id AND p.node_id=t.id WHERE t.workspace_id=? AND t.deleted_at IS NULL ORDER BY t.created_at DESC,t.id LIMIT ? OFFSET ?").bind(w,limit,offset).all()).results;
  const nodes=rows.map((x,i)=>({...formatTask(x),kind:"task",x:x.x??(120+(i%4)*300),y:x.y??(140+Math.floor(i/4)*170),position_revision:x.position_revision??0}));
  const ids=new Set(nodes.map(x=>x.id));const deps=(await db.prepare("SELECT task_id,depends_on_id FROM remote_dependencies WHERE workspace_id=?").bind(w).all()).results;
  const edges=deps.filter(x=>ids.has(x.task_id)&&ids.has(x.depends_on_id)).map(x=>({from:x.depends_on_id,to:x.task_id,kind:"blocks"}));
  const style=await db.prepare("SELECT value,revision FROM remote_settings WHERE workspace_id=? AND key='connector_style'").bind(w).first();
  return {scene:{nodes,edges,connector_style:style?.value||"circuit",layout_revision:style?.revision||0,origin:"cloudflare-d1-remote-alpha",synchronized_with_local_rust:false},next_cursor:nodes.length===limit?String(offset+limit):null};
 }
 if(id==="spatial.node.position.set"){
  const cached=await duplicate(db,w,id,a.idempotency_key);if(cached)return cached;
  await getTask(db,w,a.node_id);
  const old=await db.prepare("SELECT revision FROM remote_positions WHERE workspace_id=? AND node_id=?").bind(w,a.node_id).first();
  if((old?.revision||0)!==a.expected_revision)E(409,"CONFLICT","Visual position revision changed");
  const revision=a.expected_revision+1;
  const update=old
   ?db.prepare("UPDATE remote_positions SET x=?,y=?,revision=revision+1 WHERE workspace_id=? AND node_id=? AND revision=?").bind(a.x,a.y,w,a.node_id,a.expected_revision)
   :db.prepare("INSERT INTO remote_positions(workspace_id,node_id,x,y,revision) VALUES(?,?,?,?,1)").bind(w,a.node_id,a.x,a.y);
  const result={position:{node_id:a.node_id,x:a.x,y:a.y,revision}};
  try{
   const out=await db.batch([update,
      db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) SELECT ?,?,?,?,? WHERE changes()=1").bind(w,id,a.idempotency_key,JSON.stringify(result),new Date().toISOString())]);
   if(out[0].meta.changes!==1)E(409,"CONFLICT","Visual position changed concurrently");
  }catch(err){const again=await duplicate(db,w,id,a.idempotency_key);if(again)return again;throw err;}
  return result;
 }
 if(id==="spatial.edge.style.set"){
  const cached=await duplicate(db,w,id,a.idempotency_key);if(cached)return cached;
  if(!allowedStyles.has(a.style))E(400,"VALIDATION_FAILED","Invalid connector style");
  const current=await db.prepare("SELECT revision FROM remote_settings WHERE workspace_id=? AND key='connector_style'").bind(w).first();
  if((current?.revision||0)!==a.expected_revision)E(409,"CONFLICT","Connector style revision changed");
  const result={changed:true,resource_id:"connector_style",revision:a.expected_revision+1,style:a.style};
  const update=current?
     db.prepare("UPDATE remote_settings SET value=?,revision=revision+1 WHERE workspace_id=? AND key='connector_style' AND revision=?").bind(a.style,w,a.expected_revision):
     db.prepare("INSERT INTO remote_settings(workspace_id,key,value,revision) VALUES(?,'connector_style',?,1)").bind(w,a.style);
  try{const out=await db.batch([update,db.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) SELECT ?,?,?,?,? WHERE changes()=1").bind(w,id,a.idempotency_key,JSON.stringify(result),new Date().toISOString())]);if(out[0].meta.changes!==1)E(409,"CONFLICT","Connector style changed concurrently");}
  catch(err){const again=await duplicate(db,w,id,a.idempotency_key);if(again)return again;throw err;}
  return result;
 }
 E(404,"UNSUPPORTED_CAPABILITY","Operation not implemented");
}
async function mcp(body,env){
 if(!object(body)||body.jsonrpc!=="2.0"||Array.isArray(body))return {jsonrpc:"2.0",id:body?.id??null,error:{code:-32600,message:"Invalid JSON-RPC request"}};
 if(body.id===undefined){return null;}
 const id=body.id;
 try {
  if(body.method==="initialize")return {jsonrpc:"2.0",id,result:{protocolVersion:PROTOCOL,capabilities:{tools:{listChanged:false}},serverInfo:{name:SERVER,version:VERSION}}};
  if(body.method==="ping")return {jsonrpc:"2.0",id,result:{}};
  if(body.method==="tools/list")return {jsonrpc:"2.0",id,result:{tools:OPERATIONS.map(o=>({name:o.name,description:o.description,inputSchema:o.inputSchema}))}};
  if(body.method==="tools/call"){
   const tool=BY_TOOL.get(body.params?.name);
   if(!tool)return {jsonrpc:"2.0",id,error:{code:-32602,message:"Unknown MCP tool"}};
   try{const data=await run(tool.id,body.params?.arguments||{},env);return {jsonrpc:"2.0",id,result:{content:[{type:"text",text:JSON.stringify(data)}],structuredContent:data}};}
   catch(err){const msg=err instanceof ServiceError?err.message:"Operation failed";return {jsonrpc:"2.0",id,result:{isError:true,content:[{type:"text",text:JSON.stringify({error:err.code||"INTERNAL_ERROR",message:msg})}]}};}
  }
  return {jsonrpc:"2.0",id,error:{code:-32601,message:"Method not found"}};
 }catch{return {jsonrpc:"2.0",id,error:{code:-32603,message:"Internal error"}};}
}
async function handle(request,env){
 const url=new URL(request.url);
 if(request.method==="GET"&&url.pathname==="/health")return json({service:SERVER,version:VERSION,service_state:env.SHIO_AUTH_TOKEN&&env.DB?"ready":"unconfigured",source:"isolated-cloudflare-d1",local_sync:false});
 if(url.pathname!=="/mcp"&&!url.pathname.startsWith("/api/v1/ops/"))return json({error:"NOT_FOUND"},404);
 if(request.method!=="POST")return json({error:"METHOD_NOT_ALLOWED"},405,{"allow":"POST"});
 await authenticate(request,env);await rateLimit(env.DB);
 const body=await readRequest(request);
 if(url.pathname==="/mcp"){
  const response=await mcp(body,env);return response?json(response):new Response(null,{status:202,headers:{"cache-control":"no-store"}});
 }
 const name=url.pathname.slice("/api/v1/ops/".length);
 const data=await run(name,body,env);
 return json({ok:true,operation_id:name,data});
}
export default {async fetch(request,env){
 try{return await handle(request,env);}
 catch(err){
  const known=err instanceof ServiceError;
  return json({ok:false,error:{code:known?err.code:"INTERNAL_ERROR",message:known?err.message:"Internal service error",retryable:known&&err.status>=500}},known?err.status:500,known&&err.status===401?{"www-authenticate":"Bearer realm=\"Shiori\""}:{});
 }
}};
