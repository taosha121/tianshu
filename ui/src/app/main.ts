sap.ui.loader.config({
    shim: {
        "sap/galilei/core-min":      {},
        "sap/galilei/model-min":     { deps: ["sap/galilei/core-min"] },
        "sap/galilei/common.ui-min": { deps: ["sap/galilei/core-min"] },
        "sap/galilei/ui.symbol-min": { deps: ["sap/galilei/core-min", "sap/galilei/common.ui-min"] },
        "sap/galilei/ui.editor-min": { deps: ["sap/galilei/core-min", "sap/galilei/model-min",
                                               "sap/galilei/common.ui-min", "sap/galilei/ui.symbol-min"] }
    }
});

sap.ui.define([
    "sap/galilei/ui5/GalileiModel",
    "sap/galilei/ui5/Editor"
], function (_GalileiModel: unknown, Editor: typeof sap.galilei.ui5.Editor) {
    "use strict";

    const BACKEND = "http://localhost:8000";

    // ── Metamodel definitions ────────────────────────────────────────────

    const modelDefinition = {
        contents: {
            "agent.model": {
                classDefinition: "sap.galilei.model.Package",
                displayName: "Agent Model",
                namespaceName: "agent.model",
                classifiers: {
                    AgentModel: {
                        displayName: "Agent Model",
                        parent: "sap.galilei.model.Object",
                        references: {
                            agents: {
                                contentType: "agent.model.Agent",
                                isMany: true,
                                isContainment: true
                            }
                        }
                    },
                    Agent: {
                        displayName: "Agent",
                        parent: "sap.galilei.model.Object",
                        properties: {
                            agentId: { dataType: sap.galilei.model.dataTypes.gString },
                            type:    { dataType: sap.galilei.model.dataTypes.gString },
                            prompt:  { dataType: sap.galilei.model.dataTypes.gString }
                        }
                    }
                }
            }
        }
    };

    function makeSymbolDef(className: string, label: string, fill: string, stroke: string) {
        return {
            displayName: label,
            parent: "sap.galilei.ui.diagram.Symbol",
            properties: {
                [`${className}.layoutTemplate`]: {
                    name: "layoutTemplate",
                    dataType: sap.galilei.model.dataTypes.gBlob,
                    isCached: false,
                    get() {
                        return {
                            mainShape: [{
                                shape: "RoundedRectangle",
                                r: 8,
                                fill,
                                stroke,
                                strokeWidth: 2,
                                width: 160,
                                height: 60,
                                cursor: "pointer"
                            }],
                            contentShape: [{
                                shape: "Stack",
                                orientation: "vertical",
                                padding: 8,
                                shapes: [
                                    {
                                        shape: "Text",
                                        text: label,
                                        font: "bold 12px sans-serif",
                                        horizontalAlignment: "center"
                                    },
                                    {
                                        shape: "Text",
                                        text: "{object/agentId}",
                                        font: "11px sans-serif",
                                        horizontalAlignment: "center"
                                    }
                                ]
                            }]
                        };
                    }
                }
            },
            statics: {
                objectClass: { value: "agent.model.Agent" }
            }
        };
    }

    const diagramDefinition = {
        contents: {
            "agent.ui": {
                classDefinition: "sap.galilei.model.Package",
                displayName: "Agent Diagram",
                namespaceName: "agent.ui",
                classifiers: {
                    AgentDiagram: {
                        displayName: "Agent Diagram",
                        parent: "sap.galilei.ui.diagram.Diagram"
                    },
                    MainAgentSymbol: makeSymbolDef("MainAgentSymbol", "Main Agent", "#FFF3E0", "#E65100"),
                    SubAgentSymbol:  makeSymbolDef("SubAgentSymbol",  "Sub Agent",  "#E8F4FD", "#0070F2"),
                    DependencyLink: {
                        displayName: "Dependency",
                        parent: "sap.galilei.ui.diagram.LinkSymbol",
                        properties: {
                            "DependencyLink.layoutTemplate": {
                                name: "layoutTemplate",
                                dataType: sap.galilei.model.dataTypes.gBlob,
                                isCached: false,
                                get() {
                                    return {
                                        stroke: "#7a9abf",
                                        strokeWidth: 2,
                                        targetArrow: "Arrows.FilledEnd"
                                    };
                                }
                            }
                        }
                    }
                }
            }
        }
    };

    // ── State ────────────────────────────────────────────────────────────

    let metaResource: sap.galilei.model.Resource;
    let uiMetaResource: sap.galilei.model.Resource;
    let modelResource: sap.galilei.model.Resource;
    let nsModel: any;
    let nsUi: any;
    let agentModel: any;
    let diagram: any;
    let agentList: any[] = [];
    let agentContextMap: Record<string, { historyLen: number; estimatedTokens: number; maxTokens: number; willCompress: boolean }> = {};
    let symbolMap: Record<string, any> = {};
    let subAgentDepths: Record<string, number> = {};
    let subAgentDepthCounts: Record<number, number> = {};
    let editorControl: sap.galilei.ui5.Editor;
    let innerEditor: any = null;
    let selectedAgent: any = null;
    let activeEs: EventSource | null = null;
    let currentSessionId: string | null = null;

    const SYMBOL_W = 160;
    const SYMBOL_H = 60;
    const COL_W    = SYMBOL_W + 60;
    const ROW_H    = SYMBOL_H + 30;

    // ── Galilei init ─────────────────────────────────────────────────────

    function initGalilei() {
        sap.galilei.namespace("agent.model", function () {
            metaResource = new sap.galilei.model.Resource("agent.model.model");
            new sap.galilei.model.JSONReader().load(metaResource, modelDefinition);
        });
        nsModel = (window as any).agent.model;

        sap.galilei.namespace("agent.ui", function () {
            uiMetaResource = new sap.galilei.model.Resource("agent.ui.model");
            new sap.galilei.model.JSONReader().load(uiMetaResource, diagramDefinition);
        });
        nsUi = (window as any).agent.ui;

        modelResource = new sap.galilei.model.Resource("agent.model.instance");
        agentModel = new nsModel.AgentModel(modelResource, {});

        (sap as any).galilei.ui.editor.defineDiagramEditorExtension({
            fullClassName: "agent.ui.EditorExtension",
            properties: {},
            methods: {}
        });

        editorControl = new Editor({ height: "100%", width: "100%" });
        editorControl.setEditorExtensionClassName("agent.ui.EditorExtension");
        editorControl.placeAt("canvas");
        editorControl.addEventDelegate({
            onAfterRendering() { waitForInnerEditor(); }
        });
    }

    function waitForInnerEditor() {
        const editor = editorControl.getInnerEditor?.() ?? null;
        if (!editor) { setTimeout(waitForInnerEditor, 50); return; }
        if (editor === innerEditor) return;
        innerEditor = editor;

        diagram = new nsUi.AgentDiagram(modelResource, {});
        editorControl.setDiagram(diagram);
        innerEditor.isReadOnly = false;

        sap.galilei.core.Event.subscribe(
            "symbol.selected",
            (data: any) => {
                const obj = data?.object ?? data?.sourceSymbol?.object;
                if (obj) onSymbolSelected({ object: obj, sourceSymbol: data?.sourceSymbol });
            },
            {},
            innerEditor
        );
        sap.galilei.core.Event.subscribe(
            "symbol.unselected",
            () => onSymbolUnselected(),
            {},
            innerEditor
        );
    }

    // ── Canvas ops ───────────────────────────────────────────────────────

    function addAgent(id: string, type: string, prompt: string, dependsOn?: string[]) {
        const agent = new nsModel.Agent(modelResource, { agentId: id, type, prompt });
        agentModel.agents.push(agent);
        agentList.push(agent);

        let x: number, y: number;
        if (type === "main") {
            x = 100; y = 40;
        } else {
            let depth = 0;
            if (dependsOn?.length) {
                for (const dep of dependsOn) {
                    const d = (subAgentDepths[dep] ?? 0) + 1;
                    if (d > depth) depth = d;
                }
            }
            subAgentDepths[id] = depth;
            const row = subAgentDepthCounts[depth] ?? 0;
            subAgentDepthCounts[depth] = row + 1;
            x = 20 + depth * COL_W;
            y = 160 + row * ROW_H;
        }

        const SymbolClass = type === "main" ? nsUi.MainAgentSymbol : nsUi.SubAgentSymbol;
        const symbol = new SymbolClass(modelResource, { object: agent, x, y });
        diagram.symbols.push(symbol);
        innerEditor?.drawSymbol?.(symbol);
        innerEditor?.registerSymbolEvents?.(symbol);
        symbolMap[id] = symbol;

        if (dependsOn?.length) {
            for (const srcId of dependsOn) {
                const srcSymbol = symbolMap[srcId];
                if (!srcSymbol) continue;
                try {
                    const link = new nsUi.DependencyLink(modelResource, { sourceSymbol: srcSymbol, targetSymbol: symbol });
                    diagram.symbols.push(link);
                    innerEditor?.drawSymbol?.(link);
                } catch (e) {
                    console.warn("DependencyLink failed:", e);
                }
            }
        }
    }

    function updatePrompt(agentId: string, content: unknown, context?: { historyLen: number; estimatedTokens: number; maxTokens: number; willCompress: boolean }) {
        const agent = agentList.find(a => a.agentId === agentId);
        if (!agent) return;
        agent.prompt = typeof content === "string" ? content : JSON.stringify(content, null, 2);
        if (context) agentContextMap[agentId] = context;
        if (selectedAgent?.agentId === agentId) renderPanel(selectedAgent);
    }

    function resetCanvas() {
        subAgentDepths = {};
        subAgentDepthCounts = {};
        agentList = [];
        agentContextMap = {};
        symbolMap = {};
        agentModel = new nsModel.AgentModel(modelResource, {});
        diagram = new nsUi.AgentDiagram(modelResource, {});
        if (innerEditor) editorControl.setDiagram(diagram);
        selectedAgent = null;
        clearPanel();
    }

    // ── Property panel ───────────────────────────────────────────────────

    function renderPanel(agent: any) {
        (document.getElementById("prop-id")     as HTMLElement).textContent = agent.agentId || "";
        (document.getElementById("prop-type")   as HTMLElement).textContent = agent.type    || "";
        (document.getElementById("prop-prompt") as HTMLElement).textContent = agent.prompt  || "";

        const ctx = agentContextMap[agent.agentId];
        const ctxEl = document.getElementById("prop-context") as HTMLElement;
        if (ctx) {
            const pct = Math.round(ctx.estimatedTokens / ctx.maxTokens * 100);
            const color = ctx.willCompress ? "#d9534f" : pct > 50 ? "#e6a817" : "#2e8b57";
            const badge = ctx.willCompress ? " ⚠ compresses next" : "";
            ctxEl.innerHTML =
                `<span style="color:${color};font-weight:600">${ctx.estimatedTokens.toLocaleString()} tok</span>` +
                ` / ${ctx.maxTokens.toLocaleString()} (${pct}%)${badge ? `<br><span style="color:#d9534f;font-size:11px">${badge}</span>` : ""}<br>` +
                `<span style="color:#999">${ctx.historyLen} messages</span>`;
        } else {
            ctxEl.textContent = "—";
        }

        (document.getElementById("panel-placeholder") as HTMLElement).style.display = "none";
        (document.getElementById("panel-props")       as HTMLElement).style.display = "block";
    }

    function clearPanel() {
        (document.getElementById("panel-placeholder") as HTMLElement).style.display = "block";
        (document.getElementById("panel-props")       as HTMLElement).style.display = "none";
    }

    function onSymbolSelected(event: any) {
        const obj = event?.object ?? event?.sourceSymbol?.object;
        if (!obj) return;
        selectedAgent = obj;
        renderPanel(selectedAgent);
    }

    function onSymbolUnselected() {
        selectedAgent = null;
        clearPanel();
    }

    // ── Chat output ──────────────────────────────────────────────────────

    function appendOutput(text: string, cls: string) {
        const out = document.getElementById("chat-output")!;
        const div = document.createElement("div");
        div.className = cls;
        div.textContent = text;
        out.appendChild(div);
        out.scrollTop = out.scrollHeight;
    }

    function showLoading() {
        const out = document.getElementById("chat-output")!;
        const div = document.createElement("div");
        div.id = "chat-loading";
        div.className = "msg-loading";
        div.innerHTML = "<span></span><span></span><span></span>";
        out.appendChild(div);
        out.scrollTop = out.scrollHeight;
    }

    function hideLoading() {
        document.getElementById("chat-loading")?.remove();
    }

    // ── Backend SSE ──────────────────────────────────────────────────────

    function submitCommand() {
        const input = document.getElementById("command-input") as HTMLTextAreaElement;
        const command = input.value.trim();
        if (!command) return;
        input.value = "";

        activeEs?.close();
        activeEs = null;
        appendOutput(command, "msg-user");
        showLoading();

        fetch(`${BACKEND}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command, sessionId: currentSessionId })
        })
        .then(r => r.json())
        .then((data: { runId: string; sessionId: string; isNewSession: boolean }) => {
            if (data.isNewSession) resetCanvas();
            currentSessionId = data.sessionId;
            const es = new EventSource(`${BACKEND}/stream/${data.runId}`);
            activeEs = es;
            es.onmessage = (e: MessageEvent) => {
                const evt = JSON.parse(e.data);
                if (evt.type === "agent_created") {
                    try { addAgent(evt.agentId, evt.agentType, "", evt.dependsOn); } catch (_) {}
                    appendOutput(`agent ${evt.agentId} created (${evt.agentType})`, "msg-event agent-created");
                } else if (evt.type === "prompt_updated") {
                    updatePrompt(evt.agentId, evt.prompt, evt.context);
                } else if (evt.type === "result") {
                    hideLoading();
                    appendOutput(evt.text, "msg-agent");
                } else if (evt.type === "done") {
                    es.close();
                    activeEs = null;
                }
            };
            es.onerror = () => { hideLoading(); es.close(); activeEs = null; };
        })
        .catch((err: unknown) => { hideLoading(); console.error("run failed:", err); });
    }

    // ── Wire up ──────────────────────────────────────────────────────────

    initGalilei();

    fetch(`${BACKEND}/info`)
        .then(r => r.json())
        .then((data: { cwd: string }) => {
            const el = document.getElementById("titlebar-project");
            if (el) el.textContent = data.cwd;
        })
        .catch(() => {});

    document.getElementById("test-links-btn")!.addEventListener("click", () => {
        console.log("nsUi keys:", Object.keys(nsUi || {}));
        console.log("sap.galilei.ui.diagram:", (sap as any).galilei?.ui?.diagram);
        resetCanvas();
        addAgent("main-1", "main", "main agent");
        setTimeout(() => {
            addAgent("step-1", "sub", "step 1");
            addAgent("step-2", "sub", "step 2", ["step-1"]);
            addAgent("step-3", "sub", "step 3", ["step-1"]);
            setTimeout(() => addAgent("step-4", "sub", "step 4", ["step-2", "step-3"]), 100);
        }, 200);
    });

    (document.getElementById("command-input") as HTMLTextAreaElement)
        .addEventListener("keydown", (e: KeyboardEvent) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitCommand(); }
        });
    document.getElementById("close-panel-btn")?.addEventListener("click", clearPanel);
});
