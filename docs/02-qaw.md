# 2. Atributos de Qualidade e Matriz QAW

Os atributos de qualidade prioritários foram levantados com a técnica QAW (*Quality Attribute Workshop*) na Sprint 1 e revistos na entrega final, quando o desafio passou a incluir a redistribuição autônoma de carga.

## 2.1. Dimensionamento (BOTE)

Premissa: 1,9 milhão de medidores inteligentes, cada um enviando 1 KB de telemetria a cada 15 minutos.

| Grandeza | Cálculo | Resultado |
|---|---|---|
| Requisições por segundo | 1.900.000 ÷ 900 s | **≈ 2.111 req/s** |
| Vazão de rede | 2.111 × 1 KB | **≈ 2,11 MB/s** |
| Armazenamento bruto em 5 anos | 2,11 MB/s × 86.400 × 365 × 5 | **≈ 332 TB** |
| Mensagem em Protobuf (Sprint 3) | contrato `telemetria.proto` | 57 bytes (≈ 118 KB/s no Kafka) |

Esses números eliminam opções antes de qualquer discussão de tecnologia: 2.111 gravações contínuas por segundo descartam a gravação síncrona direta no banco ([ADR-001](adr/ADR-001.md)), e 332 TB de dado temporal descartam o banco relacional tradicional como destino final ([ADR-002](adr/ADR-002.md)).

## 2.2. Matriz QAW

| Atributo de Qualidade | Cenário Padronizado (Fonte → Estímulo → Artefato → Ambiente → Resposta) | Medida da Resposta (Métrica Objetivo) |
|---|---|---|
| **Disponibilidade** | Medidores IoT → envio massivo de telemetria após o fim de um blecaute → Serviço de Ingestão → pico de reconexão de toda a base → as leituras entram em fila assíncrona no Kafka, sem perda, e o *dashboard* continua no ar | *Uptime* de 99,99% (≈ 4 min de indisponibilidade por mês); zero leituras perdidas |
| **Segurança e Privacidade (LGPD)** | Fluxo de dados de consumo e tentativas de acesso indevido → dado identificável tentando chegar ao armazenamento central, ou intrusão → borda da Ingestão e Serviço de Auditoria → operação contínua → o identificador do medidor é pseudonimizado na borda e toda tentativa de intrusão gera registro imutável | Zero dados pessoais identificáveis fora da borda; 100% das tentativas de intrusão registradas em banco somente de inserção |
| **Desempenho / Latência** | Operador da distribuidora → pede a visualização da telemetria recente → API de Consulta (lado de leitura do CQRS) → gravação em alto volume acontecendo ao mesmo tempo → a consulta é atendida sem disputar recursos com o *pipeline* de escrita | Resposta em até 500 ms, com alerta automático de APM acima disso |
| **Autonomia / Resiliência da rede** *(entrega final)* | SCADA da distribuidora → falha de uma subestação deixa alimentadores desenergizados → Serviço de Autonomia (ciclo MAPE-K) → operação normal ou pós-blecaute → a carga é transferida para alimentadores vizinhos, desde que todos os guardrails físicos aprovem; senão, a decisão vai para o operador | Plano de redistribuição decidido em até 30 s após o evento; 0 manobras executadas que violem os limites térmicos (≤ 90%) ou de tensão (≥ 0,93 pu) |

## 2.3. Interseções do nexo arquitetural

- **Topologia de dados:** o volume de 332 TB de dado puramente temporal levou ao TimescaleDB (ADR-002). Ignorar essa característica degradaria as consultas a ponto de inviabilizar financeiramente o produto.
- **Compliance (LGPD):** a pseudonimização acontece na borda, antes de qualquer dado sair da Ingestão. Tratada só no banco, a plataforma transportaria dados de comportamento residencial sem base legal, o que impediria a venda para distribuidoras.
- **Segurança física (entrega final):** a autonomia só é aceitável porque as regras que protegem a rede elétrica são determinísticas e independentes da IA ([ADR-013](adr/ADR-013.md)).
