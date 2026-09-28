import { expect, test } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";

let server: ChildProcessWithoutNullStreams;

test.beforeAll(async ({ request }) => {
  const python =
    process.env.PYTHON ??
    (process.platform === "win32"
      ? ".venv\\Scripts\\python.exe"
      : ".venv/bin/python");
  server = spawn(python, ["backend/tests/ui_server.py"], { stdio: "pipe" });
  let output = "";
  server.stderr.on("data", (chunk) => {
    output += chunk.toString();
  });
  server.stdout.on("data", (chunk) => {
    output += chunk.toString();
  });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null)
      throw new Error(`UI server exited early: ${output}`);
    try {
      const response = await request.get(
        "http://127.0.0.1:18761/_shield/health/live",
        { timeout: 500 },
      );
      if (response.ok()) return;
    } catch {
      /* wait for startup */
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`UI server did not become ready: ${output}`);
});

test.afterAll(async () => {
  if (!server || server.exitCode !== null) return;
  server.stdin.end();
  await Promise.race([
    new Promise<void>((resolve) => server.once("exit", () => resolve())),
    new Promise<void>((_, reject) =>
      setTimeout(() => reject(new Error("UI server did not stop")), 10_000),
    ),
  ]);
});

test("real management workflow", async ({ page, request }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("uismoke");
  await page.getByLabel("Password").fill("UiSmoke-password-2026");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Overview & logs" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByLabel("Baseline requests")).toBeVisible();
  await page.screenshot({
    path: "test-results/control-panel.png",
    fullPage: true,
  });
  await page.getByLabel("Baseline requests").fill("2");
  await page.getByRole("button", { name: "Add route" }).click();
  await page.getByLabel("Path pattern").fill("/cart");
  await page.getByLabel("Methods, comma separated").fill("POST");
  await page
    .getByLabel("Content types, comma separated")
    .fill("application/json");
  await page.getByLabel("Route rate limit").check();
  await page.getByLabel("Requests", { exact: true }).fill("10");
  await page.getByLabel("Window seconds", { exact: true }).fill("3600");
  await page
    .getByLabel("JSON schema, max 16 KiB")
    .fill(
      '{"type":"object","required":["quantity"],"properties":{"quantity":{"type":"integer","minimum":1}},"additionalProperties":false}',
    );
  await page.getByRole("button", { name: "Save & apply" }).click();
  await expect(
    page.getByText(/Version 1 is applied to new requests/),
  ).toBeVisible({ timeout: 20_000 });

  const blocked = await request.post("http://127.0.0.1:18762/cart", {
    headers: { Host: "api.localhost", "Content-Type": "application/json" },
    data: Buffer.from('{"quantity":'),
  });
  expect(blocked.status()).toBe(400);
  expect((await blocked.json()).error.code).toBe("INVALID_JSON");

  await page.getByRole("button", { name: "Bans" }).click();
  await page
    .getByLabel("IP address or trusted event digest")
    .fill("192.0.2.55");
  await page.getByRole("button", { name: "Create temporary ban" }).click();
  await expect(page.getByText("Ban created.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Revoke" })).toBeVisible();
  await page.getByRole("button", { name: "Revoke" }).click();
  await page.getByLabel("State").selectOption("revoked");
  await expect(page.getByText("revoked", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Overview & logs" }).click();
  await page.getByLabel("Event type").selectOption("security");
  await expect(page.getByText("ban.created", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Fuzz tests" }).click();
  await page.getByRole("button", { name: "Run fuzzing test" }).click();
  await expect(page.getByText(/Run results/)).toBeVisible();
  await expect(
    page
      .locator("section.card")
      .filter({ has: page.getByRole("heading", { name: "Run results" }) }),
  ).toContainText("PASSED · 17 passed · 0 failed · 0 errors", {
    timeout: 90_000,
  });

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Administrator sign in" }),
  ).toBeVisible();
});
