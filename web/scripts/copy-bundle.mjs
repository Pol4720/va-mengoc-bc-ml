// Copy the public results bundle into the web app (release/public when present, else synthetic).
// Only the disclosure-controlled bundle is ever copied; nothing else from the repository.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const candidates = ["public", "synthetic"].map((o) => resolve(root, "release", o, "web", "bundle.json"));
const source = candidates.find((p) => existsSync(p));
if (!source) {
  console.error("No release bundle found. Run `uv run vamengoc demo` (synthetic) or `vamengoc run` first.");
  process.exit(1);
}
const target = resolve(here, "..", "public", "data", "bundle.json");
mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
console.log(`bundle: ${source} -> ${target}`);
