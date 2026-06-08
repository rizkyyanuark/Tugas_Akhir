#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DEFAULT_FILES = [
  "notebooks/build-graph/yunesa_academic_kg_construction.ipynb",
  "notebooks/build-graph/yunesa_academic_graphrag_groq.ipynb",
  "notebooks/build-graph/yunesa_academic_graphrag_dev.ipynb",
  "notebooks/build-graph/src/yunesa_academic_kg.py",
  "notebooks/build-graph/ieee-thesaurus.ttl",
  "notebooks/build-graph/ieee-taxonomy.ttl",
  "notebooks/README.md",
  "notebooks/pyproject.toml",
  "notebooks/uv.lock",
];

function parseArgs(argv) {
  const args = {
    repoRoot: path.resolve(__dirname, ".."),
    rootFolderName: "Tugas_Akhir",
    rootFolderId: "",
    dryRun: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--repo-root") {
      args.repoRoot = path.resolve(argv[++i]);
    } else if (arg === "--root-folder-name") {
      args.rootFolderName = argv[++i];
    } else if (arg === "--root-folder-id") {
      args.rootFolderId = argv[++i];
    } else if (arg === "--dry-run") {
      args.dryRun = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return args;
}

function resolveGwsEntrypoint() {
  if (process.env.GWS_CLI_JS) {
    return process.env.GWS_CLI_JS;
  }

  const appData = process.env.APPDATA;
  if (appData) {
    const candidate = path.join(
      appData,
      "npm",
      "node_modules",
      "@googleworkspace",
      "cli",
      "run.js",
    );
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(
    "Cannot find Google Workspace CLI entrypoint. Install with: npm install -g @googleworkspace/cli",
  );
}

const GWS_CLI = resolveGwsEntrypoint();

function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function isTransientFailure(output) {
  return /connection (was )?forcibly closed|connection reset|timeout|temporar|internalError|HTTP request failed|os error 10054/i.test(
    output,
  );
}

function runGws(args, options = {}) {
  const retries = options.retries ?? 3;
  let lastError = null;

  for (let attempt = 1; attempt <= retries; attempt += 1) {
    const result = spawnSync(process.execPath, [GWS_CLI, ...args], {
      cwd: process.cwd(),
      encoding: "utf8",
      maxBuffer: 1024 * 1024 * 64,
    });

    if (result.status === 0) {
      return result.stdout?.trim() ?? "";
    }

    const message = [
      `gws command failed: gws ${args.join(" ")}`,
      result.stdout?.trim(),
      result.stderr?.trim(),
    ]
      .filter(Boolean)
      .join("\n");
    lastError = new Error(message);

    if (attempt < retries && isTransientFailure(message)) {
      const delayMs = 1500 * attempt;
      console.warn(`Transient gws failure. Retry ${attempt}/${retries - 1} in ${delayMs}ms.`);
      sleep(delayMs);
      continue;
    }

    break;
  }

  throw lastError;
}

function parseJsonOutput(output) {
  const trimmed = output.trim();
  const firstJsonIndex = Math.min(
    ...["{", "["]
      .map((char) => trimmed.indexOf(char))
      .filter((index) => index >= 0),
  );

  if (!Number.isFinite(firstJsonIndex)) {
    throw new Error(`No JSON found in gws output: ${trimmed.slice(0, 200)}`);
  }

  return JSON.parse(trimmed.slice(firstJsonIndex));
}

function driveList(params) {
  const output = runGws([
    "drive",
    "files",
    "list",
    "--params",
    JSON.stringify(params),
  ]);
  return parseJsonOutput(output).files ?? [];
}

function driveGet(fileId, fields) {
  const output = runGws([
    "drive",
    "files",
    "get",
    "--params",
    JSON.stringify({ fileId, fields }),
  ]);
  return parseJsonOutput(output);
}

function driveAboutV2(fields) {
  const output = runGws([
    "drive",
    "about",
    "get",
    "--api-version",
    "v2",
    "--params",
    JSON.stringify({ fields }),
  ]);
  return parseJsonOutput(output);
}

function driveCreateFolder(name, parentId) {
  const body = {
    name,
    mimeType: "application/vnd.google-apps.folder",
  };
  if (parentId) {
    body.parents = [parentId];
  }

  const output = runGws([
    "drive",
    "files",
    "create",
    "--params",
    JSON.stringify({ fields: "id,name,mimeType,parents" }),
    "--json",
    JSON.stringify(body),
  ]);
  return parseJsonOutput(output);
}

function escapeDriveQueryValue(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function folderQuery(name, parentId = "") {
  const clauses = [
    `name='${escapeDriveQueryValue(name)}'`,
    "mimeType='application/vnd.google-apps.folder'",
    "trashed=false",
  ];
  if (parentId) {
    clauses.push(`'${parentId}' in parents`);
  }
  return clauses.join(" and ");
}

function fileQuery(name, parentId) {
  return [
    `name='${escapeDriveQueryValue(name)}'`,
    "trashed=false",
    `'${parentId}' in parents`,
  ].join(" and ");
}

function findFolder(name, parentId = "") {
  const files = driveList({
    q: folderQuery(name, parentId),
    pageSize: 20,
    fields: "files(id,name,mimeType,modifiedTime,parents)",
  });
  return files[0] ?? null;
}

function ensureFolder(name, parentId = "", dryRun = false) {
  const existing = findFolder(name, parentId);
  if (existing) {
    return existing;
  }

  if (dryRun) {
    return { id: `dry-run:${parentId || "root"}:${name}`, name };
  }

  return driveCreateFolder(name, parentId);
}

function ensureFolderPath(parts, rootFolderId, dryRun = false) {
  let parentId = rootFolderId;
  for (const part of parts) {
    const folder = ensureFolder(part, parentId, dryRun);
    parentId = folder.id;
  }
  return parentId;
}

function resolveRootFolder({ rootFolderName, rootFolderId, dryRun }) {
  if (rootFolderId) {
    return driveGet(rootFolderId, "id,name,mimeType,parents");
  }

  try {
    const about = driveAboutV2("rootFolderId,user");
    if (about.rootFolderId) {
      const myDriveFolder = findFolder(rootFolderName, about.rootFolderId);
      if (myDriveFolder) {
        return myDriveFolder;
      }
    }
  } catch (error) {
    console.warn(`Warning: cannot resolve My Drive root folder: ${error.message}`);
  }

  const existing = findFolder(rootFolderName);
  if (existing) {
    console.warn(
      `Warning: using first folder named '${rootFolderName}'. Pass --root-folder-id to avoid ambiguity.`,
    );
    return existing;
  }

  if (dryRun) {
    return { id: `dry-run:root:${rootFolderName}`, name: rootFolderName };
  }

  return driveCreateFolder(rootFolderName, "");
}

function localMd5(filePath) {
  return crypto.createHash("md5").update(fs.readFileSync(filePath)).digest("hex");
}

function mimeFor(filePath) {
  if (filePath.endsWith(".ipynb")) return "application/json";
  if (filePath.endsWith(".py")) return "text/x-python";
  if (filePath.endsWith(".ttl")) return "text/turtle";
  if (filePath.endsWith(".md")) return "text/markdown";
  if (filePath.endsWith(".toml")) return "text/plain";
  if (filePath.endsWith(".lock")) return "application/octet-stream";
  return "application/octet-stream";
}

function findFile(name, parentId) {
  const files = driveList({
    q: fileQuery(name, parentId),
    pageSize: 20,
    fields: "files(id,name,mimeType,modifiedTime,md5Checksum,size,parents)",
  });
  return files[0] ?? null;
}

function createOrUpdateFile({ relativePath, repoRoot, rootFolderId, dryRun }) {
  const localPath = path.join(repoRoot, relativePath);
  if (!fs.existsSync(localPath)) {
    throw new Error(`Local file is missing: ${relativePath}`);
  }

  const normalized = relativePath.replaceAll("\\", "/");
  const folderParts = normalized.split("/").slice(0, -1);
  const name = path.basename(normalized);
  const parentId = ensureFolderPath(folderParts, rootFolderId, dryRun);
  const existing = findFile(name, parentId);
  const md5 = localMd5(localPath);

  if (existing?.md5Checksum === md5) {
    return {
      path: normalized,
      status: "unchanged",
      fileId: existing.id,
      md5,
      modifiedTime: existing.modifiedTime,
    };
  }

  if (dryRun) {
    return {
      path: normalized,
      status: existing ? "would-update" : "would-create",
      fileId: existing?.id ?? "",
      md5,
    };
  }

  const params = {
    fields: "id,name,mimeType,modifiedTime,md5Checksum,size,parents",
  };
  const body = {
    name,
  };

  let output;
  if (existing) {
    params.fileId = existing.id;
    output = runGws([
      "drive",
      "files",
      "update",
      "--params",
      JSON.stringify(params),
      "--json",
      JSON.stringify(body),
      "--upload",
      localPath,
      "--upload-content-type",
      mimeFor(localPath),
    ]);
  } else {
    body.parents = [parentId];
    output = runGws([
      "drive",
      "files",
      "create",
      "--params",
      JSON.stringify(params),
      "--json",
      JSON.stringify(body),
      "--upload",
      localPath,
      "--upload-content-type",
      mimeFor(localPath),
    ]);
  }

  const file = parseJsonOutput(output);
  return {
    path: normalized,
    status: existing ? "updated" : "created",
    fileId: file.id,
    md5: file.md5Checksum,
    modifiedTime: file.modifiedTime,
    size: file.size,
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const rootFolder = resolveRootFolder(args);
  const results = DEFAULT_FILES.map((relativePath) =>
    createOrUpdateFile({
      relativePath,
      repoRoot: args.repoRoot,
      rootFolderId: rootFolder.id,
      dryRun: args.dryRun,
    }),
  );

  console.log(
    JSON.stringify(
      {
        rootFolder,
        dryRun: args.dryRun,
        results,
      },
      null,
      2,
    ),
  );
}

main();
