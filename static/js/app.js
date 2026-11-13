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
            columns: [
                { key: "nome_completo", label: "Proprietário", type: "text", value: (record) => record.nome_completo },
                { key: "cpf", label: "CPF", type: "digits", value: (record) => record.cpf },
                { key: "contato", label: "Contato", type: "digits", value: (record) => record.contato },
                { key: "email", label: "E-mail", type: "text", value: (record) => record.email },
            ],
        },
        inquilinos: {
            endpoint: "/api/inquilinos-clientes",
            title: "Inquilinos / Clientes",
            singular: "inquilino/cliente",
            description: "Centralize os dados de inquilinos e clientes.",
            empty: "Ainda não há inquilinos ou clientes cadastrados.",
            emptyDescription: "Cadastre seu primeiro inquilino ou cliente para manter os contatos organizados.",
            columns: [
                { key: "nome_completo", label: "Inquilino / Cliente", type: "text", value: (record) => record.nome_completo },
                { key: "cpf", label: "CPF", type: "digits", value: (record) => record.cpf },
                { key: "contato", label: "Contato", type: "digits", value: (record) => record.contato },
                { key: "email", label: "E-mail", type: "text", value: (record) => record.email },
            ],
        },
        imoveis: {
            endpoint: "/api/imoveis",
            title: "Imóveis",
            singular: "imóvel",
            description: "Acompanhe seus imóveis, responsáveis e dados de consumo.",
            empty: "Ainda não há imóveis cadastrados.",
            emptyDescription: "Cadastre um proprietário primeiro e depois adicione o seu primeiro imóvel.",
            columns: [
                { key: "tipo_imovel", label: "Tipo de imóvel", type: "text", value: (record) => record.tipo_imovel },
                { key: "apelido", label: "Imóvel", type: "text", value: (record) => record.apelido },
                { key: "responsavel_nome", label: "Responsável", type: "text", value: (record) => record.responsavel_nome },
                {
                    key: "endereco",
                    label: "Endereço",
                    type: "text",
                    value: (record) => [record.endereco, record.numero, record.cidade, record.estado].filter(Boolean).join(" "),
                },
                { key: "aluguel", label: "Aluguel referência", type: "number", value: (record) => record.aluguel },
                { key: "tipo_operacao", label: "Tipo operação", type: "text", value: (record) => record.tipo_operacao },
            ],
        },
        contratos: {
            endpoint: "/api/contratos",
            title: "Contratos",
            singular: "contrato",
            description: "Gerencie os contratos de aluguel e seus vínculos.",
            empty: "Ainda não há contratos cadastrados.",
            emptyDescription: "Cadastre o primeiro contrato relacionando um imóvel e um inquilino/cliente.",
            columns: [
                { key: "imovel_nome", label: "Imóvel", type: "text", value: (record) => record.imovel_nome },
                { key: "inquilino_nome", label: "Inquilino / Cliente", type: "text", value: (record) => record.inquilino_nome },
                { key: "data_inicio", label: "Início", type: "date", value: (record) => record.data_inicio },
                { key: "data_fim", label: "Fim", type: "date", value: (record) => record.data_fim },
                { key: "status", label: "Status", type: "text", value: (record) => record.status },
                { key: "valor_aluguel", label: "Aluguel", type: "number", value: (record) => record.valor_aluguel },
                { key: "valor_caucao", label: "Caução", type: "number", value: (record) => record.valor_caucao },
            ],
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
    const propertyTypes = [
        "CASA",
        "APARTAMENTO",
        "GALPÃO COMERCIAL",
        "CHÁCARA/SÍTIO",
        "TERRENO",
    ];
    const operationTypes = [
        "ALUGUEL",
        "ENERGIA SOLAR",
        "ALUGUEL + ENERGIA SOLAR",
    ];
    const contractStatuses = ["ATIVO", "ENCERRADO"];
    const VIA_CEP_FIELDS = ["endereco", "estado", "cidade", "bairro"];
    const textCollator = new Intl.Collator("pt-BR", { numeric: true, sensitivity: "accent" });

    const state = {
        module: "proprietarios",
        records: [],
        editingId: null,
        modalMode: "create",
        modalModule: "proprietarios",
        moduleRequestId: 0,
        ownerFilterId: "",
        owners: [],
        properties: [],
        clients: [],
        sortByModule: {},
        viacep: {
            lastCep: "",
            requestId: 0,
            controller: null,
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
        elements.ownerFilter = document.getElementById("owner-filter");
        elements.newRecordButton = document.getElementById("new-record-button");
        elements.newRecordLabel = document.getElementById("new-record-label");
        elements.refreshButton = document.getElementById("refresh-button");
        elements.emptyAction = document.getElementById("empty-action");
        elements.emptyState = document.getElementById("empty-state");
        elements.emptyTitle = document.getElementById("empty-title");
        elements.emptyDescription = document.getElementById("empty-description");
        elements.loadingState = document.getElementById("loading-state");
        elements.recordsTableCard = document.getElementById("records-table-card");
        elements.recordsHead = document.getElementById("records-head");
        elements.recordsBody = document.getElementById("records-body");
        elements.recordCount = document.getElementById("record-count");
        elements.contractsTables = document.getElementById("contracts-tables");
        elements.contractsLoadingState = document.getElementById("contracts-loading-state");
        elements.activeContractsHead = document.getElementById("active-contracts-head");
        elements.activeContractsBody = document.getElementById("active-contracts-body");
        elements.activeContractCount = document.getElementById("active-contract-count");
        elements.activeContractsEmpty = document.getElementById("active-contracts-empty");
        elements.closedContractsHead = document.getElementById("closed-contracts-head");
        elements.closedContractsBody = document.getElementById("closed-contracts-body");
        elements.closedContractCount = document.getElementById("closed-contract-count");
        elements.closedContractsEmpty = document.getElementById("closed-contracts-empty");
        elements.modal = document.getElementById("record-modal");
        elements.modalTitle = document.getElementById("modal-title");
        elements.modalDescription = document.getElementById("modal-description");
        elements.modalEyebrow = document.getElementById("modal-eyebrow");
        elements.modalClose = document.getElementById("modal-close");
        elements.modalCancel = document.getElementById("modal-cancel");
        elements.modalSubmit = document.getElementById("modal-submit");
        elements.form = document.getElementById("record-form");
        elements.clearCepButton = document.getElementById("clear-cep-button");
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
        elements.ownerFilter.addEventListener("change", () => {
            state.ownerFilterId = elements.ownerFilter.value;
            refreshCurrentModule();
        });
        elements.form.addEventListener("submit", handleFormSubmit);
        elements.modalClose.addEventListener("click", closeModal);
        elements.modalCancel.addEventListener("click", closeModal);
        elements.modal.addEventListener("click", (event) => {
            if (event.target === elements.modal) {
                closeModal();
            }
        });
        elements.clearCepButton.addEventListener("click", clearCep);
        elements.recordsHead.addEventListener("click", handleSortHeaderClick);
        elements.recordsBody.addEventListener("click", handleTableAction);
        elements.activeContractsHead.addEventListener("click", handleSortHeaderClick);
        elements.activeContractsBody.addEventListener("click", handleTableAction);
        elements.closedContractsHead.addEventListener("click", handleSortHeaderClick);
        elements.closedContractsBody.addEventListener("click", handleTableAction);
        document.querySelectorAll(".contract-empty-action").forEach((button) => {
            button.addEventListener("click", () => openModal("create", null, "contratos"));
        });
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
        const contractSection = document.querySelector('[data-form-section="contratos"]');
        if (contractSection) {
            const startDate = contractSection.querySelector('[data-field="data_inicio"]');
            if (startDate) {
                startDate.addEventListener("change", () => updateContractDateConstraints(contractSection));
            }
        }
        setTableMode();
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
            const data = await apiFetch(withOwnerFilter("/api/dashboard", "dashboard"));
            const counts = data.counts || {};
            document.getElementById("count-proprietarios").textContent = counts.proprietarios || 0;
            document.getElementById("count-inquilinos").textContent = counts.inquilinos_clientes || 0;
            document.getElementById("count-imoveis-locacao").textContent = counts.imoveis_locacao || 0;
            document.getElementById("count-imoveis-energia-solar").textContent = counts.imoveis_energia_solar || 0;
            document.getElementById("count-contratos").textContent = counts.contratos || 0;
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function loadOwners() {
        try {
            state.owners = await apiFetch("/api/proprietarios");
            populateOwnerSelect();
            populateOwnerFilter();
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function loadContractOptions() {
        try {
            const [properties, clients] = await Promise.all([
                apiFetch(withOwnerFilter("/api/imoveis", "imoveis")),
                apiFetch("/api/inquilinos-clientes"),
            ]);
            state.properties = properties;
            state.clients = clients;
            populateContractSelects();
        } catch (error) {
            showToast(error.message, "error");
        }
    }

    async function loadModule(moduleName) {
        const config = moduleConfig[moduleName];
        if (!config) {
            return;
        }

        const requestId = ++state.moduleRequestId;
        setLoading(true);
        try {
            const records = await apiFetch(withOwnerFilter(config.endpoint, moduleName));
            if (requestId !== state.moduleRequestId || state.module !== moduleName) {
                return;
            }
            state.records = Array.isArray(records) ? records : [];
            renderTable();
        } catch (error) {
            if (requestId !== state.moduleRequestId || state.module !== moduleName) {
                return;
            }
            state.records = [];
            renderTable();
            showToast(error.message, "error");
        } finally {
            if (requestId === state.moduleRequestId) {
                setLoading(false);
            }
        }
    }

    async function refreshCurrentModule() {
        await Promise.all([loadDashboard(), loadModule(state.module)]);
        if (state.module === "imoveis") {
            await loadOwners();
        }
        if (state.module === "contratos") {
            await loadContractOptions();
        }
    }

    function setModule(moduleName) {
        if (state.module === moduleName) {
            elements.newRecordButton.dataset.module = moduleName;
            elements.emptyAction.dataset.module = moduleName;
            setTableMode();
            loadModule(moduleName);
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
        setTableMode();
        loadModule(moduleName);
    }

    function setTableMode() {
        const isContracts = state.module === "contratos";
        elements.recordsTableCard.hidden = isContracts;
        elements.contractsTables.hidden = !isContracts;
    }

    function withOwnerFilter(endpoint, context) {
        const filteredContexts = ["dashboard", "imoveis", "contratos"];
        if (!state.ownerFilterId || !filteredContexts.includes(context)) {
            return endpoint;
        }
        const separator = endpoint.includes("?") ? "&" : "?";
        return `${endpoint}${separator}proprietario_id=${encodeURIComponent(state.ownerFilterId)}`;
    }

    function setLoading(isLoading) {
        elements.loadingState.hidden = !isLoading;
        elements.contractsLoadingState.hidden = !isLoading;
        if (isLoading) {
            elements.emptyState.hidden = true;
            elements.activeContractsEmpty.hidden = true;
            elements.closedContractsEmpty.hidden = true;
        }
    }

    function renderTable() {
        const config = moduleConfig[state.module];
        const sort = state.sortByModule[state.module] || null;
        if (state.module === "contratos") {
            renderContractsTables(config, sort);
            return;
        }
        elements.recordsHead.innerHTML = `<tr>${config.columns.map((column) => renderSortHeader(column, sort)).join("")}<th class="actions-cell" scope="col">Ações</th></tr>`;
        elements.recordsBody.innerHTML = sortRecords(state.records, config.columns, sort)
            .map((record) => renderRow(record, sort))
            .join("");
        elements.recordCount.textContent = `${state.records.length} ${state.records.length === 1 ? "registro" : "registros"}`;
        elements.emptyTitle.textContent = config.empty;
        elements.emptyDescription.textContent = config.emptyDescription;
        elements.emptyState.hidden = state.records.length !== 0;
    }

    function renderContractsTables(config, sort) {
        const activeRecords = state.records.filter((record) => record.status === "ATIVO");
        const closedRecords = state.records.filter((record) => record.status === "ENCERRADO");
        renderContractTable(
            activeRecords,
            elements.activeContractsHead,
            elements.activeContractsBody,
            elements.activeContractsEmpty,
            elements.activeContractCount,
            config,
            sort,
        );
        renderContractTable(
            closedRecords,
            elements.closedContractsHead,
            elements.closedContractsBody,
            elements.closedContractsEmpty,
            elements.closedContractCount,
            config,
            sort,
        );
        elements.recordCount.textContent = `${state.records.length} ${state.records.length === 1 ? "registro" : "registros"}`;
    }

    function renderContractTable(records, head, body, emptyState, recordCount, config, sort) {
        head.innerHTML = `<tr>${config.columns.map((column) => renderSortHeader(column, sort)).join("")}<th class="actions-cell" scope="col">Ações</th></tr>`;
        body.innerHTML = sortRecords(records, config.columns, sort)
            .map((record) => renderRow(record, sort))
            .join("");
        recordCount.textContent = `${records.length} ${records.length === 1 ? "registro" : "registros"}`;
        emptyState.hidden = records.length !== 0;
    }

    function renderSortHeader(column, sort) {
        const isActive = sort && sort.key === column.key;
        const direction = isActive ? sort.direction : null;
        const nextDirection = direction === "asc" ? "decrescente" : "crescente";
        const ariaSort = direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none";
        const indicatorClass = direction ? ` is-${direction}` : "";
        const activeClass = isActive ? " is-sorted" : "";

        return `<th class="sortable-header${activeClass}" scope="col" aria-sort="${ariaSort}">
            <button class="sort-button" type="button" data-sort-key="${column.key}" aria-label="Ordenar por ${escapeHtml(column.label)} em ordem ${nextDirection}">
                <span>${escapeHtml(column.label)}</span>
                <span class="sort-indicator${indicatorClass}" aria-hidden="true"><span class="sort-arrow sort-arrow-up">▲</span><span class="sort-arrow sort-arrow-down">▼</span></span>
            </button>
        </th>`;
    }

    function handleSortHeaderClick(event) {
        const button = event.target.closest("[data-sort-key]");
        if (!button || !button.closest("thead")) {
            return;
        }

        const currentSort = state.sortByModule[state.module];
        const direction = currentSort && currentSort.key === button.dataset.sortKey && currentSort.direction === "asc"
            ? "desc"
            : "asc";
        state.sortByModule[state.module] = { key: button.dataset.sortKey, direction };
        renderTable();
    }

    function sortRecords(records, columns, sort) {
        if (!sort) {
            return records.slice();
        }

        const column = columns.find((item) => item.key === sort.key);
        if (!column) {
            return records.slice();
        }

        return records
            .map((record, index) => ({ record, index }))
            .sort((left, right) => {
                const leftValue = normalizeSortValue(column.value(left.record), column.type);
                const rightValue = normalizeSortValue(column.value(right.record), column.type);
                const leftMissing = leftValue === null;
                const rightMissing = rightValue === null;

                if (leftMissing || rightMissing) {
                    if (leftMissing && rightMissing) {
                        return left.index - right.index;
                    }
                    return leftMissing ? 1 : -1;
                }

                const comparison = compareSortValues(leftValue, rightValue, column.type);
                if (comparison === 0) {
                    return left.index - right.index;
                }
                return sort.direction === "desc" ? -comparison : comparison;
            })
            .map(({ record }) => record);
    }

    function normalizeSortValue(value, type) {
        if (value === null || value === undefined) {
            return null;
        }

        if (type === "text") {
            const text = String(value).trim();
            return text || null;
        }

        if (type === "digits") {
            const digits = onlyDigits(value);
            return digits || null;
        }

        if (type === "number") {
            if (String(value).trim() === "") {
                return null;
            }
            const number = Number(value);
            return Number.isFinite(number) ? number : null;
        }

        if (type === "date") {
            const timestamp = Date.parse(String(value).trim());
            return Number.isNaN(timestamp) ? null : timestamp;
        }

        if (type === "boolean") {
            const normalized = String(value).trim().toLowerCase();
            if (value === true || normalized === "1" || normalized === "true" || normalized === "sim") {
                return 1;
            }
            if (value === false || normalized === "0" || normalized === "false" || normalized === "nao") {
                return 0;
            }
            return null;
        }

        return String(value).trim() || null;
    }

    function compareSortValues(left, right, type) {
        if (type === "text") {
            return textCollator.compare(left, right);
        }
        return left < right ? -1 : left > right ? 1 : 0;
    }

    function sortCellClass(sort, key) {
        return sort && sort.key === key ? "is-sorted-column" : "";
    }

    function renderRow(record, sort) {
        if (state.module === "contratos") {
            return `<tr>
                <td class="${sortCellClass(sort, "imovel_nome")}"><div class="property-cell"><span class="row-avatar property">C</span><span>${escapeHtml(record.imovel_nome)}<small class="subtle-text">Código #${record.imovel_id}</small></span></div></td>
                <td class="${sortCellClass(sort, "inquilino_nome")}"><div class="person-cell"><span class="row-avatar">${initials(record.inquilino_nome)}</span><span>${escapeHtml(record.inquilino_nome)}<small class="subtle-text">Código #${record.inquilino_id}</small></span></div></td>
                <td class="${sortCellClass(sort, "data_inicio")}">${escapeHtml(formatDate(record.data_inicio))}</td>
                <td class="${sortCellClass(sort, "data_fim")}">${escapeHtml(formatDate(record.data_fim))}</td>
                <td class="${sortCellClass(sort, "status")}"><span class="status-pill ${record.status === "ENCERRADO" ? "off" : ""}">${contractStatusLabel(record.status)}</span></td>
                <td class="${sortCellClass(sort, "valor_aluguel")}">${formatCurrency(record.valor_aluguel)}</td>
                <td class="${sortCellClass(sort, "valor_caucao")}">${formatCurrency(record.valor_caucao)}</td>
                <td class="actions-cell">${actionButtons(record.id)}</td>
            </tr>`;
        }

        if (state.module === "imoveis") {
            const location = [
                record.endereco,
                record.numero ? `Nº ${record.numero}` : "",
                record.cidade,
                record.estado,
            ].filter(Boolean).join(" · ") || "Endereço não informado";
            return `<tr>
                <td class="${sortCellClass(sort, "tipo_imovel")}">${escapeHtml(record.tipo_imovel || "Não informado")}</td>
                <td class="${sortCellClass(sort, "apelido")}"><div class="property-cell"><span class="row-avatar property">⌂</span><span>${escapeHtml(record.apelido)}<small class="subtle-text">Código #${record.id}</small></span></div></td>
                <td class="${sortCellClass(sort, "responsavel_nome")}">${escapeHtml(record.responsavel_nome || "—")}</td>
                <td class="${sortCellClass(sort, "endereco")}">${escapeHtml(location)}</td>
                <td class="${sortCellClass(sort, "aluguel")}">${formatCurrency(record.aluguel)}</td>
                <td class="${sortCellClass(sort, "tipo_operacao")}"><span class="status-pill">${escapeHtml(record.tipo_operacao || "Não informado")}</span></td>
                <td class="actions-cell">${actionButtons(record.id)}</td>
            </tr>`;
        }

        return `<tr>
            <td class="${sortCellClass(sort, "nome_completo")}"><div class="person-cell"><span class="row-avatar">${initials(record.nome_completo)}</span><span>${escapeHtml(record.nome_completo)}<small class="subtle-text">Código #${record.id}</small></span></div></td>
            <td class="${sortCellClass(sort, "cpf")}">${formatCpf(record.cpf)}</td>
            <td class="${sortCellClass(sort, "contato")}">${formatPhone(record.contato)}</td>
            <td class="${sortCellClass(sort, "email")}">${escapeHtml(record.email || "—")}</td>
            <td class="actions-cell">${actionButtons(record.id)}</td>
        </tr>`;
    }

    function contractStatusLabel(status) {
        return status === "ENCERRADO" ? "Encerrado" : "Ativo";
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
        const description = state.module === "imoveis"
            ? record.apelido
            : state.module === "contratos"
                ? `${record.imovel_nome} / ${record.inquilino_nome}`
                : record.nome_completo;
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
        if (modalModule === "contratos") {
            await loadContractOptions();
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
        if (modalModule === "contratos") {
            setContractDateFields(section, isView);
            updateContractDateConstraints(section);
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
                const selectDefaults = {
                    adm_propriedade: "0",
                    imobiliaria: "0",
                    tipo_operacao: "ALUGUEL",
                    status: "ATIVO",
                };
                field.value = selectDefaults[field.dataset.field] || "";
            } else {
                field.value = "";
            }
        });
        if (state.modalModule === "imoveis") {
            resetCepLookup();
            populateOwnerSelect();
        }
        if (state.modalModule === "contratos") {
            resetContractDateFields(section);
            populateContractSelects();
            updateContractDateConstraints(section);
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
            } else if (field.dataset.mask === "phone") {
                field.value = formatPhone(value);
            } else if (field.dataset.mask === "cep") {
                field.value = formatCep(value);
            } else if (field.dataset.mask === "currency") {
                field.value = value == null
                    ? (state.modalMode === "view" ? formatCurrency(value) : "")
                    : formatCurrency(value);
            } else {
                field.value = value == null ? "" : String(value);
            }
        });
    }

    function setFormDisabled(section, disabled) {
        section.querySelectorAll("input, select, button").forEach((field) => {
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

    function populateOwnerFilter() {
        const select = elements.ownerFilter;
        if (!select) {
            return;
        }

        const currentValue = state.ownerFilterId;
        select.innerHTML = "<option value=\"\">TODOS</option>";
        state.owners.forEach((owner) => select.add(new Option(owner.nome_completo, owner.id)));

        if (currentValue && state.owners.some((owner) => String(owner.id) === String(currentValue))) {
            select.value = currentValue;
        } else {
            state.ownerFilterId = "";
            select.value = "";
        }
    }

    function populateContractSelects() {
        const propertySelect = document.getElementById("imovel-select");
        const clientSelect = document.getElementById("inquilino-select");
        if (!propertySelect || !clientSelect) {
            return;
        }

        const propertyValue = propertySelect.value;
        const clientValue = clientSelect.value;
        propertySelect.innerHTML = "<option value=\"\">Selecione um imóvel</option>";
        clientSelect.innerHTML = "<option value=\"\">Selecione um inquilino / cliente</option>";

        state.properties.forEach((property) => {
            propertySelect.add(new Option(property.apelido, property.id));
        });
        state.clients.forEach((client) => {
            clientSelect.add(new Option(client.nome_completo, client.id));
        });

        if (propertyValue) {
            propertySelect.value = propertyValue;
        }
        if (clientValue) {
            clientSelect.value = clientValue;
        }
        propertySelect.disabled = state.properties.length === 0;
        clientSelect.disabled = state.clients.length === 0;
    }

    function resetContractDateFields(section) {
        section.querySelectorAll('[data-field="data_inicio"], [data-field="data_fim"]').forEach((field) => {
            field.type = "date";
            field.value = "";
        });
    }

    function setContractDateFields(section, isView) {
        section.querySelectorAll('[data-field="data_inicio"], [data-field="data_fim"]').forEach((field) => {
            if (isView) {
                field.type = "text";
                field.value = formatDate(field.value);
            } else {
                field.type = "date";
            }
        });
    }

    function updateContractDateConstraints(section) {
        const start = section.querySelector('[data-field="data_inicio"]');
        const end = section.querySelector('[data-field="data_fim"]');
        if (!start || !end || start.type !== "date") {
            return;
        }
        end.min = start.value || "";
    }

    function resetCepLookup() {
        if (state.viacep.controller) {
            state.viacep.controller.abort();
        }
        state.viacep.lastCep = "";
        state.viacep.requestId += 1;
        state.viacep.controller = null;
        setCepStatus("", "");
    }

    function clearViaCepFields() {
        const section = getActiveSection();
        if (!section) {
            return;
        }
        VIA_CEP_FIELDS.forEach((fieldName) => {
            const field = section.querySelector(`[data-field="${fieldName}"]`);
            if (field) {
                field.value = "";
            }
        });
    }

    function clearCep() {
        const section = getActiveSection();
        resetCepLookup();
        if (!section) {
            return;
        }

        const cepField = section.querySelector('[data-field="cep"]');
        if (cepField) {
            cepField.value = "";
        }
        clearViaCepFields();
        if (cepField && !cepField.disabled) {
            cepField.focus();
        }
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
            clearViaCepFields();
            setCepStatus("", "");
            return;
        }
        if (cep.length === 8 && cep !== state.viacep.lastCep) {
            clearViaCepFields();
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
            field.value = value;
        });
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
        const isPersonModule = currentModule === "proprietarios" || currentModule === "inquilinos";
        if (isPersonModule && !data.nome_completo) {
            return "Nome completo é obrigatório.";
        }
        if (isPersonModule && data.cpf && !validCpf(data.cpf)) {
            return "Informe um CPF válido com 11 dígitos.";
        }
        if (currentModule === "imoveis") {
            if (!data.tipo_imovel) {
                return "Tipo de imóvel é obrigatório.";
            }
            if (!propertyTypes.includes(data.tipo_imovel)) {
                return "Tipo de imóvel inválido.";
            }
            if (!data.tipo_operacao) {
                return "Tipo de operação é obrigatório.";
            }
            if (!operationTypes.includes(data.tipo_operacao)) {
                return "Tipo de operação inválido.";
            }
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
        if (currentModule === "contratos") {
            if (!data.imovel_id) {
                return "Selecione um imóvel.";
            }
            if (!data.inquilino_id) {
                return "Selecione um inquilino / cliente.";
            }
            if (!data.data_inicio) {
                return "Data de início é obrigatória.";
            }
            if (!data.data_fim) {
                return "Data de fim é obrigatória.";
            }
            if (data.data_fim < data.data_inicio) {
                return "A data de fim não pode ser anterior à data de início.";
            }
            if (!data.valor_aluguel) {
                return "Valor do aluguel é obrigatório.";
            }
            if (!data.status) {
                return "Selecione o status do contrato.";
            }
            if (!contractStatuses.includes(data.status)) {
                return "Status de contrato inválido.";
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

    function formatDate(value) {
        if (!value) return "—";
        const parts = String(value).split("-");
        if (parts.length !== 3) return String(value);
        return `${parts[2]}/${parts[1]}/${parts[0]}`;
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
