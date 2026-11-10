# Intelligent Notification Service

Servicio que recibe peticiones en lenguaje natural ("Manda un mail a feda@test.com diciendo hola"), extrae con un motor de IA los datos de la notificación (`to`, `message`, `type`), los valida con *guardrails* y la envía a un proveedor externo.

- Enunciado original: [docs/original-statement.md](docs/original-statement.md)

```
POST /v1/requests               {"user_input": "..."}   -> 201 {"id": "..."}
POST /v1/requests/{id}/process                          -> 202 {"id", "status": "processing"}  (200 si ya terminó, 404 si no existe)
GET  /v1/requests/{id}                                  -> 200 {"id", "status": "queued|processing|sent|failed"}
```

## Ejecución

Requisitos: Docker.

```bash
docker-compose up -d provider influxdb grafana   # mock de IA + notificaciones, métricas
docker-compose up -d --build app                 # este servicio, en el puerto 5000
docker-compose run --rm load-test                # prueba de carga k6
# Scorecard: http://localhost:3000/d/ia-performance-scorecard/
```

Sin Docker (Python 3.12), con el provider levantado:

```bash
python -m venv .venv && .venv/Scripts/activate    # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --port 5000
pytest                                            # 76 tests, < 1 s, sin red
```

Swagger: http://localhost:5000/docs

## Arquitectura hexagonal

```
app/
├── domain/                        # Núcleo: Python puro, sin FastAPI ni httpx
│   ├── models.py                  #   NotificationRequest (ciclo de vida), Notification, ExtractedIntent
│   ├── guardrails.py              #   Reglas de negocio: ¿es seguro enviar esto?
│   ├── exceptions.py              #   Errores esperados, cada uno con un código de motivo
│   └── ports.py                   #   RequestRepository, IntentExtractor, NotificationSender, JobScheduler
├── application/                   # Casos de uso: crear, procesar, consultar
├── infrastructure/
│   ├── http_api/                  # Adaptador de ENTRADA (FastAPI)
│   ├── ai/                        # Adaptador IA: prompt, cliente HTTP, parser tolerante
│   ├── notifications/             # Adaptador notificaciones: cliente HTTP + rate limiter
│   ├── persistence/               # Repositorio en memoria
│   ├── background/                # Tareas asyncio en segundo plano
│   └── http_retry.py              # Política de reintentos compartida
├── config.py                      # Configuración por variables de entorno
└── main.py                        # Composition root
```

### Pipeline

```mermaid
flowchart LR
    A[POST /process] -->|queued -> processing, 202| B(tarea en segundo plano)
    B --> C[IA /v1/ai/extract]
    C --> D[Parser: arregla el FORMATO]
    D --> E[Guardrails: validan el CONTENIDO]
    E --> F[Rate limiter 48/10 s]
    F --> G[/v1/notify]
    G --> H[sent]
    C & D & E & G -.error.-> I[failed + motivo]
```

## Decisiones técnicas

**`/process` responde 202 y procesa en segundo plano.** La IA tarda entre 1,5 y 3 s y el proveedor solo acepta 50 notificaciones cada 10 s. Si el endpoint esperara, cada petición tendría la conexión abierta segundos (o minutos, con cola) y el servicio no escalaría. El cliente consulta el estado con `GET`.

**Idempotencia.** Solo una petición en `queued` arranca el pipeline. Llamar a `/process` otra vez devuelve el estado actual (202 si sigue en curso, 200 si terminó) sin volver a llamar a la IA. Comprobar y cambiar el estado ocurre sin ningún `await` en medio, así que dos llamadas simultáneas no pueden arrancarlo dos veces. Con Redis sería un `SET NX` atómico.

**Dos capas de defensa ante la respuesta de la IA.**
1. *Parser* (infraestructura): arregla el **formato**. Corrige bloques Markdown, texto alrededor del JSON, comillas simples, claves sin comillas, JSON truncado y nombres de clave alternativos (`Recipient`, `body`, `channel`, `destination`...). Usa `json.loads` y, como alternativa, `ast.literal_eval`, que solo construye literales y nunca ejecuta código.
2. *Guardrails* (dominio): validan el **contenido**:
   - el destinatario **tiene que aparecer en el texto original** (protege de alucinaciones y de *prompt injection* que cambie el destino);
   - email o teléfono con formato válido y coherente con el `type`;
   - mensaje no vacío y con longitud máxima.

**Datos que faltan: copiar, nunca inventar.** Si falta `type`, se deduce del formato del destino. Si falta `to`, se toma del texto del usuario **solo si hay exactamente uno**; si hay cero o varios, la petición falla.

**Reintentos con criterio.**

| Situación | Acción |
|---|---|
| Red, timeout, 429, 5xx (IA o notify) | Reintento con backoff exponencial y *jitter* (tenacity) |
| Respuesta ilegible de la IA | Una llamada más |
| Rechazo de la IA ("Lo siento...", "Refused...") | `failed`, sin reintentar: se respeta la negativa |
| 4xx del proveedor (401, 422) | `failed`, sin reintentar: repetir daría el mismo error |
| Cualquier error inesperado | `failed` con motivo `internal_error`: nunca se queda en `processing` |

**Rate limiter propio (ventana deslizante, 48 cada 10 s).** El proveedor permite 50 cada 10 s. Esperar un hueco es más barato que recibir un 429 y reintentar. En la prueba de carga hubo **1 respuesta 429 en unos 2.500 envíos**, y el reintento la resolvió.

**Bulkhead hacia la IA.** Un semáforo limita a 100 las llamadas simultáneas a la IA, para no saturar un recurso lento y caro.

### Prompt

En [app/infrastructure/ai/prompts.py](app/infrastructure/ai/prompts.py):

- formato exacto: un solo objeto JSON, claves en minúscula, sin Markdown ni explicaciones;
- `null` en lugar de inventar un destinatario;
- el texto del usuario es **dato, no instrucciones** (defensa contra *prompt injection*);
- 4 ejemplos *few-shot*, incluidos "falta el destinatario" y un intento de inyección;
- `temperature: 0` para respuestas deterministas.

El texto del usuario va como último mensaje y sin envolver: el mock lee solo ese mensaje, y envolverlo en etiquetas XML colaría las etiquetas en el mensaje extraído. La defensa contra inyección no depende solo del prompt: el guardrail del destinatario la refuerza en código.

## Resultados de la prueba de carga (k6)

`docker-compose run --rm load-test`, hasta 200 usuarios virtuales, Docker Desktop en Windows 11:

| Métrica | Resultado |
|---|---|
| Checks correctos | **100 %** (19.215 de 19.215) |
| Peticiones HTTP fallidas | **0 %** (0 de 8.235) |
| Latencia media / p95 | **0,78 ms / 1,33 ms** |
| Throughput | 198 req/s |
| Llamadas a la IA por `/process` | **1,001** (2.788 llamadas para 2.785 peticiones) |
| Respuestas 429 del proveedor | **1** de unos 2.500 envíos, resuelta con reintento |

Resultado final, cuando la cola se vació: **2.500 `sent` y 285 `failed`**, ninguna petición atascada. Todas las variaciones de formato del mock se recuperan; los 285 fallos son negativas de la IA (≈ 10 % por diseño del mock).

**El cuello de botella es el proveedor de notificaciones** (5 por segundo). k6 crea unas 66 peticiones por segundo, así que la cola crece durante la prueba y se vacía después, a 4,8 envíos/s. La API sigue respondiendo en milisegundos porque no espera al envío.

## Tests

```bash
pytest   # 76 tests, < 1 s
```

| Fichero | Qué cubre |
|---|---|
| `tests/unit/test_response_parser.py` | **Un test por cada variación del mock** (13 formatos + 4 negativas) y textos sin JSON |
| `tests/unit/test_guardrails.py` | Destino que no está en el texto, tipo incoherente, deducción de campos, sinónimos, normalización |
| `tests/unit/test_process_request.py` | Ciclo de vida, idempotencia, 404, negativa, guardrail, fallo de envío, error inesperado |
| `tests/unit/test_rate_limiter.py` | Ventana deslizante con reloj falso (sin `sleep` real) |
| `tests/integration/test_provider_clients.py` | Adaptadores HTTP con `httpx.MockTransport`: reintentos 429/5xx, sin reintento en 4xx ni en negativas |
| `tests/integration/test_api.py` | Flujo completo, 404, validación de entrada (422) |

## Qué cambiaría en producción

- **Cola duradera** (Redis Streams, SQS, RabbitMQ) y workers separados: hoy, si el proceso se reinicia, se pierden las peticiones en curso.
- **Repositorio en Redis o base de datos**, con estado compartido entre réplicas y transición de estado atómica.
- **Rate limiter distribuido** (en Redis) cuando haya varias réplicas.
- **Caducidad de notificaciones**: un SMS de "cita a las 10:00" no sirve si sale a las 11:00.
- **Observabilidad**: métricas por motivo de fallo, latencia de la IA y tamaño de la cola; logs estructurados con el id de la petición.
- **Evaluación del prompt** con un conjunto de frases reales y métricas de precisión, y la API key en un gestor de secretos.

## Cómo encajaría en un sistema mayor

Junto con el [frontend de tienda](https://github.com/howzera/itx-frontend-test) y la [API de productos similares](https://github.com/howzera/backendDevTest): cuando el cliente añade un producto a la cesta, el backend publica un evento y este servicio envía la confirmación por email o SMS. Delante, un API Gateway (autenticación, CORS, rate limit). Entre servicios, una cola en lugar de llamadas directas.

Para ejecutarlo junto al backend en la misma máquina, hay que cambiar los puertos, porque ambos usan 5000 (servicio) y 3001 (mock). La URL del proveedor es configurable con `PROVIDER_BASE_URL`.
