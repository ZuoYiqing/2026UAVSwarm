import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { exportCampusTaskArea } from "../src/task-area-export.js";

const target = new URL("../docs/samples/qinglan-campus-task-area.proposal.json", import.meta.url);
await mkdir(new URL("../docs/samples/", import.meta.url), { recursive: true });
await writeFile(target, `${JSON.stringify(exportCampusTaskArea(), null, 2)}\n`);
console.log(fileURLToPath(target));
