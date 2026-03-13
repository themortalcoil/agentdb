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

  // ---- Service nodes (populated from /api/topology) ----
  var services = [];
  var edges = [];

  var selectedService = null;
  var animationPhase = 0;
  var canvas, ctx;
  var dpr = 1;

  // ---- Layout ----

  function layoutNodes(w, h) {
    var cx = w / 2;
    var cy = h / 2;
    var r = Math.min(w, h) * 0.3;

    for (var i = 0; i < services.length; i++) {
      var angle = -Math.PI / 2 + (2 * Math.PI * i) / services.length;
      services[i].x = cx + r * Math.cos(angle);
      services[i].y = cy + r * Math.sin(angle);
    }
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

      // Cascade pulse animation (0.4s travel + 2s red highlight)
      if (edges[i].cascadeStart > 0) {
        var cascadeElapsed = (performance.now() - edges[i].cascadeStart) / 1000;

        if (cascadeElapsed < 2.4) {
          var edgeAlpha = cascadeElapsed < 0.4 ? 1.0 : Math.max(0, 1 - (cascadeElapsed - 0.4) / 2);
          ctx.beginPath();
          ctx.moveTo(fromNode.x, fromNode.y);
          ctx.lineTo(toNode.x, toNode.y);
          ctx.strokeStyle = COLORS.failed;
          ctx.lineWidth = 3;
          ctx.globalAlpha = edgeAlpha;
          ctx.stroke();
          ctx.globalAlpha = 1.0;

          if (cascadeElapsed < 0.4) {
            var pt = cascadeElapsed / 0.4;
            var px = fromNode.x + (toNode.x - fromNode.x) * pt;
            var py = fromNode.y + (toNode.y - fromNode.y) * pt;
            ctx.beginPath();
            ctx.arc(px, py, 5, 0, Math.PI * 2);
            ctx.fillStyle = COLORS.failed;
            ctx.fill();
          }
        } else {
          edges[i].cascadeStart = 0;
        }
      }

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

  function dampedSine(t, freq, decay) {
    return Math.sin(t * freq) * Math.exp(-t * decay);
  }

  function drawNode(node) {
    var isSelected = selectedService === node.id;
    var now = performance.now();
    var offsetX = 0;

    // Shake animation (failed transition, 0.5s)
    if (node.shakeStart > 0) {
      var elapsed = (now - node.shakeStart) / 1000;
      if (elapsed < 0.5) {
        offsetX = dampedSine(elapsed, 40, 6) * 3;
      } else {
        node.shakeStart = 0;
      }
    }

    var drawX = node.x + offsetX;
    var drawY = node.y;

    // Glow animation (failed transition, 3s fade)
    if (node.glowStart > 0) {
      var glowElapsed = (now - node.glowStart) / 1000;
      if (glowElapsed < 3) {
        var glowAlpha = 0.4 * (1 - glowElapsed / 3);
        ctx.save();
        var gradient = ctx.createRadialGradient(
          drawX, drawY, NODE_RADIUS,
          drawX, drawY, NODE_RADIUS + 20
        );
        gradient.addColorStop(0, node.glowColor || COLORS.failed);
        gradient.addColorStop(1, "transparent");
        ctx.globalAlpha = glowAlpha;
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(drawX, drawY, NODE_RADIUS + 20, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } else {
        node.glowStart = 0;
      }
    }

    // Pulse scale (degraded, continuous 2s cycle)
    var pulseScale = 1.0;
    if (node.status === "degraded" && node.pulseStart > 0) {
      var pulseT = ((now - node.pulseStart) / 1000) % 2;
      pulseScale = 1 + 0.08 * Math.sin(pulseT * Math.PI);
    }

    // Recovery flash (ok after failure/degraded, 0.3s)
    if (node.recoveryStart > 0) {
      var recElapsed = (now - node.recoveryStart) / 1000;
      if (recElapsed < 0.3) {
        ctx.save();
        ctx.globalAlpha = 0.5 * (1 - recElapsed / 0.3);
        ctx.fillStyle = COLORS.ok;
        ctx.beginPath();
        ctx.arc(drawX, drawY, NODE_RADIUS + 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } else {
        node.recoveryStart = 0;
      }
    }

    var statusColor = COLORS[node.status] || COLORS.ok;
    var scaledRadius = NODE_RADIUS * pulseScale;

    // Glow for selected
    if (isSelected) {
      ctx.save();
      ctx.shadowColor = COLORS.selected;
      ctx.shadowBlur = 16;
      ctx.beginPath();
      ctx.arc(drawX, drawY, scaledRadius + 2, 0, Math.PI * 2);
      ctx.strokeStyle = COLORS.selected;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
    }

    // Status ring
    ctx.beginPath();
    ctx.arc(drawX, drawY, scaledRadius, 0, Math.PI * 2);
    ctx.strokeStyle = statusColor;
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.stroke();

    // Node background
    ctx.beginPath();
    ctx.arc(drawX, drawY, scaledRadius - 2, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.nodeBg;
    ctx.fill();

    // Load arc
    if (node.load > 0) {
      var loadAngle = -Math.PI / 2 + Math.PI * 2 * Math.min(node.load, 1);
      ctx.beginPath();
      ctx.arc(drawX, drawY, scaledRadius - 6, -Math.PI / 2, loadAngle);
      ctx.strokeStyle = statusColor;
      ctx.lineWidth = 3;
      ctx.globalAlpha = 0.3;
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // Status dot
    ctx.beginPath();
    ctx.arc(drawX, drawY, 5, 0, Math.PI * 2);
    ctx.fillStyle = statusColor;
    ctx.fill();

    // Label
    ctx.font = "500 11px 'JetBrains Mono', monospace";
    ctx.fillStyle = isSelected ? COLORS.selected : COLORS.text;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(node.label, drawX, drawY + LABEL_OFFSET);

    // Status text
    ctx.font = "400 9px 'JetBrains Mono', monospace";
    ctx.fillStyle = statusColor;
    ctx.fillText(node.status.toUpperCase(), drawX, drawY + LABEL_OFFSET + 15);

    // Agent presence dots
    if (node.agentDots.length > 0) {
      for (var ai = 0; ai < node.agentDots.length; ai++) {
        var dot = node.agentDots[ai];
        var dotAngle = -Math.PI / 2 + (ai * Math.PI * 2) / Math.max(node.agentDots.length, 4);
        var dotX = drawX + (NODE_RADIUS + 12) * Math.cos(dotAngle);
        var dotY = drawY + (NODE_RADIUS + 12) * Math.sin(dotAngle);

        ctx.beginPath();
        ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
        ctx.fillStyle = dot.color;
        ctx.fill();
        ctx.strokeStyle = COLORS.bg;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
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
      window.dispatchEvent(new CustomEvent("agentdb:service-selected", {
        detail: { service: clicked.id, label: clicked.label }
      }));
    } else {
      selectedService = null;
      window.dispatchEvent(new CustomEvent("agentdb:service-selected", {
        detail: { service: null, label: null }
      }));
    }
  }

  // ---- Public API (called from app.js) ----

  window.updateServiceNode = function (id, status, load, capacity) {
    var node = findNode(id);
    if (!node) return;

    var oldStatus = node.status;
    node.status   = status   || node.status;
    node.load     = load     != null ? load     : node.load;
    node.capacity = capacity != null ? capacity : node.capacity;

    var now = performance.now();
    if (oldStatus !== node.status) {
      node.prevStatus = oldStatus;
      if (node.status === "failed") {
        node.shakeStart = now;
        node.glowStart = now;
        node.glowColor = COLORS.failed;
      } else if (node.status === "degraded" && oldStatus === "ok") {
        node.pulseStart = now;
      } else if (node.status === "ok" && oldStatus !== "ok") {
        node.recoveryStart = now;
      }
    }
  };

  var AGENT_COLORS = {
    mayor: "#81a2be",
    engineer: "#b294bb",
    monitor: "#b5bd68",
    fixer: "#f0c674"
  };

  window.updateAgentPresence = function (agentName, serviceId) {
    for (var i = 0; i < services.length; i++) {
      services[i].agentDots = services[i].agentDots.filter(function (d) {
        return d.agent !== agentName;
      });
    }
    if (serviceId) {
      var node = findNode(serviceId);
      if (node) {
        node.agentDots.push({
          agent: agentName,
          color: AGENT_COLORS[agentName] || "#8c8f93",
          startTime: performance.now()
        });
      }
    }
  };

  window.triggerCascadeEdge = function (sourceId, targetId) {
    for (var i = 0; i < edges.length; i++) {
      if (edges[i].from === sourceId && edges[i].to === targetId) {
        edges[i].cascadeStart = performance.now();
        edges[i].cascadeColor = COLORS.failed;
        return;
      }
    }
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

    // Fetch topology from API, then start rendering
    fetch("/api/topology")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        services = data.services.map(function (id) {
          return {
            id: id,
            label: id.split("-").map(function (w) {
              return w.charAt(0).toUpperCase() + w.slice(1);
            }).join(" "),
            status: "ok",
            prevStatus: "ok",
            load: 0.5,
            capacity: data.capacities[id] || 1.0,
            x: 0,
            y: 0,
            // Transition animation state
            shakeStart: 0,
            glowStart: 0,
            glowColor: null,
            pulseStart: 0,
            recoveryStart: 0,
            agentDots: []
          };
        });

        // Convert edges dict {child: [parents]} to [{from: parent, to: child}]
        edges = [];
        Object.keys(data.edges).forEach(function (child) {
          data.edges[child].forEach(function (parent) {
            edges.push({
              from: parent,
              to: child,
              cascadeStart: 0,
              cascadeColor: null
            });
          });
        });

        resize();
        draw();
      })
      .catch(function (err) {
        console.error("Failed to load topology:", err);
      });
  }

  // Wait for DOM
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
