import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app


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
            "apelido": "Apartamento Centro",
            "responsavel": owner_id,
            "cep": "01001-000",
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
            "energia_solar": "0",
            "unidade_geradora": "UG-01",
            "percentual_energia": "35,5",
        }

    def test_dashboard_and_database_initialize_automatically(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(
            dashboard.get_json()["counts"],
            {"proprietarios": 0, "inquilinos_clientes": 0, "imoveis": 0},
        )

    def test_proprietario_crud_and_normalization(self):
        created = self.post_json("/api/proprietarios", self.person_payload())
        self.assertEqual(created.status_code, 201)
        owner = created.get_json()
        self.assertEqual(owner["cpf"], "12345678909")
        self.assertEqual(owner["contato"], "11999990000")

        record_id = owner["id"]
        fetched = self.client.get(f"/api/proprietarios/{record_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["nome_completo"], "MARIA DA SILVA")
        self.assertEqual(fetched.get_json()["email"], "maria@example.com")

        updated = self.put_json(
            f"/api/proprietarios/{record_id}",
            self.person_payload("Maria Souza"),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["nome_completo"], "MARIA SOUZA")

        deleted = self.client.delete(f"/api/proprietarios/{record_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/proprietarios/{record_id}").status_code, 404)

    def test_inquilino_crud(self):
        created = self.post_json(
            "/api/inquilinos-clientes",
            self.person_payload("João Cliente"),
        )
        self.assertEqual(created.status_code, 201)
        record_id = created.get_json()["id"]

        listing = self.client.get("/api/inquilinos-clientes")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()[0]["nome_completo"], "JOÃO CLIENTE")

        self.assertEqual(
            self.client.delete(f"/api/inquilinos-clientes/{record_id}").status_code,
            204,
        )

    def test_property_relationship_crud_and_owner_delete_block(self):
        owner = self.post_json(
            "/api/proprietarios",
            self.person_payload("Proprietário do Imóvel"),
        ).get_json()

        created = self.post_json("/api/imoveis", self.property_payload(owner["id"]))
        self.assertEqual(created.status_code, 201)
        property_data = created.get_json()
        self.assertEqual(property_data["responsavel"], owner["id"])
        self.assertEqual(property_data["aluguel"], 2500.0)
        self.assertEqual(property_data["percentual_energia"], 35.5)
        self.assertEqual(property_data["responsavel_nome"], "PROPRIETÁRIO DO IMÓVEL")

        blocked = self.client.delete(f"/api/proprietarios/{owner['id']}")
        self.assertEqual(blocked.status_code, 409)

        changed = self.property_payload(owner["id"])
        changed["apelido"] = "Casa Atualizada"
        self.assertEqual(
            self.put_json(f"/api/imoveis/{property_data['id']}", changed).status_code,
            200,
        )
        self.assertEqual(
            self.client.delete(f"/api/imoveis/{property_data['id']}").status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(f"/api/proprietarios/{owner['id']}").status_code,
            204,
        )

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


if __name__ == "__main__":
    unittest.main()
