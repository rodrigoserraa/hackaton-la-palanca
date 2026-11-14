"""Arma el plan de reparto del nivel 2 y escribe nivel-2/rutas.json.

Pasos:
1. Lee pedidos, flota, reglas de operación, catálogo y padrón.
2. Calcula distancia y tiempo entre el depósito y cada pedido sobre el mapa
   (ver mapa.py).
3. Busca el reparto de menor distancia total con recocido simulado: parte de
   un plan armado por inserción y prueba cambios chicos (mover un pedido,
   intercambiar dos, invertir un tramo, cruzar dos rutas). Los planes que
   rompen una franja, un horario de chofer o una capacidad se penalizan, y
   sólo se guarda como resultado un plan que cumple todo.
4. Pule el mejor plan con una búsqueda local exhaustiva, lo vuelve a controlar
   contra todas las condiciones y lo escribe.

Uso: python3 nivel-2/codigo/planificar.py  (ver README.md)
"""

import argparse
import csv
import json
import math
import random
from fractions import Fraction
from multiprocessing import Pool
from pathlib import Path
from types import SimpleNamespace

from mapa import build_matrices, load_graph

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datos"
OUTPUT = ROOT / "nivel-2" / "rutas.json"

# Carga en millonésimas de kg y de m3: enteros exactos, sin coma flotante.
LOAD_UNIT = 10**6
# Penalidades de la búsqueda, expresadas en metros.
LATE_WEIGHT = 5  # por cada segundo fuera de franja o de horario del chofer
LOAD_WEIGHT = 20000  # por cada 100 % de capacidad excedida
TEMPERATURE_START = 300.0
TEMPERATURE_END = 1.0


def to_seconds(clock):
    hours, minutes, seconds = map(int, clock.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def to_clock(seconds):
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def exact_units(value):
    """Pasa un número del JSON a millonésimas enteras, sin redondear."""
    units = Fraction(str(value)) * LOAD_UNIT
    if units.denominator != 1:
        raise ValueError(f"{value} tiene más precisión de la esperada")
    return int(units)


def load_problem():
    """Junta todos los datos en una estructura lista para la búsqueda.

    El índice 0 es el depósito; el pedido i de la lista ocupa el índice i + 1.
    """
    operation = read_json(DATA / "nivel-2" / "operacion.json")
    orders = read_json(DATA / "nivel-2" / "pedidos.json")
    fleet = read_json(DATA / "nivel-2" / "flota.json")
    catalog = {p["producto"]: p for p in read_json(DATA / "catalogo.json")}
    with open(DATA / "padron.csv", encoding="utf-8", newline="") as handle:
        padron = {(r["calle"], int(r["altura"])): int(r["nodo"]) for r in csv.DictReader(handle)}

    earliest, latest_start, service, kg, m3 = [0], [0], [0], [0], [0]
    for order in orders:
        address = order["direccion"]
        if padron.get((address["calle"], address["altura"])) != address["nodo"]:
            raise ValueError(f"{order['pedido']}: la dirección no coincide con el padrón")

        order_kg = order_m3 = Fraction(0)
        for item in order["items"]:
            product = catalog[item["producto"]]
            quantity = Fraction(str(item["cantidad"]))
            if quantity <= 0 or (not product["fraccionable"] and quantity.denominator != 1):
                raise ValueError(f"{order['pedido']}: cantidad inválida de {item['producto']}")
            order_kg += quantity * Fraction(str(product["kg"]))
            order_m3 += quantity * Fraction(str(product["m3"]))

        window_start = to_seconds(order["franja"]["desde"])
        window_end = to_seconds(order["franja"]["hasta"])
        unload = order["descarga_segundos"]
        if window_end - window_start < unload:
            raise ValueError(f"{order['pedido']}: la descarga no entra en la franja")
        earliest.append(window_start)
        # La descarga completa debe quedar dentro de la franja.
        latest_start.append(window_end - unload)
        service.append(unload)
        kg.append(exact_units(order_kg))
        m3.append(exact_units(order_m3))

    graph = load_graph(DATA / "nivel-2" / "siracusa.osm", operation["velocidades_kmh"])
    nodes = [operation["deposito"]] + [order["direccion"]["nodo"] for order in orders]
    dist, time = build_matrices(graph, nodes)

    vehicles = [
        SimpleNamespace(
            name=v["vehiculo"],
            start=to_seconds(v["desde"]),
            end=to_seconds(v["hasta"]),
            cap_kg=exact_units(v["capacidad_kg"]),
            cap_m3=exact_units(v["capacidad_m3"]),
        )
        for v in fleet
    ]
    return SimpleNamespace(
        orders=orders, vehicles=vehicles, dist=dist, time=time, earliest=earliest,
        latest_start=latest_start, service=service, kg=kg, m3=m3,
    )


def evaluate(problem, vehicle, route):
    """Devuelve (metros, segundos de atraso, exceso de carga) de una ruta.

    El vehículo sale a su hora de inicio, llega lo antes posible a cada parada
    y espera si la franja todavía no abrió. Si llega tarde, se cuenta el
    atraso y se sigue como si hubiera empezado en el último segundo válido,
    para que un solo atraso no se propague a toda la ruta.
    """
    dist, time = problem.dist, problem.time
    earliest, latest_start, service = problem.earliest, problem.latest_start, problem.service
    clock, previous, meters, late, kg, m3 = vehicle.start, 0, 0, 0, 0, 0
    for stop in route:
        meters += dist[previous][stop]
        clock += time[previous][stop]
        if clock < earliest[stop]:
            clock = earliest[stop]
        elif clock > latest_start[stop]:
            late += clock - latest_start[stop]
            clock = latest_start[stop]
        clock += service[stop]
        kg += problem.kg[stop]
        m3 += problem.m3[stop]
        previous = stop
    meters += dist[previous][0]
    clock += time[previous][0]
    if clock > vehicle.end:
        late += clock - vehicle.end
    overload = max(0, kg - vehicle.cap_kg) / vehicle.cap_kg + max(0, m3 - vehicle.cap_m3) / vehicle.cap_m3
    return meters, late, overload


def score(problem, vehicle_index, route):
    """(costo penalizado, metros, ¿cumple todo?) de una ruta."""
    meters, late, overload = evaluate(problem, problem.vehicles[vehicle_index], route)
    return meters + LATE_WEIGHT * late + LOAD_WEIGHT * overload, meters, late == 0 and overload == 0


def build_initial(problem):
    """Plan inicial: inserta los pedidos por orden de franja donde menos cueste."""
    routes = [[] for _ in problem.vehicles]
    stops = sorted(range(1, len(problem.dist)), key=lambda s: (problem.earliest[s], s))
    for stop in stops:
        best = None
        for v, route in enumerate(routes):
            base = score(problem, v, route)[0]
            for position in range(len(route) + 1):
                candidate = route[:position] + [stop] + route[position:]
                extra = score(problem, v, candidate)[0] - base
                if best is None or extra < best[0]:
                    best = (extra, v, candidate)
        routes[best[1]] = best[2]
    return routes


def locate(routes, index):
    """Ubica el pedido número `index` contando a lo largo de todas las rutas."""
    for v, route in enumerate(routes):
        if index < len(route):
            return v, index
        index -= len(route)
    raise IndexError(index)


def propose(rng, routes, total_stops):
    """Devuelve un cambio al azar como {vehículo: ruta nueva}, o None."""
    kind = rng.random()
    v1, i = locate(routes, rng.randrange(total_stops))
    r1 = routes[v1]

    if kind < 0.30:  # mover un pedido a otra posición o a otra camioneta
        v2 = rng.randrange(len(routes))
        rest = r1[:i] + r1[i + 1:]
        target = rest if v2 == v1 else routes[v2]
        j = rng.randrange(len(target) + 1)
        moved = target[:j] + [r1[i]] + target[j:]
        return {v1: moved} if v2 == v1 else {v1: rest, v2: moved}

    if kind < 0.50:  # intercambiar dos pedidos
        v2, j = locate(routes, rng.randrange(total_stops))
        if (v1, i) == (v2, j):
            return None
        new1 = list(r1)
        new2 = new1 if v2 == v1 else list(routes[v2])
        new1[i], new2[j] = new2[j], new1[i]
        return {v1: new1} if v2 == v1 else {v1: new1, v2: new2}

    if kind < 0.65:  # invertir un tramo dentro de una ruta
        j = rng.randrange(len(r1))
        if i == j:
            return None
        i, j = min(i, j), max(i, j)
        return {v1: r1[:i] + r1[i:j + 1][::-1] + r1[j + 1:]}

    if kind < 0.85:  # mover un tramo de 2 o 3 pedidos seguidos
        segment = r1[i:i + rng.choice((2, 3))]
        if rng.random() < 0.5:
            segment = segment[::-1]
        rest = r1[:i] + r1[i + len(segment):]
        v2 = rng.randrange(len(routes))
        target = rest if v2 == v1 else routes[v2]
        j = rng.randrange(len(target) + 1)
        moved = target[:j] + segment + target[j:]
        return {v1: moved} if v2 == v1 else {v1: rest, v2: moved}

    # cruzar dos rutas: cada camioneta sigue con el final de la otra
    v2 = rng.randrange(len(routes))
    if v2 == v1:
        return None
    r2 = routes[v2]
    j = rng.randrange(len(r2) + 1)
    return {v1: r1[:i] + r2[j:], v2: r2[:j] + r1[i:]}


def anneal(task):
    """Recocido simulado con una semilla. Devuelve (metros, semilla, rutas)."""
    problem, seed, iterations = task
    rng = random.Random(seed)
    routes = build_initial(problem)
    scores = [score(problem, v, route) for v, route in enumerate(routes)]
    total_stops = len(problem.dist) - 1
    best_meters, best_routes = math.inf, None
    cooling = TEMPERATURE_END / TEMPERATURE_START

    for step in range(iterations):
        change = propose(rng, routes, total_stops)
        if change is None:
            continue
        new_scores = {v: score(problem, v, route) for v, route in change.items()}
        delta = sum(s[0] for s in new_scores.values()) - sum(scores[v][0] for v in change)
        temperature = TEMPERATURE_START * cooling ** (step / iterations)
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            for v, route in change.items():
                routes[v] = route
                scores[v] = new_scores[v]
            if delta < 0 and all(s[2] for s in scores):
                meters = sum(s[1] for s in scores)
                if meters < best_meters:
                    best_meters, best_routes = meters, [list(r) for r in routes]
    return best_meters, seed, best_routes


def neighbors(routes):
    """Todos los vecinos por mover un pedido, intercambiar dos o invertir un tramo."""
    for v1, r1 in enumerate(routes):
        for i in range(len(r1)):
            rest = r1[:i] + r1[i + 1:]
            for v2, r2 in enumerate(routes):
                target = rest if v2 == v1 else r2
                for j in range(len(target) + 1):
                    moved = target[:j] + [r1[i]] + target[j:]
                    yield {v1: moved} if v2 == v1 else {v1: rest, v2: moved}
                for j in range(len(r2)):
                    if v2 == v1 and j > i:
                        swapped = list(r1)
                        swapped[i], swapped[j] = swapped[j], swapped[i]
                        yield {v1: swapped}
                        yield {v1: r1[:i] + r1[i:j + 1][::-1] + r1[j + 1:]}
                    elif v2 > v1:
                        new1, new2 = list(r1), list(r2)
                        new1[i], new2[j] = new2[j], new1[i]
                        yield {v1: new1, v2: new2}


def polish(problem, routes):
    """Búsqueda local: aplica mejoras válidas hasta que no quede ninguna."""
    improved = True
    while improved:
        improved = False
        for change in neighbors(routes):
            new_scores = {v: score(problem, v, route) for v, route in change.items()}
            if not all(s[2] for s in new_scores.values()):
                continue
            saved = sum(score(problem, v, routes[v])[1] for v in change) - sum(s[1] for s in new_scores.values())
            if saved > 0:
                for v, route in change.items():
                    routes[v] = route
                improved = True
                break
    return routes


def schedule(problem, vehicle, route):
    """Horarios de una ruta: (salida, [inicio de cada descarga], regreso).

    Cada descarga empieza apenas se puede (llegada o apertura de la franja).
    La salida se fija justo para llegar al primer cliente a su hora de inicio,
    así la camioneta no espera en la calle antes de la primera entrega.
    """
    if not route:
        return vehicle.start, [], vehicle.start
    clock, previous, starts = vehicle.start, 0, []
    for stop in route:
        clock = max(clock + problem.time[previous][stop], problem.earliest[stop])
        starts.append(clock)
        clock += problem.service[stop]
        previous = stop
    departure = starts[0] - problem.time[0][route[0]]
    return departure, starts, clock + problem.time[previous][0]


def check_plan(problem, routes):
    """Control final de todas las condiciones antes de escribir el archivo."""
    delivered = sorted(stop for route in routes for stop in route)
    assert delivered == list(range(1, len(problem.dist))), "cada pedido debe entregarse una sola vez"
    for vehicle, route in zip(problem.vehicles, routes):
        departure, starts, back = schedule(problem, vehicle, route)
        assert vehicle.start <= departure and back <= vehicle.end, f"{vehicle.name}: fuera de horario"
        assert sum(problem.kg[s] for s in route) <= vehicle.cap_kg, f"{vehicle.name}: exceso de kg"
        assert sum(problem.m3[s] for s in route) <= vehicle.cap_m3, f"{vehicle.name}: exceso de m3"
        clock, previous = departure, 0
        for stop, start in zip(route, starts):
            assert start >= clock + problem.time[previous][stop], "se llega después del inicio"
            assert problem.earliest[stop] <= start <= problem.latest_start[stop], "descarga fuera de franja"
            clock, previous = start + problem.service[stop], stop


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--semillas", type=int, default=8, help="corridas independientes (default 8)")
    parser.add_argument("--iteraciones", type=int, default=3_000_000, help="cambios probados por corrida")
    parser.add_argument("--procesos", type=int, default=None, help="procesos en paralelo (default: todos)")
    args = parser.parse_args()

    problem = load_problem()
    tasks = [(problem, seed, args.iteraciones) for seed in range(1, args.semillas + 1)]
    with Pool(args.procesos) as pool:
        results = pool.map(anneal, tasks)
    for meters, seed, _ in results:
        print(f"semilla {seed}: {meters / 1000:.3f} km")
    feasible = [r for r in results if r[2] is not None]
    if not feasible:
        raise SystemExit("ninguna corrida encontró un plan que cumpla todo")
    # Menor distancia; ante empate, la semilla más baja (resultado reproducible).
    routes = polish(problem, min(feasible)[2])
    check_plan(problem, routes)

    plan, total = [], 0
    for vehicle, route in zip(problem.vehicles, routes):
        departure, starts, back = schedule(problem, vehicle, route)
        meters = evaluate(problem, vehicle, route)[0]
        total += meters
        plan.append({
            "vehiculo": vehicle.name,
            "salida": to_clock(departure),
            "paradas": [
                {"pedido": problem.orders[stop - 1]["pedido"], "inicio": to_clock(start)}
                for stop, start in zip(route, starts)
            ],
            "regreso": to_clock(back),
        })
        print(
            f"{vehicle.name}: {len(route)} pedidos, {meters / 1000:.3f} km, "
            f"{sum(problem.kg[s] for s in route) / LOAD_UNIT:.2f} kg, "
            f"{sum(problem.m3[s] for s in route) / LOAD_UNIT:.3f} m3, "
            f"{to_clock(departure)} a {to_clock(back)}"
        )
    print(f"total: {total / 1000:.3f} km")

    OUTPUT.write_text(json.dumps({"rutas": plan}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"escrito {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
