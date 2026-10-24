import { Input } from "@/ui/components/inputs/input";
import { Label } from "@/ui/components/inputs/label";
import { Select } from "@/ui/components/inputs/select";
import { PSE_LEGAL_ID_TYPE_OPTIONS } from "@/credits/constants/pse-legal-id-types";
import type { WompiPseFieldsProps } from "@/credits/types/wompi-pse-fields-props";

const USER_TYPE_OPTIONS = [
  { value: "0", label: "Persona natural" },
  { value: "1", label: "Persona jurídica" },
];

export const WompiPseFields: React.FC<WompiPseFieldsProps> = ({
  value,
  onChange,
  institutions,
  loadingInstitutions,
}) => {
  const institutionOptions = institutions.map((i) => ({
    value: i.financialInstitutionCode,
    label: i.financialInstitutionName,
  }));

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <Label htmlFor="wompi-pse-user-type">Tipo de persona</Label>
        <Select
          id="wompi-pse-user-type"
          options={USER_TYPE_OPTIONS}
          value={value.userType}
          onChange={(v) => onChange({ ...value, userType: v as "0" | "1" })}
        />
      </div>
      <div>
        <Label htmlFor="wompi-pse-legal-id-type">Tipo de documento</Label>
        <Select
          id="wompi-pse-legal-id-type"
          options={PSE_LEGAL_ID_TYPE_OPTIONS}
          value={value.userLegalIdType}
          onChange={(v) => onChange({ ...value, userLegalIdType: v })}
        />
      </div>
      <Input
        label="Número de documento"
        id="wompi-pse-legal-id"
        value={value.userLegalId}
        onChange={(e) => onChange({ ...value, userLegalId: e.target.value.replace(/\D/g, "") })}
      />
      <div>
        <Label htmlFor="wompi-pse-bank">Banco</Label>
        <Select
          id="wompi-pse-bank"
          options={institutionOptions}
          value={value.financialInstitutionCode}
          placeholder={loadingInstitutions ? "Cargando bancos..." : "Selecciona tu banco"}
          disabled={loadingInstitutions || institutionOptions.length === 0}
          onChange={(v) => onChange({ ...value, financialInstitutionCode: v })}
        />
      </div>
      <Input
        label="Nombre completo"
        id="wompi-pse-full-name"
        value={value.fullName}
        onChange={(e) => onChange({ ...value, fullName: e.target.value })}
      />
      <Input
        label="Celular"
        id="wompi-pse-phone"
        maxLength={10}
        value={value.phone}
        onChange={(e) => onChange({ ...value, phone: e.target.value.replace(/\D/g, "") })}
      />
      <Input
        label="Dirección"
        id="wompi-pse-address"
        value={value.address}
        onChange={(e) => onChange({ ...value, address: e.target.value })}
      />
      <Input
        label="Ciudad"
        id="wompi-pse-city"
        value={value.city}
        onChange={(e) => onChange({ ...value, city: e.target.value })}
      />
    </div>
  );
};
