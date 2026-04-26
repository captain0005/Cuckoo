export type TranslationEntry = {
  source_text: string;
  translated_text: string;
  confidence: number;
  box: Record<string, number>;
};

export type JobResult = {
  source_filename: string;
  output_filename: string;
  file_url: string;
  regions_detected: number;
  regions_replaced: number;
  entries: TranslationEntry[];
  warnings: string[];
};

export type TranslationJob = {
  job_id: string;
  status: "queued" | "processing" | "completed" | "failed" | string;
  progress: number;
  completed: number;
  total: number;
  source_language: string;
  target_language: string;
  error: string;
  created_at: string;
  updated_at: string;
  download_url: string | null;
  results: JobResult[];
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8080";

export function apiURL(path: string) {
  if (path.startsWith("http")) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function createJob(files: File[], sourceLanguage: string, targetLanguage: string) {
  const payload = new FormData();
  files.forEach((file) => payload.append("files", file));
  payload.append("source_language", sourceLanguage);
  payload.append("target_language", targetLanguage);

  const response = await fetch(apiURL("/api/jobs"), {
    method: "POST",
    body: payload,
  });
  return parseResponse<TranslationJob>(response);
}

export async function fetchJob(jobID: string) {
  const response = await fetch(apiURL(`/api/jobs/${jobID}`), {
    cache: "no-store",
  });
  return parseResponse<TranslationJob>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload.detail === "string" ? payload.detail : "请求失败";
    throw new Error(message);
  }
  return payload as T;
}
