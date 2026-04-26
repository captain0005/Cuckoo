"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiURL, createJob, fetchJob, type JobResult, type TranslationJob } from "@/lib/api";

const MAX_FILES = 30;
const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  processing: "处理中",
  completed: "已完成",
  failed: "处理失败",
};

const STEP_STATES = ["upload", "queue", "process", "done"] as const;
type StepName = (typeof STEP_STATES)[number];

export default function Home() {
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<TranslationJob | null>(null);
  const [statusText, setStatusText] = useState("上传图片后开始处理。");
  const [progress, setProgress] = useState(0);
  const [workflowState, setWorkflowState] = useState("idle");
  const [sourceLanguage, setSourceLanguage] = useState("zh");
  const [targetLanguage, setTargetLanguage] = useState("en");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const totalSize = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);
  const resultCount = job?.results?.length ?? 0;

  const refreshJob = useCallback(async () => {
    if (!job?.job_id) {
      return;
    }
    try {
      const nextJob = await fetchJob(job.job_id);
      renderJobState(nextJob, setWorkflowState, setStatusText, setProgress);
      setJob(nextJob);
      if (nextJob.status === "completed" || nextJob.status === "failed") {
        setIsSubmitting(false);
      }
    } catch (error) {
      setWorkflowState("failed");
      setStatusText(error instanceof Error ? error.message : "无法读取任务状态。");
      setProgress(0);
      setIsSubmitting(false);
    }
  }, [job?.job_id]);

  useEffect(() => {
    if (!job?.job_id || job.status === "completed" || job.status === "failed") {
      return;
    }
    const timer = window.setInterval(refreshJob, 1200);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status, refreshJob]);

  function updateFiles(nextFiles: File[]) {
    const images = nextFiles.filter((file) => file.type.startsWith("image/"));
    const capped = images.slice(0, MAX_FILES);
    setFiles(capped);
    if (images.length > MAX_FILES) {
      setStatusText(`已自动保留前 ${MAX_FILES} 张图片。`);
    } else if (!images.length && nextFiles.length) {
      setStatusText("请选择图片文件。");
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) {
      setStatusText("请先选择要翻译的商品图片。");
      setProgress(0);
      return;
    }

    setIsSubmitting(true);
    setJob(null);
    setWorkflowState("uploading");
    setStatusText("正在上传图片。");
    setProgress(3);

    try {
      const createdJob = await createJob(files, sourceLanguage, targetLanguage);
      renderJobState(createdJob, setWorkflowState, setStatusText, setProgress);
      setJob(createdJob);
    } catch (error) {
      setWorkflowState("failed");
      setStatusText(error instanceof Error ? error.message : "任务创建失败。");
      setProgress(0);
      setIsSubmitting(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar" aria-label="主导航">
        <a className="brand" href="/" aria-label="Cuckoo 首页">
          <span className="brand-mark">C</span>
          <span>
            <strong>Cuckoo</strong>
            <small>Image Translation</small>
          </span>
        </a>
        <nav className="nav-actions" aria-label="辅助操作">
          <a className="ghost-link" href={apiURL("/health")} target="_blank" rel="noreferrer">
            API 状态
          </a>
        </nav>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">跨境电商图片本地化</p>
          <h1>商品图中文一键识别、翻译并生成英文版</h1>
          <p className="hero-desc">
            保持原图设计和分辨率，只替换图片里的中文说明，支持批量上传、在线预览和 ZIP 打包下载。
          </p>
          <div className="hero-badges" aria-label="核心能力">
            <span>1-30 张批量上传</span>
            <span>高清原图输出</span>
            <span>OCR + 翻译 + 回写</span>
          </div>
        </div>
        <div className="hero-card" aria-hidden="true">
          <span className="orb orb-a" />
          <span className="orb orb-b" />
          <div className="preview-window">
            <div className="preview-toolbar">
              <span />
              <span />
              <span />
            </div>
            <div className="preview-image">
              <span className="text-block short" />
              <span className="text-block" />
              <span className="text-block long" />
            </div>
            <div className="preview-caption">TRANSLATED IMAGE READY</div>
          </div>
        </div>
      </section>

      <section className="workspace">
        <form className="panel upload-panel" onSubmit={handleSubmit}>
          <div className="section-head">
            <div>
              <p className="eyebrow">Step 01</p>
              <h2>上传商品图片</h2>
            </div>
            <span className="file-meta">{files.length ? `${files.length} 张 · ${formatBytes(totalSize)}` : "尚未选择"}</span>
          </div>

          <div
            className={`dropzone${isDragging ? " dragging" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              event.preventDefault();
              setIsDragging(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setIsDragging(false);
              updateFiles(Array.from(event.dataTransfer.files || []));
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              aria-label="选择商品图片"
              onChange={(event) => updateFiles(Array.from(event.target.files || []))}
            />
            <div className="drop-content">
              <span className="upload-icon" aria-hidden="true">
                +
              </span>
              <strong>拖拽图片到这里，或点击选择文件</strong>
              <span>支持 JPG、PNG、WebP 等格式，单次最多 30 张</span>
            </div>
          </div>

          <SelectedFiles files={files} />

          <div className="controls">
            <label>
              源语言
              <select value={sourceLanguage} onChange={(event) => setSourceLanguage(event.target.value)}>
                <option value="zh">中文</option>
              </select>
            </label>
            <label>
              目标语言
              <select value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value)}>
                <option value="en">英文</option>
                <option value="ja">日文</option>
                <option value="ko">韩文</option>
                <option value="fr">法文</option>
                <option value="de">德文</option>
              </select>
            </label>
            <button type="submit" disabled={isSubmitting}>
              开始翻译
            </button>
          </div>
        </form>

        <aside className="panel status-panel" aria-live="polite">
          <div className="section-head compact">
            <div>
              <p className="eyebrow">Step 02</p>
              <h2>{job ? `任务 ${job.job_id.slice(0, 8)}` : "任务状态"}</h2>
            </div>
            <a
              className={`download${job?.status === "completed" && job.download_url ? "" : " disabled"}`}
              href={job?.download_url ? apiURL(job.download_url) : "#"}
              aria-disabled={job?.status === "completed" ? "false" : "true"}
            >
              下载结果
            </a>
          </div>
          <p className="status-text">{statusText}</p>
          <div className="progress" aria-label="处理进度">
            <div style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
          </div>
          <ol className="steps" aria-label="处理步骤">
            {STEP_STATES.map((step) => (
              <li key={step} data-state={stepState(step, workflowState)}>
                <span />
                {stepLabel(step)}
              </li>
            ))}
          </ol>
        </aside>
      </section>

      <section className="results-section">
        <div className="section-head">
          <div>
            <p className="eyebrow">Step 03</p>
            <h2>翻译结果</h2>
          </div>
          <span className="file-meta">{resultCount ? `${resultCount} 张已生成` : "暂无结果"}</span>
        </div>
        <section className="results" aria-live="polite">
          {job?.results?.length ? (
            job.results.map((item) => <ResultCard key={`${item.source_filename}-${item.output_filename}`} item={item} />)
          ) : (
            <article className="empty-state">
              <strong>{emptyMessage(job)}</strong>
              <span>完成后可预览每张图片，也可以打包下载 ZIP 文件。</span>
            </article>
          )}
        </section>
      </section>
    </main>
  );
}

function SelectedFiles({ files }: { files: File[] }) {
  if (!files.length) {
    return null;
  }
  return (
    <ul className="selected-files" aria-live="polite">
      {files.slice(0, 5).map((file) => (
        <li key={`${file.name}-${file.size}`}>
          <strong>{file.name}</strong>
          <span>{formatBytes(file.size)}</span>
        </li>
      ))}
      {files.length > 5 ? (
        <li>
          <strong>另有 {files.length - 5} 张图片</strong>
          <span>已加入队列</span>
        </li>
      ) : null}
    </ul>
  );
}

function ResultCard({ item }: { item: JobResult }) {
  return (
    <article className="result-card">
      <img src={apiURL(item.file_url)} alt={item.output_filename || item.source_filename || "翻译结果图"} loading="lazy" />
      <div className="result-body">
        <div className="result-title-row">
          <h3>{item.source_filename || "未命名图片"}</h3>
          <a className="open-link" href={apiURL(item.file_url)} target="_blank" rel="noreferrer">
            打开
          </a>
        </div>
        <p className="meta">
          <span>识别 {item.regions_detected ?? 0} 处</span>
          <span>替换 {item.regions_replaced ?? 0} 处</span>
        </p>
        {item.warnings?.map((warning) => (
          <p className="warning" key={warning}>
            {warning}
          </p>
        ))}
      </div>
    </article>
  );
}

function renderJobState(
  job: TranslationJob,
  setWorkflowState: (value: string) => void,
  setStatusText: (value: string) => void,
  setProgress: (value: number) => void,
) {
  const progress = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const statusLabel = STATUS_LABELS[job.status] || job.status || "待处理";
  setWorkflowState(job.status);
  setProgress(progress);
  setStatusText(
    job.status === "failed"
      ? `处理失败：${job.error || "未知错误"}`
      : `${statusLabel} · ${job.completed}/${job.total} 张 · ${Math.round(progress)}%`,
  );
}

function stepLabel(step: StepName) {
  const labels: Record<StepName, string> = {
    upload: "上传",
    queue: "排队",
    process: "处理",
    done: "完成",
  };
  return labels[step];
}

function stepState(step: StepName, workflowState: string) {
  const order: StepName[] = ["upload", "queue", "process", "done"];
  const stateIndexes: Record<string, number> = {
    idle: -1,
    uploading: 0,
    queued: 1,
    processing: 2,
    completed: 3,
    failed: 2,
  };
  const activeIndex = stateIndexes[workflowState] ?? -1;

  const index = order.indexOf(step);
  if (workflowState === "failed" && step === "process") {
    return "error";
  }
  if (index < activeIndex || workflowState === "completed") {
    return "complete";
  }
  if (index === activeIndex) {
    return "active";
  }
  return "pending";
}

function emptyMessage(job: TranslationJob | null) {
  if (job?.status === "queued") {
    return "任务已进入队列，等待开始处理";
  }
  if (job?.status === "processing") {
    return "正在识别、翻译并生成图片";
  }
  return "处理完成后结果会显示在这里";
}

function formatBytes(bytes: number) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}
