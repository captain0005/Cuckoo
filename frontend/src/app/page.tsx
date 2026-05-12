"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  apiURL,
  createJob,
  fetchJob,
  fetchMe,
  userLogin,
  type AdminUser,
  type JobResult,
  type ManualRegion,
  type TranslationJob,
} from "@/lib/api";

const MAX_FILES = 30;
const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  processing: "处理中",
  completed: "已完成",
  failed: "处理失败",
};

const STEP_STATES = ["upload", "queue", "process", "done"] as const;
type StepName = (typeof STEP_STATES)[number];
type FilePermissionMode = "read" | "readwrite";
type LocalWritableFileStream = {
  write: (data: Blob | BufferSource | string) => Promise<void>;
  close: () => Promise<void>;
};
type LocalFileHandle = {
  createWritable: () => Promise<LocalWritableFileStream>;
};
type LocalDirectoryHandle = {
  name: string;
  queryPermission?: (descriptor?: { mode?: FilePermissionMode }) => Promise<PermissionState>;
  requestPermission?: (descriptor?: { mode?: FilePermissionMode }) => Promise<PermissionState>;
  getFileHandle: (name: string, options?: { create?: boolean }) => Promise<LocalFileHandle>;
};
type RegionMap = Record<string, ManualRegion[]>;

declare global {
  interface Window {
    showDirectoryPicker?: (options?: { id?: string; mode?: FilePermissionMode }) => Promise<LocalDirectoryHandle>;
  }
}

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
  const [exportDirectoryHandle, setExportDirectoryHandle] = useState<LocalDirectoryHandle | null>(null);
  const [exportDirectoryName, setExportDirectoryName] = useState("");
  const [overwriteExport, setOverwriteExport] = useState(false);
  const [exportMessage, setExportMessage] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [selectedRegionFileKey, setSelectedRegionFileKey] = useState("");
  const [manualRegions, setManualRegions] = useState<RegionMap>({});
  const [userToken, setUserToken] = useState("");
  const [currentUser, setCurrentUser] = useState<AdminUser | null>(null);
  const [loginName, setLoginName] = useState("user");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginMessage, setLoginMessage] = useState("请先登录后使用图片翻译。");
  const [isLoginBusy, setIsLoginBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const totalSize = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);
  const resultCount = job?.results?.length ?? 0;
  const regionCount = useMemo(
    () => files.reduce((sum, file) => sum + (manualRegions[fileKey(file)]?.length || 0), 0),
    [files, manualRegions],
  );
  const isAuthenticated = Boolean(userToken && currentUser);

  const refreshJob = useCallback(async () => {
    if (!job?.job_id || !userToken) {
      return;
    }
    try {
      const nextJob = await fetchJob(job.job_id, userToken);
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
  }, [job?.job_id, userToken]);

  useEffect(() => {
    const savedToken = window.localStorage.getItem("cuckoo_user_token") || "";
    const savedUser = window.localStorage.getItem("cuckoo_user");
    if (!savedToken || !savedUser) {
      return;
    }
    setUserToken(savedToken);
    setCurrentUser(JSON.parse(savedUser) as AdminUser);
    void fetchMe(savedToken)
      .then((payload) => {
        setCurrentUser(payload.user);
        window.localStorage.setItem("cuckoo_user", JSON.stringify(payload.user));
      })
      .catch(() => {
        clearUserSession();
        setLoginMessage("登录已过期，请重新登录。");
      });
  }, []);

  useEffect(() => {
    if (!job?.job_id || job.status === "completed" || job.status === "failed") {
      return;
    }
    const timer = window.setInterval(refreshJob, 1200);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status, refreshJob]);

  useEffect(() => {
    if (!files.length) {
      setSelectedRegionFileKey("");
      setManualRegions({});
      return;
    }

    const keys = new Set(files.map(fileKey));
    setSelectedRegionFileKey((currentKey) => (currentKey && keys.has(currentKey) ? currentKey : fileKey(files[0])));
    setManualRegions((currentRegions) => {
      const nextRegions: RegionMap = {};
      for (const file of files) {
        const key = fileKey(file);
        if (currentRegions[key]?.length) {
          nextRegions[key] = currentRegions[key];
        }
      }
      return nextRegions;
    });
  }, [files]);

  function updateFiles(nextFiles: File[]) {
    const images = nextFiles.filter((file) => file.type.startsWith("image/"));
    if (!images.length && nextFiles.length) {
      setStatusText("请选择图片文件。");
      return;
    }
    if (!images.length) {
      return;
    }

    setFiles((currentFiles) => {
      const existingKeys = new Set(currentFiles.map(fileKey));
      const uniqueNewFiles = images.filter((file) => {
        const key = fileKey(file);
        if (existingKeys.has(key)) {
          return false;
        }
        existingKeys.add(key);
        return true;
      });
      const mergedFiles = [...currentFiles, ...uniqueNewFiles];
      const cappedFiles = mergedFiles.slice(0, MAX_FILES);
      const duplicateCount = images.length - uniqueNewFiles.length;
      const overflowCount = Math.max(0, mergedFiles.length - MAX_FILES);

      if (overflowCount > 0) {
        setStatusText(`已达到单次最多 ${MAX_FILES} 张，自动保留前 ${MAX_FILES} 张图片。`);
      } else if (duplicateCount > 0) {
        setStatusText(`已跳过 ${duplicateCount} 个重复文件，当前共 ${cappedFiles.length} 张图片。`);
      } else {
        setStatusText(`已添加 ${uniqueNewFiles.length} 张图片，当前共 ${cappedFiles.length} 张。`);
      }
      return cappedFiles;
    });
  }

  function updateRegionsForFile(file: File, updater: (regions: ManualRegion[]) => ManualRegion[]) {
    const key = fileKey(file);
    setManualRegions((currentRegions) => ({
      ...currentRegions,
      [key]: updater(currentRegions[key] || []),
    }));
  }

  async function handleUserLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoginBusy(true);
    setLoginMessage("正在登录...");
    try {
      const payload = await userLogin(loginName, loginPassword);
      setUserToken(payload.token);
      setCurrentUser(payload.user);
      window.localStorage.setItem("cuckoo_user_token", payload.token);
      window.localStorage.setItem("cuckoo_user", JSON.stringify(payload.user));
      setStatusText("已登录，可以上传图片开始处理。");
      setLoginMessage(`已登录：${payload.user.display_name || payload.user.username}`);
    } catch (error) {
      clearUserSession();
      setLoginMessage(error instanceof Error ? error.message : "登录失败");
    } finally {
      setIsLoginBusy(false);
    }
  }

  function clearUserSession() {
    window.localStorage.removeItem("cuckoo_user_token");
    window.localStorage.removeItem("cuckoo_user");
    setUserToken("");
    setCurrentUser(null);
  }

  function logout() {
    clearUserSession();
    setJob(null);
    setFiles([]);
    setManualRegions({});
    setWorkflowState("idle");
    setProgress(0);
    setStatusText("请登录后上传图片。");
    setLoginMessage("已退出登录。");
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isAuthenticated) {
      setStatusText("请先登录后再创建翻译任务。");
      setProgress(0);
      return;
    }
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
      const regionsByFile = files.map((file) => manualRegions[fileKey(file)] || []);
      const createdJob = await createJob(files, sourceLanguage, targetLanguage, {
        token: userToken,
        manualRegions: regionsByFile,
        inpaintEngine: "lama",
      });
      renderJobState(createdJob, setWorkflowState, setStatusText, setProgress);
      setJob(createdJob);
    } catch (error) {
      setWorkflowState("failed");
      setStatusText(error instanceof Error ? error.message : "任务创建失败。");
      setProgress(0);
      setIsSubmitting(false);
    }
  }

  async function chooseExportFolder() {
    if (!window.showDirectoryPicker) {
      setExportMessage("当前浏览器不支持直接选择文件夹，请使用最新版 Chrome 或 Edge。");
      return null;
    }
    try {
      const handle = await window.showDirectoryPicker({
        id: "cuckoo-export-folder",
        mode: "readwrite",
      });
      setExportDirectoryHandle(handle);
      setExportDirectoryName(handle.name);
      setExportMessage(`已选择文件夹：${handle.name}`);
      return handle;
    } catch (error) {
      if (isAbortError(error)) {
        setExportMessage("已取消选择文件夹。");
      } else {
        setExportMessage(error instanceof Error ? error.message : "无法选择文件夹。");
      }
      return null;
    }
  }

  async function handleFolderExport(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!job?.results?.length || job.status !== "completed") {
      setExportMessage("任务完成后才能导出到文件夹。");
      return;
    }
    const directoryHandle = exportDirectoryHandle || (await chooseExportFolder());
    if (!directoryHandle) {
      return;
    }

    setIsExporting(true);
    setExportMessage("正在导出图片...");
    try {
      const granted = await ensureDirectoryPermission(directoryHandle);
      if (!granted) {
        setExportMessage("没有获得文件夹写入权限。");
        return;
      }
      let exported = 0;
      for (const item of job.results) {
        const response = await fetch(apiURL(item.file_url), { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`无法读取生成图片：${item.output_filename || item.source_filename}`);
        }
        const blob = await response.blob();
        const filename = await nextExportFilename(directoryHandle, item.output_filename || "translated.png", overwriteExport);
        const fileHandle = await directoryHandle.getFileHandle(filename, { create: true });
        const writable = await fileHandle.createWritable();
        await writable.write(blob);
        await writable.close();
        exported += 1;
      }
      setExportMessage(`已导出 ${exported} 张图片到 ${directoryHandle.name}`);
    } catch (error) {
      setExportMessage(error instanceof Error ? error.message : "导出失败。");
    } finally {
      setIsExporting(false);
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
          {currentUser ? (
            <>
              <span className="session-chip">{currentUser.display_name || currentUser.username}</span>
              <button className="ghost-button" type="button" onClick={logout}>
                退出
              </button>
            </>
          ) : (
            <span className="session-chip">未登录</span>
          )}
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
            <span>高清 LAMA 擦除</span>
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

      {!isAuthenticated ? (
        <section className="workspace auth-workspace">
          <form className="panel login-panel" onSubmit={handleUserLogin}>
            <div className="section-head">
              <div>
                <p className="eyebrow">Account</p>
                <h2>登录后使用</h2>
              </div>
            </div>
            <label>
              账号
              <input value={loginName} onChange={(event) => setLoginName(event.target.value)} autoComplete="username" />
            </label>
            <label>
              密码
              <input
                type="password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" disabled={isLoginBusy}>
              登录
            </button>
            <p className="status-text">{loginMessage}</p>
          </form>
          <aside className="panel status-panel">
            <div className="section-head compact">
              <div>
                <p className="eyebrow">Usage</p>
                <h2>用户用量将被记录</h2>
              </div>
            </div>
            <p className="status-text">登录后创建的每个任务都会绑定到当前账号，后台可以按用户查看任务、图片数和翻译字符数。</p>
          </aside>
        </section>
      ) : (
        <>
      <section className="workspace">
        <form className="panel upload-panel" onSubmit={handleSubmit}>
          <div className="section-head">
            <div>
              <p className="eyebrow">Step 01</p>
              <h2>上传商品图片</h2>
            </div>
            <span className="file-meta">
              {files.length ? `${files.length} 张 · ${formatBytes(totalSize)} · ${regionCount ? `${regionCount} 个框` : "全图"}` : "尚未选择"}
            </span>
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
              onChange={(event) => {
                updateFiles(Array.from(event.target.files || []));
                event.currentTarget.value = "";
              }}
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

          <ManualRegionEditor
            files={files}
            selectedFileKey={selectedRegionFileKey}
            regions={manualRegions}
            onSelectFile={setSelectedRegionFileKey}
            onChangeRegions={updateRegionsForFile}
          />

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
              href={job?.download_url ? `${apiURL(job.download_url)}?token=${encodeURIComponent(userToken)}` : "#"}
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
          <form className="folder-export" onSubmit={handleFolderExport}>
            <div className="folder-picker">
              <button type="button" onClick={() => void chooseExportFolder()}>
                选择文件夹
              </button>
              <span>{exportDirectoryName || "尚未选择导出文件夹"}</span>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={overwriteExport}
                onChange={(event) => setOverwriteExport(event.target.checked)}
              />
              覆盖同名文件
            </label>
            <button type="submit" disabled={job?.status !== "completed" || isExporting}>
              导出到文件夹
            </button>
            {exportMessage ? <p className="export-message">{exportMessage}</p> : null}
          </form>
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
        </>
      )}
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

function ManualRegionEditor({
  files,
  selectedFileKey,
  regions,
  onSelectFile,
  onChangeRegions,
}: {
  files: File[];
  selectedFileKey: string;
  regions: RegionMap;
  onSelectFile: (key: string) => void;
  onChangeRegions: (file: File, updater: (regions: ManualRegion[]) => ManualRegion[]) => void;
}) {
  const selectedFile = files.find((file) => fileKey(file) === selectedFileKey) || files[0] || null;
  const [previewURL, setPreviewURL] = useState("");
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [draftRegion, setDraftRegion] = useState<ManualRegion | null>(null);
  const activeRegions = selectedFile ? regions[fileKey(selectedFile)] || [] : [];

  useEffect(() => {
    if (!selectedFile) {
      setPreviewURL("");
      return;
    }
    const url = URL.createObjectURL(selectedFile);
    setPreviewURL(url);
    return () => URL.revokeObjectURL(url);
  }, [selectedFile]);

  if (!files.length) {
    return null;
  }

  function normalizedPoint(event: React.PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / Math.max(1, rect.width);
    const y = (event.clientY - rect.top) / Math.max(1, rect.height);
    return {
      x: Math.max(0, Math.min(1, x)),
      y: Math.max(0, Math.min(1, y)),
    };
  }

  function regionFromPoints(start: { x: number; y: number }, end: { x: number; y: number }) {
    const left = Math.min(start.x, end.x);
    const top = Math.min(start.y, end.y);
    return {
      x: left,
      y: top,
      width: Math.abs(end.x - start.x),
      height: Math.abs(end.y - start.y),
    };
  }

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (!selectedFile || event.button !== 0) {
      return;
    }
    event.preventDefault();
    const point = normalizedPoint(event);
    setDragStart(point);
    setDraftRegion({ x: point.x, y: point.y, width: 0, height: 0 });
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragStart) {
      return;
    }
    event.preventDefault();
    setDraftRegion(regionFromPoints(dragStart, normalizedPoint(event)));
  }

  function finishDrawing(event: React.PointerEvent<HTMLDivElement>) {
    if (!dragStart || !selectedFile) {
      return;
    }
    event.preventDefault();
    const finalRegion = draftRegion || regionFromPoints(dragStart, normalizedPoint(event));
    setDragStart(null);
    setDraftRegion(null);
    if (finalRegion.width < 0.01 || finalRegion.height < 0.01) {
      return;
    }
    onChangeRegions(selectedFile, (currentRegions) => [...currentRegions, roundRegion(finalRegion)].slice(0, 20));
  }

  function clearCurrentRegions() {
    if (!selectedFile) {
      return;
    }
    onChangeRegions(selectedFile, () => []);
  }

  function undoCurrentRegion() {
    if (!selectedFile) {
      return;
    }
    onChangeRegions(selectedFile, (currentRegions) => currentRegions.slice(0, -1));
  }

  return (
    <section className="region-panel">
      <div className="region-head">
        <div>
          <p className="eyebrow">Optional Area</p>
          <h3>框选翻译区域</h3>
        </div>
        <span>{activeRegions.length ? `当前 ${activeRegions.length} 个框` : "未框选时全图识别"}</span>
      </div>

      {files.length > 1 ? (
        <div className="region-file-tabs" aria-label="选择要框选的图片">
          {files.map((file) => {
            const key = fileKey(file);
            return (
              <button key={key} type="button" className={key === selectedFileKey ? "active" : ""} onClick={() => onSelectFile(key)}>
                {file.name}
              </button>
            );
          })}
        </div>
      ) : null}

      <div
        className="region-canvas"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishDrawing}
        onPointerCancel={() => {
          setDragStart(null);
          setDraftRegion(null);
        }}
      >
        {previewURL ? <img src={previewURL} alt={selectedFile?.name || "待框选图片"} draggable={false} /> : null}
        {[...activeRegions, ...(draftRegion ? [draftRegion] : [])].map((region, index) => (
          <span
            className={`region-box${index >= activeRegions.length ? " draft" : ""}`}
            key={`${region.x}-${region.y}-${region.width}-${region.height}-${index}`}
            style={{
              left: `${region.x * 100}%`,
              top: `${region.y * 100}%`,
              width: `${region.width * 100}%`,
              height: `${region.height * 100}%`,
            }}
          />
        ))}
      </div>

      <div className="region-actions">
        <button type="button" onClick={undoCurrentRegion} disabled={!activeRegions.length}>
          撤销框选
        </button>
        <button type="button" onClick={clearCurrentRegions} disabled={!activeRegions.length}>
          清空当前
        </button>
      </div>
    </section>
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

function fileKey(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}-${file.type}`;
}

function roundRegion(region: ManualRegion): ManualRegion {
  return {
    x: roundCoordinate(region.x),
    y: roundCoordinate(region.y),
    width: roundCoordinate(region.width),
    height: roundCoordinate(region.height),
  };
}

function roundCoordinate(value: number) {
  return Math.round(Math.max(0, Math.min(1, value)) * 10000) / 10000;
}

async function ensureDirectoryPermission(handle: LocalDirectoryHandle) {
  const options = { mode: "readwrite" as const };
  if (handle.queryPermission && (await handle.queryPermission(options)) === "granted") {
    return true;
  }
  if (handle.requestPermission) {
    return (await handle.requestPermission(options)) === "granted";
  }
  return true;
}

async function nextExportFilename(handle: LocalDirectoryHandle, filename: string, overwrite: boolean) {
  if (overwrite || !(await fileExists(handle, filename))) {
    return filename;
  }
  const dotIndex = filename.lastIndexOf(".");
  const stem = dotIndex > 0 ? filename.slice(0, dotIndex) : filename;
  const ext = dotIndex > 0 ? filename.slice(dotIndex) : "";
  for (let index = 1; index < 10000; index += 1) {
    const candidate = `${stem}_${index}${ext}`;
    if (!(await fileExists(handle, candidate))) {
      return candidate;
    }
  }
  throw new Error("无法生成可用的导出文件名。");
}

async function fileExists(handle: LocalDirectoryHandle, filename: string) {
  try {
    await handle.getFileHandle(filename);
    return true;
  } catch (error) {
    if (error instanceof DOMException && error.name === "NotFoundError") {
      return false;
    }
    throw error;
  }
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
