"""Phase 5 — Resilience routing.

Three modules:
  * ``circuit_breaker``  — Redis-backed sliding window per provider.
  * ``provider_router``  — fallback chain assembly. Asks the breaker
                            which providers are available; never
                            implements breaker logic itself.
  * ``health_probes``    — Celery Beat task that pings each provider
                            on a schedule and feeds the breaker on
                            failure.
"""
