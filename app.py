from __future__ import annotations

import re
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flask import Flask, current_app, g, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE = BASE_DIR / "instance" / "ppaluguel.db"

ESTADOS_CIVIS = {
    "SOLTEIRO(A)",
    "CASADO(A)",
    "DIVORCIADO(A)",
    "VIÚVO(A)",
    "SEPARADO(A)",
    "UNIÃO ESTÁVEL",
}
UF_VALIDAS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}

PERSON_FIELDS = (
    "nome_completo",
    "rg",
    "cpf",
    "contato",
    "profissao",
    "estado_civil",
    "email",
)

PROPERTY_FIELDS = (
    "apelido",
    "responsavel",
    "cep",
    "endereco",
    "estado",
    "cidade",
    "bairro",
    "numero",
    "complemento",
    "inscricao_mun",
    "aluguel",
    "numero_energia",
    "numero_agua",
    "adm_propriedade",
    "energia_solar",
    "unidade_geradora",
    "percentual_energia",
)

KNOWN_REPLACEMENT_REPAIRS = {
    "UNI\ufffdO": "UNIÃO",
    "EST\ufffdVEL": "ESTÁVEL",
    "LOG\ufffdSTICA": "LOGÍSTICA",
    "SERT\ufffdOZINHO": "SERTÃOZINHO",
    "ANT\ufffdNIO": "ANTÔNIO",
}


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=str(DEFAULT_DATABASE),
        JSON_SORT_KEYS=False,
    )

    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    register_routes(app)
    return app


def get_db() -> sqlite3.Connection:
    """Return the request-scoped SQLite connection."""

    if "db" not in g:
        g.db = sqlite3.connect(str(current_app.config["DATABASE"]))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS proprietario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_completo TEXT NOT NULL,
            rg TEXT,
            cpf TEXT,
            contato TEXT,
            profissao TEXT,
            estado_civil TEXT,
            email TEXT
        );

        CREATE TABLE IF NOT EXISTS inquilinos_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_completo TEXT NOT NULL,
            rg TEXT,
            cpf TEXT,
            contato TEXT,
            profissao TEXT,
            estado_civil TEXT,
            email TEXT
        );

        CREATE TABLE IF NOT EXISTS imoveis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apelido TEXT NOT NULL,
            responsavel INTEGER NOT NULL,
            cep TEXT,
            endereco TEXT,
            estado TEXT,
            cidade TEXT,
            bairro TEXT,
            numero TEXT,
            complemento TEXT,
            inscricao_mun TEXT,
            aluguel REAL NOT NULL DEFAULT 0,
            numero_energia TEXT,
            numero_agua TEXT,
            adm_propriedade INTEGER NOT NULL DEFAULT 0 CHECK (adm_propriedade IN (0, 1)),
            imobiliaria INTEGER NOT NULL DEFAULT 0 CHECK (imobiliaria IN (0, 1)),
            energia_solar INTEGER NOT NULL DEFAULT 0 CHECK (energia_solar IN (0, 1)),
            unidade_geradora TEXT,
            percentual_energia REAL CHECK (
                percentual_energia IS NULL OR
                (percentual_energia >= 0 AND percentual_energia <= 100)
            ),
            FOREIGN KEY (responsavel) REFERENCES proprietario (id) ON DELETE RESTRICT
        );
        """
    )
    migrate_database(db)
    normalize_existing_data(db)
    db.commit()


def migrate_database(db: sqlite3.Connection) -> None:
    """Apply additive schema changes without recreating existing tables."""

    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(imoveis)").fetchall()
    }
    if "endereco" not in columns:
        db.execute("ALTER TABLE imoveis ADD COLUMN endereco TEXT")
    if "imobiliaria" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN imobiliaria INTEGER NOT NULL DEFAULT 0 "
            "CHECK (imobiliaria IN (0, 1))"
        )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS contratos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imovel_id INTEGER NOT NULL,
            inquilino_id INTEGER NOT NULL,
            data_inicio TEXT NOT NULL,
            data_fim TEXT NOT NULL,
            valor_aluguel REAL NOT NULL CHECK (valor_aluguel >= 0),
            valor_caucao REAL CHECK (valor_caucao IS NULL OR valor_caucao >= 0),
            FOREIGN KEY (imovel_id) REFERENCES imoveis (id) ON DELETE RESTRICT,
            FOREIGN KEY (inquilino_id) REFERENCES inquilinos_clientes (id) ON DELETE RESTRICT,
            CHECK (data_fim >= data_inicio)
        )
        """
    )


def normalize_existing_data(db: sqlite3.Connection) -> None:
    """Normalize text already stored by an earlier version of the app."""

    fields_by_table = {
        "proprietario": PERSON_FIELDS,
        "inquilinos_clientes": PERSON_FIELDS,
        "imoveis": (
            "apelido",
            "cep",
            "endereco",
            "estado",
            "cidade",
            "bairro",
            "numero",
            "complemento",
            "inscricao_mun",
            "numero_energia",
            "numero_agua",
            "unidade_geradora",
        ),
    }
    for table, fields in fields_by_table.items():
        rows = db.execute(f"SELECT id, {', '.join(fields)} FROM {table}").fetchall()
        assignments = ", ".join(f"{field} = ?" for field in fields)
        for row in rows:
            values = tuple(normalize_persisted_text(field, row[field]) for field in fields)
            current = tuple(row[field] for field in fields)
            if values != current:
                db.execute(
                    f"UPDATE {table} SET {assignments} WHERE id = ?",
                    (*values, row["id"]),
                )


def error_response(message: str, status: int = 400):
    return jsonify({"error": message}), status


def payload() -> dict[str, Any] | None:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = repair_text_encoding(str(value)).strip().upper()
    return text or None


def repair_text_encoding(value: str) -> str:
    """Repair common UTF-8/Latin-1 mojibake without changing valid text."""

    repaired = value
    if any(marker in repaired for marker in ("Ã", "Â", "â")):
        try:
            repaired = repaired.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            repaired = value

    for corrupted, correct in KNOWN_REPLACEMENT_REPAIRS.items():
        repaired = repaired.replace(corrupted, correct)
    return repaired


def normalize_persisted_text(field: str, value: Any) -> str | None:
    if field == "email":
        if value is None:
            return None
        text = repair_text_encoding(str(value)).strip().lower()
        return text or None
    return clean_text(value)


def normalize_document(value: Any, field: str) -> str | None:
    text = clean_text(value)
    if text is None:
        return None

    normalized = re.sub(r"[^0-9A-Za-z]", "", text).upper()
    if field == "cpf":
        if len(normalized) != 11 or not valid_cpf(normalized):
            raise ValueError("Informe um CPF válido com 11 dígitos.")
    if field == "rg" and not 5 <= len(normalized) <= 15:
        raise ValueError("RG deve conter entre 5 e 15 caracteres.")
    return normalized


def valid_cpf(value: str) -> bool:
    if len(value) != 11 or not value.isdigit() or len(set(value)) == 1:
        return False

    first_digit = sum(int(value[index]) * (10 - index) for index in range(9))
    first_digit = (first_digit * 10) % 11
    if first_digit == 10:
        first_digit = 0
    if first_digit != int(value[9]):
        return False

    second_digit = sum(int(value[index]) * (11 - index) for index in range(10))
    second_digit = (second_digit * 10) % 11
    if second_digit == 10:
        second_digit = 0
    return second_digit == int(value[10])


def normalize_digits(value: Any, field: str, lengths: set[int]) -> str | None:
    text = clean_text(value)
    if text is None:
        return None

    normalized = re.sub(r"\D", "", text)
    if len(normalized) not in lengths:
        accepted = " ou ".join(str(length) for length in sorted(lengths))
        label = "CEP" if field == "cep" else "contato"
        raise ValueError(f"{label} deve conter {accepted} dígitos.")
    return normalized


def normalize_email(value: Any) -> str | None:
    email = normalize_persisted_text("email", value)
    if email is None:
        return None
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Informe um e-mail válido.")
    return email


def parse_decimal(value: Any, label: str, *, required: bool = False) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{label} é obrigatório.")
        return None

    if isinstance(value, bool):
        raise ValueError(f"{label} deve ser numérico.")

    text = str(value).strip().replace("R$", "").replace(" ", "")
    try:
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} deve ser um número válido.") from None

    if number < 0:
        raise ValueError(f"{label} não pode ser negativo.")
    return float(number)


def parse_boolean(value: Any, label: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if value is None or value == "":
        return 0
    if str(value).strip().lower() in {"1", "true", "sim", "yes", "on"}:
        return 1
    if str(value).strip().lower() in {"0", "false", "não", "nao", "no", "off"}:
        return 0
    raise ValueError(f"{label} deve ser Sim ou Não.")


def person_values(data: dict[str, Any]) -> tuple[Any, ...]:
    name = clean_text(data.get("nome_completo"))
    if not name:
        raise ValueError("Nome completo é obrigatório.")

    estado_civil = clean_text(data.get("estado_civil"))
    if estado_civil and estado_civil not in ESTADOS_CIVIS:
        raise ValueError("Estado civil inválido.")

    return (
        name,
        normalize_document(data.get("rg"), "rg"),
        normalize_document(data.get("cpf"), "cpf"),
        normalize_digits(data.get("contato"), "contato", {10, 11}),
        clean_text(data.get("profissao")),
        estado_civil,
        normalize_email(data.get("email")),
    )


def property_values(data: dict[str, Any], db: sqlite3.Connection) -> tuple[Any, ...]:
    nickname = clean_text(data.get("apelido"))
    if not nickname:
        raise ValueError("Apelido é obrigatório.")

    responsible = data.get("responsavel")
    try:
        responsible_id = int(responsible)
    except (TypeError, ValueError):
        raise ValueError("Selecione um proprietário responsável.") from None
    if responsible_id <= 0:
        raise ValueError("Selecione um proprietário responsável.")
    if db.execute("SELECT 1 FROM proprietario WHERE id = ?", (responsible_id,)).fetchone() is None:
        raise ValueError("O proprietário selecionado não existe.")

    estado = clean_text(data.get("estado"))
    if estado:
        estado = estado.upper()
        if estado not in UF_VALIDAS:
            raise ValueError("Estado inválido.")

    rent = parse_decimal(data.get("aluguel"), "Aluguel", required=True)
    energy_percentage = parse_decimal(data.get("percentual_energia"), "Percentual de energia")
    if energy_percentage is not None and energy_percentage > 100:
        raise ValueError("Percentual de energia deve estar entre 0 e 100.")

    return (
        nickname,
        responsible_id,
        normalize_digits(data.get("cep"), "cep", {8}),
        clean_text(data.get("endereco")),
        estado,
        clean_text(data.get("cidade")),
        clean_text(data.get("bairro")),
        clean_text(data.get("numero")),
        clean_text(data.get("complemento")),
        clean_text(data.get("inscricao_mun")),
        rent,
        clean_text(data.get("numero_energia")),
        clean_text(data.get("numero_agua")),
        parse_boolean(data.get("adm_propriedade"), "Administração da propriedade"),
        parse_boolean(data.get("imobiliaria"), "Administração por imobiliária"),
        parse_boolean(data.get("energia_solar"), "Energia solar"),
        clean_text(data.get("unidade_geradora")),
        energy_percentage,
    )


def parse_foreign_key(
    value: Any,
    label: str,
    table: str,
    db: sqlite3.Connection,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Selecione um {label} válido.")
    try:
        record_id = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Selecione um {label}.") from None
    if record_id <= 0:
        raise ValueError(f"Selecione um {label}.")
    if db.execute(f"SELECT 1 FROM {table} WHERE id = ?", (record_id,)).fetchone() is None:
        raise ValueError(f"O {label} selecionado não existe.")
    return record_id


def parse_contract_date(value: Any, label: str) -> date:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{label} é obrigatória.")

    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{label} deve ser uma data válida.") from None
    if parsed.isoformat() != text:
        raise ValueError(f"{label} deve estar no formato AAAA-MM-DD.")
    return parsed


def contract_values(data: dict[str, Any], db: sqlite3.Connection) -> tuple[Any, ...]:
    property_id = parse_foreign_key(data.get("imovel_id"), "imóvel", "imoveis", db)
    tenant_id = parse_foreign_key(
        data.get("inquilino_id"),
        "inquilino/cliente",
        "inquilinos_clientes",
        db,
    )
    start_date = parse_contract_date(data.get("data_inicio"), "Data de início")
    end_date = parse_contract_date(data.get("data_fim"), "Data de fim")
    if end_date < start_date:
        raise ValueError("A data de fim não pode ser anterior à data de início.")

    return (
        property_id,
        tenant_id,
        start_date.isoformat(),
        end_date.isoformat(),
        parse_decimal(data.get("valor_aluguel"), "Valor do aluguel", required=True),
        parse_decimal(data.get("valor_caucao"), "Valor da caução"),
    )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def get_property(db: sqlite3.Connection, record_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT i.*, p.nome_completo AS responsavel_nome
        FROM imoveis AS i
        JOIN proprietario AS p ON p.id = i.responsavel
        WHERE i.id = ?
        """,
        (record_id,),
    ).fetchone()


def get_contract(db: sqlite3.Connection, record_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT c.*, i.apelido AS imovel_nome,
               ic.nome_completo AS inquilino_nome
        FROM contratos AS c
        JOIN imoveis AS i ON i.id = c.imovel_id
        JOIN inquilinos_clientes AS ic ON ic.id = c.inquilino_id
        WHERE c.id = ?
        """,
        (record_id,),
    ).fetchone()


def register_routes(app: Flask) -> None:
    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/api/dashboard")
    def dashboard_data():
        db = get_db()
        counts = {
            "proprietarios": db.execute("SELECT COUNT(*) FROM proprietario").fetchone()[0],
            "inquilinos_clientes": db.execute("SELECT COUNT(*) FROM inquilinos_clientes").fetchone()[0],
            "imoveis": db.execute("SELECT COUNT(*) FROM imoveis").fetchone()[0],
            "contratos": db.execute("SELECT COUNT(*) FROM contratos").fetchone()[0],
        }
        return jsonify({"counts": counts})

    @app.route("/api/proprietarios", methods=["GET", "POST"])
    def proprietarios_collection():
        db = get_db()
        if request.method == "GET":
            rows = db.execute(
                "SELECT * FROM proprietario ORDER BY nome_completo COLLATE NOCASE"
            ).fetchall()
            return jsonify([row_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = person_values(data)
        except ValueError as error:
            return error_response(str(error))

        cursor = db.execute(
            """
            INSERT INTO proprietario
                (nome_completo, rg, cpf, contato, profissao, estado_civil, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        db.commit()
        row = db.execute("SELECT * FROM proprietario WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return jsonify(row_dict(row)), 201

    @app.route("/api/proprietarios/<int:record_id>", methods=["GET", "PUT", "DELETE"])
    def proprietario_item(record_id: int):
        db = get_db()
        row = db.execute("SELECT * FROM proprietario WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return error_response("Proprietário não encontrado.", 404)
        if request.method == "GET":
            return jsonify(row_dict(row))
        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            try:
                values = person_values(data)
            except ValueError as error:
                return error_response(str(error))
            db.execute(
                """
                UPDATE proprietario
                SET nome_completo = ?, rg = ?, cpf = ?, contato = ?,
                    profissao = ?, estado_civil = ?, email = ?
                WHERE id = ?
                """,
                (*values, record_id),
            )
            db.commit()
            updated = db.execute("SELECT * FROM proprietario WHERE id = ?", (record_id,)).fetchone()
            return jsonify(row_dict(updated))

        linked = db.execute(
            "SELECT COUNT(*) FROM imoveis WHERE responsavel = ?", (record_id,)
        ).fetchone()[0]
        if linked:
            return error_response(
                "Este proprietário possui imóveis vinculados. Reassocie-os antes de excluir.",
                409,
            )
        db.execute("DELETE FROM proprietario WHERE id = ?", (record_id,))
        db.commit()
        return ("", 204)

    @app.route("/api/inquilinos-clientes", methods=["GET", "POST"])
    def clients_collection():
        db = get_db()
        if request.method == "GET":
            rows = db.execute(
                "SELECT * FROM inquilinos_clientes ORDER BY nome_completo COLLATE NOCASE"
            ).fetchall()
            return jsonify([row_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = person_values(data)
        except ValueError as error:
            return error_response(str(error))

        cursor = db.execute(
            """
            INSERT INTO inquilinos_clientes
                (nome_completo, rg, cpf, contato, profissao, estado_civil, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM inquilinos_clientes WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return jsonify(row_dict(row)), 201

    @app.route("/api/inquilinos-clientes/<int:record_id>", methods=["GET", "PUT", "DELETE"])
    def client_item(record_id: int):
        db = get_db()
        row = db.execute(
            "SELECT * FROM inquilinos_clientes WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return error_response("Inquilino/cliente não encontrado.", 404)
        if request.method == "GET":
            return jsonify(row_dict(row))
        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            try:
                values = person_values(data)
            except ValueError as error:
                return error_response(str(error))
            db.execute(
                """
                UPDATE inquilinos_clientes
                SET nome_completo = ?, rg = ?, cpf = ?, contato = ?,
                    profissao = ?, estado_civil = ?, email = ?
                WHERE id = ?
                """,
                (*values, record_id),
            )
            db.commit()
            updated = db.execute(
                "SELECT * FROM inquilinos_clientes WHERE id = ?", (record_id,)
            ).fetchone()
            return jsonify(row_dict(updated))

        linked = db.execute(
            "SELECT COUNT(*) FROM contratos WHERE inquilino_id = ?", (record_id,)
        ).fetchone()[0]
        if linked:
            return error_response(
                "Este inquilino/cliente possui contratos vinculados. Exclua-os antes de remover o cadastro.",
                409,
            )
        db.execute("DELETE FROM inquilinos_clientes WHERE id = ?", (record_id,))
        db.commit()
        return ("", 204)

    @app.route("/api/imoveis", methods=["GET", "POST"])
    def properties_collection():
        db = get_db()
        if request.method == "GET":
            rows = db.execute(
                """
                SELECT i.*, p.nome_completo AS responsavel_nome
                FROM imoveis AS i
                JOIN proprietario AS p ON p.id = i.responsavel
                ORDER BY i.apelido COLLATE NOCASE
                """
            ).fetchall()
            return jsonify([row_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = property_values(data, db)
        except ValueError as error:
            return error_response(str(error))

        cursor = db.execute(
            """
            INSERT INTO imoveis
                (apelido, responsavel, cep, endereco, estado, cidade, bairro, numero,
                 complemento, inscricao_mun, aluguel, numero_energia, numero_agua,
                 adm_propriedade, imobiliaria, energia_solar, unidade_geradora, percentual_energia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        db.commit()
        row = get_property(db, cursor.lastrowid)
        return jsonify(row_dict(row)), 201

    @app.route("/api/imoveis/<int:record_id>", methods=["GET", "PUT", "DELETE"])
    def property_item(record_id: int):
        db = get_db()
        row = get_property(db, record_id)
        if row is None:
            return error_response("Imóvel não encontrado.", 404)
        if request.method == "GET":
            return jsonify(row_dict(row))
        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            try:
                values = property_values(data, db)
            except ValueError as error:
                return error_response(str(error))
            db.execute(
                """
                UPDATE imoveis
                SET apelido = ?, responsavel = ?, cep = ?, endereco = ?, estado = ?,
                    cidade = ?, bairro = ?, numero = ?, complemento = ?, inscricao_mun = ?,
                    aluguel = ?, numero_energia = ?, numero_agua = ?,
                    adm_propriedade = ?, imobiliaria = ?, energia_solar = ?, unidade_geradora = ?,
                    percentual_energia = ?
                WHERE id = ?
                """,
                (*values, record_id),
            )
            db.commit()
            updated = get_property(db, record_id)
            return jsonify(row_dict(updated))

        linked = db.execute(
            "SELECT COUNT(*) FROM contratos WHERE imovel_id = ?", (record_id,)
        ).fetchone()[0]
        if linked:
            return error_response(
                "Este imóvel possui contratos vinculados. Exclua-os antes de remover o cadastro.",
                409,
            )
        db.execute("DELETE FROM imoveis WHERE id = ?", (record_id,))
        db.commit()
        return ("", 204)

    @app.route("/api/contratos", methods=["GET", "POST"])
    def contracts_collection():
        db = get_db()
        if request.method == "GET":
            rows = db.execute(
                """
                SELECT c.*, i.apelido AS imovel_nome,
                       ic.nome_completo AS inquilino_nome
                FROM contratos AS c
                JOIN imoveis AS i ON i.id = c.imovel_id
                JOIN inquilinos_clientes AS ic ON ic.id = c.inquilino_id
                ORDER BY c.data_inicio DESC, c.id DESC
                """
            ).fetchall()
            return jsonify([row_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = contract_values(data, db)
        except ValueError as error:
            return error_response(str(error))

        cursor = db.execute(
            """
            INSERT INTO contratos
                (imovel_id, inquilino_id, data_inicio, data_fim,
                 valor_aluguel, valor_caucao)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        db.commit()
        row = get_contract(db, cursor.lastrowid)
        return jsonify(row_dict(row)), 201

    @app.route("/api/contratos/<int:record_id>", methods=["GET", "PUT", "DELETE"])
    def contract_item(record_id: int):
        db = get_db()
        row = get_contract(db, record_id)
        if row is None:
            return error_response("Contrato não encontrado.", 404)
        if request.method == "GET":
            return jsonify(row_dict(row))
        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            try:
                values = contract_values(data, db)
            except ValueError as error:
                return error_response(str(error))
            db.execute(
                """
                UPDATE contratos
                SET imovel_id = ?, inquilino_id = ?, data_inicio = ?, data_fim = ?,
                    valor_aluguel = ?, valor_caucao = ?
                WHERE id = ?
                """,
                (*values, record_id),
            )
            db.commit()
            updated = get_contract(db, record_id)
            return jsonify(row_dict(updated))

        db.execute("DELETE FROM contratos WHERE id = ?", (record_id,))
        db.commit()
        return ("", 204)


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
