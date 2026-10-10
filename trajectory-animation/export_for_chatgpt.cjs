#!/usr/bin/env node
'use strict';

// Export the actual player's timeline and a portable copy of the animation.
// Keyframe JPEGs are captured separately from the running browser, not this DOM stub.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = __dirname;
const out = path.join(base, 'share-with-chatgpt');
fs.mkdirSync(out, { recursive: true });
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, style: {}, dataset: {}, classList: { toggle() {} }, clientWidth: 900,
    innerHTML: '', hidden: false, addEventListener() {},
    setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name]; }, contains() { return false; },
    querySelector() { return null; },
  });
  return elements.get(id);
}
const context = vm.createContext({
  window: {}, document: {
    getElementById: element, querySelectorAll() { return []; }, activeElement: null,
    createElement() { return { getContext() { return { measureText(text) { return { width: text.length * 7 }; } }; } }; },
  },
  matchMedia: () => ({ matches: false }), ResizeObserver: class { observe() {} },
  requestAnimationFrame() {}, performance: { now: () => 0 },
});
for (const name of ['data.js', 'app.js']) vm.runInContext(fs.readFileSync(path.join(base, name), 'utf8'), context);
const player = context.window.TrajectoryPlayer;
const D = player.dataset;
const groups = new Map([...D.groups, ...D.higherGroups].map(g => [g.id, g]));
const steps = new Map(D.steps.map(s => [s.id, s]));
const event = (type, id) => player.events.find(e => e.type === type && (typeof id === 'number' ? e.stepId === id : e.groupId === id));
const atEnd = e => Number((e.end - 0.01).toFixed(2));
const merge = event('merge', 'classification');
const frames = [
  { file: '00-empty.jpg', time: 0, title: '空图，等待主 Agent 开始' },
  { file: '01-growth.jpg', time: atEnd(event('observe', 4)), title: '准备环境的三个回合逐步出现，尚未折叠' },
  { file: '02-leaf-compression.jpg', time: atEnd(event('compress', 'env')), title: '环境子图折叠为摘要，已有依赖继续连接' },
  { file: '03-feedback-error.jpg', time: atEnd(event('observe', 7)), title: '第 7 回合读取失败；下一回合将调整命令' },
  { file: '04-two-subgraphs.jpg', time: atEnd(event('compress', 'jpg')), title: 'PDF 与 JPG 子图分别形成摘要，等待二级合并' },
  { file: '05-merging.jpg', time: Number((merge.start + merge.duration * 0.36).toFixed(2)), title: '二级合并进行中，两个子图向高层摘要收拢' },
  { file: '06-higher-summary.jpg', time: Number((merge.start + merge.duration * 0.8).toFixed(2)), title: '二级合并完成，7 个回合由同一个高层摘要代表' },
  { file: '07-continue-execution.jpg', time: atEnd(event('observe', 13)), title: '主 Agent 继续归档与汇总，高层摘要向后续行动提供依赖' },
  { file: '08-complete.jpg', time: Number(player.total.toFixed(2)), title: '全部执行完成，摘要与后续回合共同构成最终图' },
];
fs.writeFileSync(path.join(out, 'keyframes.json'), JSON.stringify(frames, null, 2) + '\n');
const lines = [
  'Agent 轨迹动画：按时间阅读的执行说明',
  '',
  `任务：${D.meta.task}`,
  `来源：trajectory.json；SHA-256 ${D.meta.sourceSha256}`,
  `动画总长：${player.total.toFixed(2)} 秒；${player.events.length} 个播放事件；14 个 Agent 回合；28 次工具调用。`,
  '从空图开始，依次出现计划、工具调用、反馈与图的变化。下列秒数是动画时间，并非原始任务的实际耗时。',
  `证据边界：${D.meta.compressionNote}`,
  D.meta.dependencyNote, D.meta.tokenNote,
  '', '图片顺序（JPEG 是实际浏览器画面）：',
  ...frames.map(f => `${f.file} | ${f.time.toFixed(2)}s | ${f.title}`),
  '', '完整播放时间轴：',
];
for (const e of player.events) {
  const step = steps.get(e.stepId);
  const group = groups.get(e.groupId);
  const offset = ['compress', 'merge'].includes(e.type) ? e.duration * 0.8 : 0.01;
  player.seek(Math.min(e.start + offset, player.total));
  const state = player.getState();
  lines.push('', `[${String(e.index + 1).padStart(2, '0')}] ${e.start.toFixed(2)}–${e.end.toFixed(2)}s | ${e.type}${step ? ` | 回合 ${step.id}` : ''}`);
  if (e.type === 'start') lines.push('收到任务，轨迹从零开始构建。');
  if (e.type === 'plan') lines.push(`新增回合节点：${step.label}`, step.summary);
  if (e.type === 'tool') lines.push(`Action ${e.actionNumber}：${e.tool.name}`, e.tool.command || `${e.tool.name}()`);
  if (e.type === 'observe') lines.push(`收到反馈：${step.result}`);
  if (e.type === 'compress') lines.push(`演示折叠：${group.title}，回合 ${group.stepIds.join(', ')} → 一个摘要。`, group.summary, '保留：' + group.retained.join('；'));
  if (e.type === 'merge') lines.push(`演示二级合并：${group.memberGroupIds.join(' + ')} → ${group.title}。`, group.summary, '保留：' + group.retained.join('；'), '仍可逐层展开高层摘要、PDF / JPG 摘要和原始回合。后续依赖转接至高层摘要。');
  if (e.type === 'finish') lines.push('轨迹完成；17 份文件归档，10 份发票汇总。');
  lines.push(`阶段状态：已出现 ${state.arrived.size} 个原始回合；${state.visibleCount} 个代表节点；已出现 ${state.toolCount} 次工具调用；子图折叠 ${state.compressed.size} 次；二级合并 ${state.merged.size} 次。`);
}
lines.push('', '原始回合证据（与演示标注分开保存）：');
for (const step of D.steps) lines.push('', `STEP ${step.id}: ${step.label}`, `message:\n${step.message}`, ...step.toolCalls.map(t => `tool ${t.id}: ${t.name}\n${t.command || ''}`), `observation:\n${step.observation}`);
lines.push('', '人工标注依赖：', JSON.stringify(D.dependencies, null, 2), '', '高层摘要的结构化结果：', JSON.stringify(D.higherGroups, null, 2));
fs.writeFileSync(path.join(out, 'execution-events.txt'), lines.join('\n') + '\n');
let html = fs.readFileSync(path.join(base, 'index.html'), 'utf8');
html = html.replace(/<link[^>]*href="styles\.css"[^>]*>/, () => '<style>\n' + fs.readFileSync(path.join(base, 'styles.css'), 'utf8') + '\n</style>');
for (const name of ['data.js', 'app.js']) html = html.replace(new RegExp(`<script src="${name.replace('.', '\\.')}"[^>]*><\\/script>`), () => '<script>\n' + fs.readFileSync(path.join(base, name), 'utf8').replace(/<\/script/gi, '<\\/script') + '\n</script>');
// The portable file sits beside the share files, one level below index.html.
html = html.replace(/href="share-with-chatgpt\//g, 'href="');
fs.writeFileSync(path.join(out, 'animation-standalone.html'), html);
fs.writeFileSync(path.join(out, 'animation-source.txt'), html);
console.log(JSON.stringify({ output: out, duration: player.total, events: player.events.length, frames }, null, 2));
