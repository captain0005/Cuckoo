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

export type FolderExportResult = {
  directory: string;
  exported_count: number;
  files: string[];
};

export type AdminUser = {
  id: string;
  username: string;
  display_name: string;
  email: string;
  role: "super_admin" | "admin" | "user" | string;
  status: "active" | "disabled" | string;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AdminAPIKey = {
  id: string;
  user_id: string;
  username: string;
  provider: string;
  key_name: string;
  masked_key: string;
  key_fingerprint: string;
  status: string;
  total_requests: number;
  total_characters: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AdminUserPayload = {
  username: string;
  display_name: string;
  email: string;
  role: string;
  status: string;
  password?: string;
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

export async function exportJobToFolder(jobID: string, directory: string, overwrite = false) {
  const response = await fetch(apiURL(`/api/jobs/${jobID}/export-folder`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory, overwrite }),
  });
  return parseResponse<FolderExportResult>(response);
}

export async function adminLogin(username: string, password: string) {
  const response = await fetch(apiURL("/api/admin/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return parseResponse<{ token: string; user: AdminUser }>(response);
}

export async function fetchAdminUsers(token: string) {
  const response = await fetch(apiURL("/api/admin/users"), {
    headers: adminHeaders(token),
    cache: "no-store",
  });
  return parseResponse<{ users: AdminUser[] }>(response);
}

export async function createAdminUser(token: string, payload: AdminUserPayload) {
  const response = await fetch(apiURL("/api/admin/users"), {
    method: "POST",
    headers: adminHeaders(token),
    body: JSON.stringify(payload),
  });
  return parseResponse<{ user: AdminUser }>(response);
}

export async function updateAdminUser(token: string, userID: string, payload: AdminUserPayload) {
  const response = await fetch(apiURL(`/api/admin/users/${userID}`), {
    method: "PUT",
    headers: adminHeaders(token),
    body: JSON.stringify(payload),
  });
  return parseResponse<{ user: AdminUser }>(response);
}

export async function deleteAdminUser(token: string, userID: string) {
  const response = await fetch(apiURL(`/api/admin/users/${userID}`), {
    method: "DELETE",
    headers: adminHeaders(token),
  });
  if (response.status === 204) {
    return;
  }
  await parseResponse(response);
}

export async function fetchAdminAPIKeys(token: string, userID = "") {
  const query = userID ? `?user_id=${encodeURIComponent(userID)}` : "";
  const response = await fetch(apiURL(`/api/admin/api-keys${query}`), {
    headers: adminHeaders(token),
    cache: "no-store",
  });
  return parseResponse<{ api_keys: AdminAPIKey[] }>(response);
}

function adminHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload.detail === "string" ? payload.detail : "请求失败";
    throw new Error(message);
  }
  return payload as T;
}
