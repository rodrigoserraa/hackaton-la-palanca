"""Controla nivel-2/rutas.json contra el enunciado y los archivos recibidos.

No comparte código con planificar.py ni con mapa.py: vuelve a leer el mapa,
recalcula cada tramo y revisa el plan tal como quedó escrito. Sirve como
segunda opinión antes de entregar.

Uso: python3 nivel-2/codigo/validar.py [ruta/a/rutas.json]
"""

import heapq
import json
import re
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datos"
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$")
# Clave única para "menor distancia, empate por menor tiempo": la distancia
# pesa más que cualquier tiempo posible (una jornada tiene 86.400 s).
TIE_BASE = 10**7


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def seconds(clock):
    assert CLOCK.match(clock), f"hora mal escrita: {clock!r}"
    h, m, s = map(int, clock.split(":"))
    return h * 3600 + m * 60 + s


def read_map(operation):
    """Aristas transitables como {nodo: [(vecino, clave)]}, clave = metros * TIE_BASE + segundos."""
    speeds = operation["velocidades_kmh"]
    edges = {}
    for way in ET.parse(DATA / "nivel-2" / "siracusa.osm").getroot().iter("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        if tags["access"] == "no":
            continue
        a, b = (int(nd.get("ref")) for nd in way.findall("nd"))
        meters, speed = int(tags["distancia_m"]), int(speeds[tags["highway"]])
        # ceil(metros * 3.6 / velocidad) con enteros: 3.6 = 18 / 5.
        key = meters * TIE_BASE - (-(meters * 18) // (5 * speed))
        if tags["oneway"] in ("yes", "no"):
            edges.setdefault(a, []).append((b, key))
        if tags["oneway"] in ("-1", "no"):
            edges.setdefault(b, []).append((a, key))
    return edges


def leg(edges, cache, origin, target):
    """(metros, segundos) del tramo origen -> destino."""
    if origin not in cache:
        best, heap = {origin: 0}, [(0, origin)]
        while heap:
            key, node = heapq.heappop(heap)
            if key > best[node]:
                continue
            for neighbor, edge_key in edges.get(node, ()):
                if key + edge_key < best.get(neighbor, float("inf")):
                    best[neighbor] = key + edge_key
                    heapq.heappush(heap, (key + edge_key, neighbor))
        cache[origin] = best
    return divmod(cache[origin][target], TIE_BASE)


def main():
    plan_path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "nivel-2" / "rutas.json"
    plan = read_json(plan_path)
    operation = read_json(DATA / "nivel-2" / "operacion.json")
    orders = {o["pedido"]: o for o in read_json(DATA / "nivel-2" / "pedidos.json")}
    fleet = read_json(DATA / "nivel-2" / "flota.json")
    catalog = {p["producto"]: p for p in read_json(DATA / "catalogo.json")}
    edges, cache, depot = read_map(operation), {}, operation["deposito"]

    assert list(plan) == ["rutas"], "el JSON debe tener sólo la clave rutas"
    assert [r["vehiculo"] for r in plan["rutas"]] == [v["vehiculo"] for v in fleet], "una fila por vehículo"

    delivered, total_meters = [], 0
    for row, vehicle in zip(plan["rutas"], fleet):
        name = row["vehiculo"]
        assert list(row) == ["vehiculo", "salida", "paradas", "regreso"], f"{name}: campos"
        clock = seconds(row["salida"])
        assert clock >= seconds(vehicle["desde"]), f"{name}: sale antes de su horario"

        node, meters, kg, m3 = depot, 0, Decimal(0), Decimal(0)
        for stop in row["paradas"]:
            assert list(stop) == ["pedido", "inicio"], f"{name}: campos de parada"
            order = orders[stop["pedido"]]
            delivered.append(stop["pedido"])
            leg_meters, leg_seconds = leg(edges, cache, node, order["direccion"]["nodo"])
            start = seconds(stop["inicio"])
            assert start >= clock + leg_seconds, f"{stop['pedido']}: empieza antes de llegar"
            assert start >= seconds(order["franja"]["desde"]), f"{stop['pedido']}: antes de la franja"
            clock = start + order["descarga_segundos"]
            assert clock <= seconds(order["franja"]["hasta"]), f"{stop['pedido']}: la descarga se pasa de la franja"
            for item in order["items"]:
                product = catalog[item["producto"]]
                quantity = Decimal(str(item["cantidad"]))
                kg += quantity * Decimal(str(product["kg"]))
                m3 += quantity * Decimal(str(product["m3"]))
            meters += leg_meters
            node = order["direccion"]["nodo"]

        back_meters, back_seconds = leg(edges, cache, node, depot)
        meters += back_meters
        # Sólo se puede esperar antes de una descarga: la vuelta es directa.
        assert seconds(row["regreso"]) == clock + back_seconds, f"{name}: regreso no coincide con el recorrido"
        assert seconds(row["regreso"]) <= seconds(vehicle["hasta"]), f"{name}: vuelve fuera de horario"
        assert kg <= Decimal(str(vehicle["capacidad_kg"])), f"{name}: exceso de kg"
        assert m3 <= Decimal(str(vehicle["capacidad_m3"])), f"{name}: exceso de m3"
        total_meters += meters
        print(f"{name}: {len(row['paradas'])} pedidos, {meters / 1000:.3f} km, {kg} kg, {m3} m3, "
              f"{row['salida']} a {row['regreso']}")

    assert sorted(delivered) == sorted(orders), "cada pedido debe entregarse exactamente una vez"
    print(f"total: {total_meters / 1000:.3f} km — plan válido")


if __name__ == "__main__":
    main()
