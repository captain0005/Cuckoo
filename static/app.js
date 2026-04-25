const form = document.querySelector("#uploadForm");
const filesInput = document.querySelector("#files");
const dropzone = document.querySelector("#dropzone");
const submitButton = document.querySelector("#submitButton");
const jobTitle = document.querySelector("#jobTitle");
const progressBar = document.querySelector("#progressBar");
const statusText = document.querySelector("#statusText");
const downloadLink = document.querySelector("#downloadLink");
const results = document.querySelector("#results");
const fileMeta = document.querySelector("#fileMeta");
const selectedFiles = document.querySelector("#selectedFiles");
const resultCount = document.querySelector("#resultCount");

const stepNodes = {
  upload: document.querySelector("#stepUpload"),
  queue: document.querySelector("#stepQueue"),
  process: document.querySelector("#stepProcess"),
  done: document.querySelector("#stepDone"),
};

const MAX_FILES = 30;
const STATUS_LABELS = {
  queued: "排队中",
  processing: "处理中",
  completed: "已完成",
  failed: "处理失败",
};

let currentJob = null;
let pollTimer = null;

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  });
});

dropzone.addEventListener("drop", (event) => {
  const files = Array.from(event.dataTransfer?.files || []).filter((file) => file.type.startsWith("image/"));
  if (!files.length) {
    setStatus("请拖入图片文件。", 0);
    return;
  }
  setSelectedFiles(files);
});

filesInput.addEventListener("change", refreshFileList);

downloadLink.addEventListener("click", (event) => {
  if (downloadLink.classList.contains("disabled")) {
    event.preventDefault();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = getSelectedFiles();

  if (!files.length) {
    setStatus("请先选择要翻译的商品图片。", 0);
    return;
  }

  if (files.length > MAX_FILES) {
    setStatus(`单次最多支持 ${MAX_FILES} 张图片，请减少后重试。`, 0);
    return;
  }

  const payload = new FormData();
  files.forEach((file) => payload.append("files", file));
  payload.append("source_language", document.querySelector("#sourceLanguage").value);
  payload.append("target_language", document.querySelector("#targetLanguage").value);

  currentJob = null;
  submitButton.disabled = true;
  downloadLink.href = "#";
  downloadLink.classList.add("disabled");
  downloadLink.setAttribute("aria-disabled", "true");
  renderEmptyResults("图片上传后会在这里显示处理结果");
  setWorkflowState("uploading");
  setStatus("正在上传图片。", 3);

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      body: payload,
    });
    const data = await safeJson(response);
    if (!response.ok) {
      throw new Error(data.detail || "任务创建失败。");
    }
    currentJob = data.job_id;
    renderJob(data);
    startPolling();
  } catch (error) {
    setWorkflowState("failed");
    setStatus(error.message || "任务创建失败。", 0);
    submitButton.disabled = false;
  }
});

function setSelectedFiles(files) {
  const normalized = files.slice(0, MAX_FILES);
  const dataTransfer = new DataTransfer();
  normalized.forEach((file) => dataTransfer.items.add(file));
  filesInput.files = dataTransfer.files;
  refreshFileList();

  if (files.length > MAX_FILES) {
    setStatus(`已自动保留前 ${MAX_FILES} 张图片。`, 0);
  }
}

function refreshFileList() {
  const files = getSelectedFiles();
  selectedFiles.innerHTML = "";

  if (!files.length) {
    fileMeta.textContent = "尚未选择";
    return;
  }

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  fileMeta.textContent = `${files.length} 张 · ${formatBytes(totalSize)}`;

  for (const file of files.slice(0, 5)) {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = file.name;
    const size = document.createElement("span");
    size.textContent = formatBytes(file.size);
    item.append(name, size);
    selectedFiles.appendChild(item);
  }

  if (files.length > 5) {
    const more = document.createElement("li");
    more.innerHTML = `<strong>另有 ${files.length - 5} 张图片</strong><span>已加入队列</span>`;
    selectedFiles.appendChild(more);
  }
}

function startPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
  }
  pollTimer = setInterval(fetchJob, 1200);
  fetchJob();
}

async function fetchJob() {
  if (!currentJob) {
    return;
  }

  try {
    const response = await fetch(`/api/jobs/${currentJob}`);
    const data = await safeJson(response);
    if (!response.ok) {
      throw new Error(data.detail || "无法读取任务状态。");
    }
    renderJob(data);
    if (data.status === "completed" || data.status === "failed") {
      clearInterval(pollTimer);
      submitButton.disabled = false;
    }
  } catch (error) {
    setWorkflowState("failed");
    setStatus(error.message || "无法读取任务状态。", 0);
    clearInterval(pollTimer);
    submitButton.disabled = false;
  }
}

function renderJob(job) {
  jobTitle.textContent = `任务 ${job.job_id.slice(0, 8)}`;
  const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const statusLabel = STATUS_LABELS[job.status] || job.status || "待处理";
  const label = job.status === "failed"
    ? `处理失败：${job.error || "未知错误"}`
    : `${statusLabel} · ${job.completed}/${job.total} 张 · ${progress}%`;

  setWorkflowState(job.status);
  setStatus(label, progress);

  if (job.status === "completed" && job.download_url) {
    downloadLink.href = job.download_url;
    downloadLink.classList.remove("disabled");
    downloadLink.setAttribute("aria-disabled", "false");
  } else {
    downloadLink.href = "#";
    downloadLink.classList.add("disabled");
    downloadLink.setAttribute("aria-disabled", "true");
  }

  const items = job.results || [];
  resultCount.textContent = items.length ? `${items.length} 张已生成` : "暂无结果";
  results.innerHTML = "";

  if (!items.length) {
    renderEmptyResults(job.status === "queued" ? "任务已进入队列，等待开始处理" : "正在识别、翻译并生成图片");
    return;
  }

  for (const item of items) {
    results.appendChild(renderResult(item));
  }
}

function renderResult(item) {
  const card = document.createElement("article");
  card.className = "result-card";

  const image = document.createElement("img");
  image.src = item.file_url;
  image.alt = item.output_filename || item.source_filename || "翻译结果图";
  image.loading = "lazy";

  const body = document.createElement("div");
  body.className = "result-body";

  const titleRow = document.createElement("div");
  titleRow.className = "result-title-row";

  const title = document.createElement("h3");
  title.textContent = item.source_filename || "未命名图片";

  const openLink = document.createElement("a");
  openLink.className = "open-link";
  openLink.href = item.file_url;
  openLink.target = "_blank";
  openLink.rel = "noreferrer";
  openLink.textContent = "打开";

  titleRow.append(title, openLink);

  const meta = document.createElement("p");
  meta.className = "meta";
  meta.innerHTML = `<span>识别 ${item.regions_detected ?? 0} 处</span><span>替换 ${item.regions_replaced ?? 0} 处</span>`;

  body.append(titleRow, meta);
  for (const warning of item.warnings || []) {
    const warningNode = document.createElement("p");
    warningNode.className = "warning";
    warningNode.textContent = warning;
    body.appendChild(warningNode);
  }
  card.append(image, body);
  return card;
}

function renderEmptyResults(message) {
  resultCount.textContent = "暂无结果";
  results.innerHTML = `
    <article class="empty-state">
      <strong>${escapeHtml(message)}</strong>
      <span>完成后可预览每张图片，也可以打包下载 ZIP 文件。</span>
    </article>
  `;
}

function setStatus(text, progress) {
  statusText.textContent = text;
  progressBar.style.width = `${Math.max(0, Math.min(100, Number(progress || 0)))}%`;
}

function setWorkflowState(state) {
  const reset = () => Object.values(stepNodes).forEach((node) => node.dataset.state = "pending");
  reset();

  if (state === "uploading") {
    stepNodes.upload.dataset.state = "active";
    return;
  }

  if (state === "queued") {
    stepNodes.upload.dataset.state = "complete";
    stepNodes.queue.dataset.state = "active";
    return;
  }

  if (state === "processing") {
    stepNodes.upload.dataset.state = "complete";
    stepNodes.queue.dataset.state = "complete";
    stepNodes.process.dataset.state = "active";
    return;
  }

  if (state === "completed") {
    Object.values(stepNodes).forEach((node) => node.dataset.state = "complete");
    return;
  }

  if (state === "failed") {
    stepNodes.upload.dataset.state = "complete";
    stepNodes.queue.dataset.state = "complete";
    stepNodes.process.dataset.state = "error";
  }
}

function getSelectedFiles() {
  return Array.from(filesInput.files || []);
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
