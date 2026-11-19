import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {createHash} from "node:crypto";
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
  assert.equal(list.data.result.tools.length,33);
  assert(list.data.result.tools.some(t=>t.name==="shiori_spatial_node_position_set"));
  assert(!list.data.result.tools.some(t=>t.name==="shiori_graph_restructure_apply"));
  assert(list.data.result.tools.some(t=>t.name==="shiori_system_operations_list"));
  assert(list.data.result.tools.some(t=>t.name==="shiori_tasks_dependencies_add"));
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
  assert.equal(available.length,33);
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
 assert.equal(expected.operations.length,126);
 const listed=await call(e,"/mcp",rpc("resources/list",{}));
 assert.equal(listed.data.result.resources[0].uri,"shiori://operations/v1");
 const templates=await call(e,"/mcp",rpc("resources/templates/list",{}));
 assert.match(templates.data.result.resourceTemplates[0].uriTemplate,/operation_id/);
 const full=await call(e,"/mcp",rpc("resources/read",{uri:"shiori://operations/v1"}));
 assert.deepEqual(JSON.parse(full.data.result.contents[0].text),expected);
 const individual=await call(e,"/mcp",rpc("resources/read",{uri:"shiori://operations/v1/comments.delete"}));
 const entry=JSON.parse(individual.data.result.contents[0].text);
 assert.equal(entry.availability,"planned");
 assert.equal(entry.effect,"destructive");
 assert.deepEqual(entry.inputSchema,expected.operations.find(x=>x.id==="comments.delete").inputSchema);
 assert.deepEqual(entry.outputSchema,expected.operations.find(x=>x.id==="comments.delete").outputSchema);
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
 assert.equal(a.registry_total,126);
 assert.equal(a.total,126);
 assert.equal(a.items.length,7);
 assert.equal(a.next_cursor,"7");
 assert(a.items[0].inputSchema);
 assert(a.items[0].outputSchema);
 const second=await callCatalog({limit:7,cursor:"7"});
 const b=second.data.result.structuredContent;
 assert.equal(b.items.length,7);
 assert.notEqual(a.items[0].id,b.items[0].id);
 const planned=await callCatalog({availability:"planned",limit:500});
 assert.equal(planned.data.result.structuredContent.total,93);
 const implemented=await callCatalog({availability:"cloudflare_alpha",limit:500});
 assert.equal(implemented.data.result.structuredContent.total,33);
 const item=await callCatalog({operation_id:"comments.delete"});
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
 assert.equal(names.length,33);
 assert(!names.includes("shiori_comments_delete"));
 const planned=await call(e,"/mcp",rpc("tools/call",{name:"shiori_comments_delete",arguments:{
  workspace_id:"personal",task_id:"x",expected_revision:0,idempotency_key:"must-not-run-01"
 }}));
 assert.equal(planned.data.error.code,-32602);
 const http=await call(e,"/api/v1/ops/comments.delete",{workspace_id:"personal"});
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
 assert.equal(c.registry_total,126);
 assert.equal(c.planned_total,93);
 assert.equal(c.implemented_total,33);
 assert.equal(c.registry_uri,"shiori://operations/v1");
});


test("native prerequisite writes create real scene edges and increment task revision",async()=>{
 const e=env();
 const a=(await call(e,"/api/v1/ops/tasks.create",request("dummy-create-a01",{title:"Demo stage A"}))).data.data.resource_id;
 const b=(await call(e,"/api/v1/ops/tasks.create",request("dummy-create-b01",{title:"Demo stage B"}))).data.data.resource_id;
 const args=request("dependency-add-01",{task_id:b,depends_on_id:a,expected_revision:1});
 const created=await call(e,"/api/v1/ops/tasks.dependencies.add",args);
 assert.equal(created.status,200,JSON.stringify(created.data));
 assert.deepEqual(created.data.data,{changed:true,resource_id:b,depends_on_id:a,revision:2});
 const list=await call(e,"/api/v1/ops/tasks.dependencies.list",{workspace_id:"personal",task_id:b});
 assert.deepEqual(list.data.data.items,[{task_id:b,depends_on_id:a}]);
 const scene=await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"});
 assert.deepEqual(scene.data.data.scene.edges,[{from:a,to:b,kind:"blocks"}]);
 const now=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:b});
 assert.equal(now.data.data.item.version,2);
 assert.equal(now.data.data.item.status,"todo");
 assert.equal(now.data.data.item.body,"");
 const origin=(await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:a})).data.data.item;
 assert.equal(origin.version,1,"prerequisite's own revision does not change");
 const replay=await call(e,"/api/v1/ops/tasks.dependencies.add",args);
 assert.deepEqual(replay.data.data,created.data.data);
 const differentKey=await call(e,"/api/v1/ops/tasks.dependencies.add",{...args,idempotency_key:"dependency-add-02",expected_revision:2});
 assert.equal(differentKey.status,409);
 assert.equal(differentKey.data.error.code,"CONFLICT");
 const reusedWithDifferentTarget=await call(e,"/api/v1/ops/tasks.dependencies.add",{...args,depends_on_id:b});
 assert.equal(reusedWithDifferentTarget.status,409);
 assert.equal(reusedWithDifferentTarget.data.error.code,"IDEMPOTENCY_CONFLICT");
});

test("cycle and self-link checks reject invalid graph changes atomically",async()=>{
 const e=env();
 const create=async (label,key)=>(await call(e,"/api/v1/ops/tasks.create",request(key,{title:label}))).data.data.resource_id;
 const a=await create("A","dep-create-cycle-a");
 const b=await create("B","dep-create-cycle-b");
 const c=await create("C","dep-create-cycle-c");
 const add=(key,task,dependsOn,rev=1)=>call(e,"/api/v1/ops/tasks.dependencies.add",
   request(key,{task_id:task,depends_on_id:dependsOn,expected_revision:rev}));
 assert.equal((await add("dep-cycle-1",b,a)).status,200);
 assert.equal((await add("dep-cycle-2",c,b)).status,200);
 const cycle=await add("dep-cycle-3",a,c);
 assert.equal(cycle.status,409);
 assert.equal(cycle.data.error.code,"DEPENDENCY_CYCLE");
 const self=await add("dep-cycle-4",a,a);
 assert.equal(self.status,400);
 assert.equal(self.data.error.code,"VALIDATION_FAILED");
 const reverse=await add("dep-cycle-5",a,b);
 assert.equal(reverse.status,409);
 assert.equal(reverse.data.error.code,"DEPENDENCY_CYCLE");
 const scene=await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"});
 assert.equal(scene.data.data.scene.edges.length,2);
 const unchanged=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:a});
 assert.equal(unchanged.data.data.item.version,1);
 const noCycle=await call(e,"/api/v1/ops/tasks.dependencies.list",{workspace_id:"personal",task_id:a});
 assert.deepEqual(noCycle.data.data.items,[]);
});

test("prerequisite writes reject deleted, missing, cross-workspace and stale references",async()=>{
 const e=env();
 const a=(await call(e,"/api/v1/ops/tasks.create",request("dep-missing-a",{title:"A"}))).data.data.resource_id;
 const b=(await call(e,"/api/v1/ops/tasks.create",request("dep-missing-b",{title:"B"}))).data.data.resource_id;
 const dep=(key,task,prereq,rev=1)=>request(key,{task_id:task,depends_on_id:prereq,expected_revision:rev});
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.add",dep("dep-no-task",b,"not-here"))).status,404);
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.add",dep("dep-no-parent","not-here",a))).status,404);
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.add",dep("dep-stale-1",b,a,0))).status,409);
 const wrongWs=await call(e,"/api/v1/ops/tasks.dependencies.add",{...dep("dep-wrong-ws",b,a),workspace_id:"another"});
 assert.equal(wrongWs.status,403);
 // Deleted entries are inactive even though their rows remain.
 e.DB.db.prepare("UPDATE remote_tasks SET deleted_at=? WHERE id=?").run("2026-11-17T00:00:00Z",a);
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.add",dep("dep-deleted-1",b,a))).status,404);
 assert.deepEqual((await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"})).data.data.scene.edges,[]);
});

test("MCP prerequisite write is a distinct typed tool and rejects bad fields",async()=>{
 const e=env();
 const r=await call(e,"/mcp",rpc("tools/call",{
   name:"shiori_tasks_dependencies_add",
   arguments:{workspace_id:"personal",task_id:"one",depends_on_id:"two",expected_revision:1,idempotency_key:"mcp-dep-001",inject:"oops"}
 }));
 assert.equal(r.status,200);
 assert.equal(r.data.result.isError,true);
 assert.equal(r.data.result.structuredContent.error.code,"VALIDATION_FAILED");
});


test("expanded task editing and priority are revision guarded, idempotent and validate fields",async()=>{
 const e=env();
 const id=(await call(e,"/api/v1/ops/tasks.create",request("mut-task-001",{title:"Original",text:"Old note"}))).data.data.resource_id;
 const patch=request("mut-update-001",{task_id:id,title:"Renamed",text:"Revised description",expected_revision:1});
 const edited=await call(e,"/api/v1/ops/tasks.update",patch);
 assert.equal(edited.status,200,JSON.stringify(edited.data));
 assert.deepEqual(edited.data.data,{changed:true,resource_id:id,revision:2});
 assert.deepEqual((await call(e,"/api/v1/ops/tasks.update",patch)).data.data,edited.data.data);
 const conflict=await call(e,"/api/v1/ops/tasks.update",request("mut-update-002",{task_id:id,title:"stale",expected_revision:1}));
 assert.equal(conflict.status,409);
 const empty=await call(e,"/api/v1/ops/tasks.update",request("mut-update-003",{task_id:id,expected_revision:2}));
 assert.equal(empty.status,400);
 const notitle=await call(e,"/api/v1/ops/tasks.update",request("mut-update-004",{task_id:id,title:"  ",expected_revision:2}));
 assert.equal(notitle.status,400);
 const pri=await call(e,"/api/v1/ops/tasks.priority.set",request("mut-priority-1",{task_id:id,priority:"urgent",expected_revision:2}));
 assert.equal(pri.status,200);
 assert.equal(pri.data.data.revision,3);
 const again=await call(e,"/api/v1/ops/tasks.priority.set",request("mut-priority-2",{task_id:id,priority:"urgent",expected_revision:3}));
 assert.deepEqual(again.data.data,{changed:false,resource_id:id,revision:3});
 const get=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:id});
 assert.equal(get.data.data.item.title,"Renamed");
 assert.equal(get.data.data.item.body,"Revised description");
 assert.equal(get.data.data.item.priority,"urgent");
 const tamper=await call(e,"/mcp",rpc("tools/call",{name:"shiori_tasks_priority_set",arguments:request("mcp-pri-001",{task_id:id,priority:"not-valid",expected_revision:3})}));
 assert.equal(tamper.data.result.structuredContent.error.code,"VALIDATION_FAILED");
});

test("soft-delete and restore preserve graph identities without touching unrelated tasks",async()=>{
 const e=env();
 const a=(await call(e,"/api/v1/ops/tasks.create",request("delete-a-01",{title:"A"}))).data.data.resource_id;
 const b=(await call(e,"/api/v1/ops/tasks.create",request("delete-b-01",{title:"B"}))).data.data.resource_id;
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.add",request("before-delete-dep",{task_id:b,depends_on_id:a,expected_revision:1}))).status,200);
 const del=request("delete-001",{task_id:a,expected_revision:1});
 const deleted=await call(e,"/api/v1/ops/tasks.delete",del);
 assert.equal(deleted.status,200,JSON.stringify(deleted.data));
 assert.equal(deleted.data.data.revision,2);
 assert.equal((await call(e,"/api/v1/ops/tasks.delete",del)).data.data.revision,2);
 assert.equal((await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:a})).status,404);
 const scene=await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"});
 assert.equal(scene.data.data.scene.nodes.length,1);
 assert.equal(scene.data.data.scene.edges.length,0);
 assert.equal((await call(e,"/api/v1/ops/tasks.restore",request("restore-stale-1",{task_id:a,expected_revision:1}))).status,409);
 const restored=await call(e,"/api/v1/ops/tasks.restore",request("restore-1",{task_id:a,expected_revision:2}));
 assert.equal(restored.status,200);
 assert.equal(restored.data.data.revision,3);
 const again=await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"});
 assert.equal(again.data.data.scene.edges.length,1);
 assert.equal((await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:b})).data.data.item.version,2);
});

test("dependency removal preserves revision and rejects stale duplicate attempts",async()=>{
 const e=env();
 const a=(await call(e,"/api/v1/ops/tasks.create",request("remove-da-01",{title:"A"}))).data.data.resource_id;
 const b=(await call(e,"/api/v1/ops/tasks.create",request("remove-db-01",{title:"B"}))).data.data.resource_id;
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.add",request("remove-dadd-01",{task_id:b,depends_on_id:a,expected_revision:1}))).status,200);
 const args=request("remove-dep-01",{task_id:b,depends_on_id:a,expected_revision:2});
 const out=await call(e,"/api/v1/ops/tasks.dependencies.remove",args);
 assert.equal(out.status,200,JSON.stringify(out.data));
 assert.equal(out.data.data.revision,3);
 assert.deepEqual((await call(e,"/api/v1/ops/tasks.dependencies.remove",args)).data.data,out.data.data);
 const list=await call(e,"/api/v1/ops/tasks.dependencies.list",{workspace_id:"personal",task_id:b});
 assert.deepEqual(list.data.data.items,[]);
 assert.equal((await call(e,"/api/v1/ops/tasks.dependencies.remove",request("remove-dep-02",{task_id:b,depends_on_id:a,expected_revision:3}))).status,404);
});

test("spatial read, viewport save, layout lock and bounded scene export",async()=>{
 const e=env();
 const a=(await call(e,"/api/v1/ops/tasks.create",request("spatialnew-a",{title:"Position example"}))).data.data.resource_id;
 const initial=await call(e,"/api/v1/ops/spatial.node.position.read",{workspace_id:"personal",node_id:a});
 assert.equal(initial.data.data.item.revision,0);
 assert.equal(initial.data.data.item.stored,false);
 const moved=await call(e,"/api/v1/ops/spatial.node.position.set",request("spatialnew-p",{node_id:a,x:150,y:75,expected_revision:0}));
 assert.equal(moved.status,200);
 const position=await call(e,"/api/v1/ops/spatial.node.position.read",{workspace_id:"personal",node_id:a});
 assert.equal(position.data.data.item.x,150);
 assert.equal(position.data.data.item.revision,1);
 const inspected=await call(e,"/api/v1/ops/spatial.node.inspect",{workspace_id:"personal",node_id:a});
 assert.equal(inspected.data.data.item.id,a);
 assert.equal(inspected.data.data.item.position.x,150);
 const viewport=await call(e,"/api/v1/ops/spatial.viewport.save",request("spatialnew-view",{viewport:{x:80,y:-12,zoom:1.5},expected_revision:0}));
 assert.equal(viewport.status,200,JSON.stringify(viewport.data));
 assert.equal((await call(e,"/api/v1/ops/spatial.viewport.read",{workspace_id:"personal"})).data.data.item.viewport.zoom,1.5);
 assert.equal((await call(e,"/api/v1/ops/spatial.viewport.save",request("spatialnew-view2",{viewport:{x:0,y:0,zoom:0},expected_revision:1}))).status,400);
 assert.equal((await call(e,"/api/v1/ops/spatial.viewport.save",request("spatialnew-view3",{viewport:{x:0,y:0,zoom:1,extra:true},expected_revision:1}))).status,400);
 const locked=await call(e,"/api/v1/ops/spatial.layout.lock.set",request("spatialnew-lock",{locked:true,expected_revision:0}));
 assert.equal(locked.status,200,JSON.stringify(locked.data));
 assert.equal((await call(e,"/api/v1/ops/spatial.scene.read",{workspace_id:"personal"})).data.data.scene.layout_locked,true);
 const scene=await call(e,"/api/v1/ops/spatial.scene.export",{workspace_id:"personal"});
 assert.equal(scene.status,200,JSON.stringify(scene.data));
 assert.equal(scene.data.data.scene.nodes.length,1);
 assert.equal(scene.data.data.scene.nodes[0].x,150);
 const denied=await call(e,"/api/v1/ops/spatial.scene.export",{workspace_id:"personal",scene_id:"other"});
 assert.equal(denied.status,404);
});


test("S1 manifest returns paged identities and tombstones without exposing task contents",async()=>{
 const e=env();
 const create=async(key,title,text)=>(
  await call(e,"/api/v1/ops/tasks.create",request(key,{title,text}))
 ).data.data.resource_id;
 const a=await create("manifest-create-01","Private supplier quote","SECRET NOTES SHOULD NEVER LEAK");
 const b=await create("manifest-create-02","Confidential customer","NONPUBLIC NOTES");
 const deleted=await call(e,"/api/v1/ops/tasks.delete",request("manifest-delete-01",{task_id:b,expected_revision:1}));
 assert.equal(deleted.status,200);
 const all=await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"personal",limit:1});
 assert.equal(all.status,200,JSON.stringify(all.data));
 const page=all.data.data;
 assert.equal(page.items.length,1);
 assert.equal(page.consistent_snapshot,false,"cursor pages are never advertised as atomic snapshots");
 assert.equal(page.local_rust_sync,false);
 assert(page.next_cursor);
 const second=await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"personal",limit:1,cursor:page.next_cursor});
 assert.equal(second.status,200);
 const items=page.items.concat(second.data.data.items);
 assert.deepEqual(items.map(x=>x.id).sort(),[a,b].sort());
 assert.equal(items.find(x=>x.id===b).version,2);
 assert(items.find(x=>x.id===b).deleted_at);
 const serial=JSON.stringify(items);
 assert(!serial.includes("SECRET NOTES")&&!serial.includes("NONPUBLIC")&&!serial.includes("Private supplier quote"));
 for(const item of items){
  assert.deepEqual(Object.keys(item).sort(),["deleted_at","id","status","updated_at","version"].sort());
 }
 const end=await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"personal",limit:2,cursor:second.data.data.next_cursor??"ffffffff-ffffffff"});
 assert.equal(end.status,200);
 assert.equal(end.data.data.items.length,0);
});
test("S1 manifest is private and its pagination rejects invalid inputs",async()=>{
 const e=env();
 assert.equal((await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"personal"},{auth:null})).status,401);
 assert.equal((await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"other"})).status,403);
 assert.equal((await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"personal",cursor:"a' OR 1=1"})).status,400);
 assert.equal((await call(e,"/api/v1/ops/sync.manifest.read",{workspace_id:"personal",limit:101})).status,400);
 e.SHIO_AUTH_MODE="oauth"; e.SHIO_OAUTH_SCOPES=["mcp:read"];
 const result=await call(e,"/mcp",rpc("tools/call",{name:"shiori_sync_manifest_read",arguments:{workspace_id:"personal"}}));
 assert.equal(result.data.result.isError,undefined);
 assert.equal(result.data.result.structuredContent.local_rust_sync,false);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM idempotency").get().n,0,"read must not create mutations");
});


function importFixture(){
 const device_id="22222222-2222-4222-8222-222222222222";
 const task_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
 const event_id="sync1:"+device_id+":"+task_id+":1";
 const envelope={schema_version:1,event_id,origin_device_id:device_id,
   workspace_id:"personal",
   task:{id:task_id,title:"[DUMMY] Native owner-approved first import",
     notes:"Fixture note intentionally preserved",project:"Fixture",priority:"high",
     status:"todo",due_on:"2026-11-20",estimate_minutes:30,assignee_id:"local",
     created_at:"2026-11-18T08:00:00Z",updated_at:"2026-11-18T08:00:00Z",
     completed_at:null,version:1,deleted_at:null},
   depends_on:[]};
 const payload_json=JSON.stringify(envelope);
 const payload_sha256=createHash("sha256").update(payload_json).digest("hex");
 return {device_id,task_id,event_id,envelope,payload_json,payload_sha256};
}
async function pairFixture(e,fixture=importFixture(),key="pair-00001"){
 return call(e,"/api/v1/ops/sync.device.pair",request(key,{
  device_id:fixture.device_id,confirm_pairing:true
 }));
}
async function previewFixture(e,fixture=importFixture(),key="preview-0001"){
 return call(e,"/api/v1/ops/sync.import.preview",request(key,{
  device_id:fixture.device_id,task_id:fixture.task_id,event_id:fixture.event_id,
  local_version:1,payload_sha256:fixture.payload_sha256
 }));
}
test("S2 refuses unpaired or unapproved uploads and never sends title in preview",async()=>{
 const e=env(),f=importFixture();
 const withoutPair=await previewFixture(e,f);
 assert.equal(withoutPair.status,403);
 assert.equal((await call(e,"/api/v1/ops/sync.device.pair",request("pair-denied-1",{device_id:f.device_id,confirm_pairing:false}))).status,412);
 assert.equal((await call(e,"/api/v1/ops/sync.device.pair",request("pair-invalid-1",{device_id:"not-uuid",confirm_pairing:true}))).status,400);
 assert.equal((await pairFixture(e,f)).status,200);
 const replay=await pairFixture(e,f);
 assert.equal(replay.status,200,"same owner pairing key is idempotent");
 assert.equal((await pairFixture(e,f,"pair-newkey")).status,409);
 const preview=await previewFixture(e,f,"preview-good-1");
 assert.equal(preview.status,200,JSON.stringify(preview.data));
 assert(preview.data.data.proposal_id);
 assert(!JSON.stringify(preview.data).includes(f.envelope.task.title));
 const stored=e.DB.db.prepare("SELECT * FROM sync_import_previews WHERE task_id=?").get(f.task_id);
 assert(!JSON.stringify(stored).includes(f.envelope.task.notes));
 assert.equal(stored.payload_sha256,f.payload_sha256);
 assert.equal((await previewFixture(e,f,"preview-good-1")).data.data.proposal_id,preview.data.data.proposal_id);
 const denied=await call(e,"/api/v1/ops/sync.import.apply",request("import-denied-1",{
   proposal_id:preview.data.data.proposal_id,payload_json:f.payload_json,owner_approved:false
 }));
 assert.equal(denied.status,412);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM remote_tasks").get().n,0);
});

test("S2 commits a lossless new native task, proves receipt and avoids replay duplication",async()=>{
 const e=env(),f=importFixture();
 assert.equal((await pairFixture(e,f)).status,200);
 const preview=await previewFixture(e,f);
 assert.equal(preview.status,200);
 const args=request("apply-demo-01",{
    proposal_id:preview.data.data.proposal_id,payload_json:f.payload_json,owner_approved:true});
 const result=await call(e,"/api/v1/ops/sync.import.apply",args);
 assert.equal(result.status,200,JSON.stringify(result.data));
 const receipt=result.data.data;
 assert.deepEqual(
   {resource_id:receipt.resource_id,revision:receipt.revision,source_event_id:receipt.source_event_id,source_version:receipt.source_version,source_payload_sha256:receipt.source_payload_sha256},
   {resource_id:f.task_id,revision:1,source_event_id:f.event_id,source_version:1,source_payload_sha256:f.payload_sha256}
 );
 const source=e.DB.db.prepare("SELECT * FROM sync_imports WHERE event_id=?").get(f.event_id);
 assert.equal(source.payload_json,f.payload_json,"all native fields must be retained");
 assert.equal(source.device_id,f.device_id);
 const remote=await call(e,"/api/v1/ops/tasks.get",{workspace_id:"personal",task_id:f.task_id});
 assert.equal(remote.status,200);
 assert.equal(remote.data.data.item.id,f.task_id);
 assert.equal(remote.data.data.item.body,f.envelope.task.notes);
 assert.equal(remote.data.data.item.project,f.envelope.task.project);
 const receiptResult=await call(e,"/api/v1/ops/sync.import.receipt.read",{workspace_id:"personal",event_id:f.event_id});
 assert.equal(receiptResult.status,200);
 assert.equal(receiptResult.data.data.receipt_id,receipt.receipt_id);
 assert.equal(receiptResult.data.data.remote_modified,false);
 assert(!JSON.stringify(receiptResult.data.data).includes("Fixture note"));
 const repeat=await call(e,"/api/v1/ops/sync.import.apply",args);
 assert.deepEqual(repeat.data.data,receipt);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM sync_imports").get().n,1);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM remote_tasks").get().n,1);
 const differentKey=await call(e,"/api/v1/ops/sync.import.apply",{...args,idempotency_key:"different-apply"});
 assert.equal(differentKey.status,409);
 const changed=await call(e,"/api/v1/ops/tasks.status.set",request("change-after-1",{task_id:f.task_id,status:"in_progress",expected_revision:1}));
 assert.equal(changed.status,200);
 const after=await call(e,"/api/v1/ops/sync.import.receipt.read",{workspace_id:"personal",event_id:f.event_id});
 assert.equal(after.data.data.remote_revision,2);
 assert.equal(after.data.data.remote_modified,true,"remote edits break initial convergence");
});

test("S2 rejects changed payload, bad schema, dependencies, expired preview and remote ID collisions",async()=>{
 const e=env(),f=importFixture();
 await pairFixture(e,f);
 const preview=await previewFixture(e,f);
 const proposal_id=preview.data.data.proposal_id;
 const invalidHash=await call(e,"/api/v1/ops/sync.import.apply",request("wrong-hash-1",{
  proposal_id,owner_approved:true,payload_json:f.payload_json+" "
 }));
 assert.equal(invalidHash.status,409);
 const before=e.DB.db.prepare("SELECT * FROM sync_import_previews WHERE proposal_id=?").get(proposal_id);
 assert.equal(before.used_at,null);
 const badEnvelope={...f.envelope,depends_on:["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]};
 const payload_json=JSON.stringify(badEnvelope);
 const payload_sha256=createHash("sha256").update(payload_json).digest("hex");
 const anotherPreview=await call(e,"/api/v1/ops/sync.import.preview",request("preview-changed-1",{
  device_id:f.device_id,task_id:f.task_id,event_id:f.event_id,local_version:1,payload_sha256
 }));
 assert.equal(anotherPreview.status,200);
 const bad=await call(e,"/api/v1/ops/sync.import.apply",request("apply-dependent-1",{
   proposal_id:anotherPreview.data.data.proposal_id,payload_json,owner_approved:true
 }));
 assert.equal(bad.status,400);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM remote_tasks").get().n,0);
 e.DB.db.prepare("UPDATE sync_import_previews SET expires_at=? WHERE proposal_id=?").run("2020-01-01T00:00:00Z",proposal_id);
 const expired=await call(e,"/api/v1/ops/sync.import.apply",request("apply-expired-1",{
  proposal_id,payload_json:f.payload_json,owner_approved:true
 }));
 assert.equal(expired.status,409);
 // Task IDs are globally unique even across workspaces and soft deletes.
 e.DB.db.prepare("INSERT INTO remote_tasks(id,workspace_id,title,created_at,updated_at,deleted_at) VALUES(?,?,?,?,?,?)")
  .run(f.task_id,"different", "Existing historical task","2026-01-01Z","2026-01-01Z","2026-01-02Z");
 const collision=await previewFixture(e,f,"preview-collision");
 assert.equal(collision.status,409);
 assert.equal(e.DB.db.prepare("SELECT title FROM remote_tasks WHERE id=?").get(f.task_id).title,"Existing historical task");
});
test("S2 receipt is scoped and read-only OAuth is not allowed to mutate pairing or import",async()=>{
 const e=env(),f=importFixture();
 assert.equal((await call(e,"/api/v1/ops/sync.import.receipt.read",{workspace_id:"personal",event_id:f.event_id})).status,404);
 assert.equal((await call(e,"/api/v1/ops/sync.device.pair",request("invalid-ws-1",{
  device_id:f.device_id,confirm_pairing:true,workspace_id:"other"
 }))).status,403);
 const manifest=await call(e,"/mcp",rpc("tools/list",{}));
 for(const name of ["shiori_sync_device_pair","shiori_sync_import_preview","shiori_sync_import_apply","shiori_sync_import_receipt_read"])
   assert(manifest.data.result.tools.some(t=>t.name===name));
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM sync_imports").get().n,0);
});


test("S3 change log captures task revisions/tombstones and dependency edges without content",async()=>{
 const e=env();
 const empty=await call(e,"/api/v1/ops/sync.changes.read",{workspace_id:"personal"});
 assert.equal(empty.status,200);
 assert.deepEqual(empty.data.data.changes,[]);
 assert.equal(empty.data.data.baseline_required,true);
 assert.equal(empty.data.data.local_rust_sync,false);
 const first=await call(e,"/api/v1/ops/tasks.create",request("feed-create-1",{
  title:"SECRET TASK TITLE",text:"SECRET PRIVATE NOTES"
 }));
 assert.equal(first.status,200,JSON.stringify(first.data));
 const id=first.data.data.resource_id;
 const updated=await call(e,"/api/v1/ops/tasks.status.set",request("feed-status-1",{
  task_id:id,status:"in_progress",expected_revision:1
 }));
 assert.equal(updated.status,200);
 const dependency="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
 e.DB.db.prepare("INSERT INTO remote_dependencies(workspace_id,task_id,depends_on_id) VALUES(?,?,?)")
  .run("personal",id,dependency);
 e.DB.db.prepare("DELETE FROM remote_dependencies WHERE workspace_id=? AND task_id=? AND depends_on_id=?")
  .run("personal",id,dependency);
 const del=await call(e,"/api/v1/ops/tasks.delete",request("feed-delete-1",{
  task_id:id,expected_revision:2
 }));
 assert.equal(del.status,200,JSON.stringify(del.data));
 const page=await call(e,"/api/v1/ops/sync.changes.read",{workspace_id:"personal",limit:100});
 assert.equal(page.status,200,JSON.stringify(page.data));
 const feed=page.data.data;
 assert.deepEqual(feed.changes.map(x=>x.kind),
  ["task.insert","task.update","edge.add","edge.remove","task.delete"]);
 assert.deepEqual(feed.changes.map(x=>x.task_id),[id,id,id,id,id]);
 assert.equal(feed.changes[0].task_version,1);
 assert.equal(feed.changes[1].task_version,2);
 assert.equal(feed.changes[4].task_version,3);
 assert.equal(feed.changes[2].depends_on_id,dependency);
 assert.equal(feed.changes[3].depends_on_id,dependency);
 assert.equal(feed.changes[0].depends_on_id,null);
 assert.equal(feed.changes[2].task_version,null);
 assert.equal(feed.next_cursor,null);
 assert.equal(feed.checkpoint_cursor,feed.cutoff);
 assert.equal(feed.cutoff,5);
 assert.deepEqual(feed.changes.map(x=>x.seq),[1,2,3,4,5]);
 assert(!JSON.stringify(feed).includes("SECRET TASK TITLE"));
 assert(!JSON.stringify(feed).includes("SECRET PRIVATE NOTES"));
});
test("S3 fixed high-watermark pagination never skips or includes new events mid-stream",async()=>{
 const e=env();
 for(let i=0;i<5;i++){
  const created=await call(e,"/api/v1/ops/tasks.create",request("feed-item-"+i,{
   title:"[DUMMY] Remote feed item "+i
  }));
  assert.equal(created.status,200);
 }
 const first=await call(e,"/api/v1/ops/sync.changes.read",{workspace_id:"personal",cursor:0,limit:2});
 assert.equal(first.status,200,JSON.stringify(first.data));
 const p1=first.data.data;
 assert.equal(p1.cutoff,5);
 assert.deepEqual(p1.changes.map(x=>x.seq),[1,2]);
 assert.equal(p1.next_cursor,2);
 assert.equal(p1.checkpoint_cursor,2);
 const future=await call(e,"/api/v1/ops/tasks.create",request("feed-new-after-cutoff",{
  title:"[DUMMY] New event after read"
 }));
 assert.equal(future.status,200);
 const second=await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",cursor:p1.next_cursor,cutoff:p1.cutoff,limit:2
 });
 assert.equal(second.status,200);
 assert.deepEqual(second.data.data.changes.map(x=>x.seq),[3,4]);
 const third=await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",cursor:second.data.data.next_cursor,cutoff:p1.cutoff,limit:2
 });
 assert.equal(third.status,200);
 assert.deepEqual(third.data.data.changes.map(x=>x.seq),[5]);
 assert.equal(third.data.data.next_cursor,null);
 assert.equal(third.data.data.checkpoint_cursor,5);
 const next=await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",cursor:third.data.data.checkpoint_cursor,limit:100
 });
 assert.equal(next.status,200);
 assert.deepEqual(next.data.data.changes.map(x=>x.seq),[6]);
 assert.equal(next.data.data.checkpoint_cursor,6);
 assert.equal((await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",cursor:3,cutoff:2
 })).status,400);
 assert.equal((await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",cursor:0,cutoff:999999
 })).status,400);
 assert.equal((await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",limit:101
 })).status,400);
});
test("S3 scope boundary and non-task workspaces do not leak D1 changes",async()=>{
 const e=env();
 e.DB.db.prepare(
  "INSERT INTO remote_tasks(id,workspace_id,title,created_at,updated_at) VALUES(?,?,?,?,?)"
 ).run("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","other",
  "Unrelated workspace secret","2026-11-18T00:00:00Z","2026-11-18T00:00:00Z");
 const read=await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal",cursor:0,limit:3
 });
 assert.equal(read.status,200);
 assert.deepEqual(read.data.data.changes,[]);
 assert.equal(read.data.data.cutoff,1,"global sequence does not expose other workspaces' task IDs");
 assert.equal(read.data.data.checkpoint_cursor,1);
 assert.equal((await call(e,"/api/v1/ops/sync.changes.read",{workspace_id:"other"})).status,403);
 assert.equal((await call(e,"/api/v1/ops/sync.changes.read",{
  workspace_id:"personal"
 },{auth:null})).status,401);
 e.SHIO_AUTH_MODE="oauth";
 e.SHIO_OAUTH_SCOPES=["mcp:read"];
 const rpcRead=await call(e,"/mcp",rpc("tools/call",{
  name:"shiori_sync_changes_read",arguments:{workspace_id:"personal",cursor:1}
 }));
 assert.equal(rpcRead.status,200);
 assert.equal(rpcRead.data.result.isError,undefined);
 assert.equal(rpcRead.data.result.structuredContent.local_rust_sync,false);
});


test("S3 atomic baseline pairs task/tombstone/edge metadata with one exact feed cutoff",async()=>{
 const e=env();
 const empty=await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"personal"});
 assert.equal(empty.status,200,JSON.stringify(empty.data));
 assert.deepEqual(empty.data.data.items,[]);
 assert.deepEqual(empty.data.data.edges,[]);
 assert.equal(empty.data.data.cutoff,0);
 assert.equal(empty.data.data.consistent_snapshot,true);
 assert.equal(empty.data.data.automatic_apply,false);
 assert.equal(empty.data.data.local_rust_sync,false);
 const a=(await call(e,"/api/v1/ops/tasks.create",
   request("baseline-create-a",{title:"SECRET private title",text:"SECRET private notes"}))).data.data.resource_id;
 const b=(await call(e,"/api/v1/ops/tasks.create",
   request("baseline-create-b",{title:"Another secret"}))).data.data.resource_id;
 const edge=await call(e,"/api/v1/ops/tasks.dependencies.add",request("baseline-edge-b-a",{
   task_id:b,depends_on_id:a,expected_revision:1
 }));
 assert.equal(edge.status,200,JSON.stringify(edge.data));
 const deleted=await call(e,"/api/v1/ops/tasks.delete",request("baseline-del-a",{
   task_id:a,expected_revision:1
 }));
 assert.equal(deleted.status,200);
 const snap=await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"personal"});
 assert.equal(snap.status,200,JSON.stringify(snap.data));
 const data=snap.data.data;
 assert.equal(data.task_count,2);
 assert.equal(data.edge_count,1);
 assert.equal(data.cutoff,5,"dependency creation also bumps the dependent task revision");
 assert.deepEqual(data.items.map(x=>x.id),[a,b].sort());
 assert.equal(data.items.find(x=>x.id===a).version,2);
 assert(data.items.find(x=>x.id===a).deleted_at);
 assert.deepEqual(data.edges,[{task_id:b,depends_on_id:a}]);
 assert.deepEqual(Object.keys(data.items[0]).sort(),
   ["id","version","status","updated_at","deleted_at"].sort());
 assert(!JSON.stringify(data).includes("SECRET"),"No titles, notes or private task contents");
 // A later event is covered by starting S3 delta reads AT the snapshot cutoff.
 const changed=await call(e,"/api/v1/ops/tasks.status.set",request("baseline-change-b",{
   task_id:b,status:"in_progress",expected_revision:2
 }));
 assert.equal(changed.status,200);
 const delta=await call(e,"/api/v1/ops/sync.changes.read",{
   workspace_id:"personal",cursor:data.cutoff,limit:100
 });
 assert.equal(delta.status,200);
 assert.deepEqual(delta.data.data.changes.map(x=>x.seq),[6]);
 assert.equal(delta.data.data.changes[0].task_id,b);
 assert.equal(delta.data.data.changes[0].kind,"task.update");
});

test("S3 baseline fails closed for oversized or dangling graphs without truncation",async()=>{
 const e=env();
 const d=e.DB.db;
 for(let i=0;i<101;i++){
  d.prepare("INSERT INTO remote_tasks(id,workspace_id,title,created_at,updated_at) VALUES(?,?,?,?,?)")
   .run("fixture-"+String(i).padStart(3,"0"),"personal","Private sample "+i,
     "2026-11-18T00:00:00Z","2026-11-18T00:00:00Z");
 }
 const large=await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"personal"});
 assert.equal(large.status,413);
 assert.equal(large.data.error.code,"UNAVAILABLE");
 d.prepare("DELETE FROM remote_tasks WHERE id=?").run("fixture-100");
 const normal=await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"personal"});
 assert.equal(normal.status,200);
 assert.equal(normal.data.data.task_count,100);
 const id="fixture-001";
 d.prepare("INSERT INTO remote_dependencies(workspace_id,task_id,depends_on_id) VALUES(?,?,?)")
  .run("personal",id,"missing-dependency");
 const dangling=await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"personal"});
 assert.equal(dangling.status,409);
 assert.equal(dangling.data.error.code,"CONFLICT");
 assert.equal(d.prepare("SELECT COUNT(*) AS n FROM remote_tasks WHERE workspace_id='personal'").get().n,100);
});

test("S3 baseline respects OAuth read-only scopes and cross-workspace isolation",async()=>{
 const e=env();
 e.DB.db.prepare("INSERT INTO remote_tasks(id,workspace_id,title,created_at,updated_at) VALUES(?,?,?,?,?)")
  .run("other-secret","another","SECRET other workspace",
    "2026-11-18T00:00:00Z","2026-11-18T00:00:00Z");
 e.SHIO_AUTH_MODE="oauth";e.SHIO_OAUTH_SCOPES=["mcp:read"];
 const rpcCall=await call(e,"/mcp",rpc("tools/call",{
   name:"shiori_sync_baseline_read",arguments:{workspace_id:"personal"}
 }));
 assert.equal(rpcCall.status,200,JSON.stringify(rpcCall.data));
 assert.equal(rpcCall.data.result.structuredContent.consistent_snapshot,true);
 assert.equal(rpcCall.data.result.structuredContent.task_count,0);
 assert.equal((await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"another"})).status,403);
 assert.equal((await call(e,"/api/v1/ops/sync.baseline.read",{workspace_id:"personal"},{auth:null})).status,401);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM idempotency").get().n,0,
   "Snapshot read must be entirely nonmutating");
});


test("S3 owner revocation is permanent, idempotent, and blocks stale import proposals",async()=>{
 const e=env(),f=importFixture();
 const statusPath="/api/v1/ops/sync.device.status.read";
 const revokePath="/api/v1/ops/sync.device.revoke";
 assert.equal((await call(e,statusPath,{workspace_id:"personal",device_id:f.device_id})).status,404);
 assert.equal((await pairFixture(e,f)).status,200);
 const before=await call(e,statusPath,{workspace_id:"personal",device_id:f.device_id});
 assert.equal(before.status,200);
 assert.equal(before.data.data.can_import,true);
 assert.equal(before.data.data.revoked_at,null);
 const preview=await previewFixture(e,f,"revoke-existing-proposal-1");
 assert.equal(preview.status,200,JSON.stringify(preview.data));
 const refused=await call(e,revokePath,request("revoke-denied-1",{
  device_id:f.device_id,confirm_revocation:false
 }));
 assert.equal(refused.status,412);
 assert.equal((await call(e,statusPath,{workspace_id:"personal",device_id:f.device_id})).data.data.can_import,true);
 const args=request("revoke-approved-owner-1",{device_id:f.device_id,confirm_revocation:true});
 const revoke=await call(e,revokePath,args);
 assert.equal(revoke.status,200,JSON.stringify(revoke.data));
 assert.equal(revoke.data.data.changed,true);
 assert.equal(revoke.data.data.device_id,f.device_id);
 assert(revoke.data.data.revoked_at);
 const replay=await call(e,revokePath,args);
 assert.deepEqual(replay.data.data,revoke.data.data,"same approval key is replay-safe");
 assert.equal((await call(e,revokePath,request("revoke-another-key-1",{
  device_id:f.device_id,confirm_revocation:true
 }))).status,409,"new approval cannot revoke a second time");
 const after=await call(e,statusPath,{workspace_id:"personal",device_id:f.device_id});
 assert.equal(after.status,200);
 assert.equal(after.data.data.can_import,false);
 assert.equal(after.data.data.revoked_at,revoke.data.data.revoked_at);
 assert.equal((await previewFixture(e,f,"revoked-preview-1")).status,403);
 assert.equal((await pairFixture(e,f,"revoked-repair-1")).status,409,
   "revoking must not resurrect old device identity");
 const stale=await call(e,"/api/v1/ops/sync.import.apply",request("apply-before-revoked-1",{
   proposal_id:preview.data.data.proposal_id,payload_json:f.payload_json,owner_approved:true
 }));
 assert.equal(stale.status,403,"previously approved preview must not bypass revocation");
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM remote_tasks").get().n,0);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM sync_imports").get().n,0);
 assert.equal((await call(e,statusPath,{workspace_id:"other",device_id:f.device_id})).status,403);
 assert.equal((await call(e,statusPath,{workspace_id:"personal",device_id:f.device_id},{auth:null})).status,401);
});

test("S3 read-only OAuth may inspect device status but cannot revoke it",async()=>{
 const e=env(),f=importFixture();
 await pairFixture(e,f);
 e.SHIO_AUTH_MODE="oauth";e.SHIO_OAUTH_SCOPES=["mcp:read"];
 const status=await call(e,"/mcp",rpc("tools/call",{
   name:"shiori_sync_device_status_read",arguments:{workspace_id:"personal",device_id:f.device_id}
 }));
 assert.equal(status.status,200,JSON.stringify(status.data));
 assert.equal(status.data.result.structuredContent.can_import,true);
 const other=await call(e,"/mcp",rpc("tools/call",{
   name:"shiori_sync_device_revoke",
   arguments:request("oauth-revoke-denied-1",{device_id:f.device_id,confirm_revocation:true})
 }));
 assert.equal(other.status,200,"MCP tool errors are JSON-RPC results");
 assert.equal(other.data.result.isError,true);
 assert.equal(other.data.result.structuredContent.error.http_status,403,
   "Read-only OAuth cannot execute the revocation operation");
 const checked=await call(e,"/api/v1/ops/sync.device.status.read",{
   workspace_id:"personal",device_id:f.device_id
 });
 assert.equal(checked.data.data.can_import,true);
});


test("S4 current remote snapshot requires explicit content request and is owner scoped",async()=>{
 const e=env(),url="/api/v1/ops/sync.record.snapshot.read";
 const created=await call(e,"/api/v1/ops/tasks.create",request("s4-create-001",{
   title:"PRIVATE test title",text:"PRIVATE test notes"
 }));
 assert.equal(created.status,200);
 const task_id=created.data.data.resource_id;
 assert.equal((await call(e,url,{workspace_id:"personal",task_id})).status,400);
 assert.equal((await call(e,url,{workspace_id:"personal",task_id,include_content:false})).status,400);
 assert.equal((await call(e,url,{workspace_id:"other",task_id,include_content:true})).status,403);
 assert.equal((await call(e,url,{workspace_id:"personal",task_id,include_content:true},{auth:null})).status,401);
 assert.equal((await call(e,url,{workspace_id:"personal",task_id:"absent",include_content:true})).status,404);
 const snap=await call(e,url,{workspace_id:"personal",task_id,include_content:true});
 assert.equal(snap.status,200,JSON.stringify(snap.data));
 assert.equal(snap.data.data.record.title,"PRIVATE test title");
 assert.equal(snap.data.data.record.notes,"PRIVATE test notes");
 assert.equal(snap.data.data.record.deleted_at,null);
 assert.equal(snap.data.data.source_import,null,"Remote-only record has no verified S2 origin");
 assert.deepEqual(snap.data.data.depends_on,[]);
 assert.equal(snap.data.data.cutoff,1);
 assert.equal(snap.data.data.consistent_snapshot,true);
 assert.equal(snap.data.data.local_rust_sync,false);
 assert.equal(snap.data.data.automatic_apply,false);
 assert.match(snap.data.data.record_sha256,/^[0-9a-f]{64}$/);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM sync_imports").get().n,0);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM idempotency").get().n,1);
 e.SHIO_AUTH_MODE="oauth";e.SHIO_OAUTH_SCOPES=["mcp:read"];
 const rpcRead=await call(e,"/mcp",rpc("tools/call",{
   name:"shiori_sync_record_snapshot_read",
   arguments:{workspace_id:"personal",task_id,include_content:true}
 }));
 assert.equal(rpcRead.status,200,JSON.stringify(rpcRead.data));
 assert.equal(rpcRead.data.result.structuredContent.record.id,task_id);
});

test("S4 snapshot sees exact source receipt, tombstone, prerequisites and high-water together",async()=>{
 const e=env(),f=importFixture(),url="/api/v1/ops/sync.record.snapshot.read";
 assert.equal((await pairFixture(e,f)).status,200);
 const preview=await previewFixture(e,f);
 assert.equal(preview.status,200);
 const applied=await call(e,"/api/v1/ops/sync.import.apply",request("s4-import-001",{
  proposal_id:preview.data.data.proposal_id,
  payload_json:f.payload_json,owner_approved:true
 }));
 assert.equal(applied.status,200,JSON.stringify(applied.data));
 const origin=await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true});
 assert.equal(origin.status,200,JSON.stringify(origin.data));
 assert.equal(origin.data.data.source_import.source_event_id,f.event_id);
 assert.equal(origin.data.data.source_import.source_payload_sha256,f.payload_sha256);
 assert.equal(origin.data.data.source_import.receipt_id,applied.data.data.receipt_id);
 assert.equal(origin.data.data.record.notes,f.envelope.task.notes);
 assert.equal(origin.data.data.cutoff,1);
 const second=await call(e,"/api/v1/ops/tasks.create",request("s4-second-task",{
   title:"Independent prerequisite"
 }));
 const secondId=second.data.data.resource_id;
 assert.equal(second.status,200);
 const link=await call(e,"/api/v1/ops/tasks.dependencies.add",request("s4-first-dependency",{
  task_id:f.task_id,depends_on_id:secondId,expected_revision:1
 }));
 assert.equal(link.status,200,JSON.stringify(link.data));
 const beforeDelete=await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true});
 assert.equal(beforeDelete.data.data.cutoff,4);
 assert.equal(beforeDelete.data.data.record.version,2);
 assert.deepEqual(beforeDelete.data.data.depends_on,[secondId]);
 assert.notEqual(beforeDelete.data.data.record_sha256,origin.data.data.record_sha256);
 const del=await call(e,"/api/v1/ops/tasks.delete",request("s4-delete-task",{
  task_id:f.task_id,expected_revision:2
 }));
 assert.equal(del.status,200,JSON.stringify(del.data));
 const tombstone=await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true});
 assert.equal(tombstone.status,200);
 assert(tombstone.data.data.record.deleted_at,"Soft-deleted tasks must be included");
 assert.equal(tombstone.data.data.record.version,3);
 assert.equal(tombstone.data.data.cutoff,5);
 assert.deepEqual(tombstone.data.data.depends_on,[secondId]);
 assert.equal(tombstone.data.data.source_import.source_version,1);
 assert.equal(tombstone.data.data.automatic_apply,false);
 assert(!JSON.stringify(tombstone.data.data).includes(f.payload_json),
   "Do not expose historical full source payload");
});

test("S4 source snapshot has deterministic hash and refuses altered input schema",async()=>{
 const e=env(),url="/api/v1/ops/sync.record.snapshot.read";
 const created=await call(e,"/api/v1/ops/tasks.create",request("s4-hash-create",{
   title:"Hash source",text:"Do not leak to summary scans"
 }));
 const task_id=created.data.data.resource_id;
 const args={workspace_id:"personal",task_id,include_content:true};
 const first=await call(e,url,args),second=await call(e,url,args);
 assert.equal(first.status,200,JSON.stringify(first.data));
 assert.equal(first.data.data.record_sha256,second.data.data.record_sha256);
 assert.equal((await call(e,url,{...args,extra_field:"injection"})).status,400);
 assert.equal((await call(e,url,{...args,include_content:"true"})).status,400);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM remote_tasks").get().n,1);
});


test("S5 owner-approved paired source task update commits several fields atomically",async()=>{
 const e=env(),f=importFixture(),b="33333333-3333-4333-8333-333333333333";
 assert.equal((await pairFixture(e,f)).status,200);
 const p=await previewFixture(e,f);
 assert.equal(p.status,200);
 assert.equal((await call(e,"/api/v1/ops/sync.import.apply",request("s5-import-first",{
   proposal_id:p.data.data.proposal_id,payload_json:f.payload_json,owner_approved:true
 }))).status,200);
 assert.equal((await call(e,"/api/v1/ops/sync.device.pair",request("s5-pair-b",{
   device_id:b,confirm_pairing:true
 }))).status,200);
 const url="/api/v1/ops/sync.record.snapshot.read";
 const old=(await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true})).data.data;
 const args=request("s5-approved-atomic",{
  device_id:b,task_id:f.task_id,
  source_event_id:f.event_id,source_payload_sha256:f.payload_sha256,
  expected_revision:old.record.version,expected_record_sha256:old.record_sha256,
  patch:{notes:"Reviewed device B edit",status:"in_progress",priority:"urgent"},
  owner_approved:true
 });
 const applied=await call(e,"/api/v1/ops/sync.record.apply",args);
 assert.equal(applied.status,200,JSON.stringify(applied.data));
 assert.equal(applied.data.data.revision,2);
 assert.equal(applied.data.data.changed,true);
 assert.equal(applied.data.data.base_record_sha256,old.record_sha256);
 const after=await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true});
 assert.equal(after.status,200);
 assert.equal(after.data.data.record.notes,"Reviewed device B edit");
 assert.equal(after.data.data.record.priority,"urgent");
 assert.equal(after.data.data.record.status,"in_progress");
 assert.equal(after.data.data.record.version,2);
 assert.equal(after.data.data.cutoff,2,"One atomic multi-field update creates one task event");
 assert.deepEqual(after.data.data.depends_on,old.depends_on);
 assert.equal(after.data.data.source_import.source_event_id,f.event_id);
 const replay=await call(e,"/api/v1/ops/sync.record.apply",args);
 assert.deepEqual(replay.data.data,applied.data.data,"Replay must not bump revision twice");
 assert.equal((await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true})).data.data.record.version,2);
 const stale=await call(e,"/api/v1/ops/sync.record.apply",{
   ...args,idempotency_key:"s5-stale-different-key",patch:{title:"Offline device A change"}
 });
 assert.equal(stale.status,409,"Stale snapshot cannot overwrite another device");
 assert.equal((await call(e,url,{workspace_id:"personal",task_id:f.task_id,include_content:true})).data.data.record.title,
   f.envelope.task.title);
});

test("S5 rejects unpaired/revoked clients, wrong provenance and missing owner approval",async()=>{
 const e=env(),f=importFixture(),b="33333333-3333-4333-8333-333333333333";
 await pairFixture(e,f);
 const p=await previewFixture(e,f);
 await call(e,"/api/v1/ops/sync.import.apply",request("s5-source-apply",{
  proposal_id:p.data.data.proposal_id,payload_json:f.payload_json,owner_approved:true
 }));
 const before=(await call(e,"/api/v1/ops/sync.record.snapshot.read",{
   workspace_id:"personal",task_id:f.task_id,include_content:true
 })).data.data;
 const args=request("s5-scope",{
   device_id:b,task_id:f.task_id,source_event_id:f.event_id,
   source_payload_sha256:f.payload_sha256,expected_revision:1,
   expected_record_sha256:before.record_sha256,
   patch:{status:"done"},owner_approved:true
 });
 const endpoint="/api/v1/ops/sync.record.apply";
 assert.equal((await call(e,endpoint,args)).status,403);
 assert.equal((await call(e,"/api/v1/ops/sync.device.pair",request("s5-pair-client",{
  device_id:b,confirm_pairing:true
 }))).status,200);
 assert.equal((await call(e,endpoint,{...args,source_payload_sha256:"e".repeat(64)})).status,409);
 assert.equal((await call(e,endpoint,{...args,owner_approved:false})).status,400);
 assert.equal((await call(e,endpoint,{...args,patch:{due_on:"2026-11-30"}})).status,400);
 assert.equal((await call(e,endpoint,{...args,patch:{}})).status,400);
 const rev=await call(e,"/api/v1/ops/sync.device.revoke",request("s5-revoke",{
   device_id:b,confirm_revocation:true
 }));
 assert.equal(rev.status,200);
 assert.equal((await call(e,endpoint,args)).status,403);
 const current=(await call(e,"/api/v1/ops/sync.record.snapshot.read",{
  workspace_id:"personal",task_id:f.task_id,include_content:true
 })).data.data;
 assert.equal(current.record.version,1);
});

test("S5 refuses deleted records, stale hash and OAuth read-only writes",async()=>{
 const e=env(),f=importFixture();
 await pairFixture(e,f);
 const p=await previewFixture(e,f);
 await call(e,"/api/v1/ops/sync.import.apply",request("s5-source-tombstone",{
  proposal_id:p.data.data.proposal_id,payload_json:f.payload_json,owner_approved:true
 }));
 const base=(await call(e,"/api/v1/ops/sync.record.snapshot.read",{
  workspace_id:"personal",task_id:f.task_id,include_content:true
 })).data.data;
 const args=request("s5-owner-update",{
   device_id:f.device_id,task_id:f.task_id,
   source_event_id:f.event_id,source_payload_sha256:f.payload_sha256,
   expected_revision:base.record.version,expected_record_sha256:base.record_sha256,
   patch:{notes:"Changed"},owner_approved:true
 });
 e.SHIO_AUTH_MODE="oauth";e.SHIO_OAUTH_SCOPES=["mcp:read"];
 assert.equal((await call(e,"/api/v1/ops/sync.record.apply",args)).status,403);
 e.SHIO_OAUTH_SCOPES=["mcp:read","mcp:write"];
 assert.equal((await call(e,"/api/v1/ops/sync.record.apply",{
  ...args,expected_record_sha256:"0".repeat(64)
 })).status,409);
 assert.equal((await call(e,"/api/v1/ops/tasks.delete",request("s5-delete",{
  task_id:f.task_id,expected_revision:1
 }))).status,200);
 const deleted=(await call(e,"/api/v1/ops/sync.record.snapshot.read",{
  workspace_id:"personal",task_id:f.task_id,include_content:true
 })).data.data;
 assert.equal(deleted.record.version,2);
 assert(deleted.record.deleted_at);
 assert.equal((await call(e,"/api/v1/ops/sync.record.apply",{
  ...args,expected_revision:2,expected_record_sha256:deleted.record_sha256
 })).status,409);
 assert.equal((await call(e,"/api/v1/ops/sync.record.snapshot.read",{
  workspace_id:"personal",task_id:f.task_id,include_content:true
 })).data.data.record.deleted_at,deleted.record.deleted_at);
});


async function s5RaceFixture(){
 const e=env(),f=importFixture();
 assert.equal((await pairFixture(e,f)).status,200);
 const p=await previewFixture(e,f);
 assert.equal(p.status,200);
 const imported=await call(e,"/api/v1/ops/sync.import.apply",request("race-apply-first",{
  proposal_id:p.data.data.proposal_id,payload_json:f.payload_json,
  owner_approved:true
 }));
 assert.equal(imported.status,200,JSON.stringify(imported.data));
 const snapshot=(await call(e,"/api/v1/ops/sync.record.snapshot.read",{
  workspace_id:"personal",task_id:f.task_id,include_content:true
 })).data.data;
 return {e,f,snapshot};
}
function s5RaceArgs(f,snapshot,key){
 return request(key,{
   device_id:f.device_id,task_id:f.task_id,
   source_event_id:f.event_id,source_payload_sha256:f.payload_sha256,
   expected_revision:snapshot.record.version,
   expected_record_sha256:snapshot.record_sha256,
   patch:{notes:"A private device-side change"},owner_approved:true
 });
}
test("S5 CAS rejects device revocation between preflight and atomic UPDATE",async()=>{
 const {e,f,snapshot}=await s5RaceFixture(),oldBatch=e.DB.batch.bind(e.DB);
 e.DB.batch=async statements=>{
  e.DB.db.prepare("UPDATE sync_devices SET revoked_at=? WHERE workspace_id=? AND device_id=?")
    .run("2026-11-19T17:00:00Z","personal",f.device_id);
  return oldBatch(statements);
 };
 const failed=await call(e,"/api/v1/ops/sync.record.apply",
   s5RaceArgs(f,snapshot,"race-device-revoked"));
 assert.equal(failed.status,409,JSON.stringify(failed.data));
 assert.equal(e.DB.db.prepare("SELECT version FROM remote_tasks WHERE id=?").get(f.task_id).version,1);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM idempotency WHERE operation_id='sync.record.apply'").get().n,0);
});
test("S5 CAS rejects late changes to remote event cutoff even without task version change",async()=>{
 const {e,f,snapshot}=await s5RaceFixture(),oldBatch=e.DB.batch.bind(e.DB);
 e.DB.batch=async statements=>{
  e.DB.db.prepare(
    "INSERT INTO remote_tasks(id,workspace_id,title,created_at,updated_at) VALUES(?,?,?,?,?)"
  ).run("cccccccc-cccc-4ccc-8ccc-cccccccccccc","personal","UNRELATED CHANGE",
    "2026-11-19T17:00:00Z","2026-11-19T17:00:00Z");
  return oldBatch(statements);
 };
 const failed=await call(e,"/api/v1/ops/sync.record.apply",
   s5RaceArgs(f,snapshot,"race-cutoff-changed"));
 assert.equal(failed.status,409,JSON.stringify(failed.data));
 assert.equal(e.DB.db.prepare("SELECT version FROM remote_tasks WHERE id=?").get(f.task_id).version,1);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM idempotency WHERE operation_id='sync.record.apply'").get().n,0);
});
test("S5 CAS rejects import lineage replacement between source read and transaction",async()=>{
 const {e,f,snapshot}=await s5RaceFixture(),oldBatch=e.DB.batch.bind(e.DB);
 e.DB.batch=async statements=>{
  e.DB.db.prepare("UPDATE sync_imports SET payload_sha256=? WHERE workspace_id=? AND task_id=?")
   .run("a".repeat(64),"personal",f.task_id);
  return oldBatch(statements);
 };
 const failed=await call(e,"/api/v1/ops/sync.record.apply",
   s5RaceArgs(f,snapshot,"race-lineage-updated"));
 assert.equal(failed.status,409,JSON.stringify(failed.data));
 assert.equal(e.DB.db.prepare("SELECT version FROM remote_tasks WHERE id=?").get(f.task_id).version,1);
 assert.equal(e.DB.db.prepare("SELECT COUNT(*) AS n FROM idempotency WHERE operation_id='sync.record.apply'").get().n,0);
});
