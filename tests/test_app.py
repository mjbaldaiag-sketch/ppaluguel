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
            "tipo_operacao": "ALUGUEL",
            "unidade_geradora_id": "",
            "percentual_energia": "35,5",
        }

    @staticmethod
    def generation_unit_payload(owner_id, generation="0"):
        return {
            "responsavel": owner_id,
            "cep": "01001-000",
            "endereco": "Praça da Sé",
            "estado": "sp",
            "cidade": "São Paulo",
            "bairro": "Sé",
            "numero": "100",
            "complemento": "Portão 2",
            "inscricao_mun": "UG-001",
            "numero_instalacao": "INST-123A",
            "numero_unidade_geradora_consumidora": "UGC-456B",
            "geracao_mensal_kwh": generation,
        }

    @staticmethod
    def contract_payload(property_id, tenant_id):
        return {
            "imovel_id": property_id,
            "inquilino_id": tenant_id,
            "data_inicio": "2026-01-01",
            "data_fim": "2027-01-01",
            "valor_aluguel": "R$ 2.500,00",
            "dia_pagamento": "5",
            "valor_caucao": "R$ 5.000,00",
        }

    def test_dashboard_and_database_initialize_automatically(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

        dashboard = self.client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(
            dashboard.get_json()["counts"],
            {
                "proprietarios": 0,
                "inquilinos_clientes": 0,
                "imoveis": 0,
                "imoveis_locacao": 0,
                "imoveis_alugados": 0,
                "taxa_ocupacao": 0,
                "imoveis_energia_solar": 0,
                "imoveis_cobranca_solar": 0,
                "taxa_cobranca_solar": 0,
                "contratos": 0,
            },
        )
        connection = sqlite3.connect(Path(self.temp_dir.name) / "test.db")
        property_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(imoveis)").fetchall()
        }
        property_schema = {
            row[1]: (row[2], row[4])
            for row in connection.execute("PRAGMA table_info(imoveis)").fetchall()
        }
        generation_schema = {
            row[1]: row[2]
            for row in connection.execute("PRAGMA table_info(unidades_geracao)").fetchall()
        }
        connection.close()
        self.assertIn("tipo_operacao", property_columns)
        self.assertNotIn("energia_solar", property_columns)
        self.assertEqual(property_schema["repasse_iptu"], ("INTEGER", "0"))
        self.assertEqual(property_schema["valor_iptu"], ("REAL", None))
        self.assertEqual(
            property_schema["repasse_taxa_condominio"],
            ("INTEGER", "0"),
        )
        self.assertEqual(property_schema["valor_condominio"], ("REAL", None))
        self.assertEqual(property_schema["taxa_adm_imovel"], ("REAL", None))
        self.assertEqual(generation_schema["preco_venda_kwh"], "INTEGER")

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
        self.assertEqual(property_data["adm_propriedade"], 1)
        self.assertEqual(property_data["imobiliaria"], 1)
        self.assertEqual(property_data["tipo_operacao"], "ALUGUEL")
        self.assertNotIn("energia_solar", property_data)
        self.assertEqual(property_data["percentual_energia"], 35.5)
        self.assertEqual(property_data["repasse_iptu"], 0)
        self.assertIsNone(property_data["valor_iptu"])
        self.assertEqual(property_data["repasse_taxa_condominio"], 0)
        self.assertIsNone(property_data["valor_condominio"])
        self.assertEqual(property_data["endereco"], "PRAÇA DA SÉ")
        self.assertEqual(property_data["responsavel_nome"], "PROPRIETÁRIO DO IMÓVEL")

        blocked = self.client.delete(f"/api/proprietarios/{owner['id']}")
        self.assertEqual(blocked.status_code, 409)

        changed = self.property_payload(owner["id"])
        changed["apelido"] = "Casa Atualizada"
        changed["tipo_imovel"] = "CASA"
        changed["adm_propriedade"] = "0"
        changed["tipo_operacao"] = "ALUGUEL + ENERGIA SOLAR"
        updated = self.put_json(f"/api/imoveis/{property_data['id']}", changed)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["tipo_imovel"], "CASA")
        self.assertEqual(updated.get_json()["adm_propriedade"], 0)
        self.assertEqual(updated.get_json()["tipo_operacao"], "ALUGUEL + ENERGIA SOLAR")
        self.assertEqual(
            self.client.get("/api/dashboard").get_json()["counts"]["imoveis_cobranca_solar"],
            0,
        )
        self.assertEqual(
            self.client.delete(f"/api/imoveis/{property_data['id']}").status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(f"/api/proprietarios/{owner['id']}").status_code,
            204,
        )

    def test_property_tax_and_condominium_fields_crud_and_validation(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Responsavel Financeiro")
        ).get_json()
        payload = self.property_payload(owner["id"])
        payload.update(
            {
                "repasse_iptu": "1",
                "valor_iptu": "R$ 123,45",
                "repasse_taxa_condominio": "1",
                "valor_condominio": "R$ 456,78",
                "taxa_adm_imovel": "R$ 321,45",
            }
        )

        created = self.post_json("/api/imoveis", payload)
        self.assertEqual(created.status_code, 201)
        property_data = created.get_json()
        self.assertEqual(property_data["repasse_iptu"], 1)
        self.assertEqual(property_data["valor_iptu"], 123.45)
        self.assertEqual(property_data["repasse_taxa_condominio"], 1)
        self.assertEqual(property_data["valor_condominio"], 456.78)
        self.assertEqual(property_data["taxa_adm_imovel"], 321.45)

        fetched = self.client.get(f"/api/imoveis/{property_data['id']}").get_json()
        self.assertEqual(fetched["valor_iptu"], 123.45)
        self.assertEqual(fetched["valor_condominio"], 456.78)
        self.assertEqual(fetched["taxa_adm_imovel"], 321.45)
        listed = self.client.get("/api/imoveis").get_json()
        self.assertEqual(listed[0]["repasse_iptu"], 1)
        self.assertEqual(listed[0]["repasse_taxa_condominio"], 1)

        changed = self.property_payload(owner["id"])
        changed.update(
            {
                "repasse_iptu": "0",
                "valor_iptu": "",
                "repasse_taxa_condominio": "0",
                "valor_condominio": "0,00",
                "taxa_adm_imovel": "0,00",
            }
        )
        updated = self.put_json(f"/api/imoveis/{property_data['id']}", changed)
        self.assertEqual(updated.status_code, 200)
        updated_data = updated.get_json()
        self.assertEqual(updated_data["repasse_iptu"], 0)
        self.assertIsNone(updated_data["valor_iptu"])
        self.assertEqual(updated_data["repasse_taxa_condominio"], 0)
        self.assertEqual(updated_data["valor_condominio"], 0.0)
        self.assertEqual(updated_data["taxa_adm_imovel"], 0.0)

        blank_taxa = dict(changed, taxa_adm_imovel="")
        blank_updated = self.put_json(f"/api/imoveis/{property_data['id']}", blank_taxa)
        self.assertEqual(blank_updated.status_code, 200)
        self.assertIsNone(blank_updated.get_json()["taxa_adm_imovel"])

        for field in ("valor_iptu", "valor_condominio", "taxa_adm_imovel"):
            invalid_precision = self.property_payload(owner["id"])
            invalid_precision[field] = "1,001"
            self.assertEqual(
                self.post_json("/api/imoveis", invalid_precision).status_code,
                400,
            )

            invalid_negative = self.property_payload(owner["id"])
            invalid_negative[field] = "-1"
            self.assertEqual(
                self.post_json("/api/imoveis", invalid_negative).status_code,
                400,
            )

        for field in ("repasse_iptu", "repasse_taxa_condominio"):
            invalid_boolean = self.property_payload(owner["id"])
            invalid_boolean[field] = "talvez"
            self.assertEqual(
                self.post_json("/api/imoveis", invalid_boolean).status_code,
                400,
            )

    def test_generation_unit_crud_filter_and_owner_delete_block(self):
        owner_one = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Solar Um")
        ).get_json()
        owner_two = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Solar Dois")
        ).get_json()

        payload = self.generation_unit_payload(owner_one["id"], "0")
        created = self.post_json("/api/unidades-geracao", payload)
        self.assertEqual(created.status_code, 201)
        unit = created.get_json()
        self.assertEqual(unit["responsavel"], owner_one["id"])
        self.assertEqual(unit["responsavel_nome"], "PROPRIETÁRIO SOLAR UM")
        self.assertEqual(unit["cep"], "01001000")
        self.assertEqual(unit["estado"], "SP")
        self.assertEqual(unit["geracao_mensal_kwh"], 0)
        self.assertEqual(unit["inscricao_mun"], "UG-001")
        self.assertEqual(unit["numero_instalacao"], "INST-123A")
        self.assertEqual(unit["numero_unidade_geradora_consumidora"], "UGC-456B")

        fetched = self.client.get(f"/api/unidades-geracao/{unit['id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["cidade"], "SÃO PAULO")

        changed = self.generation_unit_payload(owner_two["id"], "9999999")
        changed["inscricao_mun"] = "UG-999"
        changed["numero_instalacao"] = "INST-999Z"
        changed["numero_unidade_geradora_consumidora"] = "UGC-999Y"
        updated = self.put_json(f"/api/unidades-geracao/{unit['id']}", changed)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["responsavel"], owner_two["id"])
        self.assertEqual(updated.get_json()["geracao_mensal_kwh"], 9999999)
        self.assertEqual(updated.get_json()["inscricao_mun"], "UG-999")
        self.assertEqual(updated.get_json()["numero_instalacao"], "INST-999Z")
        self.assertEqual(
            updated.get_json()["numero_unidade_geradora_consumidora"], "UGC-999Y"
        )

        owner_one_units = self.client.get(
            f"/api/unidades-geracao?proprietario_id={owner_one['id']}"
        )
        self.assertEqual(owner_one_units.status_code, 200)
        self.assertEqual(owner_one_units.get_json(), [])
        owner_two_units = self.client.get(
            f"/api/unidades-geracao?proprietario_id={owner_two['id']}"
        )
        self.assertEqual([item["id"] for item in owner_two_units.get_json()], [unit["id"]])

        blocked = self.client.delete(f"/api/proprietarios/{owner_two['id']}")
        self.assertEqual(blocked.status_code, 409)

        self.assertEqual(
            self.client.delete(f"/api/unidades-geracao/{unit['id']}").status_code,
            204,
        )
        self.assertEqual(
            self.client.delete(f"/api/proprietarios/{owner_two['id']}").status_code,
            204,
        )

    def test_generation_unit_sale_price_is_exact_across_crud_and_validation(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Owner Sale Price")
        ).get_json()

        payload = self.generation_unit_payload(owner["id"], "3000")
        payload["preco_venda_kwh"] = "1,5864"
        created_response = self.post_json("/api/unidades-geracao", payload)
        self.assertEqual(created_response.status_code, 201)
        created = created_response.get_json()
        self.assertEqual(created["preco_venda_kwh"], "1.5864")

        connection = sqlite3.connect(Path(self.temp_dir.name) / "test.db")
        stored_price = connection.execute(
            "SELECT preco_venda_kwh FROM unidades_geracao WHERE id = ?",
            (created["id"],),
        ).fetchone()[0]
        connection.close()
        self.assertEqual(stored_price, 15864)

        fetched = self.client.get(f"/api/unidades-geracao/{created['id']}")
        self.assertEqual(fetched.get_json()["preco_venda_kwh"], "1.5864")
        listed = self.client.get("/api/unidades-geracao").get_json()
        self.assertEqual(listed[0]["preco_venda_kwh"], "1.5864")

        changed = self.generation_unit_payload(owner["id"], "3000")
        changed["preco_venda_kwh"] = "1"
        updated = self.put_json(f"/api/unidades-geracao/{created['id']}", changed)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["preco_venda_kwh"], "1")

        for invalid_price in ("-1", "1,23456", "not-a-price"):
            invalid = self.generation_unit_payload(owner["id"], "0")
            invalid["preco_venda_kwh"] = invalid_price
            response = self.post_json("/api/unidades-geracao", invalid)
            self.assertEqual(response.status_code, 400, invalid_price)

        empty = self.generation_unit_payload(owner["id"], "0")
        empty["inscricao_mun"] = "UG-EMPTY-PRICE"
        empty_response = self.post_json("/api/unidades-geracao", empty)
        self.assertEqual(empty_response.status_code, 201)
        self.assertIsNone(empty_response.get_json()["preco_venda_kwh"])

    def test_property_generation_unit_link_crud_and_integrity(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário do Vínculo")
        ).get_json()
        unit = self.post_json(
            "/api/unidades-geracao",
            self.generation_unit_payload(owner["id"], "3000"),
        ).get_json()
        client = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente de Energia")
        ).get_json()

        linked_payload = self.property_payload(owner["id"])
        linked_payload.update(
            {
                "unidade_geradora_id": unit["id"],
                "percentual_energia": "35,5",
                "cliente_energia_solar_id": client["id"],
            }
        )
        created = self.post_json("/api/imoveis", linked_payload)
        self.assertEqual(created.status_code, 201)
        property_data = created.get_json()
        self.assertEqual(property_data["unidade_geradora_id"], unit["id"])
        self.assertEqual(property_data["unidade_geradora_identificacao"], "UG-001")

        fetched = self.client.get(f"/api/imoveis/{property_data['id']}").get_json()
        self.assertEqual(fetched["unidade_geradora_id"], unit["id"])

        shared_payload = self.property_payload(owner["id"])
        shared_payload["cliente_energia_solar_id"] = client["id"]
        shared_payload.update(
            {"apelido": "Outro imóvel solar", "unidade_geradora_id": unit["id"], "percentual_energia": "0"}
        )
        shared = self.post_json("/api/imoveis", shared_payload)
        self.assertEqual(shared.status_code, 201)
        self.assertEqual(shared.get_json()["unidade_geradora_id"], unit["id"])

        changed = dict(linked_payload)
        changed.update({"unidade_geradora_id": "", "percentual_energia": "25"})
        updated = self.put_json(f"/api/imoveis/{property_data['id']}", changed)
        self.assertEqual(updated.status_code, 200)
        self.assertIsNone(updated.get_json()["unidade_geradora_id"])
        self.assertEqual(updated.get_json()["percentual_energia"], 25.0)

        blocked = self.client.delete(f"/api/unidades-geracao/{unit['id']}")
        self.assertEqual(blocked.status_code, 409)

        self.assertEqual(self.client.delete(f"/api/imoveis/{shared.get_json()['id']}").status_code, 204)
        connection = sqlite3.connect(Path(self.temp_dir.name) / "test.db")
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM imovel_unidade_geradora WHERE imovel_id = ?",
                (shared.get_json()["id"],),
            ).fetchone()[0],
            0,
        )
        connection.close()

    def test_property_generation_unit_validation_and_optional_percentage(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Validação do Vínculo")
        ).get_json()
        unit = self.post_json(
            "/api/unidades-geracao",
            self.generation_unit_payload(owner["id"], "0"),
        ).get_json()
        client = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente da Unidade")
        ).get_json()

        without_unit = self.property_payload(owner["id"])
        without_unit["unidade_geradora_id"] = ""
        without_unit["percentual_energia"] = ""
        self.assertEqual(self.post_json("/api/imoveis", without_unit).status_code, 201)

        missing_percentage = self.property_payload(owner["id"])
        missing_percentage["unidade_geradora_id"] = unit["id"]
        missing_percentage["percentual_energia"] = ""
        missing_percentage["cliente_energia_solar_id"] = client["id"]
        self.assertEqual(self.post_json("/api/imoveis", missing_percentage).status_code, 400)

        zero_percentage = self.property_payload(owner["id"])
        zero_percentage["unidade_geradora_id"] = unit["id"]
        zero_percentage["percentual_energia"] = "0"
        zero_percentage["cliente_energia_solar_id"] = client["id"]
        self.assertEqual(self.post_json("/api/imoveis", zero_percentage).status_code, 201)

        invalid_unit = self.property_payload(owner["id"])
        invalid_unit["unidade_geradora_id"] = 999
        invalid_unit["percentual_energia"] = "10"
        self.assertEqual(self.post_json("/api/imoveis", invalid_unit).status_code, 400)

        legacy_payload = self.property_payload(owner["id"])
        legacy_payload.pop("unidade_geradora_id")
        legacy_payload["unidade_geradora"] = "UG-LIVRE"
        self.assertEqual(self.post_json("/api/imoveis", legacy_payload).status_code, 400)

    def test_generation_distribution_is_scoped_to_unit_and_keeps_property_rows(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario da Distribuicao")
        ).get_json()
        client_one = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Distribuicao Um")
        ).get_json()
        client_two = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Distribuicao Dois")
        ).get_json()
        unit_one = self.post_json(
            "/api/unidades-geracao",
            self.generation_unit_payload(owner["id"], "3000"),
        ).get_json()
        unit_two_payload = self.generation_unit_payload(owner["id"], "2500")
        unit_two_payload["inscricao_mun"] = "UG-002"
        unit_two = self.post_json("/api/unidades-geracao", unit_two_payload).get_json()

        def create_linked_property(name, unit_id, client_id, percentage):
            property_data = self.property_payload(owner["id"])
            property_data.update(
                {
                    "apelido": name,
                    "unidade_geradora_id": unit_id,
                    "cliente_energia_solar_id": client_id,
                    "percentual_energia": percentage,
                }
            )
            return self.post_json("/api/imoveis", property_data).get_json()

        first = create_linked_property(
            "Imovel Distribuicao Um", unit_one["id"], client_one["id"], "35,5"
        )
        second = create_linked_property(
            "Imovel Distribuicao Dois", unit_one["id"], client_one["id"], "0"
        )
        third = create_linked_property(
            "Imovel Distribuicao Tres", unit_one["id"], client_two["id"], "20"
        )
        other_unit_property = create_linked_property(
            "Imovel Outra Unidade", unit_two["id"], client_two["id"], "90"
        )
        unrelated = self.property_payload(owner["id"])
        unrelated["apelido"] = "Imovel Sem Unidade"
        unrelated["percentual_energia"] = "15"
        unrelated_property = self.post_json("/api/imoveis", unrelated).get_json()

        response = self.client.get(
            f"/api/unidades-geracao/{unit_one['id']}/distribuicao",
            query_string={"proprietario_id": "999", "adm_propriedade": "maybe"},
        )
        self.assertEqual(response.status_code, 200)
        distribution = response.get_json()
        self.assertEqual(
            distribution["unidade"],
            {"id": unit_one["id"], "identificacao": "UG-001"},
        )
        self.assertEqual(
            [item["imovel_id"] for item in distribution["distribuicoes"]],
            [second["id"], third["id"], first["id"]],
        )
        self.assertEqual(
            [item["cliente_id"] for item in distribution["distribuicoes"]],
            [client_one["id"], client_two["id"], client_one["id"]],
        )
        self.assertEqual(
            [item["percentual_distribuicao"] for item in distribution["distribuicoes"]],
            [0.0, 20.0, 35.5],
        )
        self.assertEqual(
            [item["kwh_mes_estimado"] for item in distribution["distribuicoes"]],
            [0, 600, 1065],
        )
        self.assertEqual(
            distribution["totais"]["distribuicao"],
            {
                "quantidade_imoveis": 3,
                "percentual_distribuicao": 55.5,
                "kwh_mes_estimado": 1665,
            },
        )
        self.assertEqual(
            [item["imovel_id"] for item in distribution["cobrancas"]],
            [second["id"], third["id"], first["id"]],
        )
        self.assertEqual(
            distribution["totais"]["cobranca"],
            {
                "quantidade_imoveis": 3,
                "kwh_mes_estimado": 1665,
                "valor_mensal": None,
            },
        )
        self.assertNotIn(
            other_unit_property["id"],
            [item["imovel_id"] for item in distribution["distribuicoes"]],
        )
        self.assertNotIn(
            unrelated_property["id"],
            [item["imovel_id"] for item in distribution["distribuicoes"]],
        )

        empty_unit_payload = self.generation_unit_payload(owner["id"], "100")
        empty_unit_payload["inscricao_mun"] = "UG-EMPTY"
        empty_unit = self.post_json(
            "/api/unidades-geracao", empty_unit_payload
        ).get_json()
        empty_response = self.client.get(
            f"/api/unidades-geracao/{empty_unit['id']}/distribuicao"
        )
        self.assertEqual(empty_response.status_code, 200)
        self.assertEqual(empty_response.get_json()["distribuicoes"], [])
        self.assertEqual(empty_response.get_json()["cobrancas"], [])
        self.assertEqual(
            empty_response.get_json()["totais"],
            {
                "distribuicao": {
                    "quantidade_imoveis": 0,
                    "percentual_distribuicao": 0.0,
                    "kwh_mes_estimado": 0,
                },
                "cobranca": {
                    "quantidade_imoveis": 0,
                    "kwh_mes_estimado": 0,
                    "valor_mensal": "0.00",
                },
            },
        )
        self.assertEqual(
            self.client.get("/api/unidades-geracao/999/distribuicao").status_code,
            404,
        )

    def test_generation_distribution_billing_filters_charge_flag_and_rounds_money(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario da Cobranca")
        ).get_json()
        client_one = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Cobranca Um")
        ).get_json()
        client_two = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Cobranca Dois")
        ).get_json()
        unit_payload = self.generation_unit_payload(owner["id"], "3000")
        unit_payload["preco_venda_kwh"] = "1,5864"
        unit = self.post_json("/api/unidades-geracao", unit_payload).get_json()

        def create_property(name, client_id, percentage, charge):
            property_data = self.property_payload(owner["id"])
            property_data.update(
                {
                    "apelido": name,
                    "unidade_geradora_id": unit["id"],
                    "cliente_energia_solar_id": client_id,
                    "percentual_energia": percentage,
                    "adm_propriedade": str(charge),
                }
            )
            return self.post_json("/api/imoveis", property_data).get_json()

        charge_one = create_property(
            "Imovel Cobranca Um", client_one["id"], "35,5", 1
        )
        no_charge = create_property(
            "Imovel Sem Cobranca", client_two["id"], "20", 0
        )
        charge_two = create_property(
            "Imovel Cobranca Dois", client_two["id"], "10", 1
        )

        data = self.client.get(
            f"/api/unidades-geracao/{unit['id']}/distribuicao"
        ).get_json()
        self.assertEqual(
            [item["imovel_id"] for item in data["distribuicoes"]],
            [charge_two["id"], charge_one["id"], no_charge["id"]],
        )
        self.assertEqual(
            [item["imovel_id"] for item in data["cobrancas"]],
            [charge_two["id"], charge_one["id"]],
        )
        self.assertEqual(
            [item["valor_mensal"] for item in data["cobrancas"]],
            ["475.92", "1689.52"],
        )
        self.assertEqual(
            data["totais"],
            {
                "distribuicao": {
                    "quantidade_imoveis": 3,
                    "percentual_distribuicao": 65.5,
                    "kwh_mes_estimado": 1965,
                },
                "cobranca": {
                    "quantidade_imoveis": 2,
                    "kwh_mes_estimado": 1365,
                    "valor_mensal": "2165.44",
                },
            },
        )
        pdf_response = self.client.get(
            f"/api/unidades-geracao/{unit['id']}/distribuicao/pdf"
        )
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF-"))
        self.assertIn("attachment", pdf_response.headers["Content-Disposition"])

        rounded_unit_payload = self.generation_unit_payload(owner["id"], "1")
        rounded_unit_payload["inscricao_mun"] = "UG-MONEY-ROUND"
        rounded_unit_payload["preco_venda_kwh"] = "1,005"
        rounded_unit = self.post_json(
            "/api/unidades-geracao", rounded_unit_payload
        ).get_json()
        rounded_property = self.property_payload(owner["id"])
        rounded_property.update(
            {
                "apelido": "Imovel Arredondamento Monetario",
                "unidade_geradora_id": rounded_unit["id"],
                "cliente_energia_solar_id": client_one["id"],
                "percentual_energia": "100",
                "adm_propriedade": "1",
            }
        )
        self.post_json("/api/imoveis", rounded_property)
        rounded_data = self.client.get(
            f"/api/unidades-geracao/{rounded_unit['id']}/distribuicao"
        ).get_json()
        self.assertEqual(rounded_data["cobrancas"][0]["valor_mensal"], "1.01")
        self.assertEqual(
            rounded_data["totais"]["cobranca"]["valor_mensal"], "1.01"
        )

    def test_generation_distribution_estimate_rounds_half_up_and_handles_missing_generation(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario do Arredondamento")
        ).get_json()
        client = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente do Arredondamento")
        ).get_json()

        rounded_unit = self.generation_unit_payload(owner["id"], "5")
        rounded_unit["inscricao_mun"] = "UG-ROUND"
        rounded_unit = self.post_json("/api/unidades-geracao", rounded_unit).get_json()
        rounded_property = self.property_payload(owner["id"])
        rounded_property.update(
            {
                "apelido": "Imovel Arredondamento",
                "unidade_geradora_id": rounded_unit["id"],
                "cliente_energia_solar_id": client["id"],
                "percentual_energia": "10",
            }
        )
        self.post_json("/api/imoveis", rounded_property)

        rounded_distribution = self.client.get(
            f"/api/unidades-geracao/{rounded_unit['id']}/distribuicao"
        ).get_json()
        self.assertEqual(
            rounded_distribution["distribuicoes"][0]["kwh_mes_estimado"], 1
        )

        missing_unit = self.generation_unit_payload(owner["id"], "")
        missing_unit["inscricao_mun"] = "UG-MISSING"
        missing_unit = self.post_json("/api/unidades-geracao", missing_unit).get_json()
        missing_property = self.property_payload(owner["id"])
        missing_property.update(
            {
                "apelido": "Imovel Geracao Ausente",
                "unidade_geradora_id": missing_unit["id"],
                "cliente_energia_solar_id": client["id"],
                "percentual_energia": "35,5",
            }
        )
        self.post_json("/api/imoveis", missing_property)

        missing_distribution = self.client.get(
            f"/api/unidades-geracao/{missing_unit['id']}/distribuicao"
        ).get_json()
        self.assertIsNone(
            missing_distribution["distribuicoes"][0]["kwh_mes_estimado"]
        )
        self.assertIsNone(missing_distribution["cobrancas"][0]["valor_mensal"])
        self.assertIsNone(
            missing_distribution["totais"]["cobranca"]["valor_mensal"]
        )

    def test_distribution_analysis_markup_and_frontend_hooks(self):
        page = self.client.get("/").get_data(as_text=True)
        source = (
            Path(__file__).resolve().parents[1] / "static" / "js" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn('id="distribution-modal"', page)
        self.assertIn('id="distribution-chart"', page)
        self.assertIn('id="distribution-table-body"', page)
        self.assertIn('id="distribution-table-count"', page)
        self.assertIn('id="distribution-total-percentage"', page)
        self.assertIn('id="distribution-total-kwh"', page)
        self.assertIn('id="billing-table-body"', page)
        self.assertIn('id="billing-table-count"', page)
        self.assertIn('id="billing-total-kwh"', page)
        self.assertIn('id="billing-total-amount"', page)
        self.assertIn('id="distribution-download"', page)
        self.assertIn("Baixar relatório PDF", page)
        self.assertIn("Tabela de cobrança", page)
        self.assertIn("R$/mês", page)
        self.assertIn("<tfoot>", page)
        self.assertIn("Cliente energia solar", page)
        self.assertIn("Percentual de distribuição (%)", page)
        self.assertIn("kWh/mês estimado", page)
        self.assertIn('data-action="distribution"', source)
        self.assertIn("/api/unidades-geracao/${record.id}/distribuicao", source)
        self.assertIn("distribution-slice", source)
        self.assertIn("formatDistributionPercentage", source)
        self.assertIn("kwh_mes_estimado", source)
        self.assertIn("formatEstimatedKwh", source)
        self.assertIn("function renderBillingRows", source)
        self.assertIn("data.cobrancas", source)
        self.assertIn("totals.cobranca", source)
        self.assertIn("formatCurrency(billing.valor_mensal)", source)
        self.assertIn("function formatPropertyCount", source)
        self.assertIn("function downloadDistributionPdf", source)
        self.assertIn("/distribuicao/pdf", source)
        self.assertIn("function firstClientName", source)
        self.assertIn("firstClientName(distribution.cliente_nome)", source)
        self.assertIn("distributionRequestId", source)
        self.assertNotIn("\ufffd", page)
        self.assertNotIn("\ufffd", source)

    def test_property_solar_client_relationship_validation_and_crud(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario do Cliente Solar")
        ).get_json()
        client = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Solar")
        ).get_json()
        unit = self.post_json(
            "/api/unidades-geracao",
            self.generation_unit_payload(owner["id"], "1200"),
        ).get_json()

        without_unit = self.property_payload(owner["id"])
        without_unit["percentual_energia"] = ""
        created_without_client = self.post_json("/api/imoveis", without_unit)
        self.assertEqual(created_without_client.status_code, 201)
        self.assertIsNone(created_without_client.get_json()["cliente_energia_solar_id"])

        with_client_without_unit = self.property_payload(owner["id"])
        with_client_without_unit["apelido"] = "Imovel com Cliente Solar"
        with_client_without_unit["cliente_energia_solar_id"] = client["id"]
        with_client_without_unit["percentual_energia"] = ""
        created_without_unit = self.post_json("/api/imoveis", with_client_without_unit)
        self.assertEqual(created_without_unit.status_code, 201)
        self.assertEqual(
            created_without_unit.get_json()["cliente_energia_solar_id"], client["id"]
        )

        missing_client = self.property_payload(owner["id"])
        missing_client["unidade_geradora_id"] = unit["id"]
        missing_client["percentual_energia"] = "25"
        self.assertEqual(self.post_json("/api/imoveis", missing_client).status_code, 400)

        invalid_client = dict(missing_client)
        invalid_client["cliente_energia_solar_id"] = 999
        self.assertEqual(self.post_json("/api/imoveis", invalid_client).status_code, 400)

        text_client = dict(without_unit)
        text_client["cliente_energia_solar_id"] = client["nome_completo"]
        self.assertEqual(self.post_json("/api/imoveis", text_client).status_code, 400)

        linked_payload = self.property_payload(owner["id"])
        linked_payload.update(
            {
                "apelido": "Imovel Vinculado ao Cliente",
                "unidade_geradora_id": unit["id"],
                "percentual_energia": "25",
                "cliente_energia_solar_id": client["id"],
            }
        )
        linked = self.post_json("/api/imoveis", linked_payload)
        self.assertEqual(linked.status_code, 201)
        property_id = linked.get_json()["id"]
        self.assertEqual(
            self.client.get(f"/api/imoveis/{property_id}").get_json()["cliente_energia_solar_id"],
            client["id"],
        )

        missing_on_update = dict(linked_payload)
        missing_on_update["cliente_energia_solar_id"] = ""
        self.assertEqual(self.put_json(f"/api/imoveis/{property_id}", missing_on_update).status_code, 400)

        cleared = dict(linked_payload)
        cleared["unidade_geradora_id"] = ""
        cleared["cliente_energia_solar_id"] = ""
        cleared["percentual_energia"] = ""
        updated = self.put_json(f"/api/imoveis/{property_id}", cleared)
        self.assertEqual(updated.status_code, 200)
        self.assertIsNone(updated.get_json()["cliente_energia_solar_id"])

    def test_solar_client_delete_is_blocked_while_linked_to_property(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario do Vinculo Solar")
        ).get_json()
        client = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Protegido")
        ).get_json()
        property_payload = self.property_payload(owner["id"])
        property_payload["cliente_energia_solar_id"] = client["id"]
        property_payload["percentual_energia"] = ""
        property_data = self.post_json("/api/imoveis", property_payload).get_json()

        blocked = self.client.delete(f"/api/inquilinos-clientes/{client['id']}")
        self.assertEqual(blocked.status_code, 409)

        cleared = self.property_payload(owner["id"])
        cleared["percentual_energia"] = ""
        self.assertEqual(
            self.put_json(f"/api/imoveis/{property_data['id']}", cleared).status_code,
            200,
        )
        self.assertEqual(self.client.delete(f"/api/inquilinos-clientes/{client['id']}").status_code, 204)

    def test_generation_unit_validation_and_optional_generation(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Validação Solar")
        ).get_json()

        optional_payload = self.generation_unit_payload(owner["id"], "")
        optional = self.post_json("/api/unidades-geracao", optional_payload)
        self.assertEqual(optional.status_code, 201)
        self.assertIsNone(optional.get_json()["geracao_mensal_kwh"])

        maximum = self.post_json(
            "/api/unidades-geracao",
            self.generation_unit_payload(owner["id"], "9999999"),
        )
        self.assertEqual(maximum.status_code, 201)
        self.assertEqual(maximum.get_json()["geracao_mensal_kwh"], 9999999)

        invalid_values = ("-1", "1.5", "abc", "10000000", True)
        for value in invalid_values:
            invalid = self.post_json(
                "/api/unidades-geracao",
                self.generation_unit_payload(owner["id"], value),
            )
            self.assertEqual(invalid.status_code, 400, value)

        missing_owner = self.post_json(
            "/api/unidades-geracao", self.generation_unit_payload(None, "0")
        )
        self.assertEqual(missing_owner.status_code, 400)
        invalid_owner = self.post_json(
            "/api/unidades-geracao", self.generation_unit_payload(999, "0")
        )
        self.assertEqual(invalid_owner.status_code, 400)

        invalid_cep = self.generation_unit_payload(owner["id"], "0")
        invalid_cep["cep"] = "123"
        self.assertEqual(self.post_json("/api/unidades-geracao", invalid_cep).status_code, 400)
        invalid_state = self.generation_unit_payload(owner["id"], "0")
        invalid_state["estado"] = "XX"
        self.assertEqual(self.post_json("/api/unidades-geracao", invalid_state).status_code, 400)
        self.assertEqual(
            self.client.get("/api/unidades-geracao?proprietario_id=abc").status_code,
            400,
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
        self.assertEqual(contract["dia_pagamento"], 5)
        self.assertEqual(contract["valor_caucao"], 5000.0)
        self.assertEqual(contract["status"], "ATIVO")
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

    def test_contract_status_default_update_and_reactivation(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario Status")
        ).get_json()
        property_data = self.post_json(
            "/api/imoveis", self.property_payload(owner["id"])
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Status")
        ).get_json()
        payload = self.contract_payload(property_data["id"], tenant["id"])

        created = self.post_json("/api/contratos", payload)
        self.assertEqual(created.status_code, 201)
        contract = created.get_json()
        self.assertEqual(contract["status"], "ATIVO")

        connection = sqlite3.connect(Path(self.temp_dir.name) / "test.db")
        persisted_status = connection.execute(
            "SELECT status FROM contratos WHERE id = ?", (contract["id"],)
        ).fetchone()
        connection.close()
        self.assertEqual(persisted_status, ("ATIVO",))

        closed_payload = dict(payload, status="Encerrado", data_fim="2028-01-01")
        closed = self.put_json(f"/api/contratos/{contract['id']}", closed_payload)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.get_json()["status"], "ENCERRADO")

        legacy_update = dict(payload, data_fim="2029-01-01")
        preserved = self.put_json(f"/api/contratos/{contract['id']}", legacy_update)
        self.assertEqual(preserved.status_code, 200)
        self.assertEqual(preserved.get_json()["status"], "ENCERRADO")

        listed = self.client.get("/api/contratos").get_json()
        self.assertEqual(
            [record["id"] for record in listed if record["status"] == "ATIVO"],
            [],
        )
        self.assertEqual(
            [record["id"] for record in listed if record["status"] == "ENCERRADO"],
            [contract["id"]],
        )

        reactivated = self.put_json(
            f"/api/contratos/{contract['id']}",
            dict(payload, status="Ativo"),
        )
        self.assertEqual(reactivated.status_code, 200)
        self.assertEqual(reactivated.get_json()["status"], "ATIVO")

        listed = self.client.get("/api/contratos").get_json()
        self.assertEqual(
            [record["id"] for record in listed if record["status"] == "ATIVO"],
            [contract["id"]],
        )
        self.assertEqual(
            [record["id"] for record in listed if record["status"] == "ENCERRADO"],
            [],
        )

        invalid = self.post_json("/api/contratos", dict(payload, status="PAUSADO"))
        self.assertEqual(invalid.status_code, 400)
        invalid_update = self.put_json(
            f"/api/contratos/{contract['id']}", dict(payload, status="PAUSADO")
        )
        self.assertEqual(invalid_update.status_code, 400)

    def test_financial_report_calculates_rows_summary_and_owner_filter(self):
        owner_one = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario Relatorio Um")
        ).get_json()
        owner_two = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario Relatorio Dois")
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Relatorio")
        ).get_json()

        def create_property(
            owner_id,
            name,
            iptu_repass,
            condominium_repass,
            rent="1000",
            administration_fee="R$ 100,00",
            administration_flag="1",
        ):
            payload = self.property_payload(owner_id)
            payload.update(
                {
                    "apelido": name,
                    "repasse_iptu": str(iptu_repass),
                    "valor_iptu": "R$ 559,97",
                    "repasse_taxa_condominio": str(condominium_repass),
                    "valor_condominio": "R$ 393,59",
                    "imobiliaria": administration_flag,
                    "taxa_adm_imovel": administration_fee,
                }
            )
            property_data = self.post_json("/api/imoveis", payload).get_json()
            contract_payload = self.contract_payload(property_data["id"], tenant["id"])
            contract_payload.update({"valor_aluguel": f"R$ {rent},00"})
            contract = self.post_json("/api/contratos", contract_payload).get_json()
            return property_data, contract

        both_discounted, _ = create_property(owner_one["id"], "Relatorio Ambos", 0, 0)
        both_repassed, _ = create_property(owner_one["id"], "Relatorio Nenhum", 1, 1)
        iptu_repassed, _ = create_property(
            owner_one["id"], "Relatorio IPTU", 1, 0, administration_fee="R$ 50,00"
        )
        condominium_repassed, _ = create_property(
            owner_two["id"],
            "Relatorio Condominio",
            0,
            1,
            administration_fee="R$ 100,00",
            administration_flag="0",
        )
        no_contract = self.property_payload(owner_two["id"])
        no_contract["apelido"] = "Relatorio Sem Contrato"
        self.post_json("/api/imoveis", no_contract)

        closed_property = self.property_payload(owner_two["id"])
        closed_property["apelido"] = "Relatorio Encerrado"
        closed_property = self.post_json("/api/imoveis", closed_property).get_json()
        closed_payload = self.contract_payload(closed_property["id"], tenant["id"])
        closed_payload["status"] = "ENCERRADO"
        self.assertEqual(self.post_json("/api/contratos", closed_payload).status_code, 201)

        report = self.client.get("/api/relatorios")
        self.assertEqual(report.status_code, 200)
        data = report.get_json()
        self.assertEqual(len(data["linhas"]), 4)
        rows = {row["imovel_id"]: row for row in data["linhas"]}

        first = rows[both_discounted["id"]]
        self.assertEqual(first["tipo_linha"], "CONTRATO_ATIVO")
        self.assertNotIn("taxa_adm_imovel", first)
        self.assertEqual(
            {
                first["aluguel_bruto"],
                first["iptu_mensal"],
                first["condominio_descontado"],
                first["aluguel_liquido"],
                first["margem_liquida_percentual"],
            },
            {1000.0, 46.66, 393.59, 459.75, 45.98},
        )
        self.assertEqual(first["dia_pagamento"], 5)

        self.assertEqual(rows[both_repassed["id"]]["iptu_mensal"], 0.0)
        self.assertEqual(rows[both_repassed["id"]]["condominio_descontado"], 0.0)
        self.assertEqual(rows[both_repassed["id"]]["aluguel_liquido"], 900.0)
        self.assertEqual(rows[iptu_repassed["id"]]["iptu_mensal"], 0.0)
        self.assertEqual(rows[iptu_repassed["id"]]["condominio_descontado"], 393.59)
        self.assertEqual(rows[iptu_repassed["id"]]["aluguel_liquido"], 556.41)
        self.assertEqual(rows[condominium_repassed["id"]]["iptu_mensal"], 46.66)
        self.assertEqual(rows[condominium_repassed["id"]]["condominio_descontado"], 0.0)
        self.assertEqual(rows[condominium_repassed["id"]]["aluguel_liquido"], 953.34)

        self.assertEqual(data["resumo"]["total_aluguel_bruto"], 4000.0)
        self.assertEqual(data["resumo"]["total_iptu_descontado"], 93.32)
        self.assertEqual(data["resumo"]["total_condominio_descontado"], 787.18)
        self.assertEqual(data["resumo"]["total_aluguel_liquido"], 2869.5)
        self.assertEqual(data["resumo"]["margem_liquida_percentual"], 71.74)

        filtered = self.client.get(
            "/api/relatorios", query_string={"proprietario_id": owner_two["id"]}
        ).get_json()
        self.assertEqual(
            {row["imovel_id"] for row in filtered["linhas"]},
            {condominium_repassed["id"]},
        )
        self.assertEqual(filtered["resumo"]["total_aluguel_bruto"], 1000.0)

    def test_financial_report_includes_vacant_expenses_without_duplicates(self):
        owner_one = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario Desocupado Um")
        ).get_json()
        owner_two = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario Desocupado Dois")
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Desocupado")
        ).get_json()

        def create_property(
            owner_id,
            name,
            iptu,
            iptu_repass,
            condominium,
            condominium_repass,
        ):
            payload = self.property_payload(owner_id)
            payload.update(
                {
                    "apelido": name,
                    "repasse_iptu": str(iptu_repass),
                    "valor_iptu": f"R$ {iptu},00",
                    "repasse_taxa_condominio": str(condominium_repass),
                    "valor_condominio": f"R$ {condominium},00",
                }
            )
            return self.post_json("/api/imoveis", payload).get_json()

        active = create_property(owner_one["id"], "Despesas Ativo", "1200", 0, "300", 0)
        active_contract = self.contract_payload(active["id"], tenant["id"])
        active_contract["valor_aluguel"] = "R$ 2000,00"
        self.assertEqual(self.post_json("/api/contratos", active_contract).status_code, 201)

        vacant_iptu = create_property(owner_one["id"], "Vaga IPTU", "600", 0, "0", 0)
        vacant_condominium = create_property(
            owner_one["id"], "Vaga Condominio", "0", 0, "250", 0
        )
        vacant_both = create_property(
            owner_one["id"], "Vaga Ambos", "1200", 0, "400", 0
        )
        repassed = create_property(
            owner_one["id"], "Vaga Repassada", "600", 1, "250", 1
        )
        zero_values = create_property(
            owner_one["id"], "Vaga Zerada", "0", 0, "0", 0
        )
        closed = create_property(
            owner_one["id"], "Vaga Encerrada", "300", 0, "180", 0
        )
        closed_contract = self.contract_payload(closed["id"], tenant["id"])
        closed_contract["status"] = "ENCERRADO"
        self.assertEqual(self.post_json("/api/contratos", closed_contract).status_code, 201)

        owner_two_vacant = create_property(
            owner_two["id"], "Vaga Outro Proprietario", "0", 0, "300", 0
        )

        report = self.client.get("/api/relatorios")
        self.assertEqual(report.status_code, 200)
        data = report.get_json()
        self.assertEqual(len(data["linhas"]), 6)
        rows = {row["imovel_id"]: row for row in data["linhas"]}

        self.assertEqual(
            {row["imovel_id"] for row in data["linhas"]},
            {
                active["id"],
                vacant_iptu["id"],
                vacant_condominium["id"],
                vacant_both["id"],
                closed["id"],
                owner_two_vacant["id"],
            },
        )
        self.assertNotIn(repassed["id"], rows)
        self.assertNotIn(zero_values["id"], rows)

        self.assertEqual(rows[active["id"]]["tipo_linha"], "CONTRATO_ATIVO")
        self.assertEqual(rows[active["id"]]["aluguel_bruto"], 2000.0)
        self.assertEqual(rows[active["id"]]["aluguel_liquido"], 1600.0)

        self.assertEqual(rows[vacant_iptu["id"]]["tipo_linha"], "DESOCUPADO_DESPESA")
        self.assertEqual(rows[vacant_iptu["id"]]["iptu_mensal"], 50.0)
        self.assertEqual(rows[vacant_iptu["id"]]["condominio_descontado"], 0.0)
        self.assertEqual(rows[vacant_iptu["id"]]["aluguel_bruto"], 0.0)
        self.assertEqual(rows[vacant_iptu["id"]]["aluguel_liquido"], -50.0)
        self.assertIsNone(rows[vacant_iptu["id"]]["contrato_id"])
        self.assertIsNone(rows[vacant_iptu["id"]]["dia_pagamento"])

        self.assertEqual(rows[vacant_condominium["id"]]["iptu_mensal"], 0.0)
        self.assertEqual(
            rows[vacant_condominium["id"]]["condominio_descontado"], 250.0
        )
        self.assertEqual(rows[vacant_condominium["id"]]["aluguel_liquido"], -250.0)
        self.assertEqual(rows[vacant_both["id"]]["iptu_mensal"], 100.0)
        self.assertEqual(rows[vacant_both["id"]]["condominio_descontado"], 400.0)
        self.assertEqual(rows[closed["id"]]["aluguel_liquido"], -205.0)

        self.assertEqual(data["resumo"]["total_aluguel_bruto"], 2000.0)
        self.assertEqual(data["resumo"]["total_iptu_descontado"], 275.0)
        self.assertEqual(data["resumo"]["total_condominio_descontado"], 1430.0)
        self.assertEqual(data["resumo"]["total_aluguel_liquido"], 295.0)
        self.assertEqual(data["resumo"]["margem_liquida_percentual"], 14.75)

        filtered = self.client.get(
            "/api/relatorios", query_string={"proprietario_id": owner_two["id"]}
        ).get_json()
        self.assertEqual(
            [row["imovel_id"] for row in filtered["linhas"]],
            [owner_two_vacant["id"]],
        )
        self.assertEqual(filtered["resumo"]["total_aluguel_bruto"], 0.0)
        self.assertEqual(filtered["resumo"]["total_condominio_descontado"], 300.0)
        self.assertEqual(filtered["resumo"]["total_aluguel_liquido"], -300.0)
        self.assertEqual(filtered["resumo"]["margem_liquida_percentual"], 0.0)

    def test_financial_report_uses_latest_active_period_once_per_property(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietario Periodo Relatorio")
        ).get_json()
        property_data = self.post_json(
            "/api/imoveis", self.property_payload(owner["id"])
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Periodo Relatorio")
        ).get_json()

        first_payload = self.contract_payload(property_data["id"], tenant["id"])
        first_payload.update({"data_inicio": "2026-01-01", "valor_aluguel": "R$ 1000,00"})
        self.assertEqual(self.post_json("/api/contratos", first_payload).status_code, 201)

        second_payload = self.contract_payload(property_data["id"], tenant["id"])
        second_payload.update(
            {
                "data_inicio": "2026-03-01",
                "valor_aluguel": "R$ 1200,00",
                "dia_pagamento": "15",
            }
        )
        second = self.post_json("/api/contratos", second_payload).get_json()

        report = self.client.get("/api/relatorios").get_json()
        self.assertEqual(len(report["linhas"]), 1)
        row = report["linhas"][0]
        self.assertEqual(row["contrato_id"], second["id"])
        self.assertEqual(row["aluguel_bruto"], 1200.0)
        self.assertEqual(row["dia_pagamento"], 15)

        zero_rent = self.property_payload(owner["id"])
        zero_rent.update({"apelido": "Relatorio Zero", "aluguel": "R$ 0,00"})
        zero_property = self.post_json("/api/imoveis", zero_rent).get_json()
        zero_contract = self.contract_payload(zero_property["id"], tenant["id"])
        zero_contract["valor_aluguel"] = "R$ 0,00"
        self.assertEqual(self.post_json("/api/contratos", zero_contract).status_code, 201)

        zero_row = next(
            item
            for item in self.client.get("/api/relatorios").get_json()["linhas"]
            if item["imovel_id"] == zero_property["id"]
        )
        self.assertEqual(zero_row["aluguel_liquido"], 0.0)
        self.assertEqual(zero_row["margem_liquida_percentual"], 0.0)

    def test_quick_search_consolidates_properties_and_searches_related_fields(self):
        owner_payload = self.person_payload("Proprietario Busca Rapida")
        owner_payload["cpf"] = "123.456.789-09"
        owner = self.post_json("/api/proprietarios", owner_payload).get_json()
        vacant_owner_payload = self.person_payload("Proprietario Imovel Vago")
        vacant_owner_payload["cpf"] = ""
        vacant_owner = self.post_json(
            "/api/proprietarios", vacant_owner_payload
        ).get_json()
        solar_payload = self.person_payload("Cliente Energia Busca")
        solar_payload["cpf"] = "123.456.789-09"
        solar_client = self.post_json(
            "/api/inquilinos-clientes", solar_payload
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes",
            self.person_payload("Inquilino Busca Rapida"),
        ).get_json()

        property_payload = self.property_payload(owner["id"])
        property_payload.update(
            {
                "apelido": "Casa Busca Central",
                "inscricao_mun": "MUN-ABC-01",
                "aluguel": "R$ 1.500,00",
                "numero_energia": "ENER-10",
                "numero_agua": "AGUA-20",
                "adm_propriedade": "1",
                "cliente_energia_solar_id": str(solar_client["id"]),
                "repasse_iptu": "0",
                "valor_iptu": "R$ 1.200,00",
                "repasse_taxa_condominio": "0",
                "valor_condominio": "R$ 300,00",
                "imobiliaria": "1",
                "taxa_adm_imovel": "R$ 50,00",
            }
        )
        rented = self.post_json("/api/imoveis", property_payload).get_json()
        contract_payload = self.contract_payload(rented["id"], tenant["id"])
        contract_payload["valor_aluguel"] = "R$ 2.500,00"
        contract = self.post_json("/api/contratos", contract_payload).get_json()
        renewal = self.post_json(
            f"/api/contratos/{contract['id']}/periodos",
            {
                "data_inicio": "2027-01-01",
                "data_fim": "2028-01-01",
                "valor_aluguel": "R$ 3.000,00",
                "dia_pagamento": "10",
            },
        )
        self.assertEqual(renewal.status_code, 201)

        vacant_payload = self.property_payload(vacant_owner["id"])
        vacant_payload.update(
            {
                "apelido": "Imovel Sem Contrato",
                "cep": "",
                "endereco": "",
                "numero": "",
                "cidade": "",
                "estado": "",
                "aluguel": "R$ 900,00",
                "valor_iptu": "",
                "valor_condominio": "",
                "cliente_energia_solar_id": "",
            }
        )
        vacant = self.post_json("/api/imoveis", vacant_payload).get_json()

        response = self.client.get("/api/busca-rapida")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row["imovel_id"] for row in rows],
            sorted([rented["id"], vacant["id"]], key=lambda item: item),
        )

        rented_row = next(row for row in rows if row["imovel_id"] == rented["id"])
        self.assertEqual(rented_row["id_municipal"], "MUN-ABC-01")
        self.assertEqual(rented_row["cpf_responsavel"], "12345678909")
        self.assertEqual(rented_row["responsavel_nome"], "PROPRIETARIO BUSCA RAPIDA")
        self.assertEqual(rented_row["cep"], "01001000")
        self.assertEqual(rented_row["endereco"], "PRAÇA DA SÉ")
        self.assertEqual(rented_row["numero"], "100")
        self.assertEqual(rented_row["cidade"], "SÃO PAULO")
        self.assertEqual(rented_row["estado"], "SP")
        self.assertEqual(rented_row["inquilino"], "INQUILINO BUSCA RAPIDA")
        self.assertEqual(rented_row["cliente_energia_solar"], "CLIENTE ENERGIA BUSCA")
        self.assertEqual(rented_row["aluguel_bruto"], 3000.0)
        self.assertEqual(rented_row["aluguel_liquido"], 2550.0)
        self.assertEqual(rented_row["iptu_anual"], 1200.0)
        self.assertEqual(rented_row["iptu_mensal"], 100.0)
        self.assertEqual(rented_row["valor_condominio"], 300.0)
        self.assertEqual(rented_row["repasse_iptu"], 0)
        self.assertEqual(rented_row["repasse_condominio"], 0)
        self.assertEqual(rented_row["contrato_ativo"], 1)
        self.assertEqual(rented_row["cobranca_solar"], 1)
        self.assertEqual(rented_row["numero_energia"], "ENER-10")
        self.assertEqual(rented_row["numero_agua"], "AGUA-20")

        vacant_row = next(row for row in rows if row["imovel_id"] == vacant["id"])
        self.assertEqual(vacant_row["aluguel_bruto"], 900.0)
        self.assertEqual(vacant_row["aluguel_liquido"], 900.0)
        self.assertIsNone(vacant_row["inquilino"])
        self.assertEqual(vacant_row["contrato_ativo"], 0)
        self.assertIsNone(vacant_row["iptu_anual"])
        self.assertIsNone(vacant_row["iptu_mensal"])

        for term in (
            "MUN-ABC",
            "12345678909",
            "PROPRIETARIO BUSCA",
            "01001",
            "PRAÇA DA SÉ",
            "SÃO PAULO",
            "INQUILINO BUSCA",
            "CLIENTE ENERGIA",
            "ENER-10",
            "2550",
        ):
            result = self.client.get("/api/busca-rapida", query_string={"q": term})
            self.assertEqual(result.status_code, 200)
            self.assertEqual([row["imovel_id"] for row in result.get_json()], [rented["id"]])

        self.assertEqual(
            self.client.get(
                "/api/busca-rapida", query_string={"q": "nao-existe"}
            ).get_json(),
            [],
        )

    def test_quick_search_markup_and_frontend_hooks(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-module="busca_rapida"', page)
        self.assertIn('id="quick-search-input"', page)
        self.assertIn('id="quick-search-head"', page)
        self.assertIn('id="quick-search-body"', page)
        self.assertIn("Busca rápida", page)
        source = Path("static/js/app.js").read_text(encoding="utf-8")
        styles = Path("static/css/style.css").read_text(encoding="utf-8")
        self.assertIn('endpoint: "/api/busca-rapida"', source)
        self.assertIn('key: "responsavel_nome", label: "Nome responsável"', source)
        self.assertIn('key: "cep", label: "CEP"', source)
        self.assertIn('key: "endereco", label: "Endereço"', source)
        self.assertIn("propertyAddress(record)", source)
        self.assertIn("navigator.clipboard", source)
        self.assertIn('data-action="copy-quick-cell"', source)
        self.assertIn("quick-cell-content", source)
        self.assertIn("quick-cell-copy-button", source)
        self.assertIn('column.type === "boolean"', source)
        self.assertNotIn("quick-copy-column", source)
        self.assertNotIn("quick-copy-button", source)
        self.assertNotIn('data-action="copy-quick"', source)
        self.assertIn('showToast("Valor copiado")', source)
        self.assertIn("quick-search-table", styles)
        self.assertIn("position: sticky", styles)
        self.assertIn("quick-cell-content", styles)
        self.assertIn("quick-cell-copy-button", styles)
        self.assertIn("margin: 5px clamp(4px, .7vw, 10px) 0", styles)
        self.assertIn("padding: 0 8px 1px", styles)
        self.assertIn("border-right: 1px solid rgba(126, 141, 163, .16)", styles)
        self.assertNotIn("quick-copy-column", styles)
        self.assertNotIn("quick-copy-button", styles)

    def test_contract_period_history_renewal_edit_and_revert(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário dos Períodos")
        ).get_json()
        property_data = self.post_json(
            "/api/imoveis", self.property_payload(owner["id"])
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente dos Períodos")
        ).get_json()

        initial_payload = self.contract_payload(property_data["id"], tenant["id"])
        initial_payload["data_pagamento_caucao"] = "2026-01-05"
        contract = self.post_json("/api/contratos", initial_payload).get_json()
        contract_id = contract["id"]
        self.assertEqual(len(contract["periodos"]), 1)
        self.assertEqual(contract["periodos"][0]["data_pagamento_caucao"], "2026-01-05")

        renewal_payload = {
            "data_inicio": "2027-01-01",
            "data_fim": "2028-01-01",
            "valor_aluguel": "R$ 3.000,00",
            "dia_pagamento": "10",
            "valor_caucao": "R$ 6.000,00",
            "data_pagamento_caucao": "2027-01-05",
        }
        renewal = self.post_json(
            f"/api/contratos/{contract_id}/periodos", renewal_payload
        )
        self.assertEqual(renewal.status_code, 201)
        self.assertEqual(renewal.get_json()["valor_aluguel"], 3000.0)

        detail = self.client.get(f"/api/contratos/{contract_id}").get_json()
        self.assertEqual(detail["data_inicio"], "2027-01-01")
        self.assertEqual(detail["valor_caucao"], 6000.0)
        self.assertEqual(detail["dia_pagamento"], 10)
        self.assertEqual(detail["data_pagamento_caucao"], "2027-01-05")
        self.assertEqual(len(detail["periodos"]), 2)
        self.assertEqual(detail["periodos"][0]["data_fim"], "2026-12-31")
        self.assertEqual(detail["periodos"][0]["valor_aluguel"], 2500.0)
        self.assertEqual(detail["periodos"][0]["dia_pagamento"], 5)
        self.assertEqual(detail["periodos"][0]["data_pagamento_caucao"], "2026-01-05")
        self.assertTrue(detail["periodos"][1]["atual"])

        overlapping = self.post_json(
            f"/api/contratos/{contract_id}/periodos",
            dict(renewal_payload, data_inicio="2026-06-01"),
        )
        self.assertEqual(overlapping.status_code, 400)

        first_period_id = detail["periodos"][0]["id"]
        edited_first = self.put_json(
            f"/api/contratos/{contract_id}/periodos/{first_period_id}",
            dict(initial_payload, data_fim="2026-12-30"),
        )
        self.assertEqual(edited_first.status_code, 200)
        self.assertEqual(edited_first.get_json()["data_fim"], "2026-12-30")

        deleted_initial = self.client.delete(
            f"/api/contratos/{contract_id}/periodos/{first_period_id}"
        )
        self.assertEqual(deleted_initial.status_code, 409)

        latest_period_id = detail["periodos"][1]["id"]
        reverted = self.client.post(
            f"/api/contratos/{contract_id}/periodos/{latest_period_id}/reverter"
        )
        self.assertEqual(reverted.status_code, 204)
        reverted_detail = self.client.get(f"/api/contratos/{contract_id}").get_json()
        self.assertEqual(len(reverted_detail["periodos"]), 1)
        self.assertEqual(reverted_detail["periodos"][0]["data_fim"], "2026-12-30")
        self.assertEqual(reverted_detail["valor_aluguel"], 2500.0)

    def test_contract_period_table_is_backfilled_during_migration(self):
        database = Path(self.temp_dir.name) / "legacy-periods.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE proprietario (
                id INTEGER PRIMARY KEY, nome_completo TEXT NOT NULL, rg TEXT, cpf TEXT,
                contato TEXT, profissao TEXT, estado_civil TEXT, email TEXT
            );
            INSERT INTO proprietario (id, nome_completo) VALUES (1, 'PROPRIETARIO');
            CREATE TABLE inquilinos_clientes (
                id INTEGER PRIMARY KEY, nome_completo TEXT NOT NULL, rg TEXT, cpf TEXT,
                contato TEXT, profissao TEXT, estado_civil TEXT, email TEXT
            );
            INSERT INTO inquilinos_clientes (id, nome_completo) VALUES (1, 'CLIENTE');
            CREATE TABLE imoveis (
                id INTEGER PRIMARY KEY, apelido TEXT NOT NULL, responsavel INTEGER NOT NULL,
                cep TEXT, estado TEXT, cidade TEXT, bairro TEXT, numero TEXT,
                complemento TEXT, inscricao_mun TEXT, aluguel REAL NOT NULL DEFAULT 0,
                numero_energia TEXT, numero_agua TEXT, adm_propriedade INTEGER NOT NULL DEFAULT 0,
                unidade_geradora TEXT, percentual_energia REAL
            );
            INSERT INTO imoveis (id, apelido, responsavel, aluguel)
            VALUES (1, 'IMOVEL', 1, 1000);
            CREATE TABLE contratos (
                id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL, inquilino_id INTEGER NOT NULL,
                data_inicio TEXT NOT NULL, data_fim TEXT NOT NULL,
                valor_aluguel REAL NOT NULL, valor_caucao REAL
            );
            INSERT INTO contratos VALUES (1, 1, 1, '2026-01-01', '2027-01-01', 1500, 3000);
            """
        )
        connection.commit()
        connection.close()

        migrated = create_app({"TESTING": True, "DATABASE": str(database)})
        migrated_client = migrated.test_client()
        detail = migrated_client.get("/api/contratos/1").get_json()
        self.assertEqual(len(detail["periodos"]), 1)
        self.assertIsNone(detail["periodos"][0]["dia_pagamento"])
        self.assertEqual(detail["periodos"][0]["valor_caucao"], 3000.0)
        legacy_update = migrated_client.put(
            "/api/contratos/1",
            data=json.dumps(
                {
                    "imovel_id": 1,
                    "inquilino_id": 1,
                    "data_inicio": "2026-01-01",
                    "data_fim": "2027-01-01",
                    "valor_aluguel": "1500",
                    "valor_caucao": "3000",
                    "status": "ATIVO",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(legacy_update.status_code, 200)
        self.assertIsNone(legacy_update.get_json()["dia_pagamento"])

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

        for invalid_day in ("0", "32", "1.5", "abc", ""):
            invalid_payment_day = dict(valid, dia_pagamento=invalid_day)
            self.assertEqual(
                self.post_json("/api/contratos", invalid_payment_day).status_code,
                400,
            )

    def test_dashboard_contract_count_and_page_markup(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-module="contratos"', page)
        self.assertIn('data-module="relatorios"', page)
        self.assertIn('data-module="energia_solar"', page)
        self.assertIn('data-form-section="energia_solar"', page)
        self.assertIn('data-field="geracao_mensal_kwh"', page)
        self.assertIn('data-field="numero_instalacao"', page)
        self.assertIn('data-field="numero_unidade_geradora_consumidora"', page)
        self.assertIn('data-field="preco_venda_kwh"', page)
        self.assertIn('data-mask="sale-price"', page)
        self.assertIn("Preço de venda (R$/kWh)", page)
        self.assertIn('Est. de geração mensal (kWh/mês)', page)
        self.assertIn('class="form-field generation-field"', page)
        self.assertIn("Limpar CEP", page)
        self.assertIn('data-form-section="contratos"', page)
        self.assertIn('data-field="tipo_imovel"', page)
        self.assertIn('data-field="tipo_operacao"', page)
        self.assertIn('data-field="unidade_geradora_id"', page)
        self.assertIn('data-field="cliente_energia_solar_id"', page)
        self.assertIn("Cliente energia solar", page)
        self.assertIn('data-field="repasse_iptu"', page)
        self.assertIn('data-field="valor_iptu" data-mask="currency"', page)
        self.assertIn('data-field="repasse_taxa_condominio"', page)
        self.assertIn('data-field="valor_condominio" data-mask="currency"', page)
        self.assertIn('data-field="taxa_adm_imovel" data-mask="currency"', page)
        self.assertIn("Repasse tx. condomínio", page)
        self.assertLess(
            page.index('data-field="percentual_energia"'),
            page.index('data-field="repasse_iptu"'),
        )
        self.assertLess(
            page.index('data-field="repasse_iptu"'),
            page.index('data-field="valor_iptu"'),
        )
        self.assertLess(
            page.index('data-field="valor_iptu"'),
            page.index('data-field="repasse_taxa_condominio"'),
        )
        self.assertLess(
            page.index('data-field="imobiliaria"'),
            page.index('data-field="taxa_adm_imovel"'),
        )
        self.assertLess(
            page.index('data-field="taxa_adm_imovel"'),
            page.index('data-field="tipo_operacao"'),
        )
        report_markup = page.split('id="reports-panel"', 1)[1].split(
            'id="record-modal"', 1
        )[0]
        self.assertNotIn("Taxa adm. imóvel", report_markup)
        self.assertLess(
            page.index('data-field="unidade_geradora_id"'),
            page.index('data-field="cliente_energia_solar_id"'),
        )
        self.assertIn('<option value="">Nenhuma</option>', page)
        self.assertNotIn('data-field="unidade_geradora"', page)
        self.assertIn('value="ALUGUEL"', page)
        self.assertIn('value="ENERGIA SOLAR"', page)
        self.assertIn('value="ALUGUEL + ENERGIA SOLAR"', page)
        self.assertNotIn('data-field="energia_solar"', page)
        self.assertIn('id="count-imoveis-locacao"', page)
        self.assertIn('id="count-imoveis-cobranca-solar"', page)
        self.assertIn('id="count-imoveis-energia-solar"', page)
        self.assertIn('class="property-card-columns"', page)
        self.assertIn('class="property-operation"', page)
        self.assertIn(">Locação</h3>", page)
        self.assertIn(">Energia Solar</h3>", page)
        self.assertIn(">Total imóveis geridos</span>", page)
        self.assertIn(">Imóveis alugados/total</span>", page)
        self.assertIn(">Energia cobrada/total</span>", page)
        self.assertIn('id="rate-imoveis-ocupacao"', page)
        self.assertIn('id="rate-imoveis-cobranca-solar"', page)
        self.assertNotIn('id="count-imoveis"', page)
        self.assertIn('class="property-card-title">Imóveis</span>', page)
        self.assertNotIn('class="summary-card-amber"', page)
        self.assertNotIn('id="count-contratos"', page)
        self.assertIn("GALPÃO COMERCIAL", page)
        self.assertIn("CHÁCARA/SÍTIO", page)
        self.assertEqual(page.count('data-field="rg"'), 2)
        self.assertNotIn('data-field="rg" data-mask="rg"', page)
        self.assertIn('data-field="rg" inputmode="text" placeholder="Ex.: MG3942581"', page)
        self.assertIn('data-field="rg" inputmode="text" placeholder="Ex.: SSP4494416117"', page)
        self.assertIn('data-field="imovel_id"', page)
        self.assertIn('data-field="inquilino_id"', page)
        self.assertIn('data-field="status"', page)
        self.assertIn('data-field="dia_pagamento"', page)
        self.assertIn('data-period-field="dia_pagamento"', page)
        self.assertIn("<span>Cobrança energia solar</span>", page)
        self.assertNotIn("<span>Administração da propriedade</span>", page)
        self.assertIn('<option value="0">Não</option>', page)
        self.assertIn('<option value="1">Sim</option>', page)
        self.assertIn('value="ATIVO">Ativo</option>', page)
        self.assertIn('value="ENCERRADO">Encerrado</option>', page)
        self.assertIn('id="active-contracts-head"', page)
        self.assertIn('id="closed-contracts-head"', page)
        self.assertIn('id="reports-panel"', page)
        self.assertIn('id="report-total-gross"', page)
        self.assertIn('id="report-total-iptu"', page)
        self.assertIn('id="report-total-condominium"', page)
        self.assertIn('id="report-total-net"', page)
        self.assertIn('id="report-total-margin"', page)
        self.assertIn('id="reports-head"', page)
        self.assertIn('id="reports-body"', page)
        self.assertIn("Contratos Ativos", page)
        self.assertIn("Contratos Encerrados", page)
        self.assertIn('id="clear-cep-button"', page)
        self.assertIn(">Limpar CEP</button>", page)
        self.assertIn('id="owner-filter"', page)
        self.assertIn('id="solar-filter"', page)
        self.assertIn('id="module-title-count"', page)
        self.assertLess(page.index('id="owner-filter"'), page.index('id="solar-filter"'))
        self.assertIn('<option value="1">SIM</option>', page)
        self.assertIn('<option value="0">NÃO</option>', page)
        self.assertIn("Cobrança solar", page)
        self.assertNotIn("\ufffd", page)

        app_js = Path(__file__).resolve().parents[1] / "static" / "js" / "app.js"
        source = app_js.read_text(encoding="utf-8")
        self.assertIn("function prefillPeriodSecurityFields(period)", source)
        self.assertIn("prefillPeriodSecurityFields(previousPeriod);", source)
        self.assertIn('[data-period-field="valor_caucao"]', source)
        self.assertIn('[data-period-field="data_pagamento_caucao"]', source)
        self.assertIn("count-imoveis-cobranca-solar", source)
        self.assertIn("counts.imoveis_cobranca_solar", source)
        self.assertIn("counts.imoveis_alugados", source)
        self.assertIn("counts.taxa_ocupacao", source)
        self.assertIn("counts.taxa_cobranca_solar", source)
        self.assertNotIn('count-contratos', source)
        self.assertIn("solarFilterValue", source)
        self.assertIn("function uniqueRecordsById(records)", source)
        self.assertIn("state.records = uniqueRecordsById", source)
        self.assertIn("const seenIds = new Set()", source)
        self.assertIn("const recordId = String(record.id)", source)
        self.assertIn("if (seenIds.has(recordId))", source)
        self.assertIn("updateModuleTitle(config.title, state.records.length)", source)
        self.assertIn("adm_propriedade=${encodeURIComponent(state.solarFilterValue)}", source)
        self.assertIn("withPropertyFilters", source)
        self.assertIn('endpoint: "/api/relatorios"', source)
        self.assertIn("function renderReportsTable(config, sort)", source)
        self.assertIn('"DESOCUPADO_DESPESA"', source)
        self.assertIn('record.tipo_linha === "DESOCUPADO_DESPESA"', source)
        self.assertIn("IMÓVEIS DESOCUPADOS / DESPESAS", source)
        self.assertIn("report-vacant-section", source)
        self.assertIn("report-expense-cell", source)
        self.assertIn("function formatPercentage(value)", source)
        self.assertIn("/api/unidades-geracao", source)
        self.assertIn("syncEnergyPercentageRequirement", source)
        self.assertIn("unidade_geradora_id", source)
        self.assertIn("cliente_energia_solar_id", source)
        self.assertIn("/api/inquilinos-clientes", source)
        self.assertIn("populateSolarClientSelect", source)
        self.assertIn("generationUnitLabel", source)
        self.assertIn('key: "preco_venda_kwh"', source)
        self.assertIn('function formatSalePriceInput(value)', source)
        self.assertIn('function validSalePrice(value)', source)
        energy_config = source.split("energia_solar:", 1)[1].split("contratos:", 1)[0]
        self.assertIn('label: "Unidade de geração"', energy_config)
        self.assertNotIn('label: "Identificação municipal"', energy_config)
        self.assertNotIn('key: "numero_instalacao"', energy_config)
        self.assertNotIn(
            'key: "numero_unidade_geradora_consumidora"', energy_config
        )
        self.assertIn('newLabel: "Nova unidade de geração"', source)
        self.assertIn("validMonthlyGeneration", source)
        self.assertIn("data-cep-status", page)
        self.assertNotIn('id="cep-lookup-status"', page.split('data-form-section="energia_solar"', 1)[1])
        self.assertNotIn('key: "adm_propriedade", label: "Cobrança energia solar"', source)
        self.assertNotIn('sortCellClass(sort, "adm_propriedade")', source)
        self.assertNotIn("Administração da propriedade", source)
        self.assertIn('<option value="">TODOS</option>', page)
        proprietario_section = page.split('data-form-section="proprietarios"', 1)[1].split(
            'data-form-section="inquilinos"', 1
        )[0]
        inquilino_section = page.split('data-form-section="inquilinos"', 1)[1].split(
            'data-form-section="imoveis"', 1
        )[0]
        self.assertNotIn('data-field="nome_contato"', proprietario_section)
        self.assertIn('data-field="nome_contato"', inquilino_section)

    def test_global_owner_filter_applies_to_properties_contracts_and_dashboard(self):
        owner_one = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Um")
        ).get_json()
        owner_two = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Dois")
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Compartilhado")
        ).get_json()

        property_one = self.property_payload(owner_one["id"])
        property_one.update({"apelido": "Imóvel Um", "tipo_operacao": "ALUGUEL"})
        property_one = self.post_json("/api/imoveis", property_one).get_json()

        property_two = self.property_payload(owner_one["id"])
        property_two.update(
            {"apelido": "Imóvel Dois", "tipo_operacao": "ALUGUEL + ENERGIA SOLAR"}
        )
        property_two = self.post_json("/api/imoveis", property_two).get_json()

        property_three = self.property_payload(owner_two["id"])
        property_three.update(
            {"apelido": "Imóvel Três", "tipo_operacao": "ENERGIA SOLAR"}
        )
        property_three = self.post_json("/api/imoveis", property_three).get_json()

        contract_one = self.post_json(
            "/api/contratos", self.contract_payload(property_one["id"], tenant["id"])
        ).get_json()
        contract_two = self.post_json(
            "/api/contratos", self.contract_payload(property_three["id"], tenant["id"])
        ).get_json()

        all_properties = self.client.get("/api/imoveis").get_json()
        self.assertEqual({record["id"] for record in all_properties}, {
            property_one["id"], property_two["id"], property_three["id"]
        })
        owner_one_properties = self.client.get(
            f"/api/imoveis?proprietario_id={owner_one['id']}"
        ).get_json()
        owner_two_properties = self.client.get(
            f"/api/imoveis?proprietario_id={owner_two['id']}"
        ).get_json()
        self.assertEqual(
            {record["id"] for record in owner_one_properties},
            {property_one["id"], property_two["id"]},
        )
        self.assertEqual(
            {record["id"] for record in owner_two_properties}, {property_three["id"]}
        )
        self.assertEqual(
            {record["id"] for record in self.client.get("/api/imoveis?proprietario_id=").get_json()},
            {property_one["id"], property_two["id"], property_three["id"]},
        )

        all_contracts = self.client.get("/api/contratos").get_json()
        self.assertEqual({record["id"] for record in all_contracts}, {contract_one["id"], contract_two["id"]})
        owner_one_contracts = self.client.get(
            f"/api/contratos?proprietario_id={owner_one['id']}"
        ).get_json()
        owner_two_contracts = self.client.get(
            f"/api/contratos?proprietario_id={owner_two['id']}"
        ).get_json()
        self.assertEqual({record["id"] for record in owner_one_contracts}, {contract_one["id"]})
        self.assertEqual({record["id"] for record in owner_two_contracts}, {contract_two["id"]})

        all_counts = self.client.get("/api/dashboard").get_json()["counts"]
        owner_one_counts = self.client.get(
            f"/api/dashboard?proprietario_id={owner_one['id']}"
        ).get_json()["counts"]
        self.assertEqual(
            (all_counts["imoveis"], all_counts["imoveis_locacao"],
             all_counts["imoveis_energia_solar"], all_counts["imoveis_cobranca_solar"],
             all_counts["contratos"]),
            (3, 2, 2, 2, 2),
        )
        self.assertEqual(
            (owner_one_counts["imoveis"], owner_one_counts["imoveis_locacao"],
             owner_one_counts["imoveis_energia_solar"], owner_one_counts["imoveis_cobranca_solar"],
             owner_one_counts["contratos"]),
            (2, 2, 1, 1, 1),
        )
        self.assertEqual(owner_one_counts["proprietarios"], all_counts["proprietarios"])
        self.assertEqual(owner_one_counts["inquilinos_clientes"], all_counts["inquilinos_clientes"])

    def test_global_solar_filter_applies_to_properties_contracts_and_dashboard(self):
        owner_one = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Solar Um")
        ).get_json()
        owner_two = self.post_json(
            "/api/proprietarios", self.person_payload("Proprietário Solar Dois")
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente Solar")
        ).get_json()

        def create_property(owner_id, name, solar_charge):
            payload = self.property_payload(owner_id)
            payload.update(
                {
                    "apelido": name,
                    "adm_propriedade": str(solar_charge),
                    "tipo_operacao": "ENERGIA SOLAR" if solar_charge else "ALUGUEL",
                }
            )
            return self.post_json("/api/imoveis", payload).get_json()

        solar_property_one = create_property(owner_one["id"], "Imóvel Solar Um", 1)
        non_solar_property = create_property(owner_one["id"], "Imóvel Sem Solar", 0)
        solar_property_two = create_property(owner_two["id"], "Imóvel Solar Dois", 1)

        contracts = [
            self.post_json(
                "/api/contratos",
                self.contract_payload(property_data["id"], tenant["id"]),
            ).get_json()
            for property_data in (
                solar_property_one,
                non_solar_property,
                solar_property_two,
            )
        ]

        all_properties = self.client.get("/api/imoveis").get_json()
        self.assertEqual(len(all_properties), 3)
        solar_properties = self.client.get(
            "/api/imoveis", query_string={"adm_propriedade": "SIM"}
        ).get_json()
        non_solar_properties = self.client.get(
            "/api/imoveis", query_string={"adm_propriedade": "NÃO"}
        ).get_json()
        self.assertEqual(
            {record["id"] for record in solar_properties},
            {solar_property_one["id"], solar_property_two["id"]},
        )
        self.assertEqual(
            {record["id"] for record in non_solar_properties},
            {non_solar_property["id"]},
        )

        combined_properties = self.client.get(
            "/api/imoveis",
            query_string={
                "proprietario_id": owner_one["id"],
                "adm_propriedade": "1",
            },
        ).get_json()
        self.assertEqual(
            {record["id"] for record in combined_properties},
            {solar_property_one["id"]},
        )

        solar_contracts = self.client.get(
            "/api/contratos", query_string={"adm_propriedade": "1"}
        ).get_json()
        self.assertEqual(
            {record["id"] for record in solar_contracts},
            {contracts[0]["id"], contracts[2]["id"]},
        )
        combined_contracts = self.client.get(
            "/api/contratos",
            query_string={
                "proprietario_id": owner_one["id"],
                "adm_propriedade": "0",
            },
        ).get_json()
        self.assertEqual(
            {record["id"] for record in combined_contracts}, {contracts[1]["id"]}
        )

        all_counts = self.client.get("/api/dashboard").get_json()["counts"]
        solar_counts = self.client.get(
            "/api/dashboard", query_string={"adm_propriedade": "1"}
        ).get_json()["counts"]
        combined_counts = self.client.get(
            "/api/dashboard",
            query_string={
                "proprietario_id": owner_one["id"],
                "adm_propriedade": "0",
            },
        ).get_json()["counts"]
        self.assertEqual(
            (all_counts["imoveis"], all_counts["imoveis_cobranca_solar"], all_counts["contratos"]),
            (3, 2, 3),
        )
        self.assertEqual(
            (solar_counts["imoveis"], solar_counts["imoveis_cobranca_solar"], solar_counts["contratos"]),
            (2, 2, 2),
        )
        self.assertEqual(
            (
                combined_counts["imoveis"],
                combined_counts["imoveis_cobranca_solar"],
                combined_counts["contratos"],
            ),
            (1, 0, 1),
        )

        unfiltered = self.client.get(
            "/api/imoveis", query_string={"proprietario_id": "", "adm_propriedade": ""}
        ).get_json()
        self.assertEqual(
            {record["id"] for record in unfiltered},
            {record["id"] for record in all_properties},
        )

    def test_global_owner_filter_rejects_invalid_owner_ids(self):
        for endpoint in ("/api/imoveis", "/api/contratos", "/api/dashboard"):
            self.assertEqual(self.client.get(f"{endpoint}?proprietario_id=abc").status_code, 400)
            self.assertEqual(self.client.get(f"{endpoint}?proprietario_id=999").status_code, 400)
            self.assertEqual(self.client.get(f"{endpoint}?adm_propriedade=maybe").status_code, 400)
        self.assertEqual(
            self.client.get("/api/relatorios?proprietario_id=abc").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/relatorios?proprietario_id=999").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/unidades-geracao?proprietario_id=abc").status_code,
            400,
        )
        self.assertEqual(
            self.client.get("/api/unidades-geracao?proprietario_id=999").status_code,
            400,
        )

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

        missing_operation = self.property_payload(owner["id"])
        missing_operation.pop("tipo_operacao")
        self.assertEqual(self.post_json("/api/imoveis", missing_operation).status_code, 400)

        invalid_operation = self.property_payload(owner["id"])
        invalid_operation["tipo_operacao"] = "VENDA"
        self.assertEqual(self.post_json("/api/imoveis", invalid_operation).status_code, 400)

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

    def test_operation_types_are_persisted(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Tipos de Operação")
        ).get_json()
        expected_operations = [
            "ALUGUEL",
            "ENERGIA SOLAR",
            "ALUGUEL + ENERGIA SOLAR",
        ]

        for index, operation_type in enumerate(expected_operations, start=1):
            payload = self.property_payload(owner["id"])
            payload.update(
                {"tipo_operacao": operation_type, "apelido": f"Operação {index}"}
            )
            response = self.post_json("/api/imoveis", payload)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["tipo_operacao"], operation_type)

        records = self.client.get("/api/imoveis").get_json()
        self.assertEqual(
            {record["tipo_operacao"] for record in records},
            set(expected_operations),
        )
        self.assertTrue(all("energia_solar" not in record for record in records))

    def test_dashboard_counts_property_operations_with_overlap(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Contagem de Imóveis")
        ).get_json()
        operations = [
            "ALUGUEL",
            "ENERGIA SOLAR",
            "ALUGUEL + ENERGIA SOLAR",
            "ALUGUEL + ENERGIA SOLAR",
        ]

        for index, operation_type in enumerate(operations, start=1):
            payload = self.property_payload(owner["id"])
            payload.update(
                {
                    "tipo_operacao": operation_type,
                    "apelido": f"Contagem {index}",
                    "adm_propriedade": "1" if index in {1, 3} else "0",
                }
            )
            self.assertEqual(self.post_json("/api/imoveis", payload).status_code, 201)

        counts = self.client.get("/api/dashboard").get_json()["counts"]
        self.assertEqual(counts["imoveis"], 4)
        self.assertEqual(counts["imoveis_locacao"], 3)
        self.assertEqual(counts["imoveis_energia_solar"], 3)
        self.assertEqual(counts["imoveis_cobranca_solar"], 1)

    def test_dashboard_counts_active_rentals_and_scopes_solar_billing(self):
        owner = self.post_json(
            "/api/proprietarios", self.person_payload("Indicadores de Imóveis")
        ).get_json()
        tenant = self.post_json(
            "/api/inquilinos-clientes", self.person_payload("Cliente dos Indicadores")
        ).get_json()

        def create_property(name, operation, solar_charge):
            payload = self.property_payload(owner["id"])
            payload.update(
                {
                    "apelido": name,
                    "tipo_operacao": operation,
                    "adm_propriedade": str(solar_charge),
                }
            )
            return self.post_json("/api/imoveis", payload).get_json()

        rental_active = create_property("Locação ativa", "ALUGUEL", 0)
        rental_closed = create_property("Locação encerrada", "ALUGUEL", 0)
        solar_only = create_property("Solar sem cobrança", "ENERGIA SOLAR", 0)
        combined = create_property("Operação combinada", "ALUGUEL + ENERGIA SOLAR", 1)
        rental_with_solar_flag = create_property("Locação com flag solar", "ALUGUEL", 1)

        active_contract = self.contract_payload(rental_active["id"], tenant["id"])
        self.assertEqual(self.post_json("/api/contratos", active_contract).status_code, 201)
        closed_contract = dict(
            self.contract_payload(rental_closed["id"], tenant["id"]),
            status="ENCERRADO",
        )
        self.assertEqual(self.post_json("/api/contratos", closed_contract).status_code, 201)
        solar_contract = self.contract_payload(solar_only["id"], tenant["id"])
        self.assertEqual(self.post_json("/api/contratos", solar_contract).status_code, 201)
        combined_contract = self.contract_payload(combined["id"], tenant["id"])
        self.assertEqual(self.post_json("/api/contratos", combined_contract).status_code, 201)

        counts = self.client.get("/api/dashboard").get_json()["counts"]
        self.assertEqual(counts["imoveis"], 5)
        self.assertEqual(counts["imoveis_locacao"], 4)
        self.assertEqual(counts["imoveis_alugados"], 2)
        self.assertEqual(counts["taxa_ocupacao"], 50)
        self.assertEqual(counts["imoveis_energia_solar"], 2)
        self.assertEqual(counts["imoveis_cobranca_solar"], 1)
        self.assertEqual(counts["taxa_cobranca_solar"], 50)
        self.assertEqual(counts["contratos"], 4)

        charged_counts = self.client.get(
            "/api/dashboard", query_string={"adm_propriedade": "1"}
        ).get_json()["counts"]
        self.assertEqual(charged_counts["imoveis_locacao"], 2)
        self.assertEqual(charged_counts["imoveis_alugados"], 1)
        self.assertEqual(charged_counts["taxa_ocupacao"], 50)
        self.assertEqual(charged_counts["imoveis_energia_solar"], 1)
        self.assertEqual(charged_counts["imoveis_cobranca_solar"], 1)
        self.assertEqual(charged_counts["taxa_cobranca_solar"], 100)

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

    def test_existing_contracts_receive_active_status_during_migration(self):
        database = Path(self.temp_dir.name) / "legacy-contracts.db"
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
            INSERT INTO proprietario (nome_completo) VALUES ('PROPRIETARIO LEGADO');
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
            INSERT INTO inquilinos_clientes (nome_completo) VALUES ('CLIENTE LEGADO');
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
                unidade_geradora TEXT,
                percentual_energia REAL
            );
            INSERT INTO imoveis (apelido, responsavel, aluguel)
            VALUES ('IMOVEL LEGADO', 1, 1200);
            CREATE TABLE contratos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imovel_id INTEGER NOT NULL,
                inquilino_id INTEGER NOT NULL,
                data_inicio TEXT NOT NULL,
                data_fim TEXT NOT NULL,
                valor_aluguel REAL NOT NULL,
                valor_caucao REAL
            );
            INSERT INTO contratos
                (imovel_id, inquilino_id, data_inicio, data_fim, valor_aluguel, valor_caucao)
            VALUES (1, 1, '2026-01-01', '2027-01-01', 1500, 3000);
            """
        )
        connection.commit()
        connection.close()

        legacy_app = create_app({"TESTING": True, "DATABASE": str(database)})
        legacy_client = legacy_app.test_client()
        connection = sqlite3.connect(database)
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(contratos)").fetchall()
        ]
        persisted = connection.execute(
            "SELECT id, status FROM contratos"
        ).fetchall()
        connection.close()

        self.assertEqual(columns.count("status"), 1)
        self.assertEqual(persisted, [(1, "ATIVO")])
        self.assertEqual(legacy_client.get("/api/contratos").get_json()[0]["status"], "ATIVO")

        create_app({"TESTING": True, "DATABASE": str(database)})
        connection = sqlite3.connect(database)
        columns_after_retry = [
            row[1] for row in connection.execute("PRAGMA table_info(contratos)").fetchall()
        ]
        rows_after_retry = connection.execute(
            "SELECT id, status FROM contratos"
        ).fetchall()
        connection.close()
        self.assertEqual(columns_after_retry.count("status"), 1)
        self.assertEqual(rows_after_retry, [(1, "ATIVO")])

    def test_existing_database_migrates_solar_client_fk_without_data_loss(self):
        database = Path(self.temp_dir.name) / "legacy-solar-client.db"
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
            INSERT INTO proprietario (nome_completo) VALUES ('PROPRIETARIO LEGADO');
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
            INSERT INTO inquilinos_clientes (nome_completo) VALUES ('CLIENTE LEGADO');
            CREATE TABLE imoveis (
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
                adm_propriedade INTEGER NOT NULL DEFAULT 0,
                imobiliaria INTEGER NOT NULL DEFAULT 0,
                tipo_operacao TEXT,
                unidade_geradora_legada TEXT,
                percentual_energia REAL
            );
            INSERT INTO imoveis
                (apelido, tipo_imovel, responsavel, cidade, aluguel, unidade_geradora_legada)
            VALUES ('IMOVEL LEGADO', 'CASA', 1, 'CIDADE LEGADA', 1200, 'UG-LEGACY');
            """
        )
        connection.commit()
        connection.close()

        migrated_app = create_app({"TESTING": True, "DATABASE": str(database)})
        migrated_client = migrated_app.test_client()
        connection = sqlite3.connect(database)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(imoveis)").fetchall()
        }
        foreign_keys = connection.execute("PRAGMA foreign_key_list(imoveis)").fetchall()
        preserved = connection.execute(
            "SELECT apelido, unidade_geradora_legada, cliente_energia_solar_id "
            "FROM imoveis WHERE id = 1"
        ).fetchone()
        connection.close()

        self.assertIn("cliente_energia_solar_id", columns)
        self.assertTrue(
            any(row[2] == "inquilinos_clientes" and row[6] == "RESTRICT" for row in foreign_keys)
        )
        self.assertEqual(preserved, ("IMOVEL LEGADO", "UG-LEGACY", None))
        property_data = migrated_client.get("/api/imoveis/1").get_json()
        self.assertIsNone(property_data["cliente_energia_solar_id"])

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
            INSERT INTO imoveis (apelido, responsavel, cidade, aluguel, energia_solar)
            VALUES ('IMOVEL SOLAR LEGADO', 1, 'CIDADE LEGADA', 1300, 1);
            """
        )
        connection.commit()
        connection.close()

        legacy_app = create_app({"TESTING": True, "DATABASE": str(database)})
        legacy_client = legacy_app.test_client()
        connection = sqlite3.connect(database)
        column_names = {
            row[1] for row in connection.execute("PRAGMA table_info(imoveis)").fetchall()
        }
        client_column_names = {
            row[1]
            for row in connection.execute("PRAGMA table_info(inquilinos_clientes)").fetchall()
        }
        preserved = connection.execute(
            "SELECT apelido, cidade, aluguel, tipo_imovel, tipo_operacao, imobiliaria "
            "FROM imoveis WHERE id = 1"
        ).fetchone()
        financial_defaults = connection.execute(
            "SELECT repasse_iptu, valor_iptu, repasse_taxa_condominio, valor_condominio, taxa_adm_imovel "
            "FROM imoveis WHERE id = 1"
        ).fetchone()
        solar_preserved = connection.execute(
            "SELECT tipo_operacao FROM imoveis WHERE id = 2"
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
        self.assertIn("tipo_operacao", column_names)
        self.assertIn("imobiliaria", column_names)
        self.assertIn("repasse_iptu", column_names)
        self.assertIn("valor_iptu", column_names)
        self.assertIn("repasse_taxa_condominio", column_names)
        self.assertIn("valor_condominio", column_names)
        self.assertIn("taxa_adm_imovel", column_names)
        self.assertIn("nome_contato", client_column_names)
        self.assertIn("contratos", table_names)
        self.assertEqual(
            preserved,
            ("IMÓVEL LEGADO", "CIDADE LEGADA", 1200.0, None, "ALUGUEL", 0),
        )
        self.assertEqual(solar_preserved, ("ENERGIA SOLAR",))
        self.assertEqual(financial_defaults, (0, None, 0, None, None))

        records = legacy_client.get("/api/imoveis").get_json()
        self.assertEqual(
            {record["tipo_operacao"] for record in records},
            {"ALUGUEL", "ENERGIA SOLAR"},
        )
        self.assertTrue(all("energia_solar" not in record for record in records))

        create_app({"TESTING": True, "DATABASE": str(database)})
        migrated_again = sqlite3.connect(database)
        migrated_columns = [
            row[1] for row in migrated_again.execute("PRAGMA table_info(imoveis)").fetchall()
        ]
        migrated_values = migrated_again.execute(
            "SELECT id, tipo_operacao FROM imoveis ORDER BY id"
        ).fetchall()
        migrated_financial_columns = [
            row[1]
            for row in migrated_again.execute("PRAGMA table_info(imoveis)").fetchall()
        ]
        migrated_financial_values = migrated_again.execute(
            "SELECT repasse_iptu, valor_iptu, repasse_taxa_condominio, valor_condominio, taxa_adm_imovel "
            "FROM imoveis WHERE id = 1"
        ).fetchone()
        migrated_again.close()
        self.assertEqual(migrated_columns.count("tipo_operacao"), 1)
        self.assertEqual(
            migrated_values,
            [(1, "ALUGUEL"), (2, "ENERGIA SOLAR")],
        )
        for field in (
            "repasse_iptu",
            "valor_iptu",
            "repasse_taxa_condominio",
            "valor_condominio",
            "taxa_adm_imovel",
        ):
            self.assertEqual(migrated_financial_columns.count(field), 1)
        self.assertEqual(migrated_financial_values, (0, None, 0, None, None))
        self.assertEqual(client_preserved, ("CLIENTE LEGADO", None))

    def test_existing_database_migrates_generation_units_without_data_loss(self):
        database = Path(self.temp_dir.name) / "legacy-generation.db"
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
            VALUES ('IMÓVEL PRESERVADO', 1, 'CIDADE LEGADA', 1200);
            """
        )
        connection.commit()
        connection.close()

        migrated_app = create_app({"TESTING": True, "DATABASE": str(database)})
        migrated_client = migrated_app.test_client()
        connection = sqlite3.connect(database)
        generation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(unidades_geracao)").fetchall()
        }
        preserved_property = connection.execute(
            "SELECT apelido, cidade, aluguel FROM imoveis WHERE id = 1"
        ).fetchone()
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        connection.close()

        self.assertIn("unidades_geracao", table_names)
        self.assertTrue(
            {
                "responsavel",
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
                "geracao_mensal_kwh",
            }.issubset(generation_columns)
        )
        self.assertEqual(preserved_property, ("IMÓVEL PRESERVADO", "CIDADE LEGADA", 1200.0))

        created = migrated_client.post(
            "/api/unidades-geracao",
            data=json.dumps({"responsavel": 1, "geracao_mensal_kwh": 0}),
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["geracao_mensal_kwh"], 0)


    def test_existing_generation_table_receives_identification_columns(self):
        database = Path(self.temp_dir.name) / "legacy-generation-columns.db"
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
            INSERT INTO proprietario (nome_completo) VALUES ('OWNER LEGACY');
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
            CREATE TABLE unidades_geracao (
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
                geracao_mensal_kwh INTEGER
            );
            INSERT INTO unidades_geracao
                (responsavel, cep, endereco, estado, cidade, bairro, numero,
                 complemento, inscricao_mun, geracao_mensal_kwh)
            VALUES
                (1, '01001000', 'RUA LEGADA', 'SP', 'SAO PAULO', 'CENTRO',
                 '10', 'PORTAO', 'UG-LEGADA', 0);
            """
        )
        connection.commit()
        connection.close()

        migrated_app = create_app({"TESTING": True, "DATABASE": str(database)})
        migrated_client = migrated_app.test_client()
        connection = sqlite3.connect(database)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(unidades_geracao)").fetchall()
        }
        preserved = connection.execute(
            """
            SELECT responsavel, cep, endereco, inscricao_mun,
                   numero_instalacao, numero_unidade_geradora_consumidora,
                   geracao_mensal_kwh
            FROM unidades_geracao WHERE id = 1
            """
        ).fetchone()
        connection.close()

        self.assertTrue(
            {
                "numero_instalacao",
                "numero_unidade_geradora_consumidora",
                "preco_venda_kwh",
            }.issubset(columns)
        )
        self.assertEqual(
            preserved,
            (1, "01001000", "RUA LEGADA", "UG-LEGADA", None, None, 0),
        )
        response = migrated_client.get("/api/unidades-geracao/1")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["numero_instalacao"])
        self.assertIsNone(
            response.get_json()["numero_unidade_geradora_consumidora"]
        )
        self.assertIsNone(response.get_json()["preco_venda_kwh"])

        create_app({"TESTING": True, "DATABASE": str(database)})
        connection = sqlite3.connect(database)
        self.assertEqual(
            [row[1] for row in connection.execute("PRAGMA table_info(unidades_geracao)").fetchall()].count(
                "preco_venda_kwh"
            ),
            1,
        )
        connection.close()

    def test_legacy_generation_text_migrates_only_unique_matches(self):
        database = Path(self.temp_dir.name) / "legacy-generation-links.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE proprietario (
                id INTEGER PRIMARY KEY, nome_completo TEXT NOT NULL, rg TEXT, cpf TEXT,
                contato TEXT, profissao TEXT, estado_civil TEXT, email TEXT
            );
            INSERT INTO proprietario (id, nome_completo) VALUES (1, 'OWNER');
            CREATE TABLE inquilinos_clientes (
                id INTEGER PRIMARY KEY, nome_completo TEXT NOT NULL, rg TEXT, cpf TEXT,
                contato TEXT, profissao TEXT, estado_civil TEXT, email TEXT
            );
            CREATE TABLE imoveis (
                id INTEGER PRIMARY KEY, apelido TEXT NOT NULL, responsavel INTEGER NOT NULL,
                cep TEXT, endereco TEXT, estado TEXT, cidade TEXT, bairro TEXT, numero TEXT,
                complemento TEXT, inscricao_mun TEXT, aluguel REAL NOT NULL DEFAULT 0,
                numero_energia TEXT, numero_agua TEXT, adm_propriedade INTEGER NOT NULL DEFAULT 0,
                unidade_geradora TEXT,
                percentual_energia REAL
            );
            INSERT INTO imoveis (id, apelido, responsavel, aluguel, unidade_geradora)
            VALUES
                (1, 'MATCH', 1, 1000, 'UG-MATCH'),
                (2, 'UNKNOWN', 1, 1000, 'UG-UNKNOWN'),
                (3, 'AMBIGUOUS', 1, 1000, 'UG-DUP');
            CREATE TABLE unidades_geracao (
                id INTEGER PRIMARY KEY, responsavel INTEGER NOT NULL,
                cep TEXT, endereco TEXT, estado TEXT, cidade TEXT, bairro TEXT, numero TEXT,
                complemento TEXT, inscricao_mun TEXT, geracao_mensal_kwh INTEGER,
                numero_instalacao TEXT, numero_unidade_geradora_consumidora TEXT
            );
            INSERT INTO unidades_geracao
                (id, responsavel, inscricao_mun, numero_instalacao)
            VALUES (1, 1, 'UG-MATCH', 'INSTALL-1');
            INSERT INTO unidades_geracao
                (id, responsavel, inscricao_mun)
            VALUES (2, 1, 'UG-DUP'), (3, 1, 'UG-DUP');
            """
        )
        connection.commit()
        connection.close()

        migrated_app = create_app({"TESTING": True, "DATABASE": str(database)})
        migrated_client = migrated_app.test_client()
        records = {
            record["apelido"]: record
            for record in migrated_client.get("/api/imoveis").get_json()
        }
        self.assertEqual(records["MATCH"]["unidade_geradora_id"], 1)
        self.assertEqual(records["MATCH"]["unidade_geradora_legada"], "UG-MATCH")
        self.assertIsNone(records["UNKNOWN"]["unidade_geradora_id"])
        self.assertEqual(records["UNKNOWN"]["unidade_geradora_legada"], "UG-UNKNOWN")
        self.assertIsNone(records["AMBIGUOUS"]["unidade_geradora_id"])
        self.assertEqual(records["AMBIGUOUS"]["unidade_geradora_legada"], "UG-DUP")

        connection = sqlite3.connect(database)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(imoveis)")}
        foreign_tables = {
            row[2]
            for row in connection.execute("PRAGMA foreign_key_list(imovel_unidade_geradora)")
        }
        link_count = connection.execute(
            "SELECT COUNT(*) FROM imovel_unidade_geradora"
        ).fetchone()[0]
        connection.close()
        self.assertIn("unidade_geradora_legada", columns)
        self.assertNotIn("unidade_geradora", columns)
        self.assertEqual(foreign_tables, {"imoveis", "unidades_geracao"})
        self.assertEqual(link_count, 1)

        create_app({"TESTING": True, "DATABASE": str(database)})
        connection = sqlite3.connect(database)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM imovel_unidade_geradora").fetchone()[0],
            1,
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
