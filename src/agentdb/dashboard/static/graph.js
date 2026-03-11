/* ============================================================
   AgentDB Dashboard -- Canvas Service Dependency Graph
   ============================================================ */

(function () {
  "use strict";

  // ---- Configuration ----
  var COLORS = {
    ok:       "#b5bd68",
    degraded: "#f0c674",
    failed:   "#cc6666",
    edge:     "#404244",
    edgeFlow: "#81a2be",
    bg:       "#2c2e30",
    text:     "#c5c8c6",
    textDim:  "#8c8f93",
    nodeBg:   "#353739",
    selected: "#81a2be"
  };

  var NODE_RADIUS = 42;
  var LABEL_OFFSET = 56;

  // ---- Service nodes (diamond layout) ----
  var services = [
    { id: "power-grid",       label: "Power Grid",       status: "ok", load: 0.5, capacity: 1.0, x: 0, y: 0 },
    { id: "water-system",     label: "Water System",     status: "ok", load: 0.5, capacity: 1.0, x: 0, y: 0 },
    { id: "traffic-control",  label: "Traffic Control",  status: "ok", load: 0.5, capacity: 1.0, x: 0, y: 0 },
    { id: "comms-network",    label: "Comms Network",    status: "ok", load: 0.5, capacity: 1.0, x: 0, y: 0 }
  ];

  // Dependencies: from -> [to, ...]
  var edges = [
    { from: "power-grid",  to: "water-system" },
    { from: "power-grid",  to: "traffic-control" },
    { from: "power-grid",  to: "comms-network" },
    { from: "comms-network", to: "traffic-control" }
  ];

  var selectedService = null;
  var animationPhase = 0;
  var canvas, ctx;
  var dpr = 1;

  // ---- Layout ----

  function layoutNodes(w, h) {
    var cx = w / 2;
    var cy = h / 2;
    var rx = Math.min(w, h) * 0.3;
    var ry = Math.min(w, h) * 0.32;

    // Diamond: top, right, bottom, left
    services[0].x = cx;            services[0].y = cy - ry;        // power-grid (top)
    services[1].x = cx + rx;       services[1].y = cy;             // water-system (right)
    services[2].x = cx;            services[2].y = cy + ry;        // traffic-control (bottom)
    services[3].x = cx - rx;       services[3].y = cy;             // comms-network (left)
  }

  function findNode(id) {
    for (var i = 0; i < services.length; i++) {
      if (services[i].id === id) return services[i];
    }
    return null;
  }

  // ---- Drawing ----

  function draw() {
    if (!canvas || !ctx) return;

    var w = canvas.width / dpr;
    var h = canvas.height / dpr;

    ctx.save();
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, w, h);

    // Draw edges
    drawEdges(w, h);

    // Draw nodes
    for (var i = 0; i < services.length; i++) {
      drawNode(services[i]);
    }

    ctx.restore();

    animationPhase += 0.015;
    if (animationPhase > Math.PI * 2) animationPhase -= Math.PI * 2;

    requestAnimationFrame(draw);
  }

  function drawEdges() {
    for (var i = 0; i < edges.length; i++) {
      var fromNode = findNode(edges[i].from);
      var toNode   = findNode(edges[i].to);
      if (!fromNode || !toNode) continue;

      // Base edge line
      ctx.beginPath();
      ctx.moveTo(fromNode.x, fromNode.y);
      ctx.lineTo(toNode.x, toNode.y);
      ctx.strokeStyle = COLORS.edge;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Animated flow dot
      var t = (Math.sin(animationPhase + i * 1.2) + 1) / 2; // 0..1
      var fx = fromNode.x + (toNode.x - fromNode.x) * t;
      var fy = fromNode.y + (toNode.y - fromNode.y) * t;

      var flowColor = COLORS.edgeFlow;
      if (fromNode.status === "failed" || toNode.status === "failed") {
        flowColor = COLORS.failed;
      } else if (fromNode.status === "degraded" || toNode.status === "degraded") {
        flowColor = COLORS.degraded;
      }

      ctx.beginPath();
      ctx.arc(fx, fy, 3, 0, Math.PI * 2);
      ctx.fillStyle = flowColor;
      ctx.fill();

      // Direction arrow at midpoint
      var mx = (fromNode.x + toNode.x) / 2;
      var my = (fromNode.y + toNode.y) / 2;
      var angle = Math.atan2(toNode.y - fromNode.y, toNode.x - fromNode.x);
      drawArrow(mx, my, angle, 6, COLORS.edge);
    }
  }

  function drawArrow(x, y, angle, size, color) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.beginPath();
    ctx.moveTo(size, 0);
    ctx.lineTo(-size * 0.6, -size * 0.5);
    ctx.lineTo(-size * 0.6,  size * 0.5);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
  }

  function drawNode(node) {
    var isSelected = selectedService === node.id;

    // Outer ring (status color)
    var statusColor = COLORS[node.status] || COLORS.ok;

    // Glow for selected
    if (isSelected) {
      ctx.save();
      ctx.shadowColor = COLORS.selected;
      ctx.shadowBlur = 16;
      ctx.beginPath();
      ctx.arc(node.x, node.y, NODE_RADIUS + 2, 0, Math.PI * 2);
      ctx.strokeStyle = COLORS.selected;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
    }

    // Status ring
    ctx.beginPath();
    ctx.arc(node.x, node.y, NODE_RADIUS, 0, Math.PI * 2);
    ctx.strokeStyle = statusColor;
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.stroke();

    // Node background
    ctx.beginPath();
    ctx.arc(node.x, node.y, NODE_RADIUS - 2, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.nodeBg;
    ctx.fill();

    // Load arc (inner arc showing load %)
    if (node.load > 0) {
      var loadAngle = -Math.PI / 2 + Math.PI * 2 * Math.min(node.load, 1);
      ctx.beginPath();
      ctx.arc(node.x, node.y, NODE_RADIUS - 6, -Math.PI / 2, loadAngle);
      ctx.strokeStyle = statusColor;
      ctx.lineWidth = 3;
      ctx.globalAlpha = 0.3;
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // Status dot (small indicator inside the circle)
    ctx.beginPath();
    ctx.arc(node.x, node.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = statusColor;
    ctx.fill();

    // Label below node
    ctx.font = "500 11px 'JetBrains Mono', monospace";
    ctx.fillStyle = isSelected ? COLORS.selected : COLORS.text;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(node.label, node.x, node.y + LABEL_OFFSET);

    // Status text
    ctx.font = "400 9px 'JetBrains Mono', monospace";
    ctx.fillStyle = statusColor;
    ctx.fillText(node.status.toUpperCase(), node.x, node.y + LABEL_OFFSET + 15);
  }

  // ---- Interaction ----

  function handleClick(event) {
    var rect = canvas.getBoundingClientRect();
    var mx = event.clientX - rect.left;
    var my = event.clientY - rect.top;

    var clicked = null;
    for (var i = 0; i < services.length; i++) {
      var node = services[i];
      var dx = mx - node.x;
      var dy = my - node.y;
      if (dx * dx + dy * dy <= NODE_RADIUS * NODE_RADIUS) {
        clicked = node;
        break;
      }
    }

    if (clicked) {
      selectedService = clicked.id;
      if (typeof window.selectService === "function") {
        window.selectService(clicked.label, clicked.status, clicked.load, clicked.capacity);
      }
    } else {
      selectedService = null;
    }
  }

  // ---- Public API (called from app.js) ----

  window.updateServiceNode = function (id, status, load, capacity) {
    var node = findNode(id);
    if (!node) return;
    node.status   = status   || node.status;
    node.load     = load     != null ? load     : node.load;
    node.capacity = capacity != null ? capacity : node.capacity;
  };

  // ---- Resize ----

  function resize() {
    var container = canvas.parentElement;
    var w = container.clientWidth;
    var h = container.clientHeight;

    dpr = window.devicePixelRatio || 1;
    canvas.width  = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width  = w + "px";
    canvas.style.height = h + "px";

    layoutNodes(w, h);
  }

  // ---- Init ----

  function init() {
    canvas = document.getElementById("cityCanvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    canvas.addEventListener("click", handleClick);
    window.addEventListener("resize", resize);

    resize();
    draw();
  }

  // Wait for DOM
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
