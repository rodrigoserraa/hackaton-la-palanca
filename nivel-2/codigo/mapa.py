"""Mapa de Siracusa: lectura del .osm y camino mínimo según operacion.json.

Reglas aplicadas (operacion.json):
- recorrido: menor distancia dirigida; ante empate, menor tiempo.
- access=no no es transitable.
- tiempo de cada arista: ceil(distancia_m * 3.6 / velocidad_kmh), en segundos
  enteros que se suman arista por arista.
"""

import heapq
import math
import xml.etree.ElementTree as ET
from fractions import Fraction


def load_graph(osm_path, speeds_kmh):
    """Lee el .osm y devuelve {nodo: [(vecino, distancia_m, segundos), ...]}.

    Cada <way> del plano es una sola arista entre dos nodos y trae su largo en
    la etiqueta `distancia_m`. El sentido sale de `oneway`:
    yes = del primer nodo al segundo, -1 = al revés, no = doble mano.
    """
    root = ET.parse(osm_path).getroot()
    graph = {int(node.get("id")): [] for node in root.iter("node")}

    for way in root.iter("way"):
        refs = [int(nd.get("ref")) for nd in way.findall("nd")]
        tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
        if len(refs) != 2:
            raise ValueError(f"way {way.get('id')}: se esperaban 2 nodos")
        if tags["access"] == "no":
            continue

        # Fraction evita errores de coma flotante en el ceil() del tiempo.
        distance = Fraction(tags["distancia_m"])
        speed = Fraction(str(speeds_kmh[tags["highway"]]))
        seconds = math.ceil(distance * Fraction(36, 10) / speed)
        if distance.denominator == 1:
            distance = int(distance)

        a, b = refs
        oneway = tags["oneway"]
        if oneway in ("yes", "no"):
            graph[a].append((b, distance, seconds))
        if oneway in ("-1", "no"):
            graph[b].append((a, distance, seconds))
        if oneway not in ("yes", "no", "-1"):
            raise ValueError(f"way {way.get('id')}: oneway desconocido {oneway!r}")
    return graph


def shortest_from(graph, source):
    """Dijkstra lexicográfico desde `source`.

    Devuelve {nodo: (distancia_m, segundos)} donde la distancia es la mínima
    dirigida y los segundos son los del camino más rápido entre los que
    empatan en distancia. Comparar las tuplas (distancia, segundos) resuelve
    el empate tal como lo pide la regla de recorrido.
    """
    best = {source: (0, 0)}
    heap = [(0, 0, source)]
    while heap:
        distance, seconds, node = heapq.heappop(heap)
        if (distance, seconds) > best[node]:
            continue
        for neighbor, edge_distance, edge_seconds in graph[node]:
            candidate = (distance + edge_distance, seconds + edge_seconds)
            if neighbor not in best or candidate < best[neighbor]:
                best[neighbor] = candidate
                heapq.heappush(heap, (candidate[0], candidate[1], neighbor))
    return best


def build_matrices(graph, nodes):
    """Matrices de distancia y tiempo entre los nodos pedidos (en ese orden)."""
    distances, times = [], []
    for origin in nodes:
        reach = shortest_from(graph, origin)
        missing = [n for n in nodes if n not in reach]
        if missing:
            raise ValueError(f"desde el nodo {origin} no se llega a {missing}")
        distances.append([reach[n][0] for n in nodes])
        times.append([reach[n][1] for n in nodes])
    return distances, times
