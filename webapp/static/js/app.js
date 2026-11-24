/* 抽烟检测监控系统 · M1 骨架脚本：标签切换 + /api/health 轮询 + 顶部时钟（原生 JS，无第三方依赖） */
(function () {
  "use strict";

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }
  function $all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }
  function setText(selector, text) {
    var el = $(selector);
    if (el) { el.textContent = text; }
  }

  /* ---------- 标签页切换（disabled 的 P1 标签不切换） ---------- */
  $all(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.disabled) { return; }
      var target = btn.getAttribute("data-tab");
      $all(".tab-btn").forEach(function (b) { b.classList.toggle("active", b === btn); });
      $all(".tab-panel").forEach(function (panel) {
        panel.hidden = panel.id !== "panel-" + target;
      });
    });
  });

  /* ---------- 顶部时钟 ---------- */
  function tickClock() {
    var el = $("#clock");
    if (!el) { return; }
    try {
      el.textContent = new Date().toLocaleString("zh-CN", { hour12: false });
    } catch (e) {
      el.textContent = new Date().toLocaleTimeString();
    }
  }
  tickClock();
  setInterval(tickClock, 1000);

  /* ---------- 健康检查 ---------- */
  var badge = $("#db-badge");
  var dot = $("#status-dot");
  var detail = $("#health-detail");

  function renderBadge(text, cls, dotCls) {
    if (badge) { badge.textContent = text; badge.className = "badge " + cls; }
    if (dot) { dot.className = "status-dot " + dotCls; }
  }

  async function refreshHealth() {
    var json = null;
    try {
      var resp = await fetch("/api/health", { cache: "no-store" });
      json = await resp.json();
    } catch (networkErr) {
      renderBadge("后端不可达", "badge-err", "dot-err");
      if (detail) { detail.textContent = "无法连接 Flask 服务（/api/health），请确认 python run_web.py 正在运行。"; }
      setText("#h-dbok", "不可达");
      return;
    }

    var d = (json && json.data) || {};
    if (d.db_ok) {
      if (d.db_driver === "mysql") {
        renderBadge("MySQL 已连接", "badge-ok", "dot-ok");
      } else if (d.db_driver === "sqlite") {
        renderBadge("SQLite 应急库", "badge-warn", "dot-ok");
      } else {
        renderBadge("数据库已连接 (" + d.db_driver + ")", "badge-warn", "dot-ok");
      }
      if (detail) {
        detail.textContent = "服务正常 · 数据库驱动=" + d.db_driver + " · 版本=" + (d.version || "-") +
          " · 监听=" + (d.web_host || "-") + ":" + (d.web_port || "-");
      }
      setText("#h-dbok", "正常（SELECT 1 通过）");
    } else {
      renderBadge("数据库未连接", "badge-err", "dot-err");
      if (detail) {
        detail.textContent = "数据库异常：" + (d.db_error || json.msg || "未知错误") +
          "。Web 进程仍在运行，可按部署文档排查 Docker 容器 / 端口 / .env，或使用应急 SQLite 连接串。";
      }
      setText("#h-dbok", "异常");
    }

    setText("#h-driver", d.db_driver || "-");
    setText("#h-version", d.version || "-");
    setText("#h-addr", (d.web_host || "-") + ":" + (d.web_port || "-"));
    setText("#h-model", d.model_loaded
      ? ("已加载 " + (d.model_name || "") + "（" + (d.model_device || "-") + "）")
      : "未加载（可点击“模型引擎自检”）");
  }

  /* ---------- M2：模型引擎自检 ---------- */
  var selftestBtn = $("#btn-selftest");
  var selftestOut = $("#selftest-result");
  if (selftestBtn) {
    selftestBtn.addEventListener("click", async function () {
      selftestBtn.disabled = true;
      selftestBtn.textContent = "自检中…";
      if (selftestOut) {
        selftestOut.hidden = false;
        selftestOut.textContent = "正在加载权重并预热，请稍候（数秒）…";
      }
      try {
        var resp = await fetch("/api/engine/selftest", { method: "POST" });
        var json = await resp.json();
        if (json.code === 0) {
          var d = json.data;
          if (selftestOut) {
            selftestOut.textContent = "✅ " + d.message + "\n耗时 " + d.elapsed_ms + " ms；默认参数见下：\n" +
              JSON.stringify(d.params, null, 2);
          }
          setText("#h-model", "已加载 " + d.model_name + "（" + d.device + "）");
        } else {
          if (selftestOut) { selftestOut.textContent = "❌ " + (json.msg || "自检失败"); }
        }
      } catch (e) {
        if (selftestOut) { selftestOut.textContent = "❌ 自检请求失败：" + e; }
      } finally {
        selftestBtn.disabled = false;
        selftestBtn.textContent = "模型引擎自检";
        refreshHealth();
      }
    });
  }

  refreshHealth();
  setInterval(refreshHealth, 5000);
})();
