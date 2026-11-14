# Nivel 2 — plan de reparto

Código que genera `nivel-2/rutas.json`: el recorrido de las tres camionetas de
La Palanca para los 80 pedidos del lote, con la menor distancia total que
encontramos cumpliendo las reglas de `operacion.json`.

## Archivos

- `mapa.py` — lee `siracusa.osm` y calcula el camino mínimo entre dos nodos.
- `planificar.py` — arma el plan y escribe `nivel-2/rutas.json`.
- `validar.py` — controla el `rutas.json` ya escrito. No comparte código con
  los otros dos: recalcula todo por su cuenta.

## Uso

Requiere Python 3.10 o superior. No usa paquetes externos: sólo la biblioteca
estándar. Se corre desde la raíz del repositorio:

```bash
python3 nivel-2/codigo/planificar.py   # genera nivel-2/rutas.json
python3 nivel-2/codigo/validar.py      # controla el archivo generado
```

Los datos se leen de `datos/` (catálogo y padrón del nivel 1) y de
`datos/nivel-2/` (pedidos, flota, operación y mapa).

Opciones de `planificar.py`: `--semillas` (corridas independientes, 8 por
defecto), `--iteraciones` (cambios probados por corrida, 3.000.000 por
defecto) y `--procesos` (procesos en paralelo). Con los valores por defecto
tarda alrededor de un minuto y medio en 8 núcleos. Las semillas son fijas
(1 a 8), así que repetir la corrida da el mismo plan.

## Cómo se aplican las reglas

- **Mapa.** Cada `way` es una arista con su largo en `distancia_m`. El sentido
  sale de `oneway` (`yes`, `-1` o `no`) y las aristas con `access=no` se
  descartan.
- **Tiempo de una arista.** `ceil(distancia_m * 3.6 / velocidad_kmh)`, con la
  velocidad del tipo de calle; se suman segundos enteros arista por arista.
- **Recorrido entre dos puntos.** Camino de menor distancia dirigida y, entre
  los que empatan, el de menor tiempo (Dijkstra comparando el par
  distancia, tiempo).
- **Franjas.** La descarga completa queda dentro de la franja: el inicio va
  entre `desde` y `hasta − descarga_segundos`.
- **Espera.** Si la camioneta llega antes de que abra la franja, espera en el
  lugar. Nunca espera en otro momento: la vuelta al depósito es directa.
- **Viajes.** Cada camioneta sale una vez del depósito y vuelve, dentro de su
  horario (`desde` / `hasta` de `flota.json`), sin recargar ni dividir pedidos.
- **Carga.** Los kg y m3 de cada pedido salen del catálogo (cantidad × valor
  por unidad, envases incluidos) y la suma de cada camioneta no supera su
  capacidad. Las cuentas se hacen con enteros exactos, sin coma flotante.
- **Datos de entrada.** Antes de planificar se controla que cada dirección
  coincida con el padrón y que las cantidades respeten el catálogo.

## Método

1. Matriz de distancias y tiempos entre el depósito y los 80 pedidos.
2. Plan inicial por inserción: los pedidos entran por orden de franja en la
   posición que menos cuesta.
3. Recocido simulado: prueba millones de cambios chicos (mover un pedido,
   intercambiar dos, invertir un tramo, mover un tramo de 2 o 3 pedidos,
   cruzar dos rutas). Durante la búsqueda, un plan que rompe una franja, un
   horario o una capacidad se penaliza en lugar de descartarse, para poder
   atravesar planes inválidos camino a uno mejor. Sólo se guarda como
   resultado un plan que cumple todo.
4. Se corren varias semillas en paralelo y se toma la de menor distancia.
5. Búsqueda local exhaustiva sobre ese plan y control final de todas las
   condiciones antes de escribir el archivo.

El objetivo que se minimiza es la distancia total, incluidas las salidas y los
regresos al depósito.
