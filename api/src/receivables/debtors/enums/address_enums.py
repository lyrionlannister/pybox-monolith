"""Tipo de dirección de un deudor: domicilio principal o secundario."""

from enum import StrEnum


class AddressType(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
