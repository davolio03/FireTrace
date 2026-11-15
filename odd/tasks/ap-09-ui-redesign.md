# AP-09 web experience redesign
Branch: feat/ap-09-ui-redesign; delivery: ask-on-risk; runner: npm test, npm run lint, npm run build.
Human review precedes commit, PR and merge; no new dependencies without separate approval.

## Specs

1. **S1**: “Transformar FireTrace de una interfaz que se siente como una maqueta en una experiencia «muy dinámica, moderna y fluida», adecuada para explorar evidencia geoespacial. La dirección visual debe sentirse cuidada y coherente; el mapa y los datos siguen siendo los protagonistas.”

2. **S2**: “En la portada, identificar de un vistazo el caso, el lugar, las fechas y el estado de los datos, y entender cómo entrar al análisis o iniciar la historia. La información secundaria y las fuentes siguen disponibles sin competir con la acción principal.”

3. **S3**: “En el análisis, disponer de un mapa claramente protagonista y acceder fácilmente a capas, leyendas, comparación HH/HV, perímetro, métricas, inspector, transecto y anotaciones. Organizar controles y paneles para evitar una página de bloques largos que obligue a buscar cada herramienta; se pueden emplear paneles laterales, secciones desplegables u otra solución equivalente.”

4. **S4**: “Entender en cada momento qué herramienta, capa, selección o comparación está activa; mostrar acciones principales, estados de carga, datos ausentes, errores y confirmaciones de guardado/importación/exportación de forma visible y comprensible.”

5. **S5**: “Recorrer la historia, volver al análisis y continuar explorando sin perder inesperadamente el estado compartido ni romper las funciones existentes.”

6. **S6**: “Definir una identidad visual consistente para tipografía, colores, espaciado, superficies, iconos, botones y controles. Priorizar jerarquía, legibilidad y contraste; evitar que la decoración compita con el mapa o sus leyendas.”

7. **S7**: “Dar profundidad y continuidad con transiciones, cambios de estado y microinteracciones útiles: por ejemplo, apertura de paneles, selección de herramientas y navegación. Deben ser rápidas y no bloquear la interacción; con movimiento reducido, la experiencia debe seguir siendo completa sin animaciones innecesarias.”

8. **S8**: “En escritorio, aprovechar el espacio para ver simultáneamente el mapa y la herramienta pertinente. En pantalla estrecha, reorganizar los controles y paneles sin que oculten permanentemente el mapa ni exijan desplazamiento horizontal.”

9. **S9**: “Mantener controles operables con teclado, foco visible y etiquetas accesibles; los estados y categorías no dependen solo del color. Mantener legibles las leyendas, los valores y los avisos.”

10. **S10**: “Conservar de forma visible el aviso MOCK cuando corresponda y las diferencias entre observaciones de radar, perímetro oficial, limitaciones y juicios del analista. Nunca presentar cambios como confirmación de incendio, superficie quemada o confianza inventada.”

11. **S11**: “Revisar primero la interfaz y los recorridos existentes; definir una dirección visual y una organización coherente antes de extender estilos aislados. La persona que implemente tiene libertad para decidir la paleta, la composición, el aspecto de los componentes y las transiciones, siempre que cumplan los resultados anteriores; los ejemplos de paneles no son una solución obligatoria.”

12. **S12**: “Reutilizar el stack y las herramientas existentes cuando sirvan: React, Tailwind CSS, MapLibre, Lucide, Zustand, TanStack Query y Recharts. Aprovechar componentes accesibles existentes y CSS para interacciones sencillas; no incorporar librerías solo por efecto visual.”

13. **S13**: “Si una necesidad concreta justifica una librería adicional de componentes o animación, se puede proponer con su utilidad, coste y alternativas. Su incorporación requiere aprobación humana y seguir la política del proyecto para dependencias y cambios de stack; no queda instalada ni aprobada por esta propuesta.”

14. **S14**: “Buscar y utilizar las skills de frontend, diseño o accesibilidad que estén realmente disponibles en el entorno durante la implementación. Si no hay una específica, indicarlo y aplicar igualmente los criterios de esta tarea; no inventar skills ni convertir documentación en una dependencia de ejecución.”

15. **S15**: “Portada, análisis y navegación tienen el acabado y la jerarquía descritos; la persona responsable de frontend puede revisar el resultado en escritorio y en pantalla estrecha.”

16. **S16**: “Capas/leyendas, comparación, perímetro, métricas, inspector, transecto, historia y anotaciones/exportación siguen funcionando; se comprueban los estados reales y MOCK disponibles y los errores sin fabricar datos.”

17. **S17**: “Se comprueban navegación con teclado, foco visible, contraste, etiquetas y movimiento reducido; la presentación de datos y advertencias sigue siendo fiel a los contratos.”

18. **S18**: “Las pruebas existentes siguen pasando y se añaden pruebas proporcionadas para interacciones o regresiones introducidas. Se registran las comprobaciones visuales y las limitaciones reales.”

19. **S19**: “Fuera de alcance: cambios de contratos o métodos científicos, nuevas funciones de backend, integración de la API real y despliegue. Coordinar los archivos compartidos con EV-04 e IN-03 si continúan en curso.”

20. **S20**: “si necesitas herramientas y dependencias las puedes instalar o me das los comandos para que yo lo instale. Y he probado la web y es una buena primera version pero es muhy estatica, plana, colores apagados; quiero que recuerde a una mision de la nasa la interfaz y que uses librerias y skills para hacer mas dinamico el sitio e interactivo e inmersivo”

21. **S21**: “te autorizo a descargarlo, tambien haz una investigacion de que librerias, plugins, skills se usan en proyectos nuevos para conseguir esos resultados de experiencia inmersiva, dinamica, etc y lo haces, no hay limite, tiene que tener efecto wow”

22. **S22**: “Sigue sin convencerme el resultado, muy plano y con poco movimiento. Debe sentirse como una experiencia inmersiva con dinamismo, colores llamativos, con expresividad. Dale una vuelta sobre que librerias, plugins y skills se puede usar para lograr eso y me dices”

23. **S23**: “sigue siendo muy cuadriculado todo, ten libertad creativa, no todo dentro de cajas. Hazme una propuesta primero y te digo si me parece bien”

24. **S24**: “hazlo, que sea inmersivo, me gusto eso que hiciste de que el globo terraqueo hace zoom al entrar al analisis, mas cosas asi dinamicas pero que afecten mas pantallas, haz eso que propusiste con ese toque que dije, como si fuera un videojuego de inmersivo”

## Tasks
- [ ] T1 S1–S24 — inline; no independent writer reason; human review before commit.

## Log
- L1: “quiero mejorar la UI y UX de la pagina porque ahora esta muy maqueta, quiero que sea muy dinamico, moderno, fluido. Quiero crear una nueva tarea de app web para hacer esta mejora de la pagina”
- 2026-11-15: “creo que se puede ser mas espqcifico con lo que se espera de la interfaz y un poco como hacerlo o dejar claro esa libertad en la propuesta, usar skills y librerias para conseguirlo”
- 2026-11-15: “ya lo he aprobado, puedes empezar”
- 2026-11-15: Worktree created from main d5bd444. EV-04 and IN-03 are active separately. No frontend-specific design skill was found in the installed registry.
- 2026-11-15: Implemented map-first workspace, mounted tool panels, active-state indicators and annotation action feedback. Focused tests: 34 passed; web suite: 177 passed; web lint and build passed, with a Vite chunk-size warning.
- 2026-11-15: Offline Chromium at 390 px showed no horizontal overflow in the overview and five panels. Focus outline and reduced-motion transition were observed. Corrected text contrast measured 5.39:1 and 5.38:1. Basemap display remains unverified because external access was blocked.
- 2026-11-15: Repository check failed because ruff is unavailable; contract validation is pending because offline dependencies are unavailable. No dependencies were installed. The check created an ignored .venv. Independent verification of shared map and annotation behavior is pending; human review must precede commit.
- 2026-11-15: Independent verification reproduced a story-exit regression: selected Inspector evidence was hidden. Added failing-then-passing tests for the final chapter's Explore action and Escape, and synchronized the workspace panel in the shared story-exit callback. Focused tests: 36 passed; full web suite: 179 passed; lint, build and git diff --check passed. The targeted independent recheck is pending.
- 2026-11-15: Independent targeted recheck passed for Explore and Escape (2 tests). Repository-level checks and contract validation remain unavailable without the missing local dependencies; no install was performed. RDD is globally off. Local preview responds at 127.0.0.1:5192. Task remains in progress pending missing proof and human review.
- 2026-11-15: “si necesitas herramientas y dependencias las puedes instalar o me das los comandos para que yo lo instale. Y he probado la web y es una buena primera version pero es muhy estatica, plana, colores apagados; quiero que recuerde a una mision de la nasa la interfaz y que uses librerias y skills para hacer mas dinamico el sitio e interactivo e inmersivo”
- 2026-11-15: Started a mission-inspired dark visual direction with existing React, Lucide and CSS; transitions respect reduced motion. The revised direction is not yet complete. Web lint, 179 tests and build passed; build still warns about large chunks. Motion for React is a candidate for richer interaction; dependency installation and board coordination remain pending.
- 2026-11-15: “te autorizo a descargarlo, tambien haz una investigacion de que librerias, plugins, skills se usan en proyectos nuevos para conseguir esos resultados de experiencia inmersiva, dinamica, etc y lo haces, no hay limite, tiene que tener efecto wow”
- 2026-11-15: User authorized anonymous downloads of Motion from the public npm registry and declared Python dependencies from PyPI; bounded research and Python environment preparation are in progress.
- 2026-11-15: Gabriel authorized consulting AP-09 and recording Motion approval on the configured Kanvas board; approval was noted. Research compared Motion, GSAP, Three.js, deck.gl and native/CSS options. Added Motion 14.14.0 and ADR 0002; no second rendering engine. Implemented a mission-inspired palette and coordinated workspace navigation while retaining mounted panels and reduced-motion support.
- 2026-11-15: Updated web focused tests (36), lint and build passed. At 390 px all five panels remained within viewport, focus was visible, and reduced motion disabled CSS transitions. Build reports main bundle 1,899.91 kB (543.03 kB gzip), versus 1,811.70 kB (511.75 kB gzip) before Motion. Full repository checks and independent verification of dependency/shared-state changes are pending.
- 2026-11-15: Full repository check after Motion passed: 608 Python tests, 7 Windows-specific skips, 179 web tests, lint and build. Contract fixtures validated with uv. Python emitted 2,141 warnings and Vite retained its chunk-size warning.
- 2026-11-15: Independent verification found the dark background reduced map-load error contrast. Added a failing-then-passing map error test and applied the accessible error notice; the targeted recheck passed with 9.93:1 contrast. Web tests (179), lint, build and diff check passed after correction. Other acceptance, real-data journeys and basemap appearance remain for further review; human review precedes commit.
- 2026-11-15: “Sigue sin convencerme el resultado, muy plano y con poco movimiento. Debe sentirse como una experiencia inmersiva con dinamismo, colores llamativos, con expresividad. Dale una vuelta sobre que librerias, plugins y skills se puede usar para lograr eso y me dices”
- 2026-11-15: Second research round measured real bundle cost per library (esbuild, minified, gzip): Motion adds 31 kB to the main chunk, GSAP with ScrollTrigger 45 kB, anime.js 14 kB, Lenis 5 kB, auto-animate 4 kB, Radix slider 11 kB, Sonner 10 kB, lottie-react 83 kB, deck.gl 199 kB, three 190 kB, react-three-fiber 250 kB, drei 212 kB, postprocessing 148 kB, ogl 5 kB. No frontend design skill exists in the environment; a project skill was written instead.
- 2026-11-15: Implemented the immersive pass from MapLibre and CSS: globe overview with atmosphere and projection expression, colour-graded dark basemap, lat/lon graticule, additive raster blending, pale casing on vector overlays, pulsing selection marker, filmic grain and vignette, console typography (Space Grotesk + IBM Plex Mono), mission timeline strip, comparison sweep divider, staggered Motion reveals and a globe-to-analysis descent with a 2.5 s fallback. Web suite 180 passed; lint and build passed. Repository verification and human review pending.
- 2026-11-15: Full repository verification passed twice against a fingerprint-stable tree: ruff, eslint and prettier clean; pytest 608 passed and 7 Windows-only skips; vitest 28 files and 180 tests; web build; contract fixtures valid. Pre-existing warnings remain (2141 pytest warnings, jsdom per file, Vite chunk size). Measurement and verification scratch removed; the machine's /tmp tmpfs holds about 3.4 GB, so the uv environment must live on the /home disk. Human visual acceptance and basemap appearance with network remain open.
- 2026-11-15: “sigue siendo muy cuadriculado todo, ten libertad creativa, no todo dentro de cajas. Hazme una propuesta primero y te digo si me parece bien”
- Proposed, pending human approval: replace the boxed console with a full-bleed map canvas and floating HUD. The map fills the viewport; a hairline top bar holds the case and the MOCK badge; a vertical instrument rail of glyphs sits on the map; the active tool opens as a single floating glass panel over the map; panel content uses hairlines and mono readouts instead of nested cards; a faint engineering grid and edge instrumentation (real MapLibre scale bar, coordinate readout, heading ticks) frame the view; the landing becomes a full-bleed globe with overlaid type and an edge metadata column. No new dependency, no invented telemetry, every number on screen comes from the contracts.
- 2026-11-15: “hazlo, que sea inmersivo, me gusto eso que hiciste de que el globo terraqueo hace zoom al entrar al analisis, mas cosas asi dinamicas pero que afecten mas pantallas, haz eso que propusiste con ese toque que dije, como si fuera un videojuego de inmersivo”
- 2026-11-15: Implemented the approved HUD: full-bleed map, 46 px top bar, vertical instrument rail with hover labels and number-key shortcuts (1–5), one floating glass panel that keeps the other tools mounted, dark instrumented panels, engineering grid, real MapLibre metric scale bar, cursor coordinate readout and camera bearing, MOCK badge persistent in the bar. Landing is a full-bleed globe offset to the right with the title over it and case metadata on the right edge; the reticle follows the projected case position. Motion: instrument boot sweep, lit sweep when the instrumentation changes, panels entering with a spring, measured values counting to their new reading (AnimatedValue). Narrow layout becomes a bottom sheet with the rail above it and no horizontal overflow. Web suite 184 passed (29 files); lint and build passed.
- 2026-11-15: Browser checks at 1440 px and 390 px: no horizontal overflow in the landing or the HUD, the rail and the floating panel are present at both widths, the MOCK notice stays visible, the focus outline is 3 px amber, and with prefers-reduced-motion the boot sweep and panel reveal animations are disabled while the descent still completes. The guided story keeps its own approved AP-07 amber treatment.
