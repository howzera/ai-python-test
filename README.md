# Intelligent Notification Service

Servicio que recibe peticiones en lenguaje natural ("Manda un mail a feda@test.com diciendo hola"), extrae con un motor de IA los datos de la notificación (`to`, `message`, `type`), los valida con *guardrails* y la envía a un proveedor externo.

- Enunciado original: [docs/original-statement.md](docs/original-statement.md)

## Plan

1. Modelo de dominio, puertos y casos de uso (arquitectura hexagonal).
2. Parser tolerante de la respuesta de la IA y guardrails de negocio, con un test por cada variación del mock.
3. Adaptadores HTTP de IA y notificaciones: reintentos con backoff, rate limiter.
4. API FastAPI con procesamiento en segundo plano.
5. Docker, prueba de carga k6 y documentación final.
