(() => {
    "use strict";

    const listeners = new Set();
    const state = {
        selection: null,
        infrastructure: null,
        infrastructureStatus: "idle",
        infrastructureError: null,
    };

    function snapshot() {
        return {
            selection: state.selection ? { ...state.selection } : null,
            infrastructure: state.infrastructure,
            infrastructureStatus: state.infrastructureStatus,
            infrastructureError: state.infrastructureError,
        };
    }

    function emit() {
        const current = snapshot();
        listeners.forEach((listener) => listener(current));
        window.dispatchEvent(new CustomEvent("capivara:dashboard-state", { detail: current }));
    }

    function setSelection(selection) {
        state.selection = selection ? {
            type: selection.type,
            id: selection.id,
            name: selection.name || "",
        } : null;
        emit();
    }

    function setInfrastructure(data) {
        state.infrastructure = data;
        state.infrastructureStatus = "ready";
        state.infrastructureError = null;
        emit();
    }

    function setInfrastructureLoading() {
        state.infrastructureStatus = "loading";
        state.infrastructureError = null;
        emit();
    }

    function setInfrastructureError(error) {
        state.infrastructureStatus = "error";
        state.infrastructureError = String(error || "Falha ao carregar infraestrutura.");
        emit();
    }

    function subscribe(listener) {
        listeners.add(listener);
        listener(snapshot());
        return () => listeners.delete(listener);
    }

    window.CapivaraDashboardState = {
        get: snapshot,
        subscribe,
        setSelection,
        setInfrastructure,
        setInfrastructureLoading,
        setInfrastructureError,
    };
})();