/* ============================================================
   AgentDB Dashboard -- WebSocket Client & DOM Controller
   ============================================================ */

(function () {
  "use strict";

  // ---- State ----
  let ws = null;
  let paused = false;
  let totalEvents = 0;
  let reconnectTimer = null;
  var agentTimers = {};
  const RECONNECT_DELAY_MS = 2000;
  const MAX_FEED_ENTRIES = 200;

  // ---- DOM refs ----
  const tickCounter      = document.getElementById("tickCounter");
  const pauseBtn         = document.getElementById("pauseBtn");
  const pauseIcon        = document.getElementById("pauseIcon");
  const pauseLabel       = document.getElementById("pauseLabel");
  const activityFeed     = document.getElementById("activityFeed");
  const connectionStatus = document.getElementById("connectionStatus");
  const eventCount       = document.getElementById("eventCount");
  const timelineProgress = document.getElementById("timelineProgress");

  // ---- WebSocket ----

  function connect() {
    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var url = protocol + "//" + location.host + "/ws";

    ws = new WebSocket(url);

    ws.onopen = function () {
      setConnectionStatus(true);
      console.log("[ws] connected");
    };

    ws.onclose = function () {
      setConnectionStatus(false);
      console.log("[ws] disconnected, reconnecting...");
      scheduleReconnect();
    };

    ws.onerror = function (e) {
      console.error("[ws] error:", e);
      ws.close();
    };

    ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error("[ws] bad message:", e);
      }
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
  }

  function setConnectionStatus(connected) {
    var dot   = connectionStatus.querySelector(".status-dot");
    var label = connectionStatus.querySelector(".status-label");
    if (connected) {
      dot.className = "status-dot connected";
      label.textContent = "Connected";
    } else {
      dot.className = "status-dot disconnected";
      label.textContent = "Disconnected";
    }
  }

  function sendAction(action) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: action }));
    }
  }

  // ---- Message handlers ----

  function handleMessage(msg) {
    switch (msg.type) {
      case "tick":
        handleTick(msg.data);
        break;
      case "city_event":
        handleCityEvent(msg.data);
        break;
      case "agent_update":
        handleAgentUpdate(msg.data);
        break;
      case "agent_message":
        window.dispatchEvent(new CustomEvent("agentdb:agent-message", { detail: msg.data }));
        break;
      case "code_diff":
        window.dispatchEvent(new CustomEvent("agentdb:code-diff", { detail: msg.data }));
        break;
      case "fs_change":
        window.dispatchEvent(new CustomEvent("agentdb:fs-change", { detail: msg.data }));
        break;
      case "fs_snapshot":
        window.dispatchEvent(new CustomEvent("agentdb:fs-snapshot", { detail: msg.data }));
        break;
      default:
        console.log("[ws] unknown type:", msg.type);
    }
  }

  function handleTick(data) {
    var tick = data.tick || 0;
    tickCounter.textContent = tick;

    // Update timeline -- loops every 100 ticks
    var pct = (tick % 100);
    timelineProgress.style.width = pct + "%";

    // Update service states if present
    if (data.services) {
      var serviceNames = Object.keys(data.services);
      for (var i = 0; i < serviceNames.length; i++) {
        var name = serviceNames[i];
        var info = data.services[name];
        if (typeof updateServiceNode === "function") {
          updateServiceNode(name, info.status, info.load, info.capacity);
        }
      }
    }
  }

  function handleCityEvent(data) {
    totalEvents++;
    eventCount.textContent = totalEvents + " event" + (totalEvents !== 1 ? "s" : "");
    addFeedEntry(data);
  }

  function handleAgentUpdate(data) {
    var agent = data.agent;
    if (!agent) return;

    var energyBar = document.getElementById("energy-" + agent);
    var statusText = document.getElementById("status-" + agent);
    if (!energyBar || !statusText) return;

    // Update energy bar
    var energy = data.energy != null ? data.energy : 100;
    energyBar.style.width = energy + "%";
    energyBar.className = "energy-bar";
    if (energy < 30) {
      energyBar.classList.add("low");
    } else if (energy < 60) {
      energyBar.classList.add("medium");
    }

    // Cancel any pending revert timer for this agent
    if (agentTimers[agent]) {
      clearTimeout(agentTimers[agent]);
      agentTimers[agent] = null;
    }

    // Update status text
    var status = data.status || "idle";
    statusText.textContent = status;
    statusText.className = "agent-status-text";
    if (status === "active" || status === "working") {
      statusText.classList.add("active");
    } else if (status === "busy" || status === "repairing") {
      statusText.classList.add("busy");
    } else if (status === "error") {
      statusText.classList.add("error");
    } else if (status === "acted") {
      statusText.classList.add("active");
      // Revert to idle after a few seconds
      agentTimers[agent] = setTimeout(function () {
        statusText.textContent = "idle";
        statusText.className = "agent-status-text";
        agentTimers[agent] = null;
      }, 8000);
    }
  }

  // ---- Activity Feed ----

  function addFeedEntry(data) {
    // Remove placeholder
    var placeholder = activityFeed.querySelector(".feed-empty");
    if (placeholder) placeholder.remove();

    var entry = document.createElement("div");
    entry.className = "feed-entry";

    var severity = (data.severity || "low").toLowerCase();
    var service  = data.service || "system";
    var message  = data.message || "Unknown event";
    var tick     = data.tick || tickCounter.textContent;

    // Build entry using safe DOM methods (no innerHTML)
    var tickSpan = document.createElement("span");
    tickSpan.className = "feed-tick";
    tickSpan.textContent = "#" + tick;

    var sevSpan = document.createElement("span");
    sevSpan.className = "feed-severity " + severity;

    var msgSpan = document.createElement("span");
    msgSpan.className = "feed-message";

    var svcSpan = document.createElement("span");
    svcSpan.className = "feed-service";
    svcSpan.textContent = "[" + service + "]";

    msgSpan.appendChild(svcSpan);
    msgSpan.appendChild(document.createTextNode(" " + message));

    entry.appendChild(tickSpan);
    entry.appendChild(sevSpan);
    entry.appendChild(msgSpan);

    // Prepend (newest first)
    activityFeed.insertBefore(entry, activityFeed.firstChild);

    // Trim old entries
    while (activityFeed.children.length > MAX_FEED_ENTRIES) {
      activityFeed.removeChild(activityFeed.lastChild);
    }
  }

  // ---- Pause / Resume ----

  window.togglePause = function () {
    paused = !paused;
    if (paused) {
      pauseIcon.textContent = "\u25B6";
      pauseLabel.textContent = "Resume";
      sendAction("pause");
    } else {
      pauseIcon.textContent = "\u23F8";
      pauseLabel.textContent = "Pause";
      sendAction("resume");
    }
  };

  // ---- Clear Feed ----

  window.clearFeed = function () {
    while (activityFeed.firstChild) {
      activityFeed.removeChild(activityFeed.firstChild);
    }
    var empty = document.createElement("div");
    empty.className = "feed-empty";
    empty.textContent = "Waiting for events...";
    activityFeed.appendChild(empty);
  };

  // ---- Init ----
  connect();

})();
