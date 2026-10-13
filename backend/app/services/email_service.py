import smtplib
from html import escape
import logging
import asyncio
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email import encoders
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings

logger = logging.getLogger(__name__)

# Read from pydantic-settings (which loads .env). Falling back to os.environ
# directly silently lost the values configured in the project's .env file.
SMTP_HOST = settings.SMTP_HOST
SMTP_PORT = settings.SMTP_PORT
SMTP_USER = settings.SMTP_USER
SMTP_PASS = settings.SMTP_PASSWORD
FROM_EMAIL = settings.EMAILS_FROM_EMAIL or SMTP_USER or "noreply@piqbit.com"
FROM_NAME = settings.EMAILS_FROM_NAME or "PIQBIT Recrutement"

_executor = ThreadPoolExecutor(max_workers=4)


def _send_sync(to_email: str, subject: str, html: str, attachments: list[tuple[str, bytes, str]] | None = None) -> bool:
    """
    attachments: list of (filename, content_bytes, mimetype) tuples.
    """
    if not SMTP_HOST or not SMTP_USER:
        logger.info(
            f"[EMAIL-DEV] To: {to_email} | Subject: {subject}\n"
            f"(attachments: {[a[0] for a in attachments] if attachments else 'none'})\n"
            f"Configure SMTP_HOST/SMTP_USER env vars to send real emails."
        )
        return True
    try:
        msg = MIMEMultipart("mixed" if attachments else "alternative")
        msg["Subject"] = subject
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email

        if attachments:
            body = MIMEMultipart("alternative")
            body.attach(MIMEText(html, "html", "utf-8"))
            msg.attach(body)
            for filename, content, mimetype in attachments:
                maintype, subtype = (mimetype.split("/", 1) + ["octet-stream"])[:2]
                part = MIMEBase(maintype, subtype)
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename=\"{filename}\"")
                msg.attach(part)
        else:
            msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as exc:
        logger.error(f"Email send failed to {to_email}: {exc}")
        return False


async def send_email(
    to_email: str,
    subject: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _send_sync, to_email, subject, html, attachments)


# ── ICS helper ─────────────────────────────────────────────────────

def _ics_dt(dt: datetime) -> str:
    """Format as UTC for an .ics file (e.g. 20260611T090000Z)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    *,
    summary: str,
    description: str,
    start_at: datetime,
    end_at: datetime,
    organizer_email: str = FROM_EMAIL,
    attendee_email: str | None = None,
    location: str = "Visioconférence",
) -> bytes:
    """Build a minimal RFC-5545 .ics file as bytes."""
    uid = f"{uuid.uuid4()}@piqbit"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PIQBIT//Interview//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_ics_dt(datetime.now(timezone.utc))}",
        f"DTSTART:{_ics_dt(start_at)}",
        f"DTEND:{_ics_dt(end_at)}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description.replace(chr(10), ' ')}",
        f"LOCATION:{location}",
        f"ORGANIZER;CN={FROM_NAME}:mailto:{organizer_email}",
    ]
    if attendee_email:
        lines.append(f"ATTENDEE;CN={attendee_email};RSVP=TRUE:mailto:{attendee_email}")
    lines += [
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8")


def _slot_rows(slots: list[str]) -> str:
    return "".join(
        f"<li style='margin:6px 0;padding:8px 14px;background:#f0f9ff;"
        f"border-left:3px solid #0ea5e9;border-radius:4px;'>"
        f"📅 {s}</li>"
        for s in slots
    )


async def send_interview_invitation(
    to_email: str,
    candidate_name: str,
    job_title: str,
    slots: list[str],
    message: str = "",
) -> bool:
    extra = f"<p style='color:#374151;'>{message}</p>" if message else ""
    html = f"""
    <div style='font-family:Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#1e40af;color:#fff;padding:24px;border-radius:8px 8px 0 0;'>
        <h2 style='margin:0;'>Invitation à un entretien</h2>
        <p style='margin:4px 0 0;opacity:.85;'>{job_title}</p>
      </div>
      <div style='background:#fff;padding:28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;'>
        <p>Bonjour <strong>{candidate_name}</strong>,</p>
        <p>Suite à l'examen de votre candidature pour le poste de <strong>{job_title}</strong>,
           nous souhaitons vous rencontrer pour un entretien.</p>
        <p><strong>Créneaux disponibles :</strong></p>
        <ul style='padding-left:0;list-style:none;'>
          {_slot_rows(slots)}
        </ul>
        <p>Veuillez nous indiquer le créneau qui vous convient le mieux en répondant à cet email.</p>
        {extra}
        <hr style='border:none;border-top:1px solid #e5e7eb;margin:20px 0;'/>
        <p style='color:#6b7280;font-size:.85rem;'>
          Cordialement,<br/>L'équipe Recrutement — PIQBIT
        </p>
      </div>
    </div>
    """
    return await send_email(to_email, f"Entretien — {job_title}", html)


# ───────────────────────────────────────────────────────────────────
# NEW WORKFLOW : link-based invitation with public confirm page
# ───────────────────────────────────────────────────────────────────

def libelle_fuseau() -> str:
    """« heure de Tunis » pour Africa/Tunis — dit au lecteur quelle heure il lit."""
    ville = settings.APP_TIMEZONE.rsplit("/", 1)[-1].replace("_", " ")
    return "UTC" if ville.upper() == "UTC" else f"heure de {ville}"


def formater_date_heure(dt: datetime) -> str:
    """
    Date et heure en toutes lettres, DANS LE FUSEAU DE LA PLATEFORME.

    Les dates sont stockées en UTC : formatées telles quelles, elles
    annonçaient au candidat une heure décalée (13h07 pour 14h07 à Tunis).
    Le fuseau est rappelé : un lecteur à l'étranger sait ce qu'il lit, et le
    fichier .ics joint s'affiche, lui, à l'heure locale de chacun.
    """
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo(settings.APP_TIMEZONE))
        days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        months = ["janvier", "février", "mars", "avril", "mai", "juin",
                  "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        return (f"{days[dt.weekday()]} {dt.day} {months[dt.month - 1]} {dt.year} "
                f"à {dt.strftime('%Hh%M')} ({libelle_fuseau()})")
    except Exception:
        return str(dt)


def _slot_link_rows(slots: list[datetime]) -> str:
    return "".join(
        f"<li style='margin:8px 0;padding:10px 14px;background:#f0f9ff;"
        f"border-left:3px solid #0ea5e9;border-radius:6px;font-size:14px;'>"
        f"📅 {formater_date_heure(s)}</li>"
        for s in slots
    )


async def send_interview_invitation_link(
    *,
    to_email: str,
    candidate_name: str,
    job_title: str,
    slots: list[datetime],
    public_url: str,
    message: str = "",
    expires_at: datetime | None = None,
) -> bool:
    extra = f"<p style='color:#374151;margin:18px 0;'>{message}</p>" if message else ""
    exp = ""
    if expires_at:
        exp = (f"<p style='color:#9CA3AF;font-size:.82rem;margin-top:16px;'>"
               f"⏰ Ce lien est valable jusqu'au {formater_date_heure(expires_at)}.</p>")
    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#18534F;color:#FEEAA1;padding:28px;border-radius:12px 12px 0 0;text-align:center;'>
        <h2 style='margin:0;font-size:1.5rem;letter-spacing:-.02em;'>Invitation à un entretien</h2>
        <p style='margin:8px 0 0;color:rgba(254,234,161,.78);font-size:.92rem;'>{job_title}</p>
      </div>
      <div style='background:#FFFFFF;padding:32px 28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{candidate_name}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.55;color:#1F2937;'>Suite à l'examen de votre candidature pour le poste de
           <strong>{job_title}</strong>, nous souhaitons vous rencontrer pour un entretien.</p>
        <p style='font-size:14.5px;color:#1F2937;margin-top:18px;'>👉 <strong>Cliquez sur le bouton ci-dessous</strong> pour choisir
           le créneau qui vous convient le mieux :</p>
        <div style='text-align:center;margin:28px 0;'>
          <a href="{public_url}" style='display:inline-block;padding:14px 30px;background:#18534F;color:#FEEAA1;
             border-radius:50px;font-weight:700;text-decoration:none;font-size:15px;'>
            ✔ Choisir mon créneau
          </a>
        </div>
        <p style='font-size:13px;color:#6B7280;text-align:center;margin:8px 0;'>
          ou copiez ce lien : <br/>
          <span style='font-family:monospace;font-size:12px;color:#18534F;word-break:break-all;'>{public_url}</span>
        </p>
        <p style='font-size:13.5px;color:#6B7280;margin-top:22px;'>Créneaux proposés :</p>
        <ul style='padding-left:0;list-style:none;margin:8px 0 0;'>
          {_slot_link_rows(slots)}
        </ul>
        {extra}
        {exp}
        <hr style='border:none;border-top:1px solid #ECF8F6;margin:24px 0;'/>
        <p style='color:#9CA3AF;font-size:.82rem;margin:0;'>
          Cordialement,<br/>L'équipe Recrutement — PIQBIT
        </p>
      </div>
    </div>
    """
    return await send_email(to_email, f"Invitation Entretien — {job_title}", html)


def _meet_block(meet_url: str | None) -> str:
    """Encart « Lien de connexion » commun aux emails d'entretien (vide si pas de lien)."""
    if not meet_url:
        return ""
    return f"""
        <div style='background:#EEF6FF;padding:18px 22px;border-radius:12px;border-left:4px solid #2563EB;margin:18px 0;'>
          <p style='margin:0 0 10px;font-size:.78rem;color:#3B5B8C;text-transform:uppercase;letter-spacing:.1em;font-weight:700;'>Lien de connexion</p>
          <a href='{meet_url}' style='display:inline-block;background:#2563EB;color:#fff;text-decoration:none;
             padding:11px 22px;border-radius:8px;font-weight:700;font-size:14px;'>Rejoindre l'entretien</a>
          <p style='margin:10px 0 0;font-size:12px;color:#5B7B79;word-break:break-all;'>{meet_url}</p>
        </div>"""


async def send_interview_confirmation_candidate(
    *,
    to_email: str,
    candidate_name: str,
    job_title: str,
    slot_start: datetime,
    slot_end: datetime,
    meet_url: str | None = None,
) -> bool:
    ics = build_ics(
        summary=f"Entretien — {job_title}",
        description=f"Entretien avec {candidate_name} pour le poste {job_title}."
        + (f"\nLien : {meet_url}" if meet_url else ""),
        start_at=slot_start,
        end_at=slot_end,
        attendee_email=to_email,
    )
    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#1F6F47;color:#fff;padding:28px;border-radius:12px 12px 0 0;text-align:center;'>
        <div style='font-size:2.4rem;margin-bottom:6px;'>✅</div>
        <h2 style='margin:0;font-size:1.4rem;'>Entretien confirmé</h2>
        <p style='margin:6px 0 0;opacity:.82;'>{job_title}</p>
      </div>
      <div style='background:#FFFFFF;padding:32px 28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{candidate_name}</strong>,</p>
        <p style='font-size:14.5px;color:#1F2937;line-height:1.55;'>Votre entretien est <strong>confirmé</strong> aux date et heure suivantes :</p>
        <div style='background:#ECF8F6;padding:20px 22px;border-radius:12px;border-left:4px solid #18534F;margin:18px 0;'>
          <p style='margin:0 0 6px;font-size:.78rem;color:#5B7B79;text-transform:uppercase;letter-spacing:.1em;font-weight:700;'>Date & heure</p>
          <p style='margin:0;font-size:18px;font-weight:700;color:#18534F;'>{formater_date_heure(slot_start)}</p>
          <p style='margin:8px 0 0;font-size:.85rem;color:#5B7B79;'>📹 Format : Visioconférence</p>
        </div>
        {_meet_block(meet_url)}
        <p style='font-size:13.5px;color:#6B7280;line-height:1.55;'>Un fichier d'invitation calendrier (.ics) est joint à cet email — vous pouvez
           l'ajouter à Google Calendar, Outlook ou Apple Calendar en un clic.</p>
        <p style='font-size:13.5px;color:#6B7280;line-height:1.55;'>📩 Vous recevrez un rappel avec le lien quelques minutes avant l'entretien.</p>
        <p style='font-size:13.5px;color:#6B7280;line-height:1.55;'>💡 Besoin de modifier ou d'annuler ? Contactez-nous : rh@piqbit.tn</p>
        <hr style='border:none;border-top:1px solid #ECF8F6;margin:24px 0;'/>
        <p style='color:#9CA3AF;font-size:.82rem;margin:0;'>
          À très bientôt,<br/>L'équipe Recrutement — PIQBIT
        </p>
      </div>
    </div>
    """
    return await send_email(
        to_email,
        f"Confirmation entretien — {job_title}",
        html,
        attachments=[("entretien.ics", ics, "text/calendar")],
    )


async def send_interview_notification_rh(
    *,
    to_email: str,
    candidate_name: str,
    candidate_email: str,
    job_title: str,
    slot_start: datetime,
    slot_end: datetime,
    meet_url: str | None = None,
) -> bool:
    visio_row = (
        f"<p style='margin:10px 0 0;color:#5B7B79;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;font-weight:700;'>Visio</p>"
        f"<p style='margin:2px 0 0;font-size:13px;word-break:break-all;'><a style='color:#2563EB;' href='{meet_url}'>{meet_url}</a></p>"
        if meet_url else ""
    )
    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#18534F;color:#FEEAA1;padding:24px;border-radius:12px 12px 0 0;'>
        <h2 style='margin:0;font-size:1.25rem;'>📅 Nouvelle confirmation d'entretien</h2>
      </div>
      <div style='background:#FFFFFF;padding:28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        <p style='font-size:14.5px;color:#1F2937;'>
          <strong>{candidate_name}</strong> (<a style='color:#18534F;' href="mailto:{candidate_email}">{candidate_email}</a>)
          vient de confirmer un créneau d'entretien.
        </p>
        <div style='background:#ECF8F6;padding:16px 20px;border-radius:10px;border-left:4px solid #18534F;margin:14px 0;'>
          <p style='margin:0;color:#5B7B79;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;font-weight:700;'>Poste</p>
          <p style='margin:2px 0 10px;font-size:15px;font-weight:700;color:#18534F;'>{job_title}</p>
          <p style='margin:0;color:#5B7B79;font-size:.78rem;text-transform:uppercase;letter-spacing:.08em;font-weight:700;'>Date</p>
          <p style='margin:2px 0 0;font-size:15px;font-weight:700;color:#18534F;'>{formater_date_heure(slot_start)}</p>
          {visio_row}
        </div>
        <p style='font-size:13px;color:#6B7280;'>Les autres créneaux proposés ont été libérés automatiquement.
           Un rappel avec le lien de connexion sera envoyé quelques minutes avant l'entretien.</p>
      </div>
    </div>
    """
    return await send_email(to_email, f"Entretien confirmé — {candidate_name}", html)


async def send_interview_meet_link(
    *,
    to_email: str,
    recipient_role: str,           # "candidate" | "rh" | "superadmin"
    candidate_name: str,
    job_title: str,
    slot_start: datetime,
    meet_url: str | None,
    minutes_before: int,
) -> bool:
    """
    Rappel « rejoindre maintenant », envoyé peu avant l'heure de l'entretien
    confirmé au candidat, au RH et au superadmin.
    """
    intro = {
        "candidate": f"Votre entretien pour <strong>{job_title}</strong> commence bientôt.",
        "rh": f"L'entretien de <strong>{candidate_name}</strong> ({job_title}) commence bientôt.",
        "superadmin": f"Entretien <strong>{candidate_name}</strong> — {job_title}.",
    }.get(recipient_role, f"Entretien {candidate_name} — {job_title}.")

    delai = f"dans {minutes_before} minute{'s' if minutes_before > 1 else ''}" if minutes_before > 0 else "maintenant"

    bouton = (
        f"<a href='{meet_url}' style='display:inline-block;background:#2563EB;color:#fff;text-decoration:none;"
        f"padding:14px 32px;border-radius:10px;font-weight:800;font-size:16px;'>Rejoindre l'entretien</a>"
        f"<p style='margin:12px 0 0;font-size:12px;color:#6B7280;word-break:break-all;'>{meet_url}</p>"
        if meet_url
        else "<p style='color:#B45309;font-size:14px;'>Aucun lien de visioconférence n'a pu être généré — "
             "contactez le candidat directement.</p>"
    )

    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#2563EB;color:#fff;padding:26px;border-radius:12px 12px 0 0;text-align:center;'>
        <div style='font-size:2rem;margin-bottom:4px;'>📹</div>
        <h2 style='margin:0;font-size:1.3rem;'>L'entretien commence {delai}</h2>
      </div>
      <div style='background:#FFFFFF;padding:30px 26px;border:1px solid #E5E7EB;border-top:none;border-radius:0 0 12px 12px;text-align:center;'>
        <p style='font-size:14.5px;color:#1F2937;line-height:1.55;margin:0 0 6px;'>{intro}</p>
        <p style='font-size:13.5px;color:#6B7280;margin:0 0 22px;'>{formater_date_heure(slot_start)}</p>
        {bouton}
        <hr style='border:none;border-top:1px solid #EEF2F7;margin:26px 0 16px;'/>
        <p style='color:#9CA3AF;font-size:.8rem;margin:0;'>PIQBIT — Recrutement</p>
      </div>
    </div>
    """
    sujet = (
        f"Votre entretien commence {delai} — {job_title}"
        if recipient_role == "candidate"
        else f"Entretien {candidate_name} — commence {delai}"
    )
    return await send_email(to_email, sujet, html)


async def send_interview_cancellation(
    *,
    to_email: str,
    candidate_name: str,
    job_title: str,
    reason: str = "",
) -> bool:
    reason_block = (
        f"<p style='color:#374151;padding:12px 16px;background:#FEF3F2;border-left:3px solid #D45B5B;border-radius:6px;'>{reason}</p>"
        if reason else ""
    )
    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#8C3838;color:#fff;padding:24px;border-radius:12px 12px 0 0;'>
        <h2 style='margin:0;font-size:1.3rem;'>Entretien annulé</h2>
        <p style='margin:6px 0 0;opacity:.82;'>{job_title}</p>
      </div>
      <div style='background:#FFFFFF;padding:28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        <p>Bonjour <strong>{candidate_name}</strong>,</p>
        <p style='color:#1F2937;line-height:1.55;'>Nous vous informons que votre entretien prévu pour le poste de
          <strong>{job_title}</strong> a été <strong>annulé</strong>.</p>
        {reason_block}
        <p style='color:#6B7280;font-size:.9rem;'>Nous reviendrons vers vous prochainement si une nouvelle opportunité se présente.</p>
      </div>
    </div>
    """
    return await send_email(to_email, f"Entretien annulé — {job_title}", html)


async def send_rejection_email(
    to_email: str,
    candidate_name: str,
    job_title: str,
    message: str = "",
) -> bool:
    # Le message est saisi par le RH : échappé comme le nom et le poste.
    nom, poste = escape(candidate_name), escape(job_title)
    extra = f"<p style='color:#374151;'>{escape(message)}</p>" if message else ""
    html = f"""
    <div style='font-family:Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#374151;color:#fff;padding:24px;border-radius:8px 8px 0 0;'>
        <h2 style='margin:0;'>Réponse à votre candidature</h2>
        <p style='margin:4px 0 0;opacity:.85;'>{poste}</p>
      </div>
      <div style='background:#fff;padding:28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;'>
        <p>Bonjour <strong>{nom}</strong>,</p>
        <p>Nous vous remercions pour l'intérêt que vous portez au poste de <strong>{poste}</strong>
           et pour le temps consacré à votre candidature.</p>
        <p>Après examen attentif de votre profil, nous avons décidé de poursuivre avec d'autres candidats
           dont le profil correspond davantage à nos besoins actuels.</p>
        {extra}
        <p>Nous conservons votre dossier et n'hésiterons pas à vous recontacter si une opportunité
           adaptée à votre profil se présente.</p>
        <hr style='border:none;border-top:1px solid #e5e7eb;margin:20px 0;'/>
        <p style='color:#6b7280;font-size:.85rem;'>
          Cordialement,<br/>L'équipe Recrutement — PIQBIT
        </p>
      </div>
    </div>
    """
    return await send_email(to_email, f"Candidature — {job_title}", html)


# ── Comptes utilisateurs ───────────────────────────────────────────

def _account_email(title: str, greeting: str, body: str, cta_label: str, cta_url: str, footer: str) -> str:
    """Gabarit commun aux e-mails de compte (vérification, réinitialisation)."""
    return f"""
    <div style='font-family:Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#1f2937;color:#fff;padding:24px;border-radius:8px 8px 0 0;'>
        <h2 style='margin:0;'>{title}</h2>
      </div>
      <div style='background:#fff;padding:28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;'>
        <p>Bonjour <strong>{greeting}</strong>,</p>
        {body}
        <p style='text-align:center;margin:28px 0;'>
          <a href='{cta_url}'
             style='background:#2563eb;color:#fff;text-decoration:none;padding:12px 28px;
                    border-radius:6px;display:inline-block;font-weight:bold;'>{cta_label}</a>
        </p>
        <p style='color:#6b7280;font-size:.8rem;word-break:break-all;'>
          Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :<br/>{cta_url}
        </p>
        <hr style='border:none;border-top:1px solid #e5e7eb;margin:20px 0;'/>
        <p style='color:#6b7280;font-size:.85rem;'>{footer}</p>
      </div>
    </div>
    """


async def send_email_verification(to_email: str, full_name: str, code: str) -> bool:
    """
    Envoie le code de confirmation d'adresse (OTP à saisir dans l'application).

    `code` est la valeur EN CLAIR : la base n'en conserve que l'empreinte, ce
    message est donc le seul endroit où elle circule. Contrairement à un lien,
    un code se recopie depuis le téléphone vers l'ordinateur, et ne se perd pas
    dans les redirections des clients de messagerie.
    """
    minutes = settings.EMAIL_OTP_EXPIRE_MINUTES
    html = f"""
    <div style='font-family:Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#1f2937;color:#fff;padding:24px;border-radius:8px 8px 0 0;'>
        <h2 style='margin:0;'>Confirmez votre adresse e-mail</h2>
      </div>
      <div style='background:#fff;padding:28px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;'>
        <p>Bonjour <strong>{full_name}</strong>,</p>
        <p>Votre compte PIQBIT a bien été créé. Saisissez le code ci-dessous
           dans l'application pour activer votre compte.</p>
        <p style='text-align:center;margin:28px 0;'>
          <span style='display:inline-block;background:#f3f4f6;border:1px solid #e5e7eb;
                       border-radius:8px;padding:16px 32px;font-size:2rem;font-weight:bold;
                       letter-spacing:.5rem;color:#111827;font-family:monospace;'>{code}</span>
        </p>
        <p style='color:#6b7280;font-size:.9rem;text-align:center;'>
          Ce code est valable {minutes} minutes.
        </p>
        <hr style='border:none;border-top:1px solid #e5e7eb;margin:20px 0;'/>
        <p style='color:#6b7280;font-size:.85rem;'>
          Ne communiquez ce code à personne. Si vous n'êtes pas à l'origine de
          cette inscription, ignorez simplement ce message.
        </p>
      </div>
    </div>
    """
    return await send_email(to_email, f"PIQBIT — Votre code de vérification : {code}", html)


async def send_password_reset_email(to_email: str, full_name: str, token: str) -> bool:
    """Envoie le lien de réinitialisation de mot de passe (jeton en clair, cf. ci-dessus)."""
    url = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/reset-password?token={token}"
    html = _account_email(
        title="Réinitialisation de votre mot de passe",
        greeting=full_name,
        body=(
            "<p>Nous avons reçu une demande de réinitialisation du mot de passe "
            "associé à ce compte.</p>"
        ),
        cta_label="Choisir un nouveau mot de passe",
        cta_url=url,
        footer=(
            "Ce lien est valable 1 heure et ne peut servir qu'une fois. Si vous n'êtes pas "
            "à l'origine de cette demande, ignorez ce message : votre mot de passe reste inchangé."
        ),
    )
    return await send_email(to_email, "PIQBIT — Réinitialisation de votre mot de passe", html)


async def send_technical_test_invitation(
    *,
    to_email: str,
    candidate_name: str,
    job_title: str,
    token: str,
    question_count: int,
    duration_minutes: int,
    expires_at: datetime | None = None,
) -> bool:
    """
    Invitation à passer le test technique.

    Ce qui est annoncé au candidat, et rien d'autre : le nombre de questions,
    la durée GLOBALE, et le fait que la progression est définitive. Le budget de
    temps par question n'est pas mentionné — il ne bloque rien et n'entre pas
    dans la note.
    """
    from app.services.interview_service import _frontend_base_url

    url = f"{_frontend_base_url()}/test/{token}"
    exp = ""
    if expires_at:
        exp = (f"<p style='color:#9CA3AF;font-size:.82rem;margin-top:16px;'>"
               f"⏰ Ce lien est valable jusqu'au {formater_date_heure(expires_at)}.</p>")

    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#18534F;color:#FEEAA1;padding:28px;border-radius:12px 12px 0 0;text-align:center;'>
        <h2 style='margin:0;font-size:1.5rem;letter-spacing:-.02em;'>Test technique</h2>
        <p style='margin:8px 0 0;color:rgba(254,234,161,.78);font-size:.92rem;'>{job_title}</p>
      </div>
      <div style='background:#FFFFFF;padding:32px 28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{candidate_name}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.55;color:#1F2937;'>Votre candidature pour le poste de
           <strong>{job_title}</strong> a retenu notre attention. Avant l'entretien, nous vous
           proposons un court test technique.</p>
        <div style='background:#F6FBFA;border:1px solid #DCEDEA;border-radius:10px;padding:16px 18px;margin:22px 0;'>
          <p style='margin:0 0 6px;font-size:14px;color:#1F2937;'><strong>{question_count} questions</strong> à choix multiple</p>
          <p style='margin:0 0 6px;font-size:14px;color:#1F2937;'><strong>{duration_minutes} minutes</strong> au total</p>
          <p style='margin:0;font-size:14px;color:#1F2937;'>Une seule tentative — pensez à vous installer au calme</p>
        </div>
        <p style='font-size:13.5px;line-height:1.55;color:#6B7280;'>Vous avancez question par question, sans retour
           en arrière : chaque réponse est définitive. Un bouton « Passer » vous permet d'avancer
           sans répondre, il compte alors comme une erreur.</p>
        <div style='text-align:center;margin:28px 0;'>
          <a href="{url}" style='display:inline-block;padding:14px 30px;background:#18534F;color:#FEEAA1;
             border-radius:50px;font-weight:700;text-decoration:none;font-size:15px;'>
            Commencer le test
          </a>
        </div>
        <p style='font-size:12.5px;color:#9CA3AF;word-break:break-all;'>Si le bouton ne fonctionne pas :<br>{url}</p>
        {exp}
      </div>
    </div>
    """
    return await send_email(to_email, f"PIQBIT — Test technique : {job_title}", html)


async def send_technical_test_completed(
    *,
    to_email: str,
    recipient_name: str,
    candidate_name: str,
    job_title: str,
    application_id,
    score: float | None,
    correct_count: int | None,
    question_count: int,
    outcome: str,
) -> bool:
    """
    Alerte au RH : un candidat vient de terminer son test technique.

    Adressée au RH qui a envoyé le test et aux administrateurs. Elle porte la
    note, parce que c'est elle qui décide si l'on enchaîne sur un entretien —
    mais aucun détail de réponse : ceux-là se consultent dans le back-office,
    derrière l'authentification.

    `outcome` distingue les trois fins possibles. Un test « terminé » et un test
    « interrompu par le temps » ne se lisent pas de la même façon, et un lien
    jamais ouvert encore moins.
    """
    from app.services.interview_service import _frontend_base_url

    url = f"{_frontend_base_url()}/admin/assessment?application={application_id}"

    fins = {
        "TERMINE": ("a terminé son test", "#18534F", "#F6FBFA", "#DCEDEA"),
        "EXPIRE": ("a été interrompu par la fin du temps imparti",
                   "#8A5A16", "#FDF6EA", "#F0DDBB"),
        "ABANDONNE": ("n'a jamais ouvert son lien de test — celui-ci a expiré",
                      "#8A3232", "#FDF0EE", "#F2D4CF"),
    }
    phrase, teinte, fond, bord = fins.get(outcome, fins["TERMINE"])

    if score is None:
        bloc_note = (
            "<p style='margin:0;font-size:14px;color:#1F2937;'>"
            "Aucune réponse n'a été enregistrée.</p>"
        )
    else:
        detail = (f" — {correct_count} bonne(s) réponse(s) sur {question_count}"
                  if correct_count is not None else "")
        bloc_note = (
            f"<p style='margin:0;font-size:22px;font-weight:800;color:{teinte};'>"
            f"{score:.0f}<span style='font-size:14px;font-weight:600;color:#6B7280;'>/100</span></p>"
            f"<p style='margin:4px 0 0;font-size:13px;color:#6B7280;'>"
            f"Score du test{detail}</p>"
        )

    html = f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:{teinte};color:#FFFFFF;padding:26px;border-radius:12px 12px 0 0;'>
        <h2 style='margin:0;font-size:1.35rem;letter-spacing:-.02em;'>Test technique rendu</h2>
        <p style='margin:8px 0 0;color:rgba(255,255,255,.8);font-size:.92rem;'>{job_title}</p>
      </div>
      <div style='background:#FFFFFF;padding:30px 28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{recipient_name}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.55;color:#1F2937;'>
          <strong>{candidate_name}</strong> {phrase} pour le poste de <strong>{job_title}</strong>.
        </p>
        <div style='background:{fond};border:1px solid {bord};border-radius:10px;padding:18px;margin:22px 0;text-align:center;'>
          {bloc_note}
        </div>
        <p style='font-size:13.5px;line-height:1.55;color:#6B7280;'>
          Le détail des réponses, la réussite par compétence et les temps de réponse
          sont consultables dans le back-office. Le candidat, lui, ne voit ni sa note
          ni sa correction.
        </p>
        <div style='text-align:center;margin:26px 0 8px;'>
          <a href="{url}" style='display:inline-block;padding:13px 28px;background:{teinte};color:#FFFFFF;
             border-radius:50px;font-weight:700;text-decoration:none;font-size:14.5px;'>
            Voir les résultats
          </a>
        </div>
      </div>
    </div>
    """
    return await send_email(
        to_email, f"PIQBIT — Test rendu : {candidate_name} · {job_title}", html
    )


# ── Vivier « en réserve » ──────────────────────────────────────────

async def send_talent_pool_notice(*, to_email: str, candidate_name: str, job_title: str) -> bool:
    """Informe le candidat que sa candidature est conservée en réserve."""
    nom, poste = escape(candidate_name), escape(job_title)
    corps = f"""
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{nom}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.6;color:#1F2937;'>Merci pour votre candidature au poste de
           <strong>{poste}</strong>. Votre profil a retenu notre attention, mais nous ne pouvons pas
           vous proposer ce poste pour le moment.</p>
        <p style='font-size:14.5px;line-height:1.6;color:#1F2937;'>Nous conservons donc votre candidature
           <strong>en réserve</strong>. Dès qu'une offre correspondant à votre profil sera ouverte, nous vous
           l'enverrons par e-mail, avec un lien pour postuler directement.</p>
        <p style='font-size:13px;line-height:1.55;color:#6B7280;margin-top:18px;'>Vous n'avez rien à faire de
           votre côté. Si vous ne souhaitez plus être contacté, répondez simplement à cet e-mail.</p>
    """
    return await send_email(to_email, f"Votre candidature est conservée — {job_title}",
                            _cadre_contrat("Votre candidature est conservée", poste, corps))


async def send_talent_pool_offers(*, to_email: str, candidate_name: str, offres: list[dict]) -> bool:
    """Invite un candidat en réserve à postuler aux offres qui correspondent à son profil."""
    nom = escape(candidate_name)
    lignes = "".join(
        f"""<div style='padding:14px 16px;margin:0 0 10px;border:1px solid #E5E7EB;border-radius:10px;'>
              <p style='margin:0 0 6px;font-size:15px;font-weight:700;color:#18534F;'>{escape(o["title"])}</p>
              {f"<p style='margin:0 0 10px;font-size:13px;color:#4B5563;'>{escape(o['reasons'][0])}</p>" if o.get("reasons") else ""}
              <a href="{escape(o["url"])}" style='display:inline-block;padding:9px 20px;background:#18534F;color:#FEEAA1;
                 border-radius:50px;font-weight:700;text-decoration:none;font-size:13.5px;'>Voir l'offre et postuler</a>
            </div>"""
        for o in offres
    )
    pluriel = len(offres) > 1
    corps = f"""
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{nom}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.6;color:#1F2937;'>Comme promis, votre candidature est restée
           dans notre vivier. {"De nouvelles offres correspondent" if pluriel else "Une nouvelle offre correspond"}
           à votre profil — nous vous invitons à y postuler :</p>
        {lignes}
        <p style='font-size:13px;line-height:1.55;color:#6B7280;margin-top:18px;'>Vous recevez ce message parce que
           votre candidature a été placée en réserve. Pour ne plus être contacté, répondez simplement à cet e-mail.</p>
    """
    titre = "Des offres pour vous" if pluriel else "Une offre pour vous"
    return await send_email(to_email, f"PIQBIT — {titre}", _cadre_contrat(titre, "Selon votre profil", corps))


# ── Contrats ───────────────────────────────────────────────────────

def _cadre_contrat(titre: str, sous_titre: str, corps: str) -> str:
    """Gabarit commun aux e-mails de contrat, dans le style des invitations d'entretien."""
    return f"""
    <div style='font-family:Inter,Arial,sans-serif;max-width:600px;margin:auto;'>
      <div style='background:#18534F;color:#FEEAA1;padding:28px;border-radius:12px 12px 0 0;text-align:center;'>
        <h2 style='margin:0;font-size:1.5rem;letter-spacing:-.02em;'>{titre}</h2>
        <p style='margin:8px 0 0;color:rgba(254,234,161,.78);font-size:.92rem;'>{sous_titre}</p>
      </div>
      <div style='background:#FFFFFF;padding:32px 28px;border:1px solid #ECF8F6;border-top:none;border-radius:0 0 12px 12px;'>
        {corps}
        <hr style='border:none;border-top:1px solid #ECF8F6;margin:24px 0;'/>
        <p style='color:#9CA3AF;font-size:.82rem;margin:0;'>Cordialement,<br/>L'équipe Recrutement — PIQBIT</p>
      </div>
    </div>
    """


async def send_contract_to_sign(
    *, to_email: str, candidate_name: str, job_title: str, sign_url: str,
    expires_at: datetime | None = None,
) -> bool:
    """Envoie au candidat le lien de signature électronique de son contrat."""
    nom, poste = escape(candidate_name), escape(job_title)
    validite = (f"<p style='color:#9CA3AF;font-size:.82rem;margin-top:16px;'>⏰ Ce lien est valable jusqu'au "
                f"{formater_date_heure(expires_at)}.</p>") if expires_at else ""
    corps = f"""
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{nom}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.55;color:#1F2937;'>Félicitations : votre contrat de travail pour le poste de
           <strong>{poste}</strong> est prêt. Relisez-le, puis signez-le en ligne — cela prend une minute.</p>
        <div style='text-align:center;margin:28px 0;'>
          <a href="{sign_url}" style='display:inline-block;padding:14px 30px;background:#18534F;color:#FEEAA1;
             border-radius:50px;font-weight:700;text-decoration:none;font-size:15px;'>✍️ Lire et signer mon contrat</a>
        </div>
        <p style='font-size:13px;color:#6B7280;text-align:center;margin:8px 0;'>ou copiez ce lien :<br/>
          <span style='font-family:monospace;font-size:12px;color:#18534F;word-break:break-all;'>{sign_url}</span></p>
        {validite}
        <p style='font-size:12.5px;color:#6B7280;margin-top:18px;'>Ce lien vous est personnel : ne le transférez pas.</p>
    """
    return await send_email(to_email, f"Votre contrat à signer — {job_title}",
                            _cadre_contrat("Votre contrat est prêt", poste, corps))


async def send_contract_signed(
    *, to_email: str, candidate_name: str, job_title: str, pdf: bytes | None, reference: str,
) -> bool:
    """Confirme la signature au candidat et lui transmet son exemplaire signé (PDF)."""
    nom, poste = escape(candidate_name), escape(job_title)
    piece = ("<p style='font-size:14.5px;color:#1F2937;'>Votre exemplaire signé, avec son certificat de signature, "
             "est joint à cet e-mail.</p>") if pdf else ""
    corps = f"""
        <p style='margin:0 0 16px;font-size:15px;'>Bonjour <strong>{nom}</strong>,</p>
        <p style='font-size:14.5px;line-height:1.55;color:#1F2937;'>Votre contrat pour le poste de <strong>{poste}</strong>
           est signé. Bienvenue chez PIQBIT !</p>
        {piece}
        <p style='font-size:13px;color:#6B7280;'>Référence du contrat : <strong>{escape(reference)}</strong></p>
    """
    pieces = [(f"Contrat_PIQBIT_{reference}.pdf", pdf, "application/pdf")] if pdf else None
    return await send_email(to_email, f"Contrat signé — {job_title}",
                            _cadre_contrat("Contrat signé 🎉", poste, corps), pieces)
