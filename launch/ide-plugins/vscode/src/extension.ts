// Synapse VS Code extension — thin wrapper around `synapse audit` and the
// FS watcher. The heavy lifting all lives in the Python SDK (`pip install
// synapse-protocol`); this extension is just glue + commands + status bar.
//
// Architecture:
//   - On activation: ensure `synapse` is on PATH (else show a one-click
//     install prompt).
//   - `Synapse: Audit current repo trace` → opens a quick-pick over JSON
//     trace files in the workspace, runs `synapse audit <path> --no-html
//     --json /tmp/...`, then opens the JSON in a new editor.
//   - `Synapse: Start FS watcher (this session)` → spawns
//     `python -m synapse.watchers.fs_watcher .` as a child process,
//     showing its log in an output channel. Tags writes with the
//     configured agentId.
//   - Status bar item: shows "Synapse: watching · 3 conflicts" when active.

import * as vscode from "vscode";
import * as cp from "child_process";
import * as path from "path";
import * as fs from "fs";

let watcherProc: cp.ChildProcess | undefined;
let outputChannel: vscode.OutputChannel;
let statusBar: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel("Synapse");
    statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = "$(circle-outline) Synapse";
    statusBar.tooltip = "Click to start FS watcher";
    statusBar.command = "synapse.startWatcher";
    statusBar.show();
    context.subscriptions.push(outputChannel, statusBar);

    context.subscriptions.push(
        vscode.commands.registerCommand("synapse.auditCurrentRepo", auditCurrentRepo),
        vscode.commands.registerCommand("synapse.startWatcher", startWatcher),
        vscode.commands.registerCommand("synapse.stopWatcher", stopWatcher),
        vscode.commands.registerCommand("synapse.showLastReport", showLastReport),
    );

    // Verify synapse is installed
    cp.exec(getSynapseCmd() + " --help", (err) => {
        if (err) {
            vscode.window.showWarningMessage(
                "Synapse CLI not found on PATH. Install with: pip install synapse-protocol",
                "Install Now",
            ).then(action => {
                if (action === "Install Now") {
                    const term = vscode.window.createTerminal("Synapse Install");
                    term.show();
                    term.sendText("pip install synapse-protocol");
                }
            });
        }
    });

    if (vscode.workspace.getConfiguration("synapse").get<boolean>("autoStartWatcherOnLaunch")) {
        startWatcher();
    }
}

export function deactivate() {
    stopWatcher();
}

function getSynapseCmd(): string {
    return vscode.workspace.getConfiguration("synapse").get<string>("synapseCmd") || "synapse";
}

function getAgentId(): string {
    return vscode.workspace.getConfiguration("synapse").get<string>("agentId") || "vscode-default";
}

function getSessionId(): string {
    return vscode.workspace.getConfiguration("synapse").get<string>("sessionId") || "vscode-default";
}

function getRepoRoot(): string | undefined {
    const folders = vscode.workspace.workspaceFolders;
    return folders && folders.length > 0 ? folders[0].uri.fsPath : undefined;
}

async function auditCurrentRepo() {
    const root = getRepoRoot();
    if (!root) {
        vscode.window.showErrorMessage("Synapse: open a workspace first.");
        return;
    }
    // Find candidate trace files
    const candidates = await vscode.workspace.findFiles(
        "**/*.{json,jsonl,ndjson}",
        "**/node_modules/**,**/__pycache__/**",
        50,
    );
    if (candidates.length === 0) {
        vscode.window.showInformationMessage(
            "Synapse: no .json / .jsonl trace files found in workspace.",
        );
        return;
    }
    const choice = await vscode.window.showQuickPick(
        candidates.map(c => ({
            label: path.relative(root, c.fsPath),
            uri: c.fsPath,
        })),
        { placeHolder: "Pick a trace file to audit" },
    );
    if (!choice) return;

    const outPath = path.join(root, ".synapse", "vscode-audit-result.json");
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    outputChannel.show(true);
    outputChannel.appendLine(`$ ${getSynapseCmd()} audit ${choice.label} --no-html --json ${outPath}`);
    cp.exec(
        `${getSynapseCmd()} audit "${choice.uri}" --no-html --json "${outPath}"`,
        async (err, stdout, stderr) => {
            outputChannel.appendLine(stdout);
            if (stderr) outputChannel.appendLine(stderr);
            if (err) {
                vscode.window.showErrorMessage(`Synapse audit failed: ${err.message}`);
                return;
            }
            const doc = await vscode.workspace.openTextDocument(outPath);
            await vscode.window.showTextDocument(doc);
        },
    );
}

function startWatcher() {
    if (watcherProc && !watcherProc.killed) {
        vscode.window.showInformationMessage("Synapse: watcher already running.");
        return;
    }
    const root = getRepoRoot();
    if (!root) {
        vscode.window.showErrorMessage("Synapse: open a workspace first.");
        return;
    }
    const env = { ...process.env, SYNAPSE_AGENT_ID: getAgentId(), SYNAPSE_SESSION_ID: getSessionId() };
    outputChannel.show(true);
    outputChannel.appendLine(
        `$ python -m synapse.watchers.fs_watcher . (agent=${getAgentId()}, session=${getSessionId()})`,
    );
    watcherProc = cp.spawn("python", ["-m", "synapse.watchers.fs_watcher", "."], {
        cwd: root, env, shell: true,
    });
    watcherProc.stdout?.on("data", (d: Buffer) => outputChannel.append(d.toString()));
    watcherProc.stderr?.on("data", (d: Buffer) => outputChannel.append(d.toString()));
    watcherProc.on("exit", (code) => {
        outputChannel.appendLine(`watcher exited (code=${code})`);
        statusBar.text = "$(circle-outline) Synapse";
        statusBar.tooltip = "Click to start FS watcher";
        statusBar.command = "synapse.startWatcher";
        watcherProc = undefined;
    });
    statusBar.text = "$(eye) Synapse: watching";
    statusBar.tooltip = "FS watcher active. Click to stop.";
    statusBar.command = "synapse.stopWatcher";
}

function stopWatcher() {
    if (watcherProc && !watcherProc.killed) {
        watcherProc.kill();
        outputChannel.appendLine("watcher stopped by user");
    }
    statusBar.text = "$(circle-outline) Synapse";
    statusBar.tooltip = "Click to start FS watcher";
    statusBar.command = "synapse.startWatcher";
    watcherProc = undefined;
}

async function showLastReport() {
    const root = getRepoRoot();
    if (!root) return;
    const reportPath = path.join(root, ".synapse", "vscode-audit-result.json");
    if (!fs.existsSync(reportPath)) {
        vscode.window.showInformationMessage("Synapse: no recent audit. Run 'Synapse: Audit current repo trace' first.");
        return;
    }
    const doc = await vscode.workspace.openTextDocument(reportPath);
    await vscode.window.showTextDocument(doc);
}
