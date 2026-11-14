Reciben `pedidos.json`, `siracusa.osm`, `flota.json` y `operacion.json`. Usen también el catálogo y el padrón anteriores. Este lote reemplaza al anterior; no sumen sus pedidos. El archivo de operación define cómo se calcula un recorrido sobre el mapa y las condiciones de la jornada.

Suban `nivel-2/rutas.json` y el código utilizado en `nivel-2/codigo/`, junto con las instrucciones de uso. Se admiten `.py`, `.js`, `.ts`, `.r` e `.ipynb`. El juez lee el código; no lo ejecuta. No incluyan entornos virtuales, paquetes instalados, modelos ni credenciales.

El JSON es un objeto con una única clave `rutas`, cuyo valor es una lista con una fila por vehículo de la flota. Cada fila tiene exactamente los campos del siguiente formato:

```json
{
  "vehiculo": "VX",
  "salida": "HH:MM:SS",
  "paradas": [{"pedido": "P2-XXX", "inicio": "HH:MM:SS"}],
  "regreso": "HH:MM:SS"
}
```

`salida` es la hora de salida del depósito; `inicio`, el comienzo de la descarga de ese pedido; `regreso`, la llegada al depósito. Las paradas van en orden de ejecución. Una camioneta sin pedidos lleva `paradas: []`. Cada pedido se entrega una sola vez y completo. Usen los identificadores recibidos y horas locales de la misma jornada. No incluyan distancias declaradas, caminos alternativos ni otros campos: el juez calcula cada tramo sobre el mapa recibido.

El plan debe cumplir las condiciones de los archivos y su distancia total no puede superar en más de 10 % la del plan de la organización. Los kilómetros incluyen todas las salidas y los regresos.
