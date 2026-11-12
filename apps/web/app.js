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
    attention:['My attention','Work that needs a look.','Local demo preview: due, urgent and in-progress tasks. Assignment tracking is not implemented.','ATTENTION','Needs your attention'],
    inbox:['Inbox','Nothing gets lost.','Capture first. Organize when you have time.','ALL TASKS','Your inbox'],
    projects:['Projects','Everything has its place.','See progress across all the work that matters.','YOUR PORTFOLIO','Project spaces'],
    board:['Board','A clearer view of progress.','Move work through the stages that make sense.','WORKFLOW','Kanban board'],
    timeline:['Timeline','See what comes next.','A lightweight view of your upcoming commitments.','PLANNING','Next seven days'],
    reports:['Reports','Progress without pressure.','Useful signals, with no productivity theatre.','INSIGHTS','Workspace report'],
    automations:['Automations','Make routine work lighter.','Automation belongs to the user, not a subscription tier.','WORKFLOWS','Automation centre'],
    settings:['Settings','Made to be yours.','Control the workspace, your information and appearance.','PREFERENCES','Workspace settings']
  };
  let tasks;
  let mode = 'demo'; // demo, live (local Rust/SQLite), or local-error
  try {const saved = JSON.parse(localStorage.getItem('shiori-demo-tasks') || 'null');tasks = Array.isArray(saved) ? saved : defaultTasks;} catch {tasks = defaultTasks;}
  const fromStoredTask = (t) => ({
    id:t.id, title:t.title, description:t.notes||'', project:t.project,
    priority:t.priority, status:t.status==='in_progress'?'progress':t.status,
    due:t.due_on||'', tags:[], mins:t.estimate_minutes,
    createdAt:t.created_at, updatedAt:t.updated_at, version:t.version
  });
  async function reloadBridge() {
    const response = await fetch('/api/tasks', {cache:'no-store'});
    if(!response.ok) throw new Error('Local Rust storage could not be read');
    const payload = await response.json();
    if(!Array.isArray(payload.tasks)) throw new Error('Unexpected task response');
    tasks = payload.tasks.map(fromStoredTask);
    render();
  }
  async function requestBridge(path, data) {
    const response = await fetch(path, {
      method:'POST', headers:{'Content-Type':'application/json'},
      credentials:'same-origin', body:JSON.stringify(data)
    });
    if(!response.ok) throw new Error('Local task operation rejected');
    await reloadBridge();
  }
  async function bootstrapBridge() {
    if(location.protocol!=='http:' || !['localhost','127.0.0.1'].includes(location.hostname)) return;
    try {
      const response = await fetch('/api/health', {cache:'no-store'});
      if(!response.ok) return;
      const health = await response.json();
      if(health.mode!=='rust-sqlite' || health.protocol!==1) return;
      mode='live';
      tasks=[]; // Never silently modify demo records after discovering a live DB.
      $('#footerMode').textContent='LOCAL RUST / SQLITE · OFFLINE';
      $('#railMode').textContent='● LOCAL DATABASE';
      await reloadBridge();
    } catch {
      if(mode==='live') {
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
  let calendarExpanded = true;
  try { calendarExpanded = localStorage.getItem('shiori-calendar-expanded') !== 'false'; } catch {}
  let calendarSelected = null;
  const calendarMonth = new Date();
  calendarMonth.setDate(1);
  calendarMonth.setHours(12, 0, 0, 0);
  const dateKey = (year, month, day) => `${year}-${String(month + 1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
  let toastTimer;
  const save=()=>{try{localStorage.setItem('shiori-demo-tasks',JSON.stringify(tasks));}catch{}};
  const count=()=>({all:tasks.length,open:tasks.filter(t=>t.status!=='done').length,done:tasks.filter(t=>t.status==='done').length,today:tasks.filter(t=>t.status!=='done' && t.due<=newDate()).length});
  const chosen = () => {
    let result=tasks;
    if(view==='today') result=result.filter(t=>calendarSelected ? t.due===calendarSelected : (t.due<=newDate() || t.status==='progress'));
    if(view==='inbox') result=result.filter(t=>t.status!=='done');
    if(view==='attention') result=result.filter(t=>t.status!=='done' && ((t.due && t.due<=newDate()) || ['high','urgent'].includes(t.priority) || t.status==='progress'));
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
  function renderStats(){const c=count();const cards=[['Open tasks',c.open,'across all projects','check-circle'],['Due today',c.today,'needs your attention','calendar'],['Completed',c.done,'small wins add up','check'],['Workspaces',4,'sample project spaces','folder']];$('#stats').innerHTML=cards.map(([label,value,note,glyph])=>`<article class="stat-card"><div class="stat-head">${escapeHTML(label)}${icon(glyph)}</div><div class="stat-value">${value.toString().padStart(2,'0')}</div><div class="stat-foot">${escapeHTML(note)}</div></article>`).join('');const today=tasks.filter(t=>t.due<=newDate());const pct=today.length?Math.round(today.filter(t=>t.status==='done').length/today.length*100):0;$('#momentumNumber').innerHTML=`${pct}<span>%</span>`;$('#momentumFill').style.width=pct+'%';$('#navTodayCount').textContent=String(c.today).padStart(2,'0');$('#navAttentionCount').textContent=String(tasks.filter(t=>t.status!=='done' && ((t.due && t.due<=newDate()) || ['high','urgent'].includes(t.priority) || t.status==='progress')).length).padStart(2,'0');}
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
  function renderList(){const arr=chosen();const note=view==='attention'?'<div class="attention-note">Attention · due, high-priority and in-progress tasks. Assignment tracking and remote sync are not available yet.</div>':'';if(!arr.length)return note+'<div class="empty-state">'+icon('check-circle')+'<h3>A little breathing room.</h3><p>Nothing matches this view. Try another filter or create a task.</p></div>';return note+`<div class="task-list">${arr.map(t=>`<article class="task-row"><button class="task-complete ${t.status==='done'?'done':''}" aria-label="${t.status==='done'?'Reopen':'Complete'} ${escapeHTML(t.title)}" data-complete="${escapeHTML(t.id)}">${t.status==='done'?icon('check'):''}</button><div class="task-info" data-detail="${escapeHTML(t.id)}"><div class="task-title ${t.status==='done'?'done':''}">${escapeHTML(t.title)}</div><div class="task-meta"><span class="project-chip">${escapeHTML(t.project)}</span><span class="task-meta-dot"></span><span>${escapeHTML((t.tags||[]).slice(0,2).join(' / '))}</span></div></div><div class="task-end"><span class="priority-dot ${t.priority}" title="${t.priority} priority"></span><span class="due-chip">${icon('calendar')}${displayDate(t.due)}</span>${icon('chevron').replace('<svg ', '<svg class="row-arrow" data-detail="'+escapeHTML(t.id)+'" ')}</div></article>`).join('')}</div>`;}
  function renderBoard(){const statuses=[['todo','To do'],['progress','In progress'],['done','Completed']];const list=chosen();return `<div class="board">${statuses.map(([status,label])=>{const group=list.filter(t=>t.status===status);return `<section class="board-col" data-drop="${status}"><div class="board-head"><b>${label}</b><span class="board-count">${group.length}</span></div>${group.map(t=>`<article class="board-card" draggable="true" data-drag="${escapeHTML(t.id)}" data-detail="${escapeHTML(t.id)}"><b>${escapeHTML(t.title)}</b><div class="task-meta"><span class="project-chip">${escapeHTML(t.project)}</span><span>${displayDate(t.due)}</span></div></article>`).join('')}${group.length?'':'<div style="font-size:11px;color:var(--faint);padding:8px">Drop tasks here</div>'}</section>`}).join('')}</div>`;}
  function renderProjects(){const projects=mode==='demo'?Object.keys(projectDescriptions):[...new Set(tasks.map(t=>t.project))];return `<div class="project-grid">${projects.map(p=>{const all=tasks.filter(t=>t.project===p),done=all.filter(t=>t.status==='done').length,pct=all.length?Math.round(done/all.length*100):0;return `<article class="project-card" data-project="${escapeHTML(p)}"><div class="project-card-top"><span>${projectGlyphs[p]||'◇'}</span><span>${all.length} tasks ${icon('chevron')}</span></div><h3>${escapeHTML(p==='Core'?'Core platform':p==='Interface'?'Interface design':p)}</h3><p>${escapeHTML(projectDescriptions[p]||'Local project')}</p><div class="project-progress"><span>${done} of ${all.length} completed</span><strong>${pct}%</strong></div><div class="project-bar"><div style="width:${pct}%"></div></div></article>`}).join('')}</div>`;}
  function renderTimeline(){return `<div class="timeline">${Array.from({length:7},(_,i)=>{let d=new Date(`${newDate(i)}T12:00:00`);let matches=tasks.filter(t=>t.due===newDate(i));return `<section class="timeline-day"><header>${new Intl.DateTimeFormat('en-GB',{weekday:'short'}).format(d)}<b>${d.getDate()}</b></header>${matches.map(t=>`<div class="timeline-pill" data-detail="${escapeHTML(t.id)}">${escapeHTML(t.title)}</div>`).join('')}${!matches.length?'<div style="font-size:10px;color:var(--faint);margin-top:14px">Open space</div>':''}</section>`}).join('')}</div>`;}
  function renderReports(){const c=count(),pct=c.all?Math.round(c.done/c.all*100):0;const projects=mode==='demo'?Object.keys(projectDescriptions):[...new Set(tasks.map(t=>t.project))];return `<div class="report-grid"><article class="report-card"><div class="section-eyebrow">COMPLETION RATE</div><div class="report-big">${pct}%</div><p>${c.done} tasks complete across ${c.all} ${mode==='demo'?'demo':'local'} tasks.</p><div class="report-line"><span>Progress</span><div><span style="width:${pct}%"></span></div><b>${pct}%</b></div></article><article class="report-card"><div class="section-eyebrow">PORTFOLIO HEALTH</div><div class="report-big">04</div><p>Projects in progress. All enterprise report types should eventually be freely accessible.</p>${projects.map(p=>{let a=tasks.filter(t=>t.project===p);let n=Math.round(a.filter(t=>t.status==='done').length/(a.length||1)*100);return `<div class="report-line"><span>${escapeHTML(p)}</span><div><span style="width:${n}%"></span></div><b>${n}%</b></div>`}).join('')}</article></div>`;}
  function renderAutomations(){return `<div class="settings-list">${[['Recurring work','Automatic task generation from repeat rules.','Planned'],['Rules & triggers','When status, date or project changes, take a defined action.','Planned'],['Webhooks','Connect external services through auditable, permission-controlled events.','Planned'],['MCP actions','Let authorized AI assistants work with tasks through typed tools.','Planned']].map(([n,d,s])=>`<article class="automation-card"><div><h3>${n}</h3><p>${d}</p><span class="status-tag">${s.toUpperCase()} · NOT IMPLEMENTED</span></div><button data-preview-feature="${n}">Preview</button></article>`).join('')}</div>`;}
  function renderSettings(){return `<div class="settings-list"><article class="settings-card"><h3>Appearance</h3><p>Choose between ink-dark and parchment-light workspaces. The approved visual identity remains consistent in both.</p><div class="settings-actions"><button data-theme="dark">Ink dark</button><button data-theme="light">Parchment light</button></div></article><article class="settings-card"><h3>Your data</h3><p>This concept keeps sample task changes inside your browser using localStorage. Nothing is sent to a server. Production SHIORI will add local databases, secure backups and portable export formats.</p><div class="settings-actions"><button id="resetDemo">Reset demo tasks</button></div></article><article class="settings-card"><h3>Official SHIORI visual identity</h3><p>The ink-brush 栞 and modern Latin wordmark carry across launch, splash and publication assets.</p><img src="assets/shiori-logo.webp" alt="Approved SHIORI plum and black ink calligraphic logo" style="width:100%;max-width:460px;border-radius:10px;margin-top:14px" /></article><article class="settings-card"><h3>AI-optional by design</h3><p>No embedded model, no inference bills, and no required provider account. A permission-controlled MCP server is on the roadmap, not connected in this prototype.</p></article></div>`;}
  function renderUpcoming(){let upcoming=[...tasks].filter(t=>t.status!=='done' && t.due>=newDate()).sort((a,b)=>a.due.localeCompare(b.due)).slice(0,3);$('#upcoming').innerHTML=upcoming.map(t=>{const d=new Date(`${t.due}T12:00:00`);return `<div class="upcoming-item"><div class="upcoming-date"><div>${d.getDate()}<small>${new Intl.DateTimeFormat('en-GB',{month:'short'}).format(d).toUpperCase()}</small></div></div><div class="upcoming-main"><b>${escapeHTML(t.title)}</b><span>${escapeHTML(t.project)} · ${t.mins==null?'No estimate':t.mins+' min estimate'}</span></div></div>`}).join('');}
  function setView(next){view=next;query='';$('#searchInput').value='';$$('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));const v=views[view];$('#breadcrumbCurrent').textContent=v[0];$('#pageTitle').innerHTML=escapeHTML(v[1].replace(/\.$/,''))+'<span class="period">.</span>';$('#pageSubtitle').textContent=v[2];$('#sectionEyebrow').textContent=v[3];$('#sectionTitle').textContent=v[4];const regular=['today','attention','inbox','board'];$('#hero').style.display=view==='today'?'flex':'none';$('#stats').style.display=view==='today'||view==='reports'?'grid':'none';$('.quick-search').style.display=regular.includes(view)?'flex':'none';$('#filterButton').style.display=regular.includes(view)?'flex':'none';$('.sort-control').style.display=regular.includes(view)?'inline-flex':'none';$('#viewSwitch').style.display=regular.includes(view)?'flex':'none';$('#viewSwitch').innerHTML=view==='board'?`${icon('check-circle')} List`:`${icon('columns')} Board`;render();closeSidebar();window.scrollTo({top:0,behavior:'instant'});}
  function render(){renderStats();renderUpcoming();renderCalendar();if(view==='today')$('#sectionTitle').textContent=calendarSelected?`Tasks for ${displayDate(calendarSelected)}`:views.today[4];let html;if(view==='projects')html=renderProjects();else if(view==='board')html=renderBoard();else if(view==='timeline')html=renderTimeline();else if(view==='reports')html=renderReports();else if(view==='automations')html=renderAutomations();else if(view==='settings')html=renderSettings();else html=renderList();$('#mainData').innerHTML=html;$('#filterLabel').textContent=filter==='all'?'All priorities':filter[0].toUpperCase()+filter.slice(1);}
  function closeSidebar(){$('#sidebar').classList.remove('open');$('#scrim').classList.remove('open');}
  function openModal(){$('#taskModal').classList.add('open');$('#taskModal').setAttribute('aria-hidden','false');$('#taskForm').reset();setTimeout(()=>$('#taskName').focus(),0);}
  function closeModal(){$('#taskModal').classList.remove('open');$('#taskModal').setAttribute('aria-hidden','true');}
  function showDetail(id){const t=tasks.find(item=>item.id===id);if(!t)return;activeDetail=id;$('#detailPane').innerHTML=`<div class="detail-top"><span class="detail-label">TASK RECORD / ${escapeHTML(id.toUpperCase())}</span><button class="icon-button" data-close-detail aria-label="Close task details">${icon('x')}</button></div><h2>${escapeHTML(t.title)}</h2><p>${escapeHTML(t.description || 'No additional notes yet.')}</p><div class="detail-rows"><div class="detail-row"><span>Project</span><strong>${escapeHTML(t.project)}</strong></div><div class="detail-row"><span>Priority</span><strong>${escapeHTML(t.priority)}</strong></div><div class="detail-row"><span>Due</span><strong>${displayDate(t.due)}</strong></div><div class="detail-row"><span>Stage</span><strong>${t.status==='progress'?'In progress':t.status==='done'?'Completed':'To do'}</strong></div><div class="detail-row"><span>Estimated effort</span><strong>${t.mins==null?'Not estimated':t.mins+' min'}</strong></div><div class="detail-row"><span>Tags</span><strong>${escapeHTML((t.tags||[]).join(', '))||'None'}</strong></div></div><button class="primary-btn detail-done" data-complete="${id}">${icon(t.status==='done'?'arrow':'check')} ${t.status==='done'?'Reopen task':'Mark complete'}</button><p style="margin-top:18px;font-size:10px">${mode==='live'?'Local SQLite task · Rust-backed changes':'Demo task · not connected to a backend'}.</p>`;$('#detailOverlay').classList.add('open');}
  async function toggleTask(id){
    const t=tasks.find(x=>x.id===id);if(!t)return;
    const next=t.status==='done'?'todo':'done';
    if(mode==='local-error'){toast('Local database unavailable');return;}
    if(mode==='live'){
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
    const project=e.target.closest('[data-project]');if(project){setView('inbox');$('#searchInput').value=project.dataset.project;query=project.dataset.project;render();return;}
    const theme=e.target.closest('[data-theme]');if(theme){setTheme(theme.dataset.theme);return;}
    const close=e.target.closest('[data-close-modal]');if(close){closeModal();return;}
    if(e.target.closest('[data-close-detail]')){$('#detailOverlay').classList.remove('open');return;}
    if(e.target.closest('[data-preview-feature]')){toast('Feature preview only · planned for the roadmap');return;}
    if(e.target.id==='resetDemo'){if(mode!=='demo'){toast('Reset is only for demo records');return;}tasks=defaultTasks.map(t=>({...t, tags:[...t.tags]}));save();render();toast('Sample tasks restored');}
  });
  $('#taskForm').addEventListener('submit',async e=>{
    e.preventDefault();
    const title=$('#taskName').value.trim();if(!title)return;
    if(mode==='local-error'){toast('Local database unavailable');return;}
    const record={title,notes:$('#taskDescription').value.trim(),project:$('#taskProject').value,priority:$('#taskPriority').value,due_on:newDate(),estimate_minutes:30};
    if(mode==='live'){
      try {await requestBridge('/api/tasks',record);}
      catch {toast('Could not save task to SQLite');return;}
    } else {
      tasks.unshift({id:'u'+Date.now(),createdAt:new Date().toISOString(),title,description:record.notes,project:record.project,priority:record.priority,status:'todo',due:record.due_on,tags:['New'],mins:30});
      save();
    }
    closeModal();setView('inbox');toast(mode==='live'?'Task saved to local SQLite':'Task added to your local demo');
  });
  $('#searchInput').addEventListener('input',e=>{query=e.target.value;render();});
  $('#filterButton').addEventListener('click',()=>{const options=['all','high','medium','low'];filter=options[(options.indexOf(filter)+1)%options.length];render();});
  $('#sortMode').addEventListener('change',e=>{
    if (!['focus','fifo','due','priority'].includes(e.target.value)) return;
    sortMode=e.target.value;
    try {localStorage.setItem('shiori-demo-sort',sortMode);} catch {}
    render();
  });
  $('#viewSwitch').addEventListener('click',()=>setView(view==='board'?'today':'board'));
  $('#openSidebar').addEventListener('click',()=>{$('#sidebar').classList.add('open');$('#scrim').classList.add('open');});
  $('#closeSidebar').addEventListener('click',closeSidebar);$('#scrim').addEventListener('click',closeSidebar);
  $('#moreTab').addEventListener('click',()=>{$('#sidebar').classList.add('open');$('#scrim').classList.add('open');});
  $('#exploreButton').addEventListener('click',()=>setView('projects'));
  $('#notifyButton').addEventListener('click',()=>toast('Notifications will be added in a later milestone'));
  $('#taskModal').addEventListener('click',e=>{if(e.target.id==='taskModal')closeModal();});
  $('#detailOverlay').addEventListener('click',e=>{if(e.target.id==='detailOverlay')$('#detailOverlay').classList.remove('open');});
  function setTheme(t){document.documentElement.setAttribute('data-theme',t);try{localStorage.setItem('shiori-theme',t)}catch{}$('#themeToggle').innerHTML=icon(t==='dark'?'sun':'moon');}
  $('#themeToggle').addEventListener('click',()=>setTheme(document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark'));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();closeSidebar();$('#detailOverlay').classList.remove('open');}if(e.target.matches('input,textarea,select'))return;if(e.key==='/'){e.preventDefault();$('#searchInput').focus();}if(e.key.toLowerCase()==='n' && !e.metaKey && !e.ctrlKey){openModal();}});
  let dragged=null;document.addEventListener('dragstart',e=>{const card=e.target.closest('[data-drag]');if(card){dragged=card.dataset.drag;card.classList.add('dragging');}});document.addEventListener('dragend',()=>{$$('.dragging').forEach(c=>c.classList.remove('dragging'));dragged=null;});document.addEventListener('dragover',e=>{const col=e.target.closest('[data-drop]');if(col){e.preventDefault();col.classList.add('drag-over');}});document.addEventListener('dragleave',e=>{const col=e.target.closest('[data-drop]');if(col && !col.contains(e.relatedTarget))col.classList.remove('drag-over');});document.addEventListener('drop',e=>{const col=e.target.closest('[data-drop]');if(col && dragged){
    e.preventDefault();const t=tasks.find(x=>x.id===dragged);
    if(t){
      if(mode==='local-error'){toast('Local database unavailable');return;}
      const next=col.dataset.drop;
      if(mode==='live') {
        requestBridge('/api/tasks/'+encodeURIComponent(t.id)+'/status',{status:next==='progress'?'in_progress':next})
          .then(()=>toast('Task stage saved to SQLite'))
          .catch(()=>toast('Could not save task stage'));
      } else {t.status=next;save();render();toast('Task moved to '+(next==='progress'?'In progress':next==='done'?'Completed':'To do'));}
    }
  }});
  const now=new Date();$('#dateLabel').textContent=new Intl.DateTimeFormat('en-GB',{weekday:'long',day:'numeric',month:'long'}).format(now).toUpperCase();$('#railDay').textContent=now.getDate();$('#railMonth').textContent=new Intl.DateTimeFormat('en-GB',{month:'long',year:'numeric'}).format(now).toUpperCase();$('#railWeekday').textContent=new Intl.DateTimeFormat('en-GB',{weekday:'long'}).format(now).toUpperCase();
  let pref='dark';try{pref=localStorage.getItem('shiori-theme')||'dark';}catch{}setTheme(pref);setView('today');bootstrapBridge();
})();
