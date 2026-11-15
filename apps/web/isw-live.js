/* SHIORI ISW development integration: real Rust/SQLite tasks and spatial view.
 * No model credentials or executable scripts. The local bridge is loopback-only.
 * This module never modifies canonical task dependencies.
 */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const debug=window.__iswDebug;
const revisions=new Map();
const saved=new Map();
const pending=new Map();
let sourceReady=false;
const liveButton=$("liveBtn");
const notice=msg=>{const el=$("notice");if(el){el.textContent=msg;el.classList.add("active");setTimeout(()=>el.classList.remove("active"),3800);}};
const json=async(url,init)=>{
  const result=await fetch(url,{cache:"no-store",credentials:"same-origin",...init});
  const data=await result.json();
  if(!result.ok)throw new Error(data.error||"Rust local service unavailable");
  return data;
};
function projectLayout(tasks,edges,positions){
  const byId=new Map(tasks.map(t=>[t.id,t]));
  const incoming=new Map(tasks.map(t=>[t.id,[]]));
  for(const e of edges)if(incoming.has(e.to)&&byId.has(e.from))incoming.get(e.to).push(e.from);
  const depths=new Map();
  function depth(id,visiting=new Set()){
    if(depths.has(id))return depths.get(id);
    if(visiting.has(id))return 0;
    visiting.add(id);
    const d=Math.min(16,Math.max(0,...(incoming.get(id)||[]).map(x=>depth(x,visiting)+1)));
    visiting.delete(id);depths.set(id,d);return d;
  }
  tasks.forEach(t=>depth(t.id));
  const cols=new Map();
  tasks.forEach(t=>{const d=depths.get(t.id)||0;const seq=cols.get(d)||[];seq.push(t);cols.set(d,seq);});
  const coordinate=new Map();
  for(const [d,col] of cols){
    col.sort((a,b)=>(a.project||"").localeCompare(b.project||"")||(a.created_at||"").localeCompare(b.created_at||""));
    col.forEach((t,i)=>coordinate.set(t.id,{x:110+d*315,y:160+i*166}));
  }
  positions.forEach(p=>{if(coordinate.has(p.task_id)){coordinate.set(p.task_id,{x:p.x,y:p.y});revisions.set(p.task_id,p.revision);saved.set(p.task_id,{x:p.x,y:p.y});}});
  return coordinate;
}
function adaptScene(data){
  revisions.clear();saved.clear();
  const tasks=data.tasks.filter(t=>t&&typeof t.id==="string");
  const edges=data.edges.filter(e=>e&&typeof e.from==="string"&&typeof e.to==="string").map(e=>({from:e.from,to:e.to,kind:"dependency"}));
  const positions=Array.isArray(data.positions)?data.positions:[];
  const place=projectLayout(tasks,edges,positions);
  const taskMap=new Map(tasks.map(t=>[t.id,t]));
  const blockers=new Set();
  for(const e of edges){if(taskMap.get(e.from)?.status!=="done")blockers.add(e.to);}
  const nodes=tasks.map(t=>{
    const pos=place.get(t.id)||{x:0,y:0};
    if(!saved.has(t.id))saved.set(t.id,pos);
    return {
      id:t.id,title:t.title,kind:"task",glyph:"▤",
      status:t.status==="done"?"ready":blockers.has(t.id)?"blocked":"active",
      role:(t.project||"General")+" · "+(t.assignee_id||"Unassigned")+" · "+(t.priority||"medium"),
      due:t.due_on||"",x:pos.x,y:pos.y,notes:t.notes||"",version:t.version
    };
  });
  return {nodes,edges};
}
async function refresh(selectId){
  const data=await json("/api/isw/scene");
  const scene=adaptScene(data);
  debug.loadLive(scene);
  sourceReady=true;liveButton?.setAttribute("aria-pressed","true");
  if(scene.nodes.length===0)notice("SQLite workspace is empty. Long-press the canvas to create your first task.");
  else notice("Live Rust/SQLite · "+scene.nodes.length+" tasks · "+scene.edges.length+" prerequisites");
  if(selectId){const n=debug.getNodes().find(n=>n.id===selectId);if(n)document.title="SHIORI · "+n.title;}
}
async function post(path,body){
  return json(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
}
async function commitPosition(id,x,y){
  const previous=saved.get(id);
  if(previous&&previous.x===x&&previous.y===y)return;
  const revision=revisions.get(id)||0;
  try{
    const data=await post("/api/isw/position",{task_id:id,x,y,expected_revision:revision});
    revisions.set(id,data.position.revision);
    saved.set(id,{x:data.position.x,y:data.position.y});
  }catch(error){
    notice("Position not saved: "+error.message+" · reload Live Rust before editing again");
    await refresh().catch(()=>{});
  }
}
function savePosition(id,x,y){
  if(!sourceReady||!debug.getNodes().some(n=>n.id===id))return;
  if(pending.has(id))clearTimeout(pending.get(id));
  pending.set(id,setTimeout(async()=>{
    pending.delete(id);
    await commitPosition(id,x,y);
  },350));
}
async function createTask(item){
  if(!sourceReady)return;
  try{
    const created=await post("/api/tasks",{title:item.title,project:"Spatial Workspace",priority:"medium",notes:""});
    const id=created.task_id;
    if(!id)throw Error("Task created, but no task identifier returned; refresh Live Rust");
    const placed=await post("/api/isw/position",{task_id:id,x:item.x,y:item.y,expected_revision:0});
    if(!placed.position)throw Error("Task added, but position save failed");
    $("createArtifact")?.close();$("createForm")?.reset();
    await refresh(id);
  }catch(error){notice("Creation failed or needs reload: "+error.message);}
}
window.__iswLive={savePosition,createTask,refresh};
if(liveButton)liveButton.addEventListener("click",()=>refresh().catch(e=>notice("Rust workspace unavailable: "+e.message)));
json("/api/health").then(data=>{
  if(data.mode!=="rust-sqlite")return;
  return refresh();
}).catch(()=>{ // Standalone browser remains an explicitly labelled demo.
  if(liveButton){liveButton.disabled=true;liveButton.title="Start the Rust local bridge to use live tasks";}
  const footer=document.querySelector(".inspector footer");
  if(footer)footer.textContent="OFFLINE DEMO · NO RUST CONNECTION";
});
})();
