"""
Simulador de Ataques e Teste de Resiliencia Antifraude.

Executa cenarios de ataques reais simulados por atacantes fraudulentos contra a API
do Bootcamp Bank, validando como o motor antifraude intercepta e protege o banco e correntistas.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import time
import uuid
import requests

API_BASE_URL = "http://localhost:3000"
PIX_URL = f"{API_BASE_URL}/pix/transaction"
HEADERS = {
    "Content-Type": "application/json",
    "INTERNAL-TOKEN": "default_token",
}


def print_header(title: str):
    print("\n" + "=" * 80)
    print(f" [SIMULACAO DE ATAQUE] {title}")
    print("=" * 80)


def run_scenario(
    name: str,
    description: str,
    payload: dict,
    expected_status: str,
    expected_challenge: str = None,
):
    print_header(name)
    print(f"Vetor de Ataque : {description}")
    channel = payload.get("source", {}).get("channel", "N/A")
    valor_reais = payload.get("amount", 0) / 100
    print(f"Canal / Valor   : {channel} | R$ {valor_reais:.2f}")

    start = time.perf_counter()
    try:
        resp = requests.post(PIX_URL, json=payload, headers=HEADERS, timeout=5)
        elapsed_ms = (time.perf_counter() - start) * 1000
    except Exception as e:
        print(f"[ERRO DE CONEXAO] Nao foi possivel conectar na API: {e}")
        return False

    print(f"Status HTTP     : {resp.status_code} | Latencia total: {elapsed_ms:.2f}ms")
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    status = data.get("status")
    metadata = data.get("metadata", {})
    challenge = None
    if data.get("two_factor_required"):
        challenge = data.get("two_factor_required", {}).get("challenge_type")
    customer_msg = metadata.get("customer_message_key")
    rules = [r.get("code") for r in metadata.get("rules_fired", [])]

    print(f"Decisao Antifraude: {str(status).upper() if status else 'REJEITADO'}")
    if rules:
        print(f"Regras Disparadas : {', '.join(rules)} (Score: {metadata.get('score')})")
    if challenge:
        print(f"Desafio de Seguranca: {challenge}")
    if customer_msg:
        print(f"Mensagem ao Cliente : {customer_msg}")
    if metadata.get("in_trusted_location"):
        print("Geofencing         : [LOCAL CONFIÁVEL DETECTADO]")

    # Checagem de sucesso da defesa
    passed = False
    if status == expected_status:
        if expected_challenge:
            passed = challenge == expected_challenge
        else:
            passed = True
    elif resp.status_code in (400, 422) and expected_status == "rejected":
        passed = True

    if passed:
        print(">> [DEFESA EFICAZ] Motor antifraude agiu exatamente conforme o esperado!")
    else:
        print(f">> [ALERTA] Resposta diferente: esperado='{expected_status}', recebido='{status}'")

    return passed


def main():
    print("\n" + "#" * 80)
    print(" INICIANDO BATERIA DE TESTES DE ATAQUE FRAUDULENTO CONTRA O MOTOR ANTIFRAUDE")
    print(f" Endpoint sob teste: {PIX_URL}")
    print("#" * 80)

    now = datetime.now(timezone.utc)
    device_vitima = "device-maria-phone-01"
    device_hacker = "device-kali-emulator-999"

    resultados = []

    # =========================================================================
    # CENARIO 1: Golpe da Mao Fantasma / Coacao Telefonica (Regra R1)
    # =========================================================================
    payload_remoto = {
        "id": f"PIX-ATTACK-R1-{uuid.uuid4().hex[:8]}",
        "type": "payment",
        "amount": 85000,  # R$ 850,00
        "transaction_date": now.isoformat(),
        "source": {
            "channel": "celular",
            "device_id": device_hacker,
            "remote_access_detected": True,  # AnyDesk ativo
            "call_in_progress": True,  # Ligacao simultanea
            "geolocation": {"latitude": -23.600000, "longitude": -46.700000},  # Fora de local seguro
        },
        "source_account": {
            "account_key": "48ca1247-8967-4f79-8534-bb12e0262a4f",
            "document_number": "408.463.867-63",
            "has_trusted_contact": True,
            "owner": {"name": "Maria Idosa"},
        },
        "destination_account": {
            "document_number": "98765432100",
            "owner": {"name": "Receptor Desconhecido"},
        },
    }
    r1 = run_scenario(
        name="Golpe da Mao Fantasma / Coacao Telefonica (Regra R1 + Notificacao Familiar)",
        description="Vitima idosa sob ligacao com AnyDesk ativo tentando transferir R$ 850 fora de local seguro.",
        payload=payload_remoto,
        expected_status="rejected",  # Score 90 > teto 75 -> Rejeitado e aciona rede de apoio
    )
    resultados.append(("Mao Fantasma / Coacao Telefonica", r1))

    # =========================================================================
    # CENARIO 2: Teletransporte Impossivel (> 800 km/h)
    # =========================================================================
    t_sp = now - timedelta(minutes=5)
    pix_origem_sp = {
        "id": f"PIX-BASE-SP-{uuid.uuid4().hex[:8]}",
        "type": "payment",
        "amount": 1000,
        "transaction_date": t_sp.isoformat(),
        "source": {
            "channel": "celular",
            "device_id": "device-teleport-test",
            "geolocation": {"latitude": -23.550520, "longitude": -46.633308},  # SP
        },
        "source_account": {
            "document_number": "11222333000181",
            "owner": {"name": "João da Silva MEI"},
        },
        "destination_account": {
            "document_number": "33024468000175",
            "owner": {"name": "Comercio Local"},
        },
    }
    requests.post(PIX_URL, json=pix_origem_sp, headers=HEADERS, timeout=5)

    # 4 minutos depois tenta transacionar em Manaus no mesmo device
    payload_teletransporte = {
        "id": f"PIX-ATTACK-G2-{uuid.uuid4().hex[:8]}",
        "type": "payment",
        "amount": 250000,  # R$ 2.500,00
        "transaction_date": (t_sp + timedelta(minutes=4)).isoformat(),
        "source": {
            "channel": "celular",
            "device_id": "device-teleport-test",
            "geolocation": {"latitude": -3.119028, "longitude": -60.021731},  # Manaus (>20.000 km/h)
        },
        "source_account": {
            "document_number": "11222333000181",
            "owner": {"name": "João da Silva MEI"},
        },
        "destination_account": {
            "document_number": "33024468000175",
            "owner": {"name": "Comercio Local"},
        },
    }
    r2 = run_scenario(
        name="Teletransporte Fisico Impossivel (Regra G2 > 800 km/h)",
        description="Mesmo device transaciona em Manaus apenas 4 min apos transacao em Sao Paulo.",
        payload=payload_teletransporte,
        expected_status="rejected",
    )
    resultados.append(("Teletransporte Impossivel", r2))

    # =========================================================================
    # CENARIO 3: Violacao de Teto Noturno de Seguranca (Regra E5)
    # =========================================================================
    # Simula horário noturno (ex: 23:30 de ontem)
    t_noite = (now - timedelta(days=1)).replace(hour=23, minute=30, second=0, microsecond=0)
    payload_noturno = {
        "id": f"PIX-ATTACK-E5-{uuid.uuid4().hex[:8]}",
        "type": "payment",
        "amount": 450000,  # R$ 4.500,00 (Teto noturno PF e R$ 1.000,00)
        "transaction_date": t_noite.isoformat(),
        "source": {
            "channel": "celular",
            "device_id": device_hacker,
            "geolocation": {"latitude": -23.550520, "longitude": -46.633308},
        },
        "source_account": {
            "account_key": "48ca1247-8967-4f79-8534-bb12e0262a4f",
            "document_number": "408.463.867-63",
            "owner": {"name": "Maria Idosa"},
        },
        "destination_account": {
            "document_number": "98765432100",
            "owner": {"name": "Saque Noturno Golpista"},
        },
    }
    r3 = run_scenario(
        name="Sequestro Relampago / Drenagem Noturna (Regra E5: Teto R$ 1.000)",
        description="Atacante tenta transferir R$ 4.500,00 as 23h30 violando a restricao regulatoria do Bacen.",
        payload=payload_noturno,
        expected_status="rejected",
    )
    resultados.append(("Drenagem Noturna Acima do Teto", r3))

    # =========================================================================
    # CENARIO 4: Transacao Legitima em Local Confiavel (Safe Zone / Geofencing)
    # =========================================================================
    payload_seguro = {
        "id": f"PIX-SAFE-HOME-{uuid.uuid4().hex[:8]}",
        "type": "payment",
        "amount": 1500,  # R$ 15,00 (Compra da feira ou farmácia)
        "transaction_date": now.isoformat(),
        "source": {
            "channel": "celular",
            "device_id": "device-carlos-phone-04",
            # Exatamente nas coordenadas da residência cadastrada em trusted_location
            "geolocation": {"latitude": -23.550520, "longitude": -46.633308},
        },
        "source_account": {
            "account_key": "b1b2c3d4-0002-4000-8000-000000000004",
            "document_number": "529.982.247-25",
            "owner": {"name": "Carlos Eduardo"},
        },
        "destination_account": {
            "document_number": "31372324000184",
            "owner": {"name": "Padaria e Confeitaria Central"},
        },
    }
    r4 = run_scenario(
        name="Uso Legitimo em Local Confiavel (Rotina Preservada)",
        description="Carlos faz Pix corriqueiro de R$ 15,00 para padaria em horario diurno.",
        payload=payload_seguro,
        expected_status="approved",
    )
    resultados.append(("Uso Legitimo em Local Seguro", r4))

    # =========================================================================
    # RESUMO
    # =========================================================================
    print("\n" + "=" * 80)
    print(" RELATORIO DE EFICACIA DAS DEFESAS ANTIFRAUDE:")
    print("=" * 80)
    for nome, sucesso in resultados:
        status_txt = "[PASSOU - Bloqueou/Desafiou]" if sucesso else "[FALHOU]"
        print(f" • {nome:45}: {status_txt}")

    total_passou = sum(1 for _, s in resultados if s)
    taxa = (total_passou / len(resultados)) * 100
    print(f"\nTaxa de Eficacia Antifraude: {taxa:.1f}% ({total_passou}/{len(resultados)})\n")


if __name__ == "__main__":
    main()
