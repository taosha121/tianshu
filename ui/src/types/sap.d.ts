declare namespace sap {
    namespace ui {
        function define(deps: string[], factory: (...args: any[]) => void): void;
        function define(id: string, deps: string[], factory: (...args: any[]) => void): void;
        function require(deps: string[], callback: (...args: any[]) => void): void;
        function getCore(): { attachInit(callback: () => void): void };
        namespace loader {
            function config(settings: {
                shim?: Record<string, { deps?: string[]; exports?: string }>;
                [key: string]: any;
            }): void;
        }
    }

    namespace galilei {
        function namespace(ns: string, callback?: (this: any) => void): void;

        namespace model {
            namespace dataTypes {
                const gString: any;
                const gBool: any;
                const gInteger: any;
                const gBlob: any;
            }
            class Resource { constructor(id?: string); }
            class JSONReader { load(resource: Resource, definition: object): void; }
            function getClass(name: string, resource: Resource): {
                create(resource: Resource, props: Record<string, unknown>): any;
            } | undefined;
        }

        namespace ui5 {
            class Editor {
                constructor(options: { height: string; width: string; viewBackgroundFill?: string; pageBackgroundFill?: string; [key: string]: any });
                placeAt(containerId: string): void;
                addEventDelegate(delegate: { onAfterRendering(): void }): void;
                setEditorExtensionClassName(className: string): void;
                getInnerEditor?(): any;
                setDiagram(diagram: any): void;
            }
        }

        namespace core {
            namespace Event {
                function subscribe(event: string, callback: (evt: any) => void, scope?: any, target?: any): void;
            }
        }
    }
}
