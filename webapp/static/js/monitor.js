import { api, byId, feedback, post } from "./api.js";

const form = byId("monitor-form");
const inputs = byId("monitor-inputs");
const sourceType = byId("source-type");
const samples = byId("sample-source");
const uploadInput = byId("upload-source");
const progress = byId("upload-progress");
const stream = byId("monitor-stream");
const placeholder = byId("video-placeholder");
const parameters = form.querySelector(".parameters");
const startButton = byId("monitor-start");
const stopButton = byId("monitor-stop");
const sourceFeedback = byId("source-feedback");
const actionFeedback = byId("monitor-feedback");
const sessions = { idle: "待启动", starting: "正在加载模型", running: "监控中", stopping: "正在停止", ended: "播放完毕", error: "运行异常" };
const numericSettings = ["conf", "iou", "imgsz", "cooldown", "vote_window", "vote_threshold"];
const toggleSettings = ["heartbeat", "save_snapshot", "loop", "use_vote"];
let defaults;
let uploadId;
let status = { state: "idle", running: false };
let action = "";
let requestVersion = 0;
let visible = true;
let shownSession;
let lockedSession;
let draftSettings;

function setText(id, value) {
  byId(id).textContent = value ?? "—";
}

function updateButtons() {
  inputs.disabled = !defaults || Boolean(action) || status.running;
  startButton.disabled = inputs.disabled || (sourceType.value === "sample" && !samples.value)
    || (sourceType.value === "upload" && !uploadId);
  stopButton.disabled = Boolean(action) || !status.running || status.state === "stopping";
}

function updateSource() {
  const kind = sourceType.value;
  form.querySelectorAll("[data-source]").forEach((section) => {
    section.hidden = section.dataset.source !== kind;
    section.querySelectorAll("input, select, button").forEach((input) => { input.disabled = section.hidden; });
  });
  byId("loop-option").hidden = kind === "camera";
  form.elements.loop.disabled = kind === "camera";
  feedback(sourceFeedback, kind === "upload" && uploadId ? "视频已上传，可开始监控。" : "", "success");
  updateButtons();
}

function updateVoteLimit() {
  const threshold = form.elements.vote_threshold;
  const voteWindow = form.elements.vote_window;
  const windowSize = voteWindow.valueAsNumber;
  voteWindow.disabled = threshold.disabled = !form.elements.use_vote.checked;
  threshold.max = Number.isFinite(windowSize) ? windowSize : 15;
  if (threshold.valueAsNumber > windowSize) threshold.value = windowSize;
}

function displayFrame() {
  const show = visible && status.has_frame && status.state !== "idle";
  if (!show) {
    stream.hidden = true;
    stream.removeAttribute("src");
    shownSession = undefined;
  } else if (shownSession !== status.session_id) {
    shownSession = status.session_id;
    stream.src = `/api/stream.mjpeg?session_id=${status.session_id}`;
    stream.hidden = false;
  }
  placeholder.hidden = !stream.hidden;
  setText("video-placeholder-text", status.state === "idle" ? "等待开始监控" : sessions[status.state]);
}

function setFormSettings(settings) {
  for (const name of numericSettings) {
    const input = form.elements[name];
    const value = settings[name];
    if (input instanceof HTMLSelectElement && !Array.from(input.options).some((option) => Number(option.value) === Number(value))) {
      input.add(new Option(String(value), String(value)));
    }
    input.value = value;
  }
  for (const name of toggleSettings) form.elements[name].checked = Boolean(settings[name]);
  updateVoteLimit();
}

function renderSession(data) {
  status = data;
  const badge = byId("monitor-state");
  badge.dataset.state = data.state;
  badge.textContent = sessions[data.state];
  byId("monitor-alarm").hidden = !data.alarm;
  setText("monitor-fps", data.fps == null ? null : `${data.fps.toFixed(1)} FPS`);
  setText("monitor-ms", data.infer_ms == null ? null : `${data.infer_ms.toFixed(1)} ms`);
  setText("monitor-votes", data.vote_sum == null ? null : (data.use_vote ? `${data.vote_sum} / ${data.vote_window}` : "未启用"));
  setText("monitor-alarms", data.alarm_count);
  setText("monitor-source", data.source_display);
  setText("monitor-frame", data.frame_idx == null ? null : `第 ${data.frame_idx} 帧 · 人脸 ${data.n_faces} · 香烟 ${data.n_boxes} · 报警 ${data.alarm_persons} 人${data.video_time == null ? "" : ` · ${data.video_time.toFixed(1)} 秒`}`);
  setText("monitor-model", data.model_name ? `${data.face_model_name} → ${data.model_name} (${data.device})` : null);
  setText("monitor-event", data.last_event_at);
  feedback(byId("monitor-session-message"), data.last_error || data.record_error || "", "error");
  if (defaults && data.running && data.session_id !== lockedSession) {
    if (lockedSession === undefined) {
      draftSettings = Object.fromEntries(numericSettings.map((name) => [name, form.elements[name].value]));
      for (const name of toggleSettings) draftSettings[name] = form.elements[name].checked;
    }
    setFormSettings(data);
    lockedSession = data.session_id;
  } else if (defaults && !data.running && lockedSession !== undefined) {
    setFormSettings(draftSettings);
    lockedSession = undefined;
  }
  displayFrame();
  updateButtons();
}

async function refreshStatus() {
  const version = ++requestVersion;
  try {
    const data = await api("/api/session/status");
    if (version === requestVersion) renderSession(data);
  } catch (error) {
    if (version === requestVersion) feedback(byId("monitor-session-message"), `无法获取监控状态：${error.message}`, "error");
  }
}

async function runAction(name, handler, resultElement) {
  if (action) return;
  action = name;
  updateButtons();
  try {
    await handler();
  } catch (error) {
    feedback(resultElement, error.message, "error");
  } finally {
    action = "";
    updateButtons();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const kind = sourceType.value;
  const values = { sample: samples.value, local: form.elements.local.value.trim(),
    upload: uploadId, camera: Number(form.elements.camera.value) };
  const body = { source_type: kind, source: values[kind] };
  numericSettings.forEach((name) => { body[name] = Number(form.elements[name].value); });
  toggleSettings.forEach((name) => { body[name] = form.elements[name].checked; });
  if (!body.use_vote) {
    body.vote_window = 1;
    body.vote_threshold = 1;
  }
  void runAction("start", async () => {
    feedback(actionFeedback, "");
    try {
      await post("/api/session/start", body);
    } finally {
      await refreshStatus();
    }
  }, actionFeedback);
});

stopButton.addEventListener("click", () => {
  void runAction("stop", async () => {
    feedback(actionFeedback, "");
    await post("/api/session/stop", {});
    await refreshStatus();
  }, actionFeedback);
});

function uploadVideo(file) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const data = new FormData();
    data.append("file", file);
    xhr.open("POST", "/api/sources/upload");
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) progress.value = (event.loaded / event.total) * 100;
    };
    xhr.onload = () => {
      if (xhr.status === 200 && xhr.response?.code === 0) resolve(xhr.response.data);
      else reject(new Error(xhr.response?.msg || `上传失败 (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("上传失败，请检查服务连接"));
    xhr.send(data);
  });
}

uploadInput.addEventListener("change", () => {
  const [file] = uploadInput.files;
  uploadId = undefined;
  updateButtons();
  if (!file) {
    feedback(sourceFeedback, "");
    return;
  }
  void runAction("upload", async () => {
    if (file.size > defaults.upload_max_mb * 1024 * 1024) throw new Error(`视频大小超过 ${defaults.upload_max_mb} MB`);
    progress.value = 0;
    progress.hidden = false;
    feedback(sourceFeedback, "正在上传并检查视频…");
    try {
      const result = await uploadVideo(file);
      uploadId = result.upload_id;
      feedback(sourceFeedback, `已上传 ${result.original_name}`, "success");
    } finally {
      progress.hidden = true;
      if (!uploadId) uploadInput.value = "";
    }
  }, sourceFeedback);
});

byId("probe-source").addEventListener("click", () => {
  void runAction("probe", async () => {
    feedback(sourceFeedback, "正在检查视频…");
    const { probe } = await post("/api/sources/resolve-local", { path: form.elements.local.value.trim() });
    const duration = probe.duration_sec == null ? "" : ` · ${probe.duration_sec} 秒`;
    feedback(sourceFeedback, `${probe.width} × ${probe.height} · ${probe.fps} FPS${duration}`, "success");
  }, sourceFeedback);
});

form.elements.local.addEventListener("input", () => feedback(sourceFeedback, ""));
form.elements.vote_window.addEventListener("input", updateVoteLimit);
form.elements.use_vote.addEventListener("change", updateVoteLimit);
parameters.open = !window.matchMedia("(max-width: 800px)").matches;
parameters.addEventListener("invalid", () => { parameters.open = true; }, true);
sourceType.addEventListener("change", updateSource);
samples.addEventListener("change", updateButtons);
stream.addEventListener("error", () => {
  stream.hidden = true;
  placeholder.hidden = false;
  setText("video-placeholder-text", "画面暂不可用");
  if (status.running) shownSession = undefined;
});
document.addEventListener("smoke-tab", (event) => {
  visible = event.detail === "monitor";
  displayFrame();
  if (visible) void refreshStatus();
});

async function loadDefaults() {
  try {
    defaults = await api("/api/config/defaults");
    samples.replaceChildren(...defaults.samples.map(({ name }) => new Option(name, name)));
    if (!defaults.samples.length) samples.add(new Option("没有样例视频", ""));
    else if (defaults.samples.some(({ name }) => name === "smoke_test2.mp4")) samples.value = "smoke_test2.mp4";
    form.elements.camera.value = defaults.camera_default;
    uploadInput.accept = defaults.exts.join(",");
    setFormSettings({ ...defaults, save_snapshot: true, loop: false });
    updateSource();
  } catch (error) {
    feedback(actionFeedback, `无法读取监控配置：${error.message}`, "error");
  }
  await refreshStatus();
}

void loadDefaults();
window.setInterval(() => { if (visible) void refreshStatus(); }, 1000);
