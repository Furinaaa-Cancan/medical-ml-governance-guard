import * as vscode from "vscode";
import { spawn } from "child_process";

interface SarifResult {
  ruleId: string;
  level: string;
  message: { text: string };
  locations: Array<{
    physicalLocation: {
      artifactLocation: { uri: string };
      region: {
        startLine: number;
        startColumn: number;
        endLine?: number;
        endColumn?: number;
      };
    };
  }>;
  fixes?: Array<{ description: { text: string } }>;
}

interface SarifRun {
  tool: { driver: { rules: Array<{ id: string; shortDescription: { text: string } }> } };
  results: SarifResult[];
}

interface SarifReport {
  version: string;
  runs: SarifRun[];
}

const DIAG_COLLECTION_NAME = "mlgg-lint";
let diagnosticCollection: vscode.DiagnosticCollection;

export function activate(context: vscode.ExtensionContext): void {
  diagnosticCollection = vscode.languages.createDiagnosticCollection(DIAG_COLLECTION_NAME);
  context.subscriptions.push(diagnosticCollection);

  // Run on save
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const config = vscode.workspace.getConfiguration("mlgg-lint");
      if (config.get<boolean>("enable") && config.get<boolean>("runOnSave") && doc.languageId === "python") {
        lintDocument(doc);
      }
    })
  );

  // Run on open
  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((doc) => {
      const config = vscode.workspace.getConfiguration("mlgg-lint");
      if (config.get<boolean>("enable") && config.get<boolean>("runOnOpen") && doc.languageId === "python") {
        lintDocument(doc);
      }
    })
  );

  // Run on active editor change
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) {
        const config = vscode.workspace.getConfiguration("mlgg-lint");
        if (config.get<boolean>("enable") && editor.document.languageId === "python") {
          lintDocument(editor.document);
        }
      }
    })
  );

  // Manual command
  context.subscriptions.push(
    vscode.commands.registerCommand("mlgg-lint.check", () => {
      const editor = vscode.window.activeTextEditor;
      if (editor && editor.document.languageId === "python") {
        lintDocument(editor.document);
      }
    })
  );

  // Lint all open Python files on activation
  vscode.workspace.textDocuments.forEach((doc) => {
    if (doc.languageId === "python") {
      const config = vscode.workspace.getConfiguration("mlgg-lint");
      if (config.get<boolean>("enable")) {
        lintDocument(doc);
      }
    }
  });
}

function lintDocument(document: vscode.TextDocument): void {
  const config = vscode.workspace.getConfiguration("mlgg-lint");
  const pythonPath = config.get<string>("pythonPath") || "python3";
  const severity = config.get<string>("severity") || "info";
  const disableRules = config.get<string[]>("disableRules") || [];

  const args = ["-m", "mlgg_lint", "check", document.uri.fsPath, "--format", "sarif", "--severity", severity];

  if (disableRules.length > 0) {
    args.push("--disable", disableRules.join(","));
  }

  const proc = spawn(pythonPath, args, {
    cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
  });

  let stdout = "";
  let stderr = "";

  proc.stdout.on("data", (data: Buffer) => {
    stdout += data.toString();
  });

  proc.stderr.on("data", (data: Buffer) => {
    stderr += data.toString();
  });

  proc.on("close", () => {
    if (!stdout.trim()) {
      diagnosticCollection.set(document.uri, []);
      return;
    }

    try {
      const sarif: SarifReport = JSON.parse(stdout);
      const diagnostics = parseSarif(sarif, document);
      diagnosticCollection.set(document.uri, diagnostics);
    } catch {
      console.error("mlgg-lint: failed to parse SARIF output", stderr);
    }
  });

  proc.on("error", (err: Error) => {
    console.error("mlgg-lint: failed to spawn process", err.message);
  });
}

function parseSarif(sarif: SarifReport, document: vscode.TextDocument): vscode.Diagnostic[] {
  const diagnostics: vscode.Diagnostic[] = [];

  for (const run of sarif.runs) {
    for (const result of run.results) {
      const loc = result.locations?.[0]?.physicalLocation;
      if (!loc) continue;

      const region = loc.region;
      const lastLine = document.lineCount - 1;
      const startLine = Math.min(Math.max((region.startLine || 1) - 1, 0), lastLine);
      const startCol = Math.max((region.startColumn || 1) - 1, 0);
      const endLine = region.endLine
        ? Math.min(region.endLine - 1, lastLine)
        : startLine;
      let endCol: number;
      try {
        endCol = region.endColumn
          ? region.endColumn - 1
          : document.lineAt(endLine).text.length;
      } catch {
        endCol = 0;
      }

      const range = new vscode.Range(startLine, startCol, endLine, endCol);
      const severity = mapSeverity(result.level);

      const diag = new vscode.Diagnostic(range, result.message.text, severity);
      diag.source = "mlgg-lint";
      diag.code = result.ruleId;

      diagnostics.push(diag);
    }
  }

  return diagnostics;
}

function mapSeverity(level: string): vscode.DiagnosticSeverity {
  switch (level) {
    case "error":
      return vscode.DiagnosticSeverity.Error;
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "note":
    default:
      return vscode.DiagnosticSeverity.Information;
  }
}

export function deactivate(): void {
  diagnosticCollection?.dispose();
}
