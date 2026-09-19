# Routing service

`engine.py` owns deterministic graph consequences for the MVP. It converts a
flood frame and optional injected events into edge states, builds a traversable
graph, computes shortest safe paths, reports shelter and hospital access
separately, and calculates baseline time-to-isolation.

The service uses explicit node IDs from `road-network.geojson`. Map geometry and
display names never establish connectivity.
