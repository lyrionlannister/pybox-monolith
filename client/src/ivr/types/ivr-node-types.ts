import type { Node, Edge } from "@xyflow/react";
import type { AmdPreset, AmdVariables } from "@/ivr/constants/amd-presets";

/**
 * Modelo de datos del diseñador de flujos IVR, alineado con el contrato de la
 * API de Helena (`CampaignIvrConfig`). El grafo visual (nodos React Flow +
 * conexiones) se compila a ese contrato en `utils/compile-flow.ts`.
 *
 * Mapeo de tipos visuales → tipos Helena:
 *   play → playback · menu → menu · transfer → transfer · capture → collect
 * El desenlace "colgar" se modela como una ACCIÓN terminal (no como un nodo).
 *
 * Se usan `type` (no `interface`) porque React Flow exige que `node.data` sea
 * asignable a `Record<string, unknown>`.
 */

export type IvrNodeType = "play" | "menu" | "transfer" | "capture" | "condition" | "hangup";

/**
 * Variables built-in que Helena expone a un nodo `condition`, además de
 * cualquier variable capturada por un nodo `capture`/`collect` de la sesión.
 */
export const CONDITION_BUILTIN_VARIABLES: Array<{ value: string; label: string }> = [
  { value: "amd_status", label: "amd_status (HUMAN / MACHINE / NOTSURE / HANGUP)" },
  { value: "amd_cause", label: "amd_cause (causa del AMD)" },
  { value: "hour", label: "hour (hora del servidor, '0'–'23')" },
  { value: "weekday", label: "weekday ('0' = domingo … '6' = sábado)" },
];

/** Teclas marcables en un teléfono. */
export type DigitKey = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "*" | "#";

/**
 * Acción asociada a un desenlace de un nodo (fin de audio, dígito, timeout, etc.).
 * - `goto`  → salta a otro nodo; genera un handle de salida propio en el nodo.
 * - `hangup`→ cuelga la llamada. Helena exige un `reason` (para reportería); si
 *             se deja vacío, el compilador genera uno por defecto según el desenlace.
 * - `repeat`→ repite el nodo actual (solo permitido donde tiene sentido).
 */
export type IvrActionKind = "hangup" | "goto" | "repeat";

export type IvrAction = {
  kind: IvrActionKind;
  /**
   * Id del handle de salida del que parte la conexión cuando `kind === "goto"`.
   * Es determinista según el desenlace (ver HANDLE_IDS en ivr-utils).
   */
  handleId?: string;
  /** Motivo registrado al colgar (`kind === "hangup"`). Opcional. */
  reason?: string;
};

export type MenuDigit = {
  /** Id estable para React (independiente de la tecla elegida). */
  id: string;
  key: DigitKey | "";
  action: IvrAction;
};

// --- ajustes a nivel de flujo (compilan a defaults/redial de Helena) --------

export type IvrDefaults = {
  /** Timeout de espera de DTMF en ms (menu / entre dígitos de collect). */
  dtmfTimeoutMs: number;
  /** Máximo de reintentos por acción `repeat` antes de colgar. */
  maxRetries: number;
  /** Si el audio principal es interrumpible por DTMF por defecto. */
  interruptible: boolean;
};

export type IvrRedial = {
  /** Intentos totales por contacto (1 = sin remarcado). */
  maxAttempts: number;
  /** Segundos de espera entre intentos. */
  retryDelaySeconds: number;
};

/**
 * Ritmo de marcación del bulk. A diferencia de `defaults`/`redial`,
 * no hay compilación: estos valores viajan tal cual al `callsPerSecond` /
 * `maxConcurrent` / `defaultCallerId` del bulk. `null` en cualquiera de los
 * dos primeros deja que Helena use su propio default de sistema.
 */
export type IvrPacing = {
  callsPerSecond: number | null;
  maxConcurrent: number | null;
  callerId: string;
  /** Id de la política de contacto de Helena; "" = sin restricción horaria. */
  contactPolicyId: string;
};

/**
 * Etiquetas de resultado de negocio por desenlace.
 *
 * En el editor se indexa por **id de nodo** (estable mientras se edita, así
 * reordenar o renombrar no pierde las etiquetas); al compilar se traduce al
 * nombre del nodo en el contrato de Helena, que es lo que devuelve el webhook
 * en `ivrEndNodeId`. La clave especial `__call_level__` cubre las llamadas que
 * nunca entraron al IVR.
 */
export type IvrOutcomeMap = Record<string, Record<string, string>>;

/** Nodo virtual para las llamadas que no llegaron a entrar al flujo. */
export const CALL_LEVEL_NODE = "__call_level__";

/** Desenlaces de nivel de llamada, con su etiqueta sugerida. */
export const CALL_LEVEL_OUTCOMES: Array<{ key: string; hint: string }> = [
  { key: "no_answer", hint: "No contestó" },
  { key: "voicemail", hint: "Buzón / contestadora" },
  { key: "abandono", hint: "Contestó pero colgó" },
  { key: "out_of_schedule", hint: "Fuera del horario permitido (no se marcó)" },
  { key: "cancelled", hint: "Cancelada en la cola antes de marcarse" },
];

/** Desenlaces que Helena genera por su cuenta en cualquier nodo. */
export const SYSTEM_OUTCOMES: Array<{ key: string; hint: string }> = [
  { key: "abandono", hint: "El cliente colgó en este paso" },
  { key: "max_retries_exceeded", hint: "Se agotaron los reintentos" },
];

/** Desenlace extra de los nodos de transferencia. */
export const TRANSFER_SYSTEM_OUTCOME = { key: "answered", hint: "El agente atendió y colgó" };

// --- data por tipo de nodo -------------------------------------------------

/** Común a los nodos que reproducen un audio de Helena. */
type WithAudio = {
  /** Nombre de archivo en Helena (`serverFileName`), usado como `audio` en la config. */
  audio: string | null;
  /** Nombre amigable para mostrar en el diseñador. */
  audioLabel: string | null;
};

export type PlayNodeData = WithAudio & {
  interruptible: boolean;
  /** Acción al terminar el audio. Sin "repeat" (evita loop infinito sin salida). */
  onFinish: IvrAction;
};

export type MenuNodeData = WithAudio & {
  interruptible: boolean;
  digits: MenuDigit[];
  /** No se marca nada (→ `on_no_input` de Helena). */
  onTimeout: IvrAction;
  /** Dígito no contemplado (→ `on_invalid`). */
  onInvalid: IvrAction;
};

export type TransferNodeData = {
  /** Endpoint SIP destino en formato Helena, ej. `SIP/SERVIDOR/6428`. */
  endpoint: string;
  /** Tiempo máximo de ring en ms antes de considerar "no contesta". */
  timeoutMs: number;
  onNoAnswer: IvrAction;
  /** Transferencia completada (→ `on_finish`). Sin "repeat". */
  onCompleted: IvrAction;
};

/**
 * Rama de un nodo `condition`: compara la variable contra un valor exacto.
 * Helena resuelve por igualdad de string, no por expresión.
 */
export type ConditionCase = {
  /** Id estable para React (independiente del valor). */
  id: string;
  value: string;
  action: IvrAction;
};

export type ConditionNodeData = {
  /** Variable de sesión o built-in a evaluar (ver CONDITION_BUILTIN_VARIABLES). */
  variable: string;
  cases: ConditionCase[];
  /** Rama tomada cuando ningún caso coincide (`default` de Helena). */
  onDefault: IvrAction;
};

export type HangupNodeData = {
  /** Motivo registrado al colgar; queda en `ivrEndReason` para reportería. */
  reason: string;
};

export type CaptureNodeData = WithAudio & {
  interruptible: boolean;
  /** Cantidad de dígitos a capturar (`num_digits`). */
  numDigits: number;
  /** Tecla que finaliza la captura antes de completar (`finish_on_key`). */
  finishKey: DigitKey;
  /** Timeout entre dígitos en segundos (se envía a Helena en ms). */
  timeoutSeconds: number;
  /** Nombre de la variable de sesión donde se guardan los dígitos (`variable`). */
  variable: string;
  onTimeout: IvrAction;
  /** Captura completada (→ `on_complete`). Sin "repeat". */
  onCompleted: IvrAction;
};

export type IvrNodeData =
  | PlayNodeData
  | MenuNodeData
  | TransferNodeData
  | CaptureNodeData
  | ConditionNodeData
  | HangupNodeData;

/**
 * Patch parcial del `data` de un nodo. Es una unión de `Partial<...>` por tipo
 * (no `Partial<IvrNodeData>`, que colapsaría a las claves comunes).
 */
export type IvrNodeDataPatch =
  | Partial<PlayNodeData>
  | Partial<MenuNodeData>
  | Partial<TransferNodeData>
  | Partial<CaptureNodeData>
  | Partial<ConditionNodeData>
  | Partial<HangupNodeData>;

// --- nodos de React Flow tipados ------------------------------------------

export type PlayNode = Node<PlayNodeData, "play">;
export type MenuNode = Node<MenuNodeData, "menu">;
export type TransferNode = Node<TransferNodeData, "transfer">;
export type CaptureNode = Node<CaptureNodeData, "capture">;
export type ConditionNode = Node<ConditionNodeData, "condition">;
export type HangupNode = Node<HangupNodeData, "hangup">;
export type IvrNode =
  | PlayNode
  | MenuNode
  | TransferNode
  | CaptureNode
  | ConditionNode
  | HangupNode;
export type IvrEdge = Edge;

// --- serialización (graph crudo persistido para reeditar) ------------------

export type IvrFlowSerialized = {
  id: string;
  name: string;
  version: number;
  updatedAt: string;
  /** Id del nodo de entrada (arranque de la llamada). */
  entryNodeId: string | null;
  defaults: IvrDefaults;
  redial: IvrRedial;
  /** Preset AMD elegido y variables AMD (enviadas a Helena como `variables`). */
  amdPreset: AmdPreset;
  amd: AmdVariables;
  /** Etiquetas de resultado por nodo (indexadas por id de nodo). */
  outcomes?: IvrOutcomeMap;
  nodes: Array<{
    id: string;
    type: IvrNodeType;
    position: { x: number; y: number };
    data: IvrNodeData;
  }>;
  edges: Array<{
    id: string;
    source: string;
    sourceHandle: string | null;
    target: string;
    targetHandle: string | null;
  }>;
};
