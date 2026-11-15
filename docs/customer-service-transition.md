# Integración incremental de Customer Service

CBS conserva cuentas y su `customer_id` titular, números de cuenta, saldos,
movimientos, transferencias, idempotencia financiera y autorización bancaria.
Customer Service conserva perfiles, Customer UUID, vínculo actor–Customer y
onboarding de identidad. Login sigue siendo propietario de sesiones y actores.
No hay acceso cruzado a bases de datos ni dependencia de paquetes de CBS desde
Customer Service.

## Puertos y composición

| Necesidad de CBS | Puerto | Implementación activa |
| --- | --- | --- |
| Identidad del actor autenticado | `CustomerIdentityResolver` | `CustomerServiceClient.resolve_customer_id` |
| Existencia de Customer al abrir cuentas administrativas | `CustomerDirectory` | `CustomerServiceClient.exists` |
| Solicitar onboarding de identidad | `CustomerOnboardingGateway` | `CustomerServiceClient.onboard` |
| Abrir una sola cuenta durante el registro | `AccountOpeningRepository` | SQLAlchemy local, `customer_account_openings` |
| Titularidad y acceso a cuentas | `AccountRepository`, `AccountAccessPolicy` | CBS local |

El cliente HTTP es compartido durante el ciclo de vida de la aplicación y se
cierra al finalizar. No transporta estado de usuario entre peticiones. Usa
timeouts explícitos, no sigue redirecciones ni proxies del entorno, limita las
respuestas a 64 KiB y comprueba actor, Customer UUID, estado y formato del resultado.
No se interpreta un fallo de red, 401/403 del servicio o JSON inválido como vínculo
ausente. Devuelve 503 sin fallback a tablas antiguas.

`get_customer_identity`, `get_customer_directory`, `get_customer_service_client`
y `get_registration_customer_client` son puntos de inyección para tests.
La aplicación no configura implementaciones locales como alternativa.

## Configuración

Añadir a `.env`/gestor de secretos (no versionar valores reales):

```dotenv
CUSTOMER_SERVICE_URL=https://customer-service.internal
CUSTOMER_SERVICE_ID=cbs-backend
CUSTOMER_SERVICE_CREDENTIAL=<token exclusivo de 64 hex>
CUSTOMER_SERVICE_REQUEST_TIMEOUT=3
CUSTOMER_SERVICE_ALLOW_INSECURE_HTTP=false
CUSTOMER_SERVICE_REGISTRATION_ID=cbs-registration-bridge
CUSTOMER_SERVICE_REGISTRATION_CREDENTIAL=<otro token exclusivo de 64 hex>
```

En desarrollo la URL será `http://127.0.0.1:8004`, con opt-in explícito a HTTP.
La URL y el token principal se configuran conjuntamente. El token del puente
solo se usa en la aplicación interna de CBS después de autenticar al coordinador
de registro con la credencial entrante existente. Las credenciales de entrada y
salida deben ser diferentes.

En Customer Service registrar:

| Servicio | Alcances |
| --- | --- |
| `cbs-backend` | `identity:read`, `customer:read`, `onboarding:write` |
| `cbs-registration-bridge` | `identity:read`, `onboarding:write`, `identity:attest` |

El backend público reenvía a Customer Service la sesión del actor ya verificado
por `auth-client-python`. Customer Service debe tener habilitado el mismo SDK y
`AUTH_APPLICATION_CODE=CBS` para resolver esas sesiones. El puente puede atestar
una identidad CUSTOMER desactivada recién creada por login, que aún no tiene
sesión. El backend normal no tiene atestación ni enlace administrativo.
Ver [configuración de Customer Service](../../customer-service/README.md).

## Comportamiento de los endpoints existentes

* `GET /me`: autentica en login, resuelve actor en Customer Service para CUSTOMER
  y conserva `LINKED`/`PENDING_LINK`. ADMIN conserva `NOT_APPLICABLE` y no consulta
  Customer Service. Ignora cualquier `customer_id` enviado como query.
* `/me/accounts`, saldos, movimientos y transacciones: el Customer viene de la
  resolución remota; CBS filtra por el titular local y conserva ocultación 404
  para cuentas ajenas. Un actor sin vínculo recibe 403.
* `/me/transfers`: resuelve una vez antes de iniciar la transacción bancaria;
  reutiliza un snapshot inmutable asociado al actor durante esa operación.
  Comprueba el origen contra cuentas locales, bloquea cuentas en orden estable y
  reutiliza el posting existente. No consulta al servicio por cada comprobación,
  ni al consultar la cuenta de destino. Un reintento de otra petición vuelve a
  resolver identidad antes de devolver incluso un recibo financiero existente.
* `POST /accounts`: sigue siendo exclusivo de ADMIN. Comprueba existencia del
  Customer antes de abrir una cuenta; 404 si no existe, 503 si no puede verificarlo.
  Consultar, bloquear y reactivar cuentas existentes no requiere Customer Service.
* `POST /me/onboarding`: conserva el perfil y respuesta Account de la API anterior.
  Envía el perfil transitoriamente a Customer Service, recibe su UUID confiable y
  abre la cuenta de forma idempotente en CBS. No escribe el perfil ni actor–Customer
  en CBS. No acepta `actor_id`/`customer_id` en el payload del navegador.
* `PUT/GET /internal/registrations/{actor_id}`: adaptador temporal para el
  coordinador actual de login. Conserva token de servicio, rechazo de navegador,
  actor verificado por el coordinador y respuesta `status: LINKED`. PUT utiliza el
  token separado del puente; GET verifica vínculo remoto y cuenta local abierta.
  Sigue sin exponerse en la API pública.
* CLI `link_customers`: `show` consulta HTTP; `link` y `remove` se rechazan y remiten
  a la operación administrativa auditada de Customer Service.

Los 401 de sesión y 403 de autorización bancaria conservan sus significados.
Un error de autenticación del **servicio saliente** produce 503 para el navegador:
no se confunde con una sesión inválida del usuario. No hay caché global ni fallback
permisivo durante una caída. El snapshot de identidad dura una sola operación;
Customer Service no permite reasignaciones implícitas. Si se incorporan en el
futuro cambios de identidad administrativos, necesitarán una política explícita
de revocación/concurrencia antes de ampliar la duración del snapshot.

## Flujo distribuido y recuperación

1. Login reserva un actor desactivado y su recibo de registro.
2. Customer Service reserva Customer UUID; verifica identidad o atestación.
   Crea perfil, vínculo y estado LINKED en su propia transacción.
3. CBS abre cuenta y saldo cero con un recibo `customer_account_openings`, en una
   sola transacción bancaria. El recibo contiene Customer, cuenta y moneda.
4. Login confirma el resultado mediante el GET de compatibilidad y activa al actor
   según su flujo actual.

Un fallo del paso 3 **no revierte** el paso 2. Repetir el mismo alta recupera el
mismo Customer y una sola cuenta. Un timeout con resultado incierto se trata como
503, se consulta y se reintenta con los datos originales. No hay compensación que
borre identidades, Customers o cuentas confirmadas. Si login no llega a activarse,
su operación de reconciliación sigue confirmando la cuenta a través del GET del
puente. El perfil solo transita por memoria de CBS; el fingerprint y el Customer
reservado pertenecen a Customer Service.

## Migración y retirada posterior

La revisión `0007_customer_account_openings` es aditiva. Conserva tablas e índices
anteriores y copia los recibos de cuentas ya abiertas desde los onboardings
antiguos. No modifica titulares ni perfiles. Ejecutar el procedimiento habitual
`make db-migrate` antes de habilitar las nuevas rutas en un despliegue.

Antes del cambio de tráfico, importar mediante un proceso operativo revisado los
perfiles de CRP y los vínculos existentes de CBS a Customer Service, conservando
exactamente los Customer UUID de las cuentas. No se ejecuta una importación
automática ni se lee otra base desde el runtime. La tabla antigua permitía varios
actores para un Customer: resolver esas duplicidades explícitamente antes de
aplicar el nuevo contrato uno a uno. No crear nuevos UUID para clientes migrados.
Verificar los recibos incompletos de CBS, los actores inactivos de login y los
Customers provisionados parcialmente en CRP antes del corte; no asumir rollback.
La migración de datos aún no se ha ejecutado.

Una vez confirmado el corte y la reconciliación, podrá retirarse:

* `infrastructure/crp_customer_directory.py` y `crp_customer_provisioner.py`;
  ya no se instancian desde las APIs de CBS.
* `LinkActorToCustomer` legado de `application/customer_identity.py`,
  `domain/customer_identity` y el antiguo CLI/verificador local.
* `ports/actor_customer_link_repository.py`, `ActorCustomerLinkORM` y su repositorio;
  las propiedades `links`/`onboardings` de la unidad de trabajo son solo legado.
* `CustomerOnboarding`, `CustomerOnboardingRepository`, `CustomerProvisioner`, su
  modelo/repositorio SQLAlchemy y las opciones `CRP_CUSTOMER_*` de Settings.
* Las tablas `banking.actor_customer_links` y `banking.customer_onboardings`,
  mediante otra migración explícita cuando los datos estén respaldados y reconciliados.
* El puente `/internal/registrations` y su token dedicado cuando login coordine
  directamente Customer Service y solicite apertura de cuenta mediante un contrato
  bancario independiente. Eliminar también el formulario/perfil de compatibilidad
  de CBS en ese momento; hoy se conserva para evitar romper el registro existente.

No retirar `CustomerIdentityResolver`, `CustomerDirectory`, titularidad local de
cuentas ni el recibo de apertura: representan necesidades reales de CBS.

## Pruebas

`make check` valida unidad, estilo y tipos. `TEST_DATABASE_URL` dedicada (sufijo
`_test`) habilita `make test-integration`. Cada test PostgreSQL utiliza su propia
base efímera. Los tests bancarios de lectura/transferencia inyectan resoluciones
remotas; el contrato HTTP usa `httpx.MockTransport`. Se comprueban aislamiento de
titulares, reintentos financieros, permisos ADMIN, indisponibilidad, respuestas
inválidas, recuperación después de commit remoto y ausencia de nuevas filas en
las tablas locales de identidad/onboarding.
