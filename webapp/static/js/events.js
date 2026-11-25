import { api, byId, feedback, post } from "./api.js";

const filters = byId("event-filters");
const cards = byId("event-cards");
const pagination = byId("event-pagination");
const listMessage = byId("events-message");
const dialog = byId("event-dialog");
const detail = byId("event-detail");
const edit = byId("event-label");
const dialogMessage = byId("event-dialog-message");
const words = { open: "未处理", confirmed: "确认抽烟", false_alarm: "误报" };
let query = new URLSearchParams(new FormData(filters));
let page = 1;
let listVersion = 0;
let detailVersion = 0;
let currentEvent;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function preview(event, className, lazy = false) {
  const element = node("div", null, className);
  if (!event.snapshot_url) {
    element.textContent = "未保存快照";
    return element;
  }
  const image = node("img");
  image.alt = "报警快照";
  if (lazy) image.loading = "lazy";
  if (!lazy) image.className = "event-detail-image";
  image.addEventListener("error", () => { element.textContent = "快照不可用"; }, { once: true });
  image.src = event.snapshot_url;
  element.append(image);
  return element;
}

function eventCard(event) {
  const tile = node("button", null, "event-tile");
  tile.type = "button";
  const meta = node("span", null, "event-tile-body");
  meta.append(node("strong", event.source_name), node("time", event.event_time),
    node("small", `${words[event.status] || event.status} · 投票 ${event.vote_sum ?? "—"}/${event.vote_window ?? "—"}`));
  tile.append(preview(event, "event-thumb", true), meta);
  tile.addEventListener("click", () => { void showDetail(event.id); });
  return tile;
}

async function loadEvents(requestedPage = page) {
  const version = ++listVersion;
  feedback(listMessage, "正在查询违规记录…");
  const params = new URLSearchParams(query);
  params.set("page", requestedPage);
  try {
    const result = await api(`/api/events?${params}`);
    if (version !== listVersion) return;
    const lastPage = Math.max(1, Math.ceil(result.total / result.size));
    if (requestedPage > lastPage) {
      await loadEvents(lastPage);
      return;
    }
    const source = filters.elements.source;
    const selected = source.value;
    const selectedLabel = source.selectedOptions[0]?.textContent;
    source.replaceChildren(new Option("全部来源", ""), ...result.sources.map(({ id, name }) => new Option(name, id)));
    if (selected && !Array.from(source.options).some(({ value }) => value === selected)) {
      source.add(new Option(selectedLabel, selected));
    }
    source.value = selected;
    page = result.page;
    cards.replaceChildren(...result.items.map(eventCard));
    feedback(listMessage, result.total ? "" : "没有符合条件的违规记录。");
    pagination.hidden = !result.total;
    byId("event-count").textContent = `共 ${result.total} 条 · 第 ${page} / ${lastPage} 页`;
    byId("events-prev").disabled = page <= 1;
    byId("events-next").disabled = page >= lastPage;
  } catch (error) {
    if (version !== listVersion) return;
    cards.replaceChildren();
    pagination.hidden = true;
    feedback(listMessage, error.message, "error");
  }
}

function renderDetail(event) {
  const values = [
    ["报警时间", event.event_time], ["视频来源", event.source_name],
    ["帧号", event.frame_index], ["视频内时间", event.video_time_sec == null ? null : `${event.video_time_sec} 秒`],
    ["最高置信度", event.max_conf], ["投票", `${event.vote_sum ?? "—"} / ${event.vote_window ?? "—"}`],
    ["模型", event.model_name], ["记录原因", event.reason === "heartbeat" ? "持续报警" : "首次报警"],
    ["检测框", event.boxes?.length ? event.boxes.map(({ xyxy, conf }) => `[${xyxy.join(", ")}] (${conf})`).join("，") : null],
  ];
  const metadata = node("dl", null, "kv event-detail-grid");
  for (const [key, value] of values) metadata.append(node("dt", key), node("dd", value ?? "—"));
  detail.replaceChildren(preview(event, "event-detail-preview"), metadata);
  edit.elements.status.value = event.status;
  edit.elements.note.value = event.note || "";
  edit.hidden = false;
  currentEvent = event.id;
}

async function showDetail(id) {
  const version = ++detailVersion;
  currentEvent = undefined;
  detail.replaceChildren();
  edit.hidden = true;
  feedback(dialogMessage, "正在查询事件详情…");
  if (!dialog.open) dialog.showModal();
  try {
    const event = await api(`/api/events/${id}`);
    if (version !== detailVersion || !dialog.open) return;
    renderDetail(event);
    feedback(dialogMessage, "");
  } catch (error) {
    if (version === detailVersion && dialog.open) feedback(dialogMessage, error.message, "error");
  }
}

async function updateEvent(operation, message) {
  if (currentEvent === undefined) return;
  const version = detailVersion;
  const controls = Array.from(edit.elements);
  controls.forEach((control) => { control.disabled = true; });
  try {
    const event = await operation(currentEvent);
    if (version === detailVersion && dialog.open) {
      if (event) {
        renderDetail(event);
        feedback(dialogMessage, message, "success");
      } else {
        dialog.close();
      }
    }
    await loadEvents();
  } catch (error) {
    if (version === detailVersion && dialog.open) feedback(dialogMessage, error.message, "error");
  } finally {
    controls.forEach((control) => { control.disabled = false; });
  }
}

edit.addEventListener("submit", (event) => {
  event.preventDefault();
  const body = { status: edit.elements.status.value, note: edit.elements.note.value };
  void updateEvent((id) => post(`/api/events/${id}/label`, body), "处理结果已保存。");
});

byId("event-delete").addEventListener("click", () => {
  if (!window.confirm("删除这条违规记录及其快照？")) return;
  void updateEvent(async (id) => { await api(`/api/events/${id}`, { method: "DELETE" }); });
});

filters.addEventListener("submit", (event) => {
  event.preventDefault();
  query = new URLSearchParams(new FormData(filters));
  void loadEvents(1);
});
filters.addEventListener("reset", () => {
  window.setTimeout(() => {
    query = new URLSearchParams(new FormData(filters));
    void loadEvents(1);
  }, 0);
});

byId("event-export").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  feedback(listMessage, "正在导出记录…");
  try {
    const response = await fetch(`/api/events/export.csv?${query}`, { cache: "no-store" });
    if (!response.ok) {
      const result = await response.json().catch(() => null);
      throw new Error(result?.msg || `导出失败 (${response.status})`);
    }
    const url = URL.createObjectURL(await response.blob());
    const link = node("a");
    link.href = url;
    link.download = "smoke-events.csv";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    feedback(listMessage, "已导出 CSV。", "success");
  } catch (error) {
    feedback(listMessage, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

byId("events-refresh").addEventListener("click", () => { void loadEvents(); });
byId("events-prev").addEventListener("click", () => { void loadEvents(page - 1); });
byId("events-next").addEventListener("click", () => { void loadEvents(page + 1); });
document.addEventListener("smoke-tab", (event) => { if (event.detail === "events") void loadEvents(); });
