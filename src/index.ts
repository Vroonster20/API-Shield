import "./styles.css";
import { api, post, setSession, ApiError } from "./api";
import type {
  Session,
  Status,
  Page,
  RequestEvent,
  SecurityEvent,
  Ban,
  FuzzSummary,
  FuzzDetail,
  Config,
  ConfigResponse,
  ApplyResponse,
  RouteConfig,
} from "./api";

const root = document.querySelector<HTMLDivElement>("#app")!;
type Area = "overview" | "settings" | "bans" | "fuzz";
let session: Session | null = null;
let area: Area = "overview";
let draft: Config | null = null;
let version: number | null = null;
let dirty = false;
let timer: number | undefined;
let token = 0;
const date = (ms: number | null | undefined): string =>
  ms == null ? "—" : new Date(ms).toLocaleString();
const msg = (e: unknown): string =>
  e instanceof Error ? e.message : "Something went wrong. Try again.";
function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  text?: string,
  cls?: string,
): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function add(parent: HTMLElement, ...children: HTMLElement[]): void {
  parent.append(...children);
}
function btn(text: string, fn: () => void, cls = ""): HTMLButtonElement {
  const b = el("button", text, cls);
  b.type = "button";
  b.addEventListener("click", fn);
  return b;
}
function note(parent: HTMLElement, text: string, kind = "info"): void {
  const p = el("p", text, `notice ${kind}`);
  p.setAttribute("role", kind === "error" ? "alert" : "status");
  parent.prepend(p);
}
function input(
  label: string,
  value: string,
  change: (v: string) => void,
  type = "text",
  min?: number,
  max?: number,
): HTMLElement {
  const l = el("label", undefined, "field");
  add(l, el("span", label));
  const i = el("input");
  i.type = type;
  i.value = value;
  if (min !== undefined) i.min = String(min);
  if (max !== undefined) i.max = String(max);
  i.addEventListener("input", () => change(i.value));
  l.append(i);
  return l;
}
function checkbox(
  label: string,
  value: boolean,
  change: (v: boolean) => void,
): HTMLElement {
  const l = el("label", undefined, "check");
  const i = el("input");
  i.type = "checkbox";
  i.checked = value;
  i.addEventListener("change", () => change(i.checked));
  add(l, i, el("span", label));
  return l;
}
function choice(
  label: string,
  value: string,
  options: { id: string; name: string }[],
  change: (v: string) => void,
): HTMLElement {
  const l = el("label", undefined, "field");
  add(l, el("span", label));
  const s = el("select");
  options.forEach((x) => {
    const o = el("option", x.name);
    o.value = x.id;
    o.selected = x.id === value;
    s.append(o);
  });
  s.addEventListener("change", () => change(s.value));
  l.append(s);
  return l;
}
function num(v: string, lo: number, hi: number): number {
  const n = Number(v);
  return Number.isInteger(n) ? Math.max(lo, Math.min(hi, n)) : lo;
}
function stop(): void {
  if (timer !== undefined) clearTimeout(timer);
  timer = undefined;
}
function expire(message = "Your session ended. Sign in again."): void {
  session = null;
  setSession(null);
  draft = null;
  version = null;
  dirty = false;
  stop();
  login(message);
}
async function guarded<T>(p: Promise<T>): Promise<T> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) expire();
    throw e;
  }
}
function heading(main: HTMLElement, title: string, subtitle: string): void {
  const h = el("header", undefined, "page-header");
  add(h, el("h1", title), el("p", subtitle, "muted"));
  main.append(h);
}
function grid(headers: string[], rows: string[][]): HTMLElement {
  const wrap = el("div", undefined, "table-scroll"),
    t = el("table"),
    head = el("thead"),
    h = el("tr"),
    body = el("tbody");
  headers.forEach((x) => h.append(el("th", x)));
  head.append(h);
  rows.forEach((row) => {
    const tr = el("tr");
    row.forEach((x) => tr.append(el("td", x)));
    body.append(tr);
  });
  add(t, head, body);
  wrap.append(t);
  return wrap;
}
function query(values: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== undefined && v !== "") q.set(k, String(v));
  });
  return q.toString();
}

function login(error = ""): void {
  root.replaceChildren();
  const shell = el("main", undefined, "login-shell"),
    card = el("section", undefined, "login-card");
  add(
    card,
    el("div", "SHIELD / API", "brand"),
    el("h1", "Administrator sign in"),
    el("p", "Manage gateway protection and review security activity.", "muted"),
  );
  if (error) note(card, error, "error");
  const form = el("form"),
    u = el("input"),
    p = el("input"),
    ul = el("label", undefined, "field"),
    pl = el("label", undefined, "field"),
    submit = el("button", "Sign in", "primary");
  u.autocomplete = "username";
  u.required = true;
  p.type = "password";
  p.autocomplete = "current-password";
  p.required = true;
  submit.type = "submit";
  add(ul, el("span", "Username"), u);
  add(pl, el("span", "Password"), p);
  add(form, ul, pl, submit);
  card.append(form);
  shell.append(card);
  root.append(shell);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submit.disabled = true;
    submit.textContent = "Signing in…";
    try {
      session = await post<Session>("/auth/login", {
        username: u.value,
        password: p.value,
      });
      setSession(session);
      area = "overview";
      app();
    } catch (err) {
      note(card, msg(err), "error");
      submit.disabled = false;
      submit.textContent = "Sign in";
    }
  });
}
function app(): void {
  stop();
  token++;
  root.replaceChildren();
  const shell = el("div", undefined, "shell"),
    side = el("aside", undefined, "sidebar"),
    nav = el("nav"),
    main = el("main", undefined, "content");
  nav.setAttribute("aria-label", "Main navigation");
  add(
    side,
    el("div", "SHIELD / API", "brand"),
    el("p", "ADMIN CONSOLE", "eyebrow"),
  );
  const tabs: [Area, string][] = [
    ["overview", "Overview & logs"],
    ["settings", "Settings"],
    ["bans", "Bans"],
    ["fuzz", "Fuzz tests"],
  ];
  tabs.forEach(([id, label]) => {
    const b = btn(
      label,
      () => {
        area = id;
        app();
      },
      id === area ? "nav active" : "nav",
    );
    if (id === area) b.setAttribute("aria-current", "page");
    nav.append(b);
  });
  add(
    side,
    nav,
    el("p", session?.admin.username ?? "", "signed-in"),
    btn(
      "Sign out",
      async () => {
        try {
          await post<void>("/auth/logout", {});
        } catch {
          /* clear local view */
        }
        expire("");
      },
      "nav",
    ),
  );
  add(shell, side, main);
  root.append(shell);
  if (area === "overview") void overview(main, token);
  if (area === "settings") void settings(main, token);
  if (area === "bans") void bans(main, token);
  if (area === "fuzz") void fuzz(main, token);
}

async function overview(main: HTMLElement, id: number): Promise<void> {
  heading(
    main,
    "Overview & logs",
    "Gateway state and redacted activity from the management API.",
  );
  const state = el("section", "Loading gateway state…", "card"),
    logs = el("section", undefined, "card");
  add(main, state, logs);
  const toolbar = el("div", undefined, "toolbar"),
    k = el("select"),
    period = el("select");
  [
    ["request", "Request events"],
    ["security", "Security events"],
  ].forEach(([a, b]) => {
    const o = el("option", b);
    o.value = a;
    k.append(o);
  });
  [
    ["1", "Past hour"],
    ["24", "Past day"],
    ["168", "Past 7 days"],
  ].forEach(([a, b]) => {
    const o = el("option", b);
    o.value = a;
    period.append(o);
  });
  const kl = el("label", undefined, "field"),
    pl = el("label", undefined, "field");
  add(kl, el("span", "Event type"), k);
  add(pl, el("span", "Time range"), period);
  add(toolbar, kl, pl);
  add(logs, el("h2", "Events"), toolbar);
  let cursor: string | null = null;
  let range = { to: Date.now(), from: Date.now() - 3600000 };
  function resetRange(): void {
    range = {
      to: Date.now(),
      from: Date.now() - num(period.value, 1, 168) * 3600000,
    };
    cursor = null;
    void events();
  }
  k.addEventListener("change", resetRange);
  period.addEventListener("change", resetRange);
  async function status(): Promise<void> {
    try {
      const s = await guarded(api<Status>("/status"));
      if (id !== token) return;
      state.replaceChildren();
      state.append(el("h2", "Gateway status"));
      const label = s.status;
      add(
        state,
        el("p", label.toUpperCase(), `status-pill ${label}`),
        el(
          "p",
          `Desired version ${s.desired_version ?? "—"} · Applied version ${s.applied_version ?? "—"}`,
        ),
        el("p", `Last heartbeat: ${date(s.heartbeat_ms)}`, "muted"),
      );
      if (label === "failed")
        note(
          state,
          `Apply failed: ${s.apply_error_code ?? "unknown"}`,
          "error",
        );
      if (s.dropped_events_since_start)
        note(
          state,
          `${s.dropped_events_since_start} request events dropped since gateway start; logs may be incomplete.`,
        );
    } catch (e) {
      if (id === token) note(state, msg(e), "error");
    }
  }
  async function events(): Promise<void> {
    logs.querySelector(".event-body")?.remove();
    const body = el("div", "Loading events…", "event-body");
    logs.append(body);
    try {
      const p = await guarded(
        api<Page<RequestEvent | SecurityEvent>>(
          `/events?${query({ kind: k.value, from_ms: range.from, to_ms: range.to, limit: 50, cursor: cursor ?? undefined })}`,
        ),
      );
      if (id !== token) return;
      body.replaceChildren();
      if (p.telemetry_complete === false)
        body.append(
          el(
            "p",
            `Telemetry may be incomplete. Earliest retained: ${date(p.earliest_retained_ms)}.`,
            "muted",
          ),
        );
      if (!p.items.length)
        body.append(el("p", "No events in this period.", "empty"));
      else if (k.value === "request")
        body.append(
          grid(
            [
              "Time",
              "Decision",
              "Method / route",
              "Status",
              "Reason",
              "Origin",
            ],
            (p.items as RequestEvent[]).map((x) => [
              date(x.at_ms),
              x.decision,
              `${x.method} ${x.route_id ?? "unmatched"}`,
              String(x.status_code ?? "—"),
              x.reason_code ?? "—",
              x.origin_attempted
                ? `attempted · ${x.upstream_status ?? "—"}`
                : "not attempted",
            ]),
          ),
        );
      else
        body.append(
          grid(
            ["Time", "Event", "Actor", "Digest", "Request"],
            (p.items as SecurityEvent[]).map((x) => [
              date(x.at_ms),
              x.event_type,
              x.actor_type,
              x.client_digest ?? "—",
              x.request_id ?? "—",
            ]),
          ),
        );
      if (p.next_cursor)
        body.append(
          btn("Next page", () => {
            cursor = p.next_cursor;
            void events();
          }),
        );
    } catch (e) {
      if (id === token) note(body, msg(e), "error");
    }
  }
  await Promise.all([status(), events()]);
  if (id === token) {
    const refresh = async () => {
      if (id !== token) return;
      await status();
      if (id === token) timer = window.setTimeout(refresh, 5000);
    };
    timer = window.setTimeout(refresh, 5000);
  }
}

function emptyConfig(): Config {
  return {
    schema_version: 1,
    service: {
      id: "demo",
      name: "Demo service",
      public_host: "api.localhost",
      upstream_id: "demo-origin",
      enabled: true,
      unmatched_action: "baseline",
      max_body_bytes: 1048576,
      ip_rate: { limit: 300, window_seconds: 60 },
      abuse: {
        auto_ban_enabled: false,
        strike_limit: 10,
        window_seconds: 60,
        ban_seconds: 300,
      },
      routes: [],
    },
  };
}
function newRoute(cap: number): RouteConfig {
  return {
    id: "route_" + Math.random().toString(36).slice(2, 8),
    name: "New route",
    path: "/",
    methods: ["GET"],
    max_body_bytes: cap,
    content_types: [],
    ip_rate: null,
    json_schema: null,
  };
}
function valid(c: Config): string | null {
  const s = c.service;
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(s.id)) return "Invalid service ID.";
  if (!s.name.trim() || s.name.length > 80)
    return "Service name must be 1–80 characters.";
  if (!/^[a-z0-9.-]+$/.test(s.public_host) || s.public_host.includes(".."))
    return "Enter a lowercase DNS host without a port.";
  if (s.routes.length > 100) return "At most 100 routes are allowed.";
  const ids = new Set<string>();
  for (const r of s.routes) {
    if (!/^[a-z][a-z0-9_-]{0,63}$/.test(r.id) || ids.has(r.id))
      return "Each route needs a unique valid ID.";
    ids.add(r.id);
    if (!r.name.trim() || r.name.length > 80)
      return "Route names must be 1–80 characters.";
    if (!r.path.startsWith("/") || r.path.includes("//"))
      return "Route paths must start with / and cannot contain repeated slashes.";
    if (!r.methods.length) return "Each route needs a method.";
    if (r.max_body_bytes > s.max_body_bytes)
      return "Route body cap exceeds service cap.";
    if (
      r.json_schema &&
      !r.content_types.some(
        (t) => t === "application/json" || t.endsWith("+json"),
      )
    )
      return "A JSON schema requires an allowed JSON content type.";
  }
  return null;
}

async function settings(main: HTMLElement, id: number): Promise<void> {
  heading(
    main,
    "Settings",
    "Edit locally, save a revision, then watch the gateway apply it.",
  );
  const host = el("div", "Loading settings…");
  main.append(host);
  let upstreams: { id: string; name: string }[] = [];
  try {
    const r = await guarded(
      api<{ upstreams: { id: string; name: string }[] }>("/registry"),
    );
    upstreams = r.upstreams;
    if (!draft) {
      const c = await guarded(api<ConfigResponse>("/config"));
      version = c.version;
      draft = c.document ?? emptyConfig();
      if (!c.document && upstreams.length)
        draft.service.upstream_id = upstreams[0].id;
    }
    if (id === token) render();
  } catch (e) {
    if (id === token) note(host, msg(e), "error");
  }
  function render(): void {
    if (!draft) return;
    const s = draft.service;
    host.replaceChildren();
    const form = el("form"),
      service = el("section", undefined, "card"),
      sg = el("div", undefined, "grid");
    add(
      service,
      el("h2", "Service"),
      el(
        "p",
        `Editing version ${version ?? "new"}${dirty ? " · unsaved changes" : ""}`,
        "muted",
      ),
    );
    add(
      sg,
      input("Service ID", s.id, (v) => mark((s.id = v))),
      input("Name", s.name, (v) => mark((s.name = v))),
      input("Public host", s.public_host, (v) => mark((s.public_host = v))),
      choice("Approved upstream", s.upstream_id, upstreams, (v) =>
        mark((s.upstream_id = v)),
      ),
      input(
        "Max body bytes",
        String(s.max_body_bytes),
        (v) => mark((s.max_body_bytes = num(v, 0, 1048576))),
        "number",
        0,
        1048576,
      ),
      choice(
        "Unmatched paths",
        s.unmatched_action,
        [
          { id: "baseline", name: "Baseline then forward" },
          { id: "deny", name: "Baseline then 404" },
        ],
        (v) => mark((s.unmatched_action = v as "baseline" | "deny")),
      ),
      input(
        "Baseline requests",
        String(s.ip_rate.limit),
        (v) => mark((s.ip_rate.limit = num(v, 1, 100000))),
        "number",
        1,
        100000,
      ),
      input(
        "Baseline window seconds",
        String(s.ip_rate.window_seconds),
        (v) => mark((s.ip_rate.window_seconds = num(v, 1, 3600))),
        "number",
        1,
        3600,
      ),
    );
    add(
      service,
      sg,
      checkbox("Service enabled", s.enabled, (v) => mark((s.enabled = v))),
      el(
        "p",
        "Changing a rate limit or window starts fresh counters. Other edits preserve them.",
        "hint",
      ),
    );
    const abuse = el("section", undefined, "card"),
      ag = el("div", undefined, "grid");
    add(
      abuse,
      el("h2", "Abuse detection"),
      el(
        "p",
        "Detection records repeated rate and inspected JSON violations even when automatic bans are off.",
        "muted",
      ),
    );
    add(
      ag,
      input(
        "Strike threshold",
        String(s.abuse.strike_limit),
        (v) => mark((s.abuse.strike_limit = num(v, 2, 1000))),
        "number",
        2,
        1000,
      ),
      input(
        "Strike window seconds",
        String(s.abuse.window_seconds),
        (v) => mark((s.abuse.window_seconds = num(v, 10, 3600))),
        "number",
        10,
        3600,
      ),
      input(
        "Ban duration seconds",
        String(s.abuse.ban_seconds),
        (v) => mark((s.abuse.ban_seconds = num(v, 30, 3600))),
        "number",
        30,
        3600,
      ),
    );
    add(
      abuse,
      ag,
      checkbox(
        "Create automatic temporary bans",
        s.abuse.auto_ban_enabled,
        (v) => mark((s.abuse.auto_ban_enabled = v)),
      ),
      el(
        "p",
        "Changing abuse settings resets strikes. Existing bans remain active when automatic creation is disabled.",
        "hint",
      ),
    );
    const routes = el("section", undefined, "card");
    add(
      routes,
      el("h2", "Routes"),
      el(
        "p",
        "Presets copy values into a route; edit each route independently.",
        "muted",
      ),
    );
    s.routes.forEach((r, i) => routeCard(routes, r, i));
    routes.append(
      btn(
        "Add route",
        () => {
          s.routes.push(newRoute(s.max_body_bytes));
          mark();
          render();
        },
        "secondary",
      ),
    );
    const save = el("button", "Save & apply", "primary");
    save.type = "submit";
    add(form, service, abuse, routes, save);
    host.append(form);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!draft) return;
      const error = valid(draft);
      if (error) {
        note(host, error, "error");
        return;
      }
      save.disabled = true;
      save.textContent = "Saving…";
      try {
        const result = await guarded(
          api<ApplyResponse>("/config", {
            method: "PUT",
            body: JSON.stringify({
              expected_version: version,
              document: draft,
            }),
          }),
        );
        version = result.desired_version;
        dirty = false;
        note(
          host,
          `Version ${result.desired_version} saved; applied version ${result.applied_version ?? "—"}. Waiting for gateway.`,
          "success",
        );
        void watch(result.desired_version, host, id);
      } catch (err) {
        note(host, msg(err), "error");
        if (err instanceof ApiError && err.code === "CONFIG_CONFLICT")
          note(
            host,
            "Your edits remain in this form. Copy them before reloading the server version.",
            "info",
          );
      } finally {
        save.disabled = false;
        save.textContent = "Save & apply";
      }
    });
    function mark(_?: unknown): void {
      dirty = true;
      const p = service.querySelector(".muted");
      if (p)
        p.textContent = `Editing version ${version ?? "new"} · unsaved changes`;
    }
    function routeCard(parent: HTMLElement, r: RouteConfig, i: number): void {
      const card = el("div", undefined, "route-card"),
        g = el("div", undefined, "grid");
      card.append(el("h3", `Route ${i + 1}`));
      add(
        g,
        input("Route ID", r.id, (v) => mark((r.id = v))),
        input("Name", r.name, (v) => mark((r.name = v))),
        input("Path pattern", r.path, (v) => mark((r.path = v))),
        input("Methods, comma separated", r.methods.join(", "), (v) =>
          mark(
            (r.methods = v
              .split(",")
              .map((x) => x.trim().toUpperCase())
              .filter(Boolean)),
          ),
        ),
        input(
          "Max body bytes",
          String(r.max_body_bytes),
          (v) => mark((r.max_body_bytes = num(v, 0, 1048576))),
          "number",
          0,
          1048576,
        ),
        input(
          "Content types, comma separated",
          r.content_types.join(", "),
          (v) =>
            mark(
              (r.content_types = v
                .split(",")
                .map((x) => x.trim().toLowerCase())
                .filter(Boolean)),
            ),
        ),
      );
      card.append(g);
      const rate = el("div", undefined, "inline");
      rate.append(
        checkbox("Route rate limit", r.ip_rate !== null, (v) => {
          r.ip_rate = v
            ? { limit: Math.min(60, s.ip_rate.limit), window_seconds: 60 }
            : null;
          mark();
          render();
        }),
      );
      if (r.ip_rate)
        add(
          rate,
          input(
            "Requests",
            String(r.ip_rate.limit),
            (v) => {
              if (r.ip_rate) mark((r.ip_rate.limit = num(v, 1, 100000)));
            },
            "number",
            1,
            100000,
          ),
          input(
            "Window seconds",
            String(r.ip_rate.window_seconds),
            (v) => {
              if (r.ip_rate) mark((r.ip_rate.window_seconds = num(v, 1, 3600)));
            },
            "number",
            1,
            3600,
          ),
        );
      card.append(rate);
      const label = el("label", undefined, "field"),
        schema = el("textarea");
      schema.rows = 5;
      schema.maxLength = 16384;
      schema.value = r.json_schema
        ? JSON.stringify(r.json_schema, null, 2)
        : "";
      schema.placeholder = "Restricted JSON schema object (optional)";
      schema.addEventListener("input", () => {
        try {
          const v: unknown = schema.value.trim()
            ? JSON.parse(schema.value)
            : null;
          if (v !== null && (typeof v !== "object" || Array.isArray(v)))
            throw Error();
          r.json_schema = v as Record<string, unknown> | null;
          schema.setCustomValidity("");
          mark();
        } catch {
          schema.setCustomValidity("Enter a valid JSON object or leave empty.");
        }
      });
      add(label, el("span", "JSON schema, max 16 KiB"), schema);
      card.append(label);
      const actions = el("div", undefined, "actions");
      add(
        actions,
        btn("Copy login preset", () => preset("login")),
        btn("Copy JSON preset", () => preset("json")),
        btn(
          "Remove route",
          () => {
            s.routes.splice(i, 1);
            mark();
            render();
          },
          "danger",
        ),
      );
      card.append(actions);
      parent.append(card);
      function preset(kind: "login" | "json"): void {
        r.methods = ["POST"];
        r.max_body_bytes = Math.min(65536, s.max_body_bytes);
        r.content_types = ["application/json"];
        r.ip_rate = {
          limit: Math.min(kind === "login" ? 10 : 60, s.ip_rate.limit),
          window_seconds: 60,
        };
        r.json_schema = null;
        mark();
        render();
      }
    }
  }
}
async function watch(
  target: number,
  host: HTMLElement,
  id: number,
): Promise<void> {
  for (let i = 0; i < 10 && id === token; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    if (id !== token) return;
    try {
      const s = await guarded(api<Status>("/status"));
      if (s.applied_version === target) {
        note(host, `Version ${target} is applied to new requests.`, "success");
        return;
      }
      if (s.apply_error_version === target) {
        note(
          host,
          `Version ${target} could not be applied: ${s.apply_error_code ?? "unknown error"}. Last applied version remains active.`,
          "error",
        );
        return;
      }
    } catch {
      return;
    }
  }
  if (id === token)
    note(host, "Still pending. Check Overview for current gateway state.");
}

async function bans(main: HTMLElement, id: number): Promise<void> {
  heading(
    main,
    "Bans",
    "Review temporary bans and revoke by immutable ban ID.",
  );
  const advice = el("section", undefined, "card");
  add(
    advice,
    el("h2", "How bans work"),
    el(
      "p",
      "One ban affects everyone sharing that IP. Revoking a ban does not refund rate quotas; new violations can start fresh strikes. Digests do not reveal raw IP addresses.",
      "muted",
    ),
  );
  main.append(advice);
  const create = el("section", undefined, "card"),
    form = el("form"),
    identity = el("input"),
    duration = el("input"),
    reason = el("select"),
    submit = el("button", "Create temporary ban", "primary");
  identity.placeholder = "IP address or 64-character event digest";
  identity.required = true;
  duration.type = "number";
  duration.min = "30";
  duration.max = "3600";
  duration.value = "300";
  submit.type = "submit";
  [
    ["operator_action", "Operator action"],
    ["demo_test", "Demo test"],
  ].forEach(([v, t]) => {
    const o = el("option", t);
    o.value = v;
    reason.append(o);
  });
  const il = el("label", undefined, "field"),
    dl = el("label", undefined, "field"),
    rl = el("label", undefined, "field"),
    trusted = el("select"),
    tl = el("label", undefined, "field");
  add(il, el("span", "IP address or trusted event digest"), identity);
  add(dl, el("span", "Duration seconds (30–3600)"), duration);
  add(rl, el("span", "Reason"), reason);
  add(
    tl,
    el("span", "Select a recent security-event digest (optional)"),
    trusted,
  );
  trusted.append(el("option", "Loading recent digests…"));
  trusted.addEventListener("change", () => {
    if (trusted.value) identity.value = trusted.value;
  });
  add(form, tl, il, dl, rl, submit);
  add(create, el("h2", "Add ban"), form);
  main.append(create);
  void loadTrusted();
  async function loadTrusted(): Promise<void> {
    try {
      const to = Date.now(),
        from = to - 7 * 86400000;
      const p = await guarded(
        api<Page<SecurityEvent>>(
          `/events?${query({ kind: "security", from_ms: from, to_ms: to, limit: 100 })}`,
        ),
      );
      if (id !== token) return;
      trusted.replaceChildren();
      const first = el("option", "Enter an IP or select a digest");
      first.value = "";
      trusted.append(first);
      const seen = new Set<string>();
      p.items.forEach((e) => {
        const d = e.client_digest;
        if (d && /^[a-fA-F0-9]{64}$/.test(d) && !seen.has(d)) {
          seen.add(d);
          const o = el("option", `${e.event_type} · ${d.slice(0, 16)}…`);
          o.value = d;
          trusted.append(o);
        }
      });
    } catch {
      trusted.replaceChildren(el("option", "Recent digests unavailable"));
    }
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = identity.value.trim(),
      seconds = Number(duration.value);
    if (!Number.isInteger(seconds) || seconds < 30 || seconds > 3600) {
      note(create, "Duration must be 30–3600 seconds.", "error");
      return;
    }
    submit.disabled = true;
    try {
      const body = /^[a-fA-F0-9]{64}$/.test(v)
        ? {
            client_digest: v.toLowerCase(),
            duration_seconds: seconds,
            reason: reason.value,
          }
        : { ip: v, duration_seconds: seconds, reason: reason.value };
      await guarded(post<Ban>("/bans", body));
      identity.value = "";
      note(create, "Ban created.", "success");
      void list();
    } catch (err) {
      note(create, msg(err), "error");
    } finally {
      submit.disabled = false;
    }
  });
  const listBox = el("section", undefined, "card"),
    filter = el("select");
  [
    ["active", "Active"],
    ["all", "All recent"],
    ["expired", "Expired"],
    ["revoked", "Revoked"],
  ].forEach(([v, t]) => {
    const o = el("option", t);
    o.value = v;
    filter.append(o);
  });
  const fl = el("label", undefined, "field");
  add(fl, el("span", "State"), filter);
  add(listBox, el("h2", "Ban list"), fl);
  main.append(listBox);
  let cursor: string | null = null;
  filter.addEventListener("change", () => {
    cursor = null;
    void list();
  });
  async function list(): Promise<void> {
    listBox.querySelector(".list-body")?.remove();
    const body = el("div", "Loading bans…", "list-body");
    listBox.append(body);
    try {
      const p = await guarded(
        api<Page<Ban>>(
          `/bans?${query({ state: filter.value, limit: 50, cursor: cursor ?? undefined })}`,
        ),
      );
      if (id !== token) return;
      body.replaceChildren();
      if (!p.items.length)
        body.append(el("p", "No bans in this view.", "empty"));
      else {
        const wrap = el("div", undefined, "table-scroll"),
          table = el("table"),
          head = el("tr"),
          thead = el("thead"),
          tbody = el("tbody");
        [
          "Status",
          "Digest",
          "Source / reason",
          "Created",
          "Expires",
          "Action",
        ].forEach((t) => head.append(el("th", t)));
        thead.append(head);
        p.items.forEach((b) => {
          const tr = el("tr");
          [
            b.status,
            b.client_digest,
            `${b.source} · ${b.reason_code}`,
            date(b.created_at_ms),
            date(b.expires_at_ms),
          ].forEach((v) => tr.append(el("td", v)));
          const action = el("td");
          if (b.status === "active") {
            const revoke = btn(
              "Revoke",
              async () => {
                revoke.disabled = true;
                try {
                  await guarded(
                    post(`/bans/${encodeURIComponent(b.ban_id)}/revoke`, {}),
                  );
                  void list();
                } catch (err) {
                  note(body, msg(err), "error");
                  revoke.disabled = false;
                }
              },
              "danger",
            );
            action.append(revoke);
          } else action.textContent = "—";
          tr.append(action);
          tbody.append(tr);
        });
        add(table, thead, tbody);
        wrap.append(table);
        body.append(wrap);
      }
      if (p.next_cursor)
        body.append(
          btn("Next page", () => {
            cursor = p.next_cursor;
            void list();
          }),
        );
    } catch (err) {
      if (id === token) note(body, msg(err), "error");
    }
  }
  await list();
}

async function fuzz(main: HTMLElement, id: number): Promise<void> {
  heading(
    main,
    "Fuzz tests",
    "Run a fixed synthetic profile and inspect each checked invariant.",
  );
  const intro = el("section", undefined, "card");
  add(
    intro,
    el("h2", "Core demo profile"),
    el(
      "p",
      "Tests Shield and synthetic demo API; does not scan your live API. Uses isolated fixtures, a fixed case budget and no target URL.",
      "muted",
    ),
  );
  const form = el("form"),
    seed = el("input"),
    label = el("label", undefined, "field"),
    start = el("button", "Run fuzzing test", "primary");
  seed.type = "number";
  seed.min = "0";
  seed.max = "2147483647";
  seed.value = "1";
  start.type = "submit";
  add(label, el("span", "Seed (0–2147483647)"), seed);
  add(form, label, start);
  intro.append(form);
  main.append(intro);
  const history = el("section", undefined, "card"),
    detail = el("section", undefined, "card");
  add(history, el("h2", "Recent runs"));
  add(main, history, detail);
  let active: string | null = null;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const n = Number(seed.value);
    if (!Number.isInteger(n) || n < 0 || n > 2147483647) {
      note(intro, "Enter a seed from 0 through 2147483647.", "error");
      return;
    }
    start.disabled = true;
    try {
      const r = await guarded(
        post<{ run_id: string; state: string }>("/fuzz-runs", {
          profile_id: "core-demo-v1",
          seed: n,
        }),
      );
      active = r.run_id;
      note(intro, `Run ${r.run_id} queued.`, "success");
      await Promise.all([loadHistory(), loadDetail(r.run_id)]);
      poll();
    } catch (err) {
      note(intro, msg(err), "error");
    } finally {
      start.disabled = active !== null;
    }
  });
  async function loadHistory(): Promise<void> {
    try {
      const p = await guarded(api<Page<FuzzSummary>>("/fuzz-runs?limit=50"));
      if (id !== token) return;
      history.querySelector(".run-list")?.remove();
      const list = el("div", undefined, "run-list");
      if (!p.items.length) list.append(el("p", "No runs yet.", "empty"));
      else
        p.items.forEach((r) => {
          const row = el("div", undefined, "run-row");
          add(
            row,
            el(
              "span",
              `${date(r.created_at_ms)} · ${r.state} · seed ${r.seed}`,
            ),
            btn("View results", () => {
              active = r.run_id;
              void loadDetail(r.run_id);
            }),
          );
          list.append(row);
        });
      history.append(list);
    } catch (err) {
      if (id === token) note(history, msg(err), "error");
    }
  }
  async function loadDetail(runId: string): Promise<void> {
    try {
      const r = await guarded(
        api<FuzzDetail>(`/fuzz-runs/${encodeURIComponent(runId)}`),
      );
      if (id !== token || active !== runId) return;
      detail.replaceChildren();
      add(
        detail,
        el("h2", "Run results"),
        el(
          "p",
          `${r.state.toUpperCase()} · ${r.passed_count} passed · ${r.failed_count} failed · ${r.error_count} errors`,
        ),
        el(
          "p",
          `Started ${date(r.started_at_ms)} · Finished ${date(r.finished_at_ms)}`,
          "muted",
        ),
      );
      if (!r.cases?.length)
        detail.append(
          el("p", "Results will appear when the run completes.", "empty"),
        );
      else
        detail.append(
          grid(
            [
              "Case",
              "Expected",
              "Actual",
              "Outcome",
              "Request ID",
              "Elapsed",
              "Origin receipts",
            ],
            r.cases.map((c) => [
              c.case_id,
              c.expected,
              c.actual,
              c.outcome,
              c.request_id ?? "—",
              `${c.elapsed_ms} ms`,
              String(c.origin_receipt_delta),
            ]),
          ),
        );
      if (["queued", "running"].includes(r.state)) {
        start.disabled = true;
        poll();
      } else {
        active = null;
        start.disabled = false;
        stop();
      }
    } catch (err) {
      if (id === token) note(detail, msg(err), "error");
    }
  }
  function poll(): void {
    stop();
    if (id === token && active)
      timer = window.setTimeout(() => {
        if (active) void loadDetail(active);
      }, 2000);
  }
  await loadHistory();
}

async function bootstrap(): Promise<void> {
  root.textContent = "Checking admin session…";
  try {
    session = await api<Session>("/auth/session");
    setSession(session);
    app();
  } catch {
    login();
  }
}
void bootstrap();
