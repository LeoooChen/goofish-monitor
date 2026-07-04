import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  Bot,
  BookOpen,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  ExternalLink,
  Filter,
  LogOut,
  Pencil,
  Play,
  Plus,
  QrCode,
  RefreshCcw,
  Save,
  Search,
  Settings,
  SlidersHorizontal,
  Square,
  Terminal,
  Wifi,
  Trash2,
  UserRound,
  X
} from "lucide-react";
import "./styles.css";

type AccountStatus = "pending" | "login_waiting" | "logged_in" | "failed";
type MonitorInterval = "none" | "5m" | "10m" | "30m" | "1h";
type TaskStatus = "idle" | "running" | "failed";
type ResultFilter = "all" | "recommended" | "not_recommended" | "unanalyzed";
type AppTab = "accounts" | "tasks" | "knowledge" | "results" | "settings" | "logs";

type Account = {
  id: string;
  name: string;
  status: AccountStatus;
  storage_state_path: string | null;
  created_at: string;
  last_login_at: string | null;
  last_error: string | null;
};

type MonitorTask = {
  id: string;
  title: string;
  keyword: string;
  description: string;
  knowledge_base_id: string | null;
  pages: number;
  analyze_images: boolean;
  browser_headless: boolean | null;
  interval: MonitorInterval;
  enabled: boolean;
  status: TaskStatus;
  created_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
};

type TaskDraft = {
  title: string;
  keyword: string;
  description: string;
  knowledge_base_id: string | null;
  pages: number;
  analyze_images: boolean;
  browser_headless: boolean | null;
  interval: MonitorInterval;
  enabled: boolean;
};

type AppSettings = {
  ai: {
    api_url: string | null;
    api_key: string;
    model_name: string;
    request_interval_seconds: number | null;
  };
  browser: {
    headless: boolean;
    login_timeout_seconds: number;
    min_page_delay_seconds: number;
    max_page_delay_seconds: number;
    stop_on_verification: boolean;
    user_data_dir: string;
  };
  notify: {
    enabled: boolean;
    threshold_percent: number;
    webhook_url: string;
    mention_mobile: string | null;
  };
};

type KnowledgeBase = {
  id: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
};

type KnowledgeBaseDraft = {
  title: string;
  content: string;
};

type AiTestResponse = {
  ok: boolean;
  api_url: string | null;
  request_url: string | null;
  model_name: string;
  api_key_configured: boolean;
  latency_ms: number | null;
  response_preview: string | null;
  error: string | null;
};

type ProductResult = {
  id: string;
  task_id: string;
  task_title: string;
  keyword: string;
  product: {
    title: string;
    price: string | null;
    location: string | null;
    description: string | null;
    url: string;
    image_urls: string[];
  };
  decision: {
    is_target_product: boolean;
    worth_percent: number;
    reason: string;
  } | null;
  recommended: boolean;
  fetched_at: string;
};

type RuntimeLogEntry = {
  id: number;
  timestamp: string;
  level: "debug" | "info" | "warning" | "error";
  source: string;
  message: string;
};

type AuthStatus = {
  enabled: boolean;
  authenticated: boolean;
};

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const defaultSettings: AppSettings = {
  ai: {
    api_url: null,
    api_key: "",
    model_name: "gpt-4o-mini",
    request_interval_seconds: 3
  },
  browser: {
    headless: false,
    login_timeout_seconds: 900,
    min_page_delay_seconds: 6,
    max_page_delay_seconds: 14,
    stop_on_verification: true,
    user_data_dir: "data/browser-profile"
  },
  notify: {
    enabled: false,
    threshold_percent: 80,
    webhook_url: "",
    mention_mobile: null
  }
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const rawMessage = await response.text();
    throw new ApiError(extractResponseError(rawMessage) || response.statusText, response.status);
  }
  return response.json() as Promise<T>;
}

function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [tab, setTab] = useState<AppTab>("accounts");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [tasks, setTasks] = useState<MonitorTask[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [results, setResults] = useState<ProductResult[]>([]);
  const [logs, setLogs] = useState<RuntimeLogEntry[]>([]);
  const [settings, setSettings] = useState<AppSettings>(defaultSettings);
  const [filter, setFilter] = useState<ResultFilter>("all");
  const [notice, setNotice] = useState("");

  function handleDataError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      setAuthStatus({ enabled: true, authenticated: false });
      return;
    }
    setNotice(formatErrorMessage(error));
  }

  async function refreshAuthStatus() {
    setAuthStatus(await api<AuthStatus>("/api/auth/status"));
  }

  async function refreshLiveData() {
    const [nextAccounts, nextTasks, nextKnowledgeBases, nextResults] = await Promise.all([
      api<Account[]>("/api/accounts"),
      api<MonitorTask[]>("/api/tasks"),
      api<KnowledgeBase[]>("/api/knowledge-bases"),
      api<ProductResult[]>(`/api/results?filter=${filter}`)
    ]);
    setAccounts(nextAccounts);
    setTasks(nextTasks);
    setKnowledgeBases(nextKnowledgeBases);
    setResults(nextResults);
  }

  async function refreshAll() {
    const [nextAccounts, nextTasks, nextKnowledgeBases, nextSettings, nextResults] = await Promise.all([
      api<Account[]>("/api/accounts"),
      api<MonitorTask[]>("/api/tasks"),
      api<KnowledgeBase[]>("/api/knowledge-bases"),
      api<AppSettings>("/api/settings"),
      api<ProductResult[]>(`/api/results?filter=${filter}`)
    ]);
    setAccounts(nextAccounts);
    setTasks(nextTasks);
    setKnowledgeBases(nextKnowledgeBases);
    setSettings(nextSettings);
    setResults(nextResults);
  }

  useEffect(() => {
    void refreshAuthStatus().catch((error: unknown) => setNotice(formatErrorMessage(error)));
  }, []);

  useEffect(() => {
    if (!authStatus?.authenticated) return undefined;
    void refreshAll().catch(handleDataError);
    const timer = window.setInterval(() => {
      void refreshLiveData().catch(handleDataError);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [authStatus?.authenticated, filter]);

  async function refreshLogs() {
    setLogs(await api<RuntimeLogEntry[]>("/api/logs?limit=300"));
  }

  useEffect(() => {
    if (!authStatus?.authenticated) return undefined;
    void refreshLogs().catch(handleDataError);
    const timer = window.setInterval(() => {
      void refreshLogs().catch(handleDataError);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [authStatus?.authenticated]);

  const stats = useMemo(() => {
    const recommended = results.filter((item) => item.recommended).length;
    const running = tasks.filter((item) => item.status === "running").length;
    const loggedIn = accounts.filter((item) => item.status === "logged_in").length;
    return { recommended, running, loggedIn };
  }, [accounts, results, tasks]);

  async function logout() {
    await api<{ ok: boolean }>("/api/auth/logout", { method: "POST", body: "{}" });
    setAuthStatus({ enabled: true, authenticated: false });
    setNotice("");
  }

  if (authStatus === null) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <Search size={24} />
          <h1>闲鱼监控</h1>
          <p>正在检查登录状态...</p>
        </section>
      </main>
    );
  }

  if (!authStatus.authenticated) {
    return (
      <LoginView
        onAuthenticated={() => {
          setAuthStatus({ ...authStatus, authenticated: true });
          setNotice("");
        }}
      />
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Search size={22} />
          <span>闲鱼监控</span>
        </div>
        <nav>
          <button className={tab === "accounts" ? "active" : ""} onClick={() => setTab("accounts")}>
            <UserRound size={18} /> 账号
          </button>
          <button className={tab === "tasks" ? "active" : ""} onClick={() => setTab("tasks")}>
            <SlidersHorizontal size={18} /> 任务
          </button>
          <button className={tab === "knowledge" ? "active" : ""} onClick={() => setTab("knowledge")}>
            <BookOpen size={18} /> 知识库
          </button>
          <button className={tab === "results" ? "active" : ""} onClick={() => setTab("results")}>
            <Filter size={18} /> 结果
          </button>
          <button className={tab === "logs" ? "active" : ""} onClick={() => setTab("logs")}>
            <Terminal size={18} /> 日志
          </button>
          <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
            <Settings size={18} /> 设置
          </button>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">AI Goofish Monitor</p>
            <h1>{pageTitle(tab)}</h1>
          </div>
          <div className="metrics">
            <span>已登录 {stats.loggedIn}</span>
            <span>运行中 {stats.running}</span>
            <span>推荐 {stats.recommended}</span>
          </div>
          <button className="icon-button" title="刷新" onClick={() => void refreshAll()}>
            <RefreshCcw size={18} />
          </button>
          {authStatus.enabled ? (
            <button className="icon-button ghost" title="退出登录" onClick={() => void logout()}>
              <LogOut size={18} />
            </button>
          ) : null}
        </header>

        {notice ? <div className="notice">{notice}</div> : null}

        {tab === "accounts" && (
          <AccountsView
            accounts={accounts}
            onNotice={setNotice}
            onRefresh={() => void refreshLiveData()}
          />
        )}
        {tab === "tasks" && (
          <TasksView
            tasks={tasks}
            knowledgeBases={knowledgeBases}
            onNotice={setNotice}
            onRefresh={() => void refreshLiveData()}
          />
        )}
        {tab === "knowledge" && (
          <KnowledgeBasesView
            knowledgeBases={knowledgeBases}
            onNotice={setNotice}
            onRefresh={() => void refreshLiveData()}
          />
        )}
        {tab === "results" && (
          <ResultsView
            tasks={tasks}
            results={results}
            filter={filter}
            onFilter={setFilter}
            onRefresh={() => void refreshLiveData()}
          />
        )}
        {tab === "logs" && <RunLogsView logs={logs} onRefresh={() => void refreshLogs()} />}
        {tab === "settings" && (
          <SettingsView
            settings={settings}
            setSettings={setSettings}
            onNotice={setNotice}
            onRefresh={() => void refreshAll()}
          />
        )}
      </section>
    </main>
  );
}

function LoginView({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage("");
    try {
      await api<{ ok: boolean }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password })
      });
      setPassword("");
      onAuthenticated();
    } catch (error) {
      setMessage(formatErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={(event) => void submit(event)}>
        <div className="auth-mark">
          <Search size={24} />
        </div>
        <div>
          <p className="eyebrow">AI Goofish Monitor</p>
          <h1>闲鱼监控</h1>
        </div>
        <label>
          访问密码
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="输入服务器访问密码"
            autoFocus
            required
          />
        </label>
        {message ? <div className="notice">{message}</div> : null}
        <button type="submit" disabled={submitting}>
          {submitting ? "登录中" : "登录"}
        </button>
      </form>
    </main>
  );
}

function RunLogsView({
  logs,
  onRefresh
}: {
  logs: RuntimeLogEntry[];
  onRefresh: () => void;
}) {
  async function clearLogs() {
    await api("/api/logs", { method: "DELETE" });
    onRefresh();
  }

  return (
    <section className="panel">
      <div className="section-bar">
        <div>
          <h2>运行日志</h2>
          <p>后端任务、搜索、登录和 AI 分析的关键输出。</p>
        </div>
        <button className="ghost danger" type="button" onClick={() => void clearLogs()}>
          <Trash2 size={16} /> 清空日志
        </button>
      </div>
      <div className="log-console">
        {logs.length === 0 ? (
          <div className="log-empty">暂无日志</div>
        ) : (
          logs.map((entry) => (
            <div className={`log-line ${entry.level}`} key={entry.id}>
              <span className="log-time">{formatLogTime(entry.timestamp)}</span>
              <span className="log-level">{entry.level}</span>
              <span className="log-source">{entry.source}</span>
              <span className="log-message">{entry.message}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function AccountsView({
  accounts,
  onNotice,
  onRefresh
}: {
  accounts: Account[];
  onNotice: (message: string) => void;
  onRefresh: () => void;
}) {
  const [name, setName] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [loginAccountId, setLoginAccountId] = useState<string | null>(null);
  const [qrVersion, setQrVersion] = useState(Date.now());
  const [qrAvailable, setQrAvailable] = useState(false);
  const loginAccount = accounts.find((account) => account.id === loginAccountId) ?? null;

  useEffect(() => {
    if (!loginAccountId) return;
    setQrAvailable(false);
    setQrVersion(Date.now());
    const timer = window.setInterval(() => {
      setQrVersion(Date.now());
      onRefresh();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [loginAccountId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    await api<Account>("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ name })
    });
    setName("");
    setModalOpen(false);
    onRefresh();
  }

  async function login(accountId: string) {
    setLoginAccountId(accountId);
    setQrAvailable(false);
    setQrVersion(Date.now());
    await api(`/api/accounts/${accountId}/login`, { method: "POST" });
    onNotice("正在生成扫码登录图片，请在弹窗中扫码。");
    onRefresh();
  }

  async function remove(accountId: string) {
    await api(`/api/accounts/${accountId}`, { method: "DELETE" });
    onRefresh();
  }

  return (
    <section className="panel">
      <div className="section-bar">
        <div>
          <h2>账号管理</h2>
          <p>扫码登录后，登录态会保存到本地 JSON 文件。</p>
        </div>
        <button type="button" onClick={() => setModalOpen(true)}>
          <Plus size={16} /> 新增账号
        </button>
      </div>
      <div className="list-grid">
        {accounts.map((account) => (
          <article className="item-card" key={account.id}>
            <div>
              <h3>{account.name}</h3>
              <StatusBadge status={account.status} />
              {account.last_error ? <p className="error">{account.last_error}</p> : null}
            </div>
            <div className="card-actions">
              <button title="扫码登录" onClick={() => void login(account.id)}>
                <QrCode size={16} /> 登录
              </button>
              <button className="ghost danger" title="删除" onClick={() => void remove(account.id)}>
                <Trash2 size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
      <Modal title="新增账号" open={modalOpen} onClose={() => setModalOpen(false)}>
        <form className="modal-form" onSubmit={(event) => void submit(event)}>
          <label>
            账号名称
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：主账号"
              autoFocus
            />
          </label>
          <div className="modal-actions">
            <button className="ghost" type="button" onClick={() => setModalOpen(false)}>
              取消
            </button>
            <button type="submit">
              <Plus size={16} /> 新增
            </button>
          </div>
        </form>
      </Modal>
      <Modal title="扫码登录" open={loginAccount !== null} onClose={() => setLoginAccountId(null)}>
        <div className="login-qr-panel">
          <div className="login-qr-frame">
            {!qrAvailable ? <span>正在生成登录图片...</span> : null}
            {loginAccount ? (
              <img
                src={`/api/accounts/${loginAccount.id}/login-qrcode?t=${qrVersion}`}
                alt={`${loginAccount.name} 登录二维码`}
                style={{ opacity: qrAvailable ? 1 : 0 }}
                onLoad={() => setQrAvailable(true)}
                onError={() => setQrAvailable(false)}
              />
            ) : null}
          </div>
          <p>请用闲鱼 App 扫码确认。登录成功后状态会自动更新。</p>
          {loginAccount?.last_error ? <p className="error">{loginAccount.last_error}</p> : null}
        </div>
      </Modal>
    </section>
  );
}

function TasksView({
  tasks,
  knowledgeBases,
  onNotice,
  onRefresh
}: {
  tasks: MonitorTask[];
  knowledgeBases: KnowledgeBase[];
  onNotice: (message: string) => void;
  onRefresh: () => void;
}) {
  const emptyDraft = (): TaskDraft => ({
    title: "",
    keyword: "",
    description: "",
    knowledge_base_id: null,
    pages: 1,
    analyze_images: false,
    browser_headless: null,
    interval: "none" as MonitorInterval,
    enabled: true
  });
  const [draft, setDraft] = useState<TaskDraft>(() => emptyDraft());
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const path = editingTaskId ? `/api/tasks/${editingTaskId}` : "/api/tasks";
    await api<MonitorTask>(path, {
      method: editingTaskId ? "PATCH" : "POST",
      body: JSON.stringify(draft)
    });
    setDraft(emptyDraft());
    setEditingTaskId(null);
    setModalOpen(false);
    onRefresh();
  }

  function createTask() {
    setEditingTaskId(null);
    setDraft(emptyDraft());
    setModalOpen(true);
  }

  function edit(task: MonitorTask) {
    setEditingTaskId(task.id);
    setDraft({
      title: task.title,
      keyword: task.keyword,
      description: task.description,
      knowledge_base_id: task.knowledge_base_id,
      pages: task.pages,
      analyze_images: task.analyze_images,
      browser_headless: task.browser_headless,
      interval: task.interval,
      enabled: task.enabled
    });
    setModalOpen(true);
  }

  function cancelEdit() {
    setEditingTaskId(null);
    setDraft(emptyDraft());
    setModalOpen(false);
  }

  async function startTask(taskId: string) {
    await api(`/api/tasks/${taskId}/start`, { method: "POST" });
    onNotice("任务已启动。");
    onRefresh();
  }

  async function stopTask(taskId: string) {
    await api(`/api/tasks/${taskId}/stop`, { method: "POST" });
    onNotice("任务已停止。");
    onRefresh();
  }

  async function remove(taskId: string) {
    await api(`/api/tasks/${taskId}`, { method: "DELETE" });
    onRefresh();
  }

  return (
    <section className="panel">
      <div className="section-bar">
        <div>
          <h2>监控任务</h2>
          <p>设置关键词、AI 判定描述和运行方式。</p>
        </div>
        <button type="button" onClick={createTask}>
          <Plus size={16} /> 新建任务
        </button>
      </div>

      <div className="task-list">
        {tasks.map((task) => (
          <article className="item-card task-card" key={task.id}>
            <div>
              <h3>{task.title}</h3>
              <p>
                {task.keyword} · {task.pages} 页 · {intervalLabel(task.interval)} ·{" "}
                {browserModeLabel(task.browser_headless)} · {taskRunModeLabel(task)}
              </p>
              <p>知识库：{knowledgeBaseTitle(task.knowledge_base_id, knowledgeBases)}</p>
              <p>{task.description}</p>
              {task.last_error ? <p className="error">{task.last_error}</p> : null}
            </div>
            <div className="card-actions">
              <button className="ghost" title="编辑" onClick={() => edit(task)}>
                <Pencil size={16} /> 编辑
              </button>
              {task.status === "running" ? (
                <button
                  className="task-control ghost danger"
                  title="停止"
                  onClick={() => void stopTask(task.id)}
                >
                  <Square size={16} /> 停止
                </button>
              ) : (
                <button className="task-control" title="启动" onClick={() => void startTask(task.id)}>
                  <Play size={16} /> 启动
                </button>
              )}
              <button className="ghost danger icon-only" title="删除" onClick={() => void remove(task.id)}>
                <Trash2 size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
      <TaskModal
        draft={draft}
        editing={editingTaskId !== null}
        knowledgeBases={knowledgeBases}
        open={modalOpen}
        setDraft={setDraft}
        onClose={cancelEdit}
        onSubmit={submit}
      />
    </section>
  );
}

function TaskModal({
  draft,
  editing,
  knowledgeBases,
  open,
  setDraft,
  onClose,
  onSubmit
}: {
  draft: TaskDraft;
  editing: boolean;
  knowledgeBases: KnowledgeBase[];
  open: boolean;
  setDraft: (draft: TaskDraft) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <Modal title={editing ? "编辑任务" : "新建任务"} open={open} onClose={onClose}>
      <form className="modal-form" onSubmit={onSubmit}>
        <label>
          任务标题
          <input
            value={draft.title}
            onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            placeholder="例如：相机镜头监控"
            required
            autoFocus
          />
        </label>
        <label>
          搜索关键词
          <input
            value={draft.keyword}
            onChange={(event) => setDraft({ ...draft, keyword: event.target.value })}
            placeholder="闲鱼搜索栏关键词"
            required
          />
        </label>
        <label>
          产品描述
          <textarea
            value={draft.description}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            placeholder="告诉 AI 你要找的具体产品和成色要求"
            required
          />
        </label>
        <label>
          知识库
          <select
            value={draft.knowledge_base_id ?? ""}
            onChange={(event) =>
              setDraft({ ...draft, knowledge_base_id: event.target.value || null })
            }
          >
            <option value="">不使用知识库</option>
            {knowledgeBases.map((knowledgeBase) => (
              <option value={knowledgeBase.id} key={knowledgeBase.id}>
                {knowledgeBase.title}
              </option>
            ))}
          </select>
        </label>
        <div className="form-row">
          <label>
            页数
            <input
              type="number"
              min={1}
              max={10}
              value={draft.pages}
              onChange={(event) => setDraft({ ...draft, pages: Number(event.target.value) })}
            />
          </label>
          <label>
            频率
            <select
              value={draft.interval}
              onChange={(event) =>
                setDraft({ ...draft, interval: event.target.value as MonitorInterval })
              }
            >
              <option value="none">无</option>
              <option value="5m">每 5min</option>
              <option value="10m">每 10min</option>
              <option value="30m">每 30min</option>
              <option value="1h">每 1h</option>
            </select>
          </label>
          <label>
            浏览器模式
            <select
              value={browserModeValue(draft.browser_headless)}
              onChange={(event) =>
                setDraft({ ...draft, browser_headless: browserHeadlessFromMode(event.target.value) })
              }
            >
              <option value="system">跟随系统设置</option>
              <option value="headed">有界面浏览器</option>
              <option value="headless">无界面浏览器</option>
            </select>
          </label>
        </div>
        <label className="switch">
          <input
            type="checkbox"
            checked={draft.analyze_images}
            onChange={(event) => setDraft({ ...draft, analyze_images: event.target.checked })}
          />
          分析图片
        </label>
        <div className="modal-actions">
          <button className="ghost" type="button" onClick={onClose}>
            取消
          </button>
          <button type="submit">
            {editing ? <Save size={16} /> : <Plus size={16} />}
            {editing ? "保存修改" : "创建任务"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function KnowledgeBasesView({
  knowledgeBases,
  onNotice,
  onRefresh
}: {
  knowledgeBases: KnowledgeBase[];
  onNotice: (message: string) => void;
  onRefresh: () => void;
}) {
  const emptyDraft = (): KnowledgeBaseDraft => ({ title: "", content: "" });
  const [draft, setDraft] = useState<KnowledgeBaseDraft>(() => emptyDraft());
  const [editingKnowledgeBaseId, setEditingKnowledgeBaseId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  function createKnowledgeBase() {
    setEditingKnowledgeBaseId(null);
    setDraft(emptyDraft());
    setModalOpen(true);
  }

  function edit(knowledgeBase: KnowledgeBase) {
    setEditingKnowledgeBaseId(knowledgeBase.id);
    setDraft({
      title: knowledgeBase.title,
      content: knowledgeBase.content
    });
    setModalOpen(true);
  }

  function closeModal() {
    setEditingKnowledgeBaseId(null);
    setDraft(emptyDraft());
    setModalOpen(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const path = editingKnowledgeBaseId
      ? `/api/knowledge-bases/${editingKnowledgeBaseId}`
      : "/api/knowledge-bases";
    setSaving(true);
    try {
      await api<KnowledgeBase>(path, {
        method: editingKnowledgeBaseId ? "PATCH" : "POST",
        body: JSON.stringify(draft)
      });
      closeModal();
      onNotice(editingKnowledgeBaseId ? "知识库已保存。" : "知识库已创建。");
      onRefresh();
    } catch (error) {
      onNotice(`知识库保存失败：${formatErrorMessage(error)}`);
    } finally {
      setSaving(false);
    }
  }

  async function remove(knowledgeBaseId: string) {
    await api(`/api/knowledge-bases/${knowledgeBaseId}`, { method: "DELETE" });
    onNotice("知识库已删除，相关任务已自动解除绑定。");
    onRefresh();
  }

  return (
    <section className="panel">
      <div className="section-bar">
        <div>
          <h2>知识库</h2>
          <p>保存不同品类的型号、术语、避坑点和价格判断规则。</p>
        </div>
        <button type="button" onClick={createKnowledgeBase}>
          <Plus size={16} /> 新建知识库
        </button>
      </div>
      <div className="knowledge-list">
        {knowledgeBases.length === 0 ? (
          <div className="empty-state">暂无知识库</div>
        ) : (
          knowledgeBases.map((knowledgeBase) => (
            <article className="item-card knowledge-card" key={knowledgeBase.id}>
              <div>
                <h3>{knowledgeBase.title}</h3>
                <p>{knowledgeBase.content}</p>
                <p>更新于 {formatDateTime(knowledgeBase.updated_at)}</p>
              </div>
              <div className="card-actions">
                <button className="ghost" title="编辑" onClick={() => edit(knowledgeBase)}>
                  <Pencil size={16} /> 编辑
                </button>
                <button
                  className="ghost danger icon-only"
                  title="删除"
                  onClick={() => void remove(knowledgeBase.id)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </article>
          ))
        )}
      </div>
      <Modal
        title={editingKnowledgeBaseId ? "编辑知识库" : "新建知识库"}
        open={modalOpen}
        onClose={closeModal}
      >
        <form className="modal-form" onSubmit={(event) => void submit(event)}>
          <label>
            名称
            <input
              value={draft.title}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              placeholder="例如：相机镜头型号知识库"
              required
              autoFocus
            />
          </label>
          <label>
            内容
            <textarea
              className="knowledge-content-input"
              value={draft.content}
              onChange={(event) => setDraft({ ...draft, content: event.target.value })}
              placeholder="写入这个品类的型号对照、缩写、价格区间、常见坑点等"
              required
            />
            <span className="field-hint">{draft.content.length.toLocaleString("zh-CN")} 字符</span>
          </label>
          <div className="modal-actions">
            <button className="ghost" type="button" onClick={closeModal}>
              取消
            </button>
            <button type="submit" disabled={saving}>
              {editingKnowledgeBaseId ? <Save size={16} /> : <Plus size={16} />}
              {saving ? "保存中" : editingKnowledgeBaseId ? "保存修改" : "创建知识库"}
            </button>
          </div>
        </form>
      </Modal>
    </section>
  );
}

function ResultsView({
  tasks,
  results,
  filter,
  onFilter,
  onRefresh
}: {
  tasks: MonitorTask[];
  results: ProductResult[];
  filter: ResultFilter;
  onFilter: (value: ResultFilter) => void;
  onRefresh: () => void;
}) {
  const [expandedResultIds, setExpandedResultIds] = useState<Set<string>>(() => new Set());
  const [selectedTaskId, setSelectedTaskId] = useState("all");
  const groupedResults = useMemo(() => {
    const taskOrder = new Map(tasks.map((task, index) => [task.id, index]));
    const groups = new Map<string, { taskId: string; taskTitle: string; keyword: string; items: ProductResult[] }>();
    const visibleResults =
      selectedTaskId === "all"
        ? results
        : results.filter((result) => result.task_id === selectedTaskId);

    for (const result of visibleResults) {
      const group = groups.get(result.task_id);
      if (group) {
        group.items.push(result);
      } else {
        groups.set(result.task_id, {
          taskId: result.task_id,
          taskTitle: result.task_title,
          keyword: result.keyword,
          items: [result]
        });
      }
    }

    return Array.from(groups.values()).sort((left, right) => {
      const leftOrder = taskOrder.get(left.taskId) ?? Number.MAX_SAFE_INTEGER;
      const rightOrder = taskOrder.get(right.taskId) ?? Number.MAX_SAFE_INTEGER;
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return newestResultTime(right.items) - newestResultTime(left.items);
    });
  }, [results, selectedTaskId, tasks]);

  async function clear() {
    const query = selectedTaskId === "all" ? "" : `?task_id=${encodeURIComponent(selectedTaskId)}`;
    await api(`/api/results${query}`, { method: "DELETE" });
    setExpandedResultIds(new Set());
    onRefresh();
  }

  function toggleExpanded(resultId: string) {
    setExpandedResultIds((current) => {
      const next = new Set(current);
      if (next.has(resultId)) {
        next.delete(resultId);
      } else {
        next.add(resultId);
      }
      return next;
    });
  }

  return (
    <section className="panel">
      <div className="result-toolbar">
        <div className="result-filters">
          <select value={filter} onChange={(event) => onFilter(event.target.value as ResultFilter)}>
            <option value="all">全部结果</option>
            <option value="recommended">AI 推荐</option>
            <option value="not_recommended">AI 不推荐</option>
            <option value="unanalyzed">未分析</option>
          </select>
          <select value={selectedTaskId} onChange={(event) => setSelectedTaskId(event.target.value)}>
            <option value="all">全部任务</option>
            {tasks.map((task) => (
              <option value={task.id} key={task.id}>
                {task.title}
              </option>
            ))}
          </select>
        </div>
        <button className="ghost danger" onClick={() => void clear()}>
          <Trash2 size={16} /> 清空
        </button>
      </div>
      {groupedResults.length === 0 ? (
        <div className="empty-state">暂无结果</div>
      ) : (
        <div className="result-groups">
          {groupedResults.map((group) => {
            const recommendedCount = group.items.filter((item) => item.recommended).length;
            return (
              <section className="result-group" key={group.taskId}>
                <div className="result-group-header">
                  <div>
                    <h2>{group.taskTitle}</h2>
                    <p>{group.keyword}</p>
                  </div>
                  <div className="result-group-meta">
                    <span>{group.items.length} 条</span>
                    <span>{recommendedCount} 推荐</span>
                  </div>
                </div>
                <div className="product-grid">
                  {group.items.map((result) => {
                    const expanded = expandedResultIds.has(result.id);
                    const reason = result.decision?.reason ?? result.product.description ?? "无描述";
                    const imageUrl = firstUsableImageUrl(result.product.image_urls);
                    return (
                      <article
                        className={`product-card ${result.recommended ? "recommended" : ""}`}
                        key={result.id}
                      >
                        <ProductThumb
                          imageUrl={imageUrl}
                          recommended={result.recommended}
                          title={result.product.title}
                        />
                        <div className="product-body">
                          <div className="product-copy">
                            <div className="product-meta-row">
                              <span>{result.product.location || group.keyword}</span>
                              {result.decision ? (
                                <Score value={result.decision.worth_percent} />
                              ) : (
                                <span className="score muted">未分析</span>
                              )}
                            </div>
                            <h3>{result.product.title}</h3>
                            <p className={expanded ? "ai-reason expanded" : "ai-reason"}>{reason}</p>
                          </div>
                          <div className="product-actions">
                            <div className="price-line">
                              <strong>{result.product.price ?? "价格未知"}</strong>
                              <button
                                className="text-button"
                                type="button"
                                onClick={() => toggleExpanded(result.id)}
                              >
                                {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                                {expanded ? "收起评价" : "展开评价"}
                              </button>
                            </div>
                            <div className="product-footer">
                              <span>{formatDateTime(result.fetched_at)}</span>
                              <a href={result.product.url} target="_blank" rel="noreferrer">
                                <ExternalLink size={16} /> 打开
                              </a>
                            </div>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}

function SettingsView({
  settings,
  setSettings,
  onNotice,
  onRefresh
}: {
  settings: AppSettings;
  setSettings: (settings: AppSettings) => void;
  onNotice: (message: string) => void;
  onRefresh: () => void;
}) {
  const [aiTest, setAiTest] = useState<AiTestResponse | null>(null);
  const [testingAi, setTestingAi] = useState(false);
  const [testingNotify, setTestingNotify] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await api<AppSettings>("/api/settings", {
      method: "PUT",
      body: JSON.stringify(settings)
    });
    onNotice("设置已保存。");
    onRefresh();
  }

  async function testAi() {
    setTestingAi(true);
    setAiTest(null);
    try {
      const result = await api<AiTestResponse>("/api/settings/ai/test", {
        method: "POST",
        body: JSON.stringify(settings.ai)
      });
      setAiTest(result);
      onNotice(result.ok ? "AI 连接测试成功。" : "AI 连接测试失败。");
    } catch (error) {
      setAiTest({
        ok: false,
        api_url: settings.ai.api_url,
        request_url: null,
        model_name: settings.ai.model_name,
        api_key_configured: Boolean(settings.ai.api_key),
        latency_ms: null,
        response_preview: null,
        error: String(error)
      });
      onNotice("AI 连接测试失败。");
    } finally {
      setTestingAi(false);
    }
  }

  async function testNotify() {
    setTestingNotify(true);
    const enabledNotifySettings = { ...settings.notify, enabled: true };
    try {
      await api<{ ok: boolean }>("/api/settings/notify/test", {
        method: "POST",
        body: JSON.stringify({ settings: enabledNotifySettings, save: true })
      });
      setSettings({ ...settings, notify: enabledNotifySettings });
      onNotice("微信提醒测试成功，正式提醒已启用并保存。");
    } catch (error) {
      onNotice(`微信提醒测试失败：${String(error)}`);
    } finally {
      setTestingNotify(false);
    }
  }

  return (
    <section className="panel settings-panel">
      <form className="settings-form" onSubmit={(event) => void submit(event)}>
        <label>
          API 地址
          <input
            value={settings.ai.api_url ?? ""}
            onChange={(event) =>
              setSettings({ ...settings, ai: { ...settings.ai, api_url: event.target.value || null } })
            }
            placeholder="https://api.openai.com/v1"
          />
        </label>
        <label>
          API Key
          <input
            type="password"
            value={settings.ai.api_key}
            onChange={(event) =>
              setSettings({ ...settings, ai: { ...settings.ai, api_key: event.target.value } })
            }
          />
        </label>
        <label>
          模型名称
          <input
            value={settings.ai.model_name}
            onChange={(event) =>
              setSettings({ ...settings, ai: { ...settings.ai, model_name: event.target.value } })
            }
          />
        </label>
        <label>
          AI 请求间隔
          <input
            type="number"
            min={0.2}
            step={0.1}
            value={settings.ai.request_interval_seconds ?? ""}
            onChange={(event) =>
              setSettings({
                ...settings,
                ai: {
                  ...settings.ai,
                  request_interval_seconds: event.target.value ? Number(event.target.value) : null
                }
              })
            }
          />
        </label>
        <div className="form-row">
          <label className="switch">
            <input
              type="checkbox"
              checked={settings.browser.headless}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  browser: { ...settings.browser, headless: event.target.checked }
                })
              }
            />
            无界面浏览器
          </label>
          <label className="switch">
            <input
              type="checkbox"
              checked={settings.browser.stop_on_verification}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  browser: { ...settings.browser, stop_on_verification: event.target.checked }
                })
              }
            />
            验证时停止
          </label>
        </div>
        <div className="settings-section-title">微信提醒</div>
        <div className="form-row">
          <label className="switch">
            <input
              type="checkbox"
              checked={settings.notify.enabled}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  notify: { ...settings.notify, enabled: event.target.checked }
                })
              }
            />
            启用微信提醒
          </label>
          <label>
            提醒阈值
            <input
              type="number"
              min={0}
              max={100}
              value={settings.notify.threshold_percent}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  notify: { ...settings.notify, threshold_percent: Number(event.target.value) }
                })
              }
            />
          </label>
        </div>
        <label className="wide-field">
          企业微信机器人 Webhook
          <input
            type="password"
            value={settings.notify.webhook_url}
            onChange={(event) =>
              setSettings({
                ...settings,
                notify: { ...settings.notify, webhook_url: event.target.value }
              })
            }
            placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
          />
        </label>
        <label>
          @ 手机号
          <input
            value={settings.notify.mention_mobile ?? ""}
            onChange={(event) =>
              setSettings({
                ...settings,
                notify: {
                  ...settings.notify,
                  mention_mobile: event.target.value || null
                }
              })
            }
            placeholder="可选"
          />
        </label>
        <div className="form-row">
          <label>
            登录等待秒数
            <input
              type="number"
              min={60}
              max={3600}
              value={settings.browser.login_timeout_seconds}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  browser: { ...settings.browser, login_timeout_seconds: Number(event.target.value) }
                })
              }
            />
          </label>
          <label>
            最小等待
            <input
              type="number"
              min={2}
              value={settings.browser.min_page_delay_seconds}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  browser: { ...settings.browser, min_page_delay_seconds: Number(event.target.value) }
                })
              }
            />
          </label>
          <label>
            最大等待
            <input
              type="number"
              min={3}
              value={settings.browser.max_page_delay_seconds}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  browser: { ...settings.browser, max_page_delay_seconds: Number(event.target.value) }
                })
              }
            />
          </label>
        </div>
        <div className="settings-actions">
          <button type="submit">
            <Save size={16} /> 保存设置
          </button>
          <button className="ghost" type="button" disabled={testingAi} onClick={() => void testAi()}>
            <Wifi size={16} /> {testingAi ? "测试中" : "测试 AI"}
          </button>
          <button
            className="ghost"
            type="button"
            disabled={testingNotify}
            onClick={() => void testNotify()}
          >
            <Wifi size={16} /> {testingNotify ? "测试中" : "测试微信"}
          </button>
        </div>
        {aiTest ? (
          <div className={aiTest.ok ? "ai-test-result success" : "ai-test-result failure"}>
            <strong>{aiTest.ok ? "连接成功" : "连接失败"}</strong>
            <span>地址：{aiTest.api_url ?? "未填写"}</span>
            {aiTest.request_url ? <span>请求：{aiTest.request_url}</span> : null}
            <span>模型：{aiTest.model_name}</span>
            <span>Key：{aiTest.api_key_configured ? "已填写" : "未填写"}</span>
            {aiTest.latency_ms !== null ? <span>耗时：{aiTest.latency_ms} ms</span> : null}
            {aiTest.response_preview ? <span>响应：{aiTest.response_preview}</span> : null}
            {aiTest.error ? <span>错误：{aiTest.error}</span> : null}
            {aiTest.ok ? <span>单次测试通过只代表配置可用；批量分析仍可能触发 429 限流，请适当调大 AI 请求间隔。</span> : null}
          </div>
        ) : null}
      </form>
    </section>
  );
}

function StatusBadge({ status }: { status: AccountStatus }) {
  const label = {
    pending: "未登录",
    login_waiting: "等待扫码",
    logged_in: "已登录",
    failed: "失败"
  }[status];
  return (
    <span className={`badge ${status}`}>
      {status === "logged_in" ? <CheckCircle2 size={14} /> : null}
      {label}
    </span>
  );
}

function Score({ value }: { value: number }) {
  return <span className={value >= 50 ? "score good" : "score"}>{value}%</span>;
}

function ProductThumb({
  imageUrl,
  recommended,
  title
}: {
  imageUrl: string | undefined;
  recommended: boolean;
  title: string;
}) {
  const [failed, setFailed] = useState(false);

  if (!imageUrl || failed) {
    return (
      <div className="thumb">
        <Bot size={34} />
        {recommended ? <span className="thumb-badge">推荐</span> : null}
      </div>
    );
  }

  return (
    <div className="thumb">
      <img
        src={imageUrl}
        alt={title}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
      {recommended ? <span className="thumb-badge">推荐</span> : null}
    </div>
  );
}

function firstUsableImageUrl(imageUrls: string[]) {
  return imageUrls.find((url) => {
    const lowerUrl = url.toLowerCase();
    if (!lowerUrl || lowerUrl.startsWith("data:")) return false;
    if (/[-/]\d{1,2}[-x_]\d{1,2}(?:\.|_|-|$)/.test(lowerUrl)) return false;
    if (/spacer|blank|transparent|pixel|placeholder/.test(lowerUrl)) return false;
    return true;
  });
}

function intervalLabel(interval: MonitorInterval) {
  return {
    none: "手动",
    "5m": "每 5min",
    "10m": "每 10min",
    "30m": "每 30min",
    "1h": "每 1h"
  }[interval];
}

function taskRunModeLabel(task: MonitorTask) {
  if (task.status === "running") {
    return task.interval === "none" ? "运行中" : "定时运行中";
  }
  if (task.interval === "none") {
    return task.enabled ? "可启动" : "已停止";
  }
  return task.enabled ? "定时已启动" : "定时已停止";
}

function browserModeValue(browserHeadless: boolean | null) {
  if (browserHeadless === null) return "system";
  return browserHeadless ? "headless" : "headed";
}

function browserHeadlessFromMode(value: string) {
  if (value === "headless") return true;
  if (value === "headed") return false;
  return null;
}

function browserModeLabel(browserHeadless: boolean | null) {
  if (browserHeadless === null) return "跟随系统";
  return browserHeadless ? "无界面" : "有界面";
}

function knowledgeBaseTitle(knowledgeBaseId: string | null, knowledgeBases: KnowledgeBase[]) {
  if (!knowledgeBaseId) return "不使用";
  return knowledgeBases.find((knowledgeBase) => knowledgeBase.id === knowledgeBaseId)?.title ?? "已删除";
}

function pageTitle(tab: AppTab) {
  return {
    accounts: "账号管理",
    tasks: "监控任务",
    knowledge: "知识库",
    results: "结果展示",
    settings: "系统设置",
    logs: "运行日志"
  }[tab];
}

function newestResultTime(results: ProductResult[]) {
  return Math.max(...results.map((result) => new Date(result.fetched_at).getTime()));
}

function formatDateTime(timestamp: string) {
  return new Date(timestamp).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function extractResponseError(rawMessage: string) {
  try {
    const parsed = JSON.parse(rawMessage);
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail) && parsed.detail[0]?.msg) {
      return String(parsed.detail[0].msg);
    }
  } catch {
    return rawMessage;
  }
  return rawMessage;
}

function formatErrorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  const rawMessage = error instanceof Error ? error.message : String(error);
  return extractResponseError(rawMessage) || rawMessage;
}

function formatLogTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString("zh-CN", { hour12: false });
}

function Modal({
  title,
  open,
  onClose,
  children
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="modal-header">
          <h2>{title}</h2>
          <button className="icon-button ghost" type="button" title="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

const rootElement = document.getElementById("root") as HTMLElement & { reactRoot?: Root };
rootElement.reactRoot = rootElement.reactRoot ?? createRoot(rootElement);
rootElement.reactRoot.render(<App />);
