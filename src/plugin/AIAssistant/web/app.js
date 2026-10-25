(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var token = params.get("t") || sessionStorage.getItem("aiToken") || "";
  if (params.get("t")) {
    sessionStorage.setItem("aiToken", token);
    history.replaceState(null, "", location.pathname);
  }

  var $ = function (id) { return document.getElementById(id); };
  var log = $("log"), textBox = $("text"), sendBtn = $("send");
  var nextEvent = 0, busy = false, scenario = -1, uploads = [];

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({ "X-Token": token, "Content-Type": "application/json" }, options.headers || {});
    return fetch(path, options).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) { throw new Error(body.error || ("HTTP " + response.status)); }
        return body;
      });
    });
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  // мини-разметка markdown
  function render(text) {
    var html = "", list = null;
    function close() { if (list) { html += "</" + list + ">"; list = null; } }
    escapeHtml(text).split("\n").forEach(function (raw) {
      var line = raw.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
      var bullet = /^\s*[-*]\s+(.*)/.exec(line), number = /^\s*\d+[.)]\s+(.*)/.exec(line);
      if (bullet || number) {
        var kind = bullet ? "ul" : "ol";
        if (list !== kind) { close(); html += "<" + kind + ">"; list = kind; }
        html += "<li>" + (bullet || number)[1] + "</li>";
      } else if (line.trim()) {
        close(); html += "<p>" + line + "</p>";
      } else { close(); }
    });
    close();
    return html;
  }

  function scroll() { log.scrollTop = log.scrollHeight; }
  function add(node) { $("empty").hidden = true; log.appendChild(node); scroll(); return node; }

  function addMessage(kind, text, extra) {
    var node = document.createElement("div");
    node.className = "msg " + kind;
    node.innerHTML = render(text) + (extra ? '<div class="files-note">' + escapeHtml(extra) + "</div>" : "");
    return add(node);
  }

  function addTool(event) {
    var node = document.createElement("details");
    node.className = "tool";
    node.id = "tool-" + event.id;
    var args = Object.keys(event.arguments || {}).map(function (k) { return k + "=" + JSON.stringify(event.arguments[k]); }).join(", ");
    node.innerHTML = '<summary><span class="name"></span><span class="status">выполняется…</span></summary><pre></pre>';
    node.querySelector(".name").textContent = event.name + (args ? "(" + args.slice(0, 90) + ")" : "()");
    node.querySelector("pre").textContent = JSON.stringify(event.arguments || {}, null, 2);
    add(node);
    lastTool = node;
  }
  var lastTool = null;

  function finishTool(event) {
    if (!lastTool) { return; }
    lastTool.classList.add(event.ok ? "ok" : "fail");
    lastTool.querySelector(".status").textContent = event.ok ? "готово" : "ошибка";
    lastTool.querySelector("pre").textContent += "\n\n→ " + event.text;
    if (event.ok && (event.name === "export_gcode" || event.name === "save_project")) {
      try { addFile(JSON.parse(event.text).path); } catch (e) { /* не путь */ }
    }
  }

  var shownFiles = {};
  function addFile(path) {
    if (!path || shownFiles[path]) { return; }
    shownFiles[path] = true;
    var item = document.createElement("li"), link = document.createElement("a");
    link.href = "/download?t=" + encodeURIComponent(token) + "&path=" + encodeURIComponent(path);
    link.textContent = path.split(/[\\/]/).pop();
    link.download = link.textContent;
    item.appendChild(link);
    $("files").appendChild(item);
  }

  function showChanges(changes) {
    var box = $("changes");
    if (!changes.length) { box.innerHTML = '<p class="muted">Пока ничего не менялось.</p>'; return; }
    box.innerHTML = "";
    changes.forEach(function (c) {
      var row = document.createElement("div");
      row.className = "change";
      row.innerHTML = '<div><span class="name"></span>: <span class="old"></span> → <span class="new"></span></div><div class="why"></div>';
      row.querySelector(".name").textContent = c.name;
      row.querySelector(".old").textContent = String(c.old);
      row.querySelector(".new").textContent = String(c["new"]);
      row.querySelector(".why").textContent = c.reason || "";
      box.appendChild(row);
    });
  }

  function handle(event) {
    if (event.type === "user") {
      addMessage("user", event.text, event.attachments.length ? "Файлы: " + event.attachments.map(function (a) { return a.name; }).join(", ") : "");
    } else if (event.type === "assistant") {
      if (event.text) { addMessage("assistant", event.text); }
    } else if (event.type === "tool_call") {
      addTool(event);
    } else if (event.type === "tool_result") {
      finishTool(event);
    } else if (event.type === "changes") {
      showChanges(event.changes);
    } else if (event.type === "error") {
      var node = document.createElement("div");
      node.className = "err";
      node.setAttribute("role", "alert");
      node.textContent = event.text;
      add(node);
    }
  }

  function setBusy(value) {
    busy = value;
    $("thinking").hidden = !value;
    sendBtn.disabled = value;
  }

  function poll() {
    api("/api/events?after=" + nextEvent).then(function (data) {
      data.events.forEach(handle);
      nextEvent = data.next;
      setBusy(data.busy);
    }).catch(function (error) { banner(error.message, true); }).then(function () { setTimeout(poll, busy ? 500 : 900); });
  }

  var MODES = { classic: "3D", cylindrical: "5D Spiral", cylindrical_full: "5D" };
  function refreshState() {
    if (document.hidden) { return; }
    api("/api/state").then(function (data) {
      var s = data.printer, state = $("state");
      $("printer").textContent = s ? s.printer : "принтер не выбран";
      state.innerHTML = "";
      if (s) {
        [["Режим", MODES[s.print_mode] || s.print_mode], ["Материал", s.material_id], ["Профиль", s.quality],
         ["Слой, мм", s.settings.layer_height], ["Заполнение, %", s.settings.infill_sparse_density],
         ["Поддержки", s.settings.support_enable ? "да" : "нет"],
         ["Модели", s.models.length ? s.models.map(function (m) { return m.name + " (" + m.size_mm.x + "×" + m.size_mm.y_depth + "×" + m.size_mm.z_height + " мм)"; }).join("; ") : "нет"]
        ].forEach(function (pair) {
          var dt = document.createElement("dt"), dd = document.createElement("dd");
          dt.textContent = pair[0]; dd.textContent = pair[1] === undefined || pair[1] === null ? "—" : pair[1];
          state.appendChild(dt); state.appendChild(dd);
        });
      }
      var sl = data.slicing;
      $("bar").style.width = sl ? Math.round(sl.progress * 100) + "%" : "0";
      var labels = { not_started: "Не запускался.", processing: "Идёт нарезка…", done: "Готово.", error: "Ошибка слайсинга.", disabled: "Слайсинг отключён." };
      $("slicing").textContent = sl ? (labels[sl.state] || sl.state) + (sl.print_time ? " Время печати: " + sl.print_time + ", материал: " + sl.material_grams + " г." : "") : "—";
      if (!busy) { showChanges(data.changes); }
    }).catch(function () { /* ошибку покажет опрос */ });
  }

  function banner(message, isError) {
    var node = $("banner");
    node.hidden = !message;
    node.textContent = message || "";
    node.className = "banner" + (isError ? " error" : "");
  }

  // сценарии
  function loadScenarios() {
    api("/api/scenarios").then(function (list) {
      var box = $("scenarios");
      list.forEach(function (item, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = item.title;
        button.addEventListener("click", function () {
          scenario = index;
          Array.prototype.forEach.call(box.children, function (b) { b.classList.remove("active"); });
          button.classList.add("active");
          textBox.value = item.prompt;
          textBox.focus();
        });
        box.appendChild(button);
      });
    });
  }

  // файлы
  function readBase64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result).split(",")[1]); };
      reader.onerror = function () { reject(new Error("Не удалось прочитать файл " + file.name)); };
      reader.readAsDataURL(file);
    });
  }

  function attach(files) {
    Array.prototype.forEach.call(files, function (file) {
      readBase64(file).then(function (data) {
        return api("/api/upload", { method: "POST", body: JSON.stringify({ name: file.name, data: data }) });
      }).then(function (info) {
        uploads.push(info);
        renderAttachments(file);
      }).catch(function (error) { banner(error.message, true); });
    });
  }

  function renderAttachments(source) {
    var box = $("attachments");
    box.innerHTML = "";
    uploads.forEach(function (item, index) {
      var chip = document.createElement("span");
      chip.className = "file";
      if (item.kind === "image" && (source || item.preview)) {
        item.preview = item.preview || URL.createObjectURL(source);
        var image = document.createElement("img");
        image.src = item.preview; image.alt = "";
        chip.appendChild(image);
      }
      var name = document.createElement("span");
      name.textContent = item.name;
      var remove = document.createElement("button");
      remove.type = "button"; remove.textContent = "×"; remove.setAttribute("aria-label", "Убрать " + item.name);
      remove.addEventListener("click", function () { uploads.splice(index, 1); renderAttachments(); });
      chip.appendChild(name); chip.appendChild(remove);
      box.appendChild(chip);
    });
  }

  $("attach").addEventListener("click", function () { $("file").click(); });
  $("file").addEventListener("change", function (e) { attach(e.target.files); e.target.value = ""; });
  var chat = document.querySelector(".chat");
  ["dragenter", "dragover"].forEach(function (name) {
    chat.addEventListener(name, function (e) { e.preventDefault(); chat.classList.add("drag"); });
  });
  ["dragleave", "drop"].forEach(function (name) {
    chat.addEventListener(name, function (e) { e.preventDefault(); chat.classList.remove("drag"); });
  });
  chat.addEventListener("drop", function (e) { attach(e.dataTransfer.files); });

  // отправка
  $("composer").addEventListener("submit", function (e) {
    e.preventDefault();
    var text = textBox.value.trim();
    if (!text || busy) { return; }
    banner("");
    setBusy(true);
    api("/api/chat", { method: "POST", body: JSON.stringify({ text: text, uploads: uploads.map(function (u) { return u.id; }), scenario: scenario }) })
      .then(function () { textBox.value = ""; uploads = []; renderAttachments(); })
      .catch(function (error) { setBusy(false); banner(error.message, true); });
  });
  textBox.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); }
  });
  $("reset").addEventListener("click", function () {
    api("/api/reset", { method: "POST", body: "{}" }).then(function () {
      Array.prototype.slice.call(log.children).forEach(function (n) { if (n.id !== "empty") { n.remove(); } });
      $("empty").hidden = false; nextEvent = 0; shownFiles = {}; $("files").innerHTML = ""; showChanges([]); lastTool = null;
    });
  });

  // настройки
  var dialog = $("settings");
  function openSettings() {
    api("/api/config").then(function (c) {
      $("cfg-url").value = c.base_url; $("cfg-model").value = c.model;
      $("cfg-key").value = ""; $("cfg-key").placeholder = c.has_key ? "ключ сохранён, оставьте пустым чтобы не менять" : "ключ";
      dialog.showModal();
    });
  }
  $("open-settings").addEventListener("click", openSettings);
  $("cfg-save").addEventListener("click", function () {
    api("/api/config", { method: "POST", body: JSON.stringify({ base_url: $("cfg-url").value, model: $("cfg-model").value, api_key: $("cfg-key").value }) })
      .then(function () { dialog.close(); checkConfig(); })
      .catch(function (error) { banner(error.message, true); });
  });

  function checkConfig() {
    api("/api/config").then(function (c) {
      banner(c.has_key ? "" : "Введите API key в настройках, чтобы начать работу.", false);
    });
  }

  loadScenarios();
  checkConfig();
  poll();
  refreshState();
  setInterval(refreshState, 2000);
})();
