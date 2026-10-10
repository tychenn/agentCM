#!/usr/bin/env node
'use strict';

// State and SVG structure regression checks. No browser or package install needed.
// This DOM stub deliberately does not test actual layout, fonts, or interaction focus.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const base = path.resolve(__dirname, '..');

function playerFixture(reducedMotion = false, width = 900) {
  const elements = new Map();
  let nextFrame;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, style: {}, dataset: {}, listeners: {}, classList: { toggle() {} },
      clientWidth: width, innerHTML: '', hidden: false,
      addEventListener(name, handler) { this.listeners[name] = handler; },
      setAttribute(name, value) { this[name] = value; },
      getAttribute(name) { return this[name]; },
      contains() { return false; }, querySelector() { return null; },
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    window: {},
    document: {
      getElementById: element, querySelectorAll() { return []; }, activeElement: null,
      createElement() {
        return { getContext() { return { measureText(text) { return { width: text.length * 7 }; } }; } };
      },
    },
    matchMedia: () => ({ matches: reducedMotion }),
    ResizeObserver: class { observe() {} },
    requestAnimationFrame: callback => { nextFrame = callback; },
    performance: { now: () => 0 },
  });
  for (const filename of ['data.js', 'app.js']) {
    vm.runInContext(fs.readFileSync(path.join(base, filename), 'utf8'), context, { filename });
  }
  const player = context.window.TrajectoryPlayer;
  function render() {
    nextFrame(1);
    const html = element('graph').innerHTML;
    assert(!/\b(?:NaN|undefined)\b/.test(html), 'SVG contains invalid coordinates or values');
    return html;
  }
  function snapshot() {
    const html = render();
    const edges = [...html.matchAll(/data-dependency="([^"]+)" data-evidence-count="(\d+)"/g)]
      .map(match => ({ key: match[1].replace(/&gt;/g, '>'), count: Number(match[2]) }));
    const roundCount = [...html.matchAll(/data-step="\d+"/g)].length;
    const summaryCount = [...html.matchAll(/data-group="[^"]+"/g)].length;
    return { state: player.getState(), html, edges, roundCount, summaryCount, nodeCount: roundCount + summaryCount };
  }
  function toggle(id) {
    const controls = element('group-controls').innerHTML;
    assert(controls.includes(`data-toggle-group="${id}"`), `Missing available toggle ${id}`);
    element('group-controls').listeners.click({ target: { closest: () => ({ dataset: { toggleGroup: id } }) } });
    return snapshot();
  }
  return { player, element, snapshot, toggle };
}

const fixture = playerFixture();
const { player } = fixture;
assert.equal(player.events.length, 63);
assert.equal(player.dataset.steps.length, 14);
assert.equal(player.dataset.dependencies.length, 18);
const rawSource = fs.readFileSync(path.resolve(base, player.dataset.meta.source));
assert.equal(crypto.createHash('sha256').update(rawSource).digest('hex'), player.dataset.meta.sourceSha256);

// Visit every event in chronological order: catches stale cached group membership
// and fold state, which a test starting only at the final frame would miss.
for (const event of player.events) {
  const offset = ['compress', 'merge'].includes(event.type) ? event.duration * 0.8 : 0.01;
  player.seek(event.start + offset);
  const frame = fixture.snapshot();
  assert.equal(frame.nodeCount, frame.state.visibleCount, `Displayed node count differs at ${event.type} ${event.stepId || ''}`);
  for (const match of frame.html.matchAll(/data-step="(\d+)"/g)) {
    assert(frame.state.arrived.has(Number(match[1])), 'A future round became visible');
  }
}

const merge = player.events.find(event => event.type === 'merge');
const mergeIndex = player.events.indexOf(merge);
assert.equal(player.events[mergeIndex - 1].type, 'compress');
assert.equal(player.events[mergeIndex - 1].groupId, 'jpg');
assert.equal(player.events[mergeIndex + 1].stepId, 13);
player.seek(merge.start - 0.001);
let frame = fixture.snapshot();
assert.equal(frame.nodeCount, 4);
assert.equal(frame.state.merged.size, 0);
assert(!frame.html.includes('data-group="classification"'));

player.seek(merge.start + merge.duration * 0.8);
frame = fixture.snapshot();
assert.equal(frame.nodeCount, 3);
assert(!frame.state.arrived.has(13));
assert(!frame.edges.some(edge => edge.key.endsWith('step:13')));
assert.equal(frame.edges.find(edge => edge.key === 'group:extract>group:classification').count, 5);
assert(!frame.html.includes('data-box="pdf"'));
assert(!frame.html.includes('data-box="jpg"'));

player.seekEvent(mergeIndex);
assert.equal(fixture.snapshot().nodeCount, 3, 'Single stepping must reach the completed merge state');
const produce = player.events.find(event => event.type === 'plan' && event.stepId === 13);
player.seek(produce.start + 0.01);
frame = fixture.snapshot();
assert.equal(frame.edges.find(edge => edge.key === 'group:classification>step:13').count, 6);

player.seek(player.total);
frame = fixture.snapshot();
assert.equal(frame.nodeCount, 6);
assert.equal(frame.edges.length, 5);
assert.equal(frame.edges.reduce((sum, edge) => sum + edge.count, 0), 14);
frame = fixture.toggle('classification');
assert.equal(frame.nodeCount, 7);
assert.equal(frame.edges.length, 7);
for (const id of ['env', 'extract', 'pdf', 'jpg']) frame = fixture.toggle(id);
assert.equal(frame.nodeCount, 14);
assert.equal(frame.roundCount, 14);
assert.equal(frame.summaryCount, 0);
assert.equal(frame.edges.length, 18);
assert.deepEqual(new Set(frame.edges.map(edge => edge.key)),
  new Set(player.dataset.dependencies.map(edge => `step:${edge.source}>step:${edge.target}`)));

// Re-merging retains the user's expanded leaf state for the next unfold.
frame = fixture.toggle('classification');
assert.equal(frame.nodeCount, 8); // Expanded environment, extraction, output, verification + parent.
frame = fixture.toggle('classification');
assert.equal(frame.nodeCount, 14);

// Exercise early and late merge animation frames, including a paused hierarchy edit.
for (const fraction of [0.01, 0.25, 0.4, 0.65]) {
  player.seek(merge.start + merge.duration * fraction);
  fixture.snapshot();
  fixture.toggle('classification');
  fixture.toggle('pdf');
  fixture.toggle('classification');
  frame = fixture.toggle('classification');
  assert.equal(frame.nodeCount, 6); // Environment + extraction + 3 PDF rounds + JPG summary.
}

// Seeking back drops parent summaries and their records; restarting clears all nodes.
player.seek(player.events.find(event => event.type === 'plan' && event.stepId === 9).start + 0.01);
frame = fixture.snapshot();
assert.equal(frame.state.merged.size, 0);
assert.equal(fixture.element('result-records').hidden, true);
assert(!frame.html.includes('data-group="classification"'));
player.seek(0);
assert.equal(fixture.snapshot().nodeCount, 0);

// Geometry smoke checks at narrow widths and with reduced motion.
for (const [reduced, width] of [[false, 390], [false, 640], [true, 900]]) {
  const other = playerFixture(reduced, width);
  for (const event of other.player.events) {
    other.player.seek(event.start + (['compress', 'merge'].includes(event.type) ? event.duration * 0.8 : 0.01));
    other.snapshot();
  }
  other.player.seek(other.player.total);
  assert.equal(other.snapshot().nodeCount, 6);
}
console.log('PASS: 63 events, hierarchical merge/unfold, 14 restored rounds, 18 restored dependencies, temporal visibility, and geometry smoke checks.');
