"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  apiURL,
  cancelCurrentJobItem,
  cancelJob,
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
  queued: "排队",
  processing: "处理中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
  canceled: "已取消",
};

type QueueStatus = "completed" | "processing" | "queued" | "failed" | "canceled";
type RecognitionMode = "auto" | "manual";
type JobRecognitionMode = RecognitionMode | "mixed";
type InpaintEngine = "lama" | "opencv";
type RegionMap = Record<string, ManualRegion[]>;
type FileModeMap = Record<string, RecognitionMode>;
type DemoKind = "shield" | "welder" | "params" | "device" | "cable" | "box" | "manual" | "parts";
type ResizeHandle = "n" | "s" | "e" | "w" | "nw" | "ne" | "sw" | "se";

type QueueRow = {
  id: string;
  index: number;
  name: string;
  sizeLabel: string;
  status: QueueStatus;
  progress: number;
  demoKind?: DemoKind;
  file?: File;
  recognitionMode?: RecognitionMode;
  manualRegionCount?: number;
};

type CanvasAction =
  | { type: "draw"; start: { x: number; y: number } }
  | { type: "move"; index: number; start: { x: number; y: number }; original: ManualRegion }
  | { type: "resize"; index: number; handle: ResizeHandle; start: { x: number; y: number }; original: ManualRegion };

type TaskSnapshot = {
  recognitionMode: JobRecognitionMode;
  modesByKey: FileModeMap;
  sourceLanguage: string;
  targetLanguage: string;
  inpaintEngine: InpaintEngine;
  files: File[];
  regionsByKey: RegionMap;
};

const DEMO_QUEUE: QueueRow[] = [
  { id: "demo-shield", index: 1, name: "实力源头.png", sizeLabel: "312 KB", status: "completed", progress: 100, demoKind: "shield" },
  { id: "demo-welder", index: 2, name: "spot_welder.png", sizeLabel: "198 KB", status: "completed", progress: 100, demoKind: "welder" },
  { id: "demo-params", index: 3, name: "产品参数.png", sizeLabel: "456 KB", status: "processing", progress: 68, demoKind: "params" },
  { id: "demo-device", index: 4, name: "主机.png", sizeLabel: "512 KB", status: "queued", progress: 0, demoKind: "device" },
  { id: "demo-cable", index: 5, name: "充电线.png", sizeLabel: "128 KB", status: "queued", progress: 0, demoKind: "cable" },
  { id: "demo-box", index: 6, name: "包装盒.png", sizeLabel: "256 KB", status: "queued", progress: 0, demoKind: "box" },
  { id: "demo-manual", index: 7, name: "说明书.png", sizeLabel: "298 KB", status: "failed", progress: 0, demoKind: "manual" },
  { id: "demo-parts", index: 8, name: "配件清单.png", sizeLabel: "210 KB", status: "completed", progress: 100, demoKind: "parts" },
];

export default function Home() {
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<TranslationJob | null>(null);
  const [statusText, setStatusText] = useState("上传图片后开始处理。");
  const [progress, setProgress] = useState(0);
  const [workflowState, setWorkflowState] = useState("idle");
  const [sourceLanguage, setSourceLanguage] = useState("zh");
  const [targetLanguage, setTargetLanguage] = useState("en");
  const [inpaintEngine, setInpaintEngine] = useState<InpaintEngine>("lama");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fileModes, setFileModes] = useState<FileModeMap>({});
  const [manualRegions, setManualRegions] = useState<RegionMap>({});
  const [redoRegions, setRedoRegions] = useState<RegionMap>({});
  const [activeTaskSnapshot, setActiveTaskSnapshot] = useState<TaskSnapshot | null>(null);
  const [selectedRegionFileKey, setSelectedRegionFileKey] = useState("");
  const [userToken, setUserToken] = useState("");
  const [currentUser, setCurrentUser] = useState<AdminUser | null>(null);
  const [loginName, setLoginName] = useState("user");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginMessage, setLoginMessage] = useState("请先登录后使用图片翻译。");
  const [isLoginBusy, setIsLoginBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const isAuthenticated = Boolean(userToken && currentUser);
  const totalSize = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files]);
  const isTaskRunning =
    isSubmitting ||
    workflowState === "uploading" ||
    job?.status === "queued" ||
    job?.status === "processing";
  const displayFileModes = isTaskRunning && activeTaskSnapshot ? activeTaskSnapshot.modesByKey : fileModes;
  const displayRegionsByKey =
    isTaskRunning && activeTaskSnapshot ? activeTaskSnapshot.regionsByKey : manualRegions;
  const queueRows = useMemo(
    () => (files.length ? buildQueueRows(files, job, displayFileModes, displayRegionsByKey) : DEMO_QUEUE),
    [files, job, displayFileModes, displayRegionsByKey],
  );
  const selectedFile = useMemo(
    () => files.find((file) => fileKey(file) === selectedRegionFileKey) || files[0] || null,
    [files, selectedRegionFileKey],
  );
  const selectedKey = selectedFile ? fileKey(selectedFile) : "demo-params";
  const selectedRecognitionMode = selectedFile ? displayFileModes[fileKey(selectedFile)] || "auto" : "auto";
  const activeRegions = selectedFile && selectedRecognitionMode === "manual" ? displayRegionsByKey[fileKey(selectedFile)] || [] : [];
  const resultCount = job?.results?.length ?? 0;
  const regionCount = useMemo(
    () =>
      files.reduce((sum, file) => {
        const key = fileKey(file);
        return sum + ((displayFileModes[key] || "auto") === "manual" ? displayRegionsByKey[key]?.length || 0 : 0);
      }, 0),
    [files, displayFileModes, displayRegionsByKey],
  );
  const visibleProgress = files.length || job ? Math.max(0, Math.min(100, progress)) : 23;
  const visibleTotal = job?.total || (files.length ? files.length : 30);
  const visibleCompleted = job?.processed ?? job?.completed ?? (files.length ? resultCount : 7);
  const downloadHref =
    (job?.status === "completed" || job?.status === "partial") && job.download_url
      ? `${apiURL(job.download_url)}?token=${encodeURIComponent(userToken)}`
      : "";
  const failedRetryFiles = useMemo(() => {
    if (!job || (job.status !== "failed" && job.status !== "partial")) {
      return [];
    }
    const completedNames = new Set(job.results?.map((item) => item.source_filename).filter(Boolean));
    return files.filter((file) => !completedNames.has(file.name));
  }, [files, job]);

  const refreshJob = useCallback(async () => {
    if (!job?.job_id || !userToken) {
      return;
    }
    try {
      const nextJob = await fetchJob(job.job_id, userToken);
      renderJobState(nextJob, setWorkflowState, setStatusText, setProgress);
      setJob(nextJob);
      if (nextJob.status === "completed" || nextJob.status === "failed" || nextJob.status === "partial" || nextJob.status === "canceled") {
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

    try {
      setUserToken(savedToken);
      setCurrentUser(JSON.parse(savedUser) as AdminUser);
    } catch {
      clearUserSession();
      return;
    }

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
    if (!job?.job_id || job.status === "completed" || job.status === "failed" || job.status === "partial" || job.status === "canceled") {
      return;
    }
    const timer = window.setInterval(refreshJob, 1200);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status, refreshJob]);

  useEffect(() => {
    if (!files.length) {
      setSelectedRegionFileKey("");
      setFileModes({});
      setManualRegions({});
      setRedoRegions({});
      setActiveTaskSnapshot(null);
      return;
    }

    const keys = new Set(files.map(fileKey));
    setSelectedRegionFileKey((currentKey) => (currentKey && keys.has(currentKey) ? currentKey : fileKey(files[0])));
    setFileModes((currentModes) => {
      const nextModes: FileModeMap = {};
      for (const file of files) {
        const key = fileKey(file);
        nextModes[key] = currentModes[key] || "auto";
      }
      return nextModes;
    });
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
    setRedoRegions((currentRegions) => {
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
    setFileModes({});
    setManualRegions({});
    setRedoRegions({});
    setActiveTaskSnapshot(null);
    setWorkflowState("idle");
    setProgress(0);
    setStatusText("请登录后上传图片。");
    setLoginMessage("已退出登录。");
  }

  function openFilePicker() {
    if (!fileInputRef.current) {
      setStatusText("图片选择器还没有准备好，请稍后再试。");
      return;
    }
    fileInputRef.current.value = "";
    fileInputRef.current.click();
  }

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

      if (uniqueNewFiles[0]) {
        setSelectedRegionFileKey(fileKey(uniqueNewFiles[0]));
        setJob(null);
        setActiveTaskSnapshot(null);
        setProgress(0);
        setWorkflowState("idle");
      }
      if (overflowCount > 0) {
        setStatusText(`已达到单次最多 ${MAX_FILES} 张，自动保留前 ${MAX_FILES} 张图片。`);
      } else if (duplicateCount > 0 && uniqueNewFiles.length > 0) {
        setStatusText(`已添加 ${uniqueNewFiles.length} 张，跳过 ${duplicateCount} 个重复文件，当前共 ${cappedFiles.length} 张。`);
      } else if (duplicateCount > 0) {
        setStatusText("这批图片已经在队列里了；如需重新处理同一张图，请先清空队列或选择其他文件。");
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
    setRedoRegions((currentRegions) => ({
      ...currentRegions,
      [key]: [],
    }));
  }

  function enterManualModeForSelectedFile() {
    if (!selectedFile || isTaskRunning) {
      return;
    }
    const key = fileKey(selectedFile);
    setFileModes((currentModes) => ({
      ...currentModes,
      [key]: "manual",
    }));
    setStatusText(`${selectedFile.name} 已切换为手动框选，处理前可继续调整选区。`);
  }

  function cancelManualModeForSelectedFile() {
    if (!selectedFile || isTaskRunning) {
      return;
    }
    const key = fileKey(selectedFile);
    const regions = manualRegions[key] || [];
    if (regions.length) {
      const shouldClear = window.confirm("取消后会清空当前图片的手动框选区域，并改为自动识别。确定取消手动框选吗？");
      if (!shouldClear) {
        return;
      }
    }
    setFileModes((currentModes) => ({
      ...currentModes,
      [key]: "auto",
    }));
    setManualRegions((currentRegions) => {
      const nextRegions = { ...currentRegions };
      delete nextRegions[key];
      return nextRegions;
    });
    setRedoRegions((currentRedoRegions) => {
      const nextRedoRegions = { ...currentRedoRegions };
      delete nextRedoRegions[key];
      return nextRedoRegions;
    });
    setStatusText(`${selectedFile.name} 已取消手动框选，将使用自动识别。`);
  }

  function copyActiveRegionsToAll() {
    if (!files.length || !selectedFile) {
      setStatusText("请先添加图片并选择需要复制的框选区域。");
      return;
    }
    if (!activeRegions.length) {
      setStatusText("当前图片还没有框选区域，先在画布上拖拽框选。");
      return;
    }

    setManualRegions(() => {
      const nextRegions: RegionMap = {};
      for (const file of files) {
        nextRegions[fileKey(file)] = activeRegions.map((region) => ({ ...region }));
      }
      return nextRegions;
    });
    setFileModes(() => {
      const nextModes: FileModeMap = {};
      for (const file of files) {
        nextModes[fileKey(file)] = "manual";
      }
      return nextModes;
    });
    setRedoRegions({});
    setStatusText(`已将当前 ${activeRegions.length} 个框选区域复制到全部图片。`);
  }

  function clearQueue() {
    setFiles([]);
    setJob(null);
    setFileModes({});
    setManualRegions({});
    setRedoRegions({});
    setActiveTaskSnapshot(null);
    setProgress(0);
    setWorkflowState("idle");
    setStatusText("队列已清空，可以重新添加图片。");
  }

  function undoRegionForSelectedFile() {
    if (!selectedFile) {
      return;
    }
    const key = fileKey(selectedFile);
    const currentFileRegions = manualRegions[key] || [];
    if (!currentFileRegions.length) {
      return;
    }
    const removedRegion = currentFileRegions[currentFileRegions.length - 1];
    setManualRegions((currentRegions) => ({
      ...currentRegions,
      [key]: (currentRegions[key] || []).slice(0, -1),
    }));
    setRedoRegions((currentRedoRegions) => ({
      ...currentRedoRegions,
      [key]: [...(currentRedoRegions[key] || []), removedRegion],
    }));
  }

  function redoRegionForSelectedFile() {
    if (!selectedFile) {
      return;
    }
    const key = fileKey(selectedFile);
    const currentRedo = redoRegions[key] || [];
    if (!currentRedo.length) {
      return;
    }
    const restoredRegion = currentRedo[currentRedo.length - 1];
    setManualRegions((currentRegions) => ({
      ...currentRegions,
      [key]: [...(currentRegions[key] || []), restoredRegion],
    }));
    setRedoRegions((currentRedoRegions) => ({
      ...currentRedoRegions,
      [key]: (currentRedoRegions[key] || []).slice(0, -1),
    }));
  }

  function createTaskSnapshot(targetFiles: File[]): TaskSnapshot {
    const regionsByKey: RegionMap = {};
    const modesByKey: FileModeMap = {};
    for (const file of targetFiles) {
      const key = fileKey(file);
      const mode = fileModes[key] || "auto";
      modesByKey[key] = mode;
      regionsByKey[key] = mode === "manual" ? (manualRegions[key] || []).map((region) => ({ ...region })) : [];
    }
    return {
      recognitionMode: summarizeFileModes(targetFiles, modesByKey),
      modesByKey,
      sourceLanguage,
      targetLanguage,
      inpaintEngine,
      files: [...targetFiles],
      regionsByKey,
    };
  }

  async function handleUserLogin(event: FormEvent<HTMLFormElement>) {
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

  async function startTranslation(targetFiles = files) {
    if (!isAuthenticated) {
      setStatusText("请先登录后再创建翻译任务。");
      setProgress(0);
      return;
    }
    if (!targetFiles.length) {
      setStatusText("请先添加要翻译的商品图片。");
      setProgress(0);
      return;
    }
    const missingManualRegions = targetFiles.filter((file) => {
      const key = fileKey(file);
      return (fileModes[key] || "auto") === "manual" && !(manualRegions[key] || []).length;
    });
    if (missingManualRegions.length) {
      setStatusText(`手动框选图片需要至少 1 个选区：${missingManualRegions.map((file) => file.name).join("、")}`);
      setProgress(0);
      return;
    }

    const taskSnapshot = createTaskSnapshot(targetFiles);
    setActiveTaskSnapshot(taskSnapshot);
    setIsSubmitting(true);
    setJob(null);
    setWorkflowState("uploading");
    setStatusText("正在上传图片。");
    setProgress(3);

    try {
      const modesByFile = targetFiles.map((file) => taskSnapshot.modesByKey[fileKey(file)] || "auto");
      const regionsByFile = targetFiles.map((file) => {
        const key = fileKey(file);
        return taskSnapshot.modesByKey[key] === "manual" ? taskSnapshot.regionsByKey[key] || [] : [];
      });
      const createdJob = await createJob(targetFiles, sourceLanguage, targetLanguage, {
        token: userToken,
        manualRegions: regionsByFile,
        recognitionModes: modesByFile,
        inpaintEngine,
        recognitionMode: taskSnapshot.recognitionMode,
      });
      renderJobState(createdJob, setWorkflowState, setStatusText, setProgress);
      setJob(createdJob);
    } catch (error) {
      setActiveTaskSnapshot(null);
      setWorkflowState("failed");
      setStatusText(error instanceof Error ? error.message : "任务创建失败。");
      setProgress(0);
      setIsSubmitting(false);
    }
  }

  function retryFailedImages() {
    if (!failedRetryFiles.length) {
      setStatusText("当前没有失败项可重跑。");
      return;
    }
    setFiles(failedRetryFiles);
    setSelectedRegionFileKey(fileKey(failedRetryFiles[0]));
    setStatusText(`已筛出 ${failedRetryFiles.length} 张失败图片，正在重跑。`);
    void startTranslation(failedRetryFiles);
  }

  async function cancelCurrentImage() {
    if (!job?.job_id || !userToken) {
      return;
    }
    try {
      const nextJob = await cancelCurrentJobItem(job.job_id, userToken);
      renderJobState(nextJob, setWorkflowState, setStatusText, setProgress);
      setJob(nextJob);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "取消当前图片失败。");
    }
  }

  async function cancelEntireJob() {
    if (!job?.job_id || !userToken) {
      return;
    }
    try {
      const nextJob = await cancelJob(job.job_id, userToken);
      renderJobState(nextJob, setWorkflowState, setStatusText, setProgress);
      setJob(nextJob);
      setIsSubmitting(false);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "取消整批任务失败。");
    }
  }

  return (
    <main className="batch-app">
      <header className="batch-header" aria-label="主导航">
        <a className="batch-brand" href="/" aria-label="Cuckoo Image Translation 首页">
          <span className="cuckoo-mark" aria-hidden="true">
            C
          </span>
          <strong>Cuckoo Image Translation</strong>
        </a>
        <nav className="batch-nav" aria-label="用户操作">
          {currentUser ? (
            <>
              <span className="batch-avatar">{avatarLetter(currentUser)}</span>
              <button className="user-menu-button" type="button" title={currentUser.username}>
                {currentUser.display_name || currentUser.username}
                <span aria-hidden="true">⌄</span>
              </button>
              <button className="plain-nav-button" type="button" onClick={logout}>
                退出
              </button>
            </>
          ) : (
            <span className="batch-session">未登录</span>
          )}
          <a className="admin-nav-link" href="/admin">
            <GearIcon />
            管理后台
          </a>
        </nav>
      </header>

      <input
        ref={fileInputRef}
        className="batch-file-input"
        type="file"
        accept="image/*"
        multiple
        aria-label="选择商品图片"
        onChange={(event) => {
          updateFiles(Array.from(event.target.files || []));
          event.currentTarget.value = "";
        }}
      />

      {!isAuthenticated ? (
        <AuthLanding
          loginName={loginName}
          loginPassword={loginPassword}
          loginMessage={loginMessage}
          isLoginBusy={isLoginBusy}
          onLoginNameChange={setLoginName}
          onLoginPasswordChange={setLoginPassword}
          onSubmit={handleUserLogin}
        />
      ) : (
        <section className="batch-workspace">
          <QueuePanel
            rows={queueRows}
            selectedKey={selectedKey}
            totalSize={totalSize}
            regionCount={regionCount}
            actionsDisabled={isTaskRunning}
            onAddClick={openFilePicker}
            onCopyClick={copyActiveRegionsToAll}
            onSelectRow={(row) => {
              if (row.file) {
                setSelectedRegionFileKey(fileKey(row.file));
              }
            }}
          />

          <section className="workspace-main" aria-label="图片翻译工作区">
            <ImageEditorPanel
              file={selectedFile}
              regions={activeRegions}
              filesCount={files.length}
              statusText={statusText}
              workflowState={workflowState}
              recognitionMode={selectedRecognitionMode}
              isLocked={isTaskRunning}
              canRedo={selectedFile ? Boolean(redoRegions[fileKey(selectedFile)]?.length) : false}
              onEnterManualMode={enterManualModeForSelectedFile}
              onCancelManualMode={cancelManualModeForSelectedFile}
              onAddRegion={(region) => {
                if (selectedFile) {
                  updateRegionsForFile(selectedFile, (currentRegions) => [...currentRegions, region].slice(0, 20));
                }
              }}
              onChangeRegion={(index, region) => {
                if (selectedFile) {
                  updateRegionsForFile(selectedFile, (currentRegions) =>
                    currentRegions.map((currentRegion, currentIndex) => (currentIndex === index ? region : currentRegion)),
                  );
                }
              }}
              onDeleteRegion={(index) => {
                if (selectedFile) {
                  updateRegionsForFile(selectedFile, (currentRegions) =>
                    currentRegions.filter((_, currentIndex) => currentIndex !== index),
                  );
                }
              }}
              onUndoRegion={undoRegionForSelectedFile}
              onRedoRegion={redoRegionForSelectedFile}
            />

            <ResultPreviewPanel
              files={files}
              job={job}
              downloadHref={downloadHref}
              onRetry={retryFailedImages}
              isRetryDisabled={isSubmitting || !failedRetryFiles.length}
            />
          </section>

          <TaskPanel
            rows={queueRows}
            sourceLanguage={sourceLanguage}
            targetLanguage={targetLanguage}
            inpaintEngine={inpaintEngine}
            progress={visibleProgress}
            completed={visibleCompleted}
            total={visibleTotal}
            isSubmitting={isSubmitting}
            hasFiles={files.length > 0}
            isTaskLocked={isTaskRunning}
            onSourceLanguageChange={setSourceLanguage}
            onTargetLanguageChange={setTargetLanguage}
            onInpaintEngineChange={setInpaintEngine}
            onStart={() => void startTranslation()}
            onClearQueue={clearQueue}
            onCancelCurrent={() => void cancelCurrentImage()}
            onCancelJob={() => void cancelEntireJob()}
          />
        </section>
      )}
    </main>
  );
}

function AuthLanding({
  loginName,
  loginPassword,
  loginMessage,
  isLoginBusy,
  onLoginNameChange,
  onLoginPasswordChange,
  onSubmit,
}: {
  loginName: string;
  loginPassword: string;
  loginMessage: string;
  isLoginBusy: boolean;
  onLoginNameChange: (value: string) => void;
  onLoginPasswordChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section className="login-shell">
      <div className="login-copy">
        <p className="login-eyebrow">BATCH IMAGE TRANSLATION</p>
        <h1>商品图中文一键识别、擦除、翻译并回写</h1>
        <p>保持原图设计和分辨率，只替换图片里的中文说明，支持批量上传、手动框选、高清 LAMA 擦除、预览和 ZIP 打包下载。</p>
        <div className="login-badges" aria-label="核心能力">
          <span>1-30 张批量上传</span>
          <span>高清 LAMA 擦除</span>
          <span>OCR + 翻译 + 回写</span>
        </div>
      </div>
      <form className="login-card" onSubmit={onSubmit}>
        <p className="panel-kicker">ACCOUNT</p>
        <h2>登录后使用</h2>
        <label>
          账号
          <input value={loginName} onChange={(event) => onLoginNameChange(event.target.value)} autoComplete="username" />
        </label>
        <label>
          密码
          <input
            type="password"
            value={loginPassword}
            onChange={(event) => onLoginPasswordChange(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        <button type="submit" disabled={isLoginBusy}>
          登录
        </button>
        <p className="login-message">{loginMessage}</p>
      </form>
    </section>
  );
}

function QueuePanel({
  rows,
  selectedKey,
  totalSize,
  regionCount,
  actionsDisabled,
  onAddClick,
  onCopyClick,
  onSelectRow,
}: {
  rows: QueueRow[];
  selectedKey: string;
  totalSize: number;
  regionCount: number;
  actionsDisabled: boolean;
  onAddClick: () => void;
  onCopyClick: () => void;
  onSelectRow: (row: QueueRow) => void;
}) {
  return (
    <aside className="queue-panel">
      <div className="panel-title-row">
        <h2>图片队列</h2>
        <span className="count-pill">{rows.length}</span>
      </div>

      <div className="queue-list" aria-label="图片队列">
        {rows.map((row) => {
          const rowKey = row.file ? fileKey(row.file) : row.id;
          return (
            <button
              className={`queue-row${rowKey === selectedKey ? " active" : ""}`}
              key={row.id}
              type="button"
              onClick={() => onSelectRow(row)}
            >
              <span className="queue-index">{row.index}</span>
              <QueueThumb row={row} />
              <span className="queue-meta">
                <strong>{row.name}</strong>
                <small>{row.sizeLabel}</small>
              </span>
              <StatusBadge status={row.status} recognitionMode={row.recognitionMode} manualRegionCount={row.manualRegionCount || 0} />
            </button>
          );
        })}
      </div>

      <div className="queue-summary">
        <span>{totalSize ? `已选 ${formatBytes(totalSize)}` : "示例队列"}</span>
        <span>{regionCount ? `${regionCount} 个框选区域` : "可手动框选"}</span>
      </div>

      <div className="queue-actions">
        <button className="primary-action" type="button" onClick={onAddClick} disabled={actionsDisabled}>
          <span aria-hidden="true">+</span>
          添加图片
        </button>
        <button className="secondary-action" type="button" onClick={onCopyClick} disabled={actionsDisabled}>
          <CopyIcon />
          复制当前框选到全部图片
        </button>
      </div>
    </aside>
  );
}

function ImageEditorPanel({
  file,
  regions,
  filesCount,
  statusText,
  workflowState,
  recognitionMode,
  isLocked,
  canRedo,
  onEnterManualMode,
  onCancelManualMode,
  onAddRegion,
  onChangeRegion,
  onDeleteRegion,
  onUndoRegion,
  onRedoRegion,
}: {
  file: File | null;
  regions: ManualRegion[];
  filesCount: number;
  statusText: string;
  workflowState: string;
  recognitionMode: RecognitionMode;
  isLocked: boolean;
  canRedo: boolean;
  onEnterManualMode: () => void;
  onCancelManualMode: () => void;
  onAddRegion: (region: ManualRegion) => void;
  onChangeRegion: (index: number, region: ManualRegion) => void;
  onDeleteRegion: (index: number) => void;
  onUndoRegion: () => void;
  onRedoRegion: () => void;
}) {
  const [selectedRegionIndex, setSelectedRegionIndex] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    if (selectedRegionIndex > regions.length - 1) {
      setSelectedRegionIndex(Math.max(0, regions.length - 1));
    }
  }, [regions.length, selectedRegionIndex]);

  useEffect(() => {
    if (!isExpanded) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsExpanded(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isExpanded]);

  const isManualMode = recognitionMode === "manual";
  const visibleRegions = isManualMode ? regions : [];
  const hasRegions = visibleRegions.length > 0;
  const selectedRegionExists = !isLocked && isManualMode && selectedRegionIndex >= 0 && selectedRegionIndex < visibleRegions.length;
  const zoomPercent = Math.round(zoom * 100);
  const hintText = !filesCount
    ? "当前显示示例图，添加图片后即可框选真实区域"
    : isLocked && isManualMode
      ? "处理中 · 手动框选快照 · 选框不可修改"
    : isLocked
      ? "处理中 · 自动识别扫描整张图，无需框选区域"
    : isManualMode
      ? "拖拽框选区域，调整大小和位置"
      : "自动识别会扫描整张图，无需框选区域";
  const taskBadge = isLocked
    ? `当前任务：${recognitionMode === "manual" ? "手动框选" : "自动识别"}处理中`
    : `${isManualMode ? "手动框选" : "自动识别"}编辑模式`;

  function changeZoom(delta: number) {
    setZoom((currentZoom) => Math.round(clamp(currentZoom + delta, 0.5, 3) * 100) / 100);
  }

  function resetZoom() {
    setZoom(1);
  }

  function openExpandedEditor() {
    if (!file) {
      return;
    }
    setZoom((currentZoom) => Math.max(currentZoom, 1.35));
    setIsExpanded(true);
  }

  function renderCanvas(expanded = false) {
    return file ? (
      <ManualImageCanvas
        file={file}
        regions={visibleRegions}
        readOnly={!isManualMode || isLocked}
        selectedRegionIndex={selectedRegionIndex}
        zoom={zoom}
        expanded={expanded}
        onSelectRegion={setSelectedRegionIndex}
        onAddRegion={(region) => {
          onAddRegion(region);
          setSelectedRegionIndex(regions.length);
        }}
        onChangeRegion={onChangeRegion}
      />
    ) : (
      <DemoProductCanvas />
    );
  }

  return (
    <section className="canvas-panel">
      <div className="canvas-toolbar">
        <div className="canvas-mode-group">
          {isLocked ? (
            <>
              <div className={`task-mode-pill locked`}>
                <span>{taskBadge}</span>
              </div>
              <div className="task-lock-note" aria-label="选区已锁定，只读显示">
                <LockIcon />
                <span>选区已锁定，只读显示</span>
              </div>
            </>
          ) : isManualMode ? (
            <div className="manual-mode-toolbar" aria-label="当前图片手动框选设置">
              <span className="manual-mode-notice">
                <InfoIcon />
                此图片将按手动框选处理
              </span>
              <button className="manual-cancel-button" type="button" onClick={onCancelManualMode}>
                取消手动框选
              </button>
              <span className="manual-mode-help">取消后可重新使用自动识别</span>
            </div>
          ) : (
            <>
              <div className="segmented-control" aria-label="当前图片识别方式">
                <button className="active" type="button" aria-pressed="true">
                  自动识别
                </button>
                <button type="button" aria-pressed="false" onClick={onEnterManualMode}>
                  手动框选
                </button>
              </div>
              <div className="task-mode-pill">
                <span>{taskBadge}</span>
              </div>
            </>
          )}
        </div>
        <div className="canvas-tools" aria-label="画布工具">
          <button type="button" onClick={onUndoRegion} disabled={isLocked || !hasRegions || !isManualMode} title="撤销上一个框选">
            ↶
          </button>
          <button type="button" onClick={onRedoRegion} disabled={isLocked || !canRedo || !isManualMode} title="重做框选">
            ↷
          </button>
          <div className="zoom-control" aria-label="缩放">
            <button type="button" onClick={() => changeZoom(-0.1)} disabled={zoom <= 0.5} title="缩小">
              −
            </button>
            <span>{zoomPercent}%</span>
            <button type="button" onClick={() => changeZoom(0.1)} disabled={zoom >= 3} title="放大">
              +
            </button>
          </div>
          <button type="button" onClick={openExpandedEditor} disabled={!file} title="放大编辑">
            ⛶
          </button>
        </div>
      </div>

      <div className="image-stage-shell">{renderCanvas()}</div>

      {isExpanded && file ? (
        <div className="canvas-expanded-backdrop" role="dialog" aria-modal="true" aria-label="放大编辑图片">
          <div className="canvas-expanded-panel">
            <div className="canvas-expanded-toolbar">
              <strong>{file.name}</strong>
              <div className="canvas-expanded-tools">
                <button type="button" onClick={resetZoom}>
                  适配
                </button>
                <div className="zoom-control" aria-label="放大编辑缩放">
                  <button type="button" onClick={() => changeZoom(-0.1)} disabled={zoom <= 0.5} title="缩小">
                    −
                  </button>
                  <span>{zoomPercent}%</span>
                  <button type="button" onClick={() => changeZoom(0.1)} disabled={zoom >= 3} title="放大">
                    +
                  </button>
                </div>
                <button type="button" onClick={() => setIsExpanded(false)} aria-label="关闭放大编辑">
                  X
                </button>
              </div>
            </div>
            <div className="image-stage-shell expanded">{renderCanvas(true)}</div>
          </div>
        </div>
      ) : null}

      <div className="canvas-hint-row">
        <span className="info-dot">i</span>
        <span>{hintText}</span>
        <span className="hint-separator">|</span>
        <button
          className="text-tool-button"
          type="button"
          disabled={!selectedRegionExists}
          onClick={() => {
            onDeleteRegion(selectedRegionIndex);
            setSelectedRegionIndex(Math.max(0, selectedRegionIndex - 1));
          }}
        >
          <TrashIcon />
          删除选中区域
        </button>
      </div>

      <p className={`canvas-status ${workflowState}`}>{statusText}</p>
    </section>
  );
}

function ManualImageCanvas({
  file,
  regions,
  readOnly,
  selectedRegionIndex,
  zoom,
  expanded = false,
  onSelectRegion,
  onAddRegion,
  onChangeRegion,
}: {
  file: File;
  regions: ManualRegion[];
  readOnly: boolean;
  selectedRegionIndex: number;
  zoom: number;
  expanded?: boolean;
  onSelectRegion: (index: number) => void;
  onAddRegion: (region: ManualRegion) => void;
  onChangeRegion: (index: number, region: ManualRegion) => void;
}) {
  const previewURL = useObjectURL(file);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [action, setAction] = useState<CanvasAction | null>(null);
  const [draftRegion, setDraftRegion] = useState<ManualRegion | null>(null);

  useEffect(() => {
    if (readOnly) {
      setAction(null);
      setDraftRegion(null);
    }
  }, [readOnly]);

  function normalizedPoint(event: ReactPointerEvent<HTMLElement>) {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) {
      return { x: 0, y: 0 };
    }
    const x = (event.clientX - rect.left) / Math.max(1, rect.width);
    const y = (event.clientY - rect.top) / Math.max(1, rect.height);
    return {
      x: clamp(x, 0, 1),
      y: clamp(y, 0, 1),
    };
  }

  function capturePointer(event: ReactPointerEvent<HTMLElement>) {
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Selection continues to work if a browser rejects capture after a fast release.
    }
  }

  function capturePointerOnFrame(event: ReactPointerEvent<HTMLElement>) {
    try {
      frameRef.current?.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture is an interaction aid, not a requirement.
    }
  }

  function releasePointerCapture(event: ReactPointerEvent<HTMLElement>) {
    const frame = frameRef.current;
    if (frame?.hasPointerCapture(event.pointerId)) {
      frame.releasePointerCapture(event.pointerId);
    }
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleFramePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (readOnly || event.button !== 0) {
      return;
    }
    event.preventDefault();
    const point = normalizedPoint(event);
    onSelectRegion(-1);
    setAction({ type: "draw", start: point });
    setDraftRegion({ x: point.x, y: point.y, width: 0, height: 0 });
    capturePointer(event);
  }

  function handleRegionPointerDown(event: ReactPointerEvent<HTMLSpanElement>, index: number) {
    if (readOnly || event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onSelectRegion(index);
    setDraftRegion(null);
    setAction({ type: "move", index, start: normalizedPoint(event), original: regions[index] });
    capturePointerOnFrame(event);
  }

  function handleResizePointerDown(event: ReactPointerEvent<HTMLSpanElement>, index: number, handle: ResizeHandle) {
    if (readOnly || event.button !== 0) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    onSelectRegion(index);
    setDraftRegion(null);
    setAction({ type: "resize", index, handle, start: normalizedPoint(event), original: regions[index] });
    capturePointerOnFrame(event);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (readOnly || !action) {
      return;
    }
    event.preventDefault();
    const point = normalizedPoint(event);

    if (action.type === "draw") {
      setDraftRegion(regionFromPoints(action.start, point));
      return;
    }

    if (action.type === "move") {
      const dx = point.x - action.start.x;
      const dy = point.y - action.start.y;
      onChangeRegion(action.index, {
        ...action.original,
        x: roundCoordinate(clamp(action.original.x + dx, 0, 1 - action.original.width)),
        y: roundCoordinate(clamp(action.original.y + dy, 0, 1 - action.original.height)),
      });
      return;
    }

    onChangeRegion(action.index, resizeRegionFromHandle(action.original, point.x - action.start.x, point.y - action.start.y, action.handle));
  }

  function finishPointer(event: ReactPointerEvent<HTMLDivElement>) {
    releasePointerCapture(event);
    if (readOnly || !action) {
      return;
    }
    event.preventDefault();
    if (action.type === "draw" && draftRegion && draftRegion.width >= 0.01 && draftRegion.height >= 0.01) {
      onAddRegion(roundRegion(draftRegion));
    }
    setAction(null);
    setDraftRegion(null);
  }

  const stageMaxHeight = expanded ? `${Math.round(82 * zoom)}vh` : `${Math.round(59 * zoom)}vh`;
  const stageMaxWidth = `${Math.round(100 * zoom)}%`;

  return (
    <div
      className={`image-stage${readOnly ? " read-only" : ""}${expanded ? " expanded" : ""}`}
      ref={frameRef}
      style={{ maxHeight: stageMaxHeight, maxWidth: stageMaxWidth }}
      onPointerDown={handleFramePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPointer}
      onPointerCancel={(event) => {
        releasePointerCapture(event);
        setAction(null);
        setDraftRegion(null);
      }}
      onLostPointerCapture={() => {
        setAction(null);
        setDraftRegion(null);
      }}
    >
      {previewURL ? <img src={previewURL} alt={file.name} draggable={false} style={{ maxHeight: stageMaxHeight, maxWidth: stageMaxWidth }} /> : null}
      {[...regions, ...(draftRegion ? [draftRegion] : [])].map((region, index) => {
        const isDraft = index >= regions.length;
        return (
          <span
            className={`workspace-region${isDraft ? " draft" : ""}${readOnly ? " locked" : ""}${index === selectedRegionIndex ? " selected" : ""}`}
            key={`${region.x}-${region.y}-${region.width}-${region.height}-${index}`}
            style={{
              left: `${region.x * 100}%`,
              top: `${region.y * 100}%`,
              width: `${region.width * 100}%`,
              height: `${region.height * 100}%`,
            }}
            onPointerDown={isDraft ? undefined : (event) => handleRegionPointerDown(event, index)}
          >
            {!isDraft ? <span className="region-number">{index + 1}</span> : null}
            {!isDraft && !readOnly
              ? (["nw", "n", "ne", "e", "se", "s", "sw", "w"] as ResizeHandle[]).map((handle) => (
                  <span
                    className={`region-resize-handle ${handle}`}
                    key={handle}
                    onPointerDown={(event) => handleResizePointerDown(event, index, handle)}
                  />
                ))
              : null}
          </span>
        );
      })}
    </div>
  );
}

function DemoProductCanvas() {
  return (
    <div className="demo-product-sheet" aria-label="产品参数示例图">
      <div className="demo-title">产品参数</div>
      <div className="demo-clipboard">▣</div>
      <div className="demo-table">
        <div>参数</div>
        <div>规格</div>
        <div>产品型号</div>
        <div>ERD-10</div>
        <div>屏幕材质</div>
        <div>2.4寸彩屏</div>
        <div>背光</div>
        <div>背光亮度可调</div>
        <div>供电电源</div>
        <div>TYPE-C (5V/1A)</div>
        <div>电池</div>
        <div>1000mAh</div>
        <div>语言</div>
        <div>中文, English</div>
        <div>产品尺寸</div>
        <div>≈143×68×29mm</div>
        <div>裸机重量</div>
        <div>≈143g</div>
      </div>
      <span className="demo-region demo-region-title">
        <span className="region-number">1</span>
      </span>
      <span className="demo-region demo-region-head">
        <span className="region-number">2</span>
      </span>
      <span className="demo-region demo-region-body">
        <span className="region-number">3</span>
      </span>
    </div>
  );
}

function ResultPreviewPanel({
  files,
  job,
  downloadHref,
  onRetry,
  isRetryDisabled,
}: {
  files: File[];
  job: TranslationJob | null;
  downloadHref: string;
  onRetry: () => void;
  isRetryDisabled: boolean;
}) {
  const canDownload = Boolean(downloadHref);

  return (
    <section className="preview-panel">
      <div className="preview-title-row">
        <h2>结果预览（原图 / 译图对比）</h2>
        <span className="info-dot">i</span>
      </div>
      <div className="preview-strip" aria-live="polite">
        {job?.results?.length ? (
          job.results.slice(0, 5).map((item) => <TranslatedPreviewCard item={item} key={`${item.source_filename}-${item.output_filename}`} />)
        ) : files.length ? (
          files.slice(0, 5).map((file, index) => <LocalPreviewCard file={file} index={index} key={fileKey(file)} />)
        ) : (
          <>
            <DemoPreviewCard kind="params" label="原图" />
            <DemoPreviewCard kind="params-translated" label="译图" />
            <DemoPreviewCard kind="welder" label="原图" />
            <DemoPreviewCard kind="welder-translated" label="译图" />
            <DemoPreviewCard kind="device" label="原图" />
            <DemoPreviewCard kind="device-translated" label="译图" />
          </>
        )}
        <div className="more-preview-card">
          <span>更多结果</span>
          <strong>···</strong>
        </div>
      </div>
      <div className="preview-actions">
        <a className={`primary-action download-action${canDownload ? "" : " disabled"}`} href={canDownload ? downloadHref : "#"} aria-disabled={!canDownload}>
          <DownloadIcon />
          下载全部 ZIP
        </a>
        <button className="secondary-action retry-action" type="button" onClick={onRetry} disabled={isRetryDisabled}>
          <RefreshIcon />
          只重跑失败项
        </button>
      </div>
    </section>
  );
}

function TaskPanel({
  rows,
  sourceLanguage,
  targetLanguage,
  inpaintEngine,
  progress,
  completed,
  total,
  isSubmitting,
  hasFiles,
  isTaskLocked,
  onSourceLanguageChange,
  onTargetLanguageChange,
  onInpaintEngineChange,
  onStart,
  onClearQueue,
  onCancelCurrent,
  onCancelJob,
}: {
  rows: QueueRow[];
  sourceLanguage: string;
  targetLanguage: string;
  inpaintEngine: InpaintEngine;
  progress: number;
  completed: number;
  total: number;
  isSubmitting: boolean;
  hasFiles: boolean;
  isTaskLocked: boolean;
  onSourceLanguageChange: (value: string) => void;
  onTargetLanguageChange: (value: string) => void;
  onInpaintEngineChange: (value: InpaintEngine) => void;
  onStart: () => void;
  onClearQueue: () => void;
  onCancelCurrent: () => void;
  onCancelJob: () => void;
}) {
  return (
    <aside className="task-panel">
      <h2>批量任务</h2>
      <div className="task-controls">
        <label>
          源语言
          <span className={`select-shell${isTaskLocked ? " locked" : ""}`}>
            <select value={sourceLanguage} onChange={(event) => onSourceLanguageChange(event.target.value)} disabled={isTaskLocked}>
              <option value="zh">中文</option>
            </select>
            {isTaskLocked ? <LockIcon /> : null}
          </span>
        </label>
        <label>
          目标语言
          <span className={`select-shell${isTaskLocked ? " locked" : ""}`}>
            <select value={targetLanguage} onChange={(event) => onTargetLanguageChange(event.target.value)} disabled={isTaskLocked}>
              <option value="en">英文</option>
              <option value="ja">日文</option>
              <option value="ko">韩文</option>
              <option value="fr">法文</option>
              <option value="de">德文</option>
            </select>
            {isTaskLocked ? <LockIcon /> : null}
          </span>
        </label>
        <label>
          擦除模式
          <span className={`select-shell${isTaskLocked ? " locked" : ""}`}>
            <select value={inpaintEngine} onChange={(event) => onInpaintEngineChange(event.target.value as InpaintEngine)} disabled={isTaskLocked}>
              <option value="lama">高清 LAMA 擦除</option>
              <option value="opencv">快速 OpenCV 擦除</option>
            </select>
            {isTaskLocked ? <LockIcon /> : null}
          </span>
        </label>
        <label>
          处理策略
          <span className={`select-shell${isTaskLocked ? " locked" : ""}`}>
            <select value="continue" disabled>
              <option value="continue">失败继续</option>
            </select>
            {isTaskLocked ? <LockIcon /> : null}
          </span>
        </label>
      </div>

      {!isTaskLocked ? (
        <button className="task-start-button" type="button" onClick={onStart} disabled={isSubmitting || !hasFiles}>
          {isSubmitting ? "处理中..." : "开始批量翻译"}
        </button>
      ) : null}

      {isTaskLocked ? (
        <div className="task-cancel-actions">
          <button className="secondary-action cancel-current-action" type="button" onClick={onCancelCurrent}>
            取消当前图并继续队列
          </button>
          <button className="danger-action cancel-job-action" type="button" onClick={onCancelJob}>
            取消整批任务
          </button>
        </div>
      ) : null}

      <div className="task-progress-head">
        <h3>总体进度</h3>
        <strong>
          {completed} / {total}
        </strong>
      </div>
      <div className="task-progress-row">
        <div className="task-progress-track">
          <span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
        </div>
        <span>{Math.round(progress)}%</span>
      </div>

      <h3 className="task-subtitle">图片处理进度</h3>
      <div className="task-list" aria-label="图片处理进度">
        {rows.map((row) => (
          <div className="task-list-row" key={`task-${row.id}`}>
            <span className="queue-index small">{row.index}</span>
            <span className="task-file-name">{row.name}</span>
            <TaskModeBadge row={row} />
            {row.status !== "queued" ? <span className={`task-state ${row.status}`}>{taskStateText(row)}</span> : null}
            {row.status === "processing" || row.status === "queued" ? (
              <div className="mini-progress">
                <span style={{ width: `${row.progress}%` }} />
              </div>
            ) : null}
          </div>
        ))}
      </div>

      <button className="danger-action" type="button" onClick={onClearQueue} disabled={isTaskLocked}>
        <TrashIcon />
        清空队列
      </button>
    </aside>
  );
}

function QueueThumb({ row }: { row: QueueRow }) {
  if (row.file) {
    return <LocalImageThumb file={row.file} className="queue-thumb" />;
  }
  return (
    <span className={`queue-thumb demo-thumb ${row.demoKind || "params"}`} aria-hidden="true">
      <span />
    </span>
  );
}

function LocalImageThumb({ file, className }: { file: File; className: string }) {
  const url = useObjectURL(file);
  return <span className={className}>{url ? <img src={url} alt="" /> : null}</span>;
}

function LocalPreviewCard({ file, index }: { file: File; index: number }) {
  const url = useObjectURL(file);
  return (
    <article className="preview-card">
      <div className="preview-image-box">{url ? <img src={url} alt={file.name} /> : null}</div>
      <span>{index % 2 === 0 ? "原图" : "待生成"}</span>
    </article>
  );
}

function TranslatedPreviewCard({ item }: { item: JobResult }) {
  return (
    <article className="preview-card">
      <div className="preview-image-box">
        <img src={apiURL(item.file_url)} alt={item.output_filename || item.source_filename || "翻译结果"} loading="lazy" />
      </div>
      <span>译图</span>
    </article>
  );
}

function DemoPreviewCard({ kind, label }: { kind: string; label: string }) {
  return (
    <article className="preview-card">
      <div className={`preview-image-box demo-preview ${kind}`} aria-hidden="true" />
      <span>{label}</span>
    </article>
  );
}

function StatusBadge({
  status,
  recognitionMode,
  manualRegionCount,
}: {
  status: QueueStatus;
  recognitionMode?: RecognitionMode;
  manualRegionCount: number;
}) {
  if (status === "queued" && recognitionMode) {
    return <span className={`mode-badge ${recognitionMode}`}>{queueModeBadgeText(recognitionMode, manualRegionCount)}</span>;
  }
  return (
    <span className={`status-badge ${status}`}>
      {STATUS_LABELS[status]}
      <span aria-hidden="true">{status === "completed" ? "✓" : status === "failed" ? "!" : status === "canceled" ? "−" : status === "processing" ? "◌" : "○"}</span>
    </span>
  );
}

function TaskModeBadge({ row }: { row: QueueRow }) {
  const mode = row.recognitionMode || "auto";
  return <span className={`task-mode-badge ${mode}`}>{modeBadgeText(mode, row.manualRegionCount || 0)}</span>;
}

function modeBadgeText(mode: RecognitionMode, manualRegionCount: number) {
  if (mode === "manual") {
    return `手动框选 ${manualRegionCount} 区域`;
  }
  return "自动识别";
}

function queueModeBadgeText(mode: RecognitionMode, manualRegionCount: number) {
  if (mode === "manual") {
    return `手动 ${manualRegionCount}`;
  }
  return "自动识别";
}

function taskStateText(row: QueueRow) {
  if (row.status === "processing") {
    return `处理中 ${row.progress}%`;
  }
  if (row.status === "queued") {
    return "排队";
  }
  if (row.status === "canceled") {
    return "已取消";
  }
  return STATUS_LABELS[row.status];
}

function buildQueueRows(files: File[], job: TranslationJob | null, modesByKey: FileModeMap = {}, regionsByKey: RegionMap = {}): QueueRow[] {
  if (job?.items?.length) {
    return files.map((file, index) => {
      const item = job.items[index];
      const itemStatus = normalizeQueueStatus(item?.status || "queued");
      const key = fileKey(file);
      const recognitionMode = normalizeRecognitionModeValue(item?.recognition_mode || modesByKey[key] || "auto");
      const manualRegionCount = recognitionMode === "manual" ? item?.manual_regions?.length || regionsByKey[key]?.length || 0 : 0;
      const itemProgress =
        itemStatus === "completed"
          ? 100
          : itemStatus === "processing"
            ? Math.max(8, Math.min(95, Math.round(Number(job.progress || 0))))
            : 0;
      return {
        id: fileKey(file),
        index: index + 1,
        name: item?.source_filename || file.name,
        sizeLabel: formatBytes(file.size),
        status: itemStatus,
        progress: itemProgress,
        file,
        recognitionMode,
        manualRegionCount,
      };
    });
  }

  const completedNames = new Set(job?.results?.map((item) => item.source_filename).filter(Boolean));
  const completedCount = Math.max(0, Number(job?.completed || 0));

  return files.map((file, index) => {
    let status: QueueStatus = "queued";
    let itemProgress = 0;

    if (completedNames.has(file.name) || (job?.status === "completed" && index < completedCount)) {
      status = "completed";
      itemProgress = 100;
    } else if (job?.status === "failed" || job?.status === "partial") {
      status = "failed";
    } else if (job?.status === "processing" && index === completedCount) {
      status = "processing";
      itemProgress = Math.max(8, Math.min(95, Math.round(Number(job.progress || 0))));
    } else if (job?.status === "queued") {
      status = "queued";
    }

    return {
      id: fileKey(file),
      index: index + 1,
      name: file.name,
      sizeLabel: formatBytes(file.size),
      status,
      progress: itemProgress,
      file,
      recognitionMode: normalizeRecognitionModeValue(modesByKey[fileKey(file)] || "auto"),
      manualRegionCount: (modesByKey[fileKey(file)] || "auto") === "manual" ? regionsByKey[fileKey(file)]?.length || 0 : 0,
    };
  });
}

function normalizeQueueStatus(status: string): QueueStatus {
  if (status === "completed" || status === "processing" || status === "failed" || status === "canceled") {
    return status;
  }
  return "queued";
}

function normalizeRecognitionModeValue(value: string): RecognitionMode {
  return value === "manual" ? "manual" : "auto";
}

function summarizeFileModes(files: File[], modesByKey: FileModeMap): JobRecognitionMode {
  if (!files.length) {
    return "auto";
  }
  const firstMode = modesByKey[fileKey(files[0])] || "auto";
  return files.some((file) => (modesByKey[fileKey(file)] || "auto") !== firstMode) ? "mixed" : firstMode;
}

function renderJobState(
  job: TranslationJob,
  setWorkflowState: (value: string) => void,
  setStatusText: (value: string) => void,
  setProgress: (value: number) => void,
) {
  const nextProgress = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const statusLabel = STATUS_LABELS[job.status] || job.status || "待处理";
  setWorkflowState(job.status);
  setProgress(nextProgress);
  setStatusText(
    job.status === "failed"
      ? `处理失败：${job.error || "未知错误"}`
      : job.status === "canceled"
        ? "任务已取消。"
      : job.status === "partial"
        ? `部分完成：${job.completed}/${job.total} 张成功，失败项可重跑或下载已生成结果。`
      : `${statusLabel} · ${job.completed}/${job.total} 张 · ${Math.round(nextProgress)}%`,
  );
}

function useObjectURL(file: File | null) {
  const [url, setURL] = useState("");

  useEffect(() => {
    if (!file) {
      setURL("");
      return;
    }
    const nextURL = URL.createObjectURL(file);
    setURL(nextURL);
    return () => URL.revokeObjectURL(nextURL);
  }, [file]);

  return url;
}

function avatarLetter(user: AdminUser) {
  return (user.display_name || user.username || "D").slice(0, 1).toUpperCase();
}

function regionFromPoints(start: { x: number; y: number }, end: { x: number; y: number }): ManualRegion {
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  return {
    x: left,
    y: top,
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

function resizeRegionFromHandle(region: ManualRegion, dx: number, dy: number, handle: ResizeHandle): ManualRegion {
  const minSize = 0.01;
  let left = region.x;
  let top = region.y;
  let right = region.x + region.width;
  let bottom = region.y + region.height;

  if (handle.includes("w")) {
    left = clamp(region.x + dx, 0, right - minSize);
  }
  if (handle.includes("e")) {
    right = clamp(region.x + region.width + dx, left + minSize, 1);
  }
  if (handle.includes("n")) {
    top = clamp(region.y + dy, 0, bottom - minSize);
  }
  if (handle.includes("s")) {
    bottom = clamp(region.y + region.height + dy, top + minSize, 1);
  }

  return roundRegion({
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
  });
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
  return Math.round(clamp(value, 0, 1) * 10000) / 10000;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
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

function GearIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none">
      <path
        d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 1.55V21a2 2 0 0 1-4 0v-.08A1.7 1.7 0 0 0 9 19.38a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 0 1 0-4h.08A1.7 1.7 0 0 0 4.62 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 0 1 4 0v.08A1.7 1.7 0 0 0 15 4.62a1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.19.6.78 1 1.55 1H21a2 2 0 0 1 0 4h-.08A1.7 1.7 0 0 0 19.4 15Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none">
      <rect x="8" y="8" width="11" height="11" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none">
      <path d="M3 6h18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M8 6V4h8v2m-9 4 1 10h8l1-10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none">
      <path d="M12 3v12m0 0 5-5m-5 5-5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 20h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none">
      <path d="M20 12a8 8 0 0 1-13.66 5.66M4 12A8 8 0 0 1 17.66 6.34" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M7 18H4v3M17 6h3V3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function InfoIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
      <path d="M12 11v5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <path d="M12 8h.01" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none">
      <rect x="5" y="10" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
