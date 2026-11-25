"""Infrastructure.Protocolos: fábricas (ADR 006) e adaptadores (ADR 007). A = 0.

É a Camada Anticorrupção (ACL) da Ingestão (ADR 010): todo formato de
fornecedor é traduzido aqui para ITelemetryReading em kWh e UTC.
"""
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from domain.ports.protocolos import DecoderFactory, ITelemetryDecoder
from domain.ports.telemetria import ITelemetryReading


@dataclass(frozen=True)
class LeituraDecodificada(ITelemetryReading):
    tenant_id: str
    device_id: str
    timestamp: datetime
    value: float


class MqttJsonDecoder(ITelemetryDecoder):
    """O JSON via MQTT já segue o contrato: decodificação direta."""

    def converter(self, payload: bytes) -> ITelemetryReading:
        d = json.loads(payload)
        return LeituraDecodificada(d["tenant_id"], d["device_id"],
                                   datetime.fromisoformat(d["timestamp"]), float(d["kwh"]))


class ScadaXmlAdapter(ITelemetryDecoder):
    """Adapter: XML do SCADA legado, em Wh e horário local -> kWh e UTC."""

    def __init__(self, fuso: str = "America/Sao_Paulo"):
        self._fuso = ZoneInfo(fuso)

    def converter(self, payload: bytes) -> ITelemetryReading:
        r = ET.fromstring(payload)
        local = datetime.fromisoformat(r.findtext("DataHora")).replace(tzinfo=self._fuso)
        return LeituraDecodificada(r.findtext("Cliente"), r.findtext("Medidor"),
                                   local.astimezone(timezone.utc),
                                   float(r.findtext("ValorWh")) / 1000)


class ModbusRegistroAdapter(ITelemetryDecoder):
    """Adapter: dois registradores de 16 bits com fator de escala -> kWh."""

    def __init__(self, tenant_id: str, fator_escala: float = 0.01):
        self._tenant, self._fator = tenant_id, fator_escala

    def converter(self, payload: bytes) -> ITelemetryReading:
        device_id = payload[:8].decode()
        alto, baixo = int.from_bytes(payload[8:10], "big"), int.from_bytes(payload[10:12], "big")
        return LeituraDecodificada(self._tenant, device_id, datetime.now(timezone.utc),
                                   ((alto << 16) | baixo) * self._fator)


class MqttJsonDecoderFactory(DecoderFactory):
    def criar_decoder(self) -> ITelemetryDecoder:
        return MqttJsonDecoder()


class ScadaXmlDecoderFactory(DecoderFactory):
    def criar_decoder(self) -> ITelemetryDecoder:
        return ScadaXmlAdapter()


class ModbusDecoderFactory(DecoderFactory):
    def __init__(self, tenant_id: str):
        self._tenant = tenant_id

    def criar_decoder(self) -> ITelemetryDecoder:
        return ModbusRegistroAdapter(self._tenant)
