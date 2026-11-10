# Intelligent Notification Service

Servicio que recibe peticiones en lenguaje natural ("Manda un mail a feda@test.com diciendo hola"), extrae con un motor de IA los datos de la notificación (`to`, `message`, `type`), los valida con *guardrails* y la envía a un proveedor externo.

- Enunciado original: [docs/original-statement.md](docs/original-statement.md)

```
POST /v1/requests               {"user_input": "..."}   -> 201 {"id": "..."}
POST /v1/requests/{id}/process                          -> 202 {"id", "status": "processing"}  (200 si ya terminó, 404 si no existe)
GET  /v1/requests/{id}                                  -> 200 {"id", "status": "queued|processing|sent|failed"}
```

## Guía rápida: ejecución y pruebas

### Puertos en localhost

| Puerto | Servicio |
|---|---|
| **5000** | Este servicio (`app`, comparte red con `provider`) |
| **3001** | Mock de IA y notificaciones (`provider`) |
| **3000** | Grafana (scorecard de k6) |
| - | InfluxDB: solo red interna de Docker, no se publica |

> **Para evitar conflictos de puertos:** la [API de productos similares](https://github.com/howzera/backendDevTest) usa también 5000, 3001 y 3000. Con la configuración por defecto, no levantes los dos a la vez: ejecuta `docker-compose down` en uno antes de arrancar el otro. El [frontend](https://github.com/howzera/itx-frontend-test) usa el 5173 y no choca con ninguno.
>
> Para tener los dos a la vez, crea un fichero local `docker-compose.local.yml` que solo cambia los puertos publicados en el host (dentro de Docker siguen siendo 5000 y 3001, como pide el enunciado):
> ```yaml
> services:
>   provider:
>     ports: !override
>       - "3002:3001"
>       - "5001:5000"
>   grafana:
>     ports: !override
>       - "3003:3000"
> ```
> y añade `-f docker-compose.yaml -f docker-compose.local.yml` a cada comando `docker-compose`. Este servicio queda en http://localhost:5001 y su Grafana en http://localhost:3003.

### Paso a paso

1. **Iniciar Docker Desktop** y esperar a que esté en marcha.
2. **Clonar y entrar en la carpeta:**
   ```bash
   git clone https://github.com/howzera/ai-python-test.git
   cd ai-python-test
   ```
3. **Ejecutar los tests** (Python 3.12, sin Docker ni red):
   ```bash
   python -m venv .venv && .venv/Scripts/activate    # Linux/macOS: source .venv/bin/activate
   pip install -r requirements-dev.txt
   pytest -q                                          # esperado: 76 passed
   ```
4. **Levantar el mock, InfluxDB y Grafana.** InfluxDB es **obligatorio**: el mock escribe sus métricas en él de forma síncrona y, sin él, deja de responder.
   ```bash
   docker-compose up -d provider influxdb grafana
   ```
5. **Levantar el servicio (puerto 5000):**
   ```bash
   docker-compose up -d --build app
   ```
6. **Probar el flujo** desde Swagger (http://localhost:5000/docs) o con `curl`:
   ```bash
   curl -X POST http://localhost:5000/v1/requests -H "Content-Type: application/json" \
        -d '{"user_input": "Manda un mail a feda@test.com diciendo hola"}'
   curl -X POST http://localhost:5000/v1/requests/{id}/process
   curl http://localhost:5000/v1/requests/{id}
   ```

   | # | Acción | Resultado esperado | Qué demuestra |
   |---|---|---|---|
   | 1 | `POST /v1/requests` | **201** `{id}`; estado `queued` | Alta de la petición |
   | 2 | `POST /v1/requests/{id}/process` | **202** `processing` al instante | No espera a la IA (1,5–3 s) |
   | 3 | Repetir el paso 2 enseguida | **202** `processing` | Idempotente: no arranca otro pipeline |
   | 4 | `GET /v1/requests/{id}` tras ~5 s | **200** `sent` | IA → parser → guardrails → rate limiter → notify |
   | 5 | Repetir el paso 2 | **200** `sent` | No vuelve a llamar a la IA |
   | 6 | `GET /v1/requests/no-existe` | **404** | Id inexistente |
   | 7 | `POST` con `{"user_input": "   "}` | **422** | Validación de entrada |

7. **Probar distintos textos** (`user_input`), siguiendo los pasos 1, 2 y 4:

   | `user_input` | Estado final | Qué demuestra |
   |---|---|---|
   | `Avisar por SMS al 600-111-222 que la reserva ha sido confirmada.` | `sent` | SMS, teléfono normalizado |
   | `Dile a juan@test.com que la reunion es a las 5` | `sent` | Tipo deducido del destino |
   | `Manda un mensaje diciendo hola` | `failed` (`ai_refused`) | Sin destinatario: negativa, sin reintento |

   El motivo de cada resultado está en el log: `docker-compose logs app | grep -E "failed reason|sent channel"`.
8. **Prueba de carga k6:**
   ```bash
   docker-compose run --rm load-test
   ```
   Scorecard en Grafana: http://localhost:3000/d/ia-performance-scorecard/. Tras la prueba, la cola tarda unos minutos en vaciarse: el proveedor solo acepta 5 notificaciones por segundo.
9. **Parar todo:** `docker-compose down`

> En Windows PowerShell, usa `curl.exe` en lugar de `curl`, o Swagger.

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
