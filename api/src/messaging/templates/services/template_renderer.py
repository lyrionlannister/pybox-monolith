"""Renderizado local de plantillas ({variable}) usado solo para el preview."""

import re
from typing import Any

_VAR_PATTERN = re.compile(r"\{(\w+)\}")


class TemplateRenderer:
    """Sustituye variables `{nombre}` localmente, solo para la previsualización.

    El envío real delega la sustitución a 360NRS vía el parámetro `sub`.
    """

    def __new__(cls) -> "TemplateRenderer":
        if not hasattr(cls, "_instance"):
            cls._instance = super(TemplateRenderer, cls).__new__(cls)
        return cls._instance

    def find_variables(self, source: str) -> set[str]:
        return set(_VAR_PATTERN.findall(source))

    def render(self, source: str, variables: dict[str, Any]) -> str:
        def replace(match: re.Match) -> str:
            return str(variables.get(match.group(1), match.group(0)))

        return _VAR_PATTERN.sub(replace, source)

    def render_fields(
        self,
        body: str,
        subject: str | None,
        variables: dict[str, Any],
    ) -> tuple[str, str]:
        return self.render(body, variables), self.render(subject or "", variables)
