(() => {
  'use strict';
  const graph = JSON.parse(document.getElementById('tree-data').textContent);
  const nodes = graph.turn_nodes || [];
  const groups = graph.task_groups || [];
  const taskEdges = graph.task_edges || [];
  const rootGroupId = graph.root_group_id;
  const byId = new Map(nodes.map(node => [node.id, node]));
  const groupById = new Map(groups.map(group => [group.id, group]));
  const edgeById = new Map(taskEdges.map(edge => [edge.id, edge]));
  const groupParent = new Map(groups.filter(group => group.parent_group_id)
    .map(group => [group.id, group.parent_group_id]));
  const turnOwner = new Map(nodes.map(node => [node.id, node.owner_group_id]));

  const svg = document.getElementById('tree');
  const viewport = document.getElementById('viewport');
  const ns = 'http://www.w3.org/2000/svg';
  const collapsed = new Set();
  const W = 300, ITEM_GAP = 64;
  const GROUP_HEADER = 62, GROUP_PAD_X = 26, GROUP_PAD_TOP = 20;
  const GROUP_PAD_BOTTOM = 28, GROUP_MIN_W = 354;
  const GROUP_COLLAPSED_W = 330, GROUP_COLLAPSED_H = 64;
  const OUTER_MARGIN = 24, EDGE_OVERFLOW = 80;
  const TASK_LAYER_GAP_X = 270, TASK_LAYER_GAP_Y = 138;
  const LONG_EDGE_LANE_STEP = 30, LONG_EDGE_ROW_STEP = 72;
  const EDGE_LABEL_WIDTH = 234;
  const CALL_X = 14, CALL_Y = 82, CALL_W = W - 28, CALL_H = 19, CALL_STEP = 24;
  const ARROW_GAP = 5;
  const manualOffsets = new Map();
  let selected = rootGroupId || (nodes[0] && nodes[0].id);
  let focused = null, positions = new Map(), groupPositions = new Map();
  let visibleNodes = [], visibleGroups = [], scale = 1, tx = 0, ty = 0;
  let bounds = {x:0, y:0, width:W, height:126};
  let query = '', drag = null, itemDrag = null, moved = false;
  let groupFillLayer, edgeLayer, nodeLayer, groupOutlineLayer;

  function height(node) { return Math.max(126, 112 + node.calls.length * 24); }
  function el(tag, attrs = {}, text) {
    const element = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text !== undefined) element.textContent = text;
    return element;
  }

  const measure = document.createElement('canvas').getContext('2d');
  measure.font = '600 14px system-ui';
  function lines(text, maxWidth = W - 36, limit = 3) {
    const result = []; let line = '';
    for (const char of text) {
      if (measure.measureText(line + char).width > maxWidth) {
        const space = line.lastIndexOf(' ');
        if (space > 0) { result.push(line.slice(0, space)); line = line.slice(space + 1) + char; }
        else { result.push(line); line = char; }
      } else line += char;
    }
    if (line) result.push(line);
    if (result.length > limit) {
      result.length = limit;
      result[limit - 1] = result[limit - 1].slice(0, -2) + '…';
    }
    return result;
  }

  function updateTransform() {
    viewport.setAttribute('transform', `translate(${tx} ${ty}) scale(${scale})`);
    document.getElementById('zoom').textContent = Math.round(scale * 100) + '%';
  }
  function fit() {
    const rect = svg.getBoundingClientRect();
    scale = Math.max(.05, Math.min(1.15,
      (rect.width - 64) / bounds.width, (rect.height - 72) / bounds.height));
    tx = rect.width / 2 - (bounds.x + bounds.width / 2) * scale;
    ty = rect.height / 2 - (bounds.y + bounds.height / 2) * scale - 8;
    updateTransform();
  }

  function edgeIncident(edge, id) {
    return edge.id === id || edge.source_task_id === id || edge.target_task_id === id ||
      edge.source_event_ids.includes(id) || edge.target_event_ids.includes(id);
  }
  function applyConnectionFocus() {
    const active = Boolean(focused);
    viewport.classList.toggle('focus-active', active);
    const connected = new Set(active ? [focused] : []);
    if (active) {
      taskEdges.filter(edge => edgeIncident(edge, focused)).forEach(edge => {
        connected.add(edge.source_task_id);
        connected.add(edge.target_task_id);
        edge.source_event_ids.forEach(id => connected.add(id));
        edge.target_event_ids.forEach(id => connected.add(id));
      });
    }
    viewport.querySelectorAll('.dependency-link').forEach(element => {
      const incident = active && edgeIncident(edgeById.get(element.dataset.id), focused);
      element.classList.toggle('focus-edge', Boolean(incident));
      element.classList.toggle('focus-dimmed', Boolean(active && !incident));
      element.classList.toggle('selected', element.dataset.id === selected);
    });
    viewport.querySelectorAll('.turn-node').forEach(element => {
      const related = active && (connected.has(element.dataset.id) ||
        connected.has(turnOwner.get(element.dataset.id)));
      element.classList.toggle('focus-related', Boolean(related));
      element.classList.toggle('focus-dimmed', Boolean(active && !related));
      element.classList.toggle('selected', element.dataset.id === selected);
    });
    viewport.querySelectorAll('.task-group-fill,.task-group-outline').forEach(element => {
      const group = groupById.get(element.dataset.id);
      const related = active && (connected.has(element.dataset.id) ||
        (group && group.turn_ids.some(id => connected.has(id))));
      element.classList.toggle('focus-related', Boolean(related));
      element.classList.toggle('focus-dimmed', Boolean(active && !related));
      if (element.classList.contains('task-group-outline')) {
        element.classList.toggle('selected', element.dataset.id === selected);
      }
    });
  }
  function clearConnectionFocus() {
    focused = null;
    applyConnectionFocus();
  }
  function select(id, focus = true) {
    selected = id;
    focused = focus ? id : null;
    document.querySelectorAll('.task-detail').forEach(element => {
      element.hidden = element.id !== 'detail-' + id;
    });
    applyConnectionFocus();
  }

  function expandFor(id) {
    if (byId.has(id)) {
      let owner = turnOwner.get(id);
      while (owner) { collapsed.delete(owner); owner = groupParent.get(owner); }
    } else if (groupById.has(id)) {
      let groupId = id;
      while (groupId) { collapsed.delete(groupId); groupId = groupParent.get(groupId); }
    } else if (edgeById.has(id)) {
      let owner = edgeById.get(id).owner_task_id;
      while (owner) { collapsed.delete(owner); owner = groupParent.get(owner); }
    }
  }

  function groupDepth(id) {
    let depth = 0, current = id;
    const seen = new Set();
    while (groupParent.has(current) && !seen.has(current)) {
      seen.add(current);
      current = groupParent.get(current);
      depth += 1;
    }
    return depth;
  }

  function dependencyLayers(group) {
    const ids = group.items.filter(id => groupById.has(id));
    const idSet = new Set(ids);
    const outgoing = new Map(ids.map(id => [id, []]));
    const indegree = new Map(ids.map(id => [id, 0]));
    const rank = new Map(ids.map(id => [id, 0]));
    taskEdges.filter(edge => edge.owner_task_id === group.id &&
      idSet.has(edge.source_task_id) && idSet.has(edge.target_task_id) &&
      edge.source_task_id !== edge.target_task_id).forEach(edge => {
      if (outgoing.get(edge.source_task_id).includes(edge.target_task_id)) return;
      outgoing.get(edge.source_task_id).push(edge.target_task_id);
      indegree.set(edge.target_task_id, indegree.get(edge.target_task_id) + 1);
    });
    const queue = ids.filter(id => indegree.get(id) === 0);
    const visited = new Set();
    while (queue.length) {
      const id = queue.shift();
      visited.add(id);
      outgoing.get(id).forEach(target => {
        rank.set(target, Math.max(rank.get(target), rank.get(id) + 1));
        indegree.set(target, indegree.get(target) - 1);
        if (indegree.get(target) === 0) queue.push(target);
      });
    }
    let fallbackRank = Math.max(0, ...rank.values());
    ids.filter(id => !visited.has(id)).forEach(id => {
      fallbackRank += 1;
      rank.set(id, fallbackRank);
    });
    const layers = [];
    ids.forEach(id => {
      const value = rank.get(id);
      if (!layers[value]) layers[value] = [];
      layers[value].push(id);
    });
    return {layers:layers.filter(Boolean), rank};
  }
  function center(id) {
    const edge = edgeById.get(id);
    const position = positions.get(id) || groupPositions.get(id) ||
      (edge && groupPositions.get(edge.target_task_id));
    if (!position) return;
    const rect = svg.getBoundingClientRect();
    tx = rect.width / 2 - (position.x + position.w / 2) * scale;
    ty = rect.height / 2 - (position.y + position.h / 2) * scale;
    updateTransform();
  }
  function reveal(id) {
    expandFor(id);
    draw();
    select(id);
    center(id);
  }

  function startItemDrag(event, id) {
    if (event.button !== 0) return;
    event.stopPropagation();
    const offset = manualOffsets.get(id) || {x:0, y:0};
    moved = false;
    drag = null;
    itemDrag = {id, x:event.clientX, y:event.clientY,
      offsetX:offset.x, offsetY:offset.y};
    viewport.classList.add('item-dragging');
  }

  function freeEdgeRoute(source, target) {
    const sourceCenterX = source.x + source.w / 2;
    const sourceCenterY = source.y + source.h / 2;
    const targetCenterX = target.x + target.w / 2;
    const targetCenterY = target.y + target.h / 2;
    const dx = targetCenterX - sourceCenterX;
    const dy = targetCenterY - sourceCenterY;
    if (Math.abs(dx) >= Math.abs(dy)) {
      const direction = dx >= 0 ? 1 : -1;
      const sourceX = direction > 0 ? source.x + source.w : source.x;
      const targetX = direction > 0 ? target.x - ARROW_GAP : target.x + target.w + ARROW_GAP;
      const middleX = (sourceX + targetX) / 2;
      return {pathData:`M ${sourceX} ${sourceCenterY} C ${middleX} ${sourceCenterY}, ` +
        `${middleX} ${targetCenterY}, ${targetX} ${targetCenterY}`,
      labelCenterX:middleX, labelCenterY:(sourceCenterY + targetCenterY) / 2};
    }
    const direction = dy >= 0 ? 1 : -1;
    const sourceY = direction > 0 ? source.y + source.h : source.y;
    const targetY = direction > 0 ? target.y - ARROW_GAP : target.y + target.h + ARROW_GAP;
    const middleY = (sourceY + targetY) / 2;
    return {pathData:`M ${sourceCenterX} ${sourceY} C ${sourceCenterX} ${middleY}, ` +
      `${targetCenterX} ${middleY}, ${targetCenterX} ${targetY}`,
    labelCenterX:(sourceCenterX + targetCenterX) / 2, labelCenterY:middleY};
  }

  function resizeGroupsToContents() {
    [...visibleGroups].reverse().forEach(group => {
      if (collapsed.has(group.id) || !group.items.length) return;
      const children = group.items.map(id => groupPositions.get(id) || positions.get(id));
      if (children.some(position => !position)) return;
      const minX = Math.min(...children.map(position => position.x));
      const minY = Math.min(...children.map(position => position.y));
      const maxX = Math.max(...children.map(position => position.x + position.w));
      const maxY = Math.max(...children.map(position => position.y + position.h));
      const position = groupPositions.get(group.id);
      const naturalWidth = maxX - minX + GROUP_PAD_X * 2 + position.edgeExtraWidth;
      const width = Math.max(GROUP_MIN_W, naturalWidth);
      position.x = minX - GROUP_PAD_X - (width - naturalWidth) / 2;
      position.y = minY - GROUP_HEADER - GROUP_PAD_TOP;
      position.w = width;
      position.h = GROUP_HEADER + GROUP_PAD_TOP + (maxY - minY) +
        position.edgeExtraHeight + GROUP_PAD_BOTTOM;
      position.contentRight = maxX;
      position.contentBottom = maxY;
    });
  }

  function appendTaskEdge(edge) {
    const source = groupPositions.get(edge.source_task_id);
    const target = groupPositions.get(edge.target_task_id);
    const owner = groupPositions.get(edge.owner_task_id);
    if (!source || !target || !owner || collapsed.has(edge.owner_task_id)) return;
    const siblings = taskEdges.filter(item => item.owner_task_id === edge.owner_task_id);
    const span = Math.abs((target.parentLayoutRank || 0) - (source.parentLayoutRank || 0));
    const longEdges = siblings.filter(item => {
      const from = groupPositions.get(item.source_task_id);
      const to = groupPositions.get(item.target_task_id);
      return from && to && Math.abs((to.parentLayoutRank || 0) -
        (from.parentLayoutRank || 0)) > 1;
    });
    const longIndex = Math.max(0, longEdges.findIndex(item => item.id === edge.id));
    let pathData, labelCenterX, labelCenterY;
    if (manualOffsets.has(edge.source_task_id) || manualOffsets.has(edge.target_task_id)) {
      ({pathData, labelCenterX, labelCenterY} = freeEdgeRoute(source, target));
    } else if (owner.layoutDirection === 'down') {
      const sourceX = source.x + source.w / 2;
      const sourceY = source.y + source.h;
      const targetX = target.x + target.w / 2;
      const targetY = target.y - ARROW_GAP;
      if (span > 1) {
        const laneX = owner.contentRight + 28 + longIndex * LONG_EDGE_LANE_STEP;
        pathData = `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY + 30}, ` +
          `${laneX} ${sourceY + 30}, ${laneX} ${sourceY + 55} ` +
          `L ${laneX} ${targetY - 40} C ${laneX} ${targetY - 16}, ` +
          `${targetX} ${targetY - 16}, ${targetX} ${targetY}`;
        labelCenterX = laneX + EDGE_LABEL_WIDTH / 2 + 12;
        labelCenterY = (sourceY + targetY) / 2;
      } else {
        const middleY = (sourceY + targetY) / 2;
        pathData = `M ${sourceX} ${sourceY} C ${sourceX} ${middleY}, ` +
          `${targetX} ${middleY}, ${targetX} ${targetY}`;
        labelCenterX = (sourceX + targetX) / 2;
        labelCenterY = middleY;
      }
    } else {
      const sourceX = source.x + source.w;
      const sourceY = source.y + source.h / 2;
      const targetX = target.x - ARROW_GAP;
      const targetY = target.y + target.h / 2;
      if (span > 1) {
        const laneY = owner.contentBottom + 28 + longIndex * LONG_EDGE_ROW_STEP;
        pathData = `M ${sourceX} ${sourceY} C ${sourceX + 30} ${sourceY}, ` +
          `${sourceX + 30} ${laneY}, ${sourceX + 55} ${laneY} ` +
          `L ${targetX - 40} ${laneY} C ${targetX - 16} ${laneY}, ` +
          `${targetX - 16} ${targetY}, ${targetX} ${targetY}`;
        labelCenterX = (sourceX + targetX) / 2;
        labelCenterY = laneY;
      } else {
        const middleX = (sourceX + targetX) / 2;
        pathData = `M ${sourceX} ${sourceY} C ${middleX} ${sourceY}, ` +
          `${middleX} ${targetY}, ${targetX} ${targetY}`;
        labelCenterX = middleX;
        labelCenterY = (sourceY + targetY) / 2;
      }
    }
    const link = el('g', {class:'dependency-link', 'data-id':edge.id, tabindex:0,
      role:'button', 'aria-label':`子任务信息依赖 ${edge.reason}`});
    link.append(el('path', {class:'edge-hit', d:pathData}));
    const path = el('path', {class:'task-dependency-edge', d:pathData});
    path.setAttribute('marker-end', 'url(#task-arrow)');
    path.append(el('title', {}, `信息依赖：${edge.reason}\n证据：${edge.trigger_tool_call_ids.join(', ')}`));
    link.append(path);
    const reasonLines = lines(edge.reason, 214, 2);
    const labelWidth = EDGE_LABEL_WIDTH;
    const labelHeight = 12 + reasonLines.length * 15 + 18;
    const labelX = labelCenterX - labelWidth / 2;
    const labelY = labelCenterY - labelHeight / 2;
    const label = el('g', {class:'dependency-label'});
    label.append(el('rect', {x:labelX, y:labelY, width:labelWidth, height:labelHeight, rx:7}));
    reasonLines.forEach((text, index) =>
      label.append(el('text', {class:'dependency-reason', x:labelX + 10,
        y:labelY + 17 + index * 15}, text)));
    const evidenceText = edge.trigger_tool_call_ids.length === 1
      ? edge.trigger_tool_call_ids[0] : `${edge.trigger_tool_call_ids.length} 个 tool call 证据`;
    label.append(el('text', {class:'dependency-evidence-count', x:labelX + 10,
      y:labelY + labelHeight - 8}, evidenceText));
    link.append(label);
    const activate = event => {
      event.stopPropagation();
      if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
      if (event.type === 'keydown') event.preventDefault();
      if (!moved) select(edge.id);
    };
    link.onclick = activate;
    link.onkeydown = activate;
    edgeLayer.append(link);
  }

  function appendGroupFill(group) {
    const position = groupPositions.get(group.id);
    const layer = el('g', {class:'task-group-fill', 'data-id':group.id,
      transform:`translate(${position.x} ${position.y})`});
    layer.append(el('rect', {class:'group-background', width:position.w, height:position.h, rx:16}));
    groupFillLayer.append(layer);
  }
  function appendGroupOutline(group) {
    const position = groupPositions.get(group.id);
    const hit = query && (group.goal + ' ' + group.id + ' ' + group.label).toLowerCase().includes(query);
    const outline = el('g', {class:`task-group-outline${hit ? ' match' : ''}`,
      'data-id':group.id, transform:`translate(${position.x} ${position.y})`});
    outline.append(el('rect', {class:'group-border', width:position.w, height:position.h, rx:16}));
    if (!collapsed.has(group.id)) {
      outline.append(el('line', {class:'group-divider', x1:0, y1:GROUP_HEADER,
        x2:position.w, y2:GROUP_HEADER}));
    }
    const header = el('g', {class:'group-header', tabindex:0, role:'button',
      'aria-label':`${group.label} ${group.goal}，可拖动`, 'data-id':group.id});
    header.append(el('rect', {class:'group-header-hit', width:position.w,
      height:collapsed.has(group.id) ? position.h : GROUP_HEADER, rx:16}));
    header.append(el('text', {class:'group-label', x:18, y:21}, `${group.label} · ${group.status}`));
    lines(group.goal, Math.max(120, position.w - 88), 1).forEach(text =>
      header.append(el('text', {class:'group-title', x:18, y:45}, text)));
    header.onpointerdown = event => startItemDrag(event, group.id);
    header.onclick = event => { event.stopPropagation(); if (!moved) select(group.id); };
    header.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); event.stopPropagation(); select(group.id);
      }
    };
    outline.append(header);
    const toggle = el('g', {class:'group-toggle', transform:`translate(${position.w - 25} 22)`,
      role:'button', tabindex:0, 'aria-label':collapsed.has(group.id) ? '展开任务' : '折叠任务',
      'aria-expanded':!collapsed.has(group.id)});
    toggle.append(el('circle', {r:11}));
    toggle.append(el('text', {y:5}, collapsed.has(group.id) ? '+' : '−'));
    const change = event => {
      event.stopPropagation();
      if (collapsed.has(group.id)) collapsed.delete(group.id); else collapsed.add(group.id);
      draw(); fit();
    };
    toggle.onclick = change;
    toggle.onpointerdown = event => event.stopPropagation();
    toggle.onkeydown = event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); change(event); }
    };
    outline.append(toggle);
    groupOutlineLayer.append(outline);
  }

  function draw() {
    positions = new Map();
    groupPositions = new Map();
    visibleNodes = [];
    visibleGroups = [];
    const sizes = new Map();

    function turnSize(id) {
      const node = byId.get(id);
      return {w:W, h:height(node)};
    }
    function itemSize(id) {
      return groupById.has(id) ? groupSize(id) : turnSize(id);
    }
    function groupSize(id) {
      if (sizes.has(id)) return sizes.get(id);
      if (collapsed.has(id)) {
        const size = {w:GROUP_COLLAPSED_W, h:GROUP_COLLAPSED_H, itemSizes:[]};
        sizes.set(id, size); return size;
      }
      const group = groupById.get(id);
      const itemSizes = group.items.map(itemSize);
      const childTasks = group.items.length > 0 && group.items.every(item => groupById.has(item));
      const layerData = childTasks ? dependencyLayers(group) :
        {layers:[group.items.slice()], rank:new Map(group.items.map(item => [item, 0]))};
      const direction = childTasks && groupDepth(id) % 2 === 1 ? 'down' : 'right';
      const sizeById = new Map(group.items.map((item, index) => [item, itemSizes[index]]));
      const layerWidths = layerData.layers.map(layer => direction === 'right'
        ? Math.max(...layer.map(item => sizeById.get(item).w))
        : layer.reduce((sum, item) => sum + sizeById.get(item).w, 0) +
          Math.max(0, layer.length - 1) * ITEM_GAP);
      const layerHeights = layerData.layers.map(layer => direction === 'right'
        ? layer.reduce((sum, item) => sum + sizeById.get(item).h, 0) +
          Math.max(0, layer.length - 1) * ITEM_GAP
        : Math.max(...layer.map(item => sizeById.get(item).h)));
      const baseWidth = direction === 'right'
        ? layerWidths.reduce((sum, width) => sum + width, 0) +
          Math.max(0, layerWidths.length - 1) * TASK_LAYER_GAP_X
        : Math.max(...layerWidths);
      const baseHeight = direction === 'right'
        ? Math.max(...layerHeights)
        : layerHeights.reduce((sum, height) => sum + height, 0) +
          Math.max(0, layerHeights.length - 1) * TASK_LAYER_GAP_Y;
      const localEdges = taskEdges.filter(edge => edge.owner_task_id === id);
      const longEdgeCount = localEdges.filter(edge =>
        Math.abs((layerData.rank.get(edge.target_task_id) || 0) -
          (layerData.rank.get(edge.source_task_id) || 0)) > 1).length;
      const extraWidth = direction === 'down' && longEdgeCount
        ? EDGE_LABEL_WIDTH + 70 + (longEdgeCount - 1) * LONG_EDGE_LANE_STEP : 0;
      const extraHeight = direction === 'right' && longEdgeCount
        ? 68 + (longEdgeCount - 1) * LONG_EDGE_ROW_STEP : 0;
      const placements = new Map();
      if (direction === 'right') {
        let layerX = 0;
        layerData.layers.forEach((layer, layerIndex) => {
          let itemY = (baseHeight - layerHeights[layerIndex]) / 2;
          layer.forEach(item => {
            const itemSizeValue = sizeById.get(item);
            placements.set(item, {x:layerX + (layerWidths[layerIndex] - itemSizeValue.w) / 2,
              y:itemY, rank:layerIndex});
            itemY += itemSizeValue.h + ITEM_GAP;
          });
          layerX += layerWidths[layerIndex] + TASK_LAYER_GAP_X;
        });
      } else {
        let layerY = 0;
        layerData.layers.forEach((layer, layerIndex) => {
          let itemX = (baseWidth - layerWidths[layerIndex]) / 2;
          layer.forEach(item => {
            const itemSizeValue = sizeById.get(item);
            placements.set(item, {x:itemX,
              y:layerY + (layerHeights[layerIndex] - itemSizeValue.h) / 2,
              rank:layerIndex});
            itemX += itemSizeValue.w + ITEM_GAP;
          });
          layerY += layerHeights[layerIndex] + TASK_LAYER_GAP_Y;
        });
      }
      const innerWidth = baseWidth + extraWidth;
      const size = {w:Math.max(GROUP_MIN_W, innerWidth + GROUP_PAD_X * 2),
        h:GROUP_HEADER + GROUP_PAD_TOP + baseHeight + extraHeight + GROUP_PAD_BOTTOM,
        itemSizes, baseWidth, baseHeight, extraWidth, extraHeight, placements,
        layoutDirection:direction};
      sizes.set(id, size); return size;
    }
    function placeItem(id, x, y) {
      const offset = manualOffsets.get(id) || {x:0, y:0};
      x += offset.x;
      y += offset.y;
      if (groupById.has(id)) placeGroup(id, x, y);
      else {
        const size = turnSize(id);
        positions.set(id, {x, y, w:size.w, h:size.h});
        visibleNodes.push(byId.get(id));
      }
    }
    function placeGroup(id, x, y) {
      const group = groupById.get(id), size = groupSize(id);
      const innerWidth = size.baseWidth + size.extraWidth;
      const contentX = x + GROUP_PAD_X + Math.max(0,
        (size.w - GROUP_PAD_X * 2 - innerWidth) / 2);
      const contentY = y + GROUP_HEADER + GROUP_PAD_TOP;
      groupPositions.set(id, {x, y, w:size.w, h:size.h,
        contentRight:contentX + (size.baseWidth || 0),
        contentBottom:contentY + (size.baseHeight || 0),
        edgeExtraWidth:size.extraWidth || 0,
        edgeExtraHeight:size.extraHeight || 0,
        layoutDirection:size.layoutDirection || 'right'});
      visibleGroups.push(group);
      if (collapsed.has(id)) return;
      group.items.forEach(itemId => {
        const placement = size.placements.get(itemId);
        placeItem(itemId, contentX + placement.x, contentY + placement.y);
        const position = groupPositions.get(itemId) || positions.get(itemId);
        position.parentLayoutRank = placement.rank;
        position.parentGroupId = id;
      });
    }

    const rootSize = groupSize(rootGroupId);
    placeItem(rootGroupId, OUTER_MARGIN, OUTER_MARGIN);
    resizeGroupsToContents();
    const placed = [...groupPositions.values(), ...positions.values()];
    const minX = Math.min(...placed.map(position => position.x));
    const minY = Math.min(...placed.map(position => position.y));
    const maxX = Math.max(...placed.map(position => position.x + position.w));
    const maxY = Math.max(...placed.map(position => position.y + position.h));
    bounds = {x:minX - EDGE_OVERFLOW, y:minY - EDGE_OVERFLOW,
      width:maxX - minX + EDGE_OVERFLOW * 2,
      height:maxY - minY + EDGE_OVERFLOW * 2};
    viewport.replaceChildren();
    const defs = el('defs');
    const marker = el('marker', {id:'task-arrow', viewBox:'0 0 12 12', refX:11,
      refY:6, markerWidth:12, markerHeight:12, markerUnits:'userSpaceOnUse', orient:'auto'});
    marker.append(el('path', {d:'M 1 1 L 11 6 L 1 11 z', class:'task-arrow-head'}));
    defs.append(marker);
    groupFillLayer = el('g', {class:'group-fill-layer'});
    edgeLayer = el('g', {class:'edge-layer'});
    nodeLayer = el('g', {class:'node-layer'});
    groupOutlineLayer = el('g', {class:'group-outline-layer'});
    viewport.append(defs, groupFillLayer, edgeLayer, nodeLayer, groupOutlineLayer);

    visibleGroups.forEach(appendGroupFill);
    taskEdges.forEach(appendTaskEdge);
    visibleNodes.forEach(node => {
      const position = positions.get(node.id);
      const hit = query && (node.goal + ' ' + node.id).toLowerCase().includes(query);
      const element = el('g', {class:`turn-node${hit ? ' match' : ''}`,
        transform:`translate(${position.x} ${position.y})`, tabindex:0, role:'button',
        'aria-label':`${node.goal}，可拖动`, 'data-id':node.id});
      element.append(el('title', {}, node.goal));
      element.append(el('rect', {class:'card', width:W, height:position.h, rx:18}));
      element.append(el('text', {class:'node-label', x:16, y:23},
        `${node.order}. ${node.label} · ${node.status}`));
      lines(node.goal, W - 36, node.calls.length ? 2 : 3).forEach((text, index) =>
        element.append(el('text', {class:'node-title', x:16, y:47 + index * 19}, text)));
      node.calls.forEach((call, index) => {
        const y = CALL_Y + index * CALL_STEP;
        element.append(el('rect', {class:'call-row', x:CALL_X, y, width:CALL_W,
          height:CALL_H, rx:5, 'data-call':call.id}));
        element.append(el('text', {class:'call-text', x:23, y:y + 14}, `${call.id} · ${call.name}`));
      });
      element.append(el('text', {class:'node-meta', x:16, y:position.h - 10},
        `${node.actions} 个 tool call · ${node.id}`));
      element.onpointerdown = event => startItemDrag(event, node.id);
      element.onclick = event => { event.stopPropagation(); if (!moved) select(node.id); };
      element.onkeydown = event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); event.stopPropagation(); select(node.id);
        }
      };
      nodeLayer.append(element);
    });
    visibleGroups.forEach(appendGroupOutline);
    if (focused && edgeById.has(focused) && !groupPositions.has(edgeById.get(focused).source_task_id)) {
      focused = null;
    }
    applyConnectionFocus();
    updateTransform();
  }

  function zoom(factor, x, y) {
    const next = Math.max(.05, Math.min(3, scale * factor));
    tx = x - (x - tx) * next / scale;
    ty = y - (y - ty) * next / scale;
    scale = next;
    updateTransform();
  }
  svg.addEventListener('wheel', event => {
    event.preventDefault();
    const rect = svg.getBoundingClientRect();
    zoom(Math.exp(-event.deltaY * .0015), event.clientX - rect.left, event.clientY - rect.top);
  }, {passive:false});
  svg.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    moved = false; drag = {x:event.clientX, y:event.clientY, tx, ty};
  });
  svg.addEventListener('click', event => {
    if (!moved && (event.target === svg || event.target === viewport)) clearConnectionFocus();
  });
  window.addEventListener('pointermove', event => {
    if (itemDrag) {
      const dx = (event.clientX - itemDrag.x) / scale;
      const dy = (event.clientY - itemDrag.y) / scale;
      if (Math.abs(dx) + Math.abs(dy) > 4 / scale) moved = true;
      if (moved) {
        manualOffsets.set(itemDrag.id,
          {x:itemDrag.offsetX + dx, y:itemDrag.offsetY + dy});
        draw();
      }
      return;
    }
    if (!drag) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    if (moved) { tx = drag.tx + dx; ty = drag.ty + dy; updateTransform(); }
  });
  function finishPointerInteraction() {
    drag = null;
    itemDrag = null;
    viewport.classList.remove('item-dragging');
  }
  window.addEventListener('pointerup', finishPointerInteraction);
  window.addEventListener('pointercancel', finishPointerInteraction);
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape') clearConnectionFocus();
  });
  document.getElementById('fit').onclick = fit;
  document.getElementById('expand').onclick = () => { collapsed.clear(); draw(); fit(); };
  document.getElementById('collapse').onclick = () => {
    groups.filter(group => group.id !== rootGroupId).forEach(group => collapsed.add(group.id));
    draw(); fit();
  };
  for (const [id, factor] of [['plus', 1.2], ['minus', 1 / 1.2]]) {
    document.getElementById(id).onclick = () => {
      const rect = svg.getBoundingClientRect();
      zoom(factor, rect.width / 2, rect.height / 2);
    };
  }
  document.getElementById('search').oninput = event => {
    query = event.target.value.trim().toLowerCase();
    const candidates = [
      ...nodes.map(node => ({id:node.id, text:node.goal + ' ' + node.id})),
      ...groups.map(group => ({id:group.id, text:group.goal + ' ' + group.id + ' ' + group.label})),
    ];
    const matches = query ? candidates.filter(item => item.text.toLowerCase().includes(query)) : [];
    matches.forEach(item => expandFor(item.id));
    draw();
    document.getElementById('count').textContent = query ? `${matches.length} 个匹配` : '';
    if (matches.length) { select(matches[0].id); center(matches[0].id); }
  };
  document.querySelectorAll('.child-link').forEach(button => {
    button.onclick = () => reveal(button.dataset.task);
  });
  new ResizeObserver(() => fit()).observe(svg);
  draw();
  if (selected) select(selected, false);
  fit();
})();
