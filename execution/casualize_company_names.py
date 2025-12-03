import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

CASUAL_COLUMN_NAME = "casualized_company_name"
OPENROUTER_MODEL = "gpt-4o-mini"
OPENROUTER_TEMPERATURE = 0.3
OPENROUTER_MAX_TOKENS = 40
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_DELAY_SECONDS = 0.35
MAX_WORKERS = 4


def _a1_notation(row: int, col: int) -> str:
    letters = []
    while col:
        col, remainder = divmod(col - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters)) + str(row)


def _get_openrouter_api_key() -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENROUTER_API_KEY não encontrado. Defina-o no .env antes de executar esta automação."
        )
    return api_key


def _normalize_header(value: str) -> str:
    return value.strip().lower()


def _find_company_column(headers: List[str]) -> Optional[int]:
    normalized_headers = [_normalize_header(v) for v in headers]
    candidates = {
        "company_name",
        "company name",
        "company",
        "empresa",
        "nome da empresa",
        "nome_empresa",
        "nome empresa",
    }

    for idx, normalized in enumerate(normalized_headers):
        if normalized in candidates:
            return idx

    return None


def _ensure_casual_column(headers: List[str], worksheet) -> int:
    normalized_headers = [_normalize_header(h) for h in headers]
    if CASUAL_COLUMN_NAME not in normalized_headers:
        headers.append(CASUAL_COLUMN_NAME)
        worksheet.update("1:1", [headers])
        return len(headers) - 1

    return normalized_headers.index(CASUAL_COLUMN_NAME)


def _build_prompt(company_name: str, lead_preset: str) -> str:
    context = f"Preset: {lead_preset}" if lead_preset else "Preset não especificado"
    return (
        "Você é um assistente que gera versões casuais e amigáveis de nomes "
        "de empresas para serem usadas em campanhas de outreach. "
        f"Empresa oficial: {company_name}. {context}. "
        "Responda no mesmo idioma em que o nome oficial foi fornecido "
        "(ex: se o nome estiver em português, responda em português. Se o nome estiver em inglês, responda em inglês). "
        "Replique apenas o essencial do próprio nome —— use a primeira parte que parece um nome de uso cotidiano "
        "ou corte sufixos formais como 'Ltd', 'Estate Agents', 'Property', 'Group'. "
        "Não corrija possíveis erros de digitação do nome oficial nem traduza para outra palavra semelhante "
        "(por exemplo, evite transformar 'Mulburries' em 'Mulberries'). "
        "Mantenha íntegros nomes próprios (não converta 'William' para 'Will') e preserve as palavras inteiras "
        "que refletem o jeito como os founders/clientes chamam a empresa, ainda que de forma formal. "
        "Evite acrescentar palavras novas; mantenha-se fiel às palavras já existentes. "
        "Responda com uma versão curta, informal e natural (idealmente ≤3 palavras) "
        "sem pontuação extra ou explicações."
    )


def _generate_casual_name(api_key: str, company_name: str, lead_preset: str) -> Optional[str]:
    if not company_name.strip():
        return None


    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "user", "content": _build_prompt(company_name, lead_preset)}
        ],
        "temperature": OPENROUTER_TEMPERATURE,
        "max_tokens": OPENROUTER_MAX_TOKENS,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(OPENROUTER_ENDPOINT, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None

        text = choices[0].get("message", {}).get("content", "").strip()
        casual_name = text.splitlines()[0].strip() if text else ""
        return casual_name or None
    except requests.RequestException as exc:
        print(f"Erro ao gerar nome casual para '{company_name}' via OpenRouter: {exc}")
        return None
    except ValueError as exc:
        print(f"Resposta inválida ao gerar nome casual para '{company_name}': {exc}")
        return None


def casualize_sheet(google_client, spreadsheet_id: str, worksheet_title: str, lead_preset: str = "") -> None:
    if not spreadsheet_id or not worksheet_title:
        print("Dados da planilha incompletos. Ignorando casualização.")
        return

    try:
        worksheet = google_client.open_by_key(spreadsheet_id).worksheet(worksheet_title)
    except Exception as exc:
        print(f"Não foi possível abrir a planilha ({spreadsheet_id}/{worksheet_title}): {exc}")
        return

    headers = worksheet.row_values(1)
    if not headers:
        print("Cabecalho nao encontrado na planilha. Abortando casualização.")
        return

    try:
        casual_col_idx = _ensure_casual_column(headers, worksheet)
    except Exception as exc:
        print(f"Falha ao garantir coluna '{CASUAL_COLUMN_NAME}': {exc}")
        return

    try:
        openrouter_key = _get_openrouter_api_key()
    except EnvironmentError as exc:
        print(exc)
        return

    company_col_idx = _find_company_column(headers)
    if company_col_idx is None:
        print("Coluna de 'Company Name' não encontrada. Sem casualização.")
        return

    rows = worksheet.get_all_values()
    rows_to_process = []
    for row_number, row in enumerate(rows[1:], start=2):
        current_value = row[casual_col_idx] if casual_col_idx < len(row) else ""
        if current_value.strip():
            continue

        company_name = row[company_col_idx] if company_col_idx < len(row) else ""
        if not company_name.strip():
            continue

        rows_to_process.append((row_number, company_name))

    if not rows_to_process:
        print("Nenhuma linha exige casualização. Nada a fazer.")
        return

    updates = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_row = {
            executor.submit(_generate_casual_name, openrouter_key, company_name, lead_preset): row_number
            for row_number, company_name in rows_to_process
        }

        for future in as_completed(future_to_row):
            row_number = future_to_row[future]
            try:
                casual_name = future.result()
            except Exception as exc:
                print(f"Erro no futuro da linha {row_number}: {exc}")
                continue

            if not casual_name:
                continue

            updates.append((row_number, casual_name))
            time.sleep(REQUEST_DELAY_SECONDS)

    if not updates:
        print(f"Nenhum nome casual gerado em '{CASUAL_COLUMN_NAME}'.")
        return

    batch_payload = [
        {
            "range": _a1_notation(row_number, casual_col_idx + 1),
            "values": [[casual_name]],
        }
        for row_number, casual_name in updates
    ]

    try:
        worksheet.batch_update(batch_payload)
        print(f"Casualização concluída. {len(updates)} linhas atualizadas em '{CASUAL_COLUMN_NAME}'.")
    except Exception as exc:
        print(f"Falha ao aplicar atualizações em lote: {exc}")


if __name__ == "__main__":
    print("Este módulo deve ser importado por outro script (por exemplo, scrape_leads.py).")

