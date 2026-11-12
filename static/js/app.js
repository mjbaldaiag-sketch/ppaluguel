(function () {
    "use strict";

    const moduleConfig = {
        proprietarios: {
            endpoint: "/api/proprietarios",
            title: "Proprietários",
            singular: "proprietário",
            description: "Gerencie as pessoas responsáveis pelos seus imóveis.",
            empty: "Ainda não há proprietários cadastrados.",
            emptyDescription: "Cadastre o primeiro proprietário para começar a relacionar seus imóveis.",
            headers: ["Proprietário", "CPF", "Contato", "E-mail"],
        },
        inquilinos: {
            endpoint: "/api/inquilinos-clientes",
            title: "Inquilinos / Clientes",
            singular: "inquilino/cliente",
            description: "Centralize os dados de inquilinos e clientes.",
            empty: "Ainda não há inquilinos ou clientes cadastrados.",
            emptyDescription: "Cadastre seu primeiro inquilino ou cliente para manter os contatos organizados.",
            headers: ["Inquilino / Cliente", "CPF", "Contato", "E-mail"],
        },
        imoveis: {
            endpoint: "/api/imoveis",
            title: "Imóveis",
            singular: "imóvel",
            description: "Acompanhe seus imóveis, responsáveis e dados de consumo.",
            empty: "Ainda não há imóveis cadastrados.",
            emptyDescription: "Cadastre um proprietário primeiro e depois adicione o seu primeiro imóvel.",
            headers: ["Imóvel", "Responsável", "Endereço", "Aluguel", "Energia solar"],
        },
    };

    const states = [
        ["AC", "Acre"], ["AL", "Alagoas"], ["AP", "Amapá"], ["AM", "Amazonas"],
        ["BA", "Bahia"], ["CE", "Ceará"], ["DF", "Distrito Federal"], ["ES", "Espírito Santo"],
        ["GO", "Goiás"], ["MA", "Maranhão"], ["MT", "Mato Grosso"], ["MS", "Mato Grosso do Sul"],
        ["MG", "Minas Gerais"], ["PA", "Pará"], ["PB", "Paraíba"], ["PR", "Paraná"],
        ["PE", "Pernambuco"], ["PI", "Piauí"], ["RJ", "Rio de Janeiro"], ["RN", "Rio Grande do Norte"],
        ["RS", "Rio Grande do Sul"], ["RO", "Rondônia"], ["RR", "Roraima"], ["SC", "Santa Catarina"],
        ["SP", "São Paulo"], ["SE", "Sergipe"], ["TO", "Tocantins"],
    ];

    const maritalStatuses = [
        ["SOLTEIRO(A)", "Solteiro(a)"],
        ["CASADO(A)", "Casado(a)"],
        ["DIVORCIADO(A)", "Divorciado(a)"],
        ["VIÚVO(A)", "Viúvo(a)"],
        ["SEPARADO(A)", "Separado(a)"],
        ["UNIÃO ESTÁVEL", "União estável"],
    ];
    const VIA_CEP_FIELDS = ["endereco", "estado", "cidade", "bairro"];

    const state = {
        module: "proprietarios",
        records: [],
        editingId: null,
        modalMode: "create",
        modalModule: "proprietarios",
        owners: [],
        viacep: {
            lastCep: "",
            requestId: 0,
            controller: null,
            autoValues: {},
            dirtyFields: {},
        },
    };

    const elements = {};

    document.addEventListener("DOMContentLoaded", init);

    async function init() {
        cacheElements();
        populateStaticSelects();
        bindEvents();

        await Promise.all([
            loadDashboard(),
            loadOwners(),
            loadModule(state.module),
        ]);
    }

    function cacheElements() {
        elements.sidebar = document.getElementById("sidebar");
        elements.sidebarBackdrop = document.getElementById("sidebar-backdrop");
        elements.menuToggle = document.getElementById("menu-toggle");
        elements.navItems = document.querySelectorAll("[data-module]");
        elements.breadcrumbModule = document.getElementById("breadcrumb-module");
        elements.moduleTitle = document.getElementById("module-title");
        elements.moduleDescription = document.getElementById("module-description");
        elements.newRecordButton = document.getElementById("new-record-button");
        elements.newRecordLabel = document.getElementById("new-record-label");
        elements.refreshButton = document.getElementById("refresh-button");
        elements.emptyAction = document.getElementById("empty-action");
        elements.emptyState = document.getElementById("empty-state");
        elements.emptyTitle = document.getElementById("empty-title");
        elements.emptyDescription = document.getElementById("empty-description");
        elements.loadingState = document.getElementById("loading-state");
        elements.recordsHead = document.getElementById("records-head");
        elements.recordsBody = document.getElementById("records-body");
        elements.recordCount = document.getElementById("record-count");
        elements.modal = document.getElementById("record-modal");
        elements.modalTitle = document.getElementById("modal-title");
        elements.modalDescription = document.getElementById("modal-description");
        elements.modalEyebrow = document.getElementById("modal-eyebrow");
        elements.modalClose = document.getElementById("modal-close");
        elements.modalCancel = document.getElementById("modal-cancel");
        elements.modalSubmit = document.getElementById("modal-submit");
        elements.form = document.getElementById("record-form");
        elements.toastRegion = document.getElementById("toast-region");
    }

    function bindEvents() {
        elements.navItems.forEach((item) => {
            item.addEventListener("click", () => {
                if (!item.dataset.module || !moduleConfig[item.dataset.module]) {
                    return;
                }
                setModule(item.dataset.module);
                closeSidebar();
            });
        });

        elements.newRecordButton.addEventListener("click", () => openModal("create", null, elements.newRecordButton.dataset.module || state.module));
        elements.emptyAction.addEventListener("click", () => openModal("create", null, elements.emptyAction.dataset.module || state.module));
        elements.refreshButton.addEventListener("click", () => refreshCurrentModule());
        elements.form.addEventListener("submit", handleFormSubmit);
        elements.modalClose.addEventListener("click", closeModal);
        elements.modalCancel.addEventListener("click", closeModal);
        elements.modal.addEventListener("click", (event) => {
            if (event.target === elements.modal) {
                closeModal();
            }
        });
        elements.recordsBody.addEventListener("click", handleTableAction);
        elements.menuToggle.addEventListener("click", toggleSidebar);
        elements.sidebarBackdrop.addEventListener("click", closeSidebar);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                if (!elements.modal.hidden) {
                    closeModal();
                } else {
                    closeSidebar();
                }
            }
        });

        elements.form.querySelectorAll("[data-mask]").forEach((input) => {
            input.addEventListener("input", () => {
                applyMask(input);
                if (input.dataset.mask === "cep") {
                    handleCepInput(input);
                }
            });
        });
        elements.form.querySelectorAll('input:not([data-mask]):not([data-field="email"])').forEach((input) => {
            input.addEventListener("input", () => {
                input.value = input.value.toUpperCase();
            });
        });
        elements.form.querySelectorAll("[data-field]").forEach((field) => {
            if (!VIA_CEP_FIELDS.includes(field.dataset.field)) {
                return;
            }
            const markAsManual = () => {
                state.viacep.dirtyFields[field.dataset.field] = true;
            };
            field.addEventListener("input", markAsManual);
            field.addEventListener("change", markAsManual);
        });
    }

    function populateStaticSelects() {
        document.querySelectorAll('[data-field="estado_civil"]').forEach((select) => {
            maritalStatuses.forEach(([value, label]) => select.add(new Option(label, value)));
        });

        const stateSelect = document.querySelector('[data-form-section="imoveis"] [data-field="estado"]');
        states.forEach(([abbreviation, name]) => stateSelect.add(new Option(`${abbreviation} — ${name}`, abbreviation)));
    }

    async function loadDashboard() {
        try {
            const data = await apiFetch("/api/dashboard");
            const counts = data.counts || {};
            document.getElementById("count-proprietarios").textContent = counts.proprietarios || 0;
            document.getElementById("count-inquilinos").textContent = counts.inquilinos_clientes || 0;
            document.getElementById("count-imoveis").textContent = counts.imoveis || 0;
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function loadOwners() {
        try {
            state.owners = await apiFetch("/api/proprietarios");
            populateOwnerSelect();
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function loadModule(moduleName) {
        const config = moduleConfig[moduleName];
        if (!config) {
            return;
        }

        setLoading(true);
        try {
            state.records = await apiFetch(config.endpoint);
            renderTable();
        } catch (error) {
            state.records = [];
            renderTable();
            showToast(error.message, "error");
        } finally {
            setLoading(false);
        }
    }

    async function refreshCurrentModule() {
        await Promise.all([loadDashboard(), loadModule(state.module)]);
        if (state.module === "imoveis") {
            await loadOwners();
        }
    }

    function setModule(moduleName) {
        if (state.module === moduleName) {
            elements.newRecordButton.dataset.module = moduleName;
            elements.emptyAction.dataset.module = moduleName;
            return;
        }
        state.module = moduleName;
        const config = moduleConfig[moduleName];
        elements.newRecordButton.dataset.module = moduleName;
        elements.emptyAction.dataset.module = moduleName;
        elements.navItems.forEach((item) => item.classList.toggle("is-active", item.dataset.module === moduleName));
        elements.breadcrumbModule.textContent = config.title;
        elements.moduleTitle.textContent = config.title;
        elements.moduleDescription.textContent = config.description;
        elements.newRecordLabel.textContent = `Novo ${config.singular}`;
        loadModule(moduleName);
    }

    function setLoading(isLoading) {
        elements.loadingState.hidden = !isLoading;
        if (isLoading) {
            elements.emptyState.hidden = true;
        }
    }

    function renderTable() {
        const config = moduleConfig[state.module];
        elements.recordsHead.innerHTML = `<tr>${config.headers.map((header) => `<th>${header}</th>`).join("")}<th class="actions-cell">Ações</th></tr>`;
        elements.recordsBody.innerHTML = state.records.map((record) => renderRow(record)).join("");
        elements.recordCount.textContent = `${state.records.length} ${state.records.length === 1 ? "registro" : "registros"}`;
        elements.emptyTitle.textContent = config.empty;
        elements.emptyDescription.textContent = config.emptyDescription;
        elements.emptyState.hidden = state.records.length !== 0;
    }

    function renderRow(record) {
        if (state.module === "imoveis") {
            const location = [
                record.endereco,
                record.numero ? `Nº ${record.numero}` : "",
                record.cidade,
                record.estado,
            ].filter(Boolean).join(" · ") || "Endereço não informado";
            const solar = Number(record.energia_solar) === 1;
            return `<tr>
                <td><div class="property-cell"><span class="row-avatar property">⌂</span><span>${escapeHtml(record.apelido)}<small class="subtle-text">Código #${record.id}</small></span></div></td>
                <td>${escapeHtml(record.responsavel_nome || "—")}</td>
                <td>${escapeHtml(location)}</td>
                <td>${formatCurrency(record.aluguel)}</td>
                <td><span class="status-pill ${solar ? "" : "off"}">${solar ? "Sim" : "Não"}</span></td>
                <td class="actions-cell">${actionButtons(record.id)}</td>
            </tr>`;
        }

        return `<tr>
            <td><div class="person-cell"><span class="row-avatar">${initials(record.nome_completo)}</span><span>${escapeHtml(record.nome_completo)}<small class="subtle-text">Código #${record.id}</small></span></div></td>
            <td>${formatCpf(record.cpf)}</td>
            <td>${formatPhone(record.contato)}</td>
            <td>${escapeHtml(record.email || "—")}</td>
            <td class="actions-cell">${actionButtons(record.id)}</td>
        </tr>`;
    }

    function actionButtons(id) {
        return `<button class="row-action" type="button" data-action="view" data-id="${id}">Visualizar</button>
            <button class="row-action" type="button" data-action="edit" data-id="${id}">Editar</button>
            <button class="row-action delete" type="button" data-action="delete" data-id="${id}">Excluir</button>`;
    }

    async function handleTableAction(event) {
        const button = event.target.closest("[data-action]");
        if (!button) {
            return;
        }
        const id = Number(button.dataset.id);
        const record = state.records.find((item) => Number(item.id) === id);
        if (!record) {
            return;
        }

        if (button.dataset.action === "view") {
            openModal("view", record);
        } else if (button.dataset.action === "edit") {
            openModal("edit", record);
        } else if (button.dataset.action === "delete") {
            await deleteRecord(id, record);
        }
    }

    async function deleteRecord(id, record) {
        const description = state.module === "imoveis" ? record.apelido : record.nome_completo;
        if (!window.confirm(`Excluir “${description}”? Esta ação não poderá ser desfeita.`)) {
            return;
        }

        try {
            await apiFetch(`${moduleConfig[state.module].endpoint}/${id}`, { method: "DELETE" });
            showToast(`${moduleConfig[state.module].singular} excluído com sucesso.`);
            await refreshCurrentModule();
            if (state.module === "proprietarios") {
                await loadOwners();
            }
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function openModal(mode, record = null, moduleName = state.module) {
        const modalModule = moduleConfig[moduleName] ? moduleName : state.module;
        state.modalModule = modalModule;
        if (modalModule === "imoveis") {
            await loadOwners();
        }

        state.modalMode = mode;
        state.editingId = record ? record.id : null;
        const config = moduleConfig[modalModule];
        const isView = mode === "view";
        const isEdit = mode === "edit";
        const section = getActiveSection();

        document.querySelectorAll("[data-form-section]").forEach((formSection) => {
            formSection.hidden = formSection !== section;
        });

        clearForm(section);
        if (record) {
            fillForm(section, record);
        }
        setFormDisabled(section, isView);

        elements.modalEyebrow.textContent = isView ? "Detalhes" : isEdit ? "Edição" : "Cadastro";
        elements.modalTitle.textContent = isView ? `Detalhes do ${config.singular}` : isEdit ? `Editar ${config.singular}` : `Novo ${config.singular}`;
        elements.modalDescription.textContent = isView ? "Consulte as informações deste registro." : "Preencha os dados abaixo para continuar.";
        elements.modalSubmit.hidden = isView;
        elements.modalCancel.textContent = isView ? "Fechar" : "Cancelar";
        elements.modal.hidden = false;
        document.body.style.overflow = "hidden";

        window.setTimeout(() => {
            const firstField = section.querySelector("input, select");
            if (firstField && !isView) {
                firstField.focus();
            }
        }, 50);
    }

    function closeModal() {
        elements.modal.hidden = true;
        document.body.style.overflow = "";
        state.editingId = null;
        setFormDisabled(getActiveSection(), false);
    }

    function getActiveSection() {
        return document.querySelector(`[data-form-section="${state.modalModule || state.module}"]`);
    }

    function clearForm(section) {
        section.querySelectorAll("[data-field]").forEach((field) => {
            if (field.tagName === "SELECT") {
                field.value = field.dataset.field === "adm_propriedade" || field.dataset.field === "energia_solar" ? "0" : "";
            } else {
                field.value = "";
            }
        });
        if (state.modalModule === "imoveis") {
            resetCepLookup();
            populateOwnerSelect();
        }
    }

    function fillForm(section, record) {
        section.querySelectorAll("[data-field]").forEach((field) => {
            const fieldName = field.dataset.field;
            if (!Object.prototype.hasOwnProperty.call(record, fieldName)) {
                return;
            }
            const value = record[fieldName];
            if (field.dataset.mask === "cpf") {
                field.value = formatCpf(value);
            } else if (field.dataset.mask === "rg") {
                field.value = formatRg(value);
            } else if (field.dataset.mask === "phone") {
                field.value = formatPhone(value);
            } else if (field.dataset.mask === "cep") {
                field.value = formatCep(value);
            } else if (field.dataset.mask === "currency") {
                field.value = formatCurrency(value);
            } else {
                field.value = value == null ? "" : String(value);
            }
        });
    }

    function setFormDisabled(section, disabled) {
        section.querySelectorAll("input, select").forEach((field) => {
            field.disabled = disabled;
        });
    }

    function populateOwnerSelect() {
        const select = document.getElementById("responsavel-select");
        if (!select) {
            return;
        }
        const currentValue = select.value;
        select.innerHTML = "<option value=\"\">Selecione um proprietário</option>";
        state.owners.forEach((owner) => select.add(new Option(owner.nome_completo, owner.id)));
        if (currentValue) {
            select.value = currentValue;
        }
        select.disabled = state.owners.length === 0;
    }

    function resetCepLookup() {
        if (state.viacep.controller) {
            state.viacep.controller.abort();
        }
        state.viacep.lastCep = "";
        state.viacep.requestId += 1;
        state.viacep.controller = null;
        state.viacep.autoValues = {};
        state.viacep.dirtyFields = {};
        setCepStatus("", "");
    }

    function handleCepInput(input) {
        const cep = onlyDigits(input.value);
        if (cep.length < 8) {
            if (state.viacep.controller) {
                state.viacep.controller.abort();
            }
            state.viacep.requestId += 1;
            state.viacep.controller = null;
            state.viacep.lastCep = "";
            setCepStatus("", "");
            return;
        }
        if (cep.length === 8 && cep !== state.viacep.lastCep) {
            lookupCep(cep);
        }
    }

    async function lookupCep(cep) {
        if (state.viacep.controller) {
            state.viacep.controller.abort();
        }

        const requestId = ++state.viacep.requestId;
        const controller = new AbortController();
        state.viacep.controller = controller;
        state.viacep.lastCep = cep;
        setCepStatus("loading", "Consultando CEP...");

        try {
            const response = await fetch(`https://viacep.com.br/ws/${cep}/json/`, {
                signal: controller.signal,
                headers: { Accept: "application/json" },
            });
            if (!response.ok) {
                throw new Error("Não foi possível consultar o CEP agora.");
            }
            const data = await response.json();
            if (requestId !== state.viacep.requestId) {
                return;
            }
            if (data.erro) {
                state.viacep.lastCep = "";
                setCepStatus("error", "CEP não encontrado.");
                showToast("O CEP informado não foi encontrado.", "error");
                return;
            }

            applyViaCepData(data);
            setCepStatus("success", "Endereço localizado.");
        } catch (error) {
            if (error.name === "AbortError" || requestId !== state.viacep.requestId) {
                return;
            }
            state.viacep.lastCep = "";
            setCepStatus("error", "Falha na consulta.");
            showToast("Não foi possível consultar o ViaCEP. Você pode preencher o endereço manualmente.", "error");
        } finally {
            if (requestId === state.viacep.requestId) {
                state.viacep.controller = null;
            }
        }
    }

    function applyViaCepData(data) {
        const section = getActiveSection();
        const viaCepValues = {
            endereco: String(data.logradouro || "").trim().toUpperCase(),
            estado: String(data.uf || "").trim().toUpperCase(),
            cidade: String(data.localidade || "").trim().toUpperCase(),
            bairro: String(data.bairro || "").trim().toUpperCase(),
        };

        Object.entries(viaCepValues).forEach(([fieldName, value]) => {
            const field = section.querySelector(`[data-field="${fieldName}"]`);
            if (!field) {
                return;
            }
            const currentValue = field.value.trim().toUpperCase();
            const previousAutoValue = state.viacep.autoValues[fieldName] || "";
            const wasManuallyChanged = state.viacep.dirtyFields[fieldName] === true;
            if (!wasManuallyChanged && (!currentValue || currentValue === previousAutoValue)) {
                field.value = value;
            }
        });
        state.viacep.autoValues = viaCepValues;
    }

    function setCepStatus(type, message) {
        const status = document.getElementById("cep-lookup-status");
        if (!status) {
            return;
        }
        status.className = `field-status ${type ? `is-${type}` : ""}`.trim();
        status.textContent = message;
    }

    async function handleFormSubmit(event) {
        event.preventDefault();
        if (state.modalMode === "view") {
            return;
        }

        const section = getActiveSection();
        const payload = collectForm(section);
        const validationError = validateClientPayload(payload);
        if (validationError) {
            showToast(validationError, "error");
            return;
        }

        const currentModule = state.modalModule || state.module;
        const config = moduleConfig[currentModule];
        const isEdit = state.modalMode === "edit";
        const url = isEdit ? `${config.endpoint}/${state.editingId}` : config.endpoint;
        try {
            await apiFetch(url, {
                method: isEdit ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            closeModal();
            showToast(`${config.singular} ${isEdit ? "atualizado" : "cadastrado"} com sucesso.`);
            await refreshCurrentModule();
            if (currentModule === "proprietarios") {
                await loadOwners();
            }
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    function collectForm(section) {
        const data = {};
        section.querySelectorAll("[data-field]").forEach((field) => {
            const value = field.value.trim();
            data[field.dataset.field] = field.dataset.field === "email" ? value.toLowerCase() : value.toUpperCase();
        });
        return data;
    }

    function validateClientPayload(data) {
        const currentModule = state.modalModule || state.module;
        if (currentModule !== "imoveis" && !data.nome_completo) {
            return "Nome completo é obrigatório.";
        }
        if (currentModule !== "imoveis" && data.cpf && !validCpf(data.cpf)) {
            return "Informe um CPF válido com 11 dígitos.";
        }
        if (currentModule === "imoveis") {
            if (!data.apelido) {
                return "Apelido do imóvel é obrigatório.";
            }
            if (!data.responsavel) {
                return "Selecione um proprietário responsável.";
            }
            if (!data.aluguel) {
                return "Aluguel é obrigatório.";
            }
            if (data.percentual_energia && (Number(data.percentual_energia) < 0 || Number(data.percentual_energia) > 100)) {
                return "O percentual de energia deve estar entre 0 e 100.";
            }
        }
        if (data.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email)) {
            return "Informe um e-mail válido.";
        }
        return null;
    }

    function validCpf(value) {
        const digits = onlyDigits(value);
        if (digits.length !== 11 || new Set(digits).size === 1) {
            return false;
        }
        let firstDigit = 0;
        for (let index = 0; index < 9; index += 1) {
            firstDigit += Number(digits[index]) * (10 - index);
        }
        firstDigit = (firstDigit * 10) % 11;
        if (firstDigit === 10) firstDigit = 0;
        if (firstDigit !== Number(digits[9])) return false;

        let secondDigit = 0;
        for (let index = 0; index < 10; index += 1) {
            secondDigit += Number(digits[index]) * (11 - index);
        }
        secondDigit = (secondDigit * 10) % 11;
        if (secondDigit === 10) secondDigit = 0;
        return secondDigit === Number(digits[10]);
    }

    async function apiFetch(url, options = {}) {
        const response = await fetch(url, {
            headers: { Accept: "application/json", ...(options.headers || {}) },
            ...options,
        });
        const data = response.status === 204 ? null : await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || "Não foi possível concluir a operação.");
        }
        return data;
    }

    function applyMask(input) {
        const mask = input.dataset.mask;
        if (mask === "cpf") input.value = formatCpf(input.value);
        if (mask === "rg") input.value = formatRg(input.value);
        if (mask === "phone") input.value = formatPhone(input.value);
        if (mask === "cep") input.value = formatCep(input.value);
        if (mask === "currency") input.value = formatCurrencyInput(input.value);
    }

    function onlyDigits(value) {
        return String(value || "").replace(/\D/g, "");
    }

    function formatCpf(value) {
        const digits = onlyDigits(value).slice(0, 11);
        if (digits.length <= 3) return digits;
        if (digits.length <= 6) return `${digits.slice(0, 3)}.${digits.slice(3)}`;
        if (digits.length <= 9) return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6)}`;
        return `${digits.slice(0, 3)}.${digits.slice(3, 6)}.${digits.slice(6, 9)}-${digits.slice(9)}`;
    }

    function formatRg(value) {
        const raw = String(value || "").toUpperCase().replace(/[^0-9X]/g, "").slice(0, 9);
        if (raw.length <= 2) return raw;
        if (raw.length <= 5) return `${raw.slice(0, 2)}.${raw.slice(2)}`;
        if (raw.length <= 8) return `${raw.slice(0, 2)}.${raw.slice(2, 5)}.${raw.slice(5)}`;
        return `${raw.slice(0, 2)}.${raw.slice(2, 5)}.${raw.slice(5, 8)}-${raw.slice(8)}`;
    }

    function formatPhone(value) {
        const digits = onlyDigits(value).slice(0, 11);
        if (digits.length <= 2) return digits;
        if (digits.length <= 6) return `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
        if (digits.length <= 10) return `(${digits.slice(0, 2)}) ${digits.slice(2, 6)}-${digits.slice(6)}`;
        return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
    }

    function formatCep(value) {
        const digits = onlyDigits(value).slice(0, 8);
        if (digits.length <= 5) return digits;
        return `${digits.slice(0, 5)}-${digits.slice(5)}`;
    }

    function formatCurrencyInput(value) {
        const digits = onlyDigits(value);
        if (!digits) return "";
        const number = Number(digits) / 100;
        return formatCurrency(number);
    }

    function formatCurrency(value) {
        if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "—";
        return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value));
    }

    function initials(name) {
        return String(name || "?")
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0])
            .join("")
            .toUpperCase();
    }

    function showToast(message, type = "success") {
        const toast = document.createElement("div");
        toast.className = `toast ${type === "error" ? "error" : ""}`;
        toast.innerHTML = `<span class="toast-icon">${type === "error" ? "!" : "✓"}</span><span>${escapeHtml(message)}</span>`;
        elements.toastRegion.appendChild(toast);
        window.setTimeout(() => toast.remove(), 4200);
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function toggleSidebar() {
        const open = elements.sidebar.classList.toggle("is-open");
        elements.sidebarBackdrop.classList.toggle("is-open", open);
        elements.menuToggle.setAttribute("aria-expanded", String(open));
    }

    function closeSidebar() {
        elements.sidebar.classList.remove("is-open");
        elements.sidebarBackdrop.classList.remove("is-open");
        elements.menuToggle.setAttribute("aria-expanded", "false");
    }
})();
