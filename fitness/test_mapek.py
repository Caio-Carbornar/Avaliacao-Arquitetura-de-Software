"""Testes do ciclo MAPE-K e dos guardrails físicos, com dublês (sem Kafka, IA ou ADMS)."""
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from application.autonomia import (AnalisadorRede, CicloMapeK, ExecutorManobras,  # noqa: E402
                                   GuardrailCargaPrioritaria, GuardrailLimiteTermico,
                                   GuardrailTaxaManobras, GuardrailTensao, MonitorRede,
                                   PlanejadorRedistribuicao)
from domain.ports.autonomia import (IAtuadorRede, IBaseConhecimento,  # noqa: E402
                                    IEstadoAlimentador, IFonteEstadoRede,
                                    IModeloPrevisaoCarga, IPublicadorDecisoes)


@dataclass(frozen=True)
class Estado(IEstadoAlimentador):
    alimentador_id: str
    subestacao_id: str
    energizado: bool
    carga_mw: float
    capacidade_mw: float
    tensao_pu: float = 1.0
    prioritario: bool = False


class FonteFake(IFonteEstadoRede):
    def __init__(self, estados):
        self._estados = estados

    def estados(self, subestacao_id):
        return self._estados


class ModeloFake(IModeloPrevisaoCarga):
    """Prevê 10% a mais que a carga atual."""

    def prever_mw(self, estado):
        return estado.carga_mw * 1.1


class ModeloQuebrado(IModeloPrevisaoCarga):
    def prever_mw(self, estado):
        raise TimeoutError("modelo fora do ar")


class TopologiaFake(IBaseConhecimento):
    def __init__(self, vizinhos):
        self._v = vizinhos

    def vizinhos(self, alimentador_id):
        return self._v.get(alimentador_id, [])


class AtuadorFake(IAtuadorRede):
    def __init__(self):
        self.planos = []

    def aplicar(self, plano):
        self.planos.append(plano)


class PublicadorFake(IPublicadorDecisoes):
    def __init__(self):
        self.decisoes = []

    def publicar(self, decisao):
        self.decisoes.append(decisao)


def montar_ciclo(estados, vizinhos, modelo=None):
    atuador, publicador = AtuadorFake(), PublicadorFake()
    guardrails = [GuardrailLimiteTermico(), GuardrailTensao(),
                  GuardrailCargaPrioritaria(), GuardrailTaxaManobras()]
    ciclo = CicloMapeK(MonitorRede(FonteFake(estados)),
                       AnalisadorRede(modelo or ModeloFake()),
                       PlanejadorRedistribuicao(TopologiaFake(vizinhos)),
                       ExecutorManobras(atuador, guardrails), publicador)
    return ciclo, atuador, publicador


class TestCicloMapeK(unittest.TestCase):
    def test_falha_de_subestacao_redistribui_carga_automaticamente(self):
        estados = [Estado("AL-1", "SE-NORTE", False, 4.0, 10.0),
                   Estado("AL-2", "SE-SUL", True, 3.0, 10.0),
                   Estado("AL-3", "SE-LESTE", True, 6.0, 10.0)]
        ciclo, atuador, publicador = montar_ciclo(
            estados, {"AL-1": [("AL-2", "CH-12"), ("AL-3", "CH-13")]})
        decisao = ciclo.executar_ciclo("SE-NORTE")
        self.assertEqual(decisao["status"], "EXECUTADO")
        self.assertEqual(decisao["manobras"][0]["destino"], "AL-2")  # vizinho com mais folga
        self.assertEqual(len(atuador.planos), 1)
        self.assertEqual(len(publicador.decisoes), 1)  # auditada

    def test_guardrail_termico_bloqueia_e_escala_para_operador(self):
        estados = [Estado("AL-1", "SE-NORTE", False, 6.0, 10.0),
                   Estado("AL-2", "SE-SUL", True, 5.0, 10.0)]  # 5,5 + 6,6 > 9 MW
        ciclo, atuador, _ = montar_ciclo(estados, {"AL-1": [("AL-2", "CH-12")]})
        decisao = ciclo.executar_ciclo("SE-NORTE")
        self.assertEqual(decisao["status"], "PENDENTE_APROVACAO")
        self.assertTrue(any("AL-2" in v for v in decisao["violacoes"]))
        self.assertEqual(atuador.planos, [])  # nenhum comando enviado à rede

    def test_guardrail_de_tensao(self):
        estados = [Estado("AL-1", "SE-NORTE", False, 2.0, 10.0),
                   Estado("AL-2", "SE-SUL", True, 2.0, 10.0, tensao_pu=0.94)]
        ciclo, atuador, _ = montar_ciclo(estados, {"AL-1": [("AL-2", "CH-12")]})
        self.assertEqual(ciclo.executar_ciclo("SE-NORTE")["status"], "PENDENTE_APROVACAO")
        self.assertEqual(atuador.planos, [])

    def test_carga_prioritaria_sem_destino_exige_humano(self):
        estados = [Estado("AL-H", "SE-NORTE", False, 1.0, 5.0, prioritario=True)]
        ciclo, atuador, _ = montar_ciclo(estados, {})
        decisao = ciclo.executar_ciclo("SE-NORTE")
        self.assertEqual(decisao["status"], "PENDENTE_APROVACAO")
        self.assertIn("AL-H", decisao["sem_destino"])

    def test_carga_prioritaria_e_atendida_primeiro(self):
        estados = [Estado("AL-1", "SE-NORTE", False, 3.0, 10.0),
                   Estado("AL-H", "SE-NORTE", False, 3.0, 10.0, prioritario=True),
                   Estado("AL-2", "SE-SUL", True, 2.0, 10.0)]
        ciclo, _, _ = montar_ciclo(estados, {"AL-1": [("AL-2", "CH-1")],
                                             "AL-H": [("AL-2", "CH-2")]})
        decisao = ciclo.executar_ciclo("SE-NORTE")
        self.assertEqual(decisao["manobras"][0]["origem"], "AL-H")

    def test_falha_do_modelo_de_ia_usa_fallback(self):
        estados = [Estado("AL-1", "SE-NORTE", False, 2.0, 10.0),
                   Estado("AL-2", "SE-SUL", True, 2.0, 10.0)]
        ciclo, _, _ = montar_ciclo(estados, {"AL-1": [("AL-2", "CH-12")]},
                                   modelo=ModeloQuebrado())
        decisao = ciclo.executar_ciclo("SE-NORTE")
        self.assertEqual(decisao["status"], "EXECUTADO")
        self.assertEqual(decisao["manobras"][0]["carga_mw"], 2.0)  # última medição

    def test_rede_normal_nao_gera_acao(self):
        estados = [Estado("AL-1", "SE-NORTE", True, 2.0, 10.0)]
        ciclo, atuador, _ = montar_ciclo(estados, {})
        self.assertEqual(ciclo.executar_ciclo("SE-NORTE")["status"], "SEM_ACAO")
        self.assertEqual(atuador.planos, [])


if __name__ == "__main__":
    unittest.main()
