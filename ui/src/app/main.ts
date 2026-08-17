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
                    SubAgentSymbol:  makeSymbolDef("SubAgentSymbol",  "Sub Agent",  "#E8F4FD", "#0070F2")
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
    let editorControl: sap.galilei.ui5.Editor;
    let innerEditor: any = null;
    let selectedAgent: any = null;
    let subAgentCount = 0;
    let activeEs: EventSource | null = null;

    const SYMBOL_W = 160;
    const H_GAP    = 40;

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

    function addAgent(id: string, type: string, prompt: string) {
        const agent = new nsModel.Agent(modelResource, { agentId: id, type, prompt });
        agentModel.agents.push(agent);
        agentList.push(agent);

        const x = type === "main" ? 300 : 60 + subAgentCount++ * (SYMBOL_W + H_GAP);
        const y = type === "main" ? 60 : 200;

        const SymbolClass = type === "main" ? nsUi.MainAgentSymbol : nsUi.SubAgentSymbol;
        const symbol = new SymbolClass(modelResource, { object: agent, x, y });
        diagram.symbols.push(symbol);
        innerEditor?.drawSymbol?.(symbol);
        innerEditor?.registerSymbolEvents?.(symbol);
    }

    function updatePrompt(agentId: string, content: unknown) {
        const agent = agentList.find(a => a.agentId === agentId);
        if (!agent) return;
        agent.prompt = typeof content === "string" ? content : JSON.stringify(content, null, 2);
        if (selectedAgent?.agentId === agentId) renderPanel(selectedAgent);
    }

    function resetCanvas() {
        subAgentCount = 0;
        agentList = [];
        agentModel = new nsModel.AgentModel(modelResource, {});
        diagram = new nsUi.AgentDiagram(modelResource, {});
        if (innerEditor) editorControl.setDiagram(diagram);
        selectedAgent = null;
        closePanel();
    }

    // ── Property panel ───────────────────────────────────────────────────

    function renderPanel(agent: any) {
        (document.getElementById("panel-title")  as HTMLElement).textContent = agent.agentId || "";
        (document.getElementById("prop-type")    as HTMLElement).textContent = agent.type    || "";
        (document.getElementById("prop-prompt")  as HTMLElement).textContent = agent.prompt  || "";
    }

    function openPanel()  { (document.getElementById("property-panel") as HTMLElement).style.display = "flex"; }
    function closePanel() { (document.getElementById("property-panel") as HTMLElement).style.display = "none"; }

    function onSymbolSelected(event: any) {
        const obj = event?.object ?? event?.sourceSymbol?.object;
        if (!obj) return;
        selectedAgent = obj;
        renderPanel(selectedAgent);
        openPanel();
    }

    function onSymbolUnselected() {
        selectedAgent = null;
        closePanel();
    }

    // ── Backend SSE ──────────────────────────────────────────────────────

    function submitCommand() {
        const input = document.getElementById("command-input") as HTMLInputElement;
        const command = input.value.trim();
        if (!command) return;

        activeEs?.close();
        activeEs = null;
        resetCanvas();

        fetch(`${BACKEND}/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command })
        })
        .then(r => r.json())
        .then((data: { runId: string }) => {
            const es = new EventSource(`${BACKEND}/stream/${data.runId}`);
            activeEs = es;
            es.onmessage = (e: MessageEvent) => {
                const evt = JSON.parse(e.data);
                if      (evt.type === "agent_created")   addAgent(evt.agentId, evt.agentType, "");
                else if (evt.type === "prompt_updated")  updatePrompt(evt.agentId, evt.prompt);
                else if (evt.type === "done")            { es.close(); activeEs = null; }
            };
            es.onerror = () => { es.close(); activeEs = null; };
        })
        .catch((err: unknown) => console.error("run failed:", err));
    }

    // ── Wire up ──────────────────────────────────────────────────────────

    initGalilei();

    document.getElementById("submit-btn")!.addEventListener("click", submitCommand);
    (document.getElementById("command-input") as HTMLInputElement)
        .addEventListener("keydown", (e: KeyboardEvent) => { if (e.key === "Enter") submitCommand(); });
    document.getElementById("close-panel-btn")!.addEventListener("click", closePanel);
    document.getElementById("test-btn")!.addEventListener("click", () => {
        resetCanvas();
        addAgent("main-1", "main", "You are the main agent.");
        setTimeout(() => addAgent("sub-1", "sub", "Sub agent prompt A."), 300);
        setTimeout(() => addAgent("sub-2", "sub", "Sub agent prompt B."), 600);
    });
    document.getElementById("update-btn")!.addEventListener("click", () => {
        const main = agentList.find(a => a.agentId === "main-1");
        if (!main) return;
        const firstSub = agentList.find(a => a.type === "sub");
        if (!firstSub) return;
        updatePrompt(firstSub.agentId, "Updated prompt at " + new Date().toLocaleTimeString());
    });
});
