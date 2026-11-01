"""Límites y flags de la carga masiva de portafolio vía CSV/XLSX."""

MAX_ERRORS = 50

# Feature flag (leída con get_or_default EN CADA LLAMADA, no cacheada a nivel de
# módulo -- ver portfolio_csv_service.py) para el camino de precarga + bulk upsert de
# deudores/créditos (Fase 4 de la auditoría). Default "true": el camino bulk ya está
# verificado contra el mismo golden que el secuencial
# (test_bulk_path_matches_sequential_path_result) -- dejarlo detrás de un flag en
# "false" por defecto reintroducía el N+1 por fila que ya se había resuelto.
PORTFOLIO_CSV_BULK_UPSERT_ENV_VAR = "PORTFOLIO_CSV_BULK_UPSERT"
DEFAULT_PORTFOLIO_CSV_BULK_UPSERT = "true"

# Filas por chunk del camino bulk: cada chunk se intenta como un solo INSERT ... ON
# CONFLICT DO UPDATE por entidad (deudores, créditos); si el chunk completo falla por
# algo no previsto, se reprocesa fila por fila con el camino viejo (aislado por
# SAVEPOINT) solo para ESE chunk -- no para el archivo entero.
PORTFOLIO_CSV_BULK_CHUNK_SIZE = 500

# Encabezados que el archivo de portafolio (CSV/XLSX) debe traer sí o sí. El parser
# rechaza el archivo completo si falta alguno, antes de recorrer las filas.
REQUIRED_COLUMNS = {
    "Numero de documento",
    "Nombre del titular",
    "Tipo documento",
    "Telefono",
    "Correo Electronico",
    "Nombre del Codeudor",
    "Numero de documento codeudor",
    "Telefono codeudor",
    "Correo Electronico codeudor",
    "Ciudad",
    "Departamento",
    "Direccion",
    "Ciudad 2",
    "Departamento 2",
    "Direccion 2",
    "Numero de credito",
    "Fecha Desembolso",
    "Tipo de producto",
    "Tasa de interes pactada",
    "Tasa de interes cobrada",
    "Saldo Desembolso",
    "Fecha de corte",
    "plazo inicial",
    "saldo total del credito",
    "Saldo Capital en mora",
    "Intereses Corrientes",
    "Intereses Mora",
    "Otros Conceptos",
    "Cuotas en mora",
    "Dias en mora al corte",
    "Sistema de amortizacion",
    "numero de cuotas pendientes",
    "Seguros",
    "Comision",
    "Plataforma",
    "IVA",
    "SUBPRODUCTO",
    "Cotizacion de UVR",
    "Condonaciones y/o descuentos",
    "Fecha del pago",
    "Fecha limite de pago",
    "total",
    "Numero de la cuota que se cancela",
    "abono a capital",
    "interes corriente",
    "interes mora",
    "Seguro de vida",
    "seguro de vehiculo",
    "otros cargos",
}

# Mismas columnas que REQUIRED_COLUMNS, en el orden en que las lee el parser (deudor →
# codeudor → direcciones → crédito → pago). REQUIRED_COLUMNS es un set (solo importa
# pertenencia al validar); esta lista es la que arma la plantilla descargable, donde sí
# importa el orden.
PORTFOLIO_TEMPLATE_COLUMNS = [
    "Numero de documento",
    "Nombre del titular",
    "Tipo documento",
    "Telefono",
    "Correo Electronico",
    "Nombre del Codeudor",
    "Numero de documento codeudor",
    "Telefono codeudor",
    "Correo Electronico codeudor",
    "Direccion",
    "Ciudad",
    "Departamento",
    "Direccion 2",
    "Ciudad 2",
    "Departamento 2",
    "Numero de credito",
    "Fecha Desembolso",
    "Tipo de producto",
    "Tasa de interes pactada",
    "Tasa de interes cobrada",
    "Saldo Desembolso",
    "Fecha de corte",
    "plazo inicial",
    "saldo total del credito",
    "Saldo Capital en mora",
    "Intereses Corrientes",
    "Intereses Mora",
    "Otros Conceptos",
    "Cuotas en mora",
    "Dias en mora al corte",
    "Sistema de amortizacion",
    "numero de cuotas pendientes",
    "Seguros",
    "Comision",
    "Plataforma",
    "IVA",
    "SUBPRODUCTO",
    "Cotizacion de UVR",
    "Condonaciones y/o descuentos",
    "Fecha del pago",
    "Fecha limite de pago",
    "total",
    "Numero de la cuota que se cancela",
    "abono a capital",
    "interes corriente",
    "interes mora",
    "Seguro de vida",
    "seguro de vehiculo",
    "otros cargos",
]

# Encabezados del CSV de plan de cuotas (carga independiente del portafolio grande, ver
# PortfolioCsvService.upload_installments_csv). "Pago total del credito" es aparte de
# "Numero de la cuota que se cancela" a propósito: dejar la cuota vacía por error de
# captura no debe interpretarse como "saldar todo el crédito".
INSTALLMENT_REQUIRED_COLUMNS = {
    "Numero de credito",
    "Numero de la cuota que se cancela",
    "Pago total del credito",
    "Fecha limite de pago",
    "Fecha del pago",
    "total",
    "abono a capital",
    "interes corriente",
    "interes mora",
    "Seguro de vida",
    "seguro de vehiculo",
    "otros cargos",
    "IVA",
    "Comision",
    "Plataforma",
}

INSTALLMENT_TEMPLATE_COLUMNS = [
    "Numero de credito",
    "Numero de la cuota que se cancela",
    "Pago total del credito",
    "Fecha limite de pago",
    "Fecha del pago",
    "total",
    "abono a capital",
    "interes corriente",
    "interes mora",
    "Seguro de vida",
    "seguro de vehiculo",
    "otros cargos",
    "IVA",
    "Comision",
    "Plataforma",
]

# Texto que las entidades usan para decir "sin dato"; se compara en minúsculas.
NULL_STRINGS = {"n/a", "null", "sin dato", "none", ""}

# Formatos de fecha aceptados, en orden de intento.
DATE_FORMATS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"]

# Valores aceptados como "sí" en columnas booleanas tipo SI/NO del CSV.
AFFIRMATIVE_STRINGS = {"si", "sí", "yes", "true", "1", "x"}
