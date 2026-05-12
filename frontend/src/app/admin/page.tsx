"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  adminLogin,
  createAdminUser,
  deleteAdminUser,
  fetchAdminAPIKeys,
  fetchAdminJobs,
  fetchAdminUsage,
  fetchAdminUsers,
  updateAdminUser,
  type AdminAPIKey,
  type AdminUsage,
  type AdminUser,
  type AdminUserPayload,
  type TranslationJob,
} from "@/lib/api";

const EMPTY_USER: AdminUserPayload = {
  username: "",
  display_name: "",
  email: "",
  role: "user",
  status: "active",
  password: "",
};

const ROLE_LABELS: Record<string, string> = {
  super_admin: "超级管理员",
  admin: "管理员",
  user: "普通用户",
};

const STATUS_LABELS: Record<string, string> = {
  active: "启用",
  disabled: "停用",
  queued: "排队",
  processing: "处理中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
};

export default function AdminPage() {
  const [token, setToken] = useState("");
  const [currentUser, setCurrentUser] = useState<AdminUser | null>(null);
  const [loginName, setLoginName] = useState("superadmin");
  const [password, setPassword] = useState("");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [apiKeys, setAPIKeys] = useState<AdminAPIKey[]>([]);
  const [usage, setUsage] = useState<AdminUsage[]>([]);
  const [jobs, setJobs] = useState<TranslationJob[]>([]);
  const [selectedUserID, setSelectedUserID] = useState("");
  const [editingID, setEditingID] = useState<string | null>(null);
  const [form, setForm] = useState<AdminUserPayload>(EMPTY_USER);
  const [message, setMessage] = useState("请登录后台。");
  const [isBusy, setIsBusy] = useState(false);

  const stats = useMemo(
    () => ({
      users: users.length,
      active: users.filter((item) => item.status === "active").length,
      jobs: usage.reduce((sum, item) => sum + Number(item.jobs || 0), 0),
      images: usage.reduce((sum, item) => sum + Number(item.images || 0), 0),
      characters: usage.reduce((sum, item) => sum + Number(item.source_characters || 0), 0),
    }),
    [users, usage],
  );

  const usageByUser = useMemo(() => new Map(usage.map((item) => [item.user_id, item])), [usage]);

  useEffect(() => {
    const savedToken = window.localStorage.getItem("cuckoo_admin_token") || "";
    const savedUser = window.localStorage.getItem("cuckoo_admin_user");
    if (!savedToken || !savedUser) {
      return;
    }
    try {
      setToken(savedToken);
      setCurrentUser(JSON.parse(savedUser) as AdminUser);
      void loadAdminData(savedToken);
    } catch {
      window.localStorage.removeItem("cuckoo_admin_token");
      window.localStorage.removeItem("cuckoo_admin_user");
      setMessage("登录信息已失效，请重新登录。");
    }
  }, []);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsBusy(true);
    setMessage("正在登录...");
    try {
      const payload = await adminLogin(loginName, password);
      setToken(payload.token);
      setCurrentUser(payload.user);
      window.localStorage.setItem("cuckoo_admin_token", payload.token);
      window.localStorage.setItem("cuckoo_admin_user", JSON.stringify(payload.user));
      await loadAdminData(payload.token);
      setMessage(`已登录：${payload.user.display_name || payload.user.username}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "登录失败");
    } finally {
      setIsBusy(false);
    }
  }

  async function loadAdminData(nextToken = token, userID = selectedUserID) {
    if (!nextToken) {
      return;
    }
    const [userPayload, keyPayload, usagePayload, jobsPayload] = await Promise.all([
      fetchAdminUsers(nextToken),
      fetchAdminAPIKeys(nextToken, userID),
      fetchAdminUsage(nextToken),
      fetchAdminJobs(nextToken, userID),
    ]);
    setUsers(userPayload.users);
    setAPIKeys(keyPayload.api_keys);
    setUsage(usagePayload.usage);
    setJobs(jobsPayload.jobs);
  }

  async function refreshUserFilter(userID: string) {
    setSelectedUserID(userID);
    if (!token) {
      return;
    }
    try {
      const [keyPayload, jobsPayload] = await Promise.all([fetchAdminAPIKeys(token, userID), fetchAdminJobs(token, userID)]);
      setAPIKeys(keyPayload.api_keys);
      setJobs(jobsPayload.jobs);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取用户数据失败");
    }
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      return;
    }
    setIsBusy(true);
    setMessage(editingID ? "正在更新用户..." : "正在创建用户...");
    try {
      const payload = normalizePayload(form, Boolean(editingID));
      if (editingID) {
        await updateAdminUser(token, editingID, payload);
      } else {
        await createAdminUser(token, payload);
      }
      setEditingID(null);
      setForm(EMPTY_USER);
      await loadAdminData(token);
      setMessage(editingID ? "用户已更新。" : "用户已创建。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存用户失败");
    } finally {
      setIsBusy(false);
    }
  }

  function editUser(user: AdminUser) {
    setEditingID(user.id);
    setForm({
      username: user.username,
      display_name: user.display_name,
      email: user.email,
      role: user.role,
      status: user.status,
      password: "",
    });
  }

  async function removeUser(user: AdminUser) {
    if (!token) {
      return;
    }
    const ok = window.confirm(`确定删除用户 ${user.username} 吗？`);
    if (!ok) {
      return;
    }
    setIsBusy(true);
    setMessage("正在删除用户...");
    try {
      await deleteAdminUser(token, user.id);
      await loadAdminData(token);
      setMessage("用户已删除。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "删除用户失败");
    } finally {
      setIsBusy(false);
    }
  }

  function logout() {
    window.localStorage.removeItem("cuckoo_admin_token");
    window.localStorage.removeItem("cuckoo_admin_user");
    setToken("");
    setCurrentUser(null);
    setUsers([]);
    setAPIKeys([]);
    setUsage([]);
    setJobs([]);
    setMessage("已退出后台。");
  }

  if (!token) {
    return (
      <main className="admin-shell">
        <section className="admin-login">
          <div>
            <p className="eyebrow">Admin</p>
            <h1>Cuckoo 管理后台</h1>
            <p className="admin-muted">用户、角色、API Key 和用量数据管理。</p>
          </div>
          <form className="admin-form" onSubmit={handleLogin}>
            <label>
              账号
              <input value={loginName} onChange={(event) => setLoginName(event.target.value)} autoComplete="username" />
            </label>
            <label>
              密码
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
            </label>
            <button type="submit" disabled={isBusy}>
              登录后台
            </button>
            <p className="admin-message">{message}</p>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="admin-shell">
      <header className="admin-topbar">
        <div>
          <p className="eyebrow">Admin</p>
          <h1>Cuckoo 管理后台</h1>
        </div>
        <div className="admin-session">
          <span>{currentUser?.display_name || currentUser?.username}</span>
          <button type="button" onClick={logout}>
            退出
          </button>
        </div>
      </header>

      <section className="admin-stats">
        <StatCard label="用户总数" value={stats.users} />
        <StatCard label="启用用户" value={stats.active} />
        <StatCard label="任务总数" value={stats.jobs} />
        <StatCard label="图片总数" value={stats.images} />
        <StatCard label="源文字符" value={stats.characters} />
      </section>

      <section className="admin-grid">
        <section className="admin-panel">
          <div className="admin-panel-head">
            <div>
              <p className="eyebrow">Users</p>
              <h2>用户列表</h2>
            </div>
            <button type="button" onClick={() => void loadAdminData()} disabled={isBusy}>
              刷新
            </button>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>账号</th>
                  <th>名称</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>任务</th>
                  <th>图片</th>
                  <th>字符</th>
                  <th>最近任务</th>
                  <th>最近登录</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const itemUsage = usageByUser.get(user.id);
                  return (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.username}</strong>
                        <span>{user.email}</span>
                      </td>
                      <td>{user.display_name}</td>
                      <td>{ROLE_LABELS[user.role] || user.role}</td>
                      <td>
                        <span className={`admin-pill ${user.status}`}>{STATUS_LABELS[user.status] || user.status}</span>
                      </td>
                      <td>{itemUsage?.jobs || 0}</td>
                      <td>{itemUsage?.images || 0}</td>
                      <td>{itemUsage?.source_characters || 0}</td>
                      <td>{formatTime(itemUsage?.last_job_at || null)}</td>
                      <td>{formatTime(user.last_login_at)}</td>
                      <td>
                        <div className="admin-actions">
                          <button type="button" onClick={() => editUser(user)}>
                            编辑
                          </button>
                          <button type="button" className="danger-button" onClick={() => void removeUser(user)}>
                            删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="admin-panel">
          <div className="admin-panel-head">
            <div>
              <p className="eyebrow">{editingID ? "Edit" : "Create"}</p>
              <h2>{editingID ? "编辑用户" : "新增用户"}</h2>
            </div>
            {editingID ? (
              <button
                type="button"
                onClick={() => {
                  setEditingID(null);
                  setForm(EMPTY_USER);
                }}
              >
                取消
              </button>
            ) : null}
          </div>
          <form className="admin-form dense" onSubmit={submitUser}>
            <label>
              账号
              <input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} />
            </label>
            <label>
              显示名
              <input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} />
            </label>
            <label>
              邮箱
              <input value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
            </label>
            <div className="admin-two-cols">
              <label>
                角色
                <select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
                  <option value="super_admin">超级管理员</option>
                  <option value="admin">管理员</option>
                  <option value="user">普通用户</option>
                </select>
              </label>
              <label>
                状态
                <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                  <option value="active">启用</option>
                  <option value="disabled">停用</option>
                </select>
              </label>
            </div>
            <label>
              密码
              <input
                type="password"
                value={form.password || ""}
                placeholder={editingID ? "留空则不修改" : "至少 8 位"}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
              />
            </label>
            <button type="submit" disabled={isBusy}>
              {editingID ? "保存修改" : "创建用户"}
            </button>
            <p className="admin-message">{message}</p>
          </form>
        </section>
      </section>

      <section className="admin-panel">
        <div className="admin-panel-head">
          <div>
            <p className="eyebrow">Jobs</p>
            <h2>用户任务记录</h2>
          </div>
          <UserFilter users={users} selectedUserID={selectedUserID} onChange={(userID) => void refreshUserFilter(userID)} />
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>任务</th>
                <th>用户</th>
                <th>状态</th>
                <th>图片</th>
                <th>识别/替换</th>
                <th>字符</th>
                <th>语言</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id}>
                  <td>
                    <strong>{job.job_id.slice(0, 8)}</strong>
                    <span>{job.error || "运行正常"}</span>
                  </td>
                  <td>{job.username || job.user_id || "未归属"}</td>
                  <td>{STATUS_LABELS[job.status] || job.status}</td>
                  <td>
                    {job.completed}/{job.total}
                  </td>
                  <td>
                    {job.regions_detected}/{job.regions_replaced}
                  </td>
                  <td>{job.source_characters}</td>
                  <td>
                    {job.source_language} → {job.target_language}
                  </td>
                  <td>{formatTime(job.created_at)}</td>
                </tr>
              ))}
              {!jobs.length ? (
                <tr>
                  <td colSpan={8}>暂无任务数据</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-panel">
        <div className="admin-panel-head">
          <div>
            <p className="eyebrow">API Keys</p>
            <h2>用户 API Key 数据</h2>
          </div>
          <UserFilter users={users} selectedUserID={selectedUserID} onChange={(userID) => void refreshUserFilter(userID)} />
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>用户</th>
                <th>服务商</th>
                <th>Key</th>
                <th>状态</th>
                <th>请求</th>
                <th>字符</th>
                <th>最近使用</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((item) => (
                <tr key={item.id}>
                  <td>{item.username || item.user_id}</td>
                  <td>{item.provider}</td>
                  <td>
                    <strong>{item.key_name}</strong>
                    <span>
                      {item.masked_key} · {item.key_fingerprint}
                    </span>
                  </td>
                  <td>
                    <span className={`admin-pill ${item.status}`}>{STATUS_LABELS[item.status] || item.status}</span>
                  </td>
                  <td>{item.total_requests}</td>
                  <td>{item.total_characters}</td>
                  <td>{formatTime(item.last_used_at)}</td>
                </tr>
              ))}
              {!apiKeys.length ? (
                <tr>
                  <td colSpan={7}>暂无 API Key 数据</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function UserFilter({
  users,
  selectedUserID,
  onChange,
}: {
  users: AdminUser[];
  selectedUserID: string;
  onChange: (userID: string) => void;
}) {
  return (
    <label className="admin-filter">
      用户
      <select value={selectedUserID} onChange={(event) => onChange(event.target.value)}>
        <option value="">全部用户</option>
        {users.map((user) => (
          <option key={user.id} value={user.id}>
            {user.username}
          </option>
        ))}
      </select>
    </label>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <article className="admin-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function normalizePayload(payload: AdminUserPayload, editing: boolean) {
  return {
    ...payload,
    password: editing && !payload.password ? undefined : payload.password,
  };
}

function formatTime(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}
