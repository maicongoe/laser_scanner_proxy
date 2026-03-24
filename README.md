# UDP Relay/Fan-out para Laser Scanners Industriais (Python 3.10+)

Relay UDP leve para Linux/AMR: recebe pacotes de ate 4 scanners e replica o payload para um ou mais destinos por scanner.

## Objetivo

Manter o relay o mais simples possivel:

1. receber UDP
2. validar o minimo
3. reenviar sem alterar payload
4. atualizar estatisticas

## Estrutura

```text
.
├── .dockerignore
├── .gitignore
├── Dockerfile
├── README.md
├── docker-compose.yml
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

## Dependencias

Projeto usa apenas biblioteca padrao do Python.

## Configuracao JSON

Cada scanner pode usar `destinations` para fan-out (recomendado):

```json
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
```

Cenario tipico para scanner com destino unico:

- scanner envia para `IP_LINUX:21110` (relay)
- relay reenvia para navegacao `IP_LINUX:21100`
- relay reenvia para CLP `IP_CLP:25000`

## Execucao local sem Docker

Validar config:

```bash
python3 src/main.py --config config/relay_config.example.json --validate-config
```

Rodar relay:

```bash
python3 src/main.py --config config/relay_config.example.json
```

## Docker (Linux) - recomendado para isolamento

Para este caso UDP, prefira `--network host` no Linux para reduzir overhead/jitter de NAT e facilitar portas.

### 1. Build da imagem

```bash
docker build -t amr-udp-relay:1.0.0 .
```

### 2. Criar config ativa

```bash
cp config/relay_config.example.json config/relay_config.json
```

Edite `config/relay_config.json` com IPs/portas reais.

### 3. Validar config dentro do container

```bash
docker run --rm --network none \
  -v $(pwd)/config/relay_config.json:/config/relay_config.json:ro \
  amr-udp-relay:1.0.0 \
  --config /config/relay_config.json --validate-config
```

### 4. Rodar com docker run

```bash
docker run -d --name amr-udp-relay \
  --network host \
  --restart unless-stopped \
  -v /etc/amr-udp-relay/relay_config.json:/config/relay_config.json:ro \
  amr-udp-relay:1.0.0 \
  --config /config/relay_config.json
```

Logs:

```bash
docker logs -f amr-udp-relay
```

Parar/remover:

```bash
docker stop amr-udp-relay
docker rm amr-udp-relay
```

### 5. Rodar com Docker Compose

```bash
cp config/relay_config.example.json config/relay_config.json
docker compose up -d --build
docker compose logs -f udp-relay
```

Parar:

```bash
docker compose down
```

## Observacoes importantes de operacao

- Mantenha `debug=false` em producao.
- Evite logs por pacote.
- Nao adicione parsing pesado no relay.
- Monitore `descartado`, `erros` e `TIMEOUT`.
- Use afinidade de CPU apenas quando medicao justificar.
- Para `nice` negativo ou ajustes avancados no container, pode ser necessario `--cap-add SYS_NICE`.

## Estatisticas periodicas

Saida por scanner:

- recebido
- reenviado
- descartado
- erros
- pps
- throughput
- sem_dados
- status (OK/TIMEOUT)

## Teste com simulador

Com relay escutando em `21110`:

```bash
python3 scripts/udp_scanner_simulator.py \
  --scanner scanner_1,127.0.0.1,21110 \
  --hz 30 \
  --packets-per-cycle 4 \
  --payload-size 512 \
  --duration-sec 10
```

## Possiveis melhorias futuras

- metricas Prometheus
- exportacao CSV opcional
- health check HTTP/UDP opcional
- tuning adicional de socket
- suporte opcional a multicast
- pacote deb/rpm
