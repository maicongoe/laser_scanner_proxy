# UDP Relay/Fan-out para Laser Scanners Industriais (Python 3.10+)

Relay UDP leve para Linux/AMR.
Recebe pacotes de ate 4 scanners e replica para um ou mais destinos por scanner, com foco em baixo jitter e manutencao simples.

## Objetivo

Manter o relay "burro" e previsivel:

1. receber UDP
2. validar rapidamente
3. reenviar payload sem alterar
4. atualizar contadores

## Estrutura do projeto

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

- Python 3.10+
- somente biblioteca padrao Python
- Docker (quando usar deploy em container)

## Formato de configuracao (`JSON`)

Cada scanner usa:

- `name`
- `enabled`
- `source_ip` (opcional, recomendado)
- `local_port` (porta em que o relay recebe)
- `destinations` (lista de destinos de fan-out)

Exemplo de scanner:

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

Topologia tipica (scanner com destino unico):

- scanner envia para `IP_LINUX:21110` (relay)
- relay reenvia para navegacao `IP_LINUX:21100`
- relay reenvia para CLP `IP_CLP:25000`

## Execucao sem Docker (manual)

Validar:

```bash
python3 src/main.py --config config/relay_config.example.json --validate-config
```

Rodar:

```bash
python3 src/main.py --config config/relay_config.example.json
```

## Docker - uso normal (Linux com internet)

Para UDP industrial, prefira `--network host` no Linux para reduzir overhead de NAT/jitter.

Build:

```bash
docker build -t amr-udp-relay:1.0.0 .
```

Config ativa:

```bash
cp config/relay_config.example.json config/relay_config.json
```

Validacao em container:

```bash
docker run --rm --network none \
  -v "$(pwd)/config/relay_config.json:/config/relay_config.json:ro" \
  amr-udp-relay:1.0.0 \
  --config /config/relay_config.json --validate-config
```

Run:

```bash
docker run -d --name amr-udp-relay \
  --network host \
  --restart unless-stopped \
  -v /etc/amr-udp-relay/relay_config.json:/config/relay_config.json:ro \
  amr-udp-relay:1.0.0 \
  --config /config/relay_config.json
```

## Docker offline (recomendado para ambiente sem internet)

Esta secao cobre o fluxo completo:

- maquina A (builder): Ubuntu 22 com internet (pode ser VM no VirtualBox)
- maquina B (alvo): Linux de producao sem internet

### 1) Maquina A - instalar Docker no Ubuntu 22

```bash
sudo apt update
sudo apt install -y docker.io git openssh-client ca-certificates
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
docker version
```

### 2) Maquina A - preparar codigo da branch Docker

```bash
git clone https://github.com/maicongoe/laser_scanner_proxy.git
cd laser_scanner_proxy
git checkout codex/docker
```

### 3) Maquina B - descobrir arquitetura

No Linux alvo:

```bash
uname -m
```

- `x86_64` -> use `linux/amd64`
- `aarch64` -> use `linux/arm64`

### 4) Maquina A - build da imagem para arquitetura alvo

Exemplo `x86_64`:

```bash
docker build --platform linux/amd64 -t amr-udp-relay:1.0.0 .
```

### 5) Maquina A - exportar imagem para arquivo

```bash
docker save amr-udp-relay:1.0.0 | gzip -1 > amr-udp-relay_1.0.0_linux-amd64.tar.gz
cp config/relay_config.example.json relay_config.json
```

### 6) Transferir arquivos para a maquina B

Via SSH/SCP:

```bash
scp amr-udp-relay_1.0.0_linux-amd64.tar.gz root@IP_DO_LINUX:/root/
scp relay_config.json root@IP_DO_LINUX:/root/
```

Se nao houver rede entre elas, use pendrive/pasta compartilhada.

### 7) Maquina B - carregar imagem e configurar

```bash
docker load -i /root/amr-udp-relay_1.0.0_linux-amd64.tar.gz
mkdir -p /etc/amr-udp-relay
mv /root/relay_config.json /etc/amr-udp-relay/relay_config.json
nano /etc/amr-udp-relay/relay_config.json
```

### 8) Maquina B - validar configuracao no container

```bash
docker run --rm --network none \
  -v /etc/amr-udp-relay/relay_config.json:/config/relay_config.json:ro \
  amr-udp-relay:1.0.0 \
  --config /config/relay_config.json --validate-config
```

### 9) Maquina B - iniciar o relay

```bash
docker run -d --name amr-udp-relay \
  --network host \
  --restart unless-stopped \
  -v /etc/amr-udp-relay/relay_config.json:/config/relay_config.json:ro \
  amr-udp-relay:1.0.0 \
  --config /config/relay_config.json
```

## Operacao diaria (Docker)

Status:

```bash
docker ps
docker logs --tail 100 amr-udp-relay
docker logs -f amr-udp-relay
```

Parar:

```bash
docker stop amr-udp-relay
```

Iniciar novamente:

```bash
docker start amr-udp-relay
```

Reiniciar:

```bash
docker restart amr-udp-relay
```

Desabilitar auto-start no boot:

```bash
docker update --restart=no amr-udp-relay
```

Habilitar auto-start no boot:

```bash
docker update --restart=unless-stopped amr-udp-relay
```

Checar politica de restart:

```bash
docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' amr-udp-relay
```

Checar Docker no boot:

```bash
systemctl is-enabled docker
systemctl is-active docker
```

## Atualizacao offline (nova versao)

1. Na maquina A: build + `docker save` da nova versao.
2. Copiar `.tar.gz` para maquina B.
3. Na maquina B:

```bash
docker load -i /root/amr-udp-relay_X.Y.Z_linux-amd64.tar.gz
docker stop amr-udp-relay
docker rm amr-udp-relay
docker run -d --name amr-udp-relay \
  --network host \
  --restart unless-stopped \
  -v /etc/amr-udp-relay/relay_config.json:/config/relay_config.json:ro \
  amr-udp-relay:X.Y.Z \
  --config /config/relay_config.json
```

## Remocao limpa

```bash
docker stop amr-udp-relay || true
docker rm amr-udp-relay || true
docker rmi amr-udp-relay:1.0.0 || true
rm -f /etc/amr-udp-relay/relay_config.json
```

## Docker Compose (opcional)

Subir:

```bash
cp config/relay_config.example.json config/relay_config.json
docker compose up -d --build
```

Logs:

```bash
docker compose logs -f udp-relay
```

Parar:

```bash
docker compose down
```

## Estatisticas e interpretacao

Resumo periodico por scanner:

- `recebido`
- `reenviado`
- `descartado`
- `erros`
- `pps`
- `throughput`
- `sem_dados`
- `status` (`OK` ou `TIMEOUT`)

## Recomendacoes operacionais

- manter `debug=false` em producao
- evitar logs por pacote
- evitar parsing pesado no relay
- monitorar `descartado`, `erros`, `TIMEOUT`
- usar afinidade de CPU apenas com medicao
- `--network host` no Linux para menor overhead UDP
- para `nice` negativo no container, pode ser necessario `--cap-add SYS_NICE`

## Teste local com simulador

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
- health check opcional
- tuning adicional de socket
- multicast opcional
- pacote deb/rpm
