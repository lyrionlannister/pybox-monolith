# Auditoría API — hallazgos pendientes de resolver

Auditoría de `api/src/` (730 archivos, ~24k líneas) hecha por 7 agentes en paralelo,
uno por dominio, aplicando `antipatterns-architecture`, `tenant-isolation`,
`db-schema-design` y `code-distribution`. Fecha: 2026-10-30.

Nota: se descartaron 6 falsos positivos de "SyntaxError" (`except A, B:` sin
paréntesis) reportados por 3 agentes — es sintaxis válida en Python 3.14 (PEP 758),
y el proyecto exige `python >=3.14`. Verificado compilando los archivos afectados.

## Alto

- [x] **IDOR en registro de organización** — `api/src/identity/organizations/services/organization_service.py:355-361`.
      Cualquier admin puede registrar una org pasando `representative_user_id` de un
      tercero arbitrario (`representative_mode=select`), sin su consentimiento, y se
      crea membresía `is_legal_representative=True` para esa persona.
- [x] **Gestión de permisos no bloquea usuario GLOBAL** — `api/src/identity/organizations/controllers/org_members_controller.py`
      + `api/src/identity/users/services/user_management_service.py:163-170` (`_require_member`).
      Falta el chequeo que sí tiene `UserService.assert_can_manage_user` (bloquear
      gestión sobre usuarios con asignación GLOBAL).
- [x] **Centavos truncados en cobro real** — `api/src/receivables/payment_gateways/gateways/bold/bold_gateway.py:97`,
      `epayco/epayco_gateway.py:170,243`, `payu/payu_gateway.py:333` (`amount_in_cents // 100`).
      Se pierde el resto de centavos al cobrar, y además rompe la reconciliación en
      `attempt_status_sync.py:38-49` (el monto esperado sin truncar no matchea el real).
- [x] **Doble cobro real posible** — `api/src/receivables/payment_gateways/services/payment_checkout_service.py:100-133`
      y `automatic_charge_service.py:122-147`. No verifican si ya existe un intento
      PENDING/APPROVED antes de llamar `gateway.create_transaction` (cargo real).
- [x] **Audio IVR sin scope de organización** — `api/src/messaging/ivr/controllers/audio_controller.py:18-56`.
      Pool de audios compartido entre tenants (`HelenaClient` sin `organization_id`);
      `upload_audio` solo exige `require_org_or_global`, puede sobrescribir audio de
      otra organización. `delete_audio` sí exige `require_global_admin`, subir no.
- [x] **Reasignación de chat WhatsApp sin validar organización** — `api/src/messaging/whatsapp/services/whatsapp_chat_service.py:206-218` (`assign`).
      No valida que `assigned_user_id` pertenezca a la organización del hilo antes de
      escribir; expone mensajes/datos de deudor a usuario de otro tenant.
- [x] **Queries en loop en bulk-send** — `api/src/messaging/bulk_send/services/bulk_send_service.py:329-335`.
      Hasta 10 000 round-trips secuenciales por request para casos WhatsApp nuevos;
      ya resuelto en `campaigns/services/automation_service.py` con `ensure_cases_bulk`
      (prefetch + creación masiva), no reusado aquí.
- [x] **Bulk upsert CSV de portafolio apagado por defecto** — `api/src/receivables/portfolios/constants/portfolio_csv_constants.py:10`
      (`DEFAULT_PORTFOLIO_CSV_BULK_UPSERT = "false"`). Sin togglear la env var, toda
      carga de CSV corre por `_process_rows_sequential` (N+1 por fila) en
      `portfolio_csv_service.py:284-307`, pese a que el camino bulk ya existe.
- [x] **Subida de documento sin límite antes de bufferizar (DoS memoria)** — `api/src/app_platform/documents/services/document_service.py:71-85` (`store`).
      Lee el archivo completo (`file.read()`) antes de comparar contra
      `MAX_DOCUMENT_SIZE_BYTES`; la utilidad `documents/utils/upload_limits.py::read_within_limit`
      existe para evitar esto pero `store()` no la usa.

## Medio

- [x] **Firma de webhook fail-open si secreto vacío (Bold)** — `api/src/receivables/payment_gateways/gateways/bold/bold_signature.py:16-21`.
      Acepta `secret_key` vacío sin distinguir sandbox/producción; si una org de
      producción queda con credencial incompleta, la firma es falsificable (HMAC con
      llave conocida = "").
- [x] **Firma de webhook fail-open si secreto vacío (ePayco)** — `api/src/receivables/payment_gateways/gateways/epayco/epayco_gateway.py:90-91,375-381`.
      Mismo patrón: `p_key` vacío no se rechaza antes de calcular el hash.
- [x] **OTP sin límite de intentos propio** — `api/src/identity/auth/repository/verification_code_repository.py:35-54`
      + `auth/services/verification_service.py:88-122`. Solo protegido por rate-limit
      de IP compartido entre los 4 pasos de forgot-password; sin lockout por
      `user_id` ni invalidación tras N intentos fallidos.
- [x] **Fuga de memoria lenta en caché de contexto IVR** — `api/src/messaging/ivr/services/ivr_event_service.py:99`
      (`_bulk_context_cache`). Dict a nivel de módulo sin TTL ni límite de tamaño,
      crece indefinidamente con cada `bulk_id` nuevo.
- [x] **Dinero como float en respuesta de chat WhatsApp** — `api/src/messaging/whatsapp/services/whatsapp_chat_service.py:327-331`.
      Convierte `total_credit_balance`/`overdue_principal_balance` (Decimal) a float.
- [x] **Dinero como float en dashboard** — `api/src/app_platform/dashboard/schemas/dashboard_schemas.py:21-25`
      (`OrganizationStatsResponse.total_overdue_amount`). El valor viene de un `SUM`
      sobre `Numeric`/`Decimal` y se tipa `float` en el schema de respuesta.
- [x] **Mensajes de chat WhatsApp sin paginar** — `api/src/messaging/whatsapp/repository/whatsapp_message_repository.py:41-50` (`list_by_chat`).
      Trae todos los mensajes del hilo en una query; hilos largos acumulan miles.
- [x] **Falta índice `(organization_id, sent_at)`** — `api/src/messaging/contacts/models/contact_model.py:51`.
      Usado en filtros de rango de fecha para facturación y en `ORDER BY`, sin índice
      compuesto, sobre tabla de crecimiento no acotado.
- [x] **Logo de branding sin límite de tamaño ni verificación de magic bytes** — `api/src/app_platform/branding/controllers/platform_branding_controller.py:57`
      + `branding/services/platform_branding_service.py:40-61` (`replace_logo`).
      Usa `store_generated()` (pensado para artefactos internos) para una subida de
      usuario real.
- [x] **Código duplicado: `read_within_limit`** — `api/src/app_platform/support/services/support_service.py:910-929`
      (`_read_within_limit`) reimplementa casi textual la utilidad compartida en
      `documents/utils/upload_limits.py` en vez de importarla.
- [x] **Queries en loop al crear grupo de chat** — `api/src/app_platform/chats/services/chat_service.py:392-395`
      (`create_group_chat`). `add_member` por miembro (flush+refresh individual) en
      vez de `add_all` + flush único.
- [x] **Enums sin constraint de BD en chats** — `api/src/app_platform/chats/models/chat_model.py:16` (`type`)
      y `chat_member_model.py:33` (`role`). `IntEnum` en Python pero columna
      `SmallInteger` plana, sin ENUM nativo ni CHECK.
- [x] **Enum libre sin justificar en notificaciones** — `api/src/app_platform/notifications/models/notification_model.py:25-28`
      (`category`, `notif_type`). Conjunto cerrado de valores modelado como `String`
      libre, sin constraint ni comentario de excepción (a diferencia de
      `support.system_topic`, que sí lo documenta).
- [x] **`segment_execution_model.file_path` sin FK** — `api/src/receivables/segments/models/segment_execution_model.py:27-29`.
      Guarda el id del documento exportado como texto libre; el equivalente
      `report_execution_model.py:36-43` ya resolvió esto con `document_id` FK.
- [x] **Repos de `segments` sin cascada de soft-delete por organización** — `api/src/receivables/segments/repository/segment_repository.py`
      y `segment_execution_repository.py`. A diferencia del resto del dominio
      `receivables`, no cascadean al borrar (soft-delete) una organización.
- [x] **Doble chequeo de permiso redundante** — `api/src/messaging/campaigns/services/campaign_service.py:370-371,436-445`.
      `update()`/`activate()` llaman `_check_portfolio_access` explícito y luego
      `get_by_id()` lo repite internamente — no es falla de seguridad, es query
      redundante.
- [x] **`list_table_fields` expone metadata de esquema fuera de catálogo** — `api/src/app_platform/schema_manager/controllers/database_controller.py:69-86`.
      Solo exige `require_org_or_global` (cualquier usuario con organización, no solo
      admin global) y no valida `schema_name`/`table_name` contra `TENANT_SCOPED_TABLES`;
      cualquier usuario puede inspeccionar columnas/tipos/enums de cualquier tabla
      física de la base (ej. `identity.usuarios`, `billing.*`), no solo las 7 tablas
      habilitadas para reportes/segmentos. No es fuga de datos cross-tenant, sí es
      reconocimiento de esquema interno fuera de lo previsto.

## Bajo

- [x] **Unicidad no validada en `update_user`** — `api/src/identity/users/services/user_service.py:415-443`.
      No valida `email`/`document_number` únicos antes de guardar; termina en
      `IntegrityError` no capturado (500 genérico) en vez de 409 controlado.
- [x] **Resolución de gateway por país sin guard** — `api/src/billing/gateways/resolver.py:37`.
      País no listado cae a Bold (exclusivo CO) sin fallar explícito; sin test que
      mantenga sincronizado con `Nationality`.
- [ ] **Payload de tarjeta Bold sin dirección de facturación** — `api/src/receivables/payment_gateways/gateways/bold/bold_gateway.py:135-150`.
      Ya marcado como `shortcut` en el propio código, pendiente de confirmar con doc de Bold.
- [x] **Serialización de Decimal a float en query builder** — `api/src/app_platform/schema_manager/utils/query_utils.py:24-26` (`serialize_value`).
      Restringido a admin global, solo lectura — bajo riesgo pero mismo patrón.
- [x] **Enums libres de dominio cerrado** — resuelto solo para `address_type`
      (`debtors/models/address_model.py` → `AddressType` nativo, 2 valores
      `PRIMARY`/`SECONDARY` confirmados en uso real con lógica que rama sobre ellos
      en `portfolio_file_parser.py`). `reactivation_mode`
      (`portfolio_daily_counter_config_model.py`) y `adjustment_type`
      (`credit_adjustment_model.py`) se dejaron como `String`: al revisar el código
      no hay un conjunto cerrado real todavía — cada uno tiene un único valor en
      uso en todo el repo (`"FROM_TODAY"`, `"CONDONACION"`), nunca se rama sobre
      otro valor, y el propio schema de `reactivation_mode` documenta "FROM_TODAY u
      otro" (abierto a futuro a propósito). Convertirlos a ENUM ahora sería cerrar
      un dominio que el propio código todavía no definió.
- [x] **Prefijo telefónico resuelto sin filtrar por portafolio** — `api/src/receivables/debtors/services/debtor_service.py:345-354`
      (`_resolve_debtor_phone_prefix`). Usa el crédito más reciente del deudor sin
      filtrar por `portfolio_id` de la operación en curso; si el deudor tiene créditos
      en portafolios de países distintos, puede tomar el prefijo equivocado.
- [x] **`build_table_alias_map` no soporta self-join** — `api/src/app_platform/schema_manager/utils/query_utils.py:262-277`.
      Indexa por `schema.tabla`, no por alias; dos entradas de la misma tabla con
      alias distintos se pisan. Falla segura (error de Postgres manejado), pero
      bloquea un caso de uso legítimo sin mensaje claro.

## Auditado — sin hallazgos de fuga cross-tenant

`api/src/app_platform/schema_manager/` (`DmlService`, query builder dinámico que usan
`receivables/reports` y `receivables/segments`): verificado que `TENANT_SCOPED_TABLES`
actúa como allowlist default-deny (tabla fuera del catálogo = `ValueError` antes de
tocar la BD), el scope se aplica por tabla y se combina con AND en el WHERE (un JOIN
no puede esquivarlo), identificadores sanitizados por regex y valores escapados
(sin inyección SQL), y el modo sin scoping solo es alcanzable vía `require_global_admin`.
Único hueco real quedó listado arriba en Medio (`list_table_fields`).
