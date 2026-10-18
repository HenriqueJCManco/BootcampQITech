from datetime import timedelta

from domain.entities import RuleHit
from domain.facts import KNOWN, MATURING, UNKNOWN, Facts
from domain.statistics import haversine_km, median


def first_band(value: float, bands: list[dict], key: str, compare) -> dict | None:
    for band in bands:
        if compare(value, band[key]):
            return band
    return None


def d1_device_stage(facts: Facts) -> RuleHit | None:
    stage = facts.device_stage
    if stage is None or facts.is_cold_start:
        return None
    params = facts.config.rule("D1")
    points = {UNKNOWN: params["pontos_desconhecido"], MATURING: params["pontos_maturando"], KNOWN: 0}[stage]
    if points == 0:
        return None
    return RuleHit("D1", points, {"device_stage": stage})


def d3_cold_start(facts: Facts) -> RuleHit | None:
    if not facts.is_cold_start:
        return None
    return RuleHit("D3", facts.config.rule("D3")["pontos"], {"previous_pix": 0})


def d2_shared_device(facts: Facts) -> RuleHit | None:
    if facts.pix.device_id is None:
        return None
    params = facts.config.rule("D2")
    documents = facts.context.device.distinct_payers_7d
    if documents < params["min_documentos"]:
        return None
    return RuleHit("D2", params["pontos"], {"documents_7d": documents})


def _past_locations(facts: Facts, days: int):
    return [pix for pix in facts.history_since(timedelta(days=days)) if pix.geolocation is not None]


def g1_distance_from_usual(facts: Facts) -> RuleHit | None:
    location = facts.pix.geolocation
    if location is None:
        facts.missing("geolocation")
        return None
    params = facts.config.rule("G1")
    past = _past_locations(facts, params["janela_dias"])
    if len(past) < params["min_pontos"]:
        return None

    center_latitude = median([pix.geolocation.latitude for pix in past])
    center_longitude = median([pix.geolocation.longitude for pix in past])
    distance = haversine_km(center_latitude, center_longitude, location.latitude, location.longitude)
    band = first_band(distance, params["faixas"], "acima_km", lambda value, limit: value > limit)
    if band is None:
        return None
    return RuleHit("G1", band["pontos"], {"distance_km": round(distance, 1)})


def _precise(geolocation, max_accuracy_m: float) -> bool:
    return geolocation.accuracy_m is None or geolocation.accuracy_m <= max_accuracy_m


def g2_impossible_travel(facts: Facts) -> RuleHit | None:
    location = facts.pix.geolocation
    params = facts.config.rule("G2")
    if location is None or not _precise(location, params["precisao_max_m"]):
        return None

    oldest = facts.now - timedelta(hours=params["idade_max_horas"])
    previous = [
        pix
        for pix in facts.payer.history
        if pix.geolocation is not None
        and oldest <= pix.transaction_date <= facts.now
        and _precise(pix.geolocation, params["precisao_max_m"])
    ]
    if not previous:
        return None

    last = max(previous, key=lambda pix: pix.transaction_date)
    distance = haversine_km(
        last.geolocation.latitude, last.geolocation.longitude, location.latitude, location.longitude
    )
    seconds = max((facts.now - last.transaction_date).total_seconds(), params["intervalo_min_s"])
    speed = distance / (seconds / 3600)

    for level in params["niveis"]:
        if distance >= level["distancia_min_km"] and speed >= level["velocidade_kmh"]:
            evidence = {"distance_km": round(distance, 1), "speed_kmh": round(speed)}
            return RuleHit("G2", level["pontos"], evidence, floor=level.get("piso", False))
    return None


def c1_new_beneficiary(facts: Facts) -> RuleHit | None:
    if not facts.is_new_destination:
        return None
    return RuleHit("C1", facts.config.rule("C1")["pontos"], {"previous_pix_to_destination": 0})


def c2_destination_age(facts: Facts) -> RuleHit | None:
    created_at = facts.destination.account_created_at
    if created_at is None:
        facts.missing("destination_account.created_at")
        return None
    age_days = (facts.now - created_at).total_seconds() / 86400
    band = first_band(
        age_days, facts.config.rule("C2")["faixas"], "menos_de_dias", lambda value, limit: value < limit
    )
    if band is None:
        return None
    return RuleHit("C2", band["pontos"], {"destination_age_days": int(age_days)})


def c5_many_payers(facts: Facts) -> RuleHit | None:
    payers = facts.destination.reputation.payers_24h
    band = first_band(
        payers, facts.config.rule("C5")["faixas"], "min_pagadores", lambda value, limit: value >= limit
    )
    if band is None:
        return None
    return RuleHit("C5", band["pontos"], {"payers_24h": payers})


def c6_fast_forward(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("C6")
    ratio = facts.destination.reputation.forwarded_ratio_1h
    if ratio < params["proporcao_min"]:
        return None
    return RuleHit("C6", params["pontos"], {"forwarded_ratio_1h": round(ratio, 4)})


def c7_endogenous_reputation(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("C7")
    reputation = facts.destination.reputation
    if reputation.analyses_count < params["min_analises"]:
        return None
    ratio = reputation.suspicious_ratio
    band = first_band(ratio, params["faixas"], "proporcao_min", lambda value, limit: value >= limit)
    if band is None:
        return None
    return RuleHit("C7", band["pontos"], {"analyses": reputation.analyses_count, "ratio": round(ratio, 4)})


def c8_test_and_drain(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("C8")
    tests = [
        pix
        for pix in facts.history_since(timedelta(hours=params["janela_horas"]))
        if pix.destination_key == facts.destination.destination_key
        and pix.amount_cents <= params["teste_max_centavos"]
        and facts.is_new_destination_at(pix.destination_key, pix.transaction_date)
    ]
    if not tests:
        return None

    test = min(tests, key=lambda pix: pix.amount_cents)
    high = max(params["alto_min_centavos"], params["alto_multiplicador"] * test.amount_cents)
    if facts.pix.amount_cents < high:
        return None
    evidence = {"test_amount_cents": test.amount_cents, "high_amount_cents": high}
    return RuleHit("C8", params["pontos"], evidence, floor=True)


def p1_amount_outlier(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("P1")
    threshold, observations, _ = facts.p1_threshold()
    amount = facts.pix.amount_cents
    if amount <= threshold:
        return None

    evidence = {"threshold_cents": round(threshold), "observations": observations}
    if observations < facts.config.p95["min_observacoes"]:
        return RuleHit("P1", params["pontos_sem_historico"], evidence)
    if amount > threshold * params["multiplicador_alto"]:
        return RuleHit("P1", params["pontos_acima_alto"], evidence)
    return RuleHit("P1", params["pontos_acima"], evidence)


def p2_unusual_hour(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("P2")
    window = timedelta(days=facts.config.p95["janela_dias"])
    moments = [
        movement.occurred_at
        for movement in facts.payer.amount_history
        if facts.now - window <= movement.occurred_at <= facts.now
    ]
    if len(moments) < params["min_observacoes"]:
        return None

    hour = facts.config.local_time(facts.now).hour
    neighbours = {(hour - 1) % 24, hour, (hour + 1) % 24}
    hits = sum(1 for moment in moments if facts.config.local_time(moment).hour in neighbours)
    share = hits / len(moments)
    if share >= facts.config.params["histograma_horas_tolerancia"]:
        return None
    return RuleHit("P2", params["pontos"], {"hour": hour, "share": round(share, 3)})


def m1_accumulated(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("M1")
    threshold, _, _ = facts.p1_threshold()
    window = facts.live_history_since(timedelta(hours=params["janela_horas"]))
    total = facts.pix.amount_cents + sum(pix.amount_cents for pix in window)
    limit = threshold * params["multiplicador"]
    if total <= limit:
        return None
    return RuleHit("M1", params["pontos"], {"sum_24h_cents": total, "limit_cents": round(limit)})


def m2_splitting(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("M2")
    amounts = [facts.pix.amount_cents] + [
        pix.amount_cents for pix in facts.live_history_since(timedelta(hours=params["janela_horas"]))
    ]
    for ceiling in params["tetos_centavos"]:
        low, high = ceiling * params["faixa_min"], ceiling * params["faixa_max"]
        count = sum(1 for amount in amounts if low <= amount <= high)
        if count >= params["min_pix"]:
            return RuleHit("M2", params["pontos"], {"ceiling_cents": ceiling, "pix_near_ceiling": count})
    return None


def v1_burst(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("V1")
    count = 1 + len(facts.history_since(timedelta(minutes=params["janela_min"])))
    band = first_band(count, params["faixas"], "min_pix", lambda value, limit: value >= limit)
    if band is None:
        return None
    return RuleHit("V1", band["pontos"], {"pix_10min": count})


def v2_new_destinations(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("V2")
    recent = facts.history_since(timedelta(minutes=params["janela_min"]))
    destinations = {
        pix.destination_key
        for pix in recent
        if facts.is_new_destination_at(pix.destination_key, pix.transaction_date)
    }
    if facts.is_new_destination:
        destinations.add(facts.destination.destination_key)
    if len(destinations) < params["min_destinos"]:
        return None
    return RuleHit("V2", params["pontos"], {"new_destinations_1h": len(destinations)})


def o1_new_source_account(facts: Facts) -> RuleHit | None:
    created_at = facts.payer.account_created_at
    if created_at is None:
        return None
    params = facts.config.rule("O1")
    age_days = (facts.now - created_at).total_seconds() / 86400
    if age_days >= params["menos_de_dias"]:
        return None
    return RuleHit("O1", params["pontos"], {"source_age_days": int(age_days)})


def _valid_open_finance(facts: Facts):
    profile = facts.payer.open_finance
    if profile is None or not profile.is_valid(facts.now):
        facts.missing("open_finance_profile")
        return None
    return profile


def f1_amount_vs_income(facts: Facts) -> RuleHit | None:
    params = facts.config.rule("F1")
    window = timedelta(days=params["janela_renda_dias"])
    income = sum(
        deposit.amount_cents
        for deposit in facts.payer.deposits
        if facts.now - window <= deposit.occurred_at <= facts.now
    )
    profile = _valid_open_finance(facts)
    if profile is not None:
        income += profile.other_income_cents
    if income <= 0:
        facts.missing("income")
        return None

    ratio = facts.pix.amount_cents / income
    band = first_band(ratio, params["faixas"], "acima_x", lambda value, limit: value > limit)
    if band is None:
        return None
    return RuleHit("F1", band["pontos"], {"amount_to_income": round(ratio, 2)})


def f2_balance_drain(facts: Facts) -> RuleHit | None:
    balance = facts.payer.balance_cents
    profile = facts.payer.open_finance
    if profile is not None and profile.is_valid(facts.now):
        balance = (balance or 0) + profile.other_balance_cents
    if not balance:
        facts.missing("balance")
        return None

    params = facts.config.rule("F2")
    ratio = facts.pix.amount_cents / balance
    if ratio < params["proporcao_min"]:
        return None
    return RuleHit("F2", params["pontos"], {"amount_to_balance": round(min(ratio, 99.0), 2)})


def f3_pass_through(facts: Facts, new_destination: bool) -> RuleHit | None:
    if not new_destination:
        return None
    params = facts.config.params["drenagem"]
    window = timedelta(minutes=params["janela_min"])
    minimum = params["valor_minimo_pct"] / 100
    deposits = [
        deposit
        for deposit in facts.payer.deposits
        if facts.now - window <= deposit.occurred_at <= facts.now
        and facts.pix.amount_cents >= deposit.amount_cents * minimum
    ]
    if not deposits:
        return None

    deposit = max(deposits, key=lambda movement: movement.amount_cents)
    points = params["pontos"]
    evidence = {"deposit_minutes_ago": int((facts.now - deposit.occurred_at).total_seconds() // 60)}

    profile = facts.payer.open_finance
    if (
        profile is not None
        and profile.is_valid(facts.now)
        and profile.other_balance_prev_cents is not None
        and facts.now - profile.loaded_at <= timedelta(hours=params["reforco_max_idade_horas"])
    ):
        drop = profile.other_balance_prev_cents - profile.other_balance_cents
        if drop >= deposit.amount_cents * minimum:
            points += params["pontos_reforco"]
            evidence["open_finance_drop"] = True

    return RuleHit("F3", points, evidence, floor=True)


def h2_trusted_beneficiary(facts: Facts, qualifies: bool, evidence: dict) -> RuleHit | None:
    if not qualifies:
        return None
    return RuleHit("H2", facts.config.rule("H2")["pontos"], evidence)
