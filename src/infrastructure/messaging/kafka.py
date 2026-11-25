"""Infrastructure.Messaging: produtores Kafka (Amazon MSK, ADR 012). A = 0."""
import json

from confluent_kafka import Producer  # SDK do fornecedor: só aqui

from domain.ports.autonomia import IPublicadorDecisoes
from domain.ports.telemetria import ITelemetryPublisher, ITelemetryReading


class KafkaTelemetryPublisher(ITelemetryPublisher):
    """Publica em telemetria.anonimizada com o contrato telemetria.proto (ADR 009)."""

    def __init__(self, producer: Producer, serializador, topico="telemetria.anonimizada"):
        self._producer, self._serializar, self._topico = producer, serializador, topico

    def publish(self, reading: ITelemetryReading) -> None:
        self._producer.produce(self._topico, key=reading.device_id,
                               value=self._serializar(reading))


class KafkaPublicadorDecisoes(IPublicadorDecisoes):
    """Publica as decisões do MAPE-K em autonomia.decisoes (lido pela Auditoria)."""

    def __init__(self, producer: Producer, topico="autonomia.decisoes"):
        self._producer, self._topico = producer, topico

    def publicar(self, decisao: dict) -> None:
        self._producer.produce(self._topico, key=decisao["subestacao_id"],
                               value=json.dumps(decisao).encode())
        self._producer.flush()
