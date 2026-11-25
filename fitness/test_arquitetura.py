"""Testes de arquitetura (equivalente em Python ao ArchUnit).

Rodar:  python -m unittest discover -s fitness -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metricas  # noqa: E402


class TestRegrasDeArquitetura(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classes, cls.imports = metricas.analisar_codigo()
        cls.metricas = metricas.calcular(cls.classes)
        cls.regras = {nome[:2]: (ok, viol) for nome, ok, viol in
                      metricas.verificar_regras(cls.classes, cls.imports, cls.metricas)}

    def test_regra_1_dominio_nao_referencia_infraestrutura(self):
        ok, viol = self.regras["R1"]
        self.assertTrue(ok, viol)

    def test_regra_2_repositorios_e_adaptadores_implementam_interface_abstrata(self):
        ok, viol = self.regras["R4"]
        self.assertTrue(ok, viol)

    def test_application_nao_referencia_infraestrutura(self):
        self.assertTrue(*self.regras["R2"])

    def test_bibliotecas_de_fornecedor_isoladas(self):
        self.assertTrue(*self.regras["R3"])

    def test_todos_os_pacotes_na_sequencia_principal(self):
        for m in self.metricas:
            with self.subTest(pacote=m.pacote):
                self.assertLessEqual(m.d, metricas.LIMITE_D)

    def test_fitness_function_detecta_violacao(self):
        """Prova de que a regra funciona: uma classe concreta em Domain.Ports reprova."""
        classes = dict(self.classes)
        classes["ClasseConcretaIntrusa"] = metricas.Classe(
            "ClasseConcretaIntrusa", "Domain.Ports", abstrata=False, bases=[])
        novas = metricas.calcular(classes)
        regras = {n[:2]: ok for n, ok, _ in metricas.verificar_regras(
            classes, self.imports, novas)}
        ports = next(m for m in novas if m.pacote == "Domain.Ports")
        self.assertGreater(ports.d, 0)  # o pacote saiu da sequência principal
        self.assertFalse(regras["R5"])


if __name__ == "__main__":
    unittest.main()
