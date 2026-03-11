/* ============================================================
   AgentDB Dashboard -- Tabbed Detail Panel (Alpine.js)
   ============================================================ */

document.addEventListener("alpine:init", function () {

  var AGENT_COLORS = {
    mayor: "#81a2be",
    engineer: "#b294bb",
    monitor: "#b5bd68",
    fixer: "#f0c674"
  };

  var MAX_CONVERSATIONS = 50;
  var MAX_DIFFS = 20;

  Alpine.data("detailPanel", function () {
    return {
      tab: "conversations",
      conversations: [],
      diffs: [],
      fsTree: {},
      selectedFile: null,
      fileContent: null,
      serviceDetail: null,

      init: function () {
        var self = this;

        window.addEventListener("agentdb:agent-message", function (e) {
          self.conversations.unshift(e.detail);
          if (self.conversations.length > MAX_CONVERSATIONS) {
            self.conversations.pop();
          }
        });

        window.addEventListener("agentdb:code-diff", function (e) {
          self.diffs.unshift(e.detail);
          if (self.diffs.length > MAX_DIFFS) {
            self.diffs.pop();
          }
        });

        window.addEventListener("agentdb:fs-snapshot", function (e) {
          self.fsTree = e.detail.tree || {};
        });

        window.addEventListener("agentdb:fs-change", function (e) {
          self.applyFsChange(e.detail);
        });
      },

      // --- Tab switching ---
      switchTab: function (name) {
        this.tab = name;
      },

      // --- Agent colors ---
      agentColor: function (name) {
        return AGENT_COLORS[name] || "#8c8f93";
      },

      // --- Diff computation ---
      computeDiff: function (oldContent, newContent) {
        var oldLines = (oldContent || "").split("\n");
        var newLines = (newContent || "").split("\n");
        var result = [];
        var maxLen = Math.max(oldLines.length, newLines.length);

        for (var i = 0; i < maxLen; i++) {
          var oldLine = i < oldLines.length ? oldLines[i] : null;
          var newLine = i < newLines.length ? newLines[i] : null;

          if (oldLine === newLine) {
            result.push({ type: "same", text: " " + (oldLine || "") });
          } else {
            if (oldLine !== null) {
              result.push({ type: "removed", text: "-" + oldLine });
            }
            if (newLine !== null) {
              result.push({ type: "added", text: "+" + newLine });
            }
          }
        }
        return result;
      },

      // --- Filesystem tree ---
      applyFsChange: function (data) {
        var parts = data.path.replace(/^\//, "").split("/");
        if (data.action === "write") {
          var node = this.fsTree;
          for (var i = 0; i < parts.length - 1; i++) {
            if (!node[parts[i]] || typeof node[parts[i]] !== "object") {
              node[parts[i]] = {};
            }
            node = node[parts[i]];
          }
          node[parts[parts.length - 1]] = data.size || 0;
        } else if (data.action === "delete") {
          var node = this.fsTree;
          for (var i = 0; i < parts.length - 1; i++) {
            if (!node[parts[i]]) return;
            node = node[parts[i]];
          }
          delete node[parts[parts.length - 1]];
        }
        // Trigger flash animation via DOM
        this.$nextTick(function () {
          var el = document.querySelector('[data-fspath="' + data.path + '"]');
          if (el) {
            el.classList.remove("fs-flash-write", "fs-flash-delete");
            void el.offsetWidth; // force reflow
            el.classList.add(data.action === "write" ? "fs-flash-write" : "fs-flash-delete");
          }
        });
      },

      sortedEntries: function (obj) {
        if (!obj || typeof obj !== "object") return [];
        var entries = Object.entries(obj);
        // Directories first, then files, both alphabetical
        entries.sort(function (a, b) {
          var aIsDir = typeof a[1] === "object";
          var bIsDir = typeof b[1] === "object";
          if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
          return a[0].localeCompare(b[0]);
        });
        return entries;
      },

      isDir: function (value) {
        return typeof value === "object" && value !== null;
      },

      loadFile: function (path) {
        var self = this;
        self.selectedFile = path;
        self.fileContent = "Loading...";
        fetch("/api/file?path=" + encodeURIComponent(path))
          .then(function (r) {
            if (!r.ok) throw new Error("Not found");
            return r.text();
          })
          .then(function (text) { self.fileContent = text; })
          .catch(function () { self.fileContent = "Error loading file"; });
      },

      // --- Service Detail (replaces window.selectService) ---
      selectService: function (name, status, load, capacity) {
        this.serviceDetail = {
          name: name,
          status: status,
          load: load,
          capacity: capacity,
          health: capacity > 0 ? Math.min(100, ((capacity - load) / capacity * 100)).toFixed(0) : 0
        };
        this.tab = "service";
      }
    };
  });

  // Expose selectService globally for graph.js compatibility
  window.selectService = function (name, status, load, capacity) {
    var el = document.querySelector("[x-data]");
    if (el && el.__x) {
      el.__x.$data.selectService(name, status, load, capacity);
    } else {
      // Alpine v3: use $data from the component
      var component = Alpine.$data(document.querySelector(".panel-detail"));
      if (component) {
        component.selectService(name, status, load, capacity);
      }
    }
  };

  // Cross-linking: clicking agent card switches to conversations
  document.querySelectorAll(".agent-card").forEach(function (card) {
    card.addEventListener("click", function () {
      var component = Alpine.$data(document.querySelector(".panel-detail"));
      if (component) {
        component.tab = "conversations";
      }
    });
  });
});
