from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as escape_xml

from flask import Flask, current_app, g, jsonify, render_template, request, send_file
from reportlab.graphics.shapes import Drawing, Line, String, Wedge
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepInFrame,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


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
TIPOS_IMOVEL = (
    "CASA",
    "APARTAMENTO",
    "GALPÃO COMERCIAL",
    "CHÁCARA/SÍTIO",
    "TERRENO",
)
TIPOS_OPERACAO = (
    "ALUGUEL",
    "ENERGIA SOLAR",
    "ALUGUEL + ENERGIA SOLAR",
)
CONTRACT_STATUSES = (
    "ATIVO",
    "ENCERRADO",
)
MAX_MONTHLY_GENERATION_KWH = 9_999_999
SALE_PRICE_SCALE = 10_000
SALE_PRICE_MAX_SCALED = (1 << 63) - 1

PERSON_FIELDS = (
    "nome_completo",
    "rg",
    "cpf",
    "contato",
    "profissao",
    "estado_civil",
    "email",
)
CLIENT_FIELDS = (
    "nome_completo",
    "rg",
    "cpf",
    "contato",
    "nome_contato",
    "profissao",
    "estado_civil",
    "email",
)

PROPERTY_FIELDS = (
    "tipo_imovel",
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
    "tipo_operacao",
    "unidade_geradora_legada",
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
            nome_contato TEXT,
            profissao TEXT,
            estado_civil TEXT,
            email TEXT
        );

        CREATE TABLE IF NOT EXISTS imoveis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            apelido TEXT NOT NULL,
            tipo_imovel TEXT,
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
            taxa_adm_imovel REAL CHECK (taxa_adm_imovel IS NULL OR taxa_adm_imovel >= 0),
            tipo_operacao TEXT NOT NULL DEFAULT 'ALUGUEL' CHECK (
                tipo_operacao IN ('ALUGUEL', 'ENERGIA SOLAR', 'ALUGUEL + ENERGIA SOLAR')
            ),
            unidade_geradora_legada TEXT,
            percentual_energia REAL CHECK (
                percentual_energia IS NULL OR
                (percentual_energia >= 0 AND percentual_energia <= 100)
            ),
            cliente_energia_solar_id INTEGER,
            repasse_iptu INTEGER NOT NULL DEFAULT 0 CHECK (repasse_iptu IN (0, 1)),
            valor_iptu REAL CHECK (valor_iptu IS NULL OR valor_iptu >= 0),
            repasse_taxa_condominio INTEGER NOT NULL DEFAULT 0 CHECK (
                repasse_taxa_condominio IN (0, 1)
            ),
            valor_condominio REAL CHECK (valor_condominio IS NULL OR valor_condominio >= 0),
            FOREIGN KEY (cliente_energia_solar_id)
                REFERENCES inquilinos_clientes (id) ON DELETE RESTRICT,
            FOREIGN KEY (responsavel) REFERENCES proprietario (id) ON DELETE RESTRICT
        );
        """
    )
    migrate_database(db)
    normalize_existing_data(db)
    migrate_legacy_generation_links(db)
    db.commit()


def migrate_database(db: sqlite3.Connection) -> None:
    """Apply additive schema changes without recreating existing tables."""

    columns = {
        row["name"] for row in db.execute("PRAGMA table_info(imoveis)").fetchall()
    }
    if "unidade_geradora" in columns and "unidade_geradora_legada" not in columns:
        db.execute(
            "ALTER TABLE imoveis RENAME COLUMN unidade_geradora TO unidade_geradora_legada"
        )
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(imoveis)").fetchall()
        }
    if "unidade_geradora_legada" not in columns:
        db.execute("ALTER TABLE imoveis ADD COLUMN unidade_geradora_legada TEXT")
    client_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(inquilinos_clientes)").fetchall()
    }
    if "nome_contato" not in client_columns:
        db.execute("ALTER TABLE inquilinos_clientes ADD COLUMN nome_contato TEXT")
    if "endereco" not in columns:
        db.execute("ALTER TABLE imoveis ADD COLUMN endereco TEXT")
    if "tipo_imovel" not in columns:
        db.execute("ALTER TABLE imoveis ADD COLUMN tipo_imovel TEXT")
    if "imobiliaria" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN imobiliaria INTEGER NOT NULL DEFAULT 0 "
            "CHECK (imobiliaria IN (0, 1))"
        )
    if "taxa_adm_imovel" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN taxa_adm_imovel REAL "
            "CHECK (taxa_adm_imovel IS NULL OR taxa_adm_imovel >= 0)"
        )
    if "tipo_operacao" not in columns:
        db.execute("ALTER TABLE imoveis ADD COLUMN tipo_operacao TEXT")
    if "cliente_energia_solar_id" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN cliente_energia_solar_id INTEGER "
            "REFERENCES inquilinos_clientes (id) ON DELETE RESTRICT"
        )
    if "repasse_iptu" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN repasse_iptu INTEGER NOT NULL DEFAULT 0 "
            "CHECK (repasse_iptu IN (0, 1))"
        )
    if "valor_iptu" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN valor_iptu REAL "
            "CHECK (valor_iptu IS NULL OR valor_iptu >= 0)"
        )
    if "repasse_taxa_condominio" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN repasse_taxa_condominio INTEGER "
            "NOT NULL DEFAULT 0 CHECK (repasse_taxa_condominio IN (0, 1))"
        )
    if "valor_condominio" not in columns:
        db.execute(
            "ALTER TABLE imoveis ADD COLUMN valor_condominio REAL "
            "CHECK (valor_condominio IS NULL OR valor_condominio >= 0)"
        )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_imoveis_cliente_energia_solar "
        "ON imoveis (cliente_energia_solar_id)"
    )

    if "energia_solar" in columns:
        db.execute(
            """
            UPDATE imoveis
            SET tipo_operacao = CASE
                WHEN energia_solar = 1 THEN 'ENERGIA SOLAR'
                ELSE 'ALUGUEL'
            END
            WHERE tipo_operacao IS NULL
            """
        )
    else:
        db.execute(
            "UPDATE imoveis SET tipo_operacao = 'ALUGUEL' WHERE tipo_operacao IS NULL"
        )

    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS unidades_geracao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            responsavel INTEGER NOT NULL,
            cep TEXT,
            endereco TEXT,
            estado TEXT,
            cidade TEXT,
            bairro TEXT,
            numero TEXT,
            complemento TEXT,
            inscricao_mun TEXT,
            numero_instalacao TEXT,
            numero_unidade_geradora_consumidora TEXT,
            geracao_mensal_kwh INTEGER CHECK (
                geracao_mensal_kwh IS NULL OR (
                    typeof(geracao_mensal_kwh) = 'integer' AND
                    geracao_mensal_kwh >= 0 AND
                    geracao_mensal_kwh <= {MAX_MONTHLY_GENERATION_KWH}
                )
            ),
            preco_venda_kwh INTEGER CHECK (
                preco_venda_kwh IS NULL OR (
                    typeof(preco_venda_kwh) = 'integer' AND
                    preco_venda_kwh >= 0
                )
            ),
            FOREIGN KEY (responsavel) REFERENCES proprietario (id) ON DELETE RESTRICT
        )
        """
    )

    generation_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(unidades_geracao)").fetchall()
    }
    if "numero_instalacao" not in generation_columns:
        db.execute(
            "ALTER TABLE unidades_geracao ADD COLUMN numero_instalacao TEXT"
        )
    if "numero_unidade_geradora_consumidora" not in generation_columns:
        db.execute(
            "ALTER TABLE unidades_geracao "
            "ADD COLUMN numero_unidade_geradora_consumidora TEXT"
        )
    if "preco_venda_kwh" not in generation_columns:
        db.execute(
            "ALTER TABLE unidades_geracao ADD COLUMN preco_venda_kwh INTEGER "
            "CHECK (preco_venda_kwh IS NULL OR "
            "(typeof(preco_venda_kwh) = 'integer' AND preco_venda_kwh >= 0))"
        )

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS imovel_unidade_geradora (
            imovel_id INTEGER PRIMARY KEY,
            unidade_geradora_id INTEGER NOT NULL,
            FOREIGN KEY (imovel_id) REFERENCES imoveis (id) ON DELETE CASCADE,
            FOREIGN KEY (unidade_geradora_id) REFERENCES unidades_geracao (id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_imovel_unidade_geradora_unidade
            ON imovel_unidade_geradora (unidade_geradora_id);
        """
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
            status TEXT NOT NULL DEFAULT 'ATIVO' CHECK (
                status IN ('ATIVO', 'ENCERRADO')
            ),
            FOREIGN KEY (imovel_id) REFERENCES imoveis (id) ON DELETE RESTRICT,
            FOREIGN KEY (inquilino_id) REFERENCES inquilinos_clientes (id) ON DELETE RESTRICT,
            CHECK (data_fim >= data_inicio)
        )
        """
    )
    contract_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(contratos)").fetchall()
    }
    if "status" not in contract_columns:
        db.execute(
            "ALTER TABLE contratos ADD COLUMN status TEXT NOT NULL DEFAULT 'ATIVO' "
            "CHECK (status IN ('ATIVO', 'ENCERRADO'))"
        )
    else:
        db.execute(
            """
            UPDATE contratos
            SET status = CASE
                WHEN UPPER(TRIM(COALESCE(status, ''))) = 'ENCERRADO'
                THEN 'ENCERRADO'
                ELSE 'ATIVO'
            END
            """
        )

    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_contratos_imovel_status_inicio
            ON contratos (imovel_id, status, data_inicio, id)
        """
    )

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS contrato_periodos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contrato_id INTEGER NOT NULL,
            data_inicio TEXT NOT NULL,
            data_fim TEXT NOT NULL,
            valor_aluguel REAL NOT NULL CHECK (valor_aluguel >= 0),
            dia_pagamento INTEGER CHECK (
                dia_pagamento IS NULL OR (dia_pagamento >= 1 AND dia_pagamento <= 31)
            ),
            valor_caucao REAL CHECK (valor_caucao IS NULL OR valor_caucao >= 0),
            data_pagamento_caucao TEXT,
            data_fim_anterior TEXT,
            FOREIGN KEY (contrato_id) REFERENCES contratos (id) ON DELETE CASCADE,
            CHECK (data_fim >= data_inicio)
        );
        CREATE INDEX IF NOT EXISTS idx_contrato_periodos_contrato_inicio
            ON contrato_periodos (contrato_id, data_inicio, id);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_contrato_periodos_contrato_inicio
            ON contrato_periodos (contrato_id, data_inicio);
        INSERT INTO contrato_periodos
            (contrato_id, data_inicio, data_fim, valor_aluguel, valor_caucao)
        SELECT c.id, c.data_inicio, c.data_fim, c.valor_aluguel, c.valor_caucao
        FROM contratos AS c
        WHERE NOT EXISTS (
            SELECT 1 FROM contrato_periodos AS cp WHERE cp.contrato_id = c.id
        );
        """
    )

    period_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(contrato_periodos)").fetchall()
    }
    if "dia_pagamento" not in period_columns:
        db.execute(
            """
            ALTER TABLE contrato_periodos ADD COLUMN dia_pagamento INTEGER CHECK (
                dia_pagamento IS NULL OR (dia_pagamento >= 1 AND dia_pagamento <= 31)
            )
            """
        )


def normalize_existing_data(db: sqlite3.Connection) -> None:
    """Normalize text already stored by an earlier version of the app."""

    fields_by_table = {
        "proprietario": PERSON_FIELDS,
        "inquilinos_clientes": CLIENT_FIELDS,
        "imoveis": (
            "tipo_imovel",
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
            "tipo_operacao",
            "unidade_geradora_legada",
        ),
        "unidades_geracao": (
            "cep",
            "endereco",
            "estado",
            "cidade",
            "bairro",
            "numero",
            "complemento",
            "inscricao_mun",
            "numero_instalacao",
            "numero_unidade_geradora_consumidora",
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


def legacy_generation_identifier(value: Any) -> str | None:
    """Return a safe lookup key for a legacy free-text generation-unit value."""

    if value is None:
        return None
    text = repair_text_encoding(str(value)).strip().upper()
    if not text or any(marker in text for marker in ("\ufffd", "Ã", "Â")):
        return None
    if text.startswith("UNIDADE #") and text[9:].strip().isdigit():
        return text[9:].strip()
    return text


def migrate_legacy_generation_links(db: sqlite3.Connection) -> None:
    """Convert uniquely identifiable legacy unit text into FK links."""

    identifiers: dict[str, set[int]] = {}
    units = db.execute(
        """
        SELECT u.id, u.inscricao_mun, u.numero_instalacao,
               u.numero_unidade_geradora_consumidora
        FROM unidades_geracao AS u
        JOIN proprietario AS p ON p.id = u.responsavel
        """
    ).fetchall()
    for unit in units:
        values = [
            str(unit["id"]),
            unit["inscricao_mun"],
            unit["numero_instalacao"],
            unit["numero_unidade_geradora_consumidora"],
        ]
        for value in values:
            key = legacy_generation_identifier(value)
            if key:
                identifiers.setdefault(key, set()).add(unit["id"])

    properties = db.execute(
        """
        SELECT i.id, i.unidade_geradora_legada
        FROM imoveis AS i
        WHERE i.unidade_geradora_legada IS NOT NULL
          AND TRIM(i.unidade_geradora_legada) <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM imovel_unidade_geradora AS link
              WHERE link.imovel_id = i.id
          )
        """
    ).fetchall()
    for property_row in properties:
        key = legacy_generation_identifier(property_row["unidade_geradora_legada"])
        matches = identifiers.get(key, set()) if key else set()
        if len(matches) == 1:
            db.execute(
                """
                INSERT OR IGNORE INTO imovel_unidade_geradora
                    (imovel_id, unidade_geradora_id)
                VALUES (?, ?)
                """,
                (property_row["id"], next(iter(matches))),
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


def parse_decimal(
    value: Any,
    label: str,
    *,
    required: bool = False,
    max_decimal_places: int | None = None,
) -> float | None:
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

    if max_decimal_places is not None:
        if not number.is_finite():
            raise ValueError(f"{label} deve ser um número válido.")
        normalized = number.normalize()
        if normalized.as_tuple().exponent < -max_decimal_places:
            raise ValueError(
                f"{label} pode ter no máximo {max_decimal_places} casas decimais."
            )

    if number < 0:
        raise ValueError(f"{label} não pode ser negativo.")
    return float(number)


def parse_sale_price(value: Any, *, required: bool = False) -> int | None:
    """Parse a Brazilian monetary value into exact ten-thousandths."""

    label = "Preço de venda"
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{label} Ã© obrigatÃ³rio.")
        return None

    if isinstance(value, bool):
        raise ValueError(f"{label} deve ser um nÃºmero vÃ¡lido.")

    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        if required:
            raise ValueError(f"{label} Ã© obrigatÃ³rio.")
        return None

    try:
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} deve ser um nÃºmero vÃ¡lido.") from None

    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} deve ser um nÃºmero nÃ£o negativo.")
    if number.as_tuple().exponent < -4:
        raise ValueError(f"{label} pode ter no mÃ¡ximo 4 casas decimais.")

    scaled = number * SALE_PRICE_SCALE
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{label} pode ter no mÃ¡ximo 4 casas decimais.")
    scaled_value = int(scaled)
    if scaled_value > SALE_PRICE_MAX_SCALED:
        raise ValueError(f"{label} estÃ¡ fora do limite permitido.")
    return scaled_value


def format_sale_price(value: Any) -> str | None:
    """Return the exact API representation of a scaled sale price."""

    if value is None:
        return None
    decimal_value = Decimal(int(value)) / Decimal(SALE_PRICE_SCALE)
    return format(decimal_value, "f").rstrip("0").rstrip(".") or "0"


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


def client_values(data: dict[str, Any]) -> tuple[Any, ...]:
    values = person_values(data)
    return (*values[:4], clean_text(data.get("nome_contato")), *values[4:])


def property_values(
    data: dict[str, Any], db: sqlite3.Connection
) -> tuple[tuple[Any, ...], int | None]:
    property_type = clean_text(data.get("tipo_imovel"))
    if not property_type:
        raise ValueError("Tipo de imóvel é obrigatório.")
    if property_type not in TIPOS_IMOVEL:
        raise ValueError("Tipo de imóvel inválido.")

    operation_type = clean_text(data.get("tipo_operacao"))
    if not operation_type:
        raise ValueError("Tipo de operação é obrigatório.")
    if operation_type not in TIPOS_OPERACAO:
        raise ValueError("Tipo de operação inválido.")

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

    generation_unit_id = optional_foreign_key(
        data.get("unidade_geradora_id"),
        "unidade geradora",
        "unidades_geracao",
        db,
    )
    if generation_unit_id is not None and db.execute(
        """
        SELECT 1
        FROM unidades_geracao AS u
        JOIN proprietario AS p ON p.id = u.responsavel
        WHERE u.id = ?
        """,
        (generation_unit_id,),
    ).fetchone() is None:
        raise ValueError("A unidade geradora selecionada nÃ£o estÃ¡ disponÃ­vel.")
    if data.get("unidade_geradora") not in (None, ""):
        raise ValueError(
            "A unidade geradora deve ser informada pelo identificador da unidade cadastrada."
        )

    solar_client_id = optional_foreign_key(
        data.get("cliente_energia_solar_id"),
        "cliente de energia solar",
        "inquilinos_clientes",
        db,
    )
    if generation_unit_id is not None and solar_client_id is None:
        raise ValueError(
            "Cliente energia solar e obrigatorio quando uma unidade geradora e selecionada."
        )

    rent = parse_decimal(data.get("aluguel"), "Aluguel", required=True)
    iptu_value = parse_decimal(
        data.get("valor_iptu"),
        "Valor IPTU",
        max_decimal_places=2,
    )
    condominium_value = parse_decimal(
        data.get("valor_condominio"),
        "Valor condomínio",
        max_decimal_places=2,
    )
    administration_fee = parse_decimal(
        data.get("taxa_adm_imovel"),
        "Taxa adm. imóvel",
        max_decimal_places=2,
    )
    energy_percentage = parse_decimal(
        data.get("percentual_energia"),
        "Percentual de energia",
        required=generation_unit_id is not None,
    )
    if energy_percentage is not None and energy_percentage > 100:
        raise ValueError("Percentual de energia deve estar entre 0 e 100.")

    return (
        (
            property_type,
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
            parse_boolean(data.get("adm_propriedade"), "Cobrança energia solar"),
            parse_boolean(data.get("imobiliaria"), "Administração por imobiliária"),
            administration_fee,
            operation_type,
            energy_percentage,
            solar_client_id,
            parse_boolean(data.get("repasse_iptu"), "Repasse IPTU"),
            iptu_value,
            parse_boolean(
                data.get("repasse_taxa_condominio"),
                "Repasse taxa de condomínio",
            ),
            condominium_value,
        ),
        generation_unit_id,
    )


def parse_monthly_generation(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("A estimativa de geração mensal deve ser um número inteiro.")

    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError(
            "A estimativa de geração mensal deve ser um número inteiro entre 0 e "
            f"{MAX_MONTHLY_GENERATION_KWH:,}.".replace(",", ".")
        )

    generation = int(text)
    if generation > MAX_MONTHLY_GENERATION_KWH:
        raise ValueError(
            "A estimativa de geração mensal deve estar entre 0 e "
            f"{MAX_MONTHLY_GENERATION_KWH:,}.".replace(",", ".")
        )
    return generation


def generation_unit_values(
    data: dict[str, Any], db: sqlite3.Connection
) -> tuple[Any, ...]:
    responsible_id = parse_foreign_key(
        data.get("responsavel"), "proprietário", "proprietario", db
    )

    estado = clean_text(data.get("estado"))
    if estado:
        estado = estado.upper()
        if estado not in UF_VALIDAS:
            raise ValueError("Estado inválido.")

    return (
        responsible_id,
        normalize_digits(data.get("cep"), "cep", {8}),
        clean_text(data.get("endereco")),
        estado,
        clean_text(data.get("cidade")),
        clean_text(data.get("bairro")),
        clean_text(data.get("numero")),
        clean_text(data.get("complemento")),
        clean_text(data.get("inscricao_mun")),
        clean_text(data.get("numero_instalacao")),
        clean_text(data.get("numero_unidade_geradora_consumidora")),
        parse_monthly_generation(data.get("geracao_mensal_kwh")),
        parse_sale_price(data.get("preco_venda_kwh")),
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


def optional_foreign_key(
    value: Any,
    label: str,
    table: str,
    db: sqlite3.Connection,
) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_foreign_key(value, label, table, db)


def optional_owner_filter(db: sqlite3.Connection) -> tuple[int, ...] | None:
    """Parse repeated owner filters, keeping absent/empty values global."""

    values = request.args.getlist("proprietario_id")
    owner_ids: list[int] = []
    for value in values:
        if value is None or not str(value).strip():
            continue
        owner_id = parse_foreign_key(value, "proprietário", "proprietario", db)
        if owner_id not in owner_ids:
            owner_ids.append(owner_id)
    return tuple(owner_ids) or None


def optional_property_type_filter() -> tuple[str, ...] | None:
    """Parse repeated property-type filters, keeping empty values global."""

    values = request.args.getlist("tipo_imovel")
    property_types: list[str] = []
    for value in values:
        if value is None or not str(value).strip():
            continue
        property_type = clean_text(value)
        if property_type not in TIPOS_IMOVEL:
            raise ValueError("Tipo de imóvel inválido.")
        if property_type not in property_types:
            property_types.append(property_type)
    return tuple(property_types) or None


def optional_boolean_filter(value: Any, label: str) -> int | None:
    """Parse an optional boolean query parameter, preserving empty as unfiltered."""

    if value is None or not str(value).strip():
        return None
    return parse_boolean(value, label)


def property_filter_conditions(
    db: sqlite3.Connection, *, include_solar: bool = True
) -> tuple[list[str], tuple[Any, ...]]:
    """Build the shared property predicates used by filtered endpoints."""

    owner_ids = optional_owner_filter(db)
    property_types = optional_property_type_filter()
    solar_charge = (
        optional_boolean_filter(
            request.args.get("adm_propriedade"), "Cobrança solar"
        )
        if include_solar
        else None
    )
    conditions: list[str] = []
    params: list[Any] = []
    if owner_ids is not None:
        placeholders = ", ".join("?" for _ in owner_ids)
        conditions.append(f"i.responsavel IN ({placeholders})")
        params.extend(owner_ids)
    if property_types is not None:
        placeholders = ", ".join("?" for _ in property_types)
        conditions.append(f"i.tipo_imovel IN ({placeholders})")
        params.extend(property_types)
    if solar_charge is not None:
        conditions.append("i.adm_propriedade = ?")
        params.append(solar_charge)

    return conditions, tuple(params)


def property_filter_clause(db: sqlite3.Connection) -> tuple[str, tuple[Any, ...]]:
    """Build the shared property scope used by the dashboard and property-based lists."""

    conditions, params = property_filter_conditions(db)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where_clause, params


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


def parse_contract_status(value: Any, default: str | None = None) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is not None:
            return default
        raise ValueError("Status é obrigatório.")

    status = clean_text(value)
    if status not in CONTRACT_STATUSES:
        raise ValueError("Status inválido. Use Ativo ou Encerrado.")
    return status


def contract_values(
    data: dict[str, Any],
    db: sqlite3.Connection,
    *,
    status_default: str | None = None,
) -> tuple[Any, ...]:
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
        parse_contract_status(data.get("status"), status_default),
    )


def optional_contract_date(value: Any, label: str) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_contract_date(value, label).isoformat()


def parse_contract_payment_day(value: Any, *, required: bool = True) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError("Dia de pagamento é obrigatório.")
        return None
    if isinstance(value, bool):
        raise ValueError("Dia de pagamento deve ser um número inteiro entre 1 e 31.")

    if isinstance(value, int):
        day = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        day = int(value.strip())
    else:
        raise ValueError("Dia de pagamento deve ser um número inteiro entre 1 e 31.")

    if not 1 <= day <= 31:
        raise ValueError("Dia de pagamento deve estar entre 1 e 31.")
    return day


_MISSING = object()


def contract_period_values(
    data: dict[str, Any],
    *,
    payment_day_default: Any = _MISSING,
    payment_day_required: bool = True,
) -> tuple[Any, ...]:
    start_date = parse_contract_date(data.get("data_inicio"), "Data de início")
    end_date = parse_contract_date(data.get("data_fim"), "Data de fim")
    if end_date < start_date:
        raise ValueError("A data de fim não pode ser anterior à data de início.")

    if "dia_pagamento" in data:
        payment_day = parse_contract_payment_day(
            data.get("dia_pagamento"), required=payment_day_required
        )
    elif payment_day_default is not _MISSING:
        payment_day = payment_day_default
    else:
        payment_day = parse_contract_payment_day(None, required=payment_day_required)

    return (
        start_date.isoformat(),
        end_date.isoformat(),
        parse_decimal(data.get("valor_aluguel"), "Valor do aluguel", required=True),
        payment_day,
        parse_decimal(data.get("valor_caucao"), "Valor da caução"),
        optional_contract_date(
            data.get("data_pagamento_caucao"), "Data de pagamento da caução"
        ),
    )


def get_contract_periods(db: sqlite3.Connection, contract_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT id, contrato_id, data_inicio, data_fim, valor_aluguel, dia_pagamento,
               valor_caucao, data_pagamento_caucao, data_fim_anterior
        FROM contrato_periodos
        WHERE contrato_id = ?
        ORDER BY data_inicio ASC, id ASC
        """,
        (contract_id,),
    ).fetchall()
    periods = []
    for order, row in enumerate(rows, start=1):
        period = dict(row)
        period["ordem"] = order
        period["atual"] = order == len(rows)
        periods.append(period)
    return periods


def validate_period_timeline(periods: list[sqlite3.Row | dict[str, Any]]) -> None:
    ordered = sorted(periods, key=lambda period: (period["data_inicio"], period["id"]))
    for previous, current in zip(ordered, ordered[1:]):
        if current["data_inicio"] <= previous["data_inicio"]:
            raise ValueError("A data de início de cada período deve ser posterior à anterior.")
        if previous["data_fim"] >= current["data_inicio"]:
            raise ValueError("Os períodos contratuais não podem se sobrepor.")


def sync_contract_current_period(db: sqlite3.Connection, contract_id: int) -> None:
    latest = db.execute(
        """
        SELECT data_inicio, data_fim, valor_aluguel, valor_caucao
        FROM contrato_periodos
        WHERE contrato_id = ?
        ORDER BY data_inicio DESC, id DESC
        LIMIT 1
        """,
        (contract_id,),
    ).fetchone()
    if latest is None:
        raise ValueError("O contrato precisa ter ao menos um período.")
    db.execute(
        """
        UPDATE contratos
        SET data_inicio = ?, data_fim = ?, valor_aluguel = ?, valor_caucao = ?
        WHERE id = ?
        """,
        (
            latest["data_inicio"],
            latest["data_fim"],
            latest["valor_aluguel"],
            latest["valor_caucao"],
            contract_id,
        ),
    )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def generation_unit_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    data = row_dict(row)
    if data is None:
        return None
    data["preco_venda_kwh"] = format_sale_price(data.get("preco_venda_kwh"))
    return data


def get_property(db: sqlite3.Connection, record_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT i.id, i.apelido, i.tipo_imovel, i.responsavel, i.cep, i.endereco,
               i.estado, i.cidade, i.bairro, i.numero, i.complemento,
               i.inscricao_mun, i.aluguel, i.numero_energia, i.numero_agua,
                       i.adm_propriedade, i.imobiliaria, i.taxa_adm_imovel, i.tipo_operacao,
               link.unidade_geradora_id,
               COALESCE(NULLIF(TRIM(unit.inscricao_mun), ''), 'Unidade #' || unit.id)
                   AS unidade_geradora_identificacao,
               i.unidade_geradora_legada, i.percentual_energia,
               i.cliente_energia_solar_id,
               i.repasse_iptu, i.valor_iptu,
               i.repasse_taxa_condominio, i.valor_condominio,
               p.nome_completo AS responsavel_nome
        FROM imoveis AS i
        JOIN proprietario AS p ON p.id = i.responsavel
        LEFT JOIN imovel_unidade_geradora AS link ON link.imovel_id = i.id
        LEFT JOIN unidades_geracao AS unit ON unit.id = link.unidade_geradora_id
        WHERE i.id = ?
        """,
        (record_id,),
    ).fetchone()


def sync_property_generation_unit(
    db: sqlite3.Connection, property_id: int, generation_unit_id: int | None
) -> None:
    db.execute(
        "DELETE FROM imovel_unidade_geradora WHERE imovel_id = ?",
        (property_id,),
    )
    if generation_unit_id is not None:
        db.execute(
            """
            INSERT INTO imovel_unidade_geradora
                (imovel_id, unidade_geradora_id)
            VALUES (?, ?)
            """,
            (property_id, generation_unit_id),
        )


def get_generation_unit(db: sqlite3.Connection, record_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT u.id, u.responsavel, u.cep, u.endereco, u.estado, u.cidade,
               u.bairro, u.numero, u.complemento, u.inscricao_mun,
               u.numero_instalacao, u.numero_unidade_geradora_consumidora,
               u.geracao_mensal_kwh, u.preco_venda_kwh,
               p.nome_completo AS responsavel_nome
        FROM unidades_geracao AS u
        JOIN proprietario AS p ON p.id = u.responsavel
        WHERE u.id = ?
        """,
        (record_id,),
    ).fetchone()


def get_generation_distribution(
    db: sqlite3.Connection, record_id: int
) -> dict[str, Any] | None:
    """Return the solar distribution rows linked to one generation unit."""

    unit = get_generation_unit(db, record_id)
    if unit is None:
        return None

    rows = db.execute(
        """
        SELECT i.id AS imovel_id,
               i.apelido AS imovel_nome,
               ic.id AS cliente_id,
               ic.nome_completo AS cliente_nome,
               i.percentual_energia AS percentual_distribuicao,
               i.adm_propriedade AS cobranca_solar
        FROM imovel_unidade_geradora AS link
        JOIN imoveis AS i ON i.id = link.imovel_id
        JOIN inquilinos_clientes AS ic
          ON ic.id = i.cliente_energia_solar_id
        WHERE link.unidade_geradora_id = ?
          AND i.percentual_energia IS NOT NULL
        ORDER BY i.apelido COLLATE NOCASE, i.id
        """,
        (record_id,),
    ).fetchall()

    distributions = []
    billings = []
    total_percentage = Decimal("0")
    distribution_kwh_values = []
    billing_kwh_values = []
    billing_amount_values = []
    for row in rows:
        distribution = row_dict(row)
        is_chargeable = bool(distribution.pop("cobranca_solar", 0))
        distribution["kwh_mes_estimado"] = estimate_distributed_generation(
            unit["geracao_mensal_kwh"], distribution["percentual_distribuicao"]
        )
        distribution["cliente_nome"] = repair_text_encoding(
            distribution["cliente_nome"]
        )
        distribution["imovel_nome"] = repair_text_encoding(
            distribution["imovel_nome"]
        )
        distributions.append(distribution)

        total_percentage += Decimal(str(distribution["percentual_distribuicao"]))
        distribution_kwh_values.append(distribution["kwh_mes_estimado"])

        if is_chargeable:
            monthly_charge = calculate_monthly_charge(
                distribution["kwh_mes_estimado"], unit["preco_venda_kwh"]
            )
            billing = {
                "imovel_id": distribution["imovel_id"],
                "imovel_nome": distribution["imovel_nome"],
                "cliente_id": distribution["cliente_id"],
                "cliente_nome": distribution["cliente_nome"],
                "kwh_mes_estimado": distribution["kwh_mes_estimado"],
                "valor_mensal": format_monthly_charge(monthly_charge),
            }
            billings.append(billing)
            billing_kwh_values.append(billing["kwh_mes_estimado"])
            billing_amount_values.append(monthly_charge)

    identification = (
        repair_text_encoding(unit["inscricao_mun"])
        if unit["inscricao_mun"]
        else f"Unidade #{unit['id']}"
    )
    return {
        "unidade": {
            "id": unit["id"],
            "identificacao": identification,
        },
        "distribuicoes": distributions,
        "cobrancas": billings,
        "totais": {
            "distribuicao": {
                "quantidade_imoveis": len(distributions),
                "percentual_distribuicao": float(total_percentage),
                "kwh_mes_estimado": sum_nullable_integers(distribution_kwh_values),
            },
            "cobranca": {
                "quantidade_imoveis": len(billings),
                "kwh_mes_estimado": sum_nullable_integers(billing_kwh_values),
                "valor_mensal": sum_monthly_charges(billing_amount_values),
            },
        },
    }


def estimate_distributed_generation(
    monthly_generation: int | None, distribution_percentage: Any
) -> int | None:
    if monthly_generation is None or distribution_percentage is None:
        return None

    estimated_generation = (
        Decimal(str(monthly_generation))
        * Decimal(str(distribution_percentage))
        / Decimal("100")
    )
    return int(estimated_generation.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_monthly_charge(
    estimated_kwh: int | None, scaled_sale_price: int | None
) -> Decimal | None:
    if estimated_kwh is None or scaled_sale_price is None:
        return None

    monthly_charge = (
        Decimal(str(estimated_kwh))
        * Decimal(str(scaled_sale_price))
        / Decimal(SALE_PRICE_SCALE)
    )
    return monthly_charge.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_monthly_charge(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, ".2f")


def sum_nullable_integers(values: list[int | None]) -> int | None:
    if not values:
        return 0
    if any(value is None for value in values):
        return None
    return sum(values)


def sum_monthly_charges(values: list[Decimal | None]) -> str | None:
    if not values:
        return "0.00"
    if any(value is None for value in values):
        return None
    return format_monthly_charge(sum(values, Decimal("0.00")))


def pdf_first_client_name(value: Any) -> str:
    name = repair_text_encoding(str(value or "")).strip()
    return name.split()[0] if name else "Cliente não informado"


def pdf_count_label(value: Any) -> str:
    count = max(0, int(value or 0))
    return f"{count} imóvel" if count == 1 else f"{count} imóveis"


def pdf_integer(value: Any) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", ".")


def pdf_kwh_total(value: Any) -> str:
    try:
        formatted = pdf_integer(value)
    except (TypeError, ValueError):
        return "—"
    return formatted if formatted == "—" else f"{formatted} kWh"


def pdf_billing_sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, Decimal, int]:
    index, billing = item
    raw_value = billing.get("valor_mensal")
    if raw_value is None or raw_value == "":
        return (1, Decimal("0"), index)
    try:
        amount = Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        return (1, Decimal("0"), index)
    if not amount.is_finite():
        return (1, Decimal("0"), index)
    return (0, -amount, index)


def pdf_percentage(value: Any) -> str:
    if value is None:
        return "—"
    rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(rounded):,}".replace(",", ".") + " %"


def pdf_currency(value: Any) -> str:
    if value is None:
        return "—"
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, cents = format(amount, ".2f").split(".")
    return f"R$ {int(whole):,}".replace(",", ".") + f",{cents}"


def pdf_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    escaped = escape_xml(str(text)).replace("\n", "<br/>")
    return Paragraph(escaped, style)


PDF_DISTRIBUTION_COLORS = (
    "#4f63d9",
    "#36a77d",
    "#d9a83d",
    "#d95b67",
    "#8d6ac8",
    "#4aa9c8",
    "#d17a4f",
    "#6f7f9d",
)


def pdf_distribution_value(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(number, 0.0)


def pdf_distribute_label_positions(
    labels: list[dict[str, Any]],
    side: str,
    chart_height: float,
    label_margin: float,
    label_gap: float,
) -> None:
    side_labels = sorted(
        (label for label in labels if label["side"] == side),
        key=lambda label: label["target_y"],
    )
    next_y = label_margin
    for label in side_labels:
        label["label_y"] = max(label["target_y"], next_y)
        next_y = label["label_y"] + label_gap

    if not side_labels:
        return

    bottom_overflow = next_y - label_gap - (chart_height - label_margin)
    if bottom_overflow > 0:
        for label in side_labels:
            label["label_y"] -= bottom_overflow

    top_overflow = label_margin - side_labels[0]["label_y"]
    if top_overflow > 0:
        for label in side_labels:
            label["label_y"] += top_overflow


def build_distribution_chart(
    distributions: list[dict[str, Any]], width: float
) -> Drawing | None:
    positive_distributions = [
        (index, item, pdf_distribution_value(item.get("percentual_distribuicao")))
        for index, item in enumerate(distributions)
        if pdf_distribution_value(item.get("percentual_distribuicao")) > 0
    ]
    if not positive_distributions:
        return None

    chart_width = max(width, 300)
    chart_scale = min(0.7, chart_width / 520.0)
    base_size = 520.0
    radius = 150.0 * chart_scale
    label_radius = 220.0 * chart_scale
    label_gap = 20.0 * chart_scale
    label_horizontal_gap = 20.0 * chart_scale
    label_font_size = max(6.4, 11.5 * chart_scale)
    label_margin = max(3.0 * chart_scale, label_font_size)
    side_counts = {"left": 0, "right": 0}
    total = sum(value for _, _, value in positive_distributions)
    accumulated = 0.0
    for _, _, value in positive_distributions:
        sweep = value / total * 360.0
        mid_angle = (accumulated + sweep / 2) * math.pi / 180.0
        side = "left" if math.sin(mid_angle) < 0 else "right"
        side_counts[side] += 1
        accumulated += sweep
    max_side_count = max(max(side_counts.values()), 1)
    chart_height = max(
        base_size * chart_scale,
        max_side_count * label_gap + label_margin * 2,
    )
    center_x = chart_width / 2
    center_y = chart_height / 2

    labels: list[dict[str, Any]] = []
    accumulated = 0.0
    drawing = Drawing(chart_width, chart_height)
    for index, item, value in positive_distributions:
        sweep = value / total * 360.0
        mid_angle = (accumulated + sweep / 2) * math.pi / 180.0
        # PDF coordinates grow upward; invert Y so the chart starts at the top
        # and advances clockwise, matching the modal's SVG chart.
        target_x = center_x + math.sin(mid_angle) * label_radius
        target_y = center_y + math.cos(mid_angle) * label_radius
        side = "left" if target_x < center_x else "right"
        labels.append(
            {
                "index": index,
                "item": item,
                "value": value,
                "side": side,
                "target_y": target_y,
                "label_y": target_y,
            }
        )
        start_angle = 90.0 - accumulated - sweep
        end_angle = 90.0 - accumulated
        slice_offset = 6.0 * chart_scale
        drawing.add(
            Wedge(
                center_x + math.sin(mid_angle) * slice_offset,
                center_y + math.cos(mid_angle) * slice_offset,
                radius,
                start_angle,
                end_angle,
                fillColor=colors.HexColor(
                    PDF_DISTRIBUTION_COLORS[index % len(PDF_DISTRIBUTION_COLORS)]
                ),
                strokeColor=colors.white,
                strokeWidth=1.2,
            )
        )
        accumulated += sweep

    pdf_distribute_label_positions(
        labels,
        "left",
        chart_height,
        label_margin,
        label_gap,
    )
    pdf_distribute_label_positions(
        labels,
        "right",
        chart_height,
        label_margin,
        label_gap,
    )

    accumulated = 0.0
    for label in labels:
        is_left = label["side"] == "left"
        text_x = (
            center_x - radius - label_horizontal_gap
            if is_left
            else center_x + radius + label_horizontal_gap
        )
        elbow_x = (
            center_x - radius - 8.0 * chart_scale
            if is_left
            else center_x + radius + 8.0 * chart_scale
        )
        line_end_x = text_x + 4.0 * chart_scale if is_left else text_x - 4.0 * chart_scale
        value = label["value"]
        item = label["item"]
        mid_angle = (accumulated + value / 2) / total * 2 * math.pi
        target_x = center_x + math.sin(mid_angle) * (radius + 4.0 * chart_scale)
        target_y = center_y + math.cos(mid_angle) * (radius + 4.0 * chart_scale)
        stroke = colors.HexColor(
            PDF_DISTRIBUTION_COLORS[label["index"] % len(PDF_DISTRIBUTION_COLORS)]
        )
        drawing.add(
            Line(
                target_x,
                target_y,
                elbow_x,
                label["label_y"],
                strokeColor=stroke,
                strokeWidth=0.7,
            )
        )
        drawing.add(
            Line(
                elbow_x,
                label["label_y"],
                line_end_x,
                label["label_y"],
                strokeColor=stroke,
                strokeWidth=0.7,
            )
        )
        drawing.add(
            String(
                text_x,
                label["label_y"] - label_font_size / 3,
                f"{pdf_first_client_name(item.get('cliente_nome'))} · {pdf_percentage(value)}",
                fontName="Helvetica-Bold",
                fontSize=label_font_size,
                fillColor=colors.HexColor("#536076"),
                textAnchor="end" if is_left else "start",
            )
        )
        accumulated += value
    return drawing


def build_pdf_legend(
    distributions: list[dict[str, Any]],
    width: float,
    style: ParagraphStyle,
) -> Table | Paragraph:
    entries = [
        (index, item, pdf_distribution_value(item.get("percentual_distribuicao")))
        for index, item in enumerate(distributions)
    ]
    if not entries:
        return pdf_paragraph(
            "Nenhum imóvel vinculado com cliente e percentual de energia cadastrados.",
            style,
        )

    item_width = max((width - 8) / 2, 90)
    legend_rows: list[list[Table | Spacer]] = []
    for row_start in range(0, len(entries), 2):
        row: list[Table | Spacer] = []
        for index, item, value in entries[row_start:row_start + 2]:
            marker = Table(
                [[
                    "",
                    pdf_paragraph(
                        f"{pdf_first_client_name(item.get('cliente_nome'))} {pdf_percentage(value)}",
                        style,
                    ),
                ]],
                colWidths=[7, item_width - 7],
            )
            marker.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (0, 0),
                            colors.HexColor(
                                PDF_DISTRIBUTION_COLORS[
                                    index % len(PDF_DISTRIBUTION_COLORS)
                                ]
                            ),
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (0, 0), 0),
                        ("RIGHTPADDING", (0, 0), (0, 0), 0),
                        ("TOPPADDING", (0, 0), (0, 0), 0),
                        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
                        ("LEFTPADDING", (1, 0), (1, 0), 5),
                        ("RIGHTPADDING", (1, 0), (1, 0), 0),
                        ("TOPPADDING", (1, 0), (1, 0), 1),
                        ("BOTTOMPADDING", (1, 0), (1, 0), 1),
                    ]
                )
            )
            row.append(marker)
        if len(row) == 1:
            row.append(Spacer(item_width, 1))
        legend_rows.append(row)

    legend = Table(legend_rows, colWidths=[item_width, item_width], hAlign="LEFT")
    legend.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return legend


def build_pdf_panel(content: list[Any], width: float) -> Table:
    panel = Table([[item] for item in content], colWidths=[width], hAlign="LEFT")
    panel.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfe")),
                ("BOX", (0, 0), (-1, -1), 0.55, colors.HexColor("#e5eaf2")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return panel


def build_pdf_table(
    rows: list[list[str]],
    widths: list[float],
    *,
    header_style: ParagraphStyle,
    body_style: ParagraphStyle,
    total_style: ParagraphStyle,
    empty_message: str | None = None,
) -> Table:
    header = [pdf_paragraph(value, header_style) for value in rows[0]]
    body = [
        [pdf_paragraph(value, body_style) for value in row]
        for row in rows[1:-1]
    ]
    empty_row_index: int | None = None
    if empty_message is not None:
        empty_row_index = len(body) + 1
        body.append(
            [
                pdf_paragraph(empty_message, body_style),
                "",
                "",
            ]
        )
    total = [pdf_paragraph(value, total_style) for value in rows[-1]]
    table_rows = [header, *body, total]
    total_row_index = len(table_rows) - 1
    table = Table(
        table_rows,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=0,
    )
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f8")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dfe6f0")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, total_row_index), (-1, total_row_index), colors.HexColor("#f1f5fa")),
        ("LINEABOVE", (0, total_row_index), (-1, total_row_index), 1, colors.HexColor("#bfcbdc")),
    ]
    if empty_row_index is not None:
        commands.extend(
            [
                ("SPAN", (0, empty_row_index), (-1, empty_row_index)),
                ("ALIGN", (0, empty_row_index), (-1, empty_row_index), "CENTER"),
                ("TEXTCOLOR", (0, empty_row_index), (-1, empty_row_index), colors.HexColor("#9aa5b5")),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def draw_pdf_footer(canvas: Any, document: SimpleDocTemplate) -> None:
    canvas.saveState()
    page_width, _ = portrait(A4)
    footer_y = 8 * mm
    canvas.setStrokeColor(colors.HexColor("#dfe6f0"))
    canvas.setLineWidth(0.5)
    canvas.line(document.leftMargin, footer_y + 6, page_width - document.rightMargin, footer_y + 6)
    canvas.setFillColor(colors.HexColor("#7e8a9d"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(
        page_width - document.rightMargin,
        footer_y,
        f"Página {canvas.getPageNumber()} de 1",
    )
    canvas.restoreState()


def build_distribution_pdf(distribution: dict[str, Any]) -> BytesIO:
    buffer = BytesIO()
    page_width, page_height = portrait(A4)
    side_margin = 12 * mm
    top_margin = 10 * mm
    bottom_margin = 18 * mm
    document = SimpleDocTemplate(
        buffer,
        pagesize=(page_width, page_height),
        rightMargin=side_margin,
        leftMargin=side_margin,
        topMargin=top_margin,
        bottomMargin=bottom_margin,
        title="Relatório analítico de energia solar",
        author="PPA Aluguel",
    )
    content_width = page_width - side_margin * 2
    styles = getSampleStyleSheet()
    eyebrow_style = ParagraphStyle(
        "SolarReportEyebrow",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#a0aabd"),
        tracking=1.1,
        spaceAfter=2,
    )
    title_style = ParagraphStyle(
        "SolarReportTitle",
        parent=styles["Title"],
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=18,
        textColor=colors.HexColor("#38465d"),
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "SolarReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10.5,
        textColor=colors.HexColor("#6e7b8e"),
        spaceAfter=6,
    )
    summary_label_style = ParagraphStyle(
        "SolarReportSummaryLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#9aa5b5"),
    )
    summary_value_style = ParagraphStyle(
        "SolarReportSummaryValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=11,
        textColor=colors.HexColor("#38465d"),
    )
    panel_heading_style = ParagraphStyle(
        "SolarReportPanelHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=11,
        textColor=colors.HexColor("#38465d"),
        spaceAfter=3,
    )
    table_header_style = ParagraphStyle(
        "SolarReportTableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.4,
        leading=7.2,
        textColor=colors.HexColor("#536076"),
    )
    table_body_style = ParagraphStyle(
        "SolarReportTableBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.4,
        leading=8.5,
        textColor=colors.HexColor("#536076"),
    )
    table_total_style = ParagraphStyle(
        "SolarReportTableTotal",
        parent=table_body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#38465d"),
    )
    chart_empty_style = ParagraphStyle(
        "SolarReportChartEmpty",
        parent=table_body_style,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#9aa5b5"),
        spaceBefore=14,
        spaceAfter=14,
    )
    legend_style = ParagraphStyle(
        "SolarReportLegend",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=6.8,
        leading=8,
        textColor=colors.HexColor("#6e7b8e"),
    )

    unit = distribution.get("unidade") or {}
    identification = unit.get("identificacao") or "Unidade sem identificação"
    distributions = list(distribution.get("distribuicoes") or [])
    billings = list(distribution.get("cobrancas") or [])
    totals = distribution.get("totais") or {}
    distribution_totals = totals.get("distribuicao") or {}
    billing_totals = totals.get("cobranca") or {}
    sorted_distributions = [
        item[1]
        for item in sorted(
            enumerate(distributions),
            key=lambda item: (
                -pdf_distribution_value(item[1].get("percentual_distribuicao")),
                item[0],
            ),
        )
    ]
    sorted_billings = [
        item[1]
        for item in sorted(enumerate(billings), key=pdf_billing_sort_key)
    ]

    header = Table(
        [
            [pdf_paragraph("Análise", eyebrow_style)],
            [pdf_paragraph("Distribuição da unidade", title_style)],
            [
                pdf_paragraph(
                    "Confira os clientes e percentuais dos imóveis vinculados.",
                    subtitle_style,
                )
            ],
            [
                Table(
                    [[
                        pdf_paragraph("Unidade geradora", summary_label_style),
                        pdf_paragraph(str(identification), summary_value_style),
                    ]],
                    colWidths=[content_width * 0.32, content_width * 0.68],
                    hAlign="LEFT",
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfe")),
                            ("BOX", (0, 0), (-1, -1), 0.55, colors.HexColor("#e5eaf2")),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    ),
                )
            ],
        ],
        colWidths=[content_width],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 2), (-1, 2), 6),
                ("BOTTOMPADDING", (0, 3), (-1, 3), 0),
            ]
        )
    )

    chart_width = content_width - 28
    chart = build_distribution_chart(sorted_distributions, chart_width)
    chart_content: list[Any] = [
        pdf_paragraph("Distribuição por cliente", panel_heading_style),
    ]
    if chart is not None:
        chart_content.append(chart)
    else:
        chart_content.append(
            pdf_paragraph(
                "Não há percentuais maiores que zero para desenhar o gráfico.",
                chart_empty_style,
            )
        )
    chart_content.append(build_pdf_legend(sorted_distributions, chart_width, legend_style))
    chart_panel = build_pdf_panel(chart_content, content_width - 8)

    panel_width = (content_width - 18) / 2
    inner_table_width = panel_width - 20
    table_widths = [
        inner_table_width * 0.39,
        inner_table_width * 0.31,
        inner_table_width * 0.30,
    ]
    distribution_rows = [
        [
            "Cliente energia solar",
            "Percentual de\ndistribuição (%)",
            "kWh/mês\nestimado",
        ],
        *[
            [
                pdf_first_client_name(item.get("cliente_nome")),
                pdf_percentage(item.get("percentual_distribuicao")),
                pdf_integer(item.get("kwh_mes_estimado")),
            ]
            for item in sorted_distributions
        ],
        [
            "Total",
            pdf_percentage(distribution_totals.get("percentual_distribuicao")),
            pdf_kwh_total(distribution_totals.get("kwh_mes_estimado")),
        ],
    ]
    billing_rows = [
        ["Cliente energia solar", "kWh/mês\nestimado", "R$/mês"],
        *[
            [
                pdf_first_client_name(item.get("cliente_nome")),
                pdf_integer(item.get("kwh_mes_estimado")),
                pdf_currency(item.get("valor_mensal")),
            ]
            for item in sorted_billings
        ],
        [
            "Total",
            pdf_integer(billing_totals.get("kwh_mes_estimado")),
            pdf_currency(billing_totals.get("valor_mensal")),
        ],
    ]
    distribution_table = build_pdf_table(
        distribution_rows,
        table_widths,
        header_style=table_header_style,
        body_style=table_body_style,
        total_style=table_total_style,
        empty_message=(
            "Nenhum imóvel vinculado com cliente e percentual de energia cadastrados."
            if not sorted_distributions
            else None
        ),
    )
    billing_table = build_pdf_table(
        billing_rows,
        table_widths,
        header_style=table_header_style,
        body_style=table_body_style,
        total_style=table_total_style,
        empty_message=(
            "Nenhum imóvel com Cobrança solar igual a SIM."
            if not billings
            else None
        ),
    )
    distribution_panel = build_pdf_panel(
        [
            pdf_paragraph(
                f"Tabela de distribuição {pdf_count_label(distribution_totals.get('quantidade_imoveis'))}",
                panel_heading_style,
            ),
            distribution_table,
        ],
        panel_width,
    )
    billing_panel = build_pdf_panel(
        [
            pdf_paragraph(
                f"Tabela de cobrança {pdf_count_label(billing_totals.get('quantidade_imoveis'))}",
                panel_heading_style,
            ),
            billing_table,
        ],
        panel_width,
    )

    body = Table(
        [
            [chart_panel, "", ""],
            [distribution_panel, "", billing_panel],
        ],
        colWidths=[panel_width, 10, panel_width],
        hAlign="LEFT",
    )
    body.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (-1, 0)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    story = [
        KeepInFrame(
            content_width,
            page_height - top_margin - bottom_margin,
            [header, Spacer(1, 7), body],
            mode="shrink",
            hAlign="LEFT",
            vAlign="TOP",
        )
    ]
    document.build(story, onFirstPage=draw_pdf_footer)
    buffer.seek(0)
    return buffer


def get_contract(db: sqlite3.Connection, record_id: int) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT c.*,
               (SELECT cp.dia_pagamento
                FROM contrato_periodos AS cp
                WHERE cp.contrato_id = c.id
                ORDER BY cp.data_inicio DESC, cp.id DESC
                LIMIT 1) AS dia_pagamento,
               (SELECT cp.data_pagamento_caucao
                FROM contrato_periodos AS cp
                WHERE cp.contrato_id = c.id
                ORDER BY cp.data_inicio DESC, cp.id DESC
                LIMIT 1) AS data_pagamento_caucao,
               i.apelido AS imovel_nome,
               ic.nome_completo AS inquilino_nome
        FROM contratos AS c
        JOIN imoveis AS i ON i.id = c.imovel_id
        JOIN inquilinos_clientes AS ic ON ic.id = c.inquilino_id
        WHERE c.id = ?
        """,
        (record_id,),
    ).fetchone()


def contract_response(db: sqlite3.Connection, record_id: int) -> dict[str, Any] | None:
    row = get_contract(db, record_id)
    if row is None:
        return None
    response = row_dict(row)
    periods = get_contract_periods(db, record_id)
    response["periodos"] = periods
    response["periodo_atual_id"] = periods[-1]["id"] if periods else None
    return response


REPORT_MONEY_QUANTUM = Decimal("0.01")
REPORT_PERCENTAGE_QUANTUM = Decimal("0.01")


def report_money(value: Any) -> Decimal:
    """Return a report monetary value rounded to Brazilian currency cents."""

    if value is None or value == "":
        return Decimal("0.00")
    return Decimal(str(value)).quantize(REPORT_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def report_percentage(net: Decimal, gross: Decimal) -> Decimal:
    """Calculate a report percentage without dividing by zero."""

    if gross == 0:
        return Decimal("0.00")
    return ((net / gross) * Decimal("100")).quantize(
        REPORT_PERCENTAGE_QUANTUM, rounding=ROUND_HALF_UP
    )


def report_number(value: Decimal) -> float:
    """Convert a Decimal report value to the numeric JSON representation."""

    return float(value)


def report_property_expenses(row: sqlite3.Row) -> tuple[Decimal, Decimal]:
    """Calculate the owner-borne monthly IPTU and condominium expenses."""

    row_keys = row.keys()
    iptu_value = row["valor_iptu"] if "valor_iptu" in row_keys else row["iptu_anual"]
    condominium_repass = (
        row["repasse_taxa_condominio"]
        if "repasse_taxa_condominio" in row_keys
        else row["repasse_condominio"]
    )
    condominium_value = row["valor_condominio"]
    iptu = (
        Decimal("0.00")
        if row["repasse_iptu"]
        else report_money(report_money(iptu_value) / Decimal("12"))
    )
    condominium = (
        Decimal("0.00")
        if condominium_repass
        else report_money(condominium_value)
    )
    return iptu, condominium


def property_financials(
    gross_rent: Any,
    row: sqlite3.Row,
    *,
    include_administration_fee: bool = True,
) -> dict[str, Decimal]:
    """Share the report's net-rent calculation with consolidated views."""

    gross = report_money(gross_rent)
    iptu, condominium = report_property_expenses(row)
    administration_fee = (
        report_money(row["taxa_adm_imovel"])
        if include_administration_fee and row["imobiliaria"]
        else Decimal("0.00")
    )
    return {
        "aluguel_bruto": gross,
        "iptu_descontado": iptu,
        "condominio_descontado": condominium,
        "taxa_administracao": administration_fee,
        "aluguel_liquido": report_money(
            gross - iptu - condominium - administration_fee
        ),
    }


def escape_like_term(value: str) -> str:
    """Escape user-controlled LIKE wildcards before binding a search term."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def quick_search_response(
    db: sqlite3.Connection, search_term: Any = ""
) -> list[dict[str, Any]]:
    """Return one searchable financial row for each property."""

    term = str(search_term or "").strip().upper()
    digits = re.sub(r"\D", "", term)
    conditions: list[str] = []
    params: list[str] = []
    if term:
        conditions.append("search_text LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like_term(term)}%")
    if digits:
        conditions.append("search_digits LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like_term(digits)}%")
    search_clause = f"WHERE {' OR '.join(conditions)}" if conditions else ""

    rows = db.execute(
        f"""
        WITH active_contract_periods AS (
            SELECT c.id AS contrato_id,
                   c.imovel_id,
                   c.inquilino_id,
                   cp.id AS periodo_id,
                   cp.data_inicio AS periodo_data_inicio,
                   cp.valor_aluguel AS contrato_valor_aluguel
            FROM contratos AS c
            JOIN contrato_periodos AS cp ON cp.contrato_id = c.id
            WHERE c.status = 'ATIVO'
        ),
        current_active_contracts AS (
            SELECT candidate.*
            FROM active_contract_periods AS candidate
            WHERE NOT EXISTS (
                SELECT 1
                FROM active_contract_periods AS newer
                WHERE newer.imovel_id = candidate.imovel_id
                  AND (
                      newer.periodo_data_inicio > candidate.periodo_data_inicio
                      OR (
                          newer.periodo_data_inicio = candidate.periodo_data_inicio
                          AND newer.periodo_id > candidate.periodo_id
                      )
                      OR (
                          newer.periodo_data_inicio = candidate.periodo_data_inicio
                          AND newer.periodo_id = candidate.periodo_id
                          AND newer.contrato_id > candidate.contrato_id
                      )
                  )
            )
        ),
        property_rows AS (
            SELECT i.id AS imovel_id,
                   i.apelido AS imovel,
                   i.inscricao_mun AS id_municipal,
                   i.cep,
                   i.endereco,
                   i.numero,
                   i.cidade,
                   i.estado,
                   p.cpf AS cpf_responsavel,
                   p.nome_completo AS responsavel_nome,
                   i.aluguel AS aluguel_referencia,
                   i.numero_energia,
                   i.numero_agua,
                   i.repasse_iptu,
                   i.valor_iptu AS iptu_anual,
                   i.repasse_taxa_condominio AS repasse_condominio,
                   i.valor_condominio,
                   i.adm_propriedade AS cobranca_solar,
                   i.imobiliaria,
                   i.taxa_adm_imovel,
                   ac.contrato_id,
                   ac.periodo_id,
                   ac.contrato_valor_aluguel,
                   CASE WHEN ac.contrato_id IS NULL THEN 0 ELSE 1 END
                       AS contrato_ativo,
                   tenant.nome_completo AS inquilino,
                   tenant.cpf AS inquilino_cpf,
                   solar.nome_completo AS cliente_energia_solar,
                   solar.cpf AS cliente_energia_solar_cpf
            FROM imoveis AS i
            JOIN proprietario AS p ON p.id = i.responsavel
            LEFT JOIN current_active_contracts AS ac
                ON ac.imovel_id = i.id
            LEFT JOIN inquilinos_clientes AS tenant
                ON tenant.id = ac.inquilino_id
            LEFT JOIN inquilinos_clientes AS solar
                ON solar.id = i.cliente_energia_solar_id
        ),
        calculated_rows AS (
            SELECT property_rows.*,
                   COALESCE(contrato_valor_aluguel, aluguel_referencia)
                       AS aluguel_bruto,
                   CASE
                       WHEN iptu_anual IS NULL THEN NULL
                       ELSE ROUND(iptu_anual / 12.0, 2)
                   END AS iptu_mensal,
                   ROUND(
                       COALESCE(contrato_valor_aluguel, aluguel_referencia)
                       - CASE
                           WHEN repasse_iptu = 1 THEN 0
                           ELSE ROUND(COALESCE(iptu_anual, 0) / 12.0, 2)
                         END
                       - CASE
                           WHEN repasse_condominio = 1 THEN 0
                           ELSE COALESCE(valor_condominio, 0)
                         END
                       - CASE
                           WHEN imobiliaria = 1 THEN COALESCE(taxa_adm_imovel, 0)
                           ELSE 0
                         END,
                       2
                    ) AS aluguel_liquido
            FROM property_rows
        ),
        searchable_rows AS (
            SELECT calculated_rows.*,
                   UPPER(
                       COALESCE(imovel, '') || ' ' ||
                       COALESCE(CAST(imovel_id AS TEXT), '') || ' ' ||
                       COALESCE(id_municipal, '') || ' ' ||
                       COALESCE(cep, '') || ' ' ||
                       COALESCE(endereco, '') || ' ' ||
                       COALESCE(numero, '') || ' ' ||
                       COALESCE(cidade, '') || ' ' ||
                       COALESCE(estado, '') || ' ' ||
                       COALESCE(cpf_responsavel, '') || ' ' ||
                       COALESCE(responsavel_nome, '') || ' ' ||
                       COALESCE(inquilino, '') || ' ' ||
                       COALESCE(inquilino_cpf, '') || ' ' ||
                       COALESCE(cliente_energia_solar, '') || ' ' ||
                       COALESCE(cliente_energia_solar_cpf, '') || ' ' ||
                       COALESCE(numero_energia, '') || ' ' ||
                       COALESCE(numero_agua, '') || ' ' ||
                       COALESCE(CAST(contrato_id AS TEXT), '') || ' ' ||
                       COALESCE(CAST(periodo_id AS TEXT), '') || ' ' ||
                       COALESCE(CAST(aluguel_bruto AS TEXT), '') || ' ' ||
                       COALESCE(CAST(iptu_anual AS TEXT), '') || ' ' ||
                       COALESCE(CAST(iptu_mensal AS TEXT), '') || ' ' ||
                       COALESCE(CAST(valor_condominio AS TEXT), '') || ' ' ||
                       COALESCE(CAST(aluguel_liquido AS TEXT), '') || ' ' ||
                       CASE WHEN repasse_iptu = 1 THEN 'SIM' ELSE 'NAO' END || ' ' ||
                       CASE WHEN repasse_condominio = 1 THEN 'SIM' ELSE 'NAO' END || ' ' ||
                       CASE WHEN contrato_ativo = 1 THEN 'SIM' ELSE 'NAO' END || ' ' ||
                       CASE WHEN cobranca_solar = 1 THEN 'SIM' ELSE 'NAO' END
                   ) AS search_text,
                   (
                       COALESCE(CAST(imovel_id AS TEXT), '') ||
                       COALESCE(id_municipal, '') ||
                       COALESCE(cep, '') ||
                       COALESCE(numero, '') ||
                       COALESCE(cpf_responsavel, '') ||
                       COALESCE(inquilino_cpf, '') ||
                       COALESCE(cliente_energia_solar_cpf, '') ||
                       COALESCE(numero_energia, '') ||
                       COALESCE(numero_agua, '') ||
                       COALESCE(CAST(contrato_id AS TEXT), '') ||
                       COALESCE(CAST(periodo_id AS TEXT), '') ||
                       CASE WHEN aluguel_bruto IS NULL THEN ''
                            ELSE REPLACE(printf('%.2f', aluguel_bruto), '.', '') END ||
                       CASE WHEN iptu_anual IS NULL THEN ''
                            ELSE REPLACE(printf('%.2f', iptu_anual), '.', '') END ||
                       CASE WHEN iptu_mensal IS NULL THEN ''
                            ELSE REPLACE(printf('%.2f', iptu_mensal), '.', '') END ||
                       CASE WHEN valor_condominio IS NULL THEN ''
                            ELSE REPLACE(printf('%.2f', valor_condominio), '.', '') END ||
                       CASE WHEN aluguel_liquido IS NULL THEN ''
                            ELSE REPLACE(printf('%.2f', aluguel_liquido), '.', '') END
                   ) AS search_digits
            FROM calculated_rows
        )
        SELECT *
        FROM searchable_rows
        {search_clause}
        ORDER BY imovel COLLATE NOCASE, imovel_id
        """,
        params,
    ).fetchall()

    result = []
    for row in rows:
        gross = row["contrato_valor_aluguel"]
        if gross is None:
            gross = row["aluguel_referencia"]
        financials = property_financials(gross, row)
        annual_iptu = (
            None
            if row["iptu_anual"] is None
            else report_money(row["iptu_anual"])
        )
        monthly_iptu = (
            None
            if annual_iptu is None
            else report_money(annual_iptu / Decimal("12"))
        )
        condominium = (
            None
            if row["valor_condominio"] is None
            else report_money(row["valor_condominio"])
        )
        result.append(
            {
                "imovel_id": row["imovel_id"],
                "imovel": row["imovel"],
                "id_municipal": row["id_municipal"],
                "responsavel_nome": row["responsavel_nome"],
                "cep": row["cep"],
                "endereco": row["endereco"],
                "numero": row["numero"],
                "cidade": row["cidade"],
                "estado": row["estado"],
                "cpf_responsavel": row["cpf_responsavel"],
                "inquilino": row["inquilino"],
                "cliente_energia_solar": row["cliente_energia_solar"],
                "aluguel_bruto": report_number(financials["aluguel_bruto"]),
                "aluguel_liquido": report_number(financials["aluguel_liquido"]),
                "repasse_iptu": row["repasse_iptu"],
                "iptu_anual": report_number(annual_iptu) if annual_iptu is not None else None,
                "iptu_mensal": report_number(monthly_iptu) if monthly_iptu is not None else None,
                "repasse_condominio": row["repasse_condominio"],
                "valor_condominio": (
                    report_number(condominium) if condominium is not None else None
                ),
                "contrato_ativo": row["contrato_ativo"],
                "cobranca_solar": row["cobranca_solar"],
                "numero_energia": row["numero_energia"],
                "numero_agua": row["numero_agua"],
            }
        )
    return result


def financial_report_response(db: sqlite3.Connection) -> dict[str, Any]:
    """Build the monthly financial report from active contracts and vacant properties."""

    conditions, query_params = property_filter_conditions(db, include_solar=False)
    property_clause = f"AND {' AND '.join(conditions)}" if conditions else ""

    rows = db.execute(
        f"""
        WITH active_periods AS (
            SELECT c.id AS contrato_id,
                   c.imovel_id,
                   cp.id AS periodo_id,
                   cp.data_inicio AS periodo_data_inicio,
                   cp.valor_aluguel,
                   cp.dia_pagamento
            FROM contratos AS c
            JOIN contrato_periodos AS cp ON cp.contrato_id = c.id
            WHERE c.status = 'ATIVO'
        )
        SELECT selected.contrato_id,
               selected.periodo_id,
               selected.imovel_id,
               selected.valor_aluguel,
               selected.dia_pagamento,
               i.apelido AS imovel_nome,
               i.imobiliaria,
               i.taxa_adm_imovel,
               i.repasse_iptu,
               i.valor_iptu,
               i.repasse_taxa_condominio,
               i.valor_condominio,
               p.id AS proprietario_id,
               p.nome_completo AS proprietario_nome
        FROM active_periods AS selected
        JOIN imoveis AS i ON i.id = selected.imovel_id
        JOIN proprietario AS p ON p.id = i.responsavel
        WHERE NOT EXISTS (
            SELECT 1
            FROM active_periods AS candidate
            WHERE candidate.imovel_id = selected.imovel_id
              AND (
                  candidate.periodo_data_inicio > selected.periodo_data_inicio
                  OR (
                      candidate.periodo_data_inicio = selected.periodo_data_inicio
                      AND candidate.periodo_id > selected.periodo_id
                  )
                  OR (
                      candidate.periodo_data_inicio = selected.periodo_data_inicio
                      AND candidate.periodo_id = selected.periodo_id
                      AND candidate.contrato_id > selected.contrato_id
                  )
              )
        )
        {property_clause}
        ORDER BY i.apelido COLLATE NOCASE, i.id
        """,
        query_params,
    ).fetchall()

    vacant_rows = db.execute(
        f"""
        SELECT i.id AS imovel_id,
               i.apelido AS imovel_nome,
               i.repasse_iptu,
               i.valor_iptu,
               i.repasse_taxa_condominio,
               i.valor_condominio,
               p.id AS proprietario_id,
               p.nome_completo AS proprietario_nome
        FROM imoveis AS i
        JOIN proprietario AS p ON p.id = i.responsavel
        WHERE NOT EXISTS (
            SELECT 1
            FROM contratos AS c
            WHERE c.imovel_id = i.id
              AND c.status = 'ATIVO'
        )
          AND (
              (
                  i.repasse_iptu = 0
                  AND COALESCE(i.valor_iptu, 0) > 0
              )
              OR (
                  i.repasse_taxa_condominio = 0
                  AND COALESCE(i.valor_condominio, 0) > 0
              )
          )
        {property_clause}
        ORDER BY i.apelido COLLATE NOCASE, i.id
        """,
        query_params,
    ).fetchall()

    lines = []
    total_gross = Decimal("0.00")
    total_iptu = Decimal("0.00")
    total_condominium = Decimal("0.00")
    total_net = Decimal("0.00")

    for row in rows:
        financials = property_financials(row["valor_aluguel"], row)
        gross = financials["aluguel_bruto"]
        iptu = financials["iptu_descontado"]
        condominium = financials["condominio_descontado"]
        net = financials["aluguel_liquido"]
        margin = report_percentage(net, gross)

        lines.append(
            {
                "imovel_id": row["imovel_id"],
                "imovel_nome": row["imovel_nome"],
                "proprietario_id": row["proprietario_id"],
                "proprietario_nome": row["proprietario_nome"],
                "tipo_linha": "CONTRATO_ATIVO",
                "contrato_id": row["contrato_id"],
                "periodo_id": row["periodo_id"],
                "aluguel_bruto": report_number(gross),
                "iptu_mensal": report_number(iptu),
                "condominio_descontado": report_number(condominium),
                "aluguel_liquido": report_number(net),
                "dia_pagamento": row["dia_pagamento"],
                "margem_liquida_percentual": report_number(margin),
            }
        )
        total_gross += gross
        total_iptu += iptu
        total_condominium += condominium
        total_net += net

    for row in vacant_rows:
        financials = property_financials(
            Decimal("0.00"), row, include_administration_fee=False
        )
        gross = financials["aluguel_bruto"]
        iptu = financials["iptu_descontado"]
        condominium = financials["condominio_descontado"]
        net = financials["aluguel_liquido"]

        lines.append(
            {
                "imovel_id": row["imovel_id"],
                "imovel_nome": row["imovel_nome"],
                "proprietario_id": row["proprietario_id"],
                "proprietario_nome": row["proprietario_nome"],
                "tipo_linha": "DESOCUPADO_DESPESA",
                "contrato_id": None,
                "periodo_id": None,
                "aluguel_bruto": report_number(gross),
                "iptu_mensal": report_number(iptu),
                "condominio_descontado": report_number(condominium),
                "aluguel_liquido": report_number(net),
                "dia_pagamento": None,
                "margem_liquida_percentual": 0.0,
            }
        )
        total_iptu += iptu
        total_condominium += condominium
        total_net += net

    return {
        "linhas": lines,
        "resumo": {
            "total_aluguel_bruto": report_number(total_gross),
            "total_iptu_descontado": report_number(total_iptu),
            "total_condominio_descontado": report_number(total_condominium),
            "total_aluguel_liquido": report_number(total_net),
            "margem_liquida_percentual": report_number(
                report_percentage(total_net, total_gross)
            ),
        },
    }


def register_routes(app: Flask) -> None:
    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/api/dashboard")
    def dashboard_data():
        db = get_db()
        try:
            property_where, property_params = property_filter_clause(db)
        except ValueError as error:
            return error_response(str(error))

        property_counts = db.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE
                    WHEN UPPER(COALESCE(i.tipo_operacao, '')) LIKE '%ALUGUEL%'
                    THEN 1 ELSE 0
                END), 0) AS imoveis_locacao,
                COALESCE(SUM(CASE
                    WHEN UPPER(COALESCE(i.tipo_operacao, '')) LIKE '%ENERGIA SOLAR%'
                    THEN 1 ELSE 0
                END), 0) AS imoveis_energia_solar,
                COALESCE(SUM(CASE
                    WHEN UPPER(COALESCE(i.tipo_operacao, '')) LIKE '%ENERGIA SOLAR%'
                         AND i.adm_propriedade = 1
                    THEN 1 ELSE 0
                END), 0) AS imoveis_cobranca_solar,
                COALESCE(SUM(CASE
                    WHEN UPPER(COALESCE(i.tipo_operacao, '')) LIKE '%ALUGUEL%'
                         AND EXISTS (
                             SELECT 1
                             FROM contratos AS ca
                             WHERE ca.imovel_id = i.id
                               AND ca.status = 'ATIVO'
                         )
                    THEN 1 ELSE 0
                END), 0) AS imoveis_alugados
            FROM imoveis AS i
            {property_where}
            """,
            property_params,
        ).fetchone()
        rental_total = property_counts["imoveis_locacao"]
        solar_total = property_counts["imoveis_energia_solar"]
        rented_total = property_counts["imoveis_alugados"]
        billed_total = property_counts["imoveis_cobranca_solar"]
        counts = {
            "proprietarios": db.execute("SELECT COUNT(*) FROM proprietario").fetchone()[0],
            "inquilinos_clientes": db.execute("SELECT COUNT(*) FROM inquilinos_clientes").fetchone()[0],
            "imoveis": property_counts["total"],
            "imoveis_locacao": rental_total,
            "imoveis_alugados": rented_total,
            "taxa_ocupacao": round((rented_total * 100) / rental_total) if rental_total else 0,
            "imoveis_energia_solar": solar_total,
            "imoveis_cobranca_solar": billed_total,
            "taxa_cobranca_solar": round((billed_total * 100) / solar_total) if solar_total else 0,
            "contratos": db.execute(
                f"""
                SELECT COUNT(*)
                FROM contratos AS c
                JOIN imoveis AS i ON i.id = c.imovel_id
                {property_where}
                """,
                property_params,
            ).fetchone()[0],
        }
        return jsonify({"counts": counts})

    @app.get("/api/tipos-imovel")
    def property_types_collection():
        db = get_db()
        try:
            owner_ids = optional_owner_filter(db)
        except ValueError as error:
            return error_response(str(error))

        conditions = ["i.tipo_imovel IS NOT NULL", "TRIM(i.tipo_imovel) <> ''"]
        query_params: list[Any] = []
        if owner_ids is not None:
            placeholders = ", ".join("?" for _ in owner_ids)
            conditions.append(f"i.responsavel IN ({placeholders})")
            query_params.extend(owner_ids)

        rows = db.execute(
            f"""
            SELECT DISTINCT i.tipo_imovel
            FROM imoveis AS i
            WHERE {' AND '.join(conditions)}
            """,
            query_params,
        ).fetchall()
        available_types = {row["tipo_imovel"] for row in rows}
        return jsonify(
            [property_type for property_type in TIPOS_IMOVEL if property_type in available_types]
        )

    @app.get("/api/relatorios")
    def financial_reports():
        db = get_db()
        try:
            return jsonify(financial_report_response(db))
        except ValueError as error:
            return error_response(str(error))

    @app.get("/api/busca-rapida")
    def quick_search():
        db = get_db()
        return jsonify(quick_search_response(db, request.args.get("q", "")))

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
        linked_generation_units = db.execute(
            "SELECT COUNT(*) FROM unidades_geracao WHERE responsavel = ?", (record_id,)
        ).fetchone()[0]
        if linked or linked_generation_units:
            return error_response(
                "Este proprietário possui imóveis ou unidades de geração vinculados. "
                "Reassocie-os antes de excluir.",
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
            values = client_values(data)
        except ValueError as error:
            return error_response(str(error))

        cursor = db.execute(
            """
            INSERT INTO inquilinos_clientes
                (nome_completo, rg, cpf, contato, nome_contato, profissao, estado_civil, email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                values = client_values(data)
            except ValueError as error:
                return error_response(str(error))
            db.execute(
                """
                UPDATE inquilinos_clientes
                SET nome_completo = ?, rg = ?, cpf = ?, contato = ?, nome_contato = ?,
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
        property_linked = db.execute(
            "SELECT COUNT(*) FROM imoveis WHERE cliente_energia_solar_id = ?",
            (record_id,),
        ).fetchone()[0]
        if property_linked:
            return error_response(
                "Este inquilino/cliente possui imoveis vinculados como cliente de energia solar. "
                "Remova o vinculo antes de remover o cadastro.",
                409,
            )
        db.execute("DELETE FROM inquilinos_clientes WHERE id = ?", (record_id,))
        db.commit()
        return ("", 204)

    @app.route("/api/imoveis", methods=["GET", "POST"])
    def properties_collection():
        db = get_db()
        if request.method == "GET":
            try:
                where_clause, query_params = property_filter_clause(db)
            except ValueError as error:
                return error_response(str(error))
            rows = db.execute(
                f"""
                SELECT i.id, i.apelido, i.tipo_imovel, i.responsavel, i.cep, i.endereco,
                       i.estado, i.cidade, i.bairro, i.numero, i.complemento,
                       i.inscricao_mun, i.aluguel, i.numero_energia, i.numero_agua,
               i.adm_propriedade, i.imobiliaria, i.taxa_adm_imovel, i.tipo_operacao,
                       link.unidade_geradora_id,
                       COALESCE(NULLIF(TRIM(unit.inscricao_mun), ''), 'Unidade #' || unit.id)
                           AS unidade_geradora_identificacao,
                       i.unidade_geradora_legada, i.percentual_energia,
                       i.cliente_energia_solar_id,
                        i.repasse_iptu, i.valor_iptu,
                        i.repasse_taxa_condominio, i.valor_condominio,
                       p.nome_completo AS responsavel_nome
                FROM imoveis AS i
                JOIN proprietario AS p ON p.id = i.responsavel
                LEFT JOIN imovel_unidade_geradora AS link ON link.imovel_id = i.id
                LEFT JOIN unidades_geracao AS unit ON unit.id = link.unidade_geradora_id
                {where_clause}
                ORDER BY i.apelido COLLATE NOCASE
                """,
                query_params,
            ).fetchall()
            return jsonify([row_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values, generation_unit_id = property_values(data, db)
        except ValueError as error:
            return error_response(str(error))

        try:
            cursor = db.execute(
                """
                INSERT INTO imoveis
                    (tipo_imovel, apelido, responsavel, cep, endereco, estado, cidade, bairro, numero,
                     complemento, inscricao_mun, aluguel, numero_energia, numero_agua,
                     adm_propriedade, imobiliaria, taxa_adm_imovel, tipo_operacao, percentual_energia,
                     cliente_energia_solar_id, repasse_iptu, valor_iptu,
                     repasse_taxa_condominio, valor_condominio)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            sync_property_generation_unit(db, cursor.lastrowid, generation_unit_id)
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return error_response("Nao foi possivel vincular a unidade geradora selecionada.")
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
                values, generation_unit_id = property_values(data, db)
            except ValueError as error:
                return error_response(str(error))
            try:
                db.execute(
                    """
                    UPDATE imoveis
                    SET tipo_imovel = ?, apelido = ?, responsavel = ?, cep = ?, endereco = ?, estado = ?,
                        cidade = ?, bairro = ?, numero = ?, complemento = ?, inscricao_mun = ?,
                        aluguel = ?, numero_energia = ?, numero_agua = ?,
                        adm_propriedade = ?, imobiliaria = ?, taxa_adm_imovel = ?, tipo_operacao = ?, percentual_energia = ?,
                        cliente_energia_solar_id = ?, repasse_iptu = ?, valor_iptu = ?,
                        repasse_taxa_condominio = ?, valor_condominio = ?
                    WHERE id = ?
                    """,
                    (*values, record_id),
                )
                sync_property_generation_unit(db, record_id, generation_unit_id)
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return error_response("Nao foi possivel vincular a unidade geradora selecionada.")
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

    @app.route("/api/unidades-geracao", methods=["GET", "POST"])
    def generation_units_collection():
        db = get_db()
        if request.method == "GET":
            try:
                owner_ids = optional_owner_filter(db)
                property_types = optional_property_type_filter()
            except ValueError as error:
                return error_response(str(error))

            conditions: list[str] = []
            query_params: list[Any] = []
            if owner_ids is not None:
                placeholders = ", ".join("?" for _ in owner_ids)
                conditions.append(f"u.responsavel IN ({placeholders})")
                query_params.extend(owner_ids)
            if property_types is not None:
                placeholders = ", ".join("?" for _ in property_types)
                conditions.append(
                    """EXISTS (
                        SELECT 1
                        FROM imovel_unidade_geradora AS link_filter
                        JOIN imoveis AS property_filter
                          ON property_filter.id = link_filter.imovel_id
                        WHERE link_filter.unidade_geradora_id = u.id
                          AND property_filter.responsavel = u.responsavel
                          AND property_filter.tipo_imovel IN (%s)
                    )"""
                    % placeholders
                )
                query_params.extend(property_types)
            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = db.execute(
                f"""
                SELECT u.id, u.responsavel, u.cep, u.endereco, u.estado, u.cidade,
                       u.bairro, u.numero, u.complemento, u.inscricao_mun,
                       u.numero_instalacao, u.numero_unidade_geradora_consumidora,
                       u.geracao_mensal_kwh, u.preco_venda_kwh,
                       p.nome_completo AS responsavel_nome
                FROM unidades_geracao AS u
                JOIN proprietario AS p ON p.id = u.responsavel
                {where_clause}
                ORDER BY u.inscricao_mun COLLATE NOCASE, u.id
                """,
                tuple(query_params),
            ).fetchall()
            return jsonify([generation_unit_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = generation_unit_values(data, db)
        except ValueError as error:
            return error_response(str(error))

        cursor = db.execute(
            """
            INSERT INTO unidades_geracao
                (responsavel, cep, endereco, estado, cidade, bairro, numero,
                 complemento, inscricao_mun, numero_instalacao,
                 numero_unidade_geradora_consumidora, geracao_mensal_kwh,
                 preco_venda_kwh)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        db.commit()
        row = get_generation_unit(db, cursor.lastrowid)
        return jsonify(generation_unit_dict(row)), 201

    @app.route("/api/unidades-geracao/<int:record_id>", methods=["GET", "PUT", "DELETE"])
    def generation_unit_item(record_id: int):
        db = get_db()
        row = get_generation_unit(db, record_id)
        if row is None:
            return error_response("Unidade de geração não encontrada.", 404)
        if request.method == "GET":
            return jsonify(generation_unit_dict(row))
        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            try:
                values = generation_unit_values(data, db)
            except ValueError as error:
                return error_response(str(error))
            db.execute(
                """
                UPDATE unidades_geracao
                SET responsavel = ?, cep = ?, endereco = ?, estado = ?, cidade = ?,
                    bairro = ?, numero = ?, complemento = ?, inscricao_mun = ?,
                    numero_instalacao = ?, numero_unidade_geradora_consumidora = ?,
                    geracao_mensal_kwh = ?, preco_venda_kwh = ?
                WHERE id = ?
                """,
                (*values, record_id),
            )
            db.commit()
            updated = get_generation_unit(db, record_id)
            return jsonify(generation_unit_dict(updated))

        linked = db.execute(
            "SELECT COUNT(*) FROM imovel_unidade_geradora WHERE unidade_geradora_id = ?",
            (record_id,),
        ).fetchone()[0]
        if linked:
            return error_response(
                "Esta unidade geradora possui imóveis vinculados. Remova os vínculos antes de excluir.",
                409,
            )
        try:
            db.execute("DELETE FROM unidades_geracao WHERE id = ?", (record_id,))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return error_response("NÃ£o foi possÃ­vel excluir a unidade geradora.", 409)
        return ("", 204)

    @app.route("/api/unidades-geracao/<int:record_id>/distribuicao", methods=["GET"])
    def generation_unit_distribution(record_id: int):
        db = get_db()
        distribution = get_generation_distribution(db, record_id)
        if distribution is None:
            return error_response("Unidade de geração não encontrada.", 404)
        return jsonify(distribution)

    @app.route(
        "/api/unidades-geracao/<int:record_id>/distribuicao/pdf", methods=["GET"]
    )
    def generation_unit_distribution_pdf(record_id: int):
        db = get_db()
        distribution = get_generation_distribution(db, record_id)
        if distribution is None:
            return error_response("Unidade de geração não encontrada.", 404)
        return send_file(
            build_distribution_pdf(distribution),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"relatorio-energia-solar-{record_id}.pdf",
        )

    @app.route("/api/contratos", methods=["GET", "POST"])
    def contracts_collection():
        db = get_db()
        if request.method == "GET":
            try:
                where_clause, query_params = property_filter_clause(db)
            except ValueError as error:
                return error_response(str(error))
            rows = db.execute(
                f"""
                SELECT c.*,
                       (SELECT cp.dia_pagamento
                        FROM contrato_periodos AS cp
                        WHERE cp.contrato_id = c.id
                        ORDER BY cp.data_inicio DESC, cp.id DESC
                        LIMIT 1) AS dia_pagamento,
                       (SELECT cp.data_pagamento_caucao
                        FROM contrato_periodos AS cp
                        WHERE cp.contrato_id = c.id
                        ORDER BY cp.data_inicio DESC, cp.id DESC
                        LIMIT 1) AS data_pagamento_caucao,
                       (SELECT cp.id
                        FROM contrato_periodos AS cp
                        WHERE cp.contrato_id = c.id
                        ORDER BY cp.data_inicio DESC, cp.id DESC
                        LIMIT 1) AS periodo_atual_id,
                       (SELECT COUNT(*)
                        FROM contrato_periodos AS cp
                        WHERE cp.contrato_id = c.id) AS periodos_count,
                       i.apelido AS imovel_nome,
                       ic.nome_completo AS inquilino_nome
                FROM contratos AS c
                JOIN imoveis AS i ON i.id = c.imovel_id
                JOIN inquilinos_clientes AS ic ON ic.id = c.inquilino_id
                {where_clause}
                ORDER BY c.data_inicio DESC, c.id DESC
                """,
                query_params,
            ).fetchall()
            return jsonify([row_dict(row) for row in rows])

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = contract_values(data, db, status_default="ATIVO")
            period_values = contract_period_values(data)
        except ValueError as error:
            return error_response(str(error))

        try:
            cursor = db.execute(
                """
                INSERT INTO contratos
                    (imovel_id, inquilino_id, data_inicio, data_fim,
                     valor_aluguel, valor_caucao, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            db.execute(
                """
                INSERT INTO contrato_periodos
                    (contrato_id, data_inicio, data_fim, valor_aluguel,
                     dia_pagamento, valor_caucao, data_pagamento_caucao)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (cursor.lastrowid, *period_values),
            )
            db.commit()
        except sqlite3.Error:
            db.rollback()
            return error_response("Não foi possível salvar o período do contrato.", 500)
        return jsonify(contract_response(db, cursor.lastrowid)), 201

    @app.route("/api/contratos/<int:record_id>/periodos", methods=["GET", "POST"])
    def contract_periods_collection(record_id: int):
        db = get_db()
        if get_contract(db, record_id) is None:
            return error_response("Contrato não encontrado.", 404)
        if request.method == "GET":
            return jsonify(get_contract_periods(db, record_id))

        data = payload()
        if data is None:
            return error_response("Envie um objeto JSON válido.")
        try:
            values = contract_period_values(data)
        except ValueError as error:
            return error_response(str(error))

        previous = db.execute(
            """
            SELECT * FROM contrato_periodos
            WHERE contrato_id = ?
            ORDER BY data_inicio DESC, id DESC
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if previous is None:
            return error_response("O contrato precisa ter um período inicial.", 409)
        if values[0] <= previous["data_inicio"]:
            return error_response(
                "A data de início da renovação deve ser posterior à do período anterior."
            )

        previous_end = previous["data_fim"]
        last_allowed_end = (date.fromisoformat(values[0]) - timedelta(days=1)).isoformat()
        finalized_end = min(previous_end, last_allowed_end)
        try:
            db.execute(
                "UPDATE contrato_periodos SET data_fim = ? WHERE id = ?",
                (finalized_end, previous["id"]),
            )
            cursor = db.execute(
                """
                INSERT INTO contrato_periodos
                    (contrato_id, data_inicio, data_fim, valor_aluguel,
                     dia_pagamento, valor_caucao, data_pagamento_caucao,
                     data_fim_anterior)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record_id, *values, previous_end),
            )
            db.execute("UPDATE contratos SET status = 'ATIVO' WHERE id = ?", (record_id,))
            sync_contract_current_period(db, record_id)
            db.commit()
        except sqlite3.Error:
            db.rollback()
            return error_response("Não foi possível cadastrar a renovação.", 500)

        periods = get_contract_periods(db, record_id)
        created = next(period for period in periods if period["id"] == cursor.lastrowid)
        return jsonify(created), 201

    @app.route(
        "/api/contratos/<int:record_id>/periodos/<int:period_id>",
        methods=["GET", "PUT", "DELETE"],
    )
    def contract_period_item(record_id: int, period_id: int):
        db = get_db()
        if get_contract(db, record_id) is None:
            return error_response("Contrato não encontrado.", 404)
        period = db.execute(
            "SELECT * FROM contrato_periodos WHERE id = ? AND contrato_id = ?",
            (period_id, record_id),
        ).fetchone()
        if period is None:
            return error_response("Período contratual não encontrado.", 404)
        if request.method == "GET":
            periods = get_contract_periods(db, record_id)
            return jsonify(next(item for item in periods if item["id"] == period_id))

        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            try:
                values = contract_period_values(
                    data,
                    payment_day_default=period["dia_pagamento"],
                    payment_day_required=period["dia_pagamento"] is not None,
                )
            except ValueError as error:
                return error_response(str(error))

            periods = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM contrato_periodos WHERE contrato_id = ?",
                    (record_id,),
                ).fetchall()
            ]
            candidate = next(item for item in periods if item["id"] == period_id)
            (
                candidate["data_inicio"],
                candidate["data_fim"],
                candidate["valor_aluguel"],
                candidate["dia_pagamento"],
                candidate["valor_caucao"],
                candidate["data_pagamento_caucao"],
            ) = values
            try:
                validate_period_timeline(periods)
            except ValueError as error:
                return error_response(str(error))

            ordered = sorted(periods, key=lambda item: (item["data_inicio"], item["id"]))
            try:
                db.execute(
                    """
                    UPDATE contrato_periodos
                    SET data_inicio = ?, data_fim = ?, valor_aluguel = ?,
                        dia_pagamento = ?, valor_caucao = ?, data_pagamento_caucao = ?
                    WHERE id = ? AND contrato_id = ?
                    """,
                    (*values, period_id, record_id),
                )
                for previous_item, current_item in zip(ordered, ordered[1:]):
                    db.execute(
                        "UPDATE contrato_periodos SET data_fim_anterior = ? WHERE id = ?",
                        (previous_item["data_fim"], current_item["id"]),
                    )
                sync_contract_current_period(db, record_id)
                db.commit()
            except sqlite3.Error:
                db.rollback()
                return error_response("Não foi possível atualizar o período contratual.", 500)
            updated_periods = get_contract_periods(db, record_id)
            return jsonify(next(item for item in updated_periods if item["id"] == period_id))

        periods = db.execute(
            """
            SELECT * FROM contrato_periodos
            WHERE contrato_id = ?
            ORDER BY data_inicio ASC, id ASC
            """,
            (record_id,),
        ).fetchall()
        if len(periods) <= 1:
            return error_response("O período inicial não pode ser excluído do contrato.", 409)
        if periods[-1]["id"] != period_id:
            return error_response(
                "Somente a última renovação pode ser revertida para preservar o histórico.",
                409,
            )

        previous = periods[-2]
        restored_end = period["data_fim_anterior"] or previous["data_fim"]
        if restored_end < previous["data_inicio"] or restored_end >= period["data_inicio"]:
            restored_end = (date.fromisoformat(period["data_inicio"]) - timedelta(days=1)).isoformat()
        try:
            db.execute(
                "UPDATE contrato_periodos SET data_fim = ? WHERE id = ?",
                (restored_end, previous["id"]),
            )
            db.execute("DELETE FROM contrato_periodos WHERE id = ?", (period_id,))
            sync_contract_current_period(db, record_id)
            db.commit()
        except sqlite3.Error:
            db.rollback()
            return error_response("Não foi possível reverter a renovação.", 500)
        return ("", 204)

    @app.post("/api/contratos/<int:record_id>/periodos/<int:period_id>/reverter")
    def revert_contract_period(record_id: int, period_id: int):
        return contract_period_item(record_id, period_id)

    @app.route("/api/contratos/<int:record_id>", methods=["GET", "PUT", "DELETE"])
    def contract_item(record_id: int):
        db = get_db()
        row = get_contract(db, record_id)
        if row is None:
            return error_response("Contrato não encontrado.", 404)
        if request.method == "GET":
            return jsonify(contract_response(db, record_id))
        if request.method == "PUT":
            data = payload()
            if data is None:
                return error_response("Envie um objeto JSON válido.")
            current_period = db.execute(
                """
                SELECT id, dia_pagamento FROM contrato_periodos
                WHERE contrato_id = ?
                ORDER BY data_inicio DESC, id DESC
                LIMIT 1
                """,
                (record_id,),
            ).fetchone()
            if current_period is None:
                return error_response("O contrato precisa ter um período inicial.", 409)
            try:
                values = contract_values(data, db, status_default=row["status"] or "ATIVO")
                period_values = contract_period_values(
                    data,
                    payment_day_default=current_period["dia_pagamento"],
                    payment_day_required=current_period["dia_pagamento"] is not None,
                )
            except ValueError as error:
                return error_response(str(error))
            periods = [
                dict(item)
                for item in db.execute(
                    "SELECT * FROM contrato_periodos WHERE contrato_id = ?",
                    (record_id,),
                ).fetchall()
            ]
            candidate = next(item for item in periods if item["id"] == current_period["id"])
            candidate.update(
                {
                    "data_inicio": period_values[0],
                    "data_fim": period_values[1],
                    "valor_aluguel": period_values[2],
                    "dia_pagamento": period_values[3],
                    "valor_caucao": period_values[4],
                    "data_pagamento_caucao": period_values[5],
                }
            )
            try:
                validate_period_timeline(periods)
            except ValueError as error:
                return error_response(str(error))
            try:
                db.execute(
                    """
                    UPDATE contratos
                    SET imovel_id = ?, inquilino_id = ?, data_inicio = ?, data_fim = ?,
                        valor_aluguel = ?, valor_caucao = ?, status = ?
                    WHERE id = ?
                    """,
                    (*values, record_id),
                )
                db.execute(
                    """
                    UPDATE contrato_periodos
                    SET data_inicio = ?, data_fim = ?, valor_aluguel = ?,
                        dia_pagamento = ?, valor_caucao = ?, data_pagamento_caucao = ?
                    WHERE id = ?
                    """,
                    (*period_values, current_period["id"]),
                )
                db.commit()
            except sqlite3.Error:
                db.rollback()
                return error_response("Não foi possível atualizar o contrato.", 500)
            return jsonify(contract_response(db, record_id))

        db.execute("DELETE FROM contratos WHERE id = ?", (record_id,))
        db.commit()
        return ("", 204)


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
