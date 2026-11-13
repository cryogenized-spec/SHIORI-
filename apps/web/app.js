/* SHIORI web prototype: local Rust/SQLite bridge or explicitly separate static demo. */
(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const icon = (name) => `<svg aria-hidden="true"><use href="#ic-${name}"/></svg>`;
  const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const newDate = (offset=0) => {const d = new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+offset);return d.toISOString().slice(0,10);};
  const displayDate = (date) => {if(!date)return 'No due date';const d = new Date(`${date}T12:00:00`);return Number.isNaN(d.getTime())?'Invalid date':new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short'}).format(d);};
  const defaultTasks = [
    {id:'t01',title:'Review the MCP tool contracts',description:'Make sure every operation has a narrow responsibility, an explicit schema, and an auditable permission boundary.',project:'Core',priority:'high',status:'progress',due:newDate(0),tags:['MCP','Architecture'],mins:45},
    {id:'t02',title:'Refine the Android quick-capture flow',description:'Keep capture under two taps. Document the notification shortcut, widget, and one-handed affordances.',project:'Interface',priority:'high',status:'todo',due:newDate(0),tags:['Android','UX'],mins:30},
    {id:'t03',title:'Approve SHIORI brand assets',description:'Review the original calligraphic mark, splash illustration and monochrome export requirements.',project:'Interface',priority:'medium',status:'done',due:newDate(0),tags:['Design'],mins:20},
    {id:'t04',title:'Define portable database contracts',description:'Specify a storage abstraction that supports local SQLite and hosted PostgreSQL without vendor-specific business logic.',project:'Core',priority:'high',status:'todo',due:newDate(1),tags:['Rust','Storage'],mins:70},
    {id:'t05',title:'Draft community governance guidelines',description:'Agree on contribution process, feature access guarantees and decision-making for a sustainable open-source project.',project:'Community',priority:'medium',status:'todo',due:newDate(2),tags:['Open source'],mins:50},
    {id:'t06',title:'Document offline sync conflict rules',description:'Describe revision IDs, idempotent mutations, task tombstones and deterministic resolution of concurrent edits.',project:'Core',priority:'medium',status:'progress',due:newDate(0),tags:['Offline','Sync'],mins:90},
    {id:'t07',title:'Prototype the compact MCP task card',description:'Create a read-only ui:// component with graceful fallback to structured data.',project:'Interface',priority:'low',status:'todo',due:newDate(3),tags:['MCP Apps'],mins:40},
    {id:'t08',title:'Evaluate the official Rust MCP SDK',description:'Review transport, typed tool definitions, authentication and framework compatibility.',project:'Infrastructure',priority:'medium',status:'done',due:newDate(-1),tags:['Rust','MCP'],mins:45},
    {id:'t09',title:'Prepare provider migration test plan',description:'Test export, restore and endpoint changes between container-based hosts before adding provider-specific adapters.',project:'Infrastructure',priority:'low',status:'todo',due:newDate(5),tags:['Portability'],mins:35},
    {id:'t10',title:'Write initial accessibility checklist',description:'Document keyboard access, focus, contrast, touch target sizes and reduced-motion support.',project:'Community',priority:'medium',status:'todo',due:newDate(0),tags:['Accessibility'],mins:30},
  ];
  const projectDescriptions = {
    'Core':'Rust task engine, data contracts, recurring work and offline synchronization.',
    'Interface':'Android, web and desktop experience, plus the SHIORI design system.',
    'Community':'Governance, documentation, accessibility and sustainable openness.',
    'Infrastructure':'MCP services, identity, deployment, backups and portability.'
  };
  const projectGlyphs = {Core:'◇',Interface:'✦',Community:'◎',Infrastructure:'⌘'};
  const views = {
    today:['My day','Your day, in order.','A quieter way to move meaningful work forward.','YOUR FOCUS',"Today's priorities"],
    attention:['Assigned to me','Work that needs a look.','Current local assignments with ready/waiting state. No remote sync.','ATTENTION','Local assignments'],
    inbox:['Inbox','Nothing gets lost.','Capture first. Organize when you have time.','ALL TASKS','Your inbox'],
    projects:['Projects','Everything has its place.','See progress across all the work that matters.','YOUR PORTFOLIO','Project spaces'],
    board:['Board','A clearer view of progress.','Move work through the stages that make sense.','WORKFLOW','Kanban board'],
    timeline:['Timeline','See what comes next.','A lightweight view of your upcoming commitments.','PLANNING','Next seven days'],
    reports:['Reports','Progress without pressure.','Useful signals, with no productivity theatre.','INSIGHTS','Workspace report'],
    automations:['Automations','Make routine work lighter.','Automation belongs to the user, not a subscription tier.','WORKFLOWS','Automation centre'],
    settings:['Settings','Made to be yours.','Control the workspace, your information and appearance.','PREFERENCES','Workspace settings']
  };
  let tasks;
  let mode = location.hostname==='appassets.androidplatform.net'
    ? 'android-local'
    : (location.protocol==='http:' && ['localhost','127.0.0.1'].includes(location.hostname) ? 'checking' : 'demo'); // no Android network dependency
  const taskStoreKey=mode==='android-local'?'shiori-android-local-tasks':'shiori-demo-tasks';
  try {const saved = JSON.parse(localStorage.getItem(taskStoreKey) || 'null');tasks = Array.isArray(saved) ? saved : mode==='android-local'?[]:defaultTasks;} catch {tasks = mode==='android-local'?[]:defaultTasks;}
  let attentionSnapshot=[];let attentionFreshAt=null;
  const fromStoredTask = (t) => ({
    id:t.id, title:t.title, description:t.notes||'', project:t.project,
    priority:t.priority, status:t.status==='in_progress'?'progress':t.status,
    due:t.due_on||'', tags:[], mins:t.estimate_minutes,
    createdAt:t.created_at, updatedAt:t.updated_at, version:t.version,
    assigneeId:t.assignee_id, blocked:!!t.blocked
  });
  async function reloadBridge() {
    const [response,attentionResponse] = await Promise.all([
      fetch('/api/tasks',{cache:'no-store'}),
      fetch('/api/attention',{cache:'no-store'})
    ]);
    if(!response.ok || !attentionResponse.ok) throw new Error('Local Rust storage could not be read');
    const [payload,attention]=await Promise.all([response.json(),attentionResponse.json()]);
    if(!Array.isArray(payload.tasks)||!Array.isArray(attention.tasks))throw new Error('Unexpected task response');
    attentionSnapshot=attention.tasks.map(fromStoredTask);
    attentionFreshAt=attention.fresh_at||null;
    const blockers=new Map(attentionSnapshot.map(task=>[task.id,task.blocked]));
    tasks=payload.tasks.map(fromStoredTask).map(task=>({...task,blocked:blockers.get(task.id)===true}));
    render();
  }
  async function requestBridge(path, data) {
    const response = await fetch(path, {
      method:'POST', headers:{'Content-Type':'application/json'},
      credentials:'same-origin', body:JSON.stringify(data)
    });
    if(response.status===409){
      await reloadBridge();
      throw new Error('conflict');
    }
    if(!response.ok) throw new Error('Local task operation rejected');
    await reloadBridge();
  }
  async function bootstrapBridge() {
    if(location.protocol!=='http:' || !['localhost','127.0.0.1'].includes(location.hostname)) return;
    try {
      const response = await fetch('/api/health', {cache:'no-store'});
      if(!response.ok) { mode='demo'; return; }
      const health = await response.json();
      if(health.mode!=='rust-sqlite' || health.protocol!==1) { mode='demo'; return; }
      mode='live';
      tasks=[]; // Never silently modify demo records after discovering a live DB.
      $('#footerMode').textContent='LOCAL RUST / SQLITE · OFFLINE';
      $('#railMode').textContent='● LOCAL DATABASE';
      await reloadBridge();
    } catch {
      if(mode==='checking') mode='demo';
      else if(mode==='live') {
        mode='local-error';tasks=[];render();
        $('#footerMode').textContent='LOCAL DATABASE UNAVAILABLE · NO DEMO FALLBACK';
        toast('Local database unavailable — no changes were made');
      }
    }
  }
  let view = 'today', filter = 'all', query = '', activeDetail = null;
  let sortMode = 'focus';
  try {
    const savedOrder = localStorage.getItem('shiori-demo-sort');
    if (['focus','fifo','due','priority'].includes(savedOrder)) sortMode = savedOrder;
  } catch {}
  $('#sortMode').value = sortMode;
  let savedViews=[];
  try {
    const parsed=JSON.parse(localStorage.getItem('shiori-saved-views')||'[]');
    if(Array.isArray(parsed))savedViews=parsed.filter(x=>x && typeof x.name==='string' && ['today','attention','inbox','board'].includes(x.view) && ['all','high','medium','low','urgent'].includes(x.filter) && ['focus','fifo','due','priority'].includes(x.sort) && typeof x.query==='string').slice(0,30);
  }catch{}
  function renderSavedViews(){
    const dropdown=$('#savedViewSelect'),selected=dropdown.value;
    dropdown.replaceChildren(new Option('Saved views',''));
    savedViews.forEach(entry=>dropdown.add(new Option(entry.name,entry.name)));
    dropdown.value=savedViews.some(x=>x.name===selected)?selected:'';
  }
  function persistSavedViews(){
    try{localStorage.setItem('shiori-saved-views',JSON.stringify(savedViews));}catch{}
    renderSavedViews();
    signalNativeVault();
  }
  renderSavedViews();

  // The Android WebView JSON format is not the Rust/SQLite database format.
  // The only native call surface is an internal custom URL intercepted by
  // Android; no JavaScriptInterface or network permission is required.
  // Native code pulls and validates the snapshot through evaluateJavascript.
  function signalNativeVault(){
    if(mode==='android-local' && window.shioriNativeVaultEnabled===true){
      window.location.href='shiori-vault://sync';
    }
  }

  // M2 opt-in native bridge. Only the installed Android shell can service
  // these requests. This never changes the regular WebView task array.
  const nativeWorking = {
    open:false, busy:false, error:'', items:[], total:0,
    editId:null, deleteId:null
  };
  // A view-only flag. Never persist it: every app launch starts on legacy tasks.
  const nativeReadOnly={active:false,page:0};
  // Debug-only opt-in normal-UI canary. Source selection is owned by Kotlin,
  // never inferred from task rows or localStorage. A failed native read
  // displays an error and does not silently fall back to the legacy source.
  const nativeCanary={selected:false,active:false,busy:false,pending:false,
    generation:0,error:'',metadata:null};
  const NATIVE_PAGE_SIZE=50;
  const MAX_NATIVE_SOURCE_TASKS=5000;
  let nativeInFlight=null;
  let nativeNextId=0;
  const NATIVE_COMMAND_TIMEOUT_MS=15000;

  window.shioriNativeTakeRequest=()=>{
    if(mode!=='android-local'||!nativeInFlight||nativeInFlight.taken) return null;
    nativeInFlight.taken=true;
    return JSON.stringify(nativeInFlight.request);
  };
  window.shioriNativeComplete=(requestId, raw)=>{
    const pending=nativeInFlight;
    if(!pending || pending.id!==String(requestId)) return false;
    clearTimeout(pending.timer);
    nativeInFlight=null;
    try {
      const response=JSON.parse(raw);
      if(!response || typeof response!=='object' || typeof response.ok!=='boolean')
        throw new Error('Invalid native task response');
      pending.resolve(response);
    } catch(error) {
      pending.reject(error);
    }
    return true;
  };
  function cancelNativeRequestForSourceChange(){
    // A new source must not inherit a pending request from the old one.
    // Late Kotlin callbacks are refused because their ID no longer matches.
    const pending=nativeInFlight;
    if(!pending)return;
    nativeInFlight=null;
    clearTimeout(pending.timer);
    pending.reject(new Error('Task source changed while request was pending'));
  }
  function nativeWorkingRequest(command){
    if(mode!=='android-local'||window.shioriNativeBridgeEnabled!==true)
      return Promise.reject(new Error('Native Rust bridge unavailable in this preview'));
    if(nativeInFlight)
      return Promise.reject(new Error('Another native operation is in progress'));
    const allowed=['list','create','rename','edit','status','delete','metadata'];
    if(!command || !allowed.includes(command.op))
      return Promise.reject(new Error('Unsupported native operation'));
    const id=String(++nativeNextId);
    const request=Object.assign({
      protocol:'shiori-native-working-v1',request_id:id,
      source:nativeCanary.selected?'primary':'working'
    },command);
    if(JSON.stringify(request).length>16000)
      return Promise.reject(new Error('Native request is too large'));
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{
        if(nativeInFlight && nativeInFlight.id===id) {
          nativeInFlight=null;
          reject(new Error('Native response timed out; refresh before retrying an edit'));
        }
      },NATIVE_COMMAND_TIMEOUT_MS);
      nativeInFlight={id,request,resolve,reject,timer,taken:false};
      // Native Android intercepts the custom URL. A cancelable signal lets
      // browser-level tests simulate the Kotlin host without navigating away.
      const signal=new Event('shiori-native-request',{cancelable:true});
      window.dispatchEvent(signal);
      if(!signal.defaultPrevented)
        window.location.href='shiori-vault://command?request_id='+encodeURIComponent(id);
    });
  }
  function nativePreviewRender(){
    if(!nativeWorking.open) return '';
    let html='<article class="settings-card native-working-panel" id="nativeWorkingPanel" aria-label="Experimental Rust task preview">';
    html+='<h3>Rust task workspace · separate copy</h3>';
    html+='<p>These are records in the experimental native SQLite working copy, NOT your normal Android task list. Changes here do not sync back. Keep an independent JSON backup.</p>';
    html+='<div class="settings-actions"><button type="button" data-native-op="refresh"'+(nativeWorking.busy?' disabled':'')+'>Refresh native tasks</button></div>';
    if(nativeWorking.busy) html+='<p role="status">Reading native task database…'+
      (nativeWorking.progress?' '+nativeWorking.progress+' task(s) loaded.':'')+'</p>';
    if(nativeWorking.error) html+='<p role="alert" class="native-working-error">'+escapeHTML(nativeWorking.error)+'</p>';
    html+='<form id="nativeWorkingCreate" class="native-working-create"><label for="nativeWorkingTitle">New task in Rust working copy</label>';
    html+='<input id="nativeWorkingTitle" name="title" maxlength="120" autocomplete="off" placeholder="Task title" required>';
    html+='<button type="submit"'+(nativeWorking.busy?' disabled':'')+'>Add native task</button></form>';
    html+='<p class="settings-hint">Loaded '+nativeWorking.items.length+' of '+nativeWorking.total+
      ' native records. Settings displays the first 50; use the read-only task layout to browse all records.</p>';
    html+='<div class="settings-actions"><button type="button" id="showNativeReadOnly"'+(nativeWorking.busy?' disabled':'')+'>Preview Rust tasks in normal task layout · read-only</button></div>';
    html+='<p class="settings-hint">This preview does not edit either task store. The complete native task source is retrieved in bounded 50-row pages.</p>';
    html+='<div class="native-working-items">';
    for(const task of nativeWorking.items.slice(0,50)) {
      const id=escapeHTML(task.id);
      const version=Number(task.version);
      if(!Number.isInteger(version)||version<1) continue;
      const busy=nativeWorking.busy?' disabled':'';
      html+='<div class="native-working-row">';
      html+='<div><strong>'+escapeHTML(task.title)+'</strong><p>'+escapeHTML(task.project)+' · '+escapeHTML(task.status.replace(/_/g,' '))+' · revision '+version+'</p></div>';
      if(nativeWorking.editId===task.id) {
        html+='<label for="nativeWorkingRename">Rename this native task</label><input id="nativeWorkingRename" maxlength="120" value="'+escapeHTML(task.title)+'">';
        html+='<div class="settings-actions"><button type="button" data-native-op="rename-save" data-native-id="'+id+'"'+busy+'>Save title</button>';
        html+='<button type="button" data-native-op="rename-cancel">Cancel</button></div>';
      } else {
        html+='<div class="settings-actions"><button type="button" data-native-op="rename" data-native-id="'+id+'"'+busy+'>Rename</button>';
        html+='<button type="button" data-native-op="status" data-native-id="'+id+'"'+busy+'>'+(task.status==='done'?'Reopen':'Complete')+'</button>';
        if(nativeWorking.deleteId===task.id) {
          html+='<button type="button" data-native-op="delete-confirm" data-native-id="'+id+'"'+busy+'>Confirm delete from copy</button>';
          html+='<button type="button" data-native-op="delete-cancel">Keep</button>';
        } else {
          html+='<button type="button" data-native-op="delete" data-native-id="'+id+'"'+busy+'>Delete</button>';
        }
        html+='</div>';
      }
      html+='</div>';
    }
    html+='</div></article>';
    return html;
  }
  function nativePreviewUpdate(){
    if(view==='settings')render();
  }
  // Read *every* native page without ever exposing a partial collection as
  // a complete result. Each successive page pins a consistency snapshot.
  // Changed, duplicated, missing, reordered or truncated pages fail closed.
  async function nativePreviewRefresh(){
    if(nativeWorking.busy) return false;
    nativeWorking.busy=true;
    nativeWorking.error='';
    nativeWorking.progress=0;
    nativePreviewUpdate();
    try {
      const all=[];
      const ids=new Set();
      let total=null;
      let snapshot=null;
      let offset=0;
      while(true) {
        const request={op:'list',offset};
        if(snapshot!==null)request.snapshot=snapshot;
        const response=await nativeWorkingRequest(request);
        if(!response.ok) throw new Error(String(response.error||'Cannot read native tasks'));
        if(!Number.isSafeInteger(response.total) || response.total<0 ||
           response.total>MAX_NATIVE_SOURCE_TASKS ||
           !Number.isSafeInteger(response.offset)||response.offset!==offset ||
           typeof response.snapshot!=='string' ||
           !/^[0-9a-f]{16}-\d+$/.test(response.snapshot) ||
           !Array.isArray(response.tasks) ||
           response.tasks.length>NATIVE_PAGE_SIZE)
          throw new Error('Invalid or oversized native task page');
        if(total===null){total=response.total;snapshot=response.snapshot;}
        if(response.total!==total || response.snapshot!==snapshot)
          throw new Error('Native tasks changed during paging; refresh the complete list');
        for(const task of response.tasks){
          if(!task || typeof task.id!=='string' || !task.id ||
             typeof task.title!=='string'||typeof task.project!=='string'||
             !['todo','in_progress','done'].includes(task.status) ||
             !['low','medium','high','urgent'].includes(task.priority)||
             !Number.isSafeInteger(task.version)||task.version<1 ||
             ids.has(task.id))
            throw new Error('Duplicate or invalid native task returned');
          ids.add(task.id);
          all.push(task);
        }
        nativeWorking.progress=all.length;
        if(response.next_offset===null){
          if(all.length!==total)throw new Error('Incomplete native task list; refusing partial preview');
          break;
        }
        if(!Number.isSafeInteger(response.next_offset) ||
           response.next_offset!==offset+response.tasks.length ||
           response.next_offset>total || response.tasks.length!==NATIVE_PAGE_SIZE)
          throw new Error('Native task paging order is inconsistent');
        offset=response.next_offset;
        nativePreviewUpdate();
      }
      // Publish only after all pages agree on the same snapshot.
      nativeWorking.items=all;
      nativeWorking.total=total;
      nativeWorking.snapshot=snapshot;
    } catch(error) {
      // Do not keep stale pages from the previous read after any failure.
      nativeWorking.items=[];
      nativeWorking.total=0;
      nativeWorking.snapshot=null;
      nativeWorking.error=error.message||'Native task listing unavailable';
    } finally {
      nativeWorking.busy=false;
      nativeWorking.progress=0;
      nativePreviewUpdate();
    }
    return !nativeWorking.error;
  }
  function clearTaskSurfacesOnSourceChange(){
    activeDetail=null;
    $('#detailOverlay').classList.remove('open');
    $('#detailPane').replaceChildren();
    $('#taskModal').classList.remove('open');
    $('#taskModal').setAttribute('aria-hidden','true');
    $('#editModal').classList.remove('open');
    $('#editModal').setAttribute('aria-hidden','true');
  }
  async function loadNativeCanary(){
    if(mode!=='android-local'||!nativeCanary.selected||nativeCanary.busy)return false;
    const generation=nativeCanary.generation;
    nativeCanary.busy=true;
    nativeCanary.active=false;
    nativeCanary.error='';
    clearTaskSurfacesOnSourceChange();
    tasks=[];
    render();
    try{
      const response=await nativeWorkingRequest({op:'metadata'});
      if(!nativeCanary.selected||nativeCanary.generation!==generation)return false;
      if(!response.ok||!response.metadata||
         !Array.isArray(response.metadata.saved_views)||
         typeof response.metadata.tags_by_id!=='object'||
         response.metadata.tags_by_id===null)
        throw new Error('Native metadata unavailable; no source cutover');
      if(!(await nativePreviewRefresh()))
        throw new Error(nativeWorking.error||'Native task read failed');
      if(!nativeCanary.selected||nativeCanary.generation!==generation)return false;
      const tags=response.metadata.tags_by_id;
      const candidate=nativeWorking.items.map(row=>{
        const task=fromStoredTask(row);
        const values=Object.prototype.hasOwnProperty.call(tags,row.id)?tags[row.id]:[];
        if(!Array.isArray(values)||values.some(x=>typeof x!=='string'))
          throw new Error('Native tags are invalid');
        task.tags=[...values];
        return task;
      });
      tasks=candidate;
      nativeCanary.metadata=response.metadata;
      nativeCanary.active=true;
      nativeCanary.error='';
      $('#footerMode').textContent='RUST SQLITE · DEBUG CUTOVER CANARY';
      $('#railMode').textContent='● RUST SQLITE (EXPERIMENTAL)';
      render();
      return true;
    }catch(error){
      if(!nativeCanary.selected||nativeCanary.generation!==generation)return false;
      tasks=[];
      nativeCanary.active=false;
      nativeCanary.error=error.message||'Cannot read native task source';
      render();
      return false;
    }finally{
      if(nativeCanary.generation===generation){
        nativeCanary.busy=false;
        render();
      }
    }
  }
  // Freeze legacy writes while Kotlin validates parity and commits the
  // independent rollback. No edits are allowed between snapshot and switch.
  window.shioriFreezeLegacyForCutover=()=>{
    if(mode!=='android-local'||nativeCanary.selected||nativeCanary.pending)return null;
    nativeCanary.pending=true;
    render();
    return window.shioriExportBackup();
  };
  // Android asks to validate the frozen legacy source against two private
  // backups before any rollback is committed. A running native operation
  // cannot be confused with a source switch or silently abandoned.
  window.shioriNativeFreezeForRollback=()=>{
    if(mode!=='android-local'||!nativeCanary.selected||
       nativeCanary.pending||nativeCanary.busy||nativeInFlight)return null;
    nativeCanary.pending=true;
    render();
    const snapshot=window.shioriExportBackup();
    if(typeof snapshot!=='string'){
      nativeCanary.pending=false;
      render();
      return null;
    }
    return snapshot;
  };
  window.shioriAbortCutover=()=>{
    nativeCanary.pending=false;
    render();
  };
  window.shioriNativeActivate=()=>{
    if(mode!=='android-local')return Promise.resolve(false);
    cancelNativeRequestForSourceChange();
    nativeCanary.pending=false;
    nativeCanary.generation++;
    nativeCanary.selected=true;
    return loadNativeCanary();
  };
  window.shioriNativeUnavailable=()=>{
    cancelNativeRequestForSourceChange();
    clearTaskSurfacesOnSourceChange();
    nativeCanary.generation++;
    nativeCanary.selected=true;
    nativeCanary.active=false;
    nativeCanary.error='Native database could not be verified. The original Android tasks remain on the device. Use Settings to roll back.';
    tasks=[];
    render();
  };
  window.shioriNativeDeactivate=()=>{
    if(mode!=='android-local')return false;
    cancelNativeRequestForSourceChange();
    clearTaskSurfacesOnSourceChange();
    nativeCanary.generation++;
    nativeCanary.selected=false;nativeCanary.active=false;
    nativeCanary.busy=false;nativeCanary.pending=false;nativeCanary.error='';nativeCanary.metadata=null;
    nativeWorking.open=false;nativeWorking.items=[];
    try{
      const saved=JSON.parse(localStorage.getItem(taskStoreKey)||'[]');
      tasks=Array.isArray(saved)?saved:[];
    }catch{tasks=[];}
    $('#footerMode').textContent='ANDROID · OFFLINE LOCAL DEVICE';
    $('#railMode').textContent='● OFFLINE DEVICE';
    try{
      const originalOrder=localStorage.getItem('shiori-demo-sort');
      if(['focus','fifo','due','priority'].includes(originalOrder)){
        sortMode=originalOrder;$('#sortMode').value=sortMode;
      }
    }catch{}
    setView('inbox');
    return true;
  };
  async function mutateNativeCanary(command){
    if(!nativeCanary.active||nativeCanary.busy||nativeCanary.pending)return false;
    const generation=nativeCanary.generation;
    nativeCanary.busy=true;
    try{
      const result=await nativeWorkingRequest(command);
      if(!nativeCanary.selected||nativeCanary.generation!==generation)return false;
      if(!result.ok)throw new Error(String(result.error||'Native write failed'));
      nativeCanary.busy=false;
      return await loadNativeCanary();
    }catch(error){
      if(!nativeCanary.selected||nativeCanary.generation!==generation)return false;
      nativeCanary.busy=false;
      nativeCanary.error='Native write failed: '+(error.message||'refresh required');
      toast('Native write rejected; refresh and inspect the task');
      render();
      return false;
    }
  }

  async function nativePreviewMutate(command){
    if(nativeWorking.busy) return;
    nativeWorking.busy=true;
    nativeWorking.error='';
    nativePreviewUpdate();
    try {
      const result=await nativeWorkingRequest(command);
      if(!result.ok) throw new Error(String(result.error||'Native change was rejected'));
      nativeWorking.editId=null;
      nativeWorking.deleteId=null;
    } catch(error) {
      nativeWorking.error=(error.message||'Native change failed')+
        '. Check or refresh the working copy before trying again.';
      nativeWorking.busy=false;
      nativePreviewUpdate();
      return;
    }
    nativeWorking.busy=false;
    await nativePreviewRefresh();
  }
  window.shioriNativeWorkingReady=()=>{
    if(mode!=='android-local'||nativeCanary.selected) return;
    nativeWorking.open=true;
    nativeWorking.error='';
    if(view!=='settings')setView('settings');
    nativePreviewRefresh();
  };

  // Snapshot projection into the existing task-row layout, never into tasks.
  function renderNativeReadOnly(){
    let visible=nativeWorking.items.map(fromStoredTask);
    if(filter!=='all')visible=visible.filter(t=>t.priority===filter);
    if(query.trim()){
      const q=query.trim().toLowerCase();
      visible=visible.filter(t=>[t.title,t.project,t.description].join(' ').toLowerCase().includes(q));
    }
    const rank=p=>({urgent:0,high:1,medium:2,low:3}[p]??4);
    visible=[...visible].sort((a,b)=>{
      const due=String(a.due||'9999-12-31').localeCompare(String(b.due||'9999-12-31'));
      const priority=rank(a.priority)-rank(b.priority);
      if(sortMode==='due')return due||priority||a.id.localeCompare(b.id);
      if(sortMode==='priority')return priority||due||a.id.localeCompare(b.id);
      if(sortMode==='fifo')return (a.createdAt||'').localeCompare(b.createdAt||'')||a.id.localeCompare(b.id);
      return (a.status==='done')-(b.status==='done')||due||priority||a.id.localeCompare(b.id);
    });
    const pageCount=Math.max(1,Math.ceil(visible.length/NATIVE_PAGE_SIZE));
    nativeReadOnly.page=Math.min(nativeReadOnly.page,pageCount-1);
    const windowStart=nativeReadOnly.page*NATIVE_PAGE_SIZE;
    const windowed=visible.slice(windowStart,windowStart+NATIVE_PAGE_SIZE);
    let html='<section class="native-readonly-banner" role="status"><strong>Read-only Rust/SQLite source preview</strong>'+
      '<p>'+nativeWorking.total+' task record(s) from the separate working copy. Your original Android tasks are unchanged.</p>'+
      '<button type="button" id="closeNativeReadOnly">Return to Android tasks</button></section>';
    if(!visible.length){
      return html+'<div class="empty-state"><h3>No matching native tasks</h3>'+
        '<p>Try another filter or return to your regular Android list.</p></div>';
    }
    html+='<nav class="native-readonly-pager" aria-label="Rust task preview pages">'+
      '<span>Showing '+(windowStart+1)+'–'+(windowStart+windowed.length)+' of '+visible.length+
      ' matching native records · page '+(nativeReadOnly.page+1)+' / '+pageCount+'</span>'+
      '<button type="button" data-native-page="prev"'+(nativeReadOnly.page===0?' disabled':'')+'>Previous</button>'+
      '<button type="button" data-native-page="next"'+(nativeReadOnly.page+1===pageCount?' disabled':'')+'>Next</button></nav>';
    html+='<div class="task-list">'+windowed.map(t=>
      '<article class="task-row native-readonly-row">'+
      '<span class="native-readonly-marker" aria-hidden="true">'+icon('search')+'</span>'+
      '<div class="task-info"><div class="task-title'+(t.status==='done'?' done':'')+'">'+
      escapeHTML(t.title)+'</div><div class="task-meta"><span class="project-chip">'+
      escapeHTML(t.project)+'</span><span>Read-only · '+
      escapeHTML(t.status.replace(/_/g,' '))+'</span></div></div>'+
      '<div class="task-end"><span class="due-chip">'+escapeHTML(displayDate(t.due))+
      '</span></div></article>'
    ).join('')+'</div>';
    return html;
  }
  async function openNativeReadOnly(){
    if(mode!=='android-local'||nativeCanary.selected||!nativeWorking.open||nativeWorking.busy)return;
    if(!(await nativePreviewRefresh()))return;
    // Full pages are already validated before nativePreviewRefresh returns.
    nativeReadOnly.page=0;
    nativeReadOnly.active=true;
    setView('inbox');
  }

  const ANDROID_BACKUP_FORMAT='shiori-android-local-v1';
  const MAX_BACKUP_CHARS=1000000;
  window.shioriExportBackup=()=>{
    if(mode!=='android-local')return null;
    let legacy=tasks;
    if(nativeCanary.selected){
      try{
        const stored=JSON.parse(localStorage.getItem(taskStoreKey)||'[]');
        if(!Array.isArray(stored))return null;
        legacy=stored;
      }catch{return null;}
    }
    let originalViews=savedViews, originalSort=sortMode;
    if(nativeCanary.selected){
      try{
        originalViews=JSON.parse(localStorage.getItem('shiori-saved-views')||'[]');
        originalSort=localStorage.getItem('shiori-demo-sort')||'focus';
      }catch{return null;}
    }
    const json=JSON.stringify({format:ANDROID_BACKUP_FORMAT,
      exported_at:new Date().toISOString(),tasks:legacy,
      saved_views:originalViews,sort:originalSort});
    return json.length<=MAX_BACKUP_CHARS?json:null;
  };
  window.shioriRestoreBackup=(raw)=>{
    if(mode!=='android-local'||nativeReadOnly.active||nativeCanary.selected||nativeCanary.pending||typeof raw!=='string'||raw.length>MAX_BACKUP_CHARS)return false;
    try{
      const data=JSON.parse(raw);
      if(!data||data.format!==ANDROID_BACKUP_FORMAT||!Array.isArray(data.tasks)
         ||data.tasks.length>5000||!Array.isArray(data.saved_views)
         ||data.saved_views.length>30)return false;
      const ids=new Set();
      const restored=data.tasks.map(item=>{
        if(!item||typeof item!=='object'||Array.isArray(item))throw new Error('task');
        const title=item.title,project=item.project,notes=item.description||'';
        const id=item.id,priority=item.priority,status=item.status;
        const due=item.due||'';
        if(typeof id!=='string'||!id||id.length>128||ids.has(id)
           ||typeof title!=='string'||!title.trim()||title.length>120
           ||typeof project!=='string'||!project.trim()||project.length>160
           ||typeof notes!=='string'||notes.length>6000
           ||!['low','medium','high','urgent'].includes(priority)
           ||!['todo','progress','done'].includes(status)
           ||typeof due!=='string'||(due!==''&&!/^\d{4}-\d{2}-\d{2}$/.test(due))
           ||(item.mins!=null&&(!Number.isInteger(item.mins)||item.mins<1||item.mins>1440))
           ||(item.assigneeId!=null&&(typeof item.assigneeId!=='string'
              ||!/^[A-Za-z0-9._:-]{1,64}$/.test(item.assigneeId))))throw new Error('fields');
        if(item.tags!=null&&(!Array.isArray(item.tags)||item.tags.length>16
           ||item.tags.some(t=>typeof t!=='string'||t.length>50)))throw new Error('tags');
        ids.add(id);
        return {id,title:title.trim(),description:notes,project:project.trim(),
          priority,status,due,tags:item.tags||[],mins:item.mins??null,
          assigneeId:item.assigneeId??null,
          createdAt:typeof item.createdAt==='string'&&item.createdAt.length<=64
            ?item.createdAt:new Date().toISOString(),
          version:Number.isInteger(item.version)&&item.version>0?item.version:1};
      });
      const views=data.saved_views.map(entry=>{
        if(!entry||typeof entry!=='object'
           ||typeof entry.name!=='string'||!entry.name.trim()||entry.name.length>40
           ||!['today','attention','inbox','board'].includes(entry.view)
           ||!['all','urgent','high','medium','low'].includes(entry.filter)
           ||!['focus','fifo','due','priority'].includes(entry.sort)
           ||typeof entry.query!=='string'||entry.query.length>250)throw new Error('view');
        return {name:entry.name.trim(),view:entry.view,filter:entry.filter,
          sort:entry.sort,query:entry.query};
      });
      const order=['focus','fifo','due','priority'].includes(data.sort)?data.sort:'focus';
      const oldTasks=localStorage.getItem(taskStoreKey),
        oldViews=localStorage.getItem('shiori-saved-views'),
        oldSort=localStorage.getItem('shiori-demo-sort');
      try{
        localStorage.setItem(taskStoreKey,JSON.stringify(restored));
        localStorage.setItem('shiori-saved-views',JSON.stringify(views));
        localStorage.setItem('shiori-demo-sort',order);
      }catch{
        // Best-effort rollback if the Android WebView storage is out of quota.
        try{
          if(oldTasks===null)localStorage.removeItem(taskStoreKey);
          else localStorage.setItem(taskStoreKey,oldTasks);
          if(oldViews===null)localStorage.removeItem('shiori-saved-views');
          else localStorage.setItem('shiori-saved-views',oldViews);
          if(oldSort===null)localStorage.removeItem('shiori-demo-sort');
          else localStorage.setItem('shiori-demo-sort',oldSort);
        }catch{}
        return false;
      }
      tasks=restored;savedViews=views;sortMode=order;
      $('#sortMode').value=sortMode;
      renderSavedViews();setView('today');toast('Offline backup restored');
      signalNativeVault();
      return true;
    }catch{return false;}
  };
  let calendarExpanded = true;
  try { calendarExpanded = localStorage.getItem('shiori-calendar-expanded') !== 'false'; } catch {}
  let calendarSelected = null;
  const calendarMonth = new Date();
  calendarMonth.setDate(1);
  calendarMonth.setHours(12, 0, 0, 0);
  const dateKey = (year, month, day) => `${year}-${String(month + 1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
  let toastTimer;
  const save=()=>{
    if(nativeReadOnly.active||nativeCanary.selected||nativeCanary.pending){
      toast('Task writes are not allowed in the legacy source during native canary');
      return;
    }
    try{
      localStorage.setItem(taskStoreKey,JSON.stringify(tasks));
      signalNativeVault();
    }catch{toast('Local storage is full or unavailable');}
  };
  const count=()=>({all:tasks.length,open:tasks.filter(t=>t.status!=='done').length,done:tasks.filter(t=>t.status==='done').length,today:tasks.filter(t=>t.status!=='done' && t.due<=newDate()).length});
  const chosen = () => {
    let result=tasks;
    if(view==='today') result=result.filter(t=>calendarSelected ? t.due===calendarSelected : (t.due<=newDate() || t.status==='progress'));
    if(view==='inbox') result=result.filter(t=>t.status!=='done');
    if(view==='attention'){
      result = mode==='live'
        ? result.filter(t=>t.assigneeId==='local' && t.status!=='done')
        : result.filter(t=>t.status!=='done' && ((t.due && t.due<=newDate()) || ['high','urgent'].includes(t.priority) || t.status==='progress'));
    }
    if(filter!=='all') result=result.filter(t=>t.priority===filter);
    if(query.trim()) {const q=query.trim().toLowerCase();result=result.filter(t=>[t.title,t.project,t.description,...(t.tags||[])].join(' ').toLowerCase().includes(q));}
    const priorityRank = (p) => ({urgent:0,high:1,medium:2,low:3}[p] ?? 4);
    return [...result].sort((a,b) => {
      if (sortMode==='fifo') {
        // Old sample records have no creation timestamp: use their original
        // insertion order. Real user-captured records have createdAt.
        if (a.createdAt && b.createdAt) return a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id);
        if (a.createdAt) return 1;
        if (b.createdAt) return -1;
        return tasks.indexOf(a) - tasks.indexOf(b);
      }
      const due = String(a.due||'9999-12-31').localeCompare(String(b.due||'9999-12-31'));
      const priority = priorityRank(a.priority)-priorityRank(b.priority);
      if (sortMode==='due') return due || priority || a.id.localeCompare(b.id);
      if (sortMode==='priority') return priority || due || a.id.localeCompare(b.id);
      return (a.status==='done')-(b.status==='done') || due || priority || a.id.localeCompare(b.id);
    });
  };
  function toast(msg){$('#toast').textContent=msg;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),2400);}
  function renderStats(){const c=count();const cards=[['Open tasks',c.open,'across all projects','check-circle'],['Due today',c.today,'needs your attention','calendar'],['Completed',c.done,'small wins add up','check'],['Projects',mode==='demo'?4:new Set(tasks.map(t=>t.project)).size,mode==='demo'?'sample project spaces':'local project spaces','folder']];$('#stats').innerHTML=cards.map(([label,value,note,glyph])=>`<article class="stat-card"><div class="stat-head">${escapeHTML(label)}${icon(glyph)}</div><div class="stat-value">${value.toString().padStart(2,'0')}</div><div class="stat-foot">${escapeHTML(note)}</div></article>`).join('');const today=tasks.filter(t=>t.due<=newDate());const pct=today.length?Math.round(today.filter(t=>t.status==='done').length/today.length*100):0;$('#momentumNumber').innerHTML=`${pct}<span>%</span>`;$('#momentumFill').style.width=pct+'%';$('#navTodayCount').textContent=String(c.today).padStart(2,'0');$('#navAttentionCount').textContent=String(mode==='live'?attentionSnapshot.length:tasks.filter(t=>t.status!=='done' && ((t.due && t.due<=newDate()) || ['high','urgent'].includes(t.priority) || t.status==='progress')).length).padStart(2,'0');}
  function renderCalendar() {
    const wrapper = $('#homeCalendar');
    const toggle = $('#homeCalendarToggle');
    toggle.style.display = view==='today' ? 'inline-flex' : 'none';
    toggle.setAttribute('aria-expanded', String(calendarExpanded));
    toggle.setAttribute('aria-label', calendarExpanded ? 'Hide calendar' : 'Show calendar');
    $('#calendarToggleLabel').textContent = calendarExpanded ? 'Hide calendar' : 'Show calendar';
    wrapper.hidden = view!=='today' || !calendarExpanded;
    if (wrapper.hidden) return;
    const year=calendarMonth.getFullYear(), month=calendarMonth.getMonth();
    const first=(new Date(year,month,1).getDay()+6)%7;
    const total=new Date(year,month+1,0).getDate();
    const taskCounts = new Map();
    tasks.filter(t=>t.status!=='done' && t.due).forEach(t=>taskCounts.set(t.due,(taskCounts.get(t.due)||0)+1));
    const heading = new Intl.DateTimeFormat('en-GB',{month:'long',year:'numeric'}).format(calendarMonth);
    const weekdayNames=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    let cells='';
    for(let offset=0;offset<first;offset++) cells+='<span class="cal-empty" aria-hidden="true"></span>';
    for(let day=1;day<=total;day++) {
      const key=dateKey(year,month,day), n=taskCounts.get(key)||0;
      const classes=['cal-day', key===newDate()?'is-today':'', key===calendarSelected?'is-selected':''].filter(Boolean).join(' ');
      cells+=`<button type="button" class="${classes}" data-calendar-date="${key}" title="${key}: ${n} open tasks" aria-describedby="calendarMonthHeading calendarLegend" aria-pressed="${String(key===calendarSelected)}"><span>${day}</span>${n?`<small class="cal-count">${n}</small>`:''}</button>`;
    }
    wrapper.innerHTML = `<div class="calendar-top"><div><span class="section-eyebrow">AT A GLANCE</span><h3 id="calendarMonthHeading">${heading}</h3></div><div class="calendar-commands"><button type="button" data-calendar-today>Today</button><button type="button" data-calendar-shift="-1" aria-label="Previous month">‹</button><button type="button" data-calendar-shift="1" aria-label="Next month">›</button></div></div><div class="cal-grid">${weekdayNames.map(d=>`<span class="cal-weekday">${d}</span>`).join('')}${cells}</div><div class="calendar-note" id="calendarLegend">Numbers show unfinished tasks due that day. Select a date to focus your list.</div>`;
  }
  function renderList(){const arr=chosen();const note=view==='attention'?'<div class="attention-note">'+(mode==='live'?'Assigned to local identity · cached from local SQLite at '+(attentionFreshAt?escapeHTML(new Date(attentionFreshAt).toLocaleTimeString()):'unknown time')+'. No remote account or sync.':'Demo preview · due, high-priority or in-progress. Assignments are unavailable in demo mode.')+'</div>':'';if(!arr.length)return note+'<div class="empty-state">'+icon('check-circle')+'<h3>A little breathing room.</h3><p>Nothing matches this view. Try another filter or create a task.</p></div>';return note+`<div class="task-list">${arr.map(t=>`<article class="task-row"><button class="task-complete ${t.status==='done'?'done':''}" aria-label="${t.status==='done'?'Reopen':'Complete'} ${escapeHTML(t.title)}" data-complete="${escapeHTML(t.id)}">${t.status==='done'?icon('check'):''}</button><div class="task-info" data-detail="${escapeHTML(t.id)}"><div class="task-title ${t.status==='done'?'done':''}">${escapeHTML(t.title)}</div><div class="task-meta"><span class="project-chip">${escapeHTML(t.project)}</span><span class="task-meta-dot"></span><span>${escapeHTML((t.tags||[]).slice(0,2).join(' / '))}</span>${view==='attention' && mode==='live'?'<span class="attention-state '+(t.blocked?'waiting':'ready')+'">'+(t.blocked?'Waiting on dependency':'Actionable')+'</span>':''}</div></div><div class="task-end"><span class="priority-dot ${t.priority}" title="${t.priority} priority"></span><span class="due-chip">${icon('calendar')}${displayDate(t.due)}</span>${icon('chevron').replace('<svg ', '<svg class="row-arrow" data-detail="'+escapeHTML(t.id)+'" ')}</div></article>`).join('')}</div>`;}
  function renderBoard(){const statuses=[['todo','To do'],['progress','In progress'],['done','Completed']];const list=chosen();return `<div class="board">${statuses.map(([status,label])=>{const group=list.filter(t=>t.status===status);return `<section class="board-col" data-drop="${status}"><div class="board-head"><b>${label}</b><span class="board-count">${group.length}</span></div>${group.map(t=>`<article class="board-card" draggable="true" data-drag="${escapeHTML(t.id)}" data-detail="${escapeHTML(t.id)}"><b>${escapeHTML(t.title)}</b><div class="task-meta"><span class="project-chip">${escapeHTML(t.project)}</span><span>${displayDate(t.due)}</span></div></article>`).join('')}${group.length?'':'<div style="font-size:11px;color:var(--faint);padding:8px">Drop tasks here</div>'}</section>`}).join('')}</div>`;}
  function renderProjects(){const projects=mode==='demo'?Object.keys(projectDescriptions):[...new Set(tasks.map(t=>t.project))];return `<div class="project-grid">${projects.map(p=>{const all=tasks.filter(t=>t.project===p),done=all.filter(t=>t.status==='done').length,pct=all.length?Math.round(done/all.length*100):0;return `<article class="project-card" data-project="${escapeHTML(p)}"><div class="project-card-top"><span>${projectGlyphs[p]||'◇'}</span><span>${all.length} tasks ${icon('chevron')}</span></div><h3>${escapeHTML(p==='Core'?'Core platform':p==='Interface'?'Interface design':p)}</h3><p>${escapeHTML(projectDescriptions[p]||'Local project')}</p><div class="project-progress"><span>${done} of ${all.length} completed</span><strong>${pct}%</strong></div><div class="project-bar"><div style="width:${pct}%"></div></div></article>`}).join('')}</div>`;}
  function renderTimeline(){return `<div class="timeline">${Array.from({length:7},(_,i)=>{let d=new Date(`${newDate(i)}T12:00:00`);let matches=tasks.filter(t=>t.due===newDate(i));return `<section class="timeline-day"><header>${new Intl.DateTimeFormat('en-GB',{weekday:'short'}).format(d)}<b>${d.getDate()}</b></header>${matches.map(t=>`<div class="timeline-pill" data-detail="${escapeHTML(t.id)}">${escapeHTML(t.title)}</div>`).join('')}${!matches.length?'<div style="font-size:10px;color:var(--faint);margin-top:14px">Open space</div>':''}</section>`}).join('')}</div>`;}
  function renderReports(){const c=count(),pct=c.all?Math.round(c.done/c.all*100):0;const projects=mode==='demo'?Object.keys(projectDescriptions):[...new Set(tasks.map(t=>t.project))];return `<div class="report-grid"><article class="report-card"><div class="section-eyebrow">COMPLETION RATE</div><div class="report-big">${pct}%</div><p>${c.done} tasks complete across ${c.all} ${mode==='demo'?'demo':'local'} tasks.</p><div class="report-line"><span>Progress</span><div><span style="width:${pct}%"></span></div><b>${pct}%</b></div></article><article class="report-card"><div class="section-eyebrow">PORTFOLIO HEALTH</div><div class="report-big">${projects.length.toString().padStart(2,'0')}</div><p>Projects in progress. All enterprise report types should eventually be freely accessible.</p>${projects.map(p=>{let a=tasks.filter(t=>t.project===p);let n=Math.round(a.filter(t=>t.status==='done').length/(a.length||1)*100);return `<div class="report-line"><span>${escapeHTML(p)}</span><div><span style="width:${n}%"></span></div><b>${n}%</b></div>`}).join('')}</article></div>`;}
  function renderAutomations(){return `<div class="settings-list">${[['Recurring work','Automatic task generation from repeat rules.','Planned'],['Rules & triggers','When status, date or project changes, take a defined action.','Planned'],['Webhooks','Connect external services through auditable, permission-controlled events.','Planned'],['MCP actions','Let authorized AI assistants work with tasks through typed tools.','Planned']].map(([n,d,s])=>`<article class="automation-card"><div><h3>${n}</h3><p>${d}</p><span class="status-tag">${s.toUpperCase()} · NOT IMPLEMENTED</span></div><button data-preview-feature="${n}">Preview</button></article>`).join('')}</div>`;}
  function renderSettings(){return `<div class="settings-list"><article class="settings-card"><h3>Appearance</h3><p>Choose between ink-dark and parchment-light workspaces. The approved visual identity remains consistent in both.</p><div class="settings-actions"><button data-theme="dark">Ink dark</button><button data-theme="light">Parchment light</button></div></article><article class="settings-card"><h3>Your data</h3><p>${mode==='live'?'Tasks are stored in local SQLite and changed through the Rust CLI using a loopback-only development bridge. No cloud or account is required. Safe backups and production authentication are still planned.':mode==='android-local'?nativeCanary.selected?'Debug native canary: Rust SQLite supplies the normal task list. The original WebView tasks remain stored separately for explicit rollback. No account or network.':'Offline Android shell: tasks live only in the embedded WebView local storage on this device. No account, network or remote server is involved. Native SQLite/Rust integration and safe backups are still needed.':'Static demo tasks are stored only in this browser using localStorage. Nothing is sent to a server.'}</p>${mode==='android-local'?'<div class="settings-actions"><button type="button" id="exportAndroidBackup">Export JSON backup</button><button type="button" id="importAndroidBackup">Restore backup</button></div><p class="settings-hint">Experimental Rust SQLite safety copy: a separate, private on-device copy. The current task store remains WebView-based while we validate migration.</p><div class="settings-actions"><button type="button" id="saveNativeVault">Save native safety copy</button><button type="button" id="recoverNativeVault">Recover native safety copy</button></div><p class="settings-hint">Migration preview: stage a copy of your current tasks into SHIORI’s canonical Rust/SQLite format. Your current tasks remain in WebView storage; this does not enable native editing or sync.</p><div class="settings-actions"><button type="button" id="stageCanonicalShadow">Stage Rust migration preview</button><button type="button" id="auditCanonicalShadow">Audit staged Rust preview</button><button type="button" id="auditNativeMigrationParity">Verify migration field parity</button></div><p class="settings-hint">Debug-only native source pilot: requires verified field parity and a separate rollback snapshot. Returning to legacy tasks rechecks both the vault and migration source; mismatched records block the switch. Native-only edits are NOT merged into legacy tasks.</p><div class="settings-actions"><button type="button" id="activateNativeCanary">Enable Rust task source · debug only</button><button type="button" id="rollbackNativeCanary">Verify and return to Android tasks</button>'+(window.shioriNativeDebugCanaryAvailable===true?'<button type="button" id="resumeInterruptedNativeCanary">Verify and resume interrupted cutover</button>':'')+'</div><p class="settings-hint">Experimental native Rust task editor: creates a third, independent SQLite working copy. Tasks added or changed there do not appear in the normal Android list. Use it only to test the native engine.</p><div class="settings-actions"><button type="button" id="openNativeWorkingCopy">Open native Rust task workspace</button><button type="button" id="exportNativeWorkingCopy">Export native SQLite backup</button><button type="button" id="recoverNativeSQLite">Stage isolated SQLite recovery</button><button type="button" id="inspectNativeSQLiteRecovery">Inspect recovered preview</button></div>'+nativePreviewRender()+'':''}${mode==='demo'?'<div class="settings-actions"><button id="resetDemo">Reset demo tasks</button></div>':''}</article><article class="settings-card"><h3>Official SHIORI visual identity</h3><p>The ink-brush 栞 and modern Latin wordmark carry across launch, splash and publication assets.</p><img src="assets/shiori-logo.webp" alt="Approved SHIORI plum and black ink calligraphic logo" style="width:100%;max-width:460px;border-radius:10px;margin-top:14px" /></article><article class="settings-card"><h3>AI-optional by design</h3><p>No embedded model, no inference bills, and no required provider account. A permission-controlled MCP server is on the roadmap, not connected in this prototype.</p></article></div>`;}
  function renderUpcoming(){let upcoming=[...tasks].filter(t=>t.status!=='done' && t.due>=newDate()).sort((a,b)=>a.due.localeCompare(b.due)).slice(0,3);$('#upcoming').innerHTML=upcoming.map(t=>{const d=new Date(`${t.due}T12:00:00`);return `<div class="upcoming-item"><div class="upcoming-date"><div>${d.getDate()}<small>${new Intl.DateTimeFormat('en-GB',{month:'short'}).format(d).toUpperCase()}</small></div></div><div class="upcoming-main"><b>${escapeHTML(t.title)}</b><span>${escapeHTML(t.project)} · ${t.mins==null?'No estimate':t.mins+' min estimate'}</span></div></div>`}).join('');}
  function setView(next){if(next!=='inbox')nativeReadOnly.active=false;view=next;query='';$('#searchInput').value='';$$('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));const v=views[view];$('#breadcrumbCurrent').textContent=v[0];$('#pageTitle').innerHTML=escapeHTML(v[1].replace(/\.$/,''))+'<span class="period">.</span>';$('#pageSubtitle').textContent=v[2];$('#sectionEyebrow').textContent=v[3];$('#sectionTitle').textContent=v[4];const regular=['today','attention','inbox','board'];$('#hero').style.display=view==='today'?'flex':'none';$('#stats').style.display=view==='today'||view==='reports'?'grid':'none';$('.quick-search').style.display=regular.includes(view)?'flex':'none';$('#filterButton').style.display=regular.includes(view)?'flex':'none';$('.sort-control').style.display=regular.includes(view)?'inline-flex':'none';$('#viewSwitch').style.display=regular.includes(view)?'flex':'none';$('#viewSwitch').innerHTML=view==='board'?`${icon('check-circle')} List`:`${icon('columns')} Board`;render();closeSidebar();window.scrollTo({top:0,behavior:'instant'});}
  function render(){
    // Read-only Rust preview never mixes native rows into legacy statistics.
    // The explicitly selected canary is instead the task source for all views.
    renderStats();renderUpcoming();renderCalendar();
    document.querySelectorAll('[data-add]').forEach(button=>{
      button.disabled=nativeCanary.pending||nativeReadOnly.active||
        (nativeCanary.selected&&!nativeCanary.active);
      button.title=button.disabled?'Task source is read-only or unavailable':'';
    });
    if(nativeCanary.pending&&view!=='settings'){
      $('#mainData').innerHTML='<section class="native-readonly-banner" role="status"><strong>Verifying native cutover</strong><p>Legacy writes are temporarily paused while backup and parity checks finish.</p></section>';
      return;
    }
    if(nativeCanary.selected&&!nativeCanary.active&&view!=='settings'){
      $('#mainData').innerHTML='<section class="native-readonly-banner" role="alert"><strong>Rust task source unavailable</strong><p>'+
        escapeHTML(nativeCanary.error||'Loading verified native SQLite records…')+
        '</p><button type="button" data-view="settings">Open Settings to roll back</button></section>';
      return;
    }
    if(nativeReadOnly.active&&view==='inbox'){
      $('#sectionTitle').textContent='Rust tasks · read-only preview';
      $('#mainData').innerHTML=renderNativeReadOnly();
      return;
    }
    if(nativeCanary.active&&view==='inbox')$('#sectionTitle').textContent='Rust tasks · debug canary';
    if(view==='today')$('#sectionTitle').textContent=calendarSelected?`Tasks for ${displayDate(calendarSelected)}`:views.today[4];let html;if(view==='projects')html=renderProjects();else if(view==='board')html=renderBoard();else if(view==='timeline')html=renderTimeline();else if(view==='reports')html=renderReports();else if(view==='automations')html=renderAutomations();else if(view==='settings')html=renderSettings();else html=renderList();$('#mainData').innerHTML=(nativeCanary.active&&view!=='settings'?
      '<section class="native-canary-banner" role="status"><strong>Experimental Rust task source</strong>'+
      '<span>Debug-only · Legacy tasks preserved for rollback</span>'+
      '<button type="button" data-view="settings">Storage settings</button></section>':'')+html;
    $('#filterLabel').textContent=filter==='all'?'All priorities':filter[0].toUpperCase()+filter.slice(1);}
  function closeSidebar(){$('#sidebar').classList.remove('open');$('#scrim').classList.remove('open');}
  // Android's soft keyboard can steal focus while a dialog is open. Keep
  // one focus owner per modal so Back, X, Cancel and Escape all restore an
  // accessible control rather than leaving focus on a hidden input.
  const dialogOpeners={create:null,edit:null};
  function restoreDialogFocus(element){
    if(element && element.isConnected && !element.disabled &&
       !element.closest('[aria-hidden="true"]')){
      element.focus({preventScroll:true});
    }
  }
  function openModal(){
    if(nativeCanary.pending){toast('Storage verification in progress');return;}
    if(nativeCanary.selected&&!nativeCanary.active){toast('Rust task source unavailable · return to Settings');return;}
    if(nativeReadOnly.active){toast('Read-only source preview · return to Android tasks to edit');return;}
    if($('#taskModal').classList.contains('open'))return;
    dialogOpeners.create=document.activeElement;
    $('#taskModal').classList.add('open');
    $('#taskModal').setAttribute('aria-hidden','false');
    $('#taskForm').reset();$('#taskDue').value=newDate();
    setTimeout(()=>{
      if($('#taskModal').classList.contains('open'))$('#taskName').focus();
    },0);
  }
  function closeModal(){
    const modal=$('#taskModal'),wasOpen=modal.classList.contains('open');
    modal.classList.remove('open');modal.setAttribute('aria-hidden','true');
    if(wasOpen){
      if(modal.contains(document.activeElement))document.activeElement.blur();
      restoreDialogFocus(dialogOpeners.create);
    }
    dialogOpeners.create=null;
  }
  // Dismiss exactly one surface per Back/Escape press, topmost first.
  // The native Android Activity sends a cancelable shiori-native-back event;
  // this keeps the browser UI and Android system navigation in agreement.
  function dismissTopLayer(){
    if($('#editModal').classList.contains('open')){closeEdit();return true;}
    if($('#taskModal').classList.contains('open')){closeModal();return true;}
    if($('#detailOverlay').classList.contains('open')){
      $('#detailOverlay').classList.remove('open');activeDetail=null;return true;
    }
    if($('#sidebar').classList.contains('open')){closeSidebar();return true;}
    return false;
  }
  window.addEventListener('shiori-native-back',event=>{
    if(dismissTopLayer())event.preventDefault();
  });
  function closeEdit(){
    const modal=$('#editModal'),wasOpen=modal.classList.contains('open');
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden','true');
    if(wasOpen){
      if(modal.contains(document.activeElement))document.activeElement.blur();
      restoreDialogFocus(dialogOpeners.edit);
    }
    dialogOpeners.edit=null;
  }
  function openEdit(){
    const t=tasks.find(item=>item.id===activeDetail);
    if(!t || nativeCanary.pending || mode==='checking' || mode==='local-error') return;
    $('#editTaskName').value=t.title;
    $('#editTaskDescription').value=t.description||'';
    $('#editTaskProject').value=t.project;
    $('#editTaskPriority').value=t.priority;
    $('#editTaskDue').value=t.due||'';
    $('#editTaskEstimate').value=t.mins==null?'':String(t.mins);
    const assigneeSelect=$('#editTaskAssignee');
    assigneeSelect.replaceChildren(
      new Option('Me · local workspace','local'),
      new Option('Unassigned','')
    );
    if(t.assigneeId && t.assigneeId!=='local'){
      assigneeSelect.add(new Option('Other: '+t.assigneeId,t.assigneeId));
    }
    assigneeSelect.value=t.assigneeId||'';
    dialogOpeners.edit=document.activeElement;
    $('#editModal').classList.add('open');
    $('#editModal').setAttribute('aria-hidden','false');
    setTimeout(()=>{
      if($('#editModal').classList.contains('open'))$('#editTaskName').focus();
    },0);
  }
  async function removeTask(){
    if(nativeReadOnly.active||nativeCanary.pending)return;
    const t=tasks.find(item=>item.id===activeDetail);
    if(!t || mode==='checking' || mode==='local-error') return;
    if(!confirm('Move this task to deleted records?')) return;
    if(nativeCanary.selected){
      if(!await mutateNativeCanary({op:'delete',id:t.id,expected_version:t.version}))
        return;
    } else if(mode==='live'){
      try {
        await requestBridge('/api/tasks/'+encodeURIComponent(t.id)+'/delete',{expected_version:t.version});
      } catch(err){
        toast(err.message==='conflict'?'Task changed elsewhere — reload and review':'Could not delete task');
        return;
      }
    } else {
      tasks=tasks.filter(item=>item.id!==t.id);save();render();
    }
    $('#detailOverlay').classList.remove('open');
    activeDetail=null;
    toast('Task moved to deleted records');
  }
  function showDetail(id){const t=tasks.find(item=>item.id===id);if(!t)return;activeDetail=id;$('#detailPane').innerHTML=`<div class="detail-top"><span class="detail-label">TASK RECORD / ${escapeHTML(id.toUpperCase())}</span><button class="icon-button" data-close-detail aria-label="Close task details">${icon('x')}</button></div><h2>${escapeHTML(t.title)}</h2><p>${escapeHTML(t.description || 'No additional notes yet.')}</p><div class="detail-rows"><div class="detail-row"><span>Project</span><strong>${escapeHTML(t.project)}</strong></div><div class="detail-row"><span>Priority</span><strong>${escapeHTML(t.priority)}</strong></div><div class="detail-row"><span>Due</span><strong>${displayDate(t.due)}</strong></div><div class="detail-row"><span>Stage</span><strong>${t.status==='progress'?'In progress':t.status==='done'?'Completed':'To do'}</strong></div><div class="detail-row"><span>Estimated effort</span><strong>${t.mins==null?'Not estimated':t.mins+' min'}</strong></div><div class="detail-row"><span>Tags</span><strong>${escapeHTML((t.tags||[]).join(', '))||'None'}</strong></div></div><div class="detail-actions"><button class="secondary-btn" data-edit-task>Edit</button><button class="secondary-btn delete-task-btn" data-remove-task>Delete</button></div><button class="primary-btn detail-done" data-complete="${escapeHTML(id)}">${icon(t.status==='done'?'arrow':'check')} ${t.status==='done'?'Reopen task':'Mark complete'}</button><p style="margin-top:18px;font-size:10px">${mode==='live'?'Local SQLite task · Rust-backed changes':mode==='android-local'?(nativeCanary.selected?'Debug Rust/SQLite task · original Android tasks kept':'Offline Android task · stored on this device'):'Demo task · not connected to a backend'}.</p>`;$('#detailOverlay').classList.add('open');}
  async function toggleTask(id){
    if(nativeReadOnly.active||nativeCanary.pending)return;
    const t=tasks.find(x=>x.id===id);if(!t)return;
    const next=t.status==='done'?'todo':'done';
    if(mode==='local-error'||mode==='checking'){toast('Local database not ready');return;}
    if(nativeCanary.selected){
      if(!await mutateNativeCanary({
        op:'status',id,expected_version:t.version,
        status:next==='progress'?'in_progress':next
      }))return;
    }else if(mode==='live'){
      try {await requestBridge('/api/tasks/'+encodeURIComponent(id)+'/status',{status:next});}
      catch {toast('Could not save task status');return;}
    } else {t.status=next;save();render();}
    if($('#detailOverlay').classList.contains('open'))showDetail(id);
    toast(next==='done'?'Task completed':'Task reopened');
  }
  $('#homeCalendarToggle').addEventListener('click',()=>{
    calendarExpanded = !calendarExpanded;
    try { localStorage.setItem('shiori-calendar-expanded', String(calendarExpanded)); } catch {}
    renderCalendar();
  });
  // Modal exit controls use direct handlers instead of relying solely on
  // document-level delegation. This remains responsive under Android WebView,
  // when tapping icons inside a nested SVG or the on-screen keyboard is open.
  document.querySelectorAll('#taskModal [data-close-modal]').forEach(button=>{
    button.addEventListener('click',event=>{
      event.preventDefault();
      event.stopPropagation();
      closeModal();
    });
  });
  document.querySelectorAll('#editModal [data-close-edit]').forEach(button=>{
    button.addEventListener('click',event=>{
      event.preventDefault();
      event.stopPropagation();
      closeEdit();
    });
  });
  document.addEventListener('click',e=>{
    const monthButton=e.target.closest('[data-calendar-shift]');
    if(monthButton){calendarMonth.setMonth(calendarMonth.getMonth()+Number(monthButton.dataset.calendarShift));renderCalendar();return;}
    if(e.target.closest('[data-calendar-today]')){calendarSelected=null;calendarMonth.setTime(Date.now());calendarMonth.setDate(1);calendarMonth.setHours(12,0,0,0);render();return;}
    const dayButton=e.target.closest('[data-calendar-date]');
    if(dayButton){calendarSelected=dayButton.dataset.calendarDate;render();return;}
    const nav=e.target.closest('[data-view]');if(nav){setView(nav.dataset.view);return;}
    const add=e.target.closest('[data-add]');if(add){openModal();return;}
    const complete=e.target.closest('[data-complete]');if(complete){toggleTask(complete.dataset.complete);return;}
    const detail=e.target.closest('[data-detail]');if(detail){showDetail(detail.dataset.detail);return;}
    if(e.target.closest('[data-edit-task]')){openEdit();return;}
    if(e.target.closest('[data-remove-task]')){removeTask();return;}
    if(e.target.closest('[data-close-edit]')){closeEdit();return;}
    const project=e.target.closest('[data-project]');if(project){setView('inbox');$('#searchInput').value=project.dataset.project;query=project.dataset.project;render();return;}
    // The HTML root also has data-theme; only theme buttons can change it.
    const theme=e.target.closest('button[data-theme]');if(theme){setTheme(theme.dataset.theme);return;}
    const close=e.target.closest('[data-close-modal]');if(close){closeModal();return;}
    if(e.target.closest('[data-close-detail]')){$('#detailOverlay').classList.remove('open');return;}
    if(e.target.id==='saveNativeVault'&&mode==='android-local'){
      window.location.href='shiori-vault://save';return;
    }
    if(e.target.id==='recoverNativeVault'&&mode==='android-local'){
      window.location.href='shiori-vault://recover';return;
    }
    if(e.target.id==='stageCanonicalShadow'&&mode==='android-local'){
      window.location.href='shiori-vault://stage';return;
    }
    if(e.target.id==='auditCanonicalShadow'&&mode==='android-local'){
      window.location.href='shiori-vault://audit';return;
    }
    if(e.target.id==='auditNativeMigrationParity'&&mode==='android-local'){
      window.location.href='shiori-vault://migration-parity';return;
    }
    if(e.target.id==='activateNativeCanary'&&mode==='android-local'){
      window.location.href='shiori-vault://native-activate';return;
    }
    if(e.target.id==='rollbackNativeCanary'&&mode==='android-local'){
      window.location.href='shiori-vault://native-rollback';return;
    }
    if(e.target.id==='resumeInterruptedNativeCanary'&&mode==='android-local'&&
       window.shioriNativeDebugCanaryAvailable===true){
      window.location.href='shiori-vault://native-resume';return;
    }
    if(e.target.id==='openNativeWorkingCopy'&&mode==='android-local'){
      window.location.href='shiori-vault://working';return;
    }
    if(e.target.id==='exportNativeWorkingCopy'&&mode==='android-local'){
      window.location.href='shiori-vault://native-export';return;
    }
    if(e.target.id==='recoverNativeSQLite'&&mode==='android-local'){
      window.location.href='shiori-vault://native-recover';return;
    }
    if(e.target.id==='inspectNativeSQLiteRecovery'&&mode==='android-local'){
      window.location.href='shiori-vault://native-inspect';return;
    }
    if(e.target.id==='showNativeReadOnly'&&mode==='android-local'){
      openNativeReadOnly();return;
    }
    if(e.target.id==='closeNativeReadOnly'){
      nativeReadOnly.active=false;
      setView('inbox');return;
    }
    const sourcePage=e.target.closest('[data-native-page]');
    if(sourcePage && nativeReadOnly.active){
      const n=sourcePage.dataset.nativePage==='next'?1:-1;
      nativeReadOnly.page=Math.max(0,nativeReadOnly.page+n);
      render();return;
    }
    const nativeButton=e.target.closest('[data-native-op]');
    if(nativeButton&&mode==='android-local'){
      const op=nativeButton.dataset.nativeOp;
      if(op==='refresh'){nativePreviewRefresh();return;}
      if(op==='rename-cancel'){nativeWorking.editId=null;nativePreviewUpdate();return;}
      if(op==='delete-cancel'){nativeWorking.deleteId=null;nativePreviewUpdate();return;}
      const task=nativeWorking.items.find(item=>item.id===nativeButton.dataset.nativeId);
      if(!task || nativeWorking.busy)return;
      if(op==='rename'){nativeWorking.editId=task.id;nativeWorking.deleteId=null;nativePreviewUpdate();return;}
      if(op==='delete'){nativeWorking.deleteId=task.id;nativeWorking.editId=null;nativePreviewUpdate();return;}
      if(op==='rename-save'){
        const field=$('#nativeWorkingRename');
        const title=field?field.value.trim():'';
        if(!title||title.length>120){nativeWorking.error='Enter a title of 1–120 characters';nativePreviewUpdate();return;}
        nativePreviewMutate({op:'rename',id:task.id,title,expected_version:task.version});
        return;
      }
      if(op==='status'){
        nativePreviewMutate({
          op:'status',id:task.id,expected_version:task.version,
          status:task.status==='done'?'todo':'done'
        });return;
      }
      if(op==='delete-confirm'){
        nativePreviewMutate({op:'delete',id:task.id,expected_version:task.version});
        return;
      }
    }

    if(e.target.id==='exportAndroidBackup'&&mode==='android-local'){
      window.location.href='shiori-backup://export';return;
    }
    if(e.target.id==='importAndroidBackup'&&mode==='android-local'){
      window.location.href='shiori-backup://import';return;
    }
    if(e.target.closest('[data-preview-feature]')){toast('Feature preview only · planned for the roadmap');return;}
    if(e.target.id==='resetDemo'){if(mode!=='demo'){toast('Reset is only for demo records');return;}tasks=defaultTasks.map(t=>({...t, tags:[...t.tags]}));save();render();toast('Sample tasks restored');}
  });
  $('#editTaskForm').addEventListener('submit',async e=>{
    e.preventDefault();
    if(nativeReadOnly.active||nativeCanary.pending)return;
    const t=tasks.find(item=>item.id===activeDetail);
    if(!t || mode==='checking' || mode==='local-error') return;
    const estimateText=$('#editTaskEstimate').value.trim();
    const updated={
      title:$('#editTaskName').value.trim(),
      notes:$('#editTaskDescription').value,
      project:$('#editTaskProject').value.trim(),
      priority:$('#editTaskPriority').value,
      due_on:$('#editTaskDue').value||null,
      estimate_minutes:estimateText===''?null:Number(estimateText),
      assignee_id:$('#editTaskAssignee').value||null,
      expected_version:t.version
    };
    if(!updated.title || !updated.project) return;
    if(nativeCanary.selected){
      if(!await mutateNativeCanary(Object.assign({op:'edit',id:t.id},updated)))
        return;
    }else if(mode==='live'){
      try{
        await requestBridge('/api/tasks/'+encodeURIComponent(t.id)+'/edit',updated);
      }catch(err){
        toast(err.message==='conflict'?'Task changed elsewhere — review and retry':'Could not save task edits');
        return;
      }
    }else{
      Object.assign(t,{
        title:updated.title,description:updated.notes,project:updated.project,
        priority:updated.priority,due:updated.due_on||'',mins:updated.estimate_minutes,
        assigneeId:updated.assignee_id,version:(t.version||1)+1
      });
      save();render();
    }
    closeEdit();
    showDetail(t.id);
    toast('Task updated');
  });
  document.addEventListener('submit',event=>{
    if(event.target.id!=='nativeWorkingCreate')return;
    event.preventDefault();
    if(mode!=='android-local'||nativeWorking.busy||nativeCanary.selected||nativeCanary.pending)return;
    const field=$('#nativeWorkingTitle');
    const title=field?field.value.trim():'';
    if(!title||title.length>120){
      nativeWorking.error='Enter a title of 1–120 characters';
      nativePreviewUpdate();
      return;
    }
    nativePreviewMutate({op:'create',title,project:'Native preview',priority:'medium'});
  });

  $('#taskForm').addEventListener('submit',async e=>{
    e.preventDefault();
    if(nativeReadOnly.active||nativeCanary.pending)return;
    const title=$('#taskName').value.trim();if(!title)return;
    if(mode==='local-error'||mode==='checking'){toast('Local database not ready');return;}
    const record={title,notes:$('#taskDescription').value.trim(),project:$('#taskProject').value,priority:$('#taskPriority').value,due_on:$('#taskDue').value||null,estimate_minutes:Number($('#taskEstimate').value)};
    if(nativeCanary.selected){
      const payload=Object.assign({op:'create'},record);
      if(!Number.isInteger(payload.estimate_minutes)||payload.estimate_minutes<1)
        payload.estimate_minutes=null;
      if(!await mutateNativeCanary(payload))return;
    }else if(mode==='live'){
      try {await requestBridge('/api/tasks',record);}
      catch {toast('Could not save task to SQLite');return;}
    } else {
      tasks.unshift({id:'u'+Date.now(),createdAt:new Date().toISOString(),title,description:record.notes,project:record.project,priority:record.priority,status:'todo',due:record.due_on||'',tags:['New'],mins:record.estimate_minutes});
      save();
    }
    closeModal();setView('inbox');
    toast(nativeCanary.selected?'Task saved to native Rust SQLite':
      mode==='live'?'Task saved to local SQLite':'Task added to your local demo');
  });
  $('#searchInput').addEventListener('input',e=>{query=e.target.value;nativeReadOnly.page=0;render();});
  $('#filterButton').addEventListener('click',()=>{const options=['all','urgent','high','medium','low'];filter=options[(options.indexOf(filter)+1)%options.length];nativeReadOnly.page=0;render();});
  $('#sortMode').addEventListener('change',e=>{
    if (!['focus','fifo','due','priority'].includes(e.target.value)) return;
    sortMode=e.target.value;
    if(!nativeCanary.selected){
      try {localStorage.setItem('shiori-demo-sort',sortMode);signalNativeVault();} catch {}
    }
    render();
  });
  $('#savedViewSelect').addEventListener('change',e=>{
    const chosenView=savedViews.find(item=>item.name===e.target.value);if(!chosenView)return;
    setView(chosenView.view);
    filter=chosenView.filter;
    sortMode=chosenView.sort;
    query=chosenView.query;
    $('#sortMode').value=sortMode;
    $('#searchInput').value=query;
    render();
  });
  $('#saveView').addEventListener('click',()=>{
    if(nativeCanary.selected||nativeCanary.pending){
      toast('Saved-view editing is paused during native source verification');return;
    }
    if(!['today','attention','inbox','board'].includes(view)){toast('Open a task list before saving a view');return;}
    const name=prompt('Name for this saved view (up to 40 characters):','My focus');
    if(name===null)return;
    const normalized=name.trim();
    if(!normalized || normalized.length>40){toast('Enter a name with up to 40 characters');return;}
    const entry={name:normalized,view,filter,sort:sortMode,query};
    const index=savedViews.findIndex(x=>x.name===normalized);
    if(index>=0)savedViews[index]=entry;
    else{
      if(savedViews.length>=30){toast('30 saved views maximum');return;}
      savedViews.push(entry);
    }
    persistSavedViews();
    $('#savedViewSelect').value=normalized;
    toast('Saved view: '+normalized);
  });
  $('#removeView').addEventListener('click',()=>{
    if(nativeCanary.selected){toast('Saved-view editing is disabled in debug canary');return;}
    const name=$('#savedViewSelect').value;if(!name){toast('Select a saved view first');return;}
    savedViews=savedViews.filter(v=>v.name!==name);
    persistSavedViews();
    toast('Saved view removed');
  });
  $('#viewSwitch').addEventListener('click',()=>setView(view==='board'?'today':'board'));
  $('#openSidebar').addEventListener('click',()=>{$('#sidebar').classList.add('open');$('#scrim').classList.add('open');});
  $('#closeSidebar').addEventListener('click',closeSidebar);$('#scrim').addEventListener('click',closeSidebar);
  $('#moreTab').addEventListener('click',()=>{$('#sidebar').classList.add('open');$('#scrim').classList.add('open');});
  $('#exploreButton').addEventListener('click',()=>setView('projects'));
  $('#notifyButton').addEventListener('click',()=>toast('Notifications will be added in a later milestone'));
  $('#taskModal').addEventListener('click',e=>{if(e.target.id==='taskModal')closeModal();});
  $('#editModal').addEventListener('click',e=>{if(e.target.id==='editModal')closeEdit();});
  $('#detailOverlay').addEventListener('click',e=>{if(e.target.id==='detailOverlay')$('#detailOverlay').classList.remove('open');});
  function setTheme(t){document.documentElement.setAttribute('data-theme',t);try{localStorage.setItem('shiori-theme',t)}catch{}$('#themeToggle').innerHTML=icon(t==='dark'?'sun':'moon');}
  $('#themeToggle').addEventListener('click',()=>setTheme(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark'));
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){
      if(dismissTopLayer())e.preventDefault();
      return;
    }
    const topModal=$('#editModal').classList.contains('open')?$('#editModal'):
      $('#taskModal').classList.contains('open')?$('#taskModal'):null;
    if(topModal){
      // Keep keyboard Tab inside the visible dialog; Android Back and the
      // explicit X/Cancel remain available regardless of screen height.
      if(e.key==='Tab'){
        const controls=Array.from(topModal.querySelectorAll(
          'button:not([disabled]),input:not([disabled]),textarea:not([disabled]),'+
          'select:not([disabled]),[tabindex]:not([tabindex="-1"])'
        )).filter(node=>node.getClientRects().length>0);
        if(controls.length){
          const first=controls[0],last=controls[controls.length-1];
          if(!topModal.contains(document.activeElement)){
            e.preventDefault();(e.shiftKey?last:first).focus();
          }else if(e.shiftKey&&document.activeElement===first){
            e.preventDefault();last.focus();
          }else if(!e.shiftKey&&document.activeElement===last){
            e.preventDefault();first.focus();
          }
        }
      }
      return; // No global shortcuts inside a dialog, even on a button.
    }
    if(e.target.matches('input,textarea,select'))return;
    if(e.key==='/'){e.preventDefault();$('#searchInput').focus();}
    if(e.key.toLowerCase()==='n' && !e.metaKey && !e.ctrlKey){openModal();}
  });
  let dragged=null;document.addEventListener('dragstart',e=>{if(nativeReadOnly.active||nativeCanary.pending)return;const card=e.target.closest('[data-drag]');if(card){dragged=card.dataset.drag;card.classList.add('dragging');}});document.addEventListener('dragend',()=>{$$('.dragging').forEach(c=>c.classList.remove('dragging'));dragged=null;});document.addEventListener('dragover',e=>{const col=e.target.closest('[data-drop]');if(col){e.preventDefault();col.classList.add('drag-over');}});document.addEventListener('dragleave',e=>{const col=e.target.closest('[data-drop]');if(col && !col.contains(e.relatedTarget))col.classList.remove('drag-over');});document.addEventListener('drop',e=>{if(nativeReadOnly.active||nativeCanary.pending)return;const col=e.target.closest('[data-drop]');if(col && dragged){
    e.preventDefault();const t=tasks.find(x=>x.id===dragged);
    if(t){
      if(mode==='local-error'||mode==='checking'){toast('Local database not ready');return;}
      const next=col.dataset.drop;
      if(nativeCanary.selected) {
        mutateNativeCanary({
          op:'status',id:t.id,expected_version:t.version,
          status:next==='progress'?'in_progress':next
        }).then(ok=>toast(ok?'Task stage saved in Rust SQLite':'Could not move task'));
      } else if(mode==='live') {
        requestBridge('/api/tasks/'+encodeURIComponent(t.id)+'/status',{status:next==='progress'?'in_progress':next})
          .then(()=>toast('Task stage saved to SQLite'))
          .catch(()=>toast('Could not save task stage'));
      } else {t.status=next;save();render();toast('Task moved to '+(next==='progress'?'In progress':next==='done'?'Completed':'To do'));}
    }
  }});
  const now=new Date();$('#dateLabel').textContent=new Intl.DateTimeFormat('en-GB',{weekday:'long',day:'numeric',month:'long'}).format(now).toUpperCase();$('#railDay').textContent=now.getDate();$('#railMonth').textContent=new Intl.DateTimeFormat('en-GB',{month:'long',year:'numeric'}).format(now).toUpperCase();$('#railWeekday').textContent=new Intl.DateTimeFormat('en-GB',{weekday:'long'}).format(now).toUpperCase();
  let pref='dark';try{pref=localStorage.getItem('shiori-theme')||'dark';}catch{}setTheme(pref);setView('today');
  if(mode==='android-local'){
    $('#footerMode').textContent='ANDROID · OFFLINE LOCAL DEVICE';
    $('#railMode').textContent='● OFFLINE DEVICE';
    $('.rail-footer').textContent='No account · on-device storage only';
  }
  bootstrapBridge();
})();
