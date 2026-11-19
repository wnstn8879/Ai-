import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { PAGE } from "../worker/page.js";
// Dependency-free bundling: the page is a single JS string, no secret values.
const entry = readFileSync("worker/worker.js", "utf8");
const pageImport =
  /^import\s*\{\s*PAGE\s*\}\s*from\s*["']\.\/page\.js["'];?\s*$/m;
if (!pageImport.test(entry))
  throw new Error("Expected the page import in Worker entry");
let source = entry.replace(
  pageImport,
  () => "const PAGE = " + JSON.stringify(PAGE) + ";",
);
if (/^import\s/m.test(source))
  throw new Error("Bundle has unresolved runtime imports");
mkdirSync("dist/server", { recursive: true });
mkdirSync("dist/.openai", { recursive: true });
writeFileSync("dist/server/index.js", source);
writeFileSync(
  "dist/.openai/hosting.json",
  readFileSync(".openai/hosting.json"),
);
