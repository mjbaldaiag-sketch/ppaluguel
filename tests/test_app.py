import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app, repair_text_encoding


class AppCrudTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "DATABASE": str(database),
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def post_json(self, url, payload):
        return self.client.post(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    def put_json(self, url, payload):
        return self.client.put(
            url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    @staticmethod
    def person_payload(name="Maria da Silva"):
        return {
            "nome_completo": name,
            "rg": "12.345.678-9",
            "cpf": "123.456.789-09",
            "contato": "(11) 99999-0000",
            "profissao": "Administradora",
            "estado_civil": "Casado(a)",
            "email": "MARIA@EXAMPLE.COM",
        }

    @staticmethod
    def property_payload(owner_id):
        return {
            "tipo_imovel": "APARTAMENTO",
            "apelido": "Apartamento Centro",
            "responsavel": owner_id,
            "cep": "01001-000",
            "endereco": "Praça da Sé",
            "estado": "SP",
            "cidade": "São Paulo",
            "bairro": "Sé",
            "numero": "100",
            "complemento": "Apto 12",
            "inscricao_mun": "12345",
            "aluguel": "R$ 2.500,00",
            "numero_energia": "9876",
            "numero_agua": "5432",
            "adm_propriedade": "1",
            "imobiliaria": "1",
            "energia_solar": "0",
            "unidade_geradora": "UG-01",
            "percentual_energia": "35,5",
        }

    @staticmethod
    def contract_payload(property_id, tenant_id):
        return {
            "imovel_id": property_id,
            "inquilino_id": tenant_id,
            "data_inicio": "2026-01-01",
            "data_fim": "2027-01-01",
            "valor_aluguel": "R$ 2.500,00",
            "valor_caucao": "R$ 5.000,00",
        }

    def test_dashboard_and_database_initialize_automatically(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(
            dashboard.get_json()["counts"],
            {"proprietarios": 0, "inquilinos_clientes": 0, "imoveis": 0, "contratos": 0},
        )

    def test_proprietario_crud_and_normalization(self):
        created = self.post_json("/api/proprietarios", self.person_payload())
        self.assertEqual(created.status_code, 201)
        owner = created.get_json()
        self.assertEqual(owner["cpf"], "12345678909")
        self.assertEqual(owner["contato"], "11999990000")
        self.assertEqual(owner["rg"], "123456789")

        record_id = owner["id"]
        fetched = self.client.get(f"/api/proprietarios/{record_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["nome_completo"], "MARIA DA SILVA")
        self.assertEqual(fetched.get_json()["email"], "maria@example.com")

        updated_payload = self.person_payload("Maria Souza")
        updated_payload["rg"] = "MG3942581"
        updated = self.put_json(f"/api/proprietarios/{record_id}", updated_payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["nome_completo"], "MARIA SOUZA")
        self.assertEqual(updated.get_json()["rg"], "MG3942581")

        deleted = self.client.delete(f"/api/proprietarios/{record_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/proprietarios/{record_id}").status_code, 404)

    def test_inquilino_crud(self):
        payload = self.person_payload("João Cliente")
        payload["rg"] = "SSP4494416117"
        payload["nome_contato"] = "Responsavel do contato"
        created = self.post_json(
            "/api/inquilinos-clientes",
            payload,
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["rg"], "SSP4494416117")
        self.assertEqual(created.get_json()["nome_contato"], "RESPONSAVEL DO CONTATO")
        record_id = created.get_json()["id"]

        fetched = self.client.get(f"/api/inquilinos-clientes/{record_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["nome_contato"], "RESPONSAVEL DO CONTATO")

        listing = self.client.get("/api/inquilinos-clientes")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()[0]["nome_completo"], "JOÃO CLIENTE")
        self.assertEqual(listing.get_json()[0]["rg"], "SSP4494416117")

        payload["nome_completo"] = "João Souza"
        payload["rg"] = "MG3942581"
        payload["nome_contato"] = "Novo responsavel"
        updated = self.put_json(f"/api/inquilinos-clientes/{record_id}", payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["rg"], "MG3942581")
        self.assertEqual(updated.get_json()["nome_contato"], "NOVO RESPONSAVEL")

        self.assertEqual(
            self.client.delete(f"/api/inquilinos-clientes/{record_id}").status_code,
            204,
        )

    def test_inquilino_nome_contato_is_optional(self):
        created = self.post_json(
            "/api/inquilinos-clientes",
            self.person_payload("Cliente sem nome de contato"),
        )
        self.assertEqual(created.status_code, 201)
        self.assertIsNone(created.get_json()["nome_contato"])

    def test_property_relationship_crud_and_owner_delete_block(self):
        owner = self.post_json(
            "/api/proprietarios",
            self.person_payload("Proprietário do Imóvel"),
        ).get_json()

        created = self.post_json("/api/imoveis", self.property_payload(owner["id"]))
        self.assertEqual(created.status_code, 201)
        property_data = created.get_json()
        self.assertEqual(property_data["responsavel"], owner["id"])
        self.assertEqual(property_data["tipo_imovel"], "APARTAMENTO")
        self.assertEqual(property_data["aluguel"], 2500.0)
        self.assertEqual(property_data["imobiliaria"], 1)
        self.assertEqual(property_data["percentual_energia"], 35.5)
        self.assertEqual(property_data["endereco"], "PRAÇA DA SÉ")
        self.assertEqual(property_data["responsavel_nome"], "PROPRIETÁRIO DO IMÓVEL")

        blocked = self.client.delete(f"/api/proprietarios/{owner['id']}")
        self.assertEqual(blocked.status_code, 409)

        changed = self.property_payload(owner["id"])
        changed["apelido"] = "Casa Atualizada"
        changed["tipo_imovel"] = "CASA"
        updated = self.put_json(f"/api/imoveis/{property_data['id']}", changed)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["tipo_imovel"], "CASA")
        self.assertEqual(
            self.client.delete(f"/api/imoveis/{property_data['id']}").status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(f"/api/proprietarios/{owner['id']}").status_code,
            204,
        )

    def test_contract_crud_relationships_and_parent_delete_block(self):
        owner = self.post_json(
            "/api/proprietarios",
            self.person_payload("Proprietário do Contrato"),
        ).get_json()
        property_data = self.post_json(
            "/api/imoveis", self.property_payload(owner["id"])
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes",
            self.person_payload("Inquilino do Contrato"),
        ).get_json()

        payload = self.contract_payload(property_data["id"], tenant["id"])
        created = self.post_json("/api/contratos", payload)
        self.assertEqual(created.status_code, 201)
        contract = created.get_json()
        self.assertEqual(contract["imovel_id"], property_data["id"])
        self.assertEqual(contract["inquilino_id"], tenant["id"])
        self.assertEqual(contract["data_inicio"], "2026-01-01")
        self.assertEqual(contract["valor_aluguel"], 2500.0)
        self.assertEqual(contract["valor_caucao"], 5000.0)
        self.assertEqual(contract["imovel_nome"], "APARTAMENTO CENTRO")
        self.assertEqual(contract["inquilino_nome"], "INQUILINO DO CONTRATO")

        contract_id = contract["id"]
        listing = self.client.get("/api/contratos")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()[0]["id"], contract_id)
        fetched = self.client.get(f"/api/contratos/{contract_id}")
        self.assertEqual(fetched.status_code, 200)

        blocked_property = self.client.delete(f"/api/imoveis/{property_data['id']}")
        self.assertEqual(blocked_property.status_code, 409)
        blocked_tenant = self.client.delete(f"/api/inquilinos-clientes/{tenant['id']}")
        self.assertEqual(blocked_tenant.status_code, 409)

        changed = self.contract_payload(property_data["id"], tenant["id"])
        changed.update({"data_fim": "2028-01-01", "valor_caucao": ""})
        updated = self.put_json(f"/api/contratos/{contract_id}", changed)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["data_fim"], "2028-01-01")
        self.assertIsNone(updated.get_json()["valor_caucao"])

        self.assertEqual(self.client.delete(f"/api/contratos/{contract_id}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/imoveis/{property_data['id']}").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/inquilinos-clientes/{tenant['id']}").status_code, 204)

    def test_contract_validation_errors(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Validação")
        ).get_json()
        property_data = self.post_json(
            "/api/imoveis", self.property_payload(owner["id"])
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Validação")
        ).get_json()
        valid = self.contract_payload(property_data["id"], tenant["id"])

        missing_required = dict(valid)
        missing_required.pop("data_inicio")
        self.assertEqual(self.post_json("/api/contratos", missing_required).status_code, 400)

        invalid_property = dict(valid, imovel_id=999)
        self.assertEqual(self.post_json("/api/contratos", invalid_property).status_code, 400)

        invalid_dates = dict(valid, data_inicio="2027-01-01", data_fim="2026-01-01")
        self.assertEqual(self.post_json("/api/contratos", invalid_dates).status_code, 400)

        invalid_format = dict(valid, data_inicio="01/01/2026")
        self.assertEqual(self.post_json("/api/contratos", invalid_format).status_code, 400)

        invalid_money = dict(valid, valor_aluguel="-1")
        self.assertEqual(self.post_json("/api/contratos", invalid_money).status_code, 400)

    def test_dashboard_contract_count_and_page_markup(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-module="contratos"', page)
        self.assertIn('data-form-section="contratos"', page)
        self.assertIn('data-field="tipo_imovel"', page)
        self.assertIn("GALPÃO COMERCIAL", page)
        self.assertIn("CHÁCARA/SÍTIO", page)
        self.assertEqual(page.count('data-field="rg"'), 2)
        self.assertNotIn('data-field="rg" data-mask="rg"', page)
        self.assertIn('data-field="rg" inputmode="text" placeholder="Ex.: MG3942581"', page)
        self.assertIn('data-field="rg" inputmode="text" placeholder="Ex.: SSP4494416117"', page)
        self.assertIn('data-field="imovel_id"', page)
        self.assertIn('data-field="inquilino_id"', page)
        self.assertIn('id="clear-cep-button"', page)
        self.assertIn(">Limpar CEP</button>", page)
        self.assertIn('id="count-contratos"', page)
        proprietario_section = page.split('data-form-section="proprietarios"', 1)[1].split(
            'data-form-section="inquilinos"', 1
        )[0]
        inquilino_section = page.split('data-form-section="inquilinos"', 1)[1].split(
            'data-form-section="imoveis"', 1
        )[0]
        self.assertNotIn('data-field="nome_contato"', proprietario_section)
        self.assertIn('data-field="nome_contato"', inquilino_section)

    def test_frontend_text_has_no_mojibake_markers(self):
        app_js = Path(__file__).resolve().parents[1] / "static" / "js" / "app.js"
        source = app_js.read_text(encoding="utf-8")
        self.assertIn("Código #", source)
        self.assertNotIn("C" + "\u00c3\u00b3" + "digo", source)
        self.assertNotIn("\ufffd", source)

    def test_text_encoding_repair_preserves_valid_utf8(self):
        self.assertEqual(repair_text_encoding("CÃ³digo"), "Código")
        self.assertEqual(repair_text_encoding("UNI\ufffdO"), "UNIÃO")
        self.assertEqual(repair_text_encoding("UNIÃO"), "UNIÃO")

    def test_validation_errors(self):
        missing_name = self.post_json("/api/proprietarios", {"email": "bad"})
        self.assertEqual(missing_name.status_code, 400)

        invalid_cpf = self.post_json(
            "/api/proprietarios",
            {"nome_completo": "Pessoa", "cpf": "111.111.111-11"},
        )
        self.assertEqual(invalid_cpf.status_code, 400)

        invalid_email = self.post_json(
            "/api/inquilinos-clientes",
            {"nome_completo": "Cliente", "email": "nao-e-email"},
        )
        self.assertEqual(invalid_email.status_code, 400)

        invalid_owner = self.post_json(
            "/api/imoveis",
            {"apelido": "Imóvel", "responsavel": 999, "aluguel": 1000},
        )
        self.assertEqual(invalid_owner.status_code, 400)

        owner = self.post_json(
            "/api/proprietarios",
            self.person_payload("Validação"),
        ).get_json()
        invalid_money = self.property_payload(owner["id"])
        invalid_money["aluguel"] = "-1"
        self.assertEqual(self.post_json("/api/imoveis", invalid_money).status_code, 400)

        invalid_percentage = self.property_payload(owner["id"])
        invalid_percentage["percentual_energia"] = "101"
        self.assertEqual(self.post_json("/api/imoveis", invalid_percentage).status_code, 400)

        missing_property_type = self.property_payload(owner["id"])
        missing_property_type.pop("tipo_imovel")
        self.assertEqual(self.post_json("/api/imoveis", missing_property_type).status_code, 400)

        invalid_property_type = self.property_payload(owner["id"])
        invalid_property_type["tipo_imovel"] = "LOFT"
        self.assertEqual(self.post_json("/api/imoveis", invalid_property_type).status_code, 400)

    def test_property_types_are_persisted(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Tipos de Imóveis")
        ).get_json()
        expected_types = [
            "CASA",
            "APARTAMENTO",
            "GALPÃO COMERCIAL",
            "CHÁCARA/SÍTIO",
            "TERRENO",
        ]

        for index, property_type in enumerate(expected_types, start=1):
            payload = self.property_payload(owner["id"])
            payload.update({"tipo_imovel": property_type, "apelido": f"Imóvel {index}"})
            response = self.post_json("/api/imoveis", payload)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["tipo_imovel"], property_type)

        records = self.client.get("/api/imoveis").get_json()
        self.assertEqual(
            {record["tipo_imovel"] for record in records},
            set(expected_types),
        )

    def test_data_persists_between_requests(self):
        self.post_json("/api/proprietarios", self.person_payload("Persistente"))
        fresh_client = self.app.test_client()
        records = fresh_client.get("/api/proprietarios").get_json()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["nome_completo"], "PERSISTENTE")

    def test_existing_text_data_is_normalized_on_startup(self):
        database = Path(self.temp_dir.name) / "test.db"
        connection = sqlite3.connect(database)
        connection.execute(
            """
            INSERT INTO proprietario
                (nome_completo, profissao, estado_civil, email)
            VALUES (?, ?, ?, ?)
            """,
            ("nome antigo", "profissão antiga", "casado(a)", "Email@Exemplo.com"),
        )
        connection.commit()
        connection.close()

        create_app({"TESTING": True, "DATABASE": str(database)})
        records = self.client.get("/api/proprietarios").get_json()
        self.assertEqual(records[0]["nome_completo"], "NOME ANTIGO")
        self.assertEqual(records[0]["profissao"], "PROFISSÃO ANTIGA")
        self.assertEqual(records[0]["estado_civil"], "CASADO(A)")
        self.assertEqual(records[0]["email"], "email@exemplo.com")

    def test_existing_database_migrates_endereco_without_recreating_data(self):
        database = Path(self.temp_dir.name) / "legacy.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE proprietario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_completo TEXT NOT NULL,
                rg TEXT,
                cpf TEXT,
                contato TEXT,
                profissao TEXT,
                estado_civil TEXT,
                email TEXT
            );
            INSERT INTO proprietario (nome_completo) VALUES ('PROPRIETÁRIO LEGADO');
            CREATE TABLE inquilinos_clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_completo TEXT NOT NULL,
                rg TEXT,
                cpf TEXT,
                contato TEXT,
                profissao TEXT,
                estado_civil TEXT,
                email TEXT
            );
            INSERT INTO inquilinos_clientes (nome_completo)
            VALUES ('CLIENTE LEGADO');
            CREATE TABLE imoveis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                apelido TEXT NOT NULL,
                responsavel INTEGER NOT NULL,
                cep TEXT,
                estado TEXT,
                cidade TEXT,
                bairro TEXT,
                numero TEXT,
                complemento TEXT,
                inscricao_mun TEXT,
                aluguel REAL NOT NULL DEFAULT 0,
                numero_energia TEXT,
                numero_agua TEXT,
                adm_propriedade INTEGER NOT NULL DEFAULT 0,
                energia_solar INTEGER NOT NULL DEFAULT 0,
                unidade_geradora TEXT,
                percentual_energia REAL
            );
            INSERT INTO imoveis (apelido, responsavel, cidade, aluguel)
            VALUES ('IMÓVEL LEGADO', 1, 'CIDADE LEGADA', 1200);
            """
        )
        connection.commit()
        connection.close()

        create_app({"TESTING": True, "DATABASE": str(database)})
        connection = sqlite3.connect(database)
        column_names = {
            row[1] for row in connection.execute("PRAGMA table_info(imoveis)").fetchall()
        }
        client_column_names = {
            row[1]
            for row in connection.execute("PRAGMA table_info(inquilinos_clientes)").fetchall()
        }
        preserved = connection.execute(
            "SELECT apelido, cidade, aluguel, tipo_imovel, imobiliaria FROM imoveis WHERE id = 1"
        ).fetchone()
        client_preserved = connection.execute(
            "SELECT nome_completo, nome_contato FROM inquilinos_clientes WHERE id = 1"
        ).fetchone()
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        connection.close()

        self.assertIn("endereco", column_names)
        self.assertIn("tipo_imovel", column_names)
        self.assertIn("imobiliaria", column_names)
        self.assertIn("nome_contato", client_column_names)
        self.assertIn("contratos", table_names)
        self.assertEqual(preserved, ("IMÓVEL LEGADO", "CIDADE LEGADA", 1200.0, None, 0))
        self.assertEqual(client_preserved, ("CLIENTE LEGADO", None))


if __name__ == "__main__":
    unittest.main()
