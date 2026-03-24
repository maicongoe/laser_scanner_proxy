# UDP Relay/Fan-out + Interpretacao nanoScan3 (Python 3.10+)

Projeto para Linux com foco em operacao industrial:

- relay UDP de 1 a 4 scanners
- fan-out para um ou mais destinos por scanner
- interpretacao dos telegramas UDP do SICK nanoScan3
- servidor web leve para visualizar os dados interpretados

## O que foi adicionado nesta versao

- parser UDP do nanoScan3 em `src/nanoscan_parser.py`
- store thread-safe de telemetria em `src/telemetry_store.py`
- servidor web HTTP (API + pagina) em `src/web_server.py`
- integracao no loop do relay para interpretar sem parar o encaminhamento UDP

Implementacao baseada na estrutura de parsing dos repositorios oficiais da SICK:

- https://github.com/SICKAG/sick_safetyscanners_base
- https://github.com/SICKAG/sick_safetyscanners2

## Estrutura

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
│   ├── nanoscan_parser.py
│   ├── stats.py
│   ├── telemetry_store.py
│   ├── udp_relay.py
│   ├── utils.py
│   └── web_server.py
└── systemd
    └── udp-relay.service
```

## Dependencias

- Python 3.10+
- NumPy (para parse vetorizado com menor CPU)

Instalacao:

```bash
python3 -m pip install -r requirements.txt
```

## Configuracao JSON

### Secao `general`

- `log_level`
- `debug`
- `stats_interval_sec`
- `recv_socket_buffer_bytes`
- `send_socket_buffer_bytes`
- `max_expected_packet_size`
- `source_ip_filter_enabled`
- `cpu_affinity`
- `nice`
- `scanner_timeout_sec`
- `max_packets_per_socket_event`

### Nova secao `web`

- `enabled`: habilita API/web
- `host`: ex. `0.0.0.0`
- `port`: ex. `8080`
- `max_sample_points`: limita pontos enviados na API (reduz CPU/rede)
- `parse_every_n_packets`: interpreta 1 a cada N pacotes (reduz CPU)
- `parse_mode`: `full` (mais detalhado) ou `minimal` (menos CPU)

### Secao `scanners`

Cada scanner:

- `name`
- `enabled`
- `source_ip` (opcional)
- `local_port`
- `destinations`: lista de `{ "ip", "port" }`

## Exemplo de config (1 scanner)

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
  "web": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8080,
    "max_sample_points": 360,
    "parse_every_n_packets": 1,
    "parse_mode": "full"
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

## Execucao

Validar config:

```bash
python3 src/main.py --config config/relay_config.example.json --validate-config
```

Rodar:

```bash
python3 src/main.py --config config/relay_config.example.json
```

## Servidor web

Com `web.enabled=true`, o processo sobe HTTP com:

- `GET /` -> pagina HTML de monitoramento
- `GET /health` -> health check
- `GET /api/scanners` -> estado de todos scanners
- `GET /api/scanners/<nome>` -> estado de um scanner

Exemplo:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/scanners
```

## O que a interpretacao mostra

Por scanner (quando telegrama completo do nanoScan3 e parse valido):

- `sequence_number`, `scan_number`, `channel_number`
- `number_of_beams`
- `start_angle_deg`, `angular_beam_resolution_deg`
- `scan_time_ms`, `interbeam_period_us`
- contadores de status (`valid`, `infinite`, `glare`, `reflector`, `contamination`)
- `min_range_m`, `max_range_m`
- amostragem de pontos (`sample_angles_deg`, `sample_ranges_m`, `sample_reflectivity`)

## Performance e robustez

- caminho de relay continua enxuto: receber -> reenviar -> contadores
- interpretacao roda no mesmo processo, mas isolada por tratamento de excecao
- erro de parse nao derruba relay
- servidor web roda em thread separada para nao bloquear o loop UDP
- logs continuam em stdout/stderr

Se o uso de CPU subir com web habilitada:

- mantenha NumPy instalado (sem ele cai para parser Python puro)
- aumente `web.parse_every_n_packets` (ex.: 2, 3, 5)
- reduza `web.max_sample_points` (ex.: 180, 90, 60)
- use `web.parse_mode = \"minimal\"` para monitoramento leve

## Teste com simulador (somente relay)

```bash
python3 scripts/udp_scanner_simulator.py \
  --scanner scanner_1,127.0.0.1,21110 \
  --hz 30 \
  --packets-per-cycle 4 \
  --payload-size 512 \
  --duration-sec 10
```

Observacao: o simulador nao gera telegrama real do nanoScan3, entao a parte de interpretacao pode nao preencher campos reais.

## systemd

Use `systemd/udp-relay.service` como base e ajuste:

- `User` / `Group`
- `WorkingDirectory`
- `ExecStart` com `--config`

## Possiveis melhorias futuras

- exportar metricas em Prometheus
- historico em CSV opcional
- endpoint de health detalhado
- tuning adicional de socket
- suporte multicast opcional
