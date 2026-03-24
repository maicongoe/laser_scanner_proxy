# UDP Relay/Fan-out para Laser Scanners Industriais (Python 3.10+)

Relay UDP leve para Linux, pensado para AMR industrial: recebe pacotes de até 4 scanners e replica rapidamente para 1 ou mais destinos por scanner, com baixo overhead e baixo jitter.

## Objetivo do relay

Duplicar/replicar pacotes UDP de scanners sem parsing pesado e sem impacto perceptível no software de navegação.

Fluxo crítico:

1. receber pacote UDP
2. validar mínimo (porta/IP/tamanho)
3. reenviar payload sem modificar
4. atualizar contadores

## Quando usar essa abordagem

Use quando:

- o scanner envia UDP contínuo (ex.: 30 Hz);
- você precisa copiar dados para outro consumidor (CLP, logger, gateway, etc.);
- quer manter solução simples, previsível e fácil de manter.

Caso clássico (scanner com **um único destino**):

- scanner envia para IP/porta do relay;
- relay faz fan-out para navegação e CLP.

## Limitações

- UDP não garante entrega.
- Não há retransmissão/ACK.
- Não há parsing de protocolo no caminho crítico.
- Não há banco de dados.
- Não há interface gráfica.

## Estrutura do projeto

```text
.
├── README.md
├── requirements.txt
├── config
│   └── relay_config.example.json
├── scripts
│   └── udp_scanner_simulator.py
├── src
│   ├── config_loader.py
│   ├── logger_setup.py
│   ├── main.py
│   ├── models.py
│   ├── stats.py
│   ├── udp_relay.py
│   └── utils.py
└── systemd
    └── udp-relay.service
```

## Dependências

Somente biblioteca padrão do Python 3.10+.

`requirements.txt`:

```txt
# Projeto usando apenas biblioteca padrão do Python 3.10+.
# Nenhuma dependência externa é necessária.
```

## Configuração (`JSON`)

Arquivo contém:

- `general`: parâmetros globais;
- `scanners`: lista de 1 a 4 scanners.

Cada scanner usa:

- `name`
- `enabled`
- `source_ip` (opcional, recomendado)
- `local_port` (porta de recepção do relay)
- `destinations` (lista de destinos fan-out, cada destino tem `ip` e `port`)

Também há compatibilidade com formato legado:

- `destination_ip` + `destination_port` (um único destino)

### Regras de validação

- 1 a 4 scanners no arquivo.
- Pelo menos 1 scanner habilitado.
- Nome de scanner único.
- IPs e portas válidos.
- Scanners desabilitados são ignorados.
- Com `source_ip_filter_enabled=false`, não pode haver múltiplos scanners na mesma `local_port`.
- Com `source_ip_filter_enabled=true`, múltiplos scanners na mesma `local_port` exigem `source_ip` único por scanner.

## Exemplo completo para 1 scanner (scanner só envia para um IP/porta)

Cenário:

- scanner: `192.168.10.101`
- Linux AMR (relay + navegação): `192.168.10.10`
- navegação escuta em `21100`
- scanner envia para relay em `21110`
- CLP: `192.168.20.50:25000`

No scanner:

- destino único = `192.168.10.10:21110` (relay)

No relay:

- recebe em `21110`
- reenvia para `192.168.10.10:21100` (navegação) e `192.168.20.50:25000` (CLP)

```json
{
  "general": {
    "log_level": "INFO",
    "debug": false,
    "stats_interval_sec": 5.0,
    "recv_socket_buffer_bytes": 1048576,
    "send_socket_buffer_bytes": 262144,
    "max_expected_packet_size": 4096,
    "source_ip_filter_enabled": true,
    "cpu_affinity": [2],
    "nice": 5,
    "scanner_timeout_sec": 2.0,
    "max_packets_per_socket_event": 128
  },
  "scanners": [
    {
      "name": "scanner_frontal",
      "enabled": true,
      "source_ip": "192.168.10.101",
      "local_port": 21110,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21100 },
        { "ip": "192.168.20.50", "port": 25000 }
      ]
    }
  ]
}
```

## Exemplos adicionais

### Exemplo 2 scanners

```json
{
  "general": {
    "log_level": "INFO",
    "debug": false,
    "stats_interval_sec": 5.0,
    "recv_socket_buffer_bytes": 1048576,
    "send_socket_buffer_bytes": 262144,
    "max_expected_packet_size": 4096,
    "source_ip_filter_enabled": true,
    "cpu_affinity": null,
    "nice": 5,
    "scanner_timeout_sec": 2.0,
    "max_packets_per_socket_event": 128
  },
  "scanners": [
    {
      "name": "front_lidar",
      "enabled": true,
      "source_ip": "192.168.10.101",
      "local_port": 21110,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21100 },
        { "ip": "192.168.20.50", "port": 25000 }
      ]
    },
    {
      "name": "rear_lidar",
      "enabled": true,
      "source_ip": "192.168.10.102",
      "local_port": 21111,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21101 },
        { "ip": "192.168.20.50", "port": 25001 }
      ]
    }
  ]
}
```

### Exemplo 4 scanners (2 scanners na mesma porta local)

```json
{
  "general": {
    "log_level": "INFO",
    "debug": false,
    "stats_interval_sec": 5.0,
    "recv_socket_buffer_bytes": 1048576,
    "send_socket_buffer_bytes": 262144,
    "max_expected_packet_size": 4096,
    "source_ip_filter_enabled": true,
    "cpu_affinity": [2],
    "nice": 5,
    "scanner_timeout_sec": 2.0,
    "max_packets_per_socket_event": 128
  },
  "scanners": [
    {
      "name": "front_lidar",
      "enabled": true,
      "source_ip": "192.168.10.101",
      "local_port": 21110,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21100 },
        { "ip": "192.168.20.50", "port": 25000 }
      ]
    },
    {
      "name": "rear_lidar",
      "enabled": true,
      "source_ip": "192.168.10.102",
      "local_port": 21110,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21101 },
        { "ip": "192.168.20.50", "port": 25001 }
      ]
    },
    {
      "name": "left_lidar",
      "enabled": true,
      "source_ip": "192.168.10.103",
      "local_port": 21112,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21102 },
        { "ip": "192.168.20.50", "port": 25002 }
      ]
    },
    {
      "name": "right_lidar",
      "enabled": true,
      "source_ip": "192.168.10.104",
      "local_port": 21113,
      "destinations": [
        { "ip": "192.168.10.10", "port": 21103 },
        { "ip": "192.168.20.50", "port": 25003 }
      ]
    }
  ]
}
```

## Instalação e execução

### Execução manual

```bash
python3 src/main.py --config config/relay_config.example.json
```

Validação de configuração:

```bash
python3 src/main.py --config config/relay_config.example.json --validate-config
```

### Como validar que está funcionando

- scanner transmitindo para `local_port` do relay;
- `recebido` subindo no scanner correto;
- `reenviado` subindo (agora conta cada cópia enviada para cada destino);
- `status=OK` para scanner ativo;
- navegação e CLP recebendo dados.

## Saída periódica de estatísticas

Por scanner:

- `recebido`
- `reenviado`
- `descartado`
- `erros`
- `pps`
- `throughput`
- `sem_dados`
- `status` (`OK` / `TIMEOUT`)

Observação:

- com múltiplos destinos no mesmo scanner, `reenviado` representa cópias bem-sucedidas.

## Teste local com simulador

1. Inicie relay com um config local.
2. Rode:

```bash
python3 scripts/udp_scanner_simulator.py \
  --scanner scanner_1,127.0.0.1,21110 \
  --hz 30 \
  --packets-per-cycle 4 \
  --payload-size 512 \
  --duration-sec 10
```

3. Veja no log do relay o crescimento de `recebido/reenviado`.

## Systemd

Arquivo: `systemd/udp-relay.service`.

Instalação:

```bash
sudo cp systemd/udp-relay.service /etc/systemd/system/udp-relay.service
sudo systemctl daemon-reload
sudo systemctl enable udp-relay.service
sudo systemctl start udp-relay.service
sudo systemctl status udp-relay.service
journalctl -u udp-relay.service -f
```

Ajustar no service:

- `User` e `Group`
- `WorkingDirectory`
- `ExecStart`

## Decisões de arquitetura e performance

Por que `selectors` + UDP não bloqueante:

- um loop único, sem threads no caminho crítico;
- menor jitter por evitar contenção de thread/scheduler;
- previsível e simples de manter.

Otimizações que realmente importam:

- não logar por pacote em produção;
- `recvfrom_into` com buffer reutilizado;
- caminho crítico mínimo;
- tratamento de bursts por `max_packets_per_socket_event`;
- relógio monotônico para watchdog e pps;
- tratamento de exceção por scanner/porta sem derrubar processo.

O que é exagero para este caso:

- parsing pesado do payload no relay;
- banco/mensageria no caminho crítico;
- arquitetura complexa sem necessidade.

## Recomendações práticas de operação

- rodar separado do software de navegação (processo distinto);
- manter `debug=false` em produção;
- evitar processamento pesado no relay;
- monitorar `descartado`, `erros` e `TIMEOUT`;
- usar afinidade de CPU apenas quando medição justificar;
- não transformar o relay em parser complexo.

## `taskset`, `nice` e `chrt` (com cautela)

```bash
taskset -c 2 python3 src/main.py --config /etc/udp-relay/relay_config.json
nice -n 5 python3 src/main.py --config /etc/udp-relay/relay_config.json
sudo chrt -r 20 python3 src/main.py --config /etc/udp-relay/relay_config.json
```

Use `chrt` só após testes de carga; prioridade real-time mal aplicada pode afetar a navegação.

## Compatibilidade com containerização futura

- sem GUI;
- sem serviços externos;
- logs em stdout/stderr;
- configuração por argumento `--config`;
- estrutura simples para futuro Dockerfile.

Docker não foi implementado nesta etapa.

## Possíveis melhorias futuras

- exportar métricas para Prometheus;
- saída opcional para CSV;
- socket tuning adicional;
- modo de health check;
- suporte opcional a multicast;
- empacotamento `.deb`/`.rpm`.
