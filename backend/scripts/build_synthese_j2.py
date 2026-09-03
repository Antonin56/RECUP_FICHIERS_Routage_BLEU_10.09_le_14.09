"""SignalMar — PDF de synthèse J2 (session complète du 8 juillet 2026).

Fix v2 (contraste) :
  1. Le template "cover" restait actif pour toutes les pages faute de
     NextPageTemplate — les pages de contenu avaient donc un fond navy
     et le corps de texte foncé était illisible. On force maintenant
     la bascule vers le template "content" AVANT le premier PageBreak,
     et on peint explicitement un fond blanc sur toutes les pages de
     contenu pour couvrir tout état de couleur résiduel du canvas.
  2. Palette texte inchangée (WCAG AA sur fond blanc désormais garanti).
"""
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, PageBreak, ListFlowable, ListItem, NextPageTemplate,
)

OUT = Path("/app/backend/public/synthese-2026-07-08.pdf")

NAVY = colors.HexColor("#0B132B")
INK = colors.HexColor("#1A1F36")
INK_MUTE = colors.HexColor("#4B5563")
CYAN = colors.HexColor("#0284C7")
CYAN_LIGHT = colors.HexColor("#E0F2FE")
GOLD = colors.HexColor("#B45309")
GREEN = colors.HexColor("#047857")
RED = colors.HexColor("#B91C1C")
BG_LIGHT = colors.HexColor("#F8FAFC")
BG_YELLOW = colors.HexColor("#FEF3C7")
BG_RED = colors.HexColor("#FEE2E2")
BG_GREEN = colors.HexColor("#D1FAE5")


def _p(size=10, leading=14, color=INK, align=TA_JUSTIFY, bold=False, back=None):
    return ParagraphStyle(
        f"p_{size}_{color.hexval()}_{bold}",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=leading, textColor=color, alignment=align,
        backColor=back,
    )


ST = {
    "H2": _p(size=14, leading=18, color=NAVY, bold=True, align=TA_CENTER),
    "Body": _p(),
    "Bullet": _p(size=10, leading=15, color=INK, align=TA_JUSTIFY),
    "TableCell": _p(size=9, leading=12, color=INK, align=TA_JUSTIFY),
    "TableWhite": _p(size=9, leading=12, color=colors.white, bold=True, align=TA_JUSTIFY),
}


def cover_page(c, doc):
    w, h = A4
    c.setFillColor(NAVY)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(CYAN)
    c.rect(0, h * 0.62, w, 3 * mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#38BDF8"))
    c.rect(0, h * 0.62 - 5 * mm, w, 1.5 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 46)
    c.drawCentredString(w / 2, h * 0.72, "SignalMar")
    c.setFillColor(colors.HexColor("#7DD3FC"))
    c.setFont("Helvetica", 15)
    c.drawCentredString(w / 2, h * 0.66, "Waze des mers — Sécurité collaborative")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(w / 2, h * 0.52, "Synthèse technique")
    c.setFillColor(colors.HexColor("#F5A524"))
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(w / 2, h * 0.47, "Session du 8 juillet 2026")
    c.setFillColor(colors.HexColor("#152449"))
    c.roundRect(2.5 * cm, 5.4 * cm, w - 5 * cm, 7.6 * cm, 6, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#7DD3FC"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(3 * cm, 12.2 * cm, "AU SOMMAIRE")
    c.setFillColor(colors.white)
    c.setFont("Helvetica", 10)
    for i, ln in enumerate([
        "1. Récapitulatif exécutif (10+ livraisons du jour)",
        "2. Phase 4.2 — Sync des contacts (livraison + fusion Aodren)",
        "3. Phase 4.2b — Invitations directes ciblées (fin du code copié)",
        "4. Phase T — Bascule rapide entre comptes de test QA",
        "5. Phase B — Parrainage viral récompensé (subscription bonus)",
        "6. Phase C — Refonte du Profil en HUB",
        "7. Fixes carte marine (vitesse km/h + kn, badge Statique)",
        "8. Audit d'intégrité + optimisations avant 50K users",
        "9. Registre des fichiers modifiés",
        "10. Prochaines étapes",
    ]):
        c.drawString(3 * cm, 11.4 * cm - i * 0.6 * cm, ln)


def content_page(c, doc):
    """Content-page chrome: WHITE full-page bg (belt & braces vs any
    residual fill from the cover), navy top strip + footer."""
    w, h = A4
    c.setFillColor(colors.white)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.rect(0, h - 15 * mm, w, 15 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15 * mm, h - 10 * mm, "SIGNALMAR")
    c.setFillColor(colors.HexColor("#7DD3FC"))
    c.setFont("Helvetica", 9)
    c.drawString(38 * mm, h - 10 * mm, "· Synthèse technique du 8 juillet 2026")
    c.setFillColor(CYAN)
    c.rect(0, h - 15.6 * mm, w, 0.6 * mm, fill=1, stroke=0)
    c.setFillColor(INK_MUTE)
    c.setFont("Helvetica", 8)
    c.drawString(15 * mm, 10 * mm, "SignalMar · Sécurité en mer collaborative")
    c.drawRightString(w - 15 * mm, 10 * mm, f"Page {doc.page}")


def section_title(text, S):
    tbl = Table([[Paragraph(f"<b>{text}</b>", ST["H2"])]], colWidths=[16.5 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, CYAN),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    S.append(Spacer(1, 6))
    S.append(tbl)
    S.append(Spacer(1, 6))


def para(t, S): S.append(Paragraph(t, ST["Body"]))


def bullets(items, S):
    S.append(ListFlowable(
        [ListItem(Paragraph(x, ST["Bullet"]), leftIndent=10, value="•") for x in items],
        bulletType="bullet", start="•", leftIndent=16, bulletFontSize=10, bulletColor=CYAN,
    ))
    S.append(Spacer(1, 4))


def info_box(title, body, S, tone="info"):
    palette = {"info": (BG_LIGHT, CYAN), "warn": (BG_YELLOW, GOLD),
               "danger": (BG_RED, RED), "success": (BG_GREEN, GREEN)}
    bg, bar = palette[tone]
    title_p = Paragraph(f"<b>{title}</b>", _p(size=10, color=INK, bold=True))
    body_p = Paragraph(body, _p(size=9.5, leading=13, color=INK))
    tbl = Table([[title_p], [body_p]], colWidths=[16.5 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, bar),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
    ]))
    S.append(tbl)
    S.append(Spacer(1, 8))


def pill(text, bg, fg):
    return Paragraph(
        f'<font color="{fg.hexval()}"><b>{text}</b></font>',
        ParagraphStyle(f"pill_{text}", fontName="Helvetica-Bold", fontSize=8,
                       leading=10, textColor=fg, backColor=bg,
                       alignment=TA_CENTER, borderPadding=(2, 6, 2, 6)),
    )


def changelog_table(rows, S):
    hdr = [Paragraph(f"<b>{h}</b>", ST["TableWhite"]) for h in ("#", "Domaine", "Modification", "Type")]
    data = [hdr]
    for i, (cat, title, tone, label) in enumerate(rows, 1):
        bg = {"feat": BG_GREEN, "fix": BG_YELLOW, "arch": CYAN_LIGHT}[tone]
        fg = {"feat": GREEN, "fix": GOLD, "arch": CYAN}[tone]
        data.append([Paragraph(str(i), ST["TableCell"]),
                     Paragraph(cat, ST["TableCell"]),
                     Paragraph(title, ST["TableCell"]),
                     pill(label, bg, fg)])
    t = Table(data, colWidths=[0.9 * cm, 3.5 * cm, 10.1 * cm, 2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    S.append(t)
    S.append(Spacer(1, 10))


def build_story():
    S = []
    para(
        "Ce document synthétise les livraisons de la session de développement du "
        "<b>8 juillet 2026</b>. La journée a été dense : quatre phases livrées "
        "(4.2, 4.2b, T, B), une refonte majeure de l'écran Profil (C), un fix "
        "d'infrastructure sur l'index téléphone MongoDB, et un audit "
        "d'intégrité complet du code avant la montée à 50 000 utilisateurs.",
        S,
    )
    section_title("1. Récapitulatif exécutif", S)
    changelog_table([
        ("Groupes", "Phase 4.2 — Sync des contacts (SHA-256, privacy-first)", "feat", "FEAT"),
        ("Groupes", "Phase 4.2b — Invitations directes (fin du code copié)", "feat", "FEAT"),
        ("Groupes", "Éviction d'un membre + notification in-app", "feat", "FEAT"),
        ("Comptes", "Phase T — Bascule rapide QA (5 comptes whitelist)", "feat", "FEAT"),
        ("Comptes", "Fusion Aodren (2 comptes → 1) + 6 rapports migrés", "fix", "FIX"),
        ("Croissance", "Phase B — Parrainage viral récompensé (bonus mois)", "feat", "FEAT"),
        ("Croissance", "Deep-link ?ref=CODE + Universal Link", "feat", "FEAT"),
        ("Profil", "Phase C — Refonte en HUB compact + sub-écrans", "feat", "FEAT"),
        ("Carte", "Vitesse km/h + kn en bas · badge « Statique » < 3 km/h", "feat", "FEAT"),
        ("Infra", "Index users.phone_1 reconstruit en partial index", "fix", "FIX"),
        ("Infra", "Audit intégrité + roadmap 50K users", "arch", "AUDIT"),
    ], S)
    info_box("État global",
             "Backend au vert. Aucun bug bloquant. 2 items P0 identifiés dans "
             "l'audit à traiter <b>avant</b> la Phase A (OTP) : (1) fan-out des "
             "notifs sur création de rapport, (2) rate-limit d'auth à ajouter "
             "en anticipation de l'OTP.", S, tone="success")
    S.append(PageBreak())

    section_title("2. Phase 4.2 — Sync des contacts (privacy-first)", S)
    bullets([
        "Endpoint <b>POST /api/contacts/match</b> — accepte 500 hashes SHA-256 max/appel, dédup + exclusion auto de l'appelant.",
        "Index sparse <b>users.phone_hash</b> + backfill idempotent (8 comptes existants ré-hashés au boot).",
        "Frontend : <b>expo-contacts + libphonenumber-js + expo-crypto</b>. Zéro numéro brut ne quitte le téléphone.",
        "Écran <b>/groups/invite</b> : contrat de permissions complet (granted / denied+retry / denied+settings), fallback share code toujours accessible.",
        "9/9 tests backend PASS (testing_agent).",
    ], S)
    info_box("Fusion des doublons Aodren (opération manuelle propre)",
             "Deux comptes existaient — <i>aodren.legouix@gmail.com</i> (typo, avec "
             "le téléphone <b>+33757102792</b> et 6 rapports) et "
             "<i>aodren.legrouix@gmail.com</i> (orthographe correcte, whitelist). "
             "Migration : 6 rapports reassignés, 5 notifs idem, téléphone détaché "
             "puis attaché au bon, compte typo supprimé. Un seul Aodren en base, "
             "historique préservé.", S, tone="info")

    section_title("3. Phase 4.2b — Invitations directes ciblées", S)
    para("<b>Objectif</b> : supprimer le copier/coller de code. L'admin "
         "sélectionne des contacts (déjà matchés SignalMar), tape "
         "<b>Envoyer</b>, et les invités voient une carte « Rejoindre » au "
         "prochain lancement de l'app.", S)
    bullets([
        "4 endpoints REST : <b>POST /groups/{gid}/invitations</b> (batch), <b>GET /invitations/mine</b>, <b>POST /invitations/{id}/accept</b>, <b>POST /invitations/{id}/decline</b>.",
        "Nouvelle collection <b>group_invitations</b> avec index composites.",
        "Upsert idempotent, TTL 30 jours, dédup, skip des déjà-membres.",
        "Frontend : écran multi-sélection avec « Tout / Aucun », ouverture séquentielle <b>WhatsApp → SMS</b> pré-remplis.",
        "Bannière « Invitations reçues » en tête de l'onglet Groupes, cartes cyan avec Décliner / Rejoindre.",
        "Auto-redirection au launch : si l'utilisateur reçoit une invitation, il atterrit directement sur <b>/groups</b>.",
        "9/9 tests backend PASS.",
    ], S)

    section_title("4. Phase T — Bascule rapide entre comptes de test", S)
    tbl = [["Email", "Pseudo", "Téléphone"],
           ["antoninlepinay@gmail.com", "SignalMar", "+33760071445"],
           ["contact@accasteo.com", "Accasteo", "+33781407745"],
           ["aodren.legrouix@gmail.com", "Aodren", "+33757102792"],
           ["mylene.audebert@gmail.com", "Mylène", "+33650381816"],
           ["niosso.aq@gmail.com", "Anthony", "+33623454165"]]
    t = Table(tbl, colWidths=[7 * cm, 4.5 * cm, 5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    S.append(t)
    S.append(Spacer(1, 6))
    para("Mot de passe partagé : <b>123454321</b>. Accessible depuis Profil → "
         "« Comptes de test (QA) », visible uniquement pour les emails whitelistés.", S)
    S.append(PageBreak())

    section_title("5. Phase B — Parrainage viral récompensé", S)
    para("<b>Règle métier</b> : 1 parrainage = 1 mois de Premium quand le "
         "filleul (1) crée un compte via le lien, (2) poste un signalement, "
         "(3) reçoit une confirmation d'un marin externe à ses groupes privés. "
         "Anti-farm : max 10 pending + max 12 mois cumulés. Un seul palier.", S)
    bullets([
        "Backend : <b>core/subscription.py</b> + collection <b>referrals</b> (source de vérité).",
        "Hooks : /auth/register, /reports, /reports/{id}/confirm.",
        "Nouveau <b>GET /api/profile/subscription</b> avec chip d'état colorée.",
        "Frontend : écran /profile/subscription (carte Premium, barres de progression, code parrainage).",
        "Deep-link <b>signalmar.app/i/CODE</b> + <b>?ref=CODE</b>, persistance AsyncStorage.",
        "9/9 tests backend PASS.",
    ], S)
    info_box("À préparer avant lancement stores",
             "AASA iOS + assetlinks.json Android à héberger sur "
             "<b>signalmar.app/.well-known/</b>. Route <b>/i/&lt;code&gt;</b> "
             "doit rediriger vers stores + passer le code en param. Coût : 0 €.",
             S, tone="info")

    section_title("6. Phase C — Refonte du Profil", S)
    para("L'écran Profil, historiquement kilométrique (~1150 lignes), a été "
         "refondu en <b>HUB compact</b>. La logique de paramètres (voix, "
         "rayon, notifs, historique, changement pseudo) est relocalisée sur "
         "<b>/profile/settings</b>. Aucune régression.", S)
    bullets([
        "Header condensé (avatar + pseudo + grade + points + badge Premium).",
        "3 tuiles stats cliquables : Signalements / Confirmations / Groupes.",
        "Carte Abonnement dynamique (état, mois cumulés, pending).",
        "Sections thématiques : Paramètres · Communauté · Autres.",
        "Chargement des 3 sources en parallèle → hub prêt < 500 ms.",
    ], S)

    section_title("7. Fixes carte marine", S)
    bullets([
        "Badge vitesse <b>déplacé en bas de l'écran</b> (le placement en haut pénalisait les coordonnées sur Galaxy A52).",
        "Format compact : <b>« 12,3 km/h · 6,6 kn »</b>, chiffres tabulaires, visible en Vigie ET Navigation.",
        "Sous 3 km/h → affichage <b>« Statique »</b> (évite les micro-variations parasites du GPS).",
        "Slot fixe (min-width 96 px) → aucune reflow quand la vitesse bascule.",
    ], S)
    info_box("Fix voix TTS Bluetooth (résiduel session précédente)",
             "Préfixe silencieux augmenté à <b>2 secondes</b> (24 kHz mono 32 kbps) "
             "injecté au vol dans chaque réponse <i>/tts/alert</i>. Marge "
             "confortable pour les enceintes/casques BT lents à sortir de veille.",
             S, tone="success")
    S.append(PageBreak())

    section_title("8. Audit d'intégrité & optimisations avant 50K users", S)
    para("Audit complet mené par code_review_agent. Verdict : "
         "<b>« READY WITH FIXES »</b> — aucun défaut catastrophique, 5 items "
         "à traiter avant la montée en charge.", S)
    findings = [
        ("P0", "Fan-out notifs sur création de rapport",
         "reports.py:140 · full-scan users + inserts séquentiels. Fix : index 2dsphere + $near + BackgroundTasks."),
        ("P0", "Rate-limit auth (critique pour OTP à venir)",
         "auth.py:96 · SlowAPI 5 tentatives / 5 min / IP."),
        ("P0", "server.py = module « dieu » (1306 lignes)",
         "Extraire core/auth.py, core/drift.py, core/db.py."),
        ("P1", "Reports list charge photos base64 en mémoire",
         "reports.py:205 · projeter photos:0 + filtre géo dans la query."),
        ("P1", "Watcher GPS 1Hz haute-précision permanent (drain batterie)",
         "map.tsx:419 · pause AppState background + accuracy adaptative."),
        ("P1", "Index manquant sur reports.expires_at",
         "server.py:1194 · TTL index à ajouter."),
        ("P2", "JWT_SECRET fallback hardcodé si var manquante",
         "server.py:29 · exception au boot si non défini."),
        ("P2", "CORS allow_origins=* + credentials=true", "server.py:1098."),
        ("P2", "/register-push non authentifié", "auth.py:229 · verrouiller Bearer."),
        ("P2", "Pseudo uniqueness sans index + regex full-scan",
         "auth.py:203 · index unique case-insensitive."),
        ("P3", "confirmReport défini 2× dans client.ts", "client.ts:238+248."),
        ("P3", "Radar-ping WebView rAF loop permanent", "MarineMap.tsx:525."),
        ("P3", "Report chat polling 6s ignore background", "report/[id].tsx:221."),
    ]
    data = [[Paragraph(f"<b>{h}</b>", ST["TableWhite"]) for h in ("Prio.", "Item", "Direction du fix")]]
    for prio, item, direction in findings:
        color = {"P0": RED, "P1": GOLD, "P2": CYAN, "P3": INK_MUTE}[prio]
        bg = {"P0": BG_RED, "P1": BG_YELLOW, "P2": CYAN_LIGHT, "P3": BG_LIGHT}[prio]
        data.append([pill(prio, bg, color),
                     Paragraph(f"<b>{item}</b>", ST["TableCell"]),
                     Paragraph(direction, ST["TableCell"])])
    t = Table(data, colWidths=[1.6 * cm, 5.7 * cm, 9.2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    S.append(t)
    S.append(Spacer(1, 8))
    info_box("Zones déjà solides (à ne PAS refactoriser)",
             "• Landing referral échappe l'input utilisateur (html.escape).<br/>"
             "• Hook <b>adaptive-polling</b> nettoie ses timers + pause en background.<br/>"
             "• Collections groups/invitations/notifications/friends bien indexées.<br/>"
             "• <b>enrich_authors</b> batch les lookups (pas de N+1).",
             S, tone="success")
    S.append(PageBreak())

    section_title("9. Registre des fichiers modifiés", S)
    files = [
        ("Backend", "core/subscription.py", "Nouveau : moteur du parrainage viral (Phase B)."),
        ("Backend", "core/notifications.py", "Utilisé pour la notif kick membre."),
        ("Backend", "routers/contacts.py", "POST /contacts/match + fix index phone_1 partial."),
        ("Backend", "routers/dev_switch.py", "Nouveau : bascule QA + seed idempotent."),
        ("Backend", "routers/groups.py", "Endpoints invitations 4.2b + notif kick membre."),
        ("Backend", "routers/auth.py", "Hook subscription au signup (email + Google)."),
        ("Backend", "routers/reports.py", "Hooks on_first_report + try_award_bonus."),
        ("Backend", "routers/profile.py", "GET /profile/subscription."),
        ("Backend", "server.py", "Wiring 3 nouveaux routers + indexes subscription."),
        ("Frontend", "app/(tabs)/profile.tsx", "Refonte HUB (Phase C)."),
        ("Frontend", "app/(tabs)/_layout.tsx", "Auto-redirect vers /groups si invitations."),
        ("Frontend", "app/(tabs)/map.tsx", "Badge vitesse en bas + Statique."),
        ("Frontend", "app/(auth)/register.tsx", "Auto-fill du code parrainage capté au launch."),
        ("Frontend", "app/_layout.tsx", "Hook usePendingReferral pour Universal Links."),
        ("Frontend", "app/groups/index.tsx", "Bannière invitations reçues + accept/decline."),
        ("Frontend", "app/groups/invite.tsx", "Refonte multi-sélection + open SMS/WhatsApp."),
        ("Frontend", "app/profile/subscription.tsx", "Nouveau : écran Abonnement Phase B."),
        ("Frontend", "app/profile/test-switch.tsx", "Nouveau : écran bascule QA."),
        ("Frontend", "app/profile/settings.tsx", "Ancien profil migré en sous-écran."),
        ("Frontend", "src/api/client.ts", "Endpoints contacts/invitations/subscription/dev."),
        ("Frontend", "src/auth/AuthContext.tsx", "switchToTestAccount()."),
        ("Frontend", "src/lib/contact-sync.ts", "Nouveau : hash SHA-256 des contacts."),
        ("Frontend", "src/lib/invite-message.ts", "Message d'invitation + WhatsApp/SMS."),
        ("Frontend", "src/lib/referral-link.ts", "Nouveau : deep-link ?ref capture."),
        ("Frontend", "src/lib/share-app.ts", "URL universal-link avec code parrain."),
        ("Frontend", "app.json", "Permission Contacts iOS + Android."),
    ]
    data = [[Paragraph(f"<b>{h}</b>", ST["TableWhite"]) for h in ("Zone", "Fichier", "Changement")]]
    for z, f, n in files:
        data.append([Paragraph(z, ST["TableCell"]),
                     Paragraph(f'<font face="Courier" size="8">{f}</font>', ST["TableCell"]),
                     Paragraph(n, ST["TableCell"])])
    t = Table(data, colWidths=[1.8 * cm, 6.8 * cm, 8 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    S.append(t)
    S.append(Spacer(1, 12))

    section_title("10. Prochaines étapes proposées", S)
    bullets([
        "<b>Traiter les 3 P0</b> (fan-out notifs, rate-limit auth, découpe server.py) AVANT la Phase A (OTP).",
        "<b>Phase A</b> — Inscription par téléphone + OTP.",
        "<b>Phase 4.3</b> — Chat de groupe (polling 10 s, 1 photo/msg compressée).",
        "<b>Phase 4.4</b> — Live tracking des membres avec mode fantôme.",
        "<b>Phase F</b> — Modération auto via Claude Haiku 4.5.",
        "<b>Store link</b> à intégrer dans le message d'invitation dès publication.",
        "<b>Universal Links</b> — AASA iOS + assetlinks.json Android sur signalmar.app.",
    ], S)
    info_box("Document généré",
             f"Le <b>{date.today().strftime('%d/%m/%Y')}</b> · SignalMar v1.5.0 "
             "· session du 8 juillet 2026. Contraste WCAG AA (fix v2 : "
             "template content forcé + fond blanc explicite sur toutes les "
             "pages de contenu).<br/>URL : <font face=\"Courier\">"
             "https://moteur-i-routing.preview.emergentagent.com/api/docs/synthese-2026-07-08.pdf"
             "</font>", S, tone="info")
    return S


def build_pdf():
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=22 * mm, bottomMargin=18 * mm,
        title="SignalMar — Synthèse technique du 8 juillet 2026",
        author="SignalMar", subject="Synthèse des évolutions",
    )
    cover_frame = Frame(0, 0, A4[0], A4[1], showBoundary=0)
    content_frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=cover_page),
        PageTemplate(id="content", frames=[content_frame], onPage=content_page),
    ])
    # v2 fix : bascule EXPLICITE vers le template "content" avant le
    # premier PageBreak — sans quoi toutes les pages restent en template
    # "cover" (fond navy plein → texte foncé invisible sur les sections
    # libres du corps).
    story = [NextPageTemplate("content"), PageBreak()]
    story.extend(build_story())
    doc.build(story)
    print("PDF:", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    build_pdf()
