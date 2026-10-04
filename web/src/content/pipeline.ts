// The eight pipeline steps, as told in the guided story and in the follow-up deck.

export interface PipelineStep {
  key: string;
  title: [string, string];
  what: [string, string];
  bullets: [string, string][];
  guarantee: [string, string];
  module: string;
  output: [string, string];
}

export const PIPELINE_STEPS: PipelineStep[] = [
  {
    key: "ingest",
    title: ["Ingesta", "Ingestion"],
    what: [
      "Lee los ficheros anuales de ESAVI y el registro de liberación de lotes tal como llegan, sin modificarlos.",
      "Reads the annual AEFI files and the lot release register as delivered, without modifying them.",
    ],
    bullets: [
      ["Registro de esquemas: detecta cabeceras desplazadas, columnas renombradas y deriva entre años.", "Schema registry: detects shifted headers, renamed columns and drift between years."],
      ["Huella SHA-256 de cada fichero de entrada en el manifiesto.", "SHA-256 fingerprint of every input file in the manifest."],
      ["Los originales se abren en solo lectura (ALCOA+).", "Originals are opened read-only (ALCOA+)."],
    ],
    guarantee: ["Datos originales inmutables y trazables.", "Immutable, traceable source data."],
    module: "vamengoc.io · vamengoc.ingest",
    output: ["Tablas intermedias locales (nunca versionadas)", "Local interim tables (never versioned)"],
  },
  {
    key: "pseudo",
    title: ["Seudonimización", "Pseudonymisation"],
    what: [
      "Elimina nombres y direcciones y genera un seudónimo HMAC con una clave secreta guardada fuera del repositorio.",
      "Drops names and addresses and derives an HMAC pseudonym with a secret key kept outside the repository.",
    ],
    bullets: [
      ["La fecha de nacimiento se generaliza a edad.", "Date of birth is generalised to age."],
      ["El texto libre (CUAL) nunca sale del entorno local.", "Free text (CUAL) never leaves the local environment."],
      ["Ningún identificador llega a registros, pruebas ni salidas.", "No identifier reaches logs, tests or outputs."],
    ],
    guarantee: ["Minimización de datos personales desde la primera línea.", "Personal data minimised from the first line."],
    module: "vamengoc.security",
    output: ["Registros seudonimizados cifrados en reposo", "Pseudonymised records, encrypted at rest"],
  },
  {
    key: "parse",
    title: ["Normalización", "Normalisation"],
    what: [
      "Convierte fechas, edades, dosis, lotes y especificaciones escritas a mano en valores tipados.",
      "Turns hand-typed dates, ages, doses, lots and specifications into typed values.",
    ],
    bullets: [
      ["Diccionarios versionados de vacunas, eventos, provincias y fabricantes.", "Versioned dictionaries of vaccines, events, provinces and manufacturers."],
      ["Cada valor recuperado o descartado queda contado.", "Every recovered or discarded value is counted."],
      ["Eventos alineados con las definiciones de Brighton.", "Events aligned with Brighton definitions."],
    ],
    guarantee: ["Reglas explícitas y probadas, no limpieza manual.", "Explicit, tested rules instead of manual cleaning."],
    module: "vamengoc.parsing · vamengoc.normalize",
    output: ["Modelo analítico de notificaciones y lotes", "Analytical model of reports and lots"],
  },
  {
    key: "quality",
    title: ["Calidad de datos", "Data quality"],
    what: [
      "Mide completitud, conformidad y plausibilidad de cada campo y cada año.",
      "Measures completeness, conformance and plausibility for every field and year.",
    ],
    bullets: [
      ["Comprobaciones temporales (notificación antes de vacunación, estancias imposibles…).", "Temporal checks (notification before vaccination, impossible stays…)."],
      ["Conflictos de edad, sexo y embarazo.", "Age, sex and pregnancy conflicts."],
      ["Los registros marcados se informan, no se borran.", "Flagged records are reported, not deleted."],
    ],
    guarantee: ["Calidad cuantificada antes de analizar.", "Quality quantified before any analysis."],
    module: "vamengoc.curate.quality",
    output: ["Informe de calidad (sección Calidad de datos)", "Data-quality report (Data quality section)"],
  },
  {
    key: "link",
    title: ["Enlace con lotes", "Lot linkage"],
    what: [
      "Une cada notificación de VA-MENGOC-BC con su lote liberado por coincidencia exacta, de núcleo o aproximada.",
      "Links every VA-MENGOC-BC report to its released lot by exact, core or fuzzy matching.",
    ],
    bullets: [
      ["Se descartan enlaces temporalmente inverosímiles.", "Temporally implausible links are discarded."],
      ["Se compara lo enlazado con lo no enlazado (sesgo de enlace).", "Linked and unlinked reports are compared (linkage bias)."],
      ["Los valores de lote se publican solo normalizados.", "Lot values are released only in normalised form."],
    ],
    guarantee: ["Información industrial confidencial protegida.", "Confidential industrial data protected."],
    module: "vamengoc.curate.linkage",
    output: ["Marco notificación–lote para el artículo 2", "Report–lot frame for paper 2"],
  },
  {
    key: "analyse",
    title: ["Análisis", "Analysis"],
    what: [
      "Ejecuta los análisis preespecificados de los dos artículos con semillas fijas.",
      "Runs the prespecified analyses of both papers with fixed seeds.",
    ],
    bullets: [
      ["Artículo 1: tasas, desproporcionalidad (ROR, PRR, IC, EBGM), clases latentes, modelo de hospitalización.", "Paper 1: rates, disproportionality (ROR, PRR, IC, EBGM), latent classes, hospitalisation model."],
      ["Artículo 2: capacidad de proceso, gráficos de control, MSPC, GEE de caso único, valor incremental.", "Paper 2: process capability, control charts, MSPC, case-only GEE, incremental value."],
      ["Análisis de sensibilidad y controles negativos.", "Sensitivity analyses and negative controls."],
    ],
    guarantee: ["Mismos datos y configuración, mismos resultados.", "Same data and configuration, same results."],
    module: "vamengoc.analysis",
    output: ["Resultados completos (solo locales)", "Full results (local only)"],
  },
  {
    key: "sdc",
    title: ["Control de divulgación", "Disclosure control"],
    what: [
      "Suprime celdas con menos de 5 casos y cualquier cifra que permita recuperarlas por diferencia.",
      "Suppresses cells below 5 cases and any figure that would allow them to be recovered by subtraction.",
    ],
    bullets: [
      ["Supresión primaria (<5) y complementaria ([c]).", "Primary (<5) and complementary ([c]) suppression."],
      ["Protección de totales, diseños anidados y porcentajes.", "Protection of totals, nested designs and percentages."],
      ["Un verificador independiente revisa cada fichero publicado.", "An independent verifier checks every released file."],
    ],
    guarantee: ["Ninguna persona identificable en lo publicado.", "No identifiable person in what is released."],
    module: "vamengoc.release.sdc · vamengoc.release.verify",
    output: ["Release público verificado", "Verified public release"],
  },
  {
    key: "publish",
    title: ["Publicación", "Publication"],
    what: [
      "Genera tablas, figuras y macros que alimentan los manuscritos LaTeX, esta aplicación y las presentaciones.",
      "Generates the tables, figures and macros that feed the LaTeX manuscripts, this app and the slide decks.",
    ],
    bullets: [
      ["Cada número del texto procede de una macro generada.", "Every number in the text comes from a generated macro."],
      ["Manuscritos en inglés y español compilados sin advertencias.", "English and Spanish manuscripts compiled without warnings."],
      ["Manifiesto con versión de código, configuración y semilla.", "Manifest with code version, configuration and seed."],
    ],
    guarantee: ["Texto y resultados no pueden contradecirse.", "Text and results cannot contradict each other."],
    module: "vamengoc.release",
    output: ["Artículos, informes, web y presentaciones", "Papers, reports, web and slide decks"],
  },
];
