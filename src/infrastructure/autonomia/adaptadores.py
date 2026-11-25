"""Infrastructure.Autonomia: adaptadores do ciclo MAPE-K (ADR 013). A = 0.

- KafkaFonteEstadoRede: monta o estado dos alimentadores a partir dos tópicos
  telemetria.anonimizada e rede.eventos (o serviço tem estado próprio, sem
  ler o TimescaleDB da Consulta: soberania de dados da ADR 005).
- ModeloPrevisaoOnnx: modelo leve de previsão de carga rodando LOCAL (tier 1).
- LlmExplicadorDecisao: LLM em nuvem (tier 2) só para explicar ao operador.
- TopologiaRedeRepository: base de conhecimento (K) com as chaves de interligação.
- AdmsAtuadorAdapter: ACL de saída para o ADMS/SCADA da distribuidora.
"""
import json
from dataclasses import dataclass

import boto3            # Amazon Bedrock (LLM) - só aqui
import jsonschema       # validação da saída estruturada do LLM
import onnxruntime      # inferência local do modelo de previsão
import requests         # chamada ao ADMS da distribuidora

from domain.ports.autonomia import (IAtuadorRede, IBaseConhecimento, IEstadoAlimentador,
                                    IExplicadorDecisao, IFonteEstadoRede,
                                    IModeloPrevisaoCarga, IPlanoRedistribuicao)


@dataclass(frozen=True)
class EstadoAlimentadorKafka(IEstadoAlimentador):
    alimentador_id: str
    subestacao_id: str
    energizado: bool
    carga_mw: float
    capacidade_mw: float
    tensao_pu: float
    prioritario: bool


class KafkaFonteEstadoRede(IFonteEstadoRede):
    def __init__(self, cache_estado: dict):
        self._cache = cache_estado  # atualizado pelo consumidor Kafka do serviço

    def estados(self, subestacao_id: str) -> list:
        return [EstadoAlimentadorKafka(**e) for e in self._cache.get(subestacao_id, [])]


class ModeloPrevisaoOnnx(IModeloPrevisaoCarga):
    def __init__(self, caminho_modelo: str):
        self._sessao = onnxruntime.InferenceSession(caminho_modelo)

    def prever_mw(self, estado: IEstadoAlimentador) -> float:
        entrada = [[estado.carga_mw, estado.capacidade_mw, estado.tensao_pu]]
        return float(self._sessao.run(None, {"x": entrada})[0][0])


class LlmExplicadorDecisao(IExplicadorDecisao):
    """Saída estruturada validada por JSON Schema; o LLM nunca decide nada."""

    SCHEMA = {"type": "object", "required": ["resumo", "riscos"],
              "properties": {"resumo": {"type": "string", "maxLength": 600},
                             "riscos": {"type": "array", "items": {"type": "string"}}},
              "additionalProperties": False}

    def __init__(self, modelo_id: str):
        self._bedrock = boto3.client("bedrock-runtime", region_name="sa-east-1")
        self._modelo = modelo_id

    def explicar(self, decisao: dict) -> str:
        # Só dados agregados por alimentador: nenhum device_id ou dado pessoal
        entrada = {k: decisao[k] for k in ("status", "violacoes", "manobras", "sem_destino")}
        resposta = self._bedrock.converse(modelId=self._modelo, messages=[{
            "role": "user", "content": [{"text": "Explique ao operador, em JSON "
                                         "{resumo, riscos}: " + json.dumps(entrada)}]}])
        saida = json.loads(resposta["output"]["message"]["content"][0]["text"])
        jsonschema.validate(saida, self.SCHEMA)
        return saida["resumo"]


class TopologiaRedeRepository(IBaseConhecimento):
    def __init__(self, topologia: dict):
        self._topologia = topologia  # {alimentador: [(vizinho, chave_id), ...]}

    def vizinhos(self, alimentador_id: str) -> list:
        return self._topologia.get(alimentador_id, [])


class AdmsAtuadorAdapter(IAtuadorRede):
    """ACL de saída: traduz o plano para o comando de manobra do ADMS."""

    def __init__(self, url_adms: str, token: str):
        self._url, self._token = url_adms, token

    def aplicar(self, plano: IPlanoRedistribuicao) -> None:
        comandos = [{"chave": m.chave_id, "acao": "FECHAR"} for m in plano.manobras]
        requests.post(self._url, json={"comandos": comandos}, timeout=2,
                      headers={"Authorization": f"Bearer {self._token}"}).raise_for_status()
