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
  assert.equal(list.data.result.tools.length,9);
  assert(list.data.result.tools.some(t=>t.name==="shiori_spatial_node_position_set"));
  assert(!list.data.result.tools.some(t=>t.name==="shiori_graph_restructure_apply"));
  const caps=await call(e,"/mcp",rpc("tools/call",{name:"shiori_system_capabilities_read",arguments:{workspace_id:"personal"}}));
  assert.equal(caps.data.result.structuredContent.local_rust_sync,false);
});

test("task create, list, get, retry and status mutations",async()=>{
  const e=env();
  const newTask=await call(e,"/api/v1/ops/tasks.create",request("create-0001",{title:"Prepare derrick inspection",body:"Sample"}));
  assert.equal(newTask.status,200,JSON.stringify(newTask.data));
  assert.equal(newTask.data.data.revision,1);
  const id=newTask.data.data.resource_id;
  const replay=await call(e,"/api/v1/ops/tasks.create",request("create-0001",{title:"Prepare derrick inspection",body:"Sample"}));
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