"""Construcción de opciones de variable de plantilla con ejemplo y descripción."""

from messaging.templates.schemas.template_schemas import TemplateVariableOption

# Nombres reales de columna: core.base.{created_at,updated_at,soft_delete}_mixin
_AUDIT_FIELD_NAMES = {"fecha_creacion", "fecha_actualizacion", "eliminado_en"}

_EXAMPLES_BY_KEYWORD: tuple[tuple[str, str], ...] = (
    ("nombre_completo", "Juan Pérez"),
    ("nombre", "Juan"),
    ("apellido", "Pérez"),
    ("empresa", "Acme Corp"),
    ("correo", "cliente@ejemplo.com"),
    ("email", "cliente@ejemplo.com"),
    ("telefono", "+57 300 123 4567"),
    ("celular", "+57 300 123 4567"),
    ("numero_documento", "1234567890"),
    ("documento", "1234567890"),
    ("numero_credito", "CR-00012345"),
    ("direccion", "Calle 123 #45-67"),
    ("ciudad", "Bogotá"),
    ("pais", "Colombia"),
)


def is_audit_field(name: str) -> bool:
    return name.lower() in _AUDIT_FIELD_NAMES


def is_id_field(name: str) -> bool:
    n = name.lower()
    return n == "id" or n.startswith("id_") or n.endswith("_id") or "_id_" in n


def should_hide_field(name: str) -> bool:
    return is_audit_field(name) or is_id_field(name)


def to_human_label(name: str) -> str:
    label = name.replace("_", " ").strip()
    return label[:1].upper() + label[1:] if label else label


def example_for(name: str, data_type: str) -> str:
    n = name.lower()
    dt = (data_type or "").lower()

    for keyword, example in _EXAMPLES_BY_KEYWORD:
        if keyword in n:
            return example

    if "bool" in dt:
        return "true"
    if "date" in dt or "time" in dt:
        return "14:30:00" if "hora" in n or n.endswith("_time") else "2025-11-14"
    if "int" in dt or "serial" in dt:
        return "123"
    if any(token in dt for token in ("numeric", "decimal", "real", "double", "money")):
        if any(
            token in n
            for token in (
                "saldo",
                "monto",
                "valor",
                "interes",
                "tasa",
                "comision",
                "fee",
                "iva",
                "seguro",
                "cuota",
            )
        ):
            return "1234.56"
        return "12.34"
    if any(token in n for token in ("dias", "cuotas", "cantidad", "plazo")):
        return "35"

    return "Ejemplo"


def build_variable(
    name: str, data_type: str, table: str
) -> TemplateVariableOption | None:
    if should_hide_field(name):
        return None
    return TemplateVariableOption(
        key=name,
        label=to_human_label(name),
        example=example_for(name, data_type),
        source_table=table,
    )


def build_payment_variable(
    name: str, data_type: str, suffix: str, strategy_label: str, table: str
) -> TemplateVariableOption | None:
    """Una columna de `pagos` genera una variable por cada estrategia de
    cuota (ver PAYMENT_STRATEGY_SUFFIXES) — elegir la variable de la
    lista ya implica elegir a cuál cuota del cronograma se refiere, sin
    necesidad de un selector aparte."""
    if should_hide_field(name):
        return None
    return TemplateVariableOption(
        key=f"{name}_{suffix}",
        label=f"{to_human_label(name)} ({strategy_label})",
        example=example_for(name, data_type),
        source_table=table,
    )
