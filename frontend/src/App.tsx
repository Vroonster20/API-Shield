import { useCallback, useEffect, useMemo, useState } from "react";
import type { Dispatch, FormEvent, ReactNode, SetStateAction } from "react";
import {
  Activity,
  Ban,
  Check,
  CircleHelp,
  FlaskConical,
  Globe2,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Menu,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  getRows,
  login,
  request,
  type ApiRecord,
  type FuzzResult,
} from "@/lib/api";

type Page = "overview" | "logs" | "bans" | "settings" | "fuzz";

const navigation: { id: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "logs", label: "Request logs", icon: Activity },
  { id: "bans", label: "IP bans", icon: Ban },
  { id: "settings", label: "Settings", icon: Settings2 },
  { id: "fuzz", label: "Fuzz testing", icon: FlaskConical },
];

const settingKeys = [
  "rate_limit_requests",
  "rate_limit_window_seconds",
  "ban_duration_seconds",
] as const;

type SettingKey = (typeof settingKeys)[number];
type Settings = Partial<Record<SettingKey, number>>;

const settingLabels: Record<SettingKey, { label: string; help: string }> = {
  rate_limit_requests: {
    label: "Requests per window",
    help: "Maximum requests allowed from one IP during the rate limit window.",
  },
  rate_limit_window_seconds: {
    label: "Rate limit window",
    help: "Window length, in seconds, used to count requests.",
  },
  ban_duration_seconds: {
    label: "Ban duration",
    help: "How long an IP ban lasts, in seconds.",
  },
};

const defaultApiUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const loginEnabled = import.meta.env.VITE_ENABLE_LOGIN !== "false";

function getErrorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function getRecordValue(record: ApiRecord, ...keys: string[]) {
  const foundKey = keys.find((key) => record[key] !== undefined);
  return foundKey ? record[foundKey] : undefined;
}

function StatusBadge({ value }: { value: unknown }) {
  const normalized = String(value ?? "").toLowerCase();
  const positive = ["allowed", "passed", "success", "active", "true"].includes(
    normalized,
  );
  const negative = ["blocked", "failed", "error", "false"].includes(normalized);

  return (
    <Badge
      variant={negative ? "destructive" : positive ? "default" : "secondary"}
      className="capitalize"
    >
      {formatValue(value)}
    </Badge>
  );
}

function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

function Notice({
  children,
  onDismiss,
}: {
  children: ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div
      role="alert"
      className="mb-5 flex items-start justify-between gap-3 rounded-lg border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-destructive"
    >
      <span>{children}</span>
      {onDismiss && (
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          onClick={onDismiss}
          aria-label="Dismiss error"
          className="text-destructive hover:bg-destructive/10 hover:text-destructive"
        >
          <X className="size-4" />
        </Button>
      )}
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof CircleHelp;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-5 py-14 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-xl bg-muted text-muted-foreground">
        <Icon className="size-5" />
      </div>
      <h3 className="font-medium text-foreground">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function DataTable({
  rows,
  columns,
  emptyTitle,
  emptyDescription,
  action,
}: {
  rows: ApiRecord[];
  columns: { key: string; label: string; render?: (row: ApiRecord) => ReactNode }[];
  emptyTitle: string;
  emptyDescription: string;
  action?: (row: ApiRecord) => ReactNode;
}) {
  if (!rows.length) {
    return (
      <EmptyState
        icon={CircleHelp}
        title={emptyTitle}
        description={emptyDescription}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-left text-sm">
        <thead>
          <tr className="border-b bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            {columns.map((column) => (
              <th key={column.key} className="px-5 py-3 font-medium">
                {column.label}
              </th>
            ))}
            {action && <th className="px-5 py-3 font-medium">Action</th>}
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((row, index) => (
            <tr
              key={String(row.id ?? row.name ?? index)}
              className="transition-colors hover:bg-muted/30"
            >
              {columns.map((column) => (
                <td key={column.key} className="px-5 py-3.5 text-foreground">
                  {column.render
                    ? column.render(row)
                    : formatValue(row[column.key])}
                </td>
              ))}
              {action && (
                <td className="px-5 py-3.5 text-right">{action(row)}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LoginScreen({
  apiUrl,
  setApiUrl,
  onLogin,
}: {
  apiUrl: string;
  setApiUrl: (value: string) => void;
  onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onLogin(username, password);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-2 flex items-center gap-2 text-primary">
            <ShieldCheck className="size-5" />
            <span className="text-sm font-semibold text-foreground">API Shield</span>
          </div>
          <CardTitle className="text-xl">Sign in</CardTitle>
          <CardDescription>
            Enter your gateway URL and admin credentials.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <label className="block space-y-1.5 text-sm font-medium">
              Gateway URL
              <Input
                type="url"
                required
                value={apiUrl}
                onChange={(event) => setApiUrl(event.target.value)}
                placeholder="http://127.0.0.1:8000"
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              Username
              <Input
                autoComplete="username"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Admin username"
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              Password
              <Input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Admin password"
              />
            </label>
            {error && <Notice>{error}</Notice>}
            <Button type="submit" disabled={busy} className="w-full">
              {busy && <LoaderCircle className="size-4 animate-spin" />}
              Sign in
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Credentials are sent only to this gateway.
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

export default function App() {
  const [apiUrl, setApiUrl] = useState(defaultApiUrl);
  const [token, setToken] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [logs, setLogs] = useState<ApiRecord[]>([]);
  const [bans, setBans] = useState<ApiRecord[]>([]);
  const [settings, setSettings] = useState<Settings>({});
  const [settingInputs, setSettingInputs] = useState<Record<SettingKey, string>>({
    rate_limit_requests: "",
    rate_limit_window_seconds: "",
    ban_duration_seconds: "",
  });
  const [fuzzResults, setFuzzResults] = useState<FuzzResult[]>([]);
  const [search, setSearch] = useState("");
  const [newBanIp, setNewBanIp] = useState("");
  const [pageNotice, setPageNotice] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const normalizedApiUrl = useMemo(() => apiUrl.trim().replace(/\/+$/, ""), [apiUrl]);

  const loadPage = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    setPageNotice("");
    try {
      if (page === "overview") {
        const results = await Promise.allSettled([
          getRows(normalizedApiUrl, "/admin/logs", token, ["logs", "items", "results"]),
          getRows(normalizedApiUrl, "/admin/bans", token, ["bans", "items", "results"]),
          request<unknown>(normalizedApiUrl, "/admin/settings", { method: "GET" }, token),
        ]);
        const failures = results.filter(
          (result): result is PromiseRejectedResult => result.status === "rejected",
        );
        if (results[0].status === "fulfilled") setLogs(results[0].value);
        if (results[1].status === "fulfilled") setBans(results[1].value);
        if (results[2].status === "rejected") {
          throw new Error(failures.map((result) => getErrorMessage(result.reason)).join(" · "));
        }
        const rawSettings = results[2].value;
        const settingsObject =
          rawSettings && typeof rawSettings === "object" && "settings" in rawSettings
            ? (rawSettings.settings as Record<string, unknown>)
            : (rawSettings as Record<string, unknown>);
        const nextSettings: Settings = {};
        for (const key of settingKeys) {
          const value = settingsObject?.[key];
          if (typeof value === "number") nextSettings[key] = value;
        }
        setSettings(nextSettings);
        if (failures.length) {
          throw new Error(failures.map((result) => getErrorMessage(result.reason)).join(" · "));
        }
      } else if (page === "logs") {
        setLogs(
          await getRows(normalizedApiUrl, "/admin/logs", token, [
            "logs",
            "items",
            "results",
          ]),
        );
      } else if (page === "bans") {
        setBans(
          await getRows(normalizedApiUrl, "/admin/bans", token, [
            "bans",
            "items",
            "results",
          ]),
        );
      } else if (page === "settings") {
        const rawSettings = await request<unknown>(
          normalizedApiUrl,
          "/admin/settings",
          { method: "GET" },
          token,
        );
        const settingsObject =
          rawSettings && typeof rawSettings === "object" && "settings" in rawSettings
            ? (rawSettings.settings as Record<string, unknown>)
            : (rawSettings as Record<string, unknown>);
        const nextSettings: Settings = {};
        const inputValues: Partial<Record<SettingKey, string>> = {};
        for (const key of settingKeys) {
          const value = settingsObject?.[key];
          if (typeof value === "number") {
            nextSettings[key] = value;
            inputValues[key] = String(value);
          }
        }
        setSettings(nextSettings);
        setSettingInputs((current) => ({ ...current, ...inputValues }));
      }
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [normalizedApiUrl, page, token]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

  async function handleLogin(username: string, password: string) {
    const result = await login(normalizedApiUrl, username, password);
    setToken(result.token);
    setPage("overview");
  }

  function signOut() {
    setToken(null);
    setPage("overview");
    setError("");
    setLogs([]);
    setBans([]);
    setFuzzResults([]);
  }

  async function createBan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newBanIp.trim()) return;
    setActionBusy(true);
    setError("");
    setPageNotice("");
    try {
      await request(normalizedApiUrl, "/admin/bans", {
        method: "POST",
        body: JSON.stringify({ ip: newBanIp.trim() }),
      }, token);
      const createdIp = newBanIp.trim();
      setNewBanIp("");
      await loadPage();
      setPageNotice(`Ban created for ${createdIp}.`);
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setActionBusy(false);
    }
  }

  async function revokeBan(id: unknown) {
    if (id === undefined || id === null) {
      setError("This ban record has no ID, so it cannot be revoked.");
      return;
    }
    setActionBusy(true);
    setError("");
    setPageNotice("");
    try {
      await request(
        normalizedApiUrl,
        `/admin/bans/${encodeURIComponent(String(id))}`,
        { method: "DELETE" },
        token,
      );
      await loadPage();
      setPageNotice("Ban revoked.");
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setActionBusy(false);
    }
  }

  async function saveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = {} as Record<SettingKey, number>;
    for (const key of settingKeys) {
      const value = Number(settingInputs[key]);
      if (!Number.isInteger(value) || value < 1) {
        setError(`${settingLabels[key].label} must be a whole number greater than zero.`);
        return;
      }
      values[key] = value;
    }
    setActionBusy(true);
    setError("");
    setPageNotice("");
    try {
      await request(
        normalizedApiUrl,
        "/admin/settings",
        { method: "PUT", body: JSON.stringify(values) },
        token,
      );
      setSettings(values);
      setPageNotice("Settings saved.");
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setActionBusy(false);
    }
  }

  async function runFuzzSuite() {
    setActionBusy(true);
    setError("");
    setPageNotice("");
    try {
      setFuzzResults(
        await getRows(
          normalizedApiUrl,
          "/admin/fuzz",
          token,
          ["results", "cases", "items"],
          { method: "POST" },
        ) as FuzzResult[],
      );
      setPageNotice("Fuzz suite completed.");
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setActionBusy(false);
    }
  }

  const filteredLogs = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return logs;
    return logs.filter((row) =>
      Object.values(row).some((value) =>
        formatValue(value).toLowerCase().includes(query),
      ),
    );
  }, [logs, search]);

  if (loginEnabled && !token) {
    return (
      <LoginScreen
        apiUrl={apiUrl}
        setApiUrl={setApiUrl}
        onLogin={handleLogin}
      />
    );
  }

  const currentNavigation = navigation.find((item) => item.id === page);

  return (
    <div className="min-h-screen bg-background text-foreground">
      {mobileNavOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setMobileNavOpen(false)}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[250px] flex-col border-r bg-background transition-transform lg:translate-x-0 ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-[72px] items-center gap-2 border-b px-5">
          <ShieldCheck className="size-5 text-primary" />
          <div className="text-sm font-semibold">API Shield</div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close navigation"
            onClick={() => setMobileNavOpen(false)}
            className="ml-auto lg:hidden"
          >
            <X />
          </Button>
        </div>
        <div className="px-3 pt-5">
          <p className="px-3 pb-2 text-xs font-medium text-muted-foreground">
            Pages
          </p>
          <nav className="space-y-1" aria-label="Main navigation">
            {navigation.map(({ id, label, icon: Icon }) => (
              <Button
                type="button"
                variant={page === id ? "secondary" : "ghost"}
                key={id}
                onClick={() => {
                  setPage(id);
                  setMobileNavOpen(false);
                }}
                className="w-full justify-start gap-3"
              >
                <Icon className="size-4" />
                {label}
                {id === "bans" && bans.length > 0 && (
                  <Badge variant="outline" className="ml-auto">
                    {bans.length}
                  </Badge>
                )}
              </Button>
            ))}
          </nav>
        </div>
        <div className="mt-auto border-t p-3">
          <p className="truncate px-3 pb-2 text-xs text-muted-foreground" title={normalizedApiUrl}>
            {normalizedApiUrl}
          </p>
          {token && (
            <Button
              type="button"
              variant="ghost"
              onClick={signOut}
              className="w-full justify-start gap-3"
            >
              <LogOut className="size-4" />
              Sign out
            </Button>
          )}
        </div>
      </aside>

      <div className="min-h-screen lg:pl-[250px]">
        <header className="sticky top-0 z-20 flex h-[64px] items-center justify-between border-b bg-background px-4 sm:px-7 lg:px-9">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Open navigation"
              onClick={() => setMobileNavOpen(true)}
              className="lg:hidden"
            >
              <Menu />
            </Button>
            <div className="text-sm font-medium">{currentNavigation?.label}</div>
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void loadPage()}
              disabled={loading}
              className="gap-2"
            >
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">Refresh</span>
            </Button>
            {token && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={signOut}
                aria-label="Sign out"
              >
                <LogOut />
              </Button>
            )}
          </div>
        </header>

        <main className="mx-auto max-w-[1440px] px-4 py-7 sm:px-7 sm:py-9 lg:px-9">
          {!token && (
            <div className="mb-5 rounded-lg border bg-muted px-4 py-3 text-sm text-muted-foreground">
              Login is disabled. API data and actions are unavailable in preview mode.
            </div>
          )}
          {error && <Notice onDismiss={() => setError("")}>{error}</Notice>}
          {pageNotice && (
            <div className="mb-5 flex items-center gap-2 rounded-lg border bg-muted px-4 py-3 text-sm">
              <Check className="size-4" />
              {pageNotice}
            </div>
          )}

          {page === "overview" && (
            <OverviewPage
              logs={logs}
              bans={bans}
              settings={settings}
              loading={loading}
              goTo={setPage}
            />
          )}
          {page === "logs" && (
            <LogsPage
              rows={filteredLogs}
              search={search}
              setSearch={setSearch}
              loading={loading}
            />
          )}
          {page === "bans" && (
            <BansPage
              rows={bans}
              ip={newBanIp}
              setIp={setNewBanIp}
              onCreate={createBan}
              onRevoke={revokeBan}
              loading={loading}
              actionBusy={actionBusy}
            />
          )}
          {page === "settings" && (
            <SettingsPage
              settings={settings}
              inputs={settingInputs}
              setInputs={setSettingInputs}
              onSave={saveSettings}
              loading={loading}
              actionBusy={actionBusy}
            />
          )}
          {page === "fuzz" && (
            <FuzzPage
              rows={fuzzResults}
              onRun={runFuzzSuite}
              loading={loading}
              actionBusy={actionBusy}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function OverviewPage({
  logs,
  bans,
  settings,
  loading,
  goTo,
}: {
  logs: ApiRecord[];
  bans: ApiRecord[];
  settings: Settings;
  loading: boolean;
  goTo: (page: Page) => void;
}) {
  const blockedCount = logs.filter(
    (row) => String(getRecordValue(row, "decision", "status")).toLowerCase() === "blocked",
  ).length;
  const allowedCount = logs.filter(
    (row) => String(getRecordValue(row, "decision", "status")).toLowerCase() === "allowed",
  ).length;

  return (
    <>
      <PageHeading
        title="Overview"
        description="Recent gateway activity and protection settings."
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Requests inspected"
          value={loading && !logs.length ? "—" : String(logs.length)}
        />
        <MetricCard
          label="Requests allowed"
          value={String(allowedCount)}
        />
        <MetricCard
          label="Requests blocked"
          value={String(blockedCount)}
        />
        <MetricCard
          label="Active bans"
          value={String(bans.length)}
        />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Recent requests</CardTitle>
            </div>
            <Button variant="outline" size="sm" onClick={() => goTo("logs")}>
              All logs
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            <DataTable
              rows={logs.slice(0, 5)}
              columns={logColumns}
              emptyTitle={loading ? "Loading request activity" : "No request logs yet"}
              emptyDescription="When the gateway receives requests, their outcomes will appear here."
            />
          </CardContent>
        </Card>
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Protection rules</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {settingKeys.map((key) => (
                <div key={key} className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium">{settingLabels[key].label}</p>
                  </div>
                  <span className="rounded-md bg-muted px-2.5 py-1 text-sm font-semibold tabular-nums">
                    {settings[key] ?? "—"}
                    {settings[key] !== undefined &&
                      key !== "rate_limit_requests" &&
                      " sec"}
                  </span>
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                className="mt-1 w-full"
                onClick={() => goTo("settings")}
              >
                Settings
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Fuzz testing</CardTitle>
              <CardDescription>Run the gateway’s predefined test cases.</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" onClick={() => goTo("fuzz")}>
                Open tests
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function MetricCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      </CardContent>
    </Card>
  );
}

const logColumns = [
  { key: "timestamp", label: "Time" },
  { key: "ip", label: "IP address" },
  { key: "path", label: "Request path" },
  {
    key: "source",
    label: "Source",
    render: (row: ApiRecord) => (
      <Badge variant={row.source === "demo" ? "secondary" : "outline"}>
        {row.source === "demo" ? "Demo" : "Live"}
      </Badge>
    ),
  },
  {
    key: "decision",
    label: "Decision",
    render: (row: ApiRecord) => (
      <StatusBadge value={getRecordValue(row, "decision", "status")} />
    ),
  },
  { key: "reason", label: "Reason" },
];

function LogsPage({
  rows,
  search,
  setSearch,
  loading,
}: {
  rows: ApiRecord[];
  search: string;
  setSearch: (value: string) => void;
  loading: boolean;
}) {
  return (
    <>
      <PageHeading
        title="Request logs"
        description="Search and review allowed or blocked requests."
        action={
          <div className="relative w-full sm:w-64">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search request logs"
              placeholder="Search logs..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="pl-9"
            />
          </div>
        }
      />
      <Card>
        <CardHeader className="flex flex-row items-center justify-between border-b">
          <div>
            <CardTitle>Gateway activity</CardTitle>
            <CardDescription className="mt-1">
              {rows.length} {rows.length === 1 ? "record" : "records"}
              {search ? " matching your search" : ""}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            rows={rows}
            columns={logColumns}
            emptyTitle={loading ? "Loading request logs" : "No matching requests"}
            emptyDescription={
              search
                ? "Try another search term."
                : "Request history will appear here when the gateway has logged traffic."
            }
          />
        </CardContent>
      </Card>
    </>
  );
}

function BansPage({
  rows,
  ip,
  setIp,
  onCreate,
  onRevoke,
  loading,
  actionBusy,
}: {
  rows: ApiRecord[];
  ip: string;
  setIp: (value: string) => void;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  onRevoke: (id: unknown) => void;
  loading: boolean;
  actionBusy: boolean;
}) {
  return (
    <>
      <PageHeading
        title="IP bans"
        description="Add an address to the deny list or revoke an existing ban."
      />
      <Card className="mb-5">
        <CardContent className="flex flex-col justify-between gap-5 p-5 sm:flex-row sm:items-center">
          <div>
            <h2 className="font-medium">Add a ban</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              The gateway applies the configured ban duration.
            </p>
          </div>
          <form onSubmit={onCreate} className="flex w-full gap-2 sm:max-w-md">
            <Input
              type="text"
              required
              value={ip}
              onChange={(event) => setIp(event.target.value)}
              placeholder="e.g. 203.0.113.42"
              aria-label="IP address to ban"
            />
            <Button type="submit" disabled={actionBusy || !ip.trim()} className="shrink-0">
              Ban IP
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between border-b">
          <div>
            <CardTitle>Banned addresses</CardTitle>
            <CardDescription className="mt-1">
              {rows.length} {rows.length === 1 ? "record" : "records"}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            rows={rows}
            columns={[
              { key: "ip", label: "IP address" },
              {
                key: "source",
                label: "Source",
                render: (row) => (
                  <Badge variant={row.source === "demo" ? "secondary" : "outline"}>
                    {row.source === "demo" ? "Demo" : "Live"}
                  </Badge>
                ),
              },
              { key: "banned_at", label: "Banned at" },
              { key: "expires_at", label: "Expires at" },
              {
                key: "status",
                label: "Status",
                render: (row) => (
                  <StatusBadge
                    value={
                      row.status ??
                      (row.expires_at &&
                      new Date(String(row.expires_at)).getTime() > Date.now()
                        ? "active"
                        : "expired")
                    }
                  />
                ),
              },
            ]}
            emptyTitle={loading ? "Loading bans" : "No banned addresses"}
            emptyDescription="Addresses banned by the gateway will appear here."
            action={(row) => (
              <Button
                variant="outline"
                size="sm"
                disabled={actionBusy}
                onClick={() => onRevoke(row.id)}
              >
                Revoke
              </Button>
            )}
          />
        </CardContent>
      </Card>
    </>
  );
}

function SettingsPage({
  settings,
  inputs,
  setInputs,
  onSave,
  loading,
  actionBusy,
}: {
  settings: Settings;
  inputs: Record<SettingKey, string>;
  setInputs: Dispatch<SetStateAction<Record<SettingKey, string>>>;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
  loading: boolean;
  actionBusy: boolean;
}) {
  return (
    <>
      <PageHeading
        title="Protection settings"
        description="Change rate limits and automatic ban duration."
      />
      <div className="max-w-3xl">
        <Card>
          <CardHeader className="border-b">
            <CardTitle>Traffic controls</CardTitle>
          </CardHeader>
          <CardContent className="p-5 sm:p-6">
            {loading && settingKeys.every((key) => settings[key] === undefined) ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                <LoaderCircle className="size-4 animate-spin" />
                Loading gateway settings…
              </div>
            ) : (
              <form onSubmit={onSave} className="space-y-6">
                {settingKeys.map((key) => (
                  <label
                    key={key}
                    className="grid gap-2 sm:grid-cols-[1fr_180px] sm:items-center sm:gap-6"
                  >
                    <span>
                      <span className="block text-sm font-medium">
                        {settingLabels[key].label}
                      </span>
                      <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                        {settingLabels[key].help}
                      </span>
                    </span>
                    <Input
                      type="number"
                      min={1}
                      step={1}
                      required
                      value={inputs[key]}
                      onChange={(event) =>
                        setInputs({ ...inputs, [key]: event.target.value })
                      }
                    />
                  </label>
                ))}
                <div className="flex justify-end border-t pt-5">
                  <Button type="submit" disabled={actionBusy}>
                    {actionBusy && (
                      <LoaderCircle className="mr-2 size-4 animate-spin" />
                    )}
                    Save changes
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function FuzzPage({
  rows,
  onRun,
  loading,
  actionBusy,
}: {
  rows: FuzzResult[];
  onRun: () => void;
  loading: boolean;
  actionBusy: boolean;
}) {
  const passed = rows.filter((row) => row.passed === true).length;
  const failed = rows.filter((row) => row.passed === false).length;

  return (
    <>
      <PageHeading
        title="Fuzz testing"
        description="Run the predefined gateway test cases."
        action={
          <Button onClick={onRun} disabled={actionBusy || loading} className="gap-2">
            {actionBusy ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <FlaskConical className="size-4" />
            )}
            Run fuzz suite
          </Button>
        }
      />
      {rows.length > 0 && (
        <div className="mb-5 grid gap-4 sm:grid-cols-3">
          <MetricCard
            label="Cases run"
            value={String(rows.length)}
          />
          <MetricCard
            label="Passed"
            value={String(passed)}
          />
          <MetricCard
            label="Failed"
            value={String(failed)}
          />
        </div>
      )}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between border-b">
          <div>
            <CardTitle>Test case results</CardTitle>
            <CardDescription className="mt-1">
              {rows.length
                ? "Expected and actual outcomes from the latest run."
                : "Run the suite to inspect the gateway’s validation behavior."}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            rows={rows as ApiRecord[]}
            columns={[
              { key: "name", label: "Test case" },
              { key: "expected", label: "Expected" },
              { key: "actual", label: "Actual" },
              {
                key: "passed",
                label: "Result",
                render: (row) => <StatusBadge value={row.passed ? "passed" : "failed"} />,
              },
            ]}
            emptyTitle={loading ? "Loading test results" : "No test run yet"}
            emptyDescription="Start a fuzz run to test the gateway and view case-by-case results."
          />
        </CardContent>
      </Card>
      <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
        <Globe2 className="size-3.5" />
        Fuzz cases are sent to the gateway’s own protected routes.
      </p>
    </>
  );
}
