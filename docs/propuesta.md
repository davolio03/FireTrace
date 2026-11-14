# FireTrace Explorer

**Propuesta de proyecto — NASA Space Apps Challenge 2026**  
**Reto:** *Dancing with the SARs*  
**Versión:** 1.1 — 13 de noviembre de 2026  
**Equipo:** 6 participantes  
**Estado:** GO para el MVP de cambio radar HH/HV en Plaskett. Datos y referencia espacial verificados; la aplicación y la evaluación de severidad no están validadas.

> **One-liner:** *FireTrace muestra qué cambió en el radar NISAR antes y después de Plaskett y permite inspeccionar la señal y contrastarla con un perímetro oficial.*

---

## 1. Resumen ejecutivo

**FireTrace Explorer** es una aplicación web destinada a **analistas ambientales, equipos de evaluación postincendio e investigadores en teledetección**. Utiliza observaciones de radar de apertura sintética (SAR) de la misión **NASA–ISRO NISAR** para estudiar cómo ha cambiado el terreno tras un incendio forestal.

En vez de limitarse a pintar un perímetro quemado, FireTrace permite:

1. **Ver** las observaciones SAR antes y después del incendio.
2. **Medir** cambios de retrodispersión radar en HH y HV y, de forma opcional, destacar las zonas que superan un umbral explícito.
3. **Contrastar** las detecciones con perímetros oficiales y, cuando sea posible, imágenes ópticas de Sentinel-2.
4. **Entender** por qué se ha marcado cada zona, qué señales la respaldan y qué explicaciones alternativas existen.
5. **Cuantificar** la cobertura válida y, si se activa la máscara exploratoria, la superficie con cambio destacado y su acuerdo espacial con la referencia.

El objetivo del hackathon es completar **un único caso de estudio real y bien explicado**, no desarrollar un servicio global, operativo o en tiempo real.

### Decisiones ya tomadas

| Dimensión | Decisión |
|---|---|
| Problema | Interpretar y delimitar cambios asociados a incendios forestales a partir de radar satelital |
| Usuario principal | Analista de impacto postincendio |
| Diferenciación | **Detección explicable y trazable**, no una clasificación opaca |
| Misión central | **NISAR** (no sustituirlo por Sentinel-1 en el producto final) |
| Alcance | Un incendio, una región, comparaciones temporales documentadas |
| Presentación | Web interactiva con mapa, comparación temporal, métricas e inspector de evidencia |
| DL | Mejora experimental, **no dependencia para que funcione el MVP** |
| Caso seleccionado | **Plaskett Fire**, Big Sur, California, 2026; Timber queda fuera del MVP |

---

## 2. Problema que queremos resolver

### Situación actual

Después de un incendio, la delimitación de áreas afectadas suele apoyarse en reconocimiento de campo, perímetros operativos e imágenes ópticas. Estas últimas aportan información muy valiosa, pero pueden verse afectadas por humo, nubes o limitaciones temporales. Las imágenes SAR pueden observar la superficie tanto de día como de noche y atravesar nubes, pero su interpretación exige experiencia: un cambio radar no equivale automáticamente a un cambio causado por el fuego.

El analista necesita responder preguntas concretas:

- **¿Dónde se observa un cambio relevante en la señal radar?**
- **¿En qué medida ese cambio coincide con el perímetro oficial?**
- **¿Dónde hay discrepancias respecto al perímetro de referencia?**
- **¿Qué polarizaciones y observaciones sustentan cada resultado?**
- **¿Qué limitaciones y factores físicos pueden explicar el cambio observado?**

### El problema central

**Existe una distancia entre disponer de imágenes SAR y poder interpretar sus cambios con contexto geográfico y evidencia científica.** FireTrace pretende reducir esa distancia.

### Lo que FireTrace **no** pretende resolver

- No predice dónde ocurrirá el próximo incendio.
- No detecta incendios activos en tiempo real ni sustituye a servicios de emergencias.
- No estima automáticamente víctimas, pérdidas económicas, intensidad del fuego o severidad ecológica a partir de dos imágenes SAR.
- No considera un perímetro operativo una verdad píxel a píxel sin limitaciones.
- No presenta un resultado del modelo como *incendio confirmado* sin contraste externo.

---

## 3. Propuesta de valor y diferenciación

### Propuesta de valor

> **Para analistas ambientales que necesitan comprender el impacto espacial de un incendio**, FireTrace Explorer proporciona un análisis visual y verificable de los cambios detectados por NISAR. A diferencia de un visor SAR genérico o una simple máscara de clasificación, vincula el cambio observado a los valores de radar, al método de cálculo y al perímetro de referencia, sin confundir **observación**, **interpretación** y **validación externa**.

### Cuatro diferenciadores

1. **Explicabilidad científica.** Al seleccionar una zona se muestran señales HH/HV, diferencias entre fechas, método empleado y posibles factores de confusión.
2. **Comparación transparente con fuentes oficiales.** Superposición de perímetros del incendio y análisis de coincidencias/desacuerdos, sin tratarlos como etiquetas perfectas.
3. **Separación entre hecho e inferencia.** Los cambios SAR observados se muestran en una capa diferente de la interpretación como posible área quemada.
4. **Un relato comprensible del antes y después.** Un jurado sin formación en radar puede recorrer el caso y entender qué aporta NISAR.

**Por qué no basta con decir «usamos IA»:** ya existen métodos de detección de áreas quemadas con imágenes SAR y ópticas. La contribución que queremos demostrar es una **experiencia investigable, reproducible y honesta respecto a la incertidumbre**, con DL solo si aporta valor medible.

---

## 4. Usuarios y casos de uso

### Usuario principal: analista de evaluación postincendio

Trabaja en una organización ambiental, una entidad pública o un equipo de análisis geoespacial. Tiene que revisar un evento concreto y producir una interpretación razonada de qué territorio parece haber sufrido cambios.

**Trabajo por hacer:** «Quiero revisar rápidamente dónde el radar detecta cambios tras el incendio y comprobar qué evidencia existe antes de confiar en el mapa».

### Usuarios secundarios

- **Investigador/a de teledetección:** quiere comparar polarizaciones, métodos y geometrías de adquisición, además de estudiar errores.
- **Divulgador/a o estudiante:** quiere entender por qué radar y observación óptica aportan información complementaria.

### Tres escenarios de uso

1. **Exploración:** revisar un evento y comparar SAR anterior/posterior.
2. **Investigación de una zona:** seleccionar un polígono de cambio y consultar la explicación radar.
3. **Contraste:** encender el perímetro de referencia y examinar coincidencias y discrepancias, tanto dentro como fuera de él.

---

## 5. Caso de estudio: Plaskett Fire (California, 2026)

### Caso seleccionado y datos verificados (13/11/2026)

**Plaskett Fire**, en el condado de Monterey (Big Sur), comenzó el **26 de agosto de 2026** según [CAL FIRE](https://www.fire.ca.gov/incidents/2026/8/26/plaskett-fire). Es el único evento del MVP. Timber queda como alternativa futura, no como línea de trabajo en paralelo.

| Fecha UTC | ID en NASA CMR | Órbita absoluta | Track / frame / dirección |
|---|---|---|---|
| 16 de agosto de 2026, 02:56:39 | [G4284560161-ASF](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4284560161-ASF) | 5504 | 42 / 70 / descendente |
| 3 de octubre de 2026, 02:56:38 | [G4340499432-ASF](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4340499432-ASF) | 6196 | 42 / 70 / descendente |

- **Datos radar:** colección provisional NISAR L2 GCOV (`NISAR_L2_GCOV_PROVISIONAL_V1`). Earthdata Harmony extrajo dos bandas de frecuencia A por fecha, `HHHH` y `HVHV`, como GeoTIFF. Se descargaron y abrieron los cuatro archivos; no se inspeccionó el HDF5 original.
- **Comparabilidad:** los cuatro rásteres comparten origen, dimensiones, rejilla de **10 m** y CRS **EPSG:32610**. No se necesita remuestreo entre las escenas. Se leyeron **1.948.374 de 1.948.374 píxeles** con valores finitos y positivos en las cuatro capas del recorte rectangular que abarca el perímetro. Esa cifra mide disponibilidad de datos, no superficie quemada ni ausencia de efectos del relieve.
- **Referencia espacial:** [polígono WFIGS 58728](https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0/query?where=OBJECTID%3D58728&outFields=*&returnGeometry=true&outSR=4326&f=geojson), multipolígono público y aprobado, EPSG:4326, fechado el **14 de septiembre de 2026 a las 20:44 UTC**. Está dentro de las huellas de ambas escenas. Su fecha es anterior a la adquisición posterior; no se presenta como perímetro final ni como etiqueta píxel a píxel.
- **Severidad:** [RAVG](https://burnseverity.cr.usgs.gov/ravg/mapping-status) lista Plaskett como publicado, pero no se ha abierto ni verificado el producto individual. No bloquea el MVP.

### Antecedente científico

El [preprint de Döweler, Leuzinger y Bader](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7553393) (2 de octubre de 2026) analiza Plaskett y Timber con NISAR GCOV provisional HH/HV. Su AUC-ROC de **0,984** corresponde a su propia evaluación, **no a FireTrace**. No se verificaron los IDs usados por los autores; el gránulo posterior elegido aquí es posterior a la publicación.

---

## 6. Concepto funcional del producto

### Principio de diseño: tres niveles que no deben confundirse

```text
OBSERVACIÓN
  Cambio en retrodispersión SAR entre fechas
        ↓
INTERPRETACIÓN
  Cambio compatible con efectos de un incendio
        ↓
CONTRASTE
  Coincidencia / discrepancia con referencias externas
```

El MVP representa la observación y el contraste con capas y leyendas diferenciadas. La interpretación mediante una máscara de cambio destacado es opcional. **El perímetro oficial no es una prueba perfecta de cambio detectable en cada píxel**: puede incluir vegetación no quemada, distintos grados de afectación y fechas de evolución del incendio.

### Recorrido ideal del usuario

1. Entra en la página del caso de estudio.
2. Ve la localización, fechas y una explicación breve del fenómeno.
3. Abre el análisis e inspecciona las imágenes NISAR antes/después.
4. Activa **Observed radar changes** para ver la variación SAR.
5. Si está disponible, activa **Highlighted radar changes** para ver qué zonas superan el umbral exploratorio.
6. Superpone el **Official fire perimeter** y observa coincidencias y discrepancias.
7. Selecciona una región o píxel y abre el **Evidence Inspector**.
8. Consulta valores de radar, el criterio de detección, fuentes y limitaciones.
9. Extrae una conclusión matizada: qué áreas están respaldadas por la señal y cuáles precisan revisión adicional.

El recorrido de demo debe poder completarse en **aproximadamente 2 minutos**.

---

## 7. Pantallas y experiencia de usuario

### Pantalla 1 — Case Overview

**Objetivo:** contextualizar antes de interpretar.

Elementos:
- Nombre del incendio y mapa de localización.
- Fecha oficial de inicio y fechas exactas de observación NISAR.
- Resumen del problema y qué significa una observación SAR.
- Procedencia de los datos y aviso de carácter exploratorio.
- Acción principal: **Explore analysis**.

**No incluir:** buscador mundial, gestión de usuarios ni varios eventos en el MVP.

### Pantalla 2 — Fire Analysis

**Objetivo:** observar y contrastar el cambio.

Diseño previsto en escritorio:

```text
┌─────────────────────────────────────────────────────────────────┐
│ FireTrace | Plaskett Fire | Before: t1 | After: t2             │
├───────────────────────────────────────┬─────────────────────────┤
│                                       │  LAYERS                 │
│      MAP / BEFORE-AFTER VIEWER        │  □ SAR backscatter      │
│                                       │  □ Observed changes     │
│      [comparador / zoom / pan]        │  □ Highlighted change* │
│                                       │  □ Official perimeter   │
│                                       ├─────────────────────────┤
│                                       │  RESULTS                │
│                                       │  Valid data coverage    │
│                                       │  Area flagged (ha)*     │
│                                       │  Perimeter overlap*     │
├───────────────────────────────────────┴─────────────────────────┤
│ Select a highlighted region to inspect the evidence            │
└─────────────────────────────────────────────────────────────────┘
```

*Los elementos marcados con asterisco corresponden a la máscara exploratoria de P1.*

Interacciones principales:
- Desplazar y ampliar el mapa.
- Comparar las dos fechas en el mismo encuadre.
- Encender/apagar capas con leyendas claras.
- Seleccionar un píxel o una zona, incluso sin máscara de cambio.
- Mostrar estadísticas calculadas sobre los datos reales.

### Panel 3 — Evidence Inspector

**Objetivo:** explicar una detección, no solo mostrarla.

Datos por región seleccionada:
- Coordenadas o identificador de región.
- Fecha de cada observación y polarizaciones disponibles.
- Retrodispersión antes/después en HH y/o HV (dB, indicando la convención).
- Magnitud del cambio radar y método de cálculo.
- Si se habilita la máscara: indicar si el cambio supera el umbral, sin etiquetarlo como superficie quemada.
- Relación espacial con el perímetro oficial: dentro/fuera/solapamiento.
- Posibles explicaciones alternativas: humedad, geometría de observación, pendientes, rugosidad, estructura vegetal, otras perturbaciones.
- Estado de validación y fuentes utilizadas.

**Regla:** no mostrar confianza «97 %» si no procede de probabilidades calibradas y correctamente evaluadas. La explicación será derivada de los observables y reglas del método, **no inventada por un chatbot**.

---

## 8. Alcance y prioridades

### P0 — MVP obligatorio

| ID | Funcionalidad | Resultado esperado |
|---|---|---|
| F01 | Caso de estudio único | Evento, área, observaciones y fuentes documentadas |
| F02 | Visor georreferenciado | Datos NISAR visibles y navegables |
| F03 | Comparador antes/después | Misma zona, imágenes espacialmente coherentes |
| F04 | Mapa de cambios SAR | Cambio observado calculado, no inferido como fuego automáticamente |
| F06 | Perímetro de referencia | Capa GIS con fuente y fecha verificadas |
| F07 | Métricas descriptivas | Cobertura válida; superficie destacada y solapamiento solo si se activa F05 |
| F08 | Evidence Inspector | Valores de radar, criterio y limitaciones por selección |
| F09 | Proveniencia y cautelas | Productos NISAR identificados y advertencias visibles |

### P1 — Mejoras importantes si sobra tiempo

- **F05 — Máscara exploratoria de cambio destacado:** documentar el umbral y mostrar superficie y acuerdo espacial con el perímetro. No es una máscara validada de área quemada.

- Comparar un **baseline estadístico** con un **modelo de Computer Vision / Deep Learning**.
- Análisis de sensibilidad al umbral; no presentar métricas de clasificación como precisión de área quemada sin una referencia adecuada.
- Vista de cambios **HH vs HV** y sensibilidad a la polarización.
- Contraste adicional con **Sentinel-2 / dNBR** o **RAVG**, si se obtienen y verifican los productos adecuados.
- Exportar mapa y resumen como GeoJSON, GeoTIFF o CSV.
- Un segundo conjunto de imágenes del mismo evento para probar estabilidad.

### P2 — Fuera del hackathon

- Analizar cualquier incendio del planeta a demanda.
- Automatizar descarga y procesado de escenas arbitrarias.
- Seguimiento continuo o alertas en tiempo real.
- Evaluar recuperación ecológica plurianual.
- Estimar severidad del fuego con garantías operativas.
- Predicciones de futuros incendios o daños económicos.

---

## 9. Papel de Data Science, Computer Vision y Deep Learning

### Baseline imprescindible: detección de cambios SAR

Un primer método viable no requiere entrenar nada:

1. Leer el mismo recorte en los cuatro GeoTIFF GCOV; conservar la rejilla verificada.
2. Aplicar máscaras de datos inválidos y controlar las diferencias geométricas.
3. Convertir correctamente intensidades de potencia a dB (`10 × log10(valor)` para potencias positivas).
4. Calcular cambios antes/después en HH y HV.
5. Combinar **magnitudes absolutas** de cambio (aproximación *sign-agnostic*), siguiendo criterios científicamente documentados.
6. Mostrar el índice continuo. Solo en P1, probar suavizado y un umbral documentado para generar regiones de cambio destacado.
7. Si se habilita esa máscara, calcular su superficie sobre píxeles válidos y contrastarla con el perímetro.

El preprint de Timber/Plaskett describe un índice basado en **cambios absolutos log-ratio HH/HV**, una referencia previa al incendio, combinación de direcciones orbitales y normalización robusta. **Se trata de una referencia metodológica**, no de código ni resultados ya reproducidos por el equipo. Una versión simplificada podría trabajar con un par de observaciones; la metodología completa requiere más datos compatibles.

### Computer Vision: segmentación y análisis espacial

- Identificar regiones conectadas y eliminar ruido espurio.
- Comparar forma, tamaño y distribución de las regiones cambiadas.
- Evaluar similitud espacial con perímetros oficiales.
- Visualizar cambios destacados fuera del perímetro y zonas interiores sin cambios destacados, sin tratarlos automáticamente como errores.

### Deep Learning: línea experimental

**Objetivo posible:** una **Siamese U-Net** o una U-Net ligera que reciba bandas SAR antes/después y produzca una máscara de cambio compatible con área quemada.

**Riesgo principal:** el volumen de datos **NISAR etiquetados específicamente para incendios** no se ha verificado como suficiente para entrenar y validar un modelo generalizable. Los conjuntos de Sentinel-1 pueden servir para preentrenamiento o experimentos, pero NISAR (banda L) y Sentinel-1 (banda C) tienen respuestas físicas y polarizaciones diferentes (*domain shift*).

**Decisión de producto:** el modelo DL **no desbloquea el MVP**. Solo se incorpora a la demo si:
- Funciona sobre datos NISAR del caso real.
- Existe una evaluación honesta frente a un baseline.
- El tiempo de entrenamiento y depuración no compromete mapa, inspector y documentación.

Un resultado visualmente convincente **no equivale** a una validación rigurosa. Evitar separar entrenamiento y prueba por parches vecinos del mismo incendio como si fueran casos independientes.

---

## 10. Datos, licencias y dependencias

| Fuente | Función en FireTrace | Estado |
|---|---|---|
| **NISAR GCOV provisional (NASA/ASF)** | Dato principal de observación y detección | Par y cuatro GeoTIFF HH/HV descargados y verificados |
| **CAL FIRE** | Fechas, localización y descripción oficial del incendio | Verificado |
| **NIFC/WFIGS / ArcGIS** | Referencia espacial para contraste | Polígono 58728 aprobado, fechado el 14 de septiembre de 2026 |
| **USFS RAVG** | Contraste opcional de severidad o afectación de vegetación | Publicación anunciada; producto individual aún no verificado |
| **Sentinel-2 / Copernicus** | Contraste óptico/dNBR cuando sea posible | Fuente auxiliar propuesta, no procesada |
| **Sentinel-1 / datasets externos** | Desarrollo o preentrenamiento experimental DL | Uso potencial; no se ha demostrado transferencia |
| **DEM / máscaras topográficas** | Interpretar sombras radar, relieve y zonas inválidas | A concretar según escenas |

**Regla de conformidad con el reto:** los resultados principales y las visualizaciones científicas deben provenir de **NISAR**. Otros satélites son fuentes complementarias, no sustitutos.

**Flujo de datos verificado:** [Harmony](https://hyp3-docs.asf.alaska.edu/nisar-docs/harmony/) extrajo `HHHH` y `HVHV` como GeoTIFF de escena completa. El recorte espacial se leyó **localmente**; no se usó un recorte espacial de Harmony. Para la demo, precalcular los productos web a partir de esos archivos, sin autenticar ni descargar escenas en directo.

---

## 11. Evaluación y criterios científicos

### Qué evaluar

- **Reproducibilidad:** ¿podemos volver a generar el mapa continuo a partir de los productos identificados?
- **Coherencia temporal:** ¿las imágenes realmente cubren antes y después del incendio?
- **Coherencia geográfica:** ¿las capas comparten una cuadrícula y un área válida?
- **Acuerdo espacial:** si se habilita la máscara, medir intersección y unión (IoU) respecto al perímetro. Para evaluar capacidad de detectar área quemada se necesita una referencia independiente adecuada.
- **Discrepancias:** revisar ejemplos de cambio fuera del perímetro y de zonas interiores sin cambio destacado.
- **Sensibilidad:** efecto de polarización, umbral, suavizado y cambios de humedad.

### Cómo interpretar correctamente las cifras

- **Superficie con cambio destacado (ha)** mide qué extensión supera el umbral; no equivale a superficie quemada.
- **IoU frente a un perímetro oficial** mide acuerdo espacial con esa referencia, no precisión absoluta sobre severidad ecológica.
- **AUC-ROC 0,984 del estudio de Döweler et al.** es un resultado externo; nunca presentarlo como rendimiento propio.
- Un buen resultado en **un incendio** no demuestra generalización a otros lugares ni otras condiciones de vegetación.

### Criterios mínimos de aceptación

1. Hay al menos dos observaciones NISAR reales, con productos y fechas trazables.
2. Se verifican cobertura, polarización común y comparabilidad de adquisición (track/frame/dirección si procede).
3. Se usan los mismos píxeles válidos y un sistema de coordenadas coherente.
4. El usuario puede alternar las imágenes, el mapa continuo y el perímetro de forma independiente.
5. La capa de referencia es trazable y se conoce la fecha del perímetro.
6. Las métricas de cobertura excluyen datos inválidos; la superficie y el solapamiento se calculan solo si se habilita la máscara.
7. El inspector enseña valores calculados y el método real, no explicaciones ficticias.
8. La demo no depende de descargar gigabytes o entrenar una red en directo.
9. Se documentan discrepancias, limitaciones y casos en los que no se puede atribuir el cambio al fuego.
10. La entrega contiene fuentes NASA, metodología, limitaciones y uso declarado de herramientas de IA.

---

## 12. Organización y secuencia de desarrollo

### Reparto sugerido para seis integrantes

| Rol | Responsable de |
|---|---|
| 1. Datos NISAR | Inventario del par verificado, metadatos, recortes y productos web |
| 2. Procesamiento geoespacial | Alineación, reproyección, máscaras, polígonos |
| 3. CV / ML | Baseline SAR, segmentación y mejora DL opcional |
| 4. Evaluación científica | Referencias, métricas, pruebas de sensibilidad |
| 5. Aplicación / frontend | Mapa, comparación temporal, controles e inspector |
| 6. Integración y storytelling | Unión de piezas, UX, documentación y demo |

Los papeles pueden solaparse; todos deben poder ayudar a desbloquear el camino crítico.

### Secuencia del hackathon (propuesta)

1. **Inicio:** usar el par y el perímetro ya verificados, preparar los recortes locales y exportar capas ligeras.
2. **Primera mitad del sábado:** procesar y mostrar un mapa SAR y un primer índice de cambio.
3. **Final del sábado:** integrar mapa, capas y estadísticas; MVP funcional aunque todavía simple.
4. **Domingo por la mañana:** inspector de evidencias, pruebas y evaluación.
5. **Domingo por la tarde:** mejoras CV/DL solo si el producto funciona; grabación, documentación y entrega anticipada.

### Stack orientativo, **no decidido**

- **Datos SAR:** `earthaccess` o `asf_search`, `h5py`, `xarray`, `rasterio`.
- **Análisis:** `numpy`, `scipy`, `geopandas`, `shapely`, `scikit-image`, `scikit-learn`.
- **DL opcional:** PyTorch; GPU personal RTX 3060 o Kaggle T4 según disponibilidad.
- **Aplicación:** Streamlit + mapa o frontend React + servicio Python, según las habilidades reales del equipo.

Estos componentes no forman aún una arquitectura cerrada. Elegir el stack que permita integrar más rápido las capas precalculadas y el inspector.

---

## 13. Puerta de decisión del caso: *go / no-go*

### GO de datos para el MVP de cambio radar

- [x] **Escenas:** par del 16 de agosto y 3 de octubre, track 42, frame 70, descendente, con HH/HV en frecuencia A.
- [x] **Lectura:** cuatro GeoTIFF abiertos; rejilla común de 10 m y 1.948.374 píxeles válidos en las cuatro capas del recorte rectangular.
- [x] **Referencia:** geometría WFIGS 58728 leída y contrastada con las huellas; fecha de la geometría documentada.
- [ ] **Aceptación del prototipo:** generar el mapa continuo, comprobar su visualización y documentar coincidencias, discrepancias y factores de confusión. La lectura de píxeles no valida una detección de área quemada.
- [ ] **Solo si se amplía el alcance:** verificar el producto RAVG individual y sus fechas antes de afirmar que se ha evaluado severidad.

**Decisión:** no hace falta cambiar de incendio ni repetir la búsqueda del catálogo para empezar. La máscara exploratoria, la validación de severidad y el DL no forman parte del GO de datos.

---

## 14. Riesgos y mitigación

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Transferencias grandes o falta de acceso durante la demo | Retraso o fallo de la presentación | Usar el par ya descargado y servir capas ligeras precalculadas |
| Diferente track/ángulo/órbita | Cambios artificiales | Elegir geometría comparable y documentar diferencias |
| Respuesta SAR de signo distinto | Regla de umbral no generalizable | Comparar cambios de magnitud absoluta en HH/HV |
| Humedad, topografía y vegetación | Cambios difíciles de atribuir al fuego | Máscaras, referencias auxiliares e inspector de evidencia |
| Perímetro oficial imperfecto | Métricas engañosas | Evaluar como *acuerdo con la referencia*, no verdad absoluta |
| DL no transfiere Sentinel-1 → NISAR | Modelo inútil en el caso real | MVP basado en un baseline robusto; DL opcional |
| Demasiadas funciones | Proyecto incompleto | Un evento y un flujo de usuario; P0 antes que P1 |
| Sobreafirmaciones científicas | Pérdida de credibilidad | Lenguaje probabilístico y explicaciones basadas en observables |

---

## 15. Qué demostraría una buena entrega

**Demo en 90–120 segundos:**

1. «Estos son Plaskett, su localización y nuestras observaciones NISAR».
2. «Así cambia la señal radar entre ambas fechas».
3. «El mapa continuo muestra cuánto cambió la señal en HH y HV; un cambio grande no identifica por sí solo un píxel quemado».
4. «Superponemos el perímetro oficial y examinamos coincidencias y discrepancias».
5. «Al seleccionar una zona, mostramos los valores de ambas fechas y los límites de la interpretación».

### Resultado esperado al acabar el hackathon

Un **prototipo interactivo** que incluya caso real, visor, comparación temporal, mapa continuo de cambio, perímetro oficial, métricas descriptivas, inspector de evidencia y documentación reproducible.

### Criterio de éxito del proyecto

> **FireTrace tiene éxito si alguien puede examinar un incendio real, entender qué detectó NISAR, contrastarlo con una referencia y saber en qué puede confiar y en qué no, sin necesidad de interpretar archivos SAR directamente.**

---

## 16. Decisiones pendientes de implementación

1. ¿Qué formato de capas precalculadas permite una demo fluida y conserva valores consultables en el inspector?
2. ¿Qué escala de color facilita comparar el cambio continuo sin exagerarlo?
3. Solo para P1: ¿qué umbral y suavizado son defendibles? ¿Se puede verificar RAVG u otra referencia independiente?

La selección del caso, las escenas, la rejilla y la referencia espacial ya no bloquean la implementación.

---

## 17. Referencias y recursos

### Reto, misión y datos

- [NASA Space Apps 2026 — Challenges](https://www.spaceappschallenge.org/2026/challenges/)
- [NASA/ASF — NISAR GCOV Data User Guide](https://nisar-docs.asf.alaska.edu/gcov/)
- [NASA/ASF — Accessing NISAR Data](https://nisar-docs.asf.alaska.edu/access-overview/)
- [NASA/ASF — Find NISAR Data with Vertex](https://nisar-docs.asf.alaska.edu/vertex/)
- [NASA/ASF — Harmony: extracción de capas y recortes](https://nisar-docs.asf.alaska.edu/harmony/)
- [NASA Earthdata CMR — colecciones ASF](https://cmr.earthdata.nasa.gov/search/site/collections/directory/ASF/gov.nasa.eosdis)
- [ASF Vertex](https://search.asf.alaska.edu/)
- [NASA Earthdata Login](https://urs.earthdata.nasa.gov/)

### Incendios y validación

- [CAL FIRE — Plaskett Fire](https://www.fire.ca.gov/incidents/2026/8/26/plaskett-fire)
- [Plaskett — ArcGIS NIFC FeatureServer](https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/NIFC_FS_Plaskett_2026_CALPF_002475/FeatureServer)
- [NIFC Open Data](https://data-nifc.opendata.arcgis.com/)

### Investigación de referencia

- [Döweler, Leuzinger y Bader (2026) — *Sign-agnostic L-band radar change detection maps wildfire burnscars: a first evaluation of NISAR over the 2026 Big Sur fires in California* (SSRN, preprint)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7553393)

---

*Propuesta con datos del caso verificados; no describe un producto ya implementado ni una validación de área quemada o severidad. Revisar las reglas oficiales antes de la entrega.*
