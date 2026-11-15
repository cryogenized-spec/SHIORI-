import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { DatabaseSync } from "node:sqlite";
import worker from "../src/worker.js";

class FakeD1 {
  constructor(){
    this.db=new DatabaseSync(":memory:");
    this.db.exec(fs.readFileSync(new URL("../schema.sql",import.meta.url),"utf8"));
  }
  prepare(sql){
    const db=this.db;
    const stmt={sql,args:[],bind(...args){this.args=args;return this;},
      first(){return db.prepare(this.sql).get(...this.args)||null;},
      all(){return {results:db.prepare(this.sql).all(...this.args)};},
      run(){
        const info=db.prepare(this.sql).run(...this.args);
        return {meta:{changes:Number(info.changes)},results:[]};
      }};
    return stmt;
  }
  async batch(statements){
    this.db.exec("BEGIN IMMEDIATE");
    try{
      const result=statements.map(s=>s.run());
      this.db.exec("COMMIT");
      return result;
    }catch(e){this.db.exec("ROLLBACK");throw e;}
  }
}

const token="shio_"+"t".repeat(48);
const env=()=>({DB:new FakeD1(),SHIO_AUTH_TOKEN:token,WORKSPACE_ID:"personal"});
async function call(e,path,data,{auth=token,origin}={}){
  const headers={"content-type":"application/json"};
  if(auth)headers.authorization="Bearer "+auth;
  if(origin)headers.origin=origin;
  const response=await worker.fetch(new Request("https://shiori-mcp-alpha.example.com"+path,{
    method:"POST",headers,body:JSON.stringify(data)
  }),e);
  return {status:response.status,data:await response.json()};
}
const request=(id,args)=>({workspace_id:"personal",...args,idempotency_key:id});
const rpc=(method,params,id=1)=>({jsonrpc:"2.0",id,method,params});

test("remote access is strictly bearer-gated and workspace-scoped",async()=>{
  const e=env();
  const denied=await call(e,"/mcp",rpc("initialize",{}),{auth:null});
  assert.equal(denied.status,401);
  assert.equal(denied.data.error.code,"UNAUTHENTICATED");
  assert.equal((await call(e,"/mcp",rpc("tools/list"),{auth:"invalid"})).status,401);
  assert.equal((await call(e,"/api/v1/ops/tasks.list",{workspace_id:"someone-else"})).status,403);
  assert.equal((await call(e,"/api/v1/ops/tasks.list",{workspace_id:"personal"},{origin:"https://evil.example"})).status,403);
});

test("stateless MCP initializes and registers implemented tools only",async()=>{
  const e=env();
  const init=await call(e,"/mcp",rpc("initialize",{protocolVersion:"2025-06-18"}));
  assert.equal(init.status,200);
  assert.equal(init.data.result.serverInfo.name,"shiori-mcp-cloudflare");
  const list=await call(e,"/mcp",rpc("tools/list",{}));
  assert.equal(list.status,200);
  assert.equal(list.data.result.tools.length,10);
  assert(list.data.result.tools.some(t=>t.name==="shiori_spatial_node_position_set"));
  assert(!list.data.result.tools.some(t=>t.name==="shiori_graph_restructure_apply"));
  assert(list.data.result.tools.some(t=>t.name==="shiori_system_operations_list"));
  const caps=await call(e,"/mcp",rpc("tools/call",{name:"shiori_system_capabilities_read",arguments:{workspace_id:"personal"}}));
  assert.equal(caps.data.result.structuredContent.capabilities.local_rust_sync,false);
});

test("task create, list, get, retry and status mutations",async()=>{
  const e=env();
  const newTask=await call(e,"/api/v1/ops/tasks.create",request("create-0001",{title:"Prepare derrick inspection",text:"Sample"}));
  assert.equal(newTask.status,200,JSON.stringify(newTask.data));
  assert.equal(newTask.data.data.revision,1);
  const id=newTask.data.data.resource_id;
  const replay=await call(e,"/api/v1/ops/tasks.create",request("create-0001",{title:"Prepare derrick inspection",text:"Sample"}));
  assert.equal(replay.data.data.resource_id,id);
  const list=await call(e,"/mcp",rpc("tools/call",{name:"shiori_tasks_list",arguments:{workspace_id:"personal"}}));
  assert.equal(list.data.result.structuredContent.items.length,1);
  const get=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:id});
  assert.equal(get.data.data.item.version,1);
  const changed=await call(e,"/api/v1/ops/tasks.status.set",request("status-0001",{task_id:id,status:"in_progress",expected_revision:1}));
  assert.equal(changed.status,200,JSON.stringify(changed));
  assert.equal(changed.data.data.revision,2);
  const idem=await call(e,"/api/v1/ops/tasks.status.set",request("status-0001",{task_id:id,status:"in_progress",expected_revision:1}));
  assert.equal(idem.data.data.revision,2);
  const conflict=await call(e,"/api/v1/ops/tasks.status.set",request("status-0002",{task_id:id,status:"done",expected_revision:1}));
  assert.equal(conflict.status,409);
  const latest=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:id});
  assert.equal(latest.data.data.item.status,"in_progress");
});

test("view positions and connector style never touch canonical task version",async()=>{
  const e=env();
  const created=await call(e,"/api/v1/ops/tasks.create",request("create-0001",{title:"Shale export planning"}));
  const id=created.data.data.resource_id;
  const moved=await call(e,"/api/v1/ops/spatial.node.position.set",request("position-0001",{node_id:id,x:640,y:320,expected_revision:0}));
  assert.equal(moved.status,200,JSON.stringify(moved));
  assert.equal(moved.data.data.position.revision,1);
  assert.equal((await call(e,"/api/v1/ops/spatial.node.position.set",request("position-0002",{node_id:id,x:99,y:99,expected_revision:0}))).status,409);
  const styled=await call(e,"/api/v1/ops/spatial.edge.style.set",request("style-00001",{style:"circuit",expected_revision:0}));
  assert.equal(styled.status,200);
  const scene=await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"});
  assert.equal(scene.data.data.scene.nodes[0].x,640);
  assert.equal(scene.data.data.scene.connector_style,"circuit");
  assert.equal(scene.data.data.scene.synchronized_with_local_rust,false);
  const task=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:id});
  assert.equal(task.data.data.item.version,1);
});

test("reject unknown operations, unexpected fields and malformed data",async()=>{
  const e=env();
  assert.equal((await call(e,"/api/v1/ops/graph.restructure.apply",{workspace_id:"personal"})).status,404);
  assert.equal((await call(e,"/api/v1/ops/tasks.create",request("create-0001",{title:"Alpha",script:"delete all"}))).status,400);
  assert.equal((await call(e,"/api/v1/ops/spatial.node.position.set",request("position-0001",{node_id:"x",x:NaN,y:0,expected_revision:0}))).status,400);
  assert.equal((await call(e,"/api/v1/ops/tasks.list",{workspace_id:"personal",limit:10000})).status,400);
  const malformed=await worker.fetch(new Request("https://shiori-mcp-alpha.example.com/mcp",{method:"POST",headers:{authorization:"Bearer "+token},body:"{"}),e);
  assert.equal(malformed.status,400);
});
test("the implemented MCP schemas match the central Shiori operation registry",async()=>{
  const registry=JSON.parse(fs.readFileSync(new URL("../../../docs/api/operations.v1.json",import.meta.url),"utf8"));
  const available=registry.operations.filter(o=>o.availability==="cloudflare_alpha");
  assert.equal(available.length,10);
  const result=await call(env(),"/mcp",rpc("tools/list",{}));
  const tools=result.data.result.tools;
  assert.equal(tools.length,available.length);
  for(const entry of available){
    const tool=tools.find(t=>t.name===entry.mcp_tool);
    assert(tool,"Missing MCP tool "+entry.mcp_tool);
    const expected=entry.inputSchema;
    assert.deepEqual(tool.inputSchema.required,expected.required,entry.id);
    assert.deepEqual(tool.inputSchema.properties,expected.properties,entry.id);
    assert.equal(tool.inputSchema.additionalProperties,false);
    const expectedSource=entry.id==="system.operations.list"?
      "bundled-static-schema-not-task-data":"isolated_remote_d1_not_synced_with_local_rust";
    assert.equal(entry.data_source,expectedSource);
  }
});


test("capabilities reflect the credential actually used by the resource",async()=>{
  const e=env();
  const params={workspace_id:"personal"};
  const legacy=await call(e,"/mcp",rpc("tools/call",{name:"shiori_system_capabilities_read",arguments:params}));
  const meta=legacy.data.result.structuredContent.capabilities;
  assert.equal(meta.oauth,false);
  assert.equal(meta.authentication,"single-user-bearer");
  assert.equal(meta.write_access,true);
  e.SHIO_AUTH_MODE="oauth";
  e.SHIO_OAUTH_SCOPES=["mcp:read"];
  const read=await call(e,"/mcp",rpc("tools/call",{name:"shiori_system_capabilities_read",arguments:params}));
  assert.equal(read.data.result.structuredContent.capabilities.oauth,true);
  assert.equal(read.data.result.structuredContent.capabilities.authentication,"oauth2.1-pkce");
  assert.deepEqual(read.data.result.structuredContent.capabilities.granted_scopes,["mcp:read"]);
  assert.equal(read.data.result.structuredContent.capabilities.write_access,false);
  e.SHIO_OAUTH_SCOPES.push("mcp:write");
  const write=await call(e,"/mcp",rpc("tools/call",{name:"shiori_system_capabilities_read",arguments:params}));
  assert.equal(write.data.result.structuredContent.capabilities.write_access,true);
});

test("MCP tool errors preserve NOT_FOUND and revision conflict details",async()=>{
  const e=env();
  const fail=await call(e,"/mcp",rpc("tools/call",{name:"shiori_tasks_get",
    arguments:{workspace_id:"personal",task_id:"no-such-id"}}));
  assert.equal(fail.status,200);
  assert.equal(fail.data.result.isError,true);
  const body=fail.data.result.structuredContent;
  assert.deepEqual(body,{ok:false,error:{code:"NOT_FOUND",message:"Task not found in remote workspace",
    http_status:404,retryable:false}});
  assert.deepEqual(JSON.parse(fail.data.result.content[0].text),body);
  const noTitle=await call(e,"/mcp",rpc("tools/call",{name:"shiori_tasks_create",
    arguments:request("mcp-err-0001",{title:" "})}));
  assert.equal(noTitle.data.result.structuredContent.error.code,"VALIDATION_FAILED");
  assert.equal(noTitle.data.result.structuredContent.error.http_status,400);
});

test("idempotency cannot replay different create inputs or reordered JSON keys",async()=>{
  const e=env();
  const same="create-fingerprint-01";
  const first=await call(e,"/api/v1/ops/tasks.create",request(same,{title:"Prepare schedule",text:"Version one"}));
  assert.equal(first.status,200);
  const reordered={idempotency_key:same,text:"Version one",title:"Prepare schedule",workspace_id:"personal"};
  const replay=await call(e,"/api/v1/ops/tasks.create",reordered);
  assert.equal(replay.data.data.resource_id,first.data.data.resource_id);
  const changed=await call(e,"/api/v1/ops/tasks.create",request(same,{title:"Prepare schedule",text:"Version two"}));
  assert.equal(changed.status,409);
  assert.equal(changed.data.error.code,"IDEMPOTENCY_CONFLICT");
  const list=await call(e,"/api/v1/ops/tasks.list",{workspace_id:"personal"});
  assert.equal(list.data.data.items.length,1);
});

test("idempotency protects status, position and connector style writes",async()=>{
  const e=env();
  const first=await call(e,"/api/v1/ops/tasks.create",request("create-fingerprint-02",{title:"Trial record"}));
  const id=first.data.data.resource_id;
  const statusArgs=request("status-fingerprint-01",{task_id:id,status:"done",expected_revision:1});
  assert.equal((await call(e,"/api/v1/ops/tasks.status.set",statusArgs)).status,200);
  assert.equal((await call(e,"/api/v1/ops/tasks.status.set",statusArgs)).data.data.revision,2);
  const badStatus=await call(e,"/api/v1/ops/tasks.status.set",{...statusArgs,status:"todo"});
  assert.equal(badStatus.status,409);
  assert.equal(badStatus.data.error.code,"IDEMPOTENCY_CONFLICT");
  const posArgs=request("position-fingerprint-01",{node_id:id,x:45,y:70,expected_revision:0});
  assert.equal((await call(e,"/api/v1/ops/spatial.node.position.set",posArgs)).status,200);
  assert.equal((await call(e,"/api/v1/ops/spatial.node.position.set",posArgs)).data.data.position.revision,1);
  const badPos=await call(e,"/api/v1/ops/spatial.node.position.set",{...posArgs,x:46});
  assert.equal(badPos.data.error.code,"IDEMPOTENCY_CONFLICT");
  const styleArgs=request("style-fingerprint-01",{style:"curved",expected_revision:0});
  assert.equal((await call(e,"/api/v1/ops/spatial.edge.style.set",styleArgs)).status,200);
  const badStyle=await call(e,"/api/v1/ops/spatial.edge.style.set",{...styleArgs,style:"straight"});
  assert.equal(badStyle.data.error.code,"IDEMPOTENCY_CONFLICT");
  const style=await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"});
  assert.equal(style.data.data.scene.connector_style,"curved");
  assert.equal(style.data.data.scene.nodes[0].x,45);
  assert.equal((await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:id})).data.data.item.status,"done");
});

test("migration preserves legacy keys, which fail closed on replay",async()=>{
  const sql=fs.readFileSync(new URL("../schema.sql",import.meta.url),"utf8");
  const oldSql=sql.replace("  request_hash TEXT NOT NULL CHECK(length(request_hash)=64),\n","");
  assert.notEqual(sql,oldSql);
  const d=new DatabaseSync(":memory:");
  d.exec(oldSql);
  const legacyKey="create-old-key-01";
  d.prepare("INSERT INTO idempotency(workspace_id,operation_id,token,result_json,created_at) VALUES(?,?,?,?,?)")
    .run("personal","tasks.create",legacyKey,JSON.stringify({changed:true,resource_id:"legacy",revision:1}),"2026-11-15");
  d.exec(fs.readFileSync(new URL("../migrations/0001_idempotency_request_hash.sql",import.meta.url),"utf8"));
  const col=d.prepare("SELECT request_hash FROM idempotency WHERE token=?").get(legacyKey);
  assert.equal(col.request_hash,null);
  const e=env();
  e.DB.db=d;
  const bad=await call(e,"/api/v1/ops/tasks.create",request(legacyKey,{title:"New record"}));
  assert.equal(bad.status,409);
  assert.equal(bad.data.error.code,"IDEMPOTENCY_CONFLICT");
});

test("the full schema catalog is available to MCP clients, including output contracts",async()=>{
 const e=env();
 const expected=JSON.parse(fs.readFileSync(new URL("../../../docs/api/operations.v1.json",import.meta.url),"utf8"));
 assert.equal(expected.operations.length,113);
 const listed=await call(e,"/mcp",rpc("resources/list",{}));
 assert.equal(listed.data.result.resources[0].uri,"shiori://operations/v1");
 const templates=await call(e,"/mcp",rpc("resources/templates/list",{}));
 assert.match(templates.data.result.resourceTemplates[0].uriTemplate,/operation_id/);
 const full=await call(e,"/mcp",rpc("resources/read",{uri:"shiori://operations/v1"}));
 assert.deepEqual(JSON.parse(full.data.result.contents[0].text),expected);
 const individual=await call(e,"/mcp",rpc("resources/read",{uri:"shiori://operations/v1/tasks.delete"}));
 const entry=JSON.parse(individual.data.result.contents[0].text);
 assert.equal(entry.availability,"planned");
 assert.equal(entry.effect,"destructive");
 assert.deepEqual(entry.inputSchema,expected.operations.find(x=>x.id==="tasks.delete").inputSchema);
 assert.deepEqual(entry.outputSchema,expected.operations.find(x=>x.id==="tasks.delete").outputSchema);
 const missing=await call(e,"/mcp",rpc("resources/read",{uri:"shiori://operations/v1/not.real"}));
 assert.equal(missing.data.error.code,-32002);
 assert.equal((await call(e,"/mcp",rpc("resources/read",{uri:"shiori://operations/v1"}),{auth:null})).status,401);
});

test("catalog tool paginates all 113 schemas and filters availability and exact ID",async()=>{
 const e=env();
 const name="shiori_system_operations_list";
 const callCatalog=args=>call(e,"/mcp",rpc("tools/call",{name,arguments:{workspace_id:"personal",...args}}));
 const first=await callCatalog({limit:7});
 const a=first.data.result.structuredContent;
 assert.equal(a.registry_total,113);
 assert.equal(a.total,113);
 assert.equal(a.items.length,7);
 assert.equal(a.next_cursor,"7");
 assert(a.items[0].inputSchema);
 assert(a.items[0].outputSchema);
 const second=await callCatalog({limit:7,cursor:"7"});
 const b=second.data.result.structuredContent;
 assert.equal(b.items.length,7);
 assert.notEqual(a.items[0].id,b.items[0].id);
 const planned=await callCatalog({availability:"planned",limit:500});
 assert.equal(planned.data.result.structuredContent.total,103);
 const implemented=await callCatalog({availability:"cloudflare_alpha",limit:500});
 assert.equal(implemented.data.result.structuredContent.total,10);
 const item=await callCatalog({operation_id:"tasks.delete"});
 assert.equal(item.data.result.structuredContent.items.length,1);
 assert.equal(item.data.result.structuredContent.items[0].effect,"destructive");
 const missing=await callCatalog({operation_id:"unknown.operation"});
 assert.equal(missing.data.result.structuredContent.items.length,0);
 const invalid=await callCatalog({cursor:"15n"});
 assert.equal(invalid.data.result.structuredContent.error.code,"VALIDATION_FAILED");
});

test("planned operations are discoverable but never callable",async()=>{
 const e=env();
 const list=await call(e,"/mcp",rpc("tools/list",{}));
 const names=list.data.result.tools.map(x=>x.name);
 assert.equal(names.length,10);
 assert(!names.includes("shiori_tasks_delete"));
 const planned=await call(e,"/mcp",rpc("tools/call",{name:"shiori_tasks_delete",arguments:{
  workspace_id:"personal",task_id:"x",expected_revision:0,idempotency_key:"must-not-run-01"
 }}));
 assert.equal(planned.data.error.code,-32602);
 const http=await call(e,"/api/v1/ops/tasks.delete",{workspace_id:"personal"});
 assert.equal(http.status,404);
 assert.equal(http.data.error.code,"UNSUPPORTED_CAPABILITY");
 const tasks=await call(e,"/api/v1/ops/tasks.list",{workspace_id:"personal"});
 assert.deepEqual(tasks.data.data.items,[]);
});

test("capabilities advertise catalog URI and actual callable tool count",async()=>{
 const e=env();
 const caps=await call(e,"/mcp",rpc("tools/call",{name:"shiori_system_capabilities_read",
   arguments:{workspace_id:"personal"}}));
 const c=caps.data.result.structuredContent.capabilities;
 assert.equal(c.registry_total,113);
 assert.equal(c.planned_total,113);
 assert.equal(c.implemented_total,10);
 assert.equal(c.registry_uri,"shiori://operations/v1");
});
