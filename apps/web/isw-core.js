
(()=>{'use strict';
const $=x=>document.getElementById(x);const svgNS='http://www.w3.org/2000/svg';const COLORS={active:'#54b9ef',ready:'#40d1a1',review:'#e7ae5b',blocked:'#e56a7e',reference:'#bc90ee'};
const task=(id,title,x,y,status,role,due)=>({id,title,x,y,status,kind:'task',glyph:'▤',role,due});
const offshore=[
 task('T-001','Daily Production Output Reconciliation',105,165,'active','Production Manager','Day 8'),
 task('T-002','Derrick Mechanical Integrity Check',105,495,'active','Jonas Forbe · Foreman','Day 10'),
 task('T-003','Shale Storage Tank Volume Verification',105,310,'ready','Production Manager','Day 12'),
 task('T-004','Export Consignment Preparation — 10,000 Barrels',510,220,'active','Production Manager','Day 60'),
 task('T-005','Loading Window Coordination — Taiwan',1380,645,'ready','Logistics','After approval'),
 task('T-006','Environmental Compliance Review',950,490,'review','Compliance Team','Day 18'),
 task('T-007','Dept. of Energy Inspection Readiness',520,570,'ready','Elias · Official Dept. of Energy Inspector','Day 20'),
 task('T-008','Safety Drill and Crew Certification Audit',105,655,'active','Jonas Forbe · Foreman','Day 14'),
 task('T-009','Shareholder Export Approval Packet',940,160,'review','Mr. Mark · Shareholder / CEO','Day 28'),
 task('T-010','Final Loading Authorization',1370,360,'blocked','Elias + Mr. Mark · pending sign-offs','Before loading'),
 {id:'D-1',title:'Tank Telemetry Report',x:510,y:60,status:'reference',kind:'document',glyph:'▤',role:'Linked evidence'},
 {id:'D-2',title:'Inspection Checklist PDF',x:500,y:760,status:'reference',kind:'document',glyph:'▣',role:'Attachment'},
 {id:'D-3',title:'Crew Roster',x:735,y:795,status:'reference',kind:'document',glyph:'◫',role:'Reference'},
 {id:'D-4',title:'Export Compliance Memo',x:770,y:30,status:'reference',kind:'document',glyph:'▤',role:'Attachment'},
 {id:'D-5',title:'Shipping Brief',x:1380,y:825,status:'reference',kind:'document',glyph:'▤',role:'Reference'}
];
const deps=[['T-001','T-004'],['T-003','T-004'],['T-002','T-007'],['T-008','T-007'],['T-004','T-009'],['T-007','T-009'],['T-007','T-010'],['T-006','T-010'],['T-009','T-010'],['T-010','T-005']];
const refs=[['D-1','T-004'],['D-4','T-004'],['D-2','T-007'],['D-3','T-007'],['T-005','D-5']];
const state={mode:'derrick',nodes:offshore.map(n=>({...n})),edges:deps.map(([from,to])=>({from,to,kind:'dependency'})).concat(refs.map(([from,to])=>({from,to,kind:'reference'}))),selected:'T-004',x:40,y:40,z:.7,dragging:null,tool:'select',route:'circuit',focusTab:'overview',longPress:null,canvasPress:null,gesture:null,gestureBlocked:false,zoomMemory:null,menuPoint:null,localNext:1,locked:true,sceneRevision:0};
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const nwidth=n=>(state.z<.48?86:(n.kind==='document'?192:((n.kind==='folder'||n.kind==='file')?205:247)));
const nheight=n=>(state.z<.48?76:(n.kind==='document'?65:(n.kind==='folder'?80:(n.kind==='file'?69:119))));
let nodeIndex=new Map(state.nodes.map(n=>[n.id,n]));
const byId=id=>nodeIndex.get(id)||state.nodes.find(x=>x.id===id);
let visibleElements=new Map(),paintRAF=0,renderRevision=-1,minimapRevision=-1,edgeStamp=null,lodCompact=null;
const edgePathCache=new Map();
let smoothMode=true;
const PERF={visibleNodes:0,visibleEdges:0,edgeDraws:0,cameraUpdates:0,edgeCacheHits:0,edgeCacheMisses:0};
function invalidateLayout(){state.sceneRevision++;edgeStamp=null;minimapRevision=-1;edgePathCache.clear()}
function worldBounds(padding=240){const st=$('stage'),left=(-state.x)/state.z,top=(-state.y)/state.z;return {l:left-padding/state.z,r:left+(st.clientWidth/state.z)+padding/state.z,t:top-padding/state.z,b:top+(st.clientHeight/state.z)+padding/state.z};}
function syncVisibleNodes(reset=false){const host=$('nodes'),bounds=worldBounds(),keep=new Set();if(reset){host.replaceChildren();visibleElements.clear();}for(const n of state.nodes){if(n.x>bounds.r||n.y>bounds.b||n.x+nwidth(n)<bounds.l||n.y+nheight(n)<bounds.t)continue;keep.add(n.id);let el=visibleElements.get(n.id);if(!el){el=makeNode(n);visibleElements.set(n.id,el);host.append(el);}else{el.classList.toggle('selected',n.id===state.selected);el.classList.toggle('locked',state.locked);}}for(const [id,el] of visibleElements){if(keep.has(id)||(state.dragging?.type==='node'&&state.dragging.id===id))continue;el.remove();visibleElements.delete(id)}PERF.visibleNodes=visibleElements.size;}
function schedulePaint(){if(paintRAF)return;paintRAF=requestAnimationFrame(()=>{paintRAF=0;syncVisibleNodes();const b=worldBounds(140);const sig=state.sceneRevision+'|'+state.route+'|'+(state.z<.48);if(!edgeStamp||edgeStamp.sig!==sig||b.l<edgeStamp.b.l||b.r>edgeStamp.b.r||b.t<edgeStamp.b.t||b.b>edgeStamp.b.b){drawEdges();}if(minimapRevision!==state.sceneRevision){drawMinimap();minimapRevision=state.sceneRevision;}})}

const cam=()=>{PERF.cameraUpdates++;$('camera').style.transform=`translate(${state.x}px,${state.y}px) scale(${state.z})`;const newLOD=state.z<.48;$('camera').classList.toggle('compact',newLOD);if(lodCompact!==newLOD){lodCompact=newLOD;invalidateLayout();} $('zoomLabel').textContent=`${Math.round(state.z*100)}%`;const gr=22*state.z;$('grid').style.backgroundSize=`${gr}px ${gr}px`;$('grid').style.backgroundPosition=`${state.x}px ${state.y}px`;schedulePaint();};
function edgeEl(t,props){const el=document.createElementNS(svgNS,t);for(const [k,v] of Object.entries(props))el.setAttribute(k,String(v));return el;}
function connectorPath(sx,sy,tx,ty,horizontal,dx,dy){
 if(state.route==='direct')return `M${sx} ${sy} L${tx} ${ty}`;
 if(state.route==='flow')return horizontal?`M${sx} ${sy} C${sx+dx*.42} ${sy} ${tx-dx*.42} ${ty} ${tx} ${ty}`:`M${sx} ${sy} C${sx} ${sy+dy*.40} ${tx} ${ty-dy*.40} ${tx} ${ty}`;
  // Manhattan routing with candidate channels, obstacle collision penalties.
  // Layout-only: no change to dependency or relation data.
  return orthogonalPath(sx,sy,tx,ty,horizontal);
}

function orthogonalPath(sx,sy,tx,ty,horizontal){
 const p=(x,y)=>({x,y});const s=p(sx,sy),t=p(tx,ty),margin=19;
 // Only consider obstacles near the segment, bounded to avoid quadratic routing on large scenes.
  const l=Math.min(sx,tx)-180,r=Math.max(sx,tx)+180,t0=Math.min(sy,ty)-180,b=Math.max(sy,ty)+180;
  const bounds=state.nodes.filter(n=>n.x<r&&n.x+nwidth(n)>l&&n.y<b&&n.y+nheight(n)>t0).slice(0,34).map(n=>({left:n.x-margin,right:n.x+nwidth(n)+margin,top:n.y-margin,bottom:n.y+nheight(n)+margin}));
 const nearly=(a,b)=>Math.abs(a-b)<.01;
 const compact=points=>points.filter((q,i)=>!i||!nearly(q.x,points[i-1].x)||!nearly(q.y,points[i-1].y));
 // Do not penalise the source or destination bbox; endpoints touch their borders.
 const touching=rect=>((s.x>=rect.left&&s.x<=rect.right&&s.y>=rect.top&&s.y<=rect.bottom)||(t.x>=rect.left&&t.x<=rect.right&&t.y>=rect.top&&t.y<=rect.bottom));
 const blockers=bounds.filter(r=>!touching(r));
 const intersects=(a,b,r)=>{if(nearly(a.x,b.x))return a.x>r.left&&a.x<r.right&&Math.max(a.y,b.y)>r.top&&Math.min(a.y,b.y)<r.bottom;
 if(nearly(a.y,b.y))return a.y>r.top&&a.y<r.bottom&&Math.max(a.x,b.x)>r.left&&Math.min(a.x,b.x)<r.right;return true;};
 const xs=new Set([(sx+tx)/2,sx+28,sx-28,tx+28,tx-28]);
 const ys=new Set([(sy+ty)/2,sy+28,sy-28,ty+28,ty-28]);
 // Generate lanes near obstacle edges; useful when a midpoint clips a card.
 for(const r of bounds){xs.add(r.left-17);xs.add(r.right+17);ys.add(r.top-17);ys.add(r.bottom+17);}
 const candidates=[[s,p(tx,sy),t],[s,p(sx,ty),t]];
 for(const x of xs)candidates.push([s,p(x,sy),p(x,ty),t]);
 for(const y of ys)candidates.push([s,p(sx,y),p(tx,y),t]);
 // 5-segment doglegs go around crowded vertical bands.
 const left=sx+(tx>=sx?28:-28),right=tx-(tx>=sx?28:-28);
 for(const y of ys)candidates.push([s,p(left,sy),p(left,y),p(right,y),p(right,ty),t]);
 const scores=candidates.map(raw=>{const q=compact(raw);let collisions=0,len=0,turns=0;
 for(let i=1;i<q.length;i++){const a=q[i-1],b=q[i];len+=Math.abs(b.x-a.x)+Math.abs(b.y-a.y);for(const r of blockers)if(intersects(a,b,r))collisions++;
 if(i>1){const prev=q[i-2];if((nearly(prev.x,a.x))!==(nearly(a.x,b.x)))turns++;}}
 // Prefer an initial horizontal lane for horizontally oriented links, otherwise vertical.
 const initialHorizontal=q.length>1&&nearly(q[0].y,q[1].y);
 return {q,score:collisions*100000+len+turns*23+((initialHorizontal!==horizontal)?22:0)};});
 scores.sort((a,b)=>a.score-b.score);return scores[0].q.map((point,i)=>`${i?'L':'M'}${Math.round(point.x*100)/100} ${Math.round(point.y*100)/100}`).join(' ');
}
function drawEdges(){
 const root=$('edges');const bounds=worldBounds(500);const wanted=new Set();const visible=[];
 for(const n of state.nodes){if(n.x<bounds.r&&n.x+nwidth(n)>bounds.l&&n.y<bounds.b&&n.y+nheight(n)>bounds.t)wanted.add(n.id);}
 for(const edge of state.edges){if(visible.length>=240)break;const a=byId(edge.from),b=byId(edge.to);if(!a||!b)continue;
  if(!wanted.has(a.id)&&!wanted.has(b.id)){if(Math.max(a.x,b.x)<bounds.l||Math.min(a.x,b.x)>bounds.r||Math.max(a.y,b.y)<bounds.t||Math.min(a.y,b.y)>bounds.b)continue;}
  visible.push([edge,a,b]);
 }
 root.replaceChildren();root.setAttribute('width',4000);root.setAttribute('height',2600);const defs=edgeEl('defs',{});const marker=edgeEl('marker',{id:'arrow',viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:5,markerHeight:5,orient:'auto-start-reverse'});marker.append(edgeEl('path',{d:'M0 0 L10 5 L0 10 z',fill:'#9ebcda'}));defs.append(marker);root.append(defs);
 const dense=state.nodes.length>250;
 for(const [edge,a,b] of visible){const ax=a.x+nwidth(a)/2,ay=a.y+nheight(a)/2,bx=b.x+nwidth(b)/2,by=b.y+nheight(b)/2;const dx=bx-ax,dy=by-ay;const horizontal=Math.abs(dx)>Math.abs(dy);const sx=horizontal?ax+Math.sign(dx)*nwidth(a)/2:ax;const sy=horizontal?ay:ay+Math.sign(dy)*nheight(a)/2;const tx=horizontal?bx-Math.sign(dx)*nwidth(b)/2:bx;const ty=horizontal?by:by-Math.sign(dy)*nheight(b)/2;
 const key=`${edge.from}\u0000${edge.to}\u0000${edge.kind}\u0000${state.route}\u0000${state.z<.48}`;
  let d=smoothMode?edgePathCache.get(key):undefined;
  if(d!==undefined)PERF.edgeCacheHits++;
  else{
   PERF.edgeCacheMisses++;
   d=dense&&state.route==='circuit'? `M${sx} ${sy} L${(sx+tx)/2} ${sy} L${(sx+tx)/2} ${ty} L${tx} ${ty}` :connectorPath(sx,sy,tx,ty,horizontal,dx,dy);
   if(smoothMode){if(edgePathCache.size>=1200)edgePathCache.clear();edgePathCache.set(key,d);}
  }
  const path=edgeEl('path',{d,class:`edge ${edge.kind==='reference'?'ref':''}`});if(edge.kind==='dependency')path.setAttribute('marker-end','url(#arrow)');root.append(path);}
 PERF.edgeDraws++;PERF.visibleEdges=visible.length;const b=worldBounds(750);edgeStamp={sig:state.sceneRevision+'|'+state.route+'|'+(state.z<.48),b};
}
function cancelLongPress(){if(state.longPress){clearTimeout(state.longPress);state.longPress=null;}}
function openFocus(id,tab='overview'){if(!byId(id))return;cancelLongPress();state.selected=id;state.focusTab=tab;render();renderFocus();if(!$('focusPanel').open)$('focusPanel').showModal();}
function makeNode(n){const el=document.createElement('div');el.className=`node ${n.kind||'task'}${n.id===state.selected?' selected':''}`;el.style.left=n.x+'px';el.style.top=n.y+'px';el.style.setProperty('--accent',COLORS[n.status]||COLORS.reference);el.dataset.id=n.id;el.classList.toggle('locked',state.locked);const head=document.createElement('div');head.className='nodehead';const glyph=document.createElement('span');glyph.className='glyph';glyph.textContent=n.glyph||'◫';const title=document.createElement('div');title.className='n-title';title.textContent=n.title;const id=document.createElement('span');id.className='n-id';id.textContent=n.kind==='task'?`#${n.id.length>12?n.id.slice(-8):n.id}`:'';head.append(glyph,title,id);const meta=document.createElement('div');meta.className='meta';const status=document.createElement('span');status.className='status';status.textContent=n.status==='ready'?'On track':n.status==='review'?'In review':n.status==='blocked'?'Blocked':n.status==='active'?'In progress':n.kind;meta.append(status);if(n.due){const due=document.createElement('span');due.textContent='◷ '+n.due;meta.append(due)}const small=document.createElement('div');small.className='smallline';small.textContent=n.role||'';const mk=document.createElement('div');mk.className='marker';const sym=document.createElement('strong');sym.textContent=n.status==='blocked'?'!':n.kind==='folder'?'▦':n.kind==='file'?'≡':n.kind==='document'?'◇':n.status==='ready'?'✓':'▤';const code=document.createElement('small');code.textContent=n.id.length>9?'◫':n.id;mk.append(sym,code);el.append(head,meta,small,mk);
 el.addEventListener('pointerdown',e=>{if(e.button!==0||state.tool==='pan'||state.gesture||state.gestureBlocked)return; e.stopPropagation();cancelLongPress();el.setPointerCapture(e.pointerId);state.dragging={type:'node',id:n.id,sx:e.clientX,sy:e.clientY,x:n.x,y:n.y,moved:false,canMove:!state.locked&&state.tool==='move',pointerType:e.pointerType};state.longPress=setTimeout(()=>{if(state.dragging?.id===n.id&&!state.dragging.moved){state.dragging=null;el.classList.remove('dragging');openFocus(n.id);}},550);el.classList.add('dragging');});
 el.addEventListener('pointermove',e=>{if(state.gesture||state.gestureBlocked||state.dragging?.type!=='node'||state.dragging.id!==n.id)return;const d=state.dragging;const delta=Math.hypot(e.clientX-d.sx,e.clientY-d.sy);if(delta>8&&d.canMove){d.moved=true;cancelLongPress()}if(!d.moved||!d.canMove)return;n.x=d.x+(e.clientX-d.sx)/state.z;n.y=d.y+(e.clientY-d.sy)/state.z;el.style.left=n.x+'px';el.style.top=n.y+'px';invalidateLayout();schedulePaint();});
 el.addEventListener('pointerup',e=>{cancelLongPress();if(state.gesture||state.gestureBlocked||state.dragging?.id!==n.id)return;const released=state.dragging;state.selected=n.id;state.dragging=null;el.classList.remove('dragging');if(released?.moved&&released.canMove&&state.mode==='live')window.__iswLive?.savePosition(n.id,n.x,n.y,released.x,released.y);document.querySelectorAll('.node.selected').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');detail();});el.addEventListener('pointercancel',()=>{cancelLongPress();if(state.dragging?.id===n.id)state.dragging=null;});el.addEventListener('dblclick',e=>{e.preventDefault();e.stopPropagation();openFocus(n.id)});
 el.addEventListener('keydown',e=>{if((e.key==='Enter'&&e.shiftKey)||e.key==='i'){e.preventDefault();openFocus(n.id)}else if(e.key==='Enter'||e.key===' '){e.preventDefault();state.selected=n.id;render()}else if(!state.locked&&state.tool==='move'&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const d=e.shiftKey?5:20;n.x+=e.key==='ArrowLeft'?-d:e.key==='ArrowRight'?d:0;n.y+=e.key==='ArrowUp'?-d:e.key==='ArrowDown'?d:0;el.style.left=n.x+'px';el.style.top=n.y+'px';invalidateLayout();schedulePaint();if(state.mode==='live')window.__iswLive?.savePosition(n.id,n.x,n.y);}});
 el.tabIndex=0;el.setAttribute('role','button');el.setAttribute('aria-label',`Inspect ${n.title}`);return el;}
function render(){nodeIndex=new Map(state.nodes.map(n=>[n.id,n]));invalidateLayout();syncVisibleNodes(true);cam();detail();}
function addTextRow(parent,label,value){const el=document.createElement('div');el.className='detailrow';const l=document.createElement('span');l.textContent=label;const v=document.createElement('strong');v.textContent=value;el.append(l,v);parent.append(el);}
function detail(){const n=byId(state.selected)||state.nodes[0];const root=$('detail');root.replaceChildren();if(!n)return;const h=document.createElement('h2');h.textContent=n.title;root.append(h);addTextRow(root,'Type',n.kind||'task');addTextRow(root,'State',n.status);if(n.due)addTextRow(root,'Due / target',n.due);if(n.role)addTextRow(root,'Responsible / source',n.role);const ing=state.edges.filter(e=>e.to===n.id&&e.kind==='dependency'),out=state.edges.filter(e=>e.from===n.id&&e.kind==='dependency'),other=state.edges.filter(e=>(e.from===n.id||e.to===n.id)&&e.kind!=='dependency');for(const [label,arr,which] of [['Prerequisites',ing,'from'],['Downstream',out,'to'],['Related / contained artefacts',other,'other']]){if(!arr.length)continue;const h=document.createElement('h3');h.textContent=`${label} (${arr.length})`;root.append(h);for(const edge of arr){const item=document.createElement('div');item.className='related';const target=which==='other'?byId(edge.from===n.id?edge.to:edge.from):byId(edge[which]);item.textContent=target?.title||'Unavailable';if(target?.role){const s=document.createElement('b');s.textContent=target.role;item.append(s)}root.append(item)}}const note=document.createElement('p');note.textContent=state.mode==='derrick'?'Hypothetical offshore project: target 10,000 barrels ready for export to Taiwan in 60 days. This view contains example tasks; it is not an operational safety or regulatory checklist.':state.mode==='custom'?'Local scene only: any changes to this diagram do not modify real Shiori tasks, dependencies or GitHub records.':state.mode==='live'?'Live local Rust task record. Dependency lines come from the canonical prerequisite table; moving cards changes visual placement only. Comments, automations and EAI are still previews.':'Read-only source tree preview. Directory hierarchy is not the same as code imports or runtime dependencies; those need separately verified analysis.';root.append(note);const focus=document.createElement('button');focus.className='focus-btn';focus.textContent='↗ Open full artefact sheet';focus.addEventListener('click',()=>openFocus(n.id));root.append(focus);}
const DEMO={
 'T-004':{description:'Hypothetical workstream for reconciling production and preparing the Taiwan-bound consignment. This is a UI demonstration, not a regulatory procedure.',progress:'Planning / reconciliation in progress',comments:['Example: reconcile the latest production volume with the storage report.','Example: attach approved export documentation before handing off.'],automations:[{name:'Watch logistics correspondence',trigger:'New email from a configured logistics contact',action:'Suggest an inbox artefact for review',status:'Not connected / proposed'}]},
 'T-010':{description:'This illustrative task is blocked on both the inspector and shareholder approvals.',progress:'Waiting for prerequisite sign-offs',comments:['Example: inspection status and shareholder approval must be reviewed separately.'],automations:[{name:'Approval reminder',trigger:'Prerequisites are completed',action:'Propose a notification to the production manager',status:'Not active / proposed'}]}
};
function section(parent,label,description){const h=document.createElement('h3');h.textContent=label;parent.append(h);if(description){const p=document.createElement('p');p.textContent=description;parent.append(p)}}
function entry(parent,title,meta){const box=document.createElement('div');box.className='focus-entry';const name=document.createElement('strong');name.textContent=title;const sub=document.createElement('small');sub.textContent=meta;box.append(name,sub);parent.append(box);}
function renderFocus(){const n=byId(state.selected);if(!n)return;$('focusTitle').textContent=n.title;for(const el of document.querySelectorAll('.focus-tabs button'))el.setAttribute('aria-selected',String(el.dataset.tab===state.focusTab));const root=$('focusContent');root.replaceChildren();const data=DEMO[n.id];
 if(state.focusTab==='overview'){
  const flag=document.createElement('span');flag.className='focus-flag';flag.textContent=state.mode==='live'?'LIVE RUST / SQLITE · activity and automations not connected':'Local prototype · read-only demo';root.append(flag);addTextRow(root,'Artefact ID',n.id);addTextRow(root,'Type',n.kind||'task');addTextRow(root,'Status',n.status);if(n.due)addTextRow(root,'Deadline / milestone',n.due);if(n.role)addTextRow(root,'Responsible / source',n.role);addTextRow(root,'Position',`${Math.round(n.x)}, ${Math.round(n.y)}`);section(root,'Notes',state.mode==='live'?(n.notes||'No task notes recorded.'):(data?.description||'This artefact is a visual demonstration. Real notes and comments require Shiori application-service integration.'));if(data?.progress)section(root,'Progress',data.progress);
 } else if(state.focusTab==='relations'){
  const related=state.edges.filter(e=>e.from===n.id||e.to===n.id);section(root,'Connected objects',`${related.length} relationship(s) in this scene. Layout changes do not change these links.`);if(!related.length)entry(root,'No graph links','No references or dependencies in this fixture.');for(const e of related){const dest=byId(e.from===n.id?e.to:e.from);entry(root,dest?.title||'Missing target',`${e.kind} · ${e.from===n.id?'outgoing':'incoming'} · ${e.from} → ${e.to}`);}
 } else if(state.focusTab==='activity'){
  section(root,'Comments and progress','Illustrative entries only. A live integration would show dated comments, audit revisions, attachments and progress with original source links.');if(data?.comments)for(const c of data.comments)entry(root,c,'Example comment · not fetched from ClickUp');else entry(root,'No example comments','No live activity feed is connected.');
 } else if(state.focusTab==='automations'){
  section(root,'Associated automations','The app does not currently monitor Gmail, trigger external actions or send replies. Future automations require separately scoped account connections, clear triggers and write approval.');if(data?.automations)for(const a of data.automations)entry(root,a.name,`${a.status} · When: ${a.trigger} · Action: ${a.action}`);else entry(root,'No active automations','Example triggers can be attached after the automation service is implemented.');
 } else if(state.focusTab==='scene'){
  section(root,'Scene object definition','View-state fields and semantic relationships are represented separately. The AI would propose validated scene operations; this panel does not grant execution rights.');const pre=document.createElement('pre');pre.textContent=JSON.stringify({id:n.id,kind:n.kind,title:n.title,x:n.x,y:n.y,status:n.status,relations:state.edges.filter(e=>e.from===n.id||e.to===n.id)},null,2);root.append(pre);
 }
}
$('focusClose').addEventListener('click',()=>$('focusPanel').close());for(const tab of document.querySelectorAll('.focus-tabs button'))tab.addEventListener('click',()=>{state.focusTab=tab.dataset.tab;renderFocus()});
function drawMinimap(){const svg=$('minisvg');svg.replaceChildren();if(!state.nodes.length)return;
 let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
 for(const n of state.nodes){minX=Math.min(minX,n.x);maxX=Math.max(maxX,n.x+nwidth(n));minY=Math.min(minY,n.y);maxY=Math.max(maxY,n.y+nheight(n));}
 const scale=Math.min(150/Math.max(1,maxX-minX),68/Math.max(1,maxY-minY));const occupied=new Set();
 for(const n of state.nodes){const x=5+(n.x-minX)*scale,y=3+(n.y-minY)*scale;const cell=Math.floor(x/4)+'/'+Math.floor(y/4);if(occupied.has(cell)&&n.id!==state.selected)continue;occupied.add(cell);if(occupied.size>420)break;svg.append(edgeEl('rect',{x,y,width:Math.max(3,nwidth(n)*scale),height:Math.max(3,nheight(n)*scale),rx:1.3,fill:COLORS[n.status]||COLORS.reference,opacity:n.id===state.selected?1:.7}));}
}
function fit(){state.zoomMemory=null;closeMenu();const width=$('stage').clientWidth-(window.innerWidth>750?345:40),height=$('stage').clientHeight-(window.innerWidth>750?150:270);if(!state.nodes.length)return;const minX=Math.min(...state.nodes.map(n=>n.x)),maxX=Math.max(...state.nodes.map(n=>n.x+247)),minY=Math.min(...state.nodes.map(n=>n.y)),maxY=Math.max(...state.nodes.map(n=>n.y+140));state.z=clamp(Math.min((width-70)/(maxX-minX),(height-120)/(maxY-minY)),.18,1.25);state.x=70-minX*state.z;state.y=135-minY*state.z;render()}
function zoom(value,px=$('stage').clientWidth/2,py=$('stage').clientHeight/2){const beforeX=(px-state.x)/state.z,beforeY=(py-state.y)/state.z;state.z=clamp(value,.16,2.2);state.x=px-beforeX*state.z;state.y=py-beforeY*state.z;cam()}

const stage=$('stage');
const stageRect=()=>stage.getBoundingClientRect();
const fromClient=(cx,cy)=>{const b=stageRect();return {x:cx-b.left,y:cy-b.top}};
const toWorld=(cx,cy)=>{const p=fromClient(cx,cy);return {x:(p.x-state.x)/state.z,y:(p.y-state.y)/state.z}};
const emptyAt=e=>!e.target.closest('button,.inspector,.minimap,.topinfo,.legend,.controls,.importbox,.node,.canvas-menu');
const touches=new Map();let prevTap=null,lastTouchDouble=0,lastTouchTime=0,preventNextTap=false;
function cancelCanvasPress(){if(state.canvasPress?.timer)clearTimeout(state.canvasPress.timer);state.canvasPress=null;}
function closeMenu(){const menu=$('canvasMenu');menu.hidden=true;state.menuPoint=null;}
function openMenu(cx,cy){cancelCanvasPress();closeMenu();const rect=stageRect();const local=fromClient(cx,cy);state.menuPoint=toWorld(cx,cy);state.lastPoint=state.menuPoint;const menu=$('canvasMenu');menu.hidden=false;const w=230,h=220;menu.style.left=Math.round(clamp(local.x,8,rect.width-w-10))+'px';menu.style.top=Math.round(clamp(local.y,8,rect.height-h-10))+'px';menu.querySelector('button')?.focus({preventScroll:true});}
function toggleTapZoom(cx,cy){closeMenu();const p=fromClient(cx,cy);if(!state.zoomMemory){state.zoomMemory={x:state.x,y:state.y,z:state.z};zoom(Math.max(1.15,state.z*1.8),p.x,p.y);statusNote('Double-tap zoom: tap twice again to restore your previous view.');}else{state.x=state.zoomMemory.x;state.y=state.zoomMemory.y;state.z=state.zoomMemory.z;state.zoomMemory=null;cam();statusNote('Returned to the previous canvas view.');}}
function beginGesture(){if(touches.size<2)return;cancelLongPress();cancelCanvasPress();if(state.dragging?.type==='node'){const n=byId(state.dragging.id);if(n){n.x=state.dragging.x;n.y=state.dragging.y;invalidateLayout();const el=visibleElements.get(n.id);if(el){el.style.left=n.x+'px';el.style.top=n.y+'px';}}}state.dragging=null;document.querySelectorAll('.node.dragging').forEach(el=>el.classList.remove('dragging'));stage.classList.remove('dragging');closeMenu();
 const [a,b]=[...touches.values()];const mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2};const pos=fromClient(mid.x,mid.y);state.gesture={distance:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),zoom:state.z,world:{x:(pos.x-state.x)/state.z,y:(pos.y-state.y)/state.z}};state.gestureBlocked=true;prevTap=null;}
// Capture phase ensures a second finger on a draggable card still reaches pinch logic.
stage.addEventListener('pointerdown',e=>{if(e.pointerType!=='touch'||!emptyAt(e)&&!e.target.closest('.node'))return;lastTouchTime=Date.now();touches.set(e.pointerId,{x:e.clientX,y:e.clientY});if(touches.size===2)beginGesture();},{capture:true});
stage.addEventListener('pointermove',e=>{if(e.pointerType!=='touch'||!touches.has(e.pointerId))return;touches.set(e.pointerId,{x:e.clientX,y:e.clientY});if(!state.gesture||touches.size<2)return;const [a,b]=[...touches.values()];const mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2};const pos=fromClient(mid.x,mid.y);const dist=Math.max(1,Math.hypot(a.x-b.x,a.y-b.y));state.z=clamp(state.gesture.zoom*(dist/state.gesture.distance),.16,2.2);state.x=pos.x-state.gesture.world.x*state.z;state.y=pos.y-state.gesture.world.y*state.z;cam();e.preventDefault();},{capture:true,passive:false});
stage.addEventListener('pointerup',e=>{if(e.pointerType!=='touch'||!touches.has(e.pointerId))return;lastTouchTime=Date.now();touches.delete(e.pointerId);if(state.gesture||state.gestureBlocked){cancelLongPress();cancelCanvasPress();state.dragging=null;stage.classList.remove('dragging');if(touches.size<2)state.gesture=null;if(touches.size===0){state.gestureBlocked=false;}return;}
 if(!emptyAt(e))return;const cp=state.canvasPress;if(!cp||cp.pointerId!==e.pointerId)return;const dist=Math.hypot(e.clientX-cp.cx,e.clientY-cp.cy);const wasHeld=cp.fired;cancelCanvasPress();stage.classList.remove('dragging');if(wasHeld||dist>13){prevTap=null;return;}const now=Date.now();if(prevTap&&now-prevTap.time<360&&Math.hypot(e.clientX-prevTap.cx,e.clientY-prevTap.cy)<29){prevTap=null;lastTouchDouble=now;toggleTapZoom(e.clientX,e.clientY);}else prevTap={time:now,cx:e.clientX,cy:e.clientY};},{capture:true});
stage.addEventListener('pointercancel',e=>{if(e.pointerType==='touch'){touches.delete(e.pointerId);if(touches.size<2)state.gesture=null;if(!touches.size)state.gestureBlocked=false;}cancelCanvasPress();cancelLongPress();state.dragging=null;stage.classList.remove('dragging');},{capture:true});
stage.addEventListener('pointerdown',e=>{if(e.button!==0||!emptyAt(e)||state.gesture||state.gestureBlocked)return;closeMenu();stage.setPointerCapture(e.pointerId);state.dragging={type:'pan',sx:e.clientX,sy:e.clientY,x:state.x,y:state.y};stage.classList.add('dragging');if(e.pointerType==='touch'){const cp={pointerId:e.pointerId,cx:e.clientX,cy:e.clientY,fired:false,timer:null};cp.timer=setTimeout(()=>{if(state.dragging?.type==='pan'&&!state.gesture&&touches.size===1){cp.fired=true;state.dragging=null;stage.classList.remove('dragging');prevTap=null;openMenu(cp.cx,cp.cy);}},610);state.canvasPress=cp;}});
stage.addEventListener('pointermove',e=>{if(state.gesture||state.gestureBlocked||state.dragging?.type!=='pan')return;if(state.canvasPress&&Math.hypot(e.clientX-state.canvasPress.cx,e.clientY-state.canvasPress.cy)>10)cancelCanvasPress();state.x=state.dragging.x+e.clientX-state.dragging.sx;state.y=state.dragging.y+e.clientY-state.dragging.sy;cam();});
stage.addEventListener('pointerup',e=>{if(e.pointerType==='touch')return;cancelCanvasPress();if(state.dragging?.type==='pan'){state.dragging=null;stage.classList.remove('dragging');}});
stage.addEventListener('wheel',e=>{if(e.target.closest('.inspector,.importbox,.canvas-menu'))return;e.preventDefault();const rect=stageRect();zoom(state.z*(e.deltaY<0?1.12:.89),e.clientX-rect.left,e.clientY-rect.top)},{passive:false});
stage.addEventListener('dblclick',e=>{if(!emptyAt(e)||Date.now()-lastTouchDouble<500||Date.now()-lastTouchTime<950)return;e.preventDefault();toggleTapZoom(e.clientX,e.clientY)});
stage.addEventListener('contextmenu',e=>{if(!emptyAt(e))return;e.preventDefault();openMenu(e.clientX,e.clientY)});

function setMode(mode){state.mode=mode;state.selected=null;state.nodes=(mode==='derrick'?offshore:githubFixture()).map(n=>({...n}));state.edges=mode==='derrick'?deps.map(([from,to])=>({from,to,kind:'dependency'})).concat(refs.map(([from,to])=>({from,to,kind:'reference'}))):treeEdges(state.nodes);state.selected=mode==='derrick'?'T-004':'repo';$('offshoreBtn').setAttribute('aria-pressed',String(mode==='derrick'));$('githubBtn').setAttribute('aria-pressed',String(mode==='github'));$('viewTitle').textContent=mode==='derrick'?'Derrick Daily-Operations':'Repository structure';$('viewSub').textContent=mode==='derrick'?'10 linked tasks · Taiwan export target · 60 days to loading':'GitHub directory structure · one graph, different artefact types';$('crumbLabel').textContent=mode==='derrick'?'Derrick operations':'GitHub tree';fit()}
function githubFixture(){const entries=['apps','apps/web','apps/web/index.html','apps/web/app.js','apps/web/styles.css','apps/android','apps/android/README.md','crates','crates/shiori-core','crates/shiori-core/src','crates/shiori-core/src/lib.rs','crates/shiori-core/src/inbox.rs','crates/shiori-storage','crates/shiori-storage/src','crates/shiori-storage/src/lib.rs','docs','docs/adr','docs/adr/0001-rust-core-sqlite.md','docs/adr/0002-application-ports-and-provider-boundaries.md','ROADMAP.md','Cargo.toml'].map(path=>({path,type:path.includes('.')&&!path.split('/').pop().startsWith('shiori-')?'blob':'tree'}));const folders=new Set(entries.filter(e=>e.type==='tree').map(e=>e.path));return makeTreeNodes(entries,'cryogenized-spec/SHIORI-',folders);}
function treeEdges(nodes){return nodes.filter(n=>n.parent).map(n=>({from:n.parent,to:n.id,kind:'contains'}))}
function makeTreeNodes(entries,repo){const byPath=new Map();byPath.set('',{path:'',type:'tree'});for(const e of entries){if(typeof e.path!=='string'||!e.path||e.path.startsWith('/')||e.path.includes('..')||e.path.includes('\\')||e.path.length>350)continue;const parts=e.path.split('/');if(parts.some(p=>!p))continue;for(let i=1;i<=parts.length;i++){const path=parts.slice(0,i).join('/');if(!byPath.has(path))byPath.set(path,{path,type:i===parts.length?e.type:'tree'});}}
const list=[...byPath.values()].slice(0,450);const depths=new Map();const positions=new Map();const result=[];for(const e of list){const parentPath=e.path.includes('/')?e.path.slice(0,e.path.lastIndexOf('/')):'';const depth=e.path?e.path.split('/').length:0;const nrow=depths.get(depth)||0;depths.set(depth,nrow+1);const title=e.path?e.path.split('/').at(-1):repo;const kind=e.type==='tree'?'folder':'file';const id=e.path?'gh:'+e.path:'repo';positions.set(e.path,id);result.push({id,title,x:75+depth*260,y:115+nrow*104,status:'reference',kind,glyph:kind==='folder'?'▦':'≡',role:repo+(e.path?' / '+e.path:''),parent:e.path?positions.get(parentPath):null});}return result;}
function sceneSnapshot(){return {schema:'shiori.isw.scene',version:1,mode:state.mode,view:{x:state.x,y:state.y,zoom:state.z,connectorStyle:state.route},nodes:state.nodes.map(n=>({id:n.id,title:n.title,kind:n.kind||'task',status:n.status,x:n.x,y:n.y,glyph:n.glyph||'',role:n.role||'',due:n.due||''})),edges:state.edges.map(e=>({from:e.from,to:e.to,kind:e.kind}))};}
function safeScene(data){
 if(!data||data.schema!=='shiori.isw.scene'||data.version!==1||!Array.isArray(data.nodes)||!Array.isArray(data.edges))throw Error('Expected shiori.isw.scene v1 with nodes and edges arrays.');
 if(data.nodes.length>450||data.edges.length>1200)throw Error('Scene exceeds prototype limits (450 nodes / 1200 edges).');
 if(!data.nodes.length)throw Error('The scene must include at least one node.');
 const types=new Set(['task','folder','file','document','note','inbox','project','reference']);const statuses=new Set(['active','ready','review','blocked','reference']);const ids=new Set();
 const nodes=data.nodes.map((n,i)=>{if(!n||typeof n.id!=='string'||!n.id||n.id.length>180||ids.has(n.id))throw Error('Invalid or duplicate node id at '+i);ids.add(n.id);if(typeof n.title!=='string'||!n.title.trim()||n.title.length>240)throw Error('Invalid node title');if(!types.has(n.kind)||!statuses.has(n.status))throw Error('Unsupported node type or status');if(!Number.isFinite(n.x)||!Number.isFinite(n.y)||Math.abs(n.x)>1e6||Math.abs(n.y)>1e6)throw Error('Invalid node coordinate');for(const k of ['role','due','glyph'])if(n[k]!==undefined&&(typeof n[k]!=='string'||n[k].length>512))throw Error('Invalid '+k);return {id:n.id,title:n.title,kind:n.kind,status:n.status,x:n.x,y:n.y,role:n.role||'',due:n.due||'',glyph:n.glyph||'▤'};});
 const edges=data.edges.map((e,i)=>{if(!e||!ids.has(e.from)||!ids.has(e.to)||e.from===e.to||!['dependency','reference','contains','related_to'].includes(e.kind))throw Error('Invalid link at '+i);return {from:e.from,to:e.to,kind:e.kind};});
 const v=data.view||{};const route=['circuit','flow','direct'].includes(v.connectorStyle)?v.connectorStyle:'circuit';return {nodes,edges,route};
}
function statusNote(msg){$('notice').textContent=msg;$('notice').classList.add('active');setTimeout(()=>$('notice').classList.remove('active'),3800);}
$('routeStyle').addEventListener('change',e=>{state.route=e.target.value;drawEdges();statusNote('Connector display: '+e.target.selectedOptions[0].textContent)});
$('exportSceneBtn').onclick=()=>{const blob=new Blob([JSON.stringify(sceneSnapshot(),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='shiori-isw-scene-v1.json';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);statusNote('Scene exported. No tasks or providers were modified.')};
$('importSceneBtn').onclick=()=>$('sceneUpload').click();
$('sceneUpload').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;try{if(file.size>1_000_000)throw Error('Scene JSON must be 1 MB or smaller');const value=safeScene(JSON.parse(await file.text()));state.nodes=value.nodes;state.edges=value.edges;state.selected=value.nodes[0].id;state.mode='custom';state.route=value.route;$('routeStyle').value=value.route;$('viewTitle').textContent='Imported spatial scene';$('viewSub').textContent=`${value.nodes.length} objects · ${value.edges.length} relationships · local snapshot only`;$('crumbLabel').textContent='Imported scene';$('offshoreBtn').setAttribute('aria-pressed','false');$('githubBtn').setAttribute('aria-pressed','false');fit();statusNote('Validated scene loaded locally. No external writes.')}catch(err){statusNote(err.message||'Scene import failed')}e.target.value='';});
$('offshoreBtn').onclick=()=>setMode('derrick');$('githubBtn').onclick=()=>setMode('github');$('zoomIn').onclick=()=>zoom(state.z*1.2);$('zoomOut').onclick=()=>zoom(state.z/1.2);$('fitTool').onclick=fit;$('fitBottom').onclick=fit;$('legendTool').onclick=()=>{$('legend').hidden=!$('legend').hidden};function setTool(t){state.tool=t;for(const [id,mode] of [['selectTool','select'],['panTool','pan'],['moveTool','move']]){$(id).classList.toggle('active',t===mode);$(id).setAttribute('aria-pressed',String(t===mode));}}
function setLocked(locked){state.locked=locked;if(locked&&state.tool==='move')setTool('select');$('lockTool').textContent=locked?'🔒':'🔓';$('lockTool').setAttribute('aria-pressed',String(locked));$('lockTool').setAttribute('aria-label',locked?'Layout locked; activate to unlock':'Layout unlocked; activate to lock');$('lockTool').title=locked?'Unlock layout to move artefacts':'Lock layout to prevent artefact movement';for(const el of visibleElements.values())el.classList.toggle('locked',locked);try{localStorage.setItem('shiori.isw.layout-lock.v1',locked?'1':'0')}catch(e){}statusNote(locked?'Canvas layout locked. Pan and pinch remain enabled.':'Canvas unlocked. Select ✥ Move before repositioning nodes.');}
$('selectTool').onclick=()=>setTool('select');$('panTool').onclick=()=>setTool('pan');$('moveTool').onclick=()=>{if(state.locked){statusNote('Unlock the canvas with 🔒 before entering Move mode.');return;}setTool('move');};$('lockTool').onclick=()=>setLocked(!state.locked);$('importBtn').onclick=()=>{$('importbox').classList.toggle('active');$('importError').textContent=''};
$('importFileBtn').onclick=async()=>{const file=$('treeFile').files?.[0];$('importError').textContent='';if(!file){$('importError').textContent='Choose a JSON file first.';return}if(file.size>2_000_000){$('importError').textContent='Maximum file size is 2 MB for this proof.';return}try{const data=JSON.parse(await file.text());if(!Array.isArray(data.tree))throw Error('Expected a Git Trees API object with a tree array.');if(data.truncated)throw Error('GitHub marked this tree as truncated; fetch subtrees individually for complete imports.');const items=data.tree.filter(e=>e&&['blob','tree'].includes(e.type)&&typeof e.path==='string');if(!items.length)throw Error('No files or directories were found.');if(items.length>430)throw Error('This proof supports at most 430 imported tree entries.');const name=$('repoName').value.trim()||'GitHub repository';if(name.length>120)throw Error('Repository name is too long.');state.mode='github';state.nodes=makeTreeNodes(items,name);state.edges=treeEdges(state.nodes);state.selected='repo';$('viewTitle').textContent=name;$('viewSub').textContent=`Read-only tree import · ${state.nodes.length} objects · ${data.sha?'commit/tree '+String(data.sha).slice(0,9):'unversioned source'}`;$('crumbLabel').textContent=name;$('offshoreBtn').setAttribute('aria-pressed','false');$('githubBtn').setAttribute('aria-pressed','true');$('importbox').classList.remove('active');fit();}catch(err){$('importError').textContent=err instanceof Error?err.message:'Invalid file';}};

function markLocalScene(){state.mode='custom';$('offshoreBtn').setAttribute('aria-pressed','false');$('githubBtn').setAttribute('aria-pressed','false');$('viewSub').textContent='Local visual scene · not synced to Shiori tasks or external providers';$('crumbLabel').textContent='Local scene';}
function showCreate(){closeMenu();$('createArtifact').showModal();$('createName').focus()}
function showLink(){closeMenu();const options=state.nodes.map(n=>({label:n.title.length>66?n.title.slice(0,65)+'…':n.title,value:n.id}));for(const el of [$('linkFrom'),$('linkTo')]){el.replaceChildren();for(const o of options){const entry=document.createElement('option');entry.textContent=o.label;entry.value=o.value;el.append(entry)}}$('linkFrom').value=state.selected||state.nodes[0]?.id;$('linkTo').selectedIndex=state.nodes.length>1?1:0;$('linkDialog').showModal();}
function showAssistant(){closeMenu();$('assistantDialog').showModal();}
$('canvasMenu').addEventListener('click',e=>{const act=e.target.closest('button')?.dataset.action;if(!act)return;if(act==='artifact')showCreate();if(act==='link')showLink();if(act==='assistant')showAssistant();if(act==='cancel')closeMenu()});
$('createClose').onclick=()=>$('createArtifact').close();$('createCancel').onclick=()=>$('createArtifact').close();
$('createForm').addEventListener('submit',e=>{e.preventDefault();const title=$('createName').value.trim(),kind=$('createType').value,status=$('createStatus').value,role=$('createRole').value.trim();if(!title||title.length>160)return;const p=state.lastPoint||toWorld(stageRect().left+stage.clientWidth/2,stageRect().top+stage.clientHeight/2);
 if(state.mode==='live'){if(kind!=='task'){statusNote('Only tasks can be created in the Rust-backed alpha.');return;}window.__iswLive?.createTask({title,role,status,x:Math.round(p.x),y:Math.round(p.y)});return;}
 let id='local-'+(state.localNext++);while(byId(id))id='local-'+(state.localNext++);const glyphs={task:'▤',note:'✎',inbox:'▣',project:'▦',document:'◇'};state.nodes.push({id,title,kind,status,role,glyph:glyphs[kind]||'◇',x:Math.round(p.x),y:Math.round(p.y),due:''});state.selected=id;markLocalScene();$('createArtifact').close();$('createForm').reset();render();statusNote('Local scene artefact created. Not saved to Shiori database.');});
$('linkClose').onclick=()=>$('linkDialog').close();$('linkCancel').onclick=()=>$('linkDialog').close();
$('linkForm').addEventListener('submit',e=>{e.preventDefault();const from=$('linkFrom').value,to=$('linkTo').value,kind=$('linkKind').value;if(from===to||!byId(from)||!byId(to)){statusNote('Choose two different valid artefacts.');return;}if(state.edges.some(x=>x.from===from&&x.to===to&&x.kind===kind)){statusNote('That relationship is already in the local scene.');return;}
 // Changing actual dependencies is a separate permissioned action.
 if(state.mode==='live'){statusNote('Actual dependencies are read-only in this alpha.');return;}
 state.edges.push({from,to,kind});markLocalScene();$('linkDialog').close();invalidateLayout();schedulePaint();detail();statusNote('Local relation added for visualisation only. No actual task dependency changed.');});
$('assistantBtn').onclick=showAssistant;$('assistantClose').onclick=()=>$('assistantDialog').close();$('assistantDismiss').onclick=()=>$('assistantDialog').close();
$('assistantCopy').onclick=async()=>{const context={schema:'shiori.isw.prompt-context',version:1,scope:'display-only fixture',selected:state.selected,mode:state.mode,view:{connectorStyle:state.route},nodes:state.nodes.slice(0,40).map(n=>({id:n.id,title:n.title,kind:n.kind,status:n.status})),edges:state.edges.slice(0,80)};const prompt='Here is a read-only Shiori scene snapshot. Analyse or propose visual modifications as an explicit plan. Do not assume permission to modify canonical tasks or connected services.\n'+JSON.stringify(context,null,2);try{await navigator.clipboard.writeText(prompt);statusNote('Scene context prompt copied. No data was sent to a model.')}catch(_){statusNote('Clipboard unavailable: open from localhost/HTTPS or export Scene JSON instead.')}};
// Escape dismisses the menu even when no dialog is open. Keyboard context key opens on canvas centre.

function setCanvasOnly(on){
 document.body.classList.toggle('canvas-only',on);
 $('canvasRestore').hidden=!on;
 $('immersiveToggle').setAttribute('aria-pressed',String(on));
 $('immersiveToggle').textContent=on?'↩ Restore UI':'⛶ Canvas only';
 closeMenu();
 if(on){$('importbox').classList.remove('active');$('aiDock').hidden=true;}
 edgeStamp=null;schedulePaint();
}
$('immersiveToggle').addEventListener('click',()=>setCanvasOnly(true));
$('canvasRestore').addEventListener('click',()=>setCanvasOnly(false));
window.addEventListener('shiori-native-back',e=>{if(document.body.classList.contains('canvas-only')){e.preventDefault();setCanvasOnly(false);}},true);
function setSmooth(on){
 smoothMode=on;$('stage').classList.toggle('smooth-mode',on);
 $('smoothToggle').setAttribute('aria-pressed',String(on));
 $('smoothToggle').textContent=on?'Smooth: on':'Smooth: off';
 edgePathCache.clear();edgeStamp=null;schedulePaint();
 try{localStorage.setItem('shiori.isw.smooth.v1',on?'1':'0')}catch(_){}
}
$('smoothToggle').addEventListener('click',()=>setSmooth(!smoothMode));
let portraitMode='auto';
$('orientationBtn').addEventListener('click',()=>{
 const next=portraitMode==='auto'?'landscape':'auto';
 if(location.hostname==='appassets.androidplatform.net'){
  // Android's allowlisted shiori-ui command adjusts Activity orientation in place.
  window.location.href='shiori-ui://orientation/'+next;
 }else if(next==='landscape'){
  statusNote('Landscape layout is ready. Rotate the device to preview it in a browser.');
 }
 portraitMode=next;
 $('orientationBtn').setAttribute('aria-pressed',String(next==='landscape'));
 $('orientationBtn').textContent=next==='landscape'?'↻ Auto rotate':'↔ Landscape';
});
try{setSmooth(localStorage.getItem('shiori.isw.smooth.v1')!=='0')}catch(_){setSmooth(true)}
window.addEventListener('resize',()=>{edgeStamp=null;cam();});

window.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('canvas-only')){e.preventDefault();setCanvasOnly(false);}if(e.key==='Escape')closeMenu();if((e.key==='F10'&&e.shiftKey)||e.key==='ContextMenu'){if(document.activeElement===stage){e.preventDefault();const r=stageRect();openMenu(r.left+r.width/2,r.top+r.height/2);}}});

window.addEventListener('keydown',e=>{if(e.target.matches('input'))return;if(e.key==='0'){e.preventDefault();fit()}if(e.key==='+'||e.key==='='){e.preventDefault();zoom(state.z*1.2)}if(e.key==='-'){e.preventDefault();zoom(state.z/1.2)}});
setMode('derrick');if(window.matchMedia('(max-width: 750px)').matches)$('legend').hidden=true;stage.tabIndex=0;setTool('select');setLocked(true);
window.__iswDebug={select:(id)=>{if(byId(id)){state.selected=id;render();}},loadLive:(scene)=>{state.mode='live';state.nodes=scene.nodes.map(n=>({...n}));state.edges=scene.edges.map(e=>({...e}));state.selected=state.nodes[0]?.id||null;state.x=30;state.y=40;state.z=.8;$('offshoreBtn').setAttribute('aria-pressed','false');$('githubBtn').setAttribute('aria-pressed','false');$('viewTitle').textContent='My spatial workspace';$('viewSub').textContent=scene.nodes.length+' real SQLite tasks · '+scene.edges.length+' verified dependencies';$('crumbLabel').textContent='LIVE RUST / SQLITE';const footer=document.querySelector('.inspector footer');if(footer)footer.textContent='LIVE RUST TASKS / VIEW POSITIONS · NO LIVE AI';if(state.nodes.length)fit();else render();},getNodes:()=>state.nodes,getSelected:()=>state.selected,getStats:()=>({...PERF,totalNodes:state.nodes.length,totalEdges:state.edges.length,locked:state.locked,smoothMode,canvasOnly:document.body.classList.contains('canvas-only')}),getCamera:()=>({x:state.x,y:state.y,z:state.z}),
 populateFixture:(count=500)=>{const n=clamp(Math.floor(count),1,5000);state.nodes=Array.from({length:n},(_,i)=>({id:'bench-'+i,title:'Sample artefact '+i,kind:'task',status:i%11===0?'blocked':i%4===0?'review':'active',x:140+(i%70)*300,y:150+Math.floor(i/70)*190,role:'Synthetic benchmark',glyph:'▤'}));state.edges=state.nodes.slice(1).map((node,i)=>({from:'bench-'+i,to:node.id,kind:'dependency'}));state.selected='bench-0';state.mode='synthetic';state.x=25;state.y=5;state.z=.7;render();return state.nodes.length;},
 setCamera:(x,y,z)=>{state.x=x;state.y=y;state.z=clamp(z,.16,2.2);cam()},
 forceFlush:()=>{syncVisibleNodes();drawEdges();drawMinimap()}};
})();
