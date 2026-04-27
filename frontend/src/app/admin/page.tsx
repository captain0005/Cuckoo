"use client";

import { useEffect, useMemo, useState } from "react";
import {
  adminLogin,
  createAdminUser,
  deleteAdminUser,
  fetchAdminAPIKeys,
  fetchAdminUsers,
  updateAdminUser,
  type AdminAPIKey,
  type AdminUser,
  type AdminUserPayload,
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
};

export default function AdminPage() {
  const [token, setToken] = useState("");
  const [currentUser, setCurrentUser] = useState<AdminUser | null>(null);
  const [loginName, setLoginName] = useState("superadmin");
  const [password, setPassword] = useState("");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [apiKeys, setAPIKeys] = useState<AdminAPIKey[]>([]);
  const [selectedUserID, setSelectedUserID] = useState("");
  const [editingID, setEditingID] = useState<string | null>(null);
  const [form, setForm] = useState<AdminUserPayload>(EMPTY_USER);
  const [message, setMessage] = useState("请登录后台。");
  const [isBusy, setIsBusy] = useState(false);

  const stats = useMemo(() => {
    return {
      users: users.length,
      active: users.filter((item) => item.status === "active").length,
      keys: apiKeys.length,
      requests: apiKeys.reduce((sum, item) => sum + Number(item.total_requests || 0), 0),
    };
  }, [users, apiKeys]);

  useEffect(() => {
    const savedToken = window.localStorage.getItem("cuckoo_admin_token") || "";
    const savedUser = window.localStorage.getItem("cuckoo_admin_user");
    if (!savedToken || !savedUser) {
      return;
    }
    setToken(savedToken);
    setCurrentUser(JSON.parse(savedUser) as AdminUser);
    void loadAdminData(savedToken);
  }, []);

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
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
    const [userPayload, keyPayload] = await Promise.all([
      fetchAdminUsers(nextToken),
      fetchAdminAPIKeys(nextToken, userID),
    ]);
    setUsers(userPayload.users);
    setAPIKeys(keyPayload.api_keys);
  }

  async function refreshAPIKeys(userID: string) {
    setSelectedUserID(userID);
    if (!token) {
      return;
    }
    try {
      const payload = await fetchAdminAPIKeys(token, userID);
      setAPIKeys(payload.api_keys);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取 API Key 失败");
    }
  }

  async function submitUser(event: React.FormEvent<HTMLFormElement>) {
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
    const ok = window.confirm(`删除用户 ${user.username}？`);
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
    setMessage("已退出后台。");
  }

  if (!token) {
    return (
      <main className="admin-shell">
        <section className="admin-login">
          <div>
            <p className="eyebrow">Admin</p>
            <h1>Cuckoo 管理后台</h1>
            <p className="admin-muted">用户、角色和 API Key 用量管理。</p>
          </div>
          <form className="admin-form" onSubmit={handleLogin}>
            <label>
              账号
              <input value={loginName} onChange={(event) => setLoginName(event.target.value)} />
            </label>
            <label>
              密码
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
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
        <StatCard label="API Key" value={stats.keys} />
        <StatCard label="调用次数" value={stats.requests} />
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
                  <th>最近登录</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
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
                ))}
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
              <button type="button" onClick={() => {
                setEditingID(null);
                setForm(EMPTY_USER);
              }}>
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
            <p className="eyebrow">API Keys</p>
            <h2>用户 API Key 数据</h2>
          </div>
          <label className="admin-filter">
            用户
            <select value={selectedUserID} onChange={(event) => void refreshAPIKeys(event.target.value)}>
              <option value="">全部用户</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.username}
                </option>
              ))}
            </select>
          </label>
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
                    <span>{item.masked_key} · {item.key_fingerprint}</span>
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
