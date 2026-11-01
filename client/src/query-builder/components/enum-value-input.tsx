import { Select } from "@/ui/components/inputs/select";
import type { EnumValueInputProps } from "@/query-builder/types/enum-value-input-props";

/**
 * Valor de un filtro sobre una columna enum de PostgreSQL: en vez de texto libre se
 * ofrecen los valores reales del enum. La forma depende del operador (ver
 * OPS_WITH_MULTIPLE_VALUES): in/not_in -> selección múltiple, between -> desde/hasta,
 * el resto -> un único select.
 */
export const EnumValueInput: React.FC<EnumValueInputProps> = ({ options, op, value, onChange }) => {
  const selectOptions = options.map((o) => ({ value: o, label: o }));

  if (op === "in" || op === "not_in") {
    const selected = Array.isArray(value) ? value : [];
    const toggle = (option: string) =>
      onChange(options.filter((o) => (o === option ? !selected.includes(o) : selected.includes(o))));

    return (
      <div className="flex flex-wrap gap-2">
        {options.map((o) => {
          const checked = selected.includes(o);
          return (
            <label
              key={o}
              className={`flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                checked
                  ? "border-brand-300 bg-brand-50 text-brand-500 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-400"
                  : "border-gray-200 text-gray-700 hover:border-brand-300 dark:border-gray-700 dark:text-gray-300"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(o)}
                className="accent-brand-500 shrink-0"
              />
              {o}
            </label>
          );
        })}
      </div>
    );
  }

  if (op === "between") {
    const [from = "", to = ""] = Array.isArray(value) ? value : [];
    return (
      <div className="grid grid-cols-2 gap-2">
        <Select value={from} onChange={(v) => onChange([v, to])} options={selectOptions} placeholder="Desde" />
        <Select value={to} onChange={(v) => onChange([from, v])} options={selectOptions} placeholder="Hasta" />
      </div>
    );
  }

  return (
    <Select
      value={typeof value === "string" ? value : ""}
      onChange={onChange}
      options={selectOptions}
      placeholder="Selecciona un valor"
    />
  );
};
