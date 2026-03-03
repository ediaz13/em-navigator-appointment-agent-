"""
Intelligence Core — the brain. Completely channel-agnostic.

Takes an IncomingMessage, returns a DraftedReply.
Does NOT know about Gmail, WhatsApp, or any channel.
Does NOT send anything. That's the Outcome layer's job.

This is your extract_appointment.py logic, elevated into the architecture.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from anthropic import Anthropic
from dotenv import load_dotenv

from src.core.message import Channel, DraftedReply, IncomingMessage

load_dotenv("config/.env")


# ─────────────────────────────────────────────
# Mock Calendar (replace with Google Calendar API later)
# ─────────────────────────────────────────────
MOCK_AVAILABILITY = {
    "Neurología": {
        "Dra. Rosario Ansede": ["lunes 10:00", "lunes 14:00", "miércoles 10:00"],
        "Dr. Martín Ordóñez": ["martes 09:00", "martes 15:00", "jueves 09:00"],
    },
    "Sexología Clínica": {
        "Dra. Rosario Ansede": ["lunes 16:00"],
    },
    "Nutrición": {
        "Lic. Sofía Almada": ["martes 10:00", "martes 14:00"],
    },
}


def _find_next_slot(doctor_or_specialty: str | None) -> dict | None:
    """Find the next available slot matching the request.

    Searches by doctor name first, then by specialty.
    Returns the first match. Production version queries a real calendar.
    """
    if not doctor_or_specialty:
        return None

    query = doctor_or_specialty.lower()

    # Search by doctor name
    for specialty, doctors in MOCK_AVAILABILITY.items():
        for doctor, slots in doctors.items():
            if any(part in query for part in doctor.lower().split()):
                # Calculate a real date for the next occurrence
                base_date = datetime.now() + timedelta(days=3)
                return {
                    "doctor": doctor,
                    "specialty": specialty,
                    "slot": slots[0],
                    "proposed_date": base_date.strftime("%d/%m/%Y"),
                }

    # Search by specialty
    for specialty, doctors in MOCK_AVAILABILITY.items():
        if specialty.lower() in query or query in specialty.lower():
            first_doctor = list(doctors.keys())[0]
            slots = doctors[first_doctor]
            base_date = datetime.now() + timedelta(days=3)
            return {
                "doctor": first_doctor,
                "specialty": specialty,
                "slot": slots[0],
                "proposed_date": base_date.strftime("%d/%m/%Y"),
            }

    return None


# ─────────────────────────────────────────────
# Extraction (reuses your validated zero-shot prompt)
# ─────────────────────────────────────────────
EXTRACTION_PROMPT = """Sos un asistente administrativo de un hospital público argentino, 
especializado en el servicio de Enfermedades Desmielinizantes (Esclerosis Múltiple).

Tu tarea: extraer datos estructurados de mensajes de pacientes que solicitan turnos.

Los pacientes escriben de manera informal, con errores de tipeo, abreviaturas 
y modismos argentinos. Ejemplos:
- "DNI" puede aparecer como "dni", "D.N.I.", "documento", "nro de documento"
- Los nombres pueden estar en cualquier orden o formato
- Las especialidades pueden ser informales: "el neurólogo", "la doctora de EM", "neuro"
- Las fechas pueden ser vagas: "la semana que viene", "después del 15", "cualquier martes"

Respondé ÚNICAMENTE con JSON válido (sin markdown, sin backticks):
{
    "patient_name": "nombre completo o null",
    "dni": "número de DNI (solo números) o null",
    "doctor_or_specialty": "nombre del médico o especialidad solicitada o null",
    "preferred_date": "fecha o preferencia temporal o null",
    "contact_info": "teléfono o email de contacto alternativo o null",
    "confidence": 0.0-1.0
}

Reglas:
- Si un campo no está en el mensaje, usá null (no inventes datos).
- El campo "confidence" refleja qué tan completa es la extracción.
- Normalizá el DNI a solo números (sin puntos ni guiones).
- Normalizá el nombre con mayúscula inicial."""


REPLY_DRAFT_PROMPT = """Sos la secretaria del servicio de Enfermedades Desmielinizantes 
(Piso 9, Sala 2) de un hospital público argentino. 

Redactá una respuesta cordial y profesional para confirmar un turno.
El tono debe ser cálido pero formal. Usá "usted".

Datos del turno:
- Paciente: {patient_name}
- Médico: {doctor}
- Especialidad: {specialty}
- Día y hora propuestos: {slot}, {proposed_date}

Reglas:
- Mencioná que el paciente debe traer DNI y carnet de obra social.
- Pedí que confirme asistencia respondiendo al mensaje.
- Si no puede asistir, que avise con anticipación para liberar el turno.
- Firmá como "Equipo de Enfermedades Desmielinizantes - Piso 9, Sala 2".
- Respuesta breve (máximo 6 líneas).
- NO uses emojis.
- Respondé SOLO con el texto del mensaje, sin comillas ni explicaciones."""


def _call_claude(system: str, user: str, max_tokens: int = 512) -> str:
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _parse_extraction(raw: str) -> dict:
    """Safely parse Claude's JSON response."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)


# ─────────────────────────────────────────────
# The main pipeline: IncomingMessage → DraftedReply
# ─────────────────────────────────────────────
def process_message(message: IncomingMessage) -> DraftedReply:
    """The complete intelligence pipeline. Channel-agnostic.

    Steps:
        1. Extract structured data from the message body
        2. Find an available calendar slot
        3. Draft a reply in the appropriate tone
        4. Return a DraftedReply for human review

    This function has NO side effects. It doesn't send anything.
    It doesn't update any database. It returns data. That's it.
    """

    # Step 1: Extract
    raw_extraction = _call_claude(
        EXTRACTION_PROMPT,
        f"Mensaje del paciente:\n\n{message.body}",
    )
    extracted = _parse_extraction(raw_extraction)

    # Step 2: Check calendar
    slot_info = _find_next_slot(extracted.get("doctor_or_specialty"))

    # Step 3: Draft reply
    if slot_info:
        reply_body = _call_claude(
            REPLY_DRAFT_PROMPT.format(
                patient_name=extracted.get("patient_name", "Paciente"),
                doctor=slot_info["doctor"],
                specialty=slot_info["specialty"],
                slot=slot_info["slot"],
                proposed_date=slot_info["proposed_date"],
            ),
            "Generá el mensaje de respuesta.",
            max_tokens=300,
        )
        subject = f"Turno {slot_info['specialty']} - {slot_info['slot']} {slot_info['proposed_date']}"
    else:
        reply_body = (
            f"Estimado/a {extracted.get('patient_name', 'Paciente')}:\n\n"
            "Recibimos su solicitud de turno. En este momento no encontramos "
            "disponibilidad inmediata para la especialidad o profesional solicitado. "
            "Nos comunicaremos a la brevedad para coordinar una fecha.\n\n"
            "Equipo de Enfermedades Desmielinizantes - Piso 9, Sala 2"
        )
        subject = "Solicitud de turno recibida"

    return DraftedReply(
        request_id=message.id,
        channel=message.channel,
        recipient_id=message.sender_id,
        subject=subject,
        body=reply_body,
        extracted_data=extracted,
        proposed_datetime=f"{slot_info['slot']} {slot_info['proposed_date']}" if slot_info else None,
        confidence=float(extracted.get("confidence", 0.0)),
        metadata=message.metadata,  # Pass through channel-specific data for reply
    )
