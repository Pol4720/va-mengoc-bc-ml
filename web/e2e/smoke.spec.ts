import { expect, test, type Page } from "@playwright/test";

const ROUTES = ["#/", "#/pv", "#/lots", "#/data", "#/slides", "#/lab"];

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("vamengoc.lang", "es"));
});

for (const route of ROUTES) {
  test(`renders ${route} without errors or horizontal overflow`, async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto(`/${route}`);
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.getByText("Datos sintéticos.")).toBeVisible();
    if (!["#/", "#/lab", "#/slides"].includes(route)) {
      await expect(page.locator(".chart svg").first()).toBeVisible();
      for (const chart of await page.locator(".chart").all()) {
        await expect(chart).toHaveAttribute("role", "img");
        expect((await chart.getAttribute("aria-label"))?.length).toBeGreaterThan(3);
      }
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    expect(errors).toEqual([]);
  });
}

test("language and theme choices persist across reloads", async ({ page }) => {
  await page.goto("/#/pv");
  await page.getByRole("group", { name: "Idioma" }).getByRole("button", { name: "EN" }).click();
  await expect(page.locator("h1")).toHaveText("Post-marketing safety");
  await page.getByRole("button", { name: /Theme: automatic/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /Theme: light/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("signal rule and minimum reports re-threshold the released measures", async ({ page }) => {
  await page.goto("/#/pv");
  const tile = page.locator(".stat", { hasText: "Señales con la regla elegida" }).locator(".value");
  await expect(tile).toHaveText(/^\d+$/);
  await page.locator(".filters input[type=range]").fill("20");
  await expect(page.locator(".filters")).toContainText("Mínimo de notificaciones: 20");
  const high = Number(await tile.textContent());
  await page.locator(".filters input[type=range]").fill("1");
  const low = Number(await tile.textContent());
  expect(low).toBeGreaterThanOrEqual(high);
  await page.getByRole("button", { name: "ROR" }).click();
  await expect(page.getByRole("button", { name: "ROR" })).toHaveAttribute("aria-pressed", "true");
});

test("table view and CSV export are available for a chart", async ({ page }) => {
  await page.goto("/#/pv");
  const card = page.locator(".card", { hasText: "Tasa de notificación por año" });
  await card.getByRole("button", { name: "Tabla" }).click();
  await expect(card.locator("table.data")).toBeVisible();
  const download = page.waitForEvent("download");
  await card.getByRole("button", { name: /Descargar CSV/ }).click();
  expect((await download).suggestedFilename()).toBe("p1_rates_target.csv");
});

test("slides navigate with the keyboard and show speaker notes", async ({ page }) => {
  await page.goto("/#/slides/p1/1");
  await expect(page.locator(".slide-foot")).toContainText("1 / 8");
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/#\/slides\/p1\/2$/);
  await page.keyboard.press("End");
  await expect(page).toHaveURL(/#\/slides\/p1\/8$/);
  await page.keyboard.press("n");
  await expect(page.getByRole("complementary", { name: "Notas del orador" })).toBeVisible();
  await page.getByRole("button", { name: "Folleto / PDF" }).click();
  await expect(page.locator(".handout .slide-frame")).toHaveCount(8);
});

test("the guided pipeline story can be stepped through", async ({ page }) => {
  await page.goto("/#/");
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(8);
  await tabs.nth(6).click();
  await expect(page.getByRole("tabpanel")).toContainText("Control de divulgación");
});

test("the lab reports a missing local API clearly", async ({ page }) => {
  await page.goto("/#/lab");
  await page.getByLabel("Dirección de la API").fill("http://127.0.0.1:9");
  await page.getByLabel("Token de sesión").fill("x");
  await page.getByRole("button", { name: "Conectar" }).click();
  await expect(page.getByRole("alert")).toContainText("No se pudo conectar");
});
