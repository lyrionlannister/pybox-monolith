export interface TableOption {
  name: string;
  label: string;
}

/**
 * Lo único que realmente difiere entre segments y reports: endpoint, nombre del
 * campo de payload, tablas disponibles (dominios de datos distintos) y los copys
 * de texto. Todo lo demás (wizard, validaciones, ejecución) es compartido.
 */
export interface QueryBuilderEntityConfig {
  kind: "segments" | "reports";
  configKey: "filterCriteria" | "reportConfig";
  mainTables: TableOption[];
  additionalTables: TableOption[];
  allTables: TableOption[];
  steps: readonly string[];
  copy: {
    entityNoun: string;
    entityNounPlural: string;
    toggleHelpExample: string;
    havingExampleMetric: string;
    namePlaceholder: string;
    descriptionPlaceholder: string;
  };
}
