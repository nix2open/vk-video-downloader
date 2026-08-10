const $ = (id) => document.getElementById(id);

const urlInput = $("url");
const analyzeBtn = $("analyzeBtn");
const downloadBtn = $("downloadBtn");
const updateBtn = $("updateBtn");
const applyUpdateBtn = $("applyUpdateBtn");
const releaseLink = $("releaseLink");
const statusEl = $("status");
const resultEl = $("result");
const titleEl = $("title");
const metaLineEl = $("metaLine");
const thumbEl = $("thumb");
const qualityEl = $("quality");
const qualityHintEl = $("qualityHint");
const progressWrap = $("progressWrap");
const progressBar = $("progressBar");
const progressLabel = $("progressLabel");
const progressEta = $("progressEta");
const progressPercent = $("progressPercent");
const progressSpeed = $("progressSpeed");
const updatePanel = $("updatePanel");
const updateTitle = $("updateTitle");
const updateBody = $("updateBody");
const versionLabel = $("versionLabel");
const footVersion = $("footVersion");

let currentUrl = "";
let latestUpdate = null;
let activeSource = null;

function setStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = `status${kind ? ` ${kind}` : ""}`;
}

function showProgress(show) {
  progressWrap.classList.toggle("hidden", !show);
  progressWrap.setAttribute("aria-hidden", show ? "false" : "true");
}

function updateProgress(job) {
  const percent = Number(job.percent || 0);
  progressBar.style.width = `${percent}%`;
  progressPercent.textContent = `${percent.toFixed(0)}%`;
  progressLabel.textContent = job.message || "Скачивание…";
  progressEta.textContent = job.eta ? `осталось ${job.eta}` : "";
  progressSpeed.textContent = job.speed || "";
  const track = progressWrap.querySelector(".progress-track");
  if (track) track.setAttribute("aria-valuenow", String(Math.round(percent)));
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return null;
  const s = Math.round(Number(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function errorDetail(data, status) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  return `Ошибка ${status}`;
}

function watchJob(jobId) {
  return new Promise((resolve, reject) => {
    if (activeSource) {
      activeSource.close();
      activeSource = null;
    }
    showProgress(true);
    updateProgress({ percent: 0, message: "Запуск…" });

    const es = new EventSource(`/api/jobs/${jobId}/events`);
    activeSource = es;
    es.onmessage = (ev) => {
      let job;
      try {
        job = JSON.parse(ev.data);
      } catch {
        return;
      }
      updateProgress(job);
      if (job.status === "done") {
        es.close();
        activeSource = null;
        resolve(job);
      } else if (job.status === "error") {
        es.close();
        activeSource = null;
        reject(new Error(job.error || job.message || "Ошибка задачи"));
      }
    };
    es.onerror = () => {
      // Fallback poll once on stream error
      fetch(`/api/jobs/${jobId}`)
        .then((r) => r.json())
        .then((job) => {
          updateProgress(job);
          if (job.status === "done") {
            es.close();
            activeSource = null;
            resolve(job);
          } else if (job.status === "error") {
            es.close();
            activeSource = null;
            reject(new Error(job.error || job.message || "Ошибка задачи"));
          }
        })
        .catch(() => {});
    };
  });
}

function renderResult(data) {
  currentUrl = data.webpage_url || urlInput.value.trim();
  titleEl.textContent = data.title;

  const bits = [];
  if (data.uploader) bits.push(data.uploader);
  const duration = formatDuration(data.duration);
  if (duration) bits.push(duration);
  bits.push(`${data.qualities.length} качеств`);
  bits.push(`${data.raw_format_count} потоков`);
  metaLineEl.textContent = bits.join(" · ");

  if (data.thumbnail) {
    thumbEl.src = data.thumbnail;
    thumbEl.alt = `Превью: ${data.title}`;
    thumbEl.hidden = false;
  } else {
    thumbEl.removeAttribute("src");
    thumbEl.hidden = true;
  }

  qualityEl.innerHTML = "";
  for (const q of data.qualities) {
    const opt = document.createElement("option");
    opt.value = q.format_id;
    opt.textContent = q.filesize_display
      ? `${q.label} — ${q.filesize_display}`
      : q.label;
    opt.dataset.description = q.description || "";
    qualityEl.appendChild(opt);
  }

  updateHint();
  resultEl.classList.remove("hidden");
}

function updateHint() {
  const selected = qualityEl.selectedOptions[0];
  qualityHintEl.textContent = selected?.dataset.description || "";
}

async function analyze() {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("Вставьте ссылку на видео.", "error");
    return;
  }

  analyzeBtn.disabled = true;
  downloadBtn.disabled = true;
  resultEl.classList.add("hidden");
  showProgress(false);
  setStatus("Анализирую…");

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errorDetail(data, res.status));
    renderResult(data);
    setStatus("Готово. Выберите качество и нажмите «Скачать».", "ok");
    downloadBtn.disabled = false;
  } catch (err) {
    setStatus(err.message || "Не удалось проанализировать видео.", "error");
  } finally {
    analyzeBtn.disabled = false;
  }
}

async function download() {
  const formatId = qualityEl.value;
  if (!currentUrl || !formatId) {
    setStatus("Сначала выполните анализ.", "error");
    return;
  }

  downloadBtn.disabled = true;
  analyzeBtn.disabled = true;
  setStatus("Скачивание запущено…");

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: currentUrl, format_id: formatId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errorDetail(data, res.status));

    const job = await watchJob(data.job_id);
    setStatus(`Готово: ${job.filename} (${job.size_display || ""})`, "ok");
    if (job.download_url) {
      window.location.assign(job.download_url);
    }
  } catch (err) {
    setStatus(err.message || "Ошибка скачивания.", "error");
  } finally {
    downloadBtn.disabled = false;
    analyzeBtn.disabled = false;
  }
}

async function loadVersion() {
  try {
    const res = await fetch("/api/version");
    const data = await res.json();
    versionLabel.textContent = `v${data.version}`;
    footVersion.textContent = `v${data.version}`;
    latestUpdate = { frozen: data.frozen, ...data };
  } catch {
    versionLabel.textContent = "v?";
  }
}

async function checkUpdates() {
  updateBtn.disabled = true;
  setStatus("Проверяю обновления на GitHub…");
  updatePanel.classList.add("hidden");
  applyUpdateBtn.classList.add("hidden");
  releaseLink.classList.add("hidden");

  try {
    const res = await fetch("/api/updates/check");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errorDetail(data, res.status));
    latestUpdate = data;

    updatePanel.classList.remove("hidden");
    updateTitle.textContent = data.update_available
      ? `Доступна версия ${data.latest_version}`
      : "Обновлений нет";
    updateBody.textContent = data.message || "";

    if (data.release_url) {
      releaseLink.href = data.release_url;
      releaseLink.classList.remove("hidden");
    }

    if (data.update_available && data.asset_url && data.can_auto_update) {
      applyUpdateBtn.classList.remove("hidden");
      setStatus(`Найдена новая версия ${data.latest_version}.`, "ok");
    } else if (data.update_available && data.release_url) {
      setStatus(`Найдена версия ${data.latest_version}. Скачайте со страницы релиза.`, "ok");
    } else {
      setStatus(data.message || "Актуальная версия.", "ok");
    }
  } catch (err) {
    setStatus(err.message || "Не удалось проверить обновления.", "error");
  } finally {
    updateBtn.disabled = false;
  }
}

async function applyUpdate() {
  if (!latestUpdate?.asset_url) return;
  applyUpdateBtn.disabled = true;
  updateBtn.disabled = true;
  setStatus("Скачиваю и устанавливаю обновление…");

  try {
    const res = await fetch("/api/updates/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_url: latestUpdate.asset_url,
        asset_name: latestUpdate.asset_name,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(errorDetail(data, res.status));
    await watchJob(data.job_id);
    setStatus("Обновление установлено. Приложение перезапускается…", "ok");
  } catch (err) {
    setStatus(err.message || "Не удалось установить обновление.", "error");
    applyUpdateBtn.disabled = false;
    updateBtn.disabled = false;
  }
}

analyzeBtn.addEventListener("click", analyze);
downloadBtn.addEventListener("click", download);
updateBtn.addEventListener("click", checkUpdates);
applyUpdateBtn.addEventListener("click", applyUpdate);
qualityEl.addEventListener("change", updateHint);
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    analyze();
  }
});

loadVersion();
