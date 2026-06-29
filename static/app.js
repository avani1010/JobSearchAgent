const STATUSES = ["saved", "in_review", "applied", "interview", "offer", "rejected"];
const SCOLOR = {saved:"--saved", applied:"--applied", interview:"--interview", offer:"--offer", rejected:"--rejected"};
const TABS = ["scheduled", "shortlist", "review", "applications"];
let JOBS = [];
let TAB = 'shortlist';

const tabOf = j =>
    (j.source === 'greenhouse_scheduled' && j.status === 'saved') ? 'scheduled'
        : j.status === 'saved'      ? 'shortlist'
            : j.status === 'in_review'  ? 'review'
                :                             'applications';

function setTab(t){
    TAB = t;
    TABS.forEach(x => document.getElementById('tab-' + x).classList.toggle('active', x === t));
    render();
}

function toast(m){
    const t = document.getElementById('toast');
    t.textContent = m; t.classList.add('on');
    setTimeout(() => t.classList.remove('on'), 2200);
}
function esc(s){ return (s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function load(){
    JOBS = await (await fetch('/api/jobs')).json();
    render();
}

function render(){
    const q = document.getElementById('search').value.toLowerCase();

    // tab counts (all four — independent of the search box)
    const c = {scheduled:0, shortlist:0, review:0, applications:0};
    JOBS.forEach(j => c[tabOf(j)]++);
    TABS.forEach(k => document.getElementById('cnt-' + k).textContent = c[k]);

    // rows: active tab, then search
    const list = JOBS.filter(j => tabOf(j) === TAB
        && (j.title + j.company + j.location + j.status).toLowerCase().includes(q));

    // stats strip
    const counts = {total: JOBS.length}; STATUSES.forEach(s => counts[s] = 0);
    JOBS.forEach(j => counts[j.status] = (counts[j.status] || 0) + 1);
    const order = [["total","Total"], ...STATUSES.map(s => [s, s.replace('_',' ')])];
    document.getElementById('stats').innerHTML = order.map(([k,l]) =>
        `<div class="stat"><div class="n">${counts[k]||0}</div><div class="l">${l}</div></div>`).join('');

    // rows
    const tb = document.getElementById('rows'); tb.innerHTML = '';
    const emptyEl = document.getElementById('empty');
    emptyEl.style.display = list.length ? 'none' : 'block';
    emptyEl.textContent =
        TAB === 'scheduled' ? 'No new scheduled finds. The twice-daily Greenhouse watcher will drop new roles here.'
            : TAB === 'shortlist' ? 'No shortlisted jobs. Ask Claude to find and save some, or add one manually.'
                : TAB === 'review'    ? 'Nothing in review. Move shortlisted jobs to “in review” to bundle them for applying.'
                    :                       'No applications yet. Set a job’s status to applied to start tracking it here.';

    list.forEach((j, i) => {
        const col = getComputedStyle(document.documentElement).getPropertyValue(SCOLOR[j.status] || '--saved');
        const tr = document.createElement('tr');
        tr.className = 'row';
        tr.style.animationDelay = (i * 0.03) + 's';
        tr.innerHTML = `
      <td><div class="scorewrap" title="${esc((j.matched_keywords||[]).join(', '))||'no keyword overlap'}">
        <span class="score">${j.match_score}</span>
        <span class="bar"><i style="width:${j.match_score}%"></i></span></div></td>
      <td><div class="role">${esc(j.title)}</div><div class="company">${esc(j.company)}</div></td>
      <td class="loc">${esc(j.location)}</td>
      <td class="posted">${esc(j.posted)}</td>
      <td><select class="status" style="color:${col.trim()};border-color:${col.trim()}55"
            onchange="setStatus('${j.id}',this.value)">
        ${STATUSES.map(s => `<option value="${s}" ${s===j.status?'selected':''}>${s.replace('_',' ')}</option>`).join('')}</select></td>
      <td><textarea class="note" onblur="setNote('${j.id}',this.value)"
            placeholder="add a note…">${esc(j.note)}</textarea></td>
      <td><div class="acts">
        ${j.url ? `<a class="icon" href="${esc(j.url)}" target="_blank" rel="noopener">View ↗</a>` : ''}
        <button class="icon opt" onclick="optimise('${j.id}')">Tailor CV</button>
        <button class="icon" onclick="copyJD('${j.id}')">Copy JD</button>
        <button class="icon del" title="Dismiss" aria-label="Dismiss"
          onclick="removeJob('${j.id}','${esc(j.title).replace(/'/g,"\\'")}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line>
            </svg>
        </button>
      </div></td>`;
        tb.appendChild(tr);
    });
}

async function removeJob(id, title){
    const r = await fetch('/api/jobs/' + id, {method:'DELETE'});
    if(!r.ok){ toast('Dimiss failed'); return; }
    JOBS = JOBS.filter(j => j.id !== id);
    render();
    toast('Dismissed — ' + title);
}

async function copyJD(id){
    const d = await (await fetch('/api/jobs/' + id + '/jd')).json();
    if(!d.description){ toast('No JD stored for this job'); return; }
    await navigator.clipboard.writeText(d.description);
    toast('JD copied — ' + d.description.length + ' chars');
}

async function setStatus(id, status){
    const j = await (await fetch('/api/jobs/' + id, {method:'PATCH', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({status})})).json();
    Object.assign(JOBS.find(x => x.id === id), j);
    render();
    toast('Status → ' + status.replace('_',' '));
}

async function setNote(id, note){
    if((JOBS.find(x => x.id === id) || {}).note === note) return;
    await fetch('/api/jobs/' + id, {method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({note})});
    (JOBS.find(x => x.id === id) || {}).note = note;
    toast('Note saved');
}

async function optimise(id){
    const {prompt} = await (await fetch('/api/jobs/' + id + '/optimise')).json();
    await navigator.clipboard.writeText(prompt);
    toast('CV-tailoring prompt copied — paste into Claude');
}

function openAdd(){ document.getElementById('scrim').classList.add('on'); }
function closeAdd(){ document.getElementById('scrim').classList.remove('on'); }

async function submitAdd(){
    const body = {title:f('title'), company:f('company'), location:f('location'), url:f('url'), note:f('note')};
    if(!body.title || !body.company){ toast('Title and company are required'); return; }
    const r = await fetch('/api/jobs', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    if(r.status === 409){ toast('Already tracked'); return; }
    ['title','company','location','url','note'].forEach(k => document.getElementById('f-' + k).value = '');
    closeAdd(); await load(); toast('Job added');
}

const f = k => document.getElementById('f-' + k).value.trim();
document.getElementById('search').addEventListener('input', render);
document.getElementById('scrim').addEventListener('click', e => { if(e.target.id === 'scrim') closeAdd(); });
load();