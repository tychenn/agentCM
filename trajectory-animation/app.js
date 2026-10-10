/* Editable playback timing in seconds. Evidence and storyboard live in data.js. */
(() => {
  'use strict';
  const TIMING = { start: 2.3, plan: 1.3, tool: 1.15, observe: 1.8, compress: 3.3, merge: 5.0, finish: 3.0 };
  const D = window.TRAJECTORY_DEMO;
  if (!D) { document.getElementById('event-description').textContent = '数据未加载，请先运行 build_data.py 生成 data.js。'; return; }
  const $ = id => document.getElementById(id);
  const steps = new Map(D.steps.map(s => [s.id, s]));
  const higherGroups = D.higherGroups || [];
  const groups = new Map([...D.groups,...higherGroups].map(g => [g.id, g]));
  const events = [];
  let total = 0, actionNumber = 0;
  function append(type, fields = {}) { const duration = TIMING[type]; events.push({type, start:total, end:total+duration, duration, index:events.length, ...fields}); total += duration; }
  append('start');
  D.steps.forEach(step => {
    append('plan', {stepId:step.id, groupId:step.groupId});
    step.toolCalls.forEach((tool, toolIndex) => append('tool', {stepId:step.id, groupId:step.groupId, toolIndex, tool, actionNumber:++actionNumber}));
    append('observe', {stepId:step.id, groupId:step.groupId});
    D.compressions.filter(c => c.afterStep === step.id).forEach(c => append('compress', {groupId:c.groupId, stepId:step.id, label:c.label}));
    (D.merges||[]).filter(c=>c.afterStep===step.id).forEach(c=>append('merge',{groupId:c.groupId,stepId:step.id,label:c.label}));
  });
  append('finish');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let time = 0, playing = false, speed = 1, lastFrame = 0, dirty = true, settling = 0;
  let selectedStep = null, selectedGroup = null, lastDescriptionKey = '', manualOpen = new Set();
  let width = 900, height = 510, lastEventIndex = -1;
  const positions = new Map();
  const mergeOrigins = new Map();
  const clamp = (n, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));
  const mix = (a, b, t) => a + (b - a) * t;
  const ease = t => { t = clamp(t); return t * t * (3 - 2 * t); };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = seconds => `${String(Math.floor(seconds / 60)).padStart(2,'0')}:${String(Math.floor(seconds % 60)).padStart(2,'0')}`;
  const short = (text, max) => text.length > max ? text.slice(0, max-1) + '…' : text;
  const textCanvas = document.createElement('canvas').getContext('2d');
  function wrap(text, limit, fontSize = 11) {
    textCanvas.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`;
    const lines = []; let line = '';
    const tokens=text.match(/[A-Za-z0-9_/.]+|./gu)||[];
    for (const token of tokens) {
      if(textCanvas.measureText(line+token).width>limit&&line&&!/^[。，；、]$/.test(token)){lines.push(line);line=token;}
      else line+=token;
    }
    if (line) lines.push(line); return lines;
  }
  function svgText(text, x, y, size = 11, fill = '#536178', extra = '') { return `<text class="graph-text" x="${x}" y="${y}" font-size="${size}" fill="${fill}" ${extra}>${esc(text)}</text>`; }
  function eventAt(t) { if (t <= 0) return null; return events.find(e => t < e.end) || events.at(-1); }
  function stateAt(t) {
    const state = {started:t>0, arrived:new Set(), completed:new Set(), calls:new Map(), compressed:new Set(), folds:new Map(), merged:new Set(), mergeProgress:new Map(), event:eventAt(t), toolCount:0};
    for (const e of events) {
      if (t <= e.start) break;
      if (e.type === 'plan') state.arrived.add(e.stepId);
      if (e.type === 'tool') { state.calls.set(e.stepId, e.toolIndex+1); state.toolCount++; }
      if (e.type === 'observe') state.completed.add(e.stepId);
      if (e.type === 'compress') { state.compressed.add(e.groupId); state.folds.set(e.groupId, reduced ? 1 : ease((t-e.start)/(e.duration*.62))); }
      if(e.type==='merge'){state.merged.add(e.groupId);state.mergeProgress.set(e.groupId,reduced?1:ease((t-e.start)/(e.duration*.72)));}
    }
    for(const g of manualOpen){if(state.merged.has(g))state.mergeProgress.set(g,0);else state.folds.set(g,0);}
    state.baseGroups=D.groups.filter(g=>g.stepIds.some(id=>state.arrived.has(id)));
    state.visibleGroups=[...state.baseGroups];
    for(const parent of higherGroups){
      if(!(state.mergeProgress.get(parent.id)>0))continue;
      const first=state.visibleGroups.findIndex(g=>parent.memberGroupIds.includes(g.id));
      state.visibleGroups=state.visibleGroups.filter(g=>!parent.memberGroupIds.includes(g.id));
      state.visibleGroups.splice(first,0,parent);
    }
    state.visibleCount=new Set([...state.arrived].map(id=>representative(id,state).key)).size;
    return state;
  }
  function representative(stepId,state){
    const leafId=steps.get(stepId).groupId;
    const parent=higherGroups.find(g=>g.memberGroupIds.includes(leafId)&&(state.mergeProgress.get(g.id)||0)>.5);
    const owner=parent?.id||leafId;
    return {owner,key:parent||(state.folds.get(leafId)||0)>.5?`group:${owner}`:`step:${stepId}`};
  }
  function seek(t, resetInspection = true) {
    time = clamp(Number(t) || 0, 0, total);
    mergeOrigins.clear();
    if (resetInspection) { selectedStep = null; selectedGroup = null; manualOpen.clear(); }
    dirty = true; settling = reduced ? 1 : 45;
    if (time >= total) playing = false;
    refreshUI(stateAt(time));
  }
  function pause() { playing = false; dirty = true; refreshUI(stateAt(time)); }
  function play() { if (time >= total) seek(0); manualOpen.clear(); selectedStep = null; selectedGroup = null; playing = true; lastFrame = performance.now(); dirty = true; refreshUI(stateAt(time)); }
  function seekEvent(index) {
    pause();
    const event=events[Math.min(index,events.length-1)];
    seek(index<0?0:event.start+(['compress','merge'].includes(event.type)?event.duration*.8:.002));
  }
  function inspectionButtons(state) {
    $('inspect-section').hidden = !state.started;
    const key = [...state.compressed].join(',') + '|' + [...state.merged].join(',') + '|' + [...manualOpen].join(',');
    if ($('group-controls').dataset.key === key) return;
    $('group-controls').dataset.key = key;
    const hidden=new Set(higherGroups.filter(g=>state.merged.has(g.id)&&!manualOpen.has(g.id)).flatMap(g=>g.memberGroupIds));
    const order=[...state.merged,...state.compressed].filter(id=>!hidden.has(id));
    $('group-controls').innerHTML=order.map(id=>{const high=groups.get(id).memberGroupIds;return `<div class="group-control ${high?'higher-control':''}"><span>${esc(groups.get(id).title)}</span><button type="button" data-toggle-group="${esc(id)}">${high?(manualOpen.has(id)?'恢复合并':'展开两子图'):(manualOpen.has(id)?'恢复压缩':'展开子图')}</button></div>`;}).join('');
  }
  function describe(state) {
    const e = state.event;
    let type='等待执行', title='让轨迹开始生长', description='真实回合和工具调用构成子图；演示压缩保留任务摘要与后续依赖。', command='', group=null, step=null;
    if (selectedStep !== null) { step=steps.get(selectedStep); type=`回合 ${step.id} · 轨迹记录`; title=step.label; description=state.completed.has(step.id)?step.result:step.summary; command=step.toolCalls.slice(0,state.calls.get(step.id)||0).map(c=>c.command || c.name).join('\n\n'); }
    else if (selectedGroup) { group=groups.get(selectedGroup); type=group.memberGroupIds?'二级摘要 · 演示':'子图摘要 · 演示'; title=group.title; description=group.summary; }
    else if (e) {
      step=steps.get(e.stepId);
      if(e.type==='start'){type='TASK RECEIVED';title='整理 17 份文档';description=D.meta.task;}
      if(e.type==='plan'){type=`主 AGENT · 回合 ${step.id}`;title=step.label;description=step.summary;}
      if(e.type==='tool'){type=`ACTION ${String(e.actionNumber).padStart(2,'0')} · 回合 ${step.id}`;title=e.tool.name==='mark_task_complete'?'提交完成标记':step.label;description=`${groups.get(step.groupId).title} · 本回合第 ${e.toolIndex+1} / ${step.toolCalls.length} 次调用`;command=e.tool.command || `${e.tool.name}()`;}
      if(e.type==='observe'){type=step.id===7?'OBSERVATION · 需要修正':'OBSERVATION · 已接收';title=step.id===7?'读取失败，调整下一步':step.label;description=step.result;}
      if(e.type==='compress'){group=groups.get(e.groupId);type='COMPRESS · 演示压缩';title=`${group.title} → 摘要`;description=`${group.stepIds.length} 个回合收拢为 1 个摘要节点。完整子图保留，已有依赖连接到摘要。`;}
      if(e.type==='merge'){group=groups.get(e.groupId);step=null;type='LEVEL 2 · 二级压缩';title=group.title;description='PDF 与 JPG 两个子图收拢为一个阶段摘要。7 个原始回合及逐文件结果仍可展开，后续依赖连接到高层摘要。';}
      if(e.type==='plan'&&step?.id===13&&state.merged.size)description+=' 图中的分类与金额输入由高层摘要统一提供。';
      if(e.type==='finish'){type='TRAJECTORY COMPLETE';title='图已生长完成';description=`17 份文件已归档，10 份发票已汇总。${D.compressions.length} 次子图压缩与 ${D.merges?.length||0} 次二级压缩完成，对外依赖继续保留。`;}
    }
    $('event-type').textContent=type; $('event-title').textContent=title; $('event-description').textContent=description;
    $('event-type').style.color=group?'var(--purple)':e?.type==='observe'&&e.stepId===7?'var(--orange)':'var(--blue)';
    $('action-box').hidden=!command; $('action-code').textContent=command;
    $('compression-box').hidden=!group;
    $('retained-list').innerHTML=group?group.retained.map(x=>`<li>${esc(x)}</li>`).join(''):'';
    $('result-records').hidden=!group?.records;
    if(group?.records){
      $('result-records-body').innerHTML=`<table class="records-table"><thead><tr><th>发票文件</th><th>总额</th><th>VAT</th></tr></thead><tbody>${group.records.invoices.map(r=>`<tr><td>${esc(r.filename)}<small>证据 s${r.evidenceStepId}</small></td><td>${esc(r.total_amount)}</td><td>${esc(r.vat_amount)}</td></tr>`).join('')}</tbody></table><div class="records-other">其他文档（${group.records.other.length}）</div><ul class="records-files">${group.records.other.map(r=>`<li>${esc(r.filename)} <small>s${r.evidenceStepId}</small></li>`).join('')}</ul>`;
    }
    $('evidence-details').hidden=!step;
    if(step){
      const calls=step.toolCalls.slice(0,state.calls.get(step.id)||0);
      $('evidence-body').innerHTML=`<h3>STEP ${step.id} · 原始 message</h3><pre>${esc(step.message)}</pre><h3>已出现的工具调用</h3><pre>${esc(calls.map(c=>`[${c.id}] ${c.name}\n${c.command}`).join('\n\n'))}</pre>${state.completed.has(step.id)?`<h3>原始 observation</h3><pre>${esc(step.observation)}</pre>`:''}`;
    }
  }
  function refreshUI(state) {
    const e=state.event; const finished=time>=total;
    $('play').textContent=playing?'Ⅱ 暂停':finished?'▶ 再播一次':time===0?'▶ 从零播放':'▶ 继续播放';
    $('live-dot').classList.toggle('playing',playing);
    $('mode-label').textContent=finished?'轨迹完成':playing?'执行中':time>0?'已暂停':'准备开始';
    $('event-number').textContent=`${String(e?e.index+1:0).padStart(2,'0')} / ${events.length}`;
    $('empty-state').hidden=state.started;
    $('visible-count').textContent=state.visibleCount; $('original-count').textContent=state.arrived.size;
    $('stat-bar').style.width=`${state.arrived.size?state.visibleCount/state.arrived.size*100:0}%`;
    $('stat-note').textContent=state.compressed.size?`子图压缩 ${state.compressed.size} 次${state.merged.size?` · 二级压缩 ${state.merged.size} 次`:''} · ${state.toolCount} / ${D.meta.toolCallCount} 次调用。此处统计图节点，未测量 token 节省。`:'随图构建而变化；压缩时以 1 个摘要替代多个回合。';
    $('player-status').textContent=e?`${e.type==='merge'?'二级压缩':e.type==='compress'?'子图压缩':e.type==='tool'?'工具调用':e.type==='observe'?'接收反馈':e.type==='finish'?'完成':'主 Agent 执行'} · ${state.toolCount} / ${D.meta.toolCallCount} actions`:'准备好开始';
    $('elapsed').textContent=fmt(time); $('duration').textContent=fmt(total); $('timeline').value=time;
    $('previous').disabled=time===0; $('next').disabled=finished;
    $('graph-caption').textContent=e?.type==='merge'?'两份子图摘要 → 一个阶段摘要 → 保留对外依赖':e?.type==='compress'?'收拢内部回合 → 形成摘要节点 → 原有依赖重新连接':state.merged.size?'可逐层展开：阶段摘要 → PDF / JPG 子图 → 原始回合。':state.compressed.size?'点击节点查看证据；已压缩子图可在右侧展开。':'主 Agent 按回合推进，工具调用逐个出现。';
    document.querySelectorAll('.chapter-button').forEach(b=>b.classList.toggle('active',b.dataset.group===(e?.groupId||'')));
    inspectionButtons(state);
    const key=`${e?.index}|${selectedStep}|${selectedGroup}|${state.calls.get(selectedStep)}|${state.completed.has(selectedStep)}`;
    if(key!==lastDescriptionKey){describe(state);lastDescriptionKey=key;}
  }
  function interpolate(id,target,origin){
    let current=positions.get(id);
    if(!current){current={x:origin?.x??target.x,y:origin?.y??target.y,w:target.w,h:target.h,opacity:reduced?1:0};positions.set(id,current);}
    const k=reduced?1:.2;
    for(const key of ['x','y','w','h','opacity'])current[key]=mix(current[key]??target[key],target[key]??1,k);
    return current;
  }
  function draw(state) {
    const stage=$('graph-stage'); width=stage.clientWidth;
    const pad=22, gap=25, cols=width<490?1:width<760?2:3;
    const cell=(width-pad*2-gap*(cols-1))/cols;
    const boxes=new Map(), nodePositions=new Map();
    function layout(items){
      const result=new Map();let y=172;
      for(let row=0;row<Math.ceil(items.length/cols);row++){
        let maxH=0;
        for(let col=0;col<cols;col++){
          const g=items[row*cols+col];if(!g)continue;
          const ids=g.stepIds.filter(id=>state.arrived.has(id)),high=!!g.memberGroupIds;
          const fold=high?1:state.folds.get(g.id)||0;
          const h=high?148:mix(57+ids.length*58,118,fold);maxH=Math.max(maxH,h);
          result.set(g.id,{x:pad+col*(cell+gap),y,w:cell,h,opacity:1,g,fold,ids,row});
        }
        y+=maxH+54;
      }
      return {items:result,bottom:y-20};
    }
    const targetLayout=layout(state.visibleGroups),baseLayout=layout(state.baseGroups);
    for(const target of targetLayout.items.values()){
      const b=interpolate(`group-${target.g.id}`,target,{x:target.x,y:target.y-10});
      boxes.set(target.g.id,{...target,...b,opacity:target.g.memberGroupIds?(state.mergeProgress.get(target.g.id)||0):b.opacity});
    }
    // Children travel into their new parent. They keep their own saved state for later expansion.
    for(const parent of higherGroups){
      const q=state.mergeProgress.get(parent.id)||0;if(q<=0||q>=1)continue;
      const destination=boxes.get(parent.id);
      for(const childId of parent.memberGroupIds){
        const base=baseLayout.items.get(childId),key=`${parent.id}:${childId}`;
        if(!mergeOrigins.has(key))mergeOrigins.set(key,{...base,...positions.get(`group-${childId}`)});
        const origin=mergeOrigins.get(key);
        const b={...base,fold:1,x:mix(origin.x,destination.x,q),y:mix(origin.y,destination.y,q),w:mix(origin.w,destination.w,q),h:mix(origin.h,destination.h,q),opacity:1-q};
        boxes.set(childId,b);positions.set(`group-${childId}`,{x:b.x,y:b.y,w:b.w,h:b.h,opacity:b.opacity});
      }
    }
    const visibleBottom=Math.max(targetLayout.bottom,...[...boxes.values()].map(b=>b.y+b.h+30));
    const desired=Math.max(490,visibleBottom);
    height=reduced?desired:mix(height,desired,.18);
    stage.style.height=`${height}px`;
    $('graph').setAttribute('viewBox',`0 0 ${width} ${height}`);
    $('graph').style.height=`${height}px`;
    const root={x:Math.max(22,(width-278)/2),y:28,w:Math.min(width-44,278),h:58};
    for(const b of boxes.values()){
      b.ids.forEach((id,i)=>{
        if(representative(id,state).owner!==b.g.id)return;
        const raw={x:b.x+12,y:b.y+45+i*58,w:b.w-24,h:47};
        const folded={x:b.x+12,y:b.y+46,w:b.w-24,h:53};
        nodePositions.set(id,{x:mix(raw.x,folded.x,b.fold),y:mix(raw.y,folded.y,b.fold),w:raw.w,h:mix(raw.h,folded.h,b.fold),fold:b.fold});
      });
    }
    const s=[];
    s.push(`<defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6" fill="#a6b4cc"/></marker><marker id="active-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6" fill="#527fe6"/></marker></defs><title id="graph-title">主 Agent 执行与层级压缩动画</title><desc id="graph-desc">已出现 ${state.arrived.size} 个回合，${state.compressed.size} 次子图压缩，${state.merged.size} 次二级压缩。依赖线为人工演示标注。</desc>`);
    if(!state.started){$('graph').innerHTML=s.join('');return;}
    const current=state.event, activeGroup=boxes.get(current?.groupId);
    // The task spine remains stable; only observed rounds appear on it.
    const railY=119, railWidth=Math.min(width-75,Math.max(90,D.steps.length*24));
    const railX=(width-railWidth)/2;
    s.push(`<path d="M${root.x+root.w/2} ${root.y+root.h} V${railY-9}" stroke="#d2dcf0" fill="none"/>`);
    if(state.arrived.size){
      const end=railX+(state.arrived.size-1)*(railWidth/(D.steps.length-1));
      s.push(`<path d="M${railX} ${railY} H${end}" stroke="#d7e1f5" stroke-width="2"/>`);
      D.steps.filter(step=>state.arrived.has(step.id)).forEach((step,i)=>{
        const x=railX+i*railWidth/(D.steps.length-1); const active=step.id===current?.stepId;
        s.push(`<circle cx="${x}" cy="${railY}" r="${active?5:3}" fill="${active?'#3567dc':'#b2c5ee'}"/>`,svgText(step.id,x,railY+20,9,active?'#3567dc':'#91a0ba','text-anchor="middle"'));
      });
    }
    if(activeGroup){
      const fromX=root.x+root.w/2,toX=activeGroup.x+activeGroup.w/2;
      s.push(`<path d="M${fromX} ${root.y+root.h} C${fromX} ${root.y+root.h+58} ${toX} ${activeGroup.y-35} ${toX} ${activeGroup.y-7}" fill="none" stroke="#7195e4" stroke-width="1.1" stroke-dasharray="3 5" opacity=".5"/>`);
    }
    // Cross-group dependencies are deduplicated when endpoints share summaries.
    const projected=new Map();
    D.dependencies.forEach(d=>{
      if(!state.arrived.has(d.target)||!state.completed.has(d.source))return;
      const sourceRep=representative(d.source,state),targetRep=representative(d.target,state);
      const sg=sourceRep.owner,tg=targetRep.owner;
      if(sg===tg)return;
      const sourceKey=sourceRep.key,targetKey=targetRep.key;
      const key=`${sourceKey}>${targetKey}`;
      if(!projected.has(key))projected.set(key,{...d,sg,tg,count:0,evidenceList:[],key});
      projected.get(key).count++;
      projected.get(key).evidenceList.push(`${d.source} → ${d.target} · ${d.label}\n${d.evidence}`);
    });
    for(const d of projected.values()){
      const a=boxes.get(d.sg),b=boxes.get(d.tg); if(!a||!b)continue;
      const na=nodePositions.get(d.source),nb=nodePositions.get(d.target);
      const sameRow=Math.abs(a.y-b.y)<12;
      let path;
      if(sameRow){
        const sx=a.x+a.w,sy=na.y+na.h/2,tx=b.x,ty=nb.y+nb.h/2;
        path=`M${sx} ${sy} C${sx+gap*.75} ${sy} ${tx-gap*.75} ${ty} ${tx-3} ${ty}`;
      }else if(cols===1||b.row-a.row>1){
        // Long links use an outer gutter so they cannot look like edges from an intervening task.
        const useRight=D.groups.indexOf(a.g)%2===1;
        const sx=useRight?a.x+a.w:a.x,tx=useRight?b.x+b.w:b.x;
        const sy=na.y+na.h/2,ty=nb.y+nb.h/2;
        const offset=9+([...projected.keys()].indexOf(d.key)%3)*4;
        const channel=useRight?width-pad+offset:pad-offset;
        path=`M${sx} ${sy} Q${channel} ${sy} ${channel} ${sy+12} L${channel} ${ty-12} Q${channel} ${ty} ${tx+(useRight?3:-3)} ${ty}`;
      }else{
        const sx=a.x+a.w/2,sy=a.y+a.h,tx=b.x+b.w/2,ty=b.y;
        const channel=sy+24+([ ...projected.keys()].indexOf(d.key)%3)*5;
        path=`M${sx} ${sy} C${sx} ${channel} ${sx} ${channel} ${sx+Math.sign(tx-sx)*12} ${channel} L${tx-Math.sign(tx-sx)*12} ${channel} Q${tx} ${channel} ${tx} ${channel+10} L${tx} ${ty-4}`;
      }
      const isActive=current?.groupId===d.tg;
      s.push(`<path data-dependency="${esc(d.key)}" data-evidence-count="${d.count}" d="${path}" fill="none" stroke="${isActive?'#7195df':'#a6b4cc'}" stroke-width="${isActive?1.5:1.2}" marker-end="url(#${isActive?'active-arrow':'arrow'})" opacity=".8"><title>${d.count} 条人工标注依赖\n${esc(d.evidenceList.join('\n\n'))}</title></path>`);
    }
    for(const b of boxes.values()){
      const active=current?.groupId===b.g.id, comp=b.fold,high=!!b.g.memberGroupIds;
      const complete=b.g.stepIds.every(id=>state.completed.has(id));
      s.push(`<g data-box="${esc(b.g.id)}" opacity="${b.opacity}"><rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="11" fill="${high?'#f3effb':comp>.5?'#f8f5fd':active?'#f8faff':'#fafbfd'}" stroke="${high?'#b59bd5':active?(comp>.5?'#bb9edb':'#b5c9f1'):'#e1e6ef'}" stroke-width="${high?1.4:1}"/>`);
      s.push(svgText(high?'L2':String(D.groups.indexOf(b.g)+1).padStart(2,'0'),b.x+13,b.y+25,10,comp>.5?'#8f72b6':'#91a1b8'));
      s.push(svgText(b.g.title,b.x+36,b.y+25,12,'#45546d','font-weight="550"'));
      s.push(svgText(high?'二级摘要':comp>.5?'摘要':complete?'已完成':'执行中',b.x+b.w-13,b.y+25,9,comp>.5?'#8c68b7':complete?'#669687':'#7594c5','text-anchor="end"'));
      if(comp<.995){
        b.ids.forEach((id,i)=>{
          const step=steps.get(id),np=nodePositions.get(id),done=state.completed.has(id),error=id===7&&done;
          const selected=id===selectedStep,now=id===current?.stepId&&current?.type!=='compress';
          const calls=state.calls.get(id)||0;
          const p=interpolate(`node-${id}`,{...np,opacity:1},{x:np.x,y:i?np.y-30:np.y-9});
          const internal=D.dependencies.find(d=>d.source===b.ids[i-1]&&d.target===id);
          if(i>0&&comp<.2&&internal){const prev=nodePositions.get(b.ids[i-1]);s.push(`<path data-dependency="step:${internal.source}>step:${id}" data-evidence-count="1" d="M${p.x+20} ${prev.y+prev.h} V${p.y-3}" stroke="${step.kind==='repair'?'#d0a273':'#c7d4e8'}" marker-end="url(#arrow)"><title>${esc(internal.label)}\n${esc(internal.evidence)}</title></path>`);}
          s.push(`<g class="graph-node" data-step="${id}" role="button" tabindex="0" aria-label="查看回合 ${id}：${esc(step.label)}" opacity="${(1-comp)*p.opacity}"><rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="7" fill="${error?'#fff8ee':now||selected?'#edf3ff':'#fff'}" stroke="${error?'#e6c79c':now||selected?'#9cb9f2':'#e0e7f0'}"/>`);
          s.push(`<circle cx="${p.x+15}" cy="${p.y+16}" r="3" fill="${error?'#c78d48':done?'#71978b':'#5481de'}"/>`,svgText(short(step.label,Math.max(10,Math.floor((p.w-64)/12))),p.x+25,p.y+20,11,'#485b78'));
          s.push(svgText(`s${id}`,p.x+p.w-11,p.y+19,9,'#99a7bc','text-anchor="end"'));
          s.push(svgText(error?'反馈：命令参数错误':done?'已接收结果':calls?'正在调用工具':'组织下一步行动',p.x+25,p.y+36,9,error?'#b98c54':'#97a2b3'));
          for(let c=0;c<step.toolCalls.length;c++)s.push(`<rect x="${p.x+p.w-13-(step.toolCalls.length-c)*7}" y="${p.y+29}" width="5" height="5" rx="1.5" fill="${c<calls?'#8ba9e7':'#e5ebf4'}"/>`);
          s.push('</g>');
        });
      }
      if(comp>.005){
        const x=b.x+12,y=b.y+44;
        s.push(`<g class="graph-node" data-group="${esc(b.g.id)}" role="button" tabindex="0" aria-label="查看${esc(b.g.title)}摘要" opacity="${comp}"><rect x="${x}" y="${y}" width="${b.w-24}" height="${high?70:58}" rx="7" fill="${high?'#e9def7':'#f0e9fa'}"/>`);
        const lines=wrap(b.g.summary,b.w-48,10);
        lines.slice(0,3).forEach((line,i)=>s.push(svgText(line,x+11,y+18+i*14,10,'#79608f')));
        if(high)s.push(svgText('PDF 子图 + JPG 子图',x+11,y+59,9,'#8b6da8'));
        s.push('</g>',svgText(high?`2 个子图 → 1 个阶段摘要 · 可展开 ${b.g.stepIds.length} 个回合`:`${b.g.stepIds.length} 个回合 → 1 个摘要`,b.x+14,b.y+b.h-9,8,'#a490ba'));
      }
      s.push('</g>');
    }
    const rootTitle=current?.type==='finish'?'主 Agent · 任务完成':current?.type==='merge'?'主 Agent · 合并子图摘要':current?.type==='compress'?'主 Agent · 压缩已完成子图':current?.stepId?`主 Agent · 回合 ${current.stepId}`:'主 Agent · 接收任务';
    const rootSubtitle=current?.type==='tool'?`ACTION ${String(current.actionNumber).padStart(2,'0')} · ${current.tool.name==='mark_task_complete'?'完成标记':current.tool.name}`:current?.type==='merge'?'子任务层 → 阶段层 · 保留对外依赖':current?.type==='compress'?'保留摘要与依赖，继续后续行动':current?.type==='observe'?'读取环境反馈，更新执行状态':'文档分类与发票汇总';
    s.push(`<g><rect x="${root.x}" y="${root.y}" width="${root.w}" height="${root.h}" rx="12" fill="#fff" stroke="#b7caef"/><rect x="${root.x+13}" y="${root.y+13}" width="32" height="32" rx="9" fill="#edf2fd"/>`,svgText('A',root.x+29,root.y+35,15,'#3567dc','text-anchor="middle" font-weight="500"'),svgText(rootTitle,root.x+57,root.y+25,12,'#3f5579','font-weight="550"'),svgText(rootSubtitle,root.x+57,root.y+43,9,'#8b9ab0'),'</g>');
    const focused=document.activeElement;
    const focusStep=focused?.getAttribute('data-step'),focusGroup=focused?.getAttribute('data-group');
    const graphHadFocus=$('graph').contains(focused);
    $('graph').innerHTML=s.join('');
    if(graphHadFocus){const replacement=focusStep?$('graph').querySelector(`[data-step="${focusStep}"]`):focusGroup?$('graph').querySelector(`[data-group="${focusGroup}"]`):null;replacement?.focus({preventScroll:true});}
  }
  $('play').addEventListener('click',()=>playing?pause():play());
  $('restart').addEventListener('click',()=>{pause();positions.clear();seek(0);});
  $('previous').addEventListener('click',()=>seekEvent((eventAt(time)?.index??0)-1));
  $('next').addEventListener('click',()=>{const i=(eventAt(time)?.index??-1)+1;if(i>=events.length){pause();seek(total);}else seekEvent(i);});
  $('timeline').max=total;
  $('timeline').addEventListener('input',e=>{pause();seek(e.target.value);});
  $('speed').addEventListener('change',e=>{speed=Number(e.target.value);});
  $('overview').addEventListener('click',()=>{pause();seek(total);});
  $('group-controls').addEventListener('click',e=>{
    const button=e.target.closest('[data-toggle-group]');if(!button)return;pause();
    const id=button.dataset.toggleGroup;
    if(manualOpen.has(id))manualOpen.delete(id);else manualOpen.add(id);
    selectedGroup=id;selectedStep=null;lastDescriptionKey='';dirty=true;settling=45;refreshUI(stateAt(time));
  });
  function selectNode(target){
    const node=target.closest('[data-step],[data-group]');if(!node)return;pause();
    selectedStep=node.hasAttribute('data-step')?Number(node.dataset.step):null;
    selectedGroup=node.dataset.group||null;lastDescriptionKey='';dirty=true;refreshUI(stateAt(time));
  }
  $('graph').addEventListener('click',e=>selectNode(e.target));
  $('graph').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectNode(e.target);}});
  $('timeline-markers').innerHTML=events.filter(e=>['compress','merge'].includes(e.type)).map(e=>`<span class="timeline-marker ${e.type==='merge'?'higher-marker':''}" style="left:${e.start/total*100}%"></span>`).join('');
  const chapterItems=D.groups.flatMap((g,i)=>[{id:g.id,label:`${String(i+1).padStart(2,'0')} ${g.title}`},...higherGroups.filter(p=>p.memberGroupIds.at(-1)===g.id).map(p=>({id:p.id,label:'L2 二级压缩'}))]);
  $('chapters').innerHTML=chapterItems.map(g=>`<button class="chapter-button" data-group="${esc(g.id)}" type="button">${esc(g.label)}</button>`).join('');
  $('chapters').addEventListener('click',e=>{const b=e.target.closest('[data-group]');if(b)seekEvent(events.findIndex(v=>v.groupId===b.dataset.group));});
  new ResizeObserver(()=>{dirty=true;settling=45;}).observe($('graph-stage'));
  function frame(now){
    const dt=Math.min((now-lastFrame)/1000,.15);lastFrame=now;
    if(playing){time=Math.min(total,time+dt*speed);dirty=true;if(time>=total)playing=false;}
    if(dirty||settling>0){const state=stateAt(time);if((state.event?.index??-1)!==lastEventIndex){lastEventIndex=state.event?.index??-1;settling=45;}draw(state);refreshUI(state);dirty=false;settling--;}
    requestAnimationFrame(frame);
  }
  window.TrajectoryPlayer={events,total,dataset:D,seek,seekEvent,play,pause,getState:()=>({time,playing,speed,...stateAt(time),manualOpen:[...manualOpen]})};
  // A timestamp link opens paused at that exact frame, useful for sharing/export.
  const linkedTime=/(?:^\?|&)t=(\d+(?:\.\d+)?)(?:&|$)/.exec(window.location?.search||'');
  if(linkedTime)seek(Number(linkedTime[1]));
  refreshUI(stateAt(time));requestAnimationFrame(frame);
})();
