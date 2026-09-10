"""Convert a rendered daily brief (browser HTML) into email-safe HTML.

The browser templates lean on things no mail client honours: a <style> block,
CSS custom properties, flexbox/grid, and inline SVG. Outlook throws all of it
away, which is why a sent brief can arrive as unstyled text on a dark-mode
background. This module re-emits the same design as nested tables with literal
colours inlined on every element, and locks the colour scheme to light.

    from emailify import emailify
    email_html = emailify(open(path, encoding="utf-8").read())

Parsing is by CSS class, so this file tracks both templates/daily_brief.html
(CoherentConnect) and templates/daily_brief_coherentlead.html (CoherentLead).
The two brands share almost all section classes (.prospect, .caps, .story, …)
but use different colour palettes and logo markup (CoherentConnect: inline
<svg class="mark">, which Outlook can't render, so it's replaced by a glyph;
CoherentLead: a real <img class="mark" src="…cl-logo.png">, which DOES render
in every major client — Gmail/Outlook/Apple Mail/Yahoo all support base64 PNG
— so it is inlined as a data: URI instead of being discarded). The brand is
auto-detected from the source HTML; pass `brand=` explicitly to override.

Any block this module does not recognise is skipped rather than half-rendered.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from bs4 import BeautifulSoup

_HERE = os.path.dirname(__file__)

# Webfonts don't load in most clients — fall back to what's installed.
SERIF = "Georgia,'Times New Roman',Times,serif"
SANS  = "'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO  = "Consolas,'Courier New',Courier,monospace"

WIDTH = 660
PAD   = "0 40px"   # matches the templates' body inset


# ---------------------------------------------------------------- palette --
@dataclass(frozen=True)
class Palette:
    ink: str        # near-black — masthead/footer/take backgrounds, headline text
    accent: str      # brand accent — labels, eyebrows, CTAs, hairline-adjacent highlights
    sage: str        # secondary "verified/action" accent (green in both brands today)
    chalk: str       # the sheet's off-white background
    paper: str = "#FFFFFF"
    outer: str = "#E9E4D8"
    muted: str = "#6C6A62"
    faint: str = "#9A978C"
    hair: str = "#E2DDD0"
    hair_dk: str = "#33322F"
    logo_path: str | None = None   # repo-relative path to a PNG logo, or None → synth glyph


COHERENTCONNECT = Palette(
    ink="#18181B", accent="#AD7145", sage="#2D6A4F", chalk="#F9F8F3",
    logo_path=None,   # CoherentConnect's masthead mark is inline SVG — no static PNG to embed
)
COHERENTLEAD = Palette(
    ink="#1A1410", accent="#D2541C", sage="#2D6A4F", chalk="#FFFCF6",
    outer="#F0EAE0", muted="#6E6459", faint="#A39A8C", hair="#E7DFD1", hair_dk="#332B23",
    logo_path="assets/cl-logo.png",
)

_BRANDS = {"coherentconnect": COHERENTCONNECT, "coherentlead": COHERENTLEAD}


def _detect_brand(soup) -> Palette:
    """CoherentLead's markup is the only one with a real <img class="mark"> logo and/or
    the literal wordmark 'CoherentLead' / 'Coherent<span class="cx">Lead</span>' — anything
    else (including CMI, which reuses CoherentConnect's card/caps classes) falls back to the
    CoherentConnect palette, which was this file's only palette before CoherentLead existed."""
    wordmark = soup.select_one(".wordmark")
    text = wordmark.get_text(" ", strip=True) if wordmark else ""
    title = soup.select_one("title")
    title_text = title.get_text(" ", strip=True) if title else ""
    if "coherentlead" in (text + title_text).lower().replace(" ", ""):
        return COHERENTLEAD
    return COHERENTCONNECT


LOGO_CID = "brand-logo"   # Content-ID this file's <img> tags reference; send_brief.py
                          # must attach the matching inline image under this same cid.


def _logo_src(pal: Palette) -> str | None:
    """cid: reference for the brand logo, or None if this brand has no static PNG.

    Deliberately NOT a data: URI: SendGrid's relay (and some other ESPs) rewrites or
    strips base64-embedded <img src> content in transit — confirmed by a live send
    where the HTML validated locally (correct PNG signature, correct bytes) but the
    logo still failed to render as a broken image once delivered through SendGrid.
    A cid:-referenced inline attachment is the standard MIME mechanism every major
    ESP and client (including Outlook, which never supported data: URIs reliably)
    is built to pass through untouched.
    """
    if not pal.logo_path:
        return None
    return f"cid:{LOGO_CID}"


def logo_bytes(pal: Palette) -> bytes | None:
    """Raw PNG bytes for the brand logo, for the caller to attach as a cid: inline part."""
    if not pal.logo_path:
        return None
    path = os.path.join(_HERE, pal.logo_path)
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


# ------------------------------------------------------------- utilities --
def _inner(el, pal: Palette) -> str:
    """Inner HTML of a tag, with <a> restyled for mail clients."""
    if el is None:
        return ""
    for a in el.find_all("a"):
        a["style"] = f"color:{pal.accent};text-decoration:underline;"
    return el.decode_contents().strip()


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el is not None else ""


def _row(pal: Palette, content: str, pad: str = PAD, bg: str | None = None) -> str:
    """One full-width row of the 660px sheet."""
    bg = bg or pal.chalk
    return (
        f'<tr><td bgcolor="{bg}" style="background-color:{bg};padding:{pad};">'
        f"{content}</td></tr>"
    )


def _p(pal: Palette, html: str, size="14.5px", color="#33322B", margin="0 0 16px", extra="") -> str:
    return (
        f'<p style="margin:{margin};font-family:{SANS};font-size:{size};'
        f"line-height:1.6;color:{color};mso-line-height-rule:exactly;{extra}\">{html}</p>"
    )


def _label(pal: Palette, text: str, color: str | None = None, size="10px", margin="0 0 5px") -> str:
    color = color or pal.accent
    return (
        f'<div style="margin:{margin};font-family:{SANS};font-size:{size};font-weight:700;'
        f'letter-spacing:.16em;text-transform:uppercase;color:{color};">{text}</div>'
    )


def _spacer(h: int) -> str:
    return f'<div style="line-height:{h}px;font-size:{h}px;height:{h}px;">&nbsp;</div>'


# --------------------------------------------------------------- sections --
def _masthead(soup, pal: Palette) -> str:
    head = soup.select_one("header.masthead")
    if head is None:
        return ""
    wordmark = _text(head.select_one(".wordmark"))
    kicker_el = head.select_one(".kicker")
    small = kicker_el.select_one("small") if kicker_el else None
    sub = _text(small)
    if small:
        small.extract()
    kicker = _text(kicker_el)
    tag = _text(head.select_one(".tagstrip"))

    logo_src = _logo_src(pal)
    if logo_src:
        # A real PNG logo (CoherentLead) — renders natively in Gmail/Outlook/Apple
        # Mail/Yahoo via a cid: inline attachment, unlike the inline SVG this markup
        # uses in the browser template (which Outlook drops entirely).
        img_el = head.select_one("img.mark")
        w = (img_el.get("width") if img_el else None) or "34"
        h = (img_el.get("height") if img_el else None) or "34"
        mark = f'<img src="{logo_src}" width="{w}" height="{h}" alt="{wordmark}" style="display:inline-block;vertical-align:middle;">'
    else:
        # No static PNG for this brand (CoherentConnect ships its mark as inline SVG,
        # which Outlook drops entirely) — fall back to a two-tone glyph approximation.
        mark = (
            f'<span style="font-family:{SANS};font-size:22px;line-height:1;color:{pal.chalk};">&#10094;</span>'
            f'<span style="font-family:{SANS};font-size:22px;line-height:1;color:{pal.accent};">&#10095;</span>'
        )
    return f"""
<tr><td bgcolor="{pal.ink}" style="background-color:{pal.ink};padding:26px 40px 24px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td align="left" valign="middle" style="font-family:{SERIF};">
        {mark}&nbsp;&nbsp;<span style="font-family:{SERIF};font-size:24px;line-height:1;color:#FFFFFF;">{wordmark}</span>
      </td>
      <td align="right" valign="middle" style="font-family:{SANS};font-size:10.5px;font-weight:700;
          letter-spacing:.22em;text-transform:uppercase;color:{pal.accent};line-height:1.5;">
        {kicker}<br><span style="color:{pal.faint};font-weight:500;letter-spacing:.18em;">{sub}</span>
      </td>
    </tr>
  </table>
  {_spacer(20)}
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td height="1" bgcolor="{pal.hair_dk}" style="background-color:{pal.hair_dk};line-height:1px;font-size:1px;">&nbsp;</td></tr>
    <tr><td style="padding-top:16px;font-family:{SERIF};font-style:italic;font-size:15px;color:#D8D4CA;">{tag}</td></tr>
  </table>
</td></tr>"""


def _intro(soup, pal: Palette) -> str:
    out = []
    date = _text(soup.select_one(".datepill"))
    if date:
        out.append(
            f'<p style="margin:0 0 18px;font-family:{MONO};font-size:11.5px;letter-spacing:.14em;'
            f'text-transform:uppercase;color:{pal.accent};">{date}</p>'
        )
    hello = soup.select_one("h1.hello")
    if hello:
        out.append(
            f'<h1 style="margin:0 0 12px;font-family:{SERIF};font-weight:400;font-size:30px;'
            f'line-height:1.15;color:{pal.ink};">{_text(hello)}</h1>'
        )
    lede = soup.select_one("p.lede")
    if lede:
        out.append(_p(pal, _inner(lede, pal), size="15.5px", color="#38372F", margin="0 0 12px"))
    agent = soup.select_one("p.agentline")
    if agent:
        # left rule = a 2px table cell, since border-left on a <p> is unreliable
        out.append(f"""
<table role="presentation" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="2" bgcolor="{pal.accent}" style="background-color:{pal.accent};width:2px;line-height:1px;font-size:1px;">&nbsp;</td>
    <td style="padding-left:11px;font-family:{SANS};font-size:13px;line-height:1.6;color:{pal.muted};">{_inner(agent, pal)}</td>
  </tr>
</table>{_spacer(26)}""")
    return _row(pal, "".join(out), pad="34px 40px 0") if out else ""


def _top3(soup, pal: Palette) -> str:
    box = soup.select_one(".top3")
    if box is None:
        return ""
    rows = [f'<tr><td colspan="2" height="1" bgcolor="{pal.hair}" '
            f'style="background-color:{pal.hair};line-height:1px;font-size:1px;">&nbsp;</td></tr>']
    for r in box.select(".row"):
        idx = _text(r.select_one(".idx"))
        txt = r.select_one(".txt")
        cat_el = txt.select_one(".cat") if txt else None
        cat = ""
        if cat_el:
            cat = (
                f'<span style="font-family:{MONO};font-size:9.5px;font-weight:500;letter-spacing:.11em;'
                f'text-transform:uppercase;color:{pal.accent};border:1px solid {pal.hair};border-radius:3px;'
                f'padding:2px 7px;margin-right:9px;white-space:nowrap;">{_text(cat_el)}</span> '
            )
            cat_el.extract()
        rows.append(f"""
<tr>
  <td width="36" valign="top" style="padding:14px 14px 14px 0;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0">
      <tr><td width="22" height="22" align="center" valign="middle"
              style="width:22px;height:22px;border:1px solid {pal.accent};border-radius:11px;
                     font-family:{MONO};font-size:11px;font-weight:700;color:{pal.accent};">{idx}</td></tr>
    </table>
  </td>
  <td valign="top" style="padding:14px 0;font-family:{SANS};font-size:14.5px;line-height:1.6;color:#2C2B25;">
    {cat}{_inner(txt, pal)}
  </td>
</tr>
<tr><td colspan="2" height="1" bgcolor="{pal.hair}" style="background-color:{pal.hair};line-height:1px;font-size:1px;">&nbsp;</td></tr>""")
    table = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
             f'{"".join(rows)}</table>')
    return _row(pal, table, pad="0 40px 6px")


def _eyebrow(pal: Palette, label: str) -> str:
    # The rule must live in its own 1px-tall nested table. Putting bgcolor
    # straight on the outer <td> paints the cell's full height instead of a
    # hairline, which shows up as a solid block next to the label.
    inner = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td valign="middle" style="font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:.2em;
        line-height:1.2;text-transform:uppercase;color:{pal.accent};white-space:nowrap;
        mso-line-height-rule:exactly;padding:0 12px 0 0;">{label}</td>
    <td valign="middle" width="99%" style="width:99%;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td height="1" bgcolor="{pal.hair}"
                style="height:1px;background-color:{pal.hair};line-height:1px;font-size:1px;">&nbsp;</td></tr>
      </table>
    </td>
  </tr>
</table>"""
    # Spacing lives on the row's padding — Outlook drops margins set on tables.
    return _row(pal, inner, pad="44px 40px 18px")


def _kv_cell(pal: Palette, h: str, v: str) -> str:
    return (f'<td width="50%" valign="top" bgcolor="{pal.paper}" '
            f'style="background-color:{pal.paper};padding:13px 15px;border:1px solid {pal.hair};">'
            f'{_label(pal, h)}<div style="font-family:{SANS};font-size:13.5px;line-height:1.45;'
            f'color:{pal.ink};">{v}</div></td>')


def _plan(pal: Palette, ol) -> str:
    """An ordered action plan — CSS counters become real table cells."""
    if ol is None:
        return ""
    out = []
    head = ol.select_one(".planh")
    if head:
        out.append(_label(pal, _text(head), size="10px", margin="0 0 12px"))
    for i, li in enumerate(ol.find_all("li"), start=1):
        out.append(f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="40" valign="top" style="padding-right:14px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0">
        <tr><td width="26" height="26" align="center" valign="middle" bgcolor="{pal.ink}"
                style="background-color:{pal.ink};width:26px;height:26px;border-radius:13px;
                       font-family:{MONO};font-size:12px;color:{pal.chalk};">{i}</td></tr>
      </table>
    </td>
    <td valign="top" style="font-family:{SANS};font-size:13.5px;line-height:1.6;color:#33322B;">{_inner(li, pal)}</td>
  </tr>
</table>{_spacer(14)}""")
    return "".join(out)


def _prospect(pal: Palette, card) -> str:
    flag = _text(card.select_one(".flag"))
    name = _text(card.select_one("h2"))
    para = card.find("p", recursive=False) or card.find("p")
    cells = card.select(".grid2 .cell")
    action = card.select_one(".action")

    body = [
        f'<span style="display:inline-block;font-family:{MONO};font-size:10px;letter-spacing:.16em;'
        f'text-transform:uppercase;color:#FFFFFF;background-color:{pal.accent};padding:4px 9px;'
        f'border-radius:3px;">{flag}</span>',
        f'<h2 style="margin:14px 0 10px;font-family:{SERIF};font-weight:400;font-size:27px;'
        f'line-height:1.15;color:{pal.ink};">{name}</h2>',
        _p(pal, _inner(para, pal)),
    ]
    if cells:
        tds = "".join(_kv_cell(pal, _text(c.select_one(".h")), _text(c.select_one(".v"))) for c in cells)
        body.append(
            f'{_spacer(18)}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="border-collapse:collapse;"><tr>{tds}</tr></table>{_spacer(18)}'
        )
    if action:
        body.append(f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td bgcolor="#F1F5F2" style="background-color:#F1F5F2;border:1px solid #CBDDD2;padding:14px 16px;">
    {_label(pal, _text(action.select_one('.h')), color=pal.sage)}
    <div style="font-family:{SANS};font-size:13.5px;line-height:1.5;color:#26332C;">{_text(action.select_one('.v'))}</div>
  </td></tr>
</table>{_spacer(12)}""")
    body.append(_plan(pal, card.select_one("ol.plan")))

    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="3" bgcolor="{pal.accent}" style="background-color:{pal.accent};width:3px;line-height:1px;font-size:1px;">&nbsp;</td>
    <td bgcolor="{pal.paper}" style="background-color:{pal.paper};border:1px solid {pal.hair};border-left:0;padding:24px 26px;">
      {"".join(body)}
    </td>
  </tr>
</table>{_spacer(20)}"""


def _planbox(pal: Palette, box) -> str:
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="3" bgcolor="{pal.accent}" style="background-color:{pal.accent};width:3px;line-height:1px;font-size:1px;">&nbsp;</td>
    <td bgcolor="{pal.paper}" style="background-color:{pal.paper};border:1px solid {pal.hair};border-left:0;padding:22px 26px 8px;">
      {_plan(pal, box.select_one("ol.plan"))}
    </td>
  </tr>
</table>{_spacer(6)}"""


def _story(pal: Palette, st) -> str:
    out = [
        f'<h3 style="margin:0 0 9px;font-family:{SERIF};font-weight:400;font-size:20px;'
        f'line-height:1.25;color:{pal.ink};">{_text(st.select_one("h3"))}</h3>'
    ]
    for p in st.find_all("p"):
        if "soaction" in (p.get("class") or []):
            lbl_el = p.select_one(".lbl")
            lbl = _text(lbl_el)
            if lbl_el:
                lbl_el.extract()
            out.append(f"""
{_spacer(12)}<table role="presentation" cellpadding="0" cellspacing="0" border="0">
  <tr>
    <td width="2" bgcolor="{pal.accent}" style="background-color:{pal.accent};width:2px;line-height:1px;font-size:1px;">&nbsp;</td>
    <td style="padding-left:12px;">{_label(pal, lbl, margin="0 0 4px")}
      <div style="font-family:{SANS};font-size:14px;line-height:1.6;color:#2C2B25;">{_inner(p, pal)}</div>
    </td>
  </tr>
</table>""")
        else:
            out.append(_p(pal, _inner(p, pal), margin="0"))

    prov = st.select_one(".prov")
    if prov:
        src = _text(prov.select_one(".src"))
        date = _text(prov.select_one("span:not([class])"))
        verified = prov.select_one(".verified")
        bits = (f'<span style="color:{pal.accent};font-weight:500;">{src}</span>'
                f'<span style="color:{pal.faint};"> &middot; {date}</span>')
        if verified:
            bits += (f'&nbsp;&nbsp;<span style="color:{pal.sage};border:1px solid #B7CCC0;border-radius:10px;'
                     f'padding:2px 8px;background-color:#F1F5F2;">{_text(verified)}</span>')
        out.append(
            f'<div style="margin-top:10px;font-family:{MONO};font-size:10.5px;letter-spacing:.08em;'
            f'text-transform:uppercase;color:{pal.faint};">{bits}</div>'
        )

    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="padding:6px 0 20px;">{"".join(out)}</td></tr>'
            f'<tr><td height="1" bgcolor="{pal.hair}" style="background-color:{pal.hair};line-height:1px;'
            f'font-size:1px;">&nbsp;</td></tr></table>{_spacer(20)}')


def _take(pal: Palette, take) -> str:
    tag = _text(take.select_one(".tag"))
    para = take.select_one("p")
    for acc in take.select(".accent"):
        acc["style"] = f"color:{pal.accent};font-style:italic;font-family:{SERIF};"
    return f"""{_spacer(8)}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td bgcolor="{pal.ink}" style="background-color:{pal.ink};padding:24px 28px;">
    <div style="font-family:{SANS};font-size:10.5px;font-weight:700;letter-spacing:.2em;
        text-transform:uppercase;color:{pal.accent};margin-bottom:12px;">{tag}</div>
    <p style="margin:0;font-family:{SANS};font-size:14.5px;line-height:1.62;color:#DBD7CE;">{_inner(para, pal)}</p>
  </td></tr>
</table>{_spacer(6)}"""


def _seccta(pal: Palette, p) -> str:
    return (f'<p style="margin:16px 0 0;text-align:center;font-family:{SANS};font-size:12.5px;'
            f'line-height:1.6;color:{pal.muted};">{_inner(p, pal)}</p>')


def _caps(pal: Palette, caps) -> str:
    h3 = caps.select_one("h3")
    for em in h3.select("em"):
        em["style"] = f"color:{pal.accent};font-style:italic;"
    sub = _text(caps.select_one(".capsub"))

    stats = caps.select(".capgrid .cap")
    stat_rows = ""
    for i in range(0, len(stats), 2):
        tds = ""
        for c in stats[i:i + 2]:
            n = c.select_one(".n")
            sfx = n.select_one(".sfx")
            sfx_txt = _text(sfx)
            if sfx:
                sfx.extract()
            tds += (
                f'<td width="50%" valign="top" style="padding:0 12px 30px 0;">'
                f'<div style="font-family:{SERIF};font-size:36px;line-height:1;color:#FFFFFF;">'
                f'{_text(n)}<span style="font-size:18px;">{sfx_txt}</span></div>'
                f'<div style="margin-top:10px;font-family:{SANS};font-size:12.5px;line-height:1.4;'
                f'color:#8F8B81;">{_text(c.select_one(".l"))}</div></td>'
            )
        if len(stats[i:i + 2]) == 1:
            tds += '<td width="50%">&nbsp;</td>'
        stat_rows += f"<tr>{tds}</tr>"

    def card_html(cd, wide=False):
        ps = "".join(
            f'<p style="margin:0 0 10px;font-family:{SANS};font-size:12.5px;line-height:1.6;'
            f'color:#8F8B81;">{_inner(p, pal)}</p>' for p in cd.find_all("p")
        )
        return (
            f'{_label(pal, _text(cd.select_one(".cl")), size="9.5px", margin="0 0 9px")}'
            f'<h4 style="margin:0 0 7px;font-family:{SANS};font-weight:700;'
            f'font-size:{"16px" if wide else "14px"};line-height:1.35;color:#FFFFFF;">'
            f'{_text(cd.select_one("h4"))}</h4>{ps}'
        )

    narrow = [c for c in caps.select(".capcard") if "wide" not in (c.get("class") or [])]
    wide = [c for c in caps.select(".capcard") if "wide" in (c.get("class") or [])]
    card_rows = ""
    for i in range(0, len(narrow), 2):
        pair = narrow[i:i + 2]
        tds = "".join(
            f'<td width="50%" valign="top" style="padding:0 13px 26px 0;">{card_html(c)}</td>' for c in pair
        )
        if len(pair) == 1:
            tds += '<td width="50%">&nbsp;</td>'
        card_rows += f"<tr>{tds}</tr>"
    for c in wide:
        card_rows += (
            f'<tr><td colspan="2" valign="top" style="padding-top:22px;border-top:1px solid {pal.hair_dk};">'
            f'{card_html(c, wide=True)}</td></tr>'
        )

    # A divider that survives Outlook: spacer, 1px-tall row, spacer.
    divider = (
        f"{_spacer(28)}"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td height="1" bgcolor="{pal.hair_dk}" style="height:1px;background-color:{pal.hair_dk};'
        f'line-height:1px;font-size:1px;">&nbsp;</td></tr></table>{_spacer(28)}'
    )

    # .featable — CoherentLead-only key/value feature rows (Multichannel Outreach, AI
    # Builder, Data Scale, …). Absent from the CoherentConnect .caps block, so this is a
    # no-op there (caps.select returns []) and card_rows/stat_rows are untouched either way.
    feat_rows = caps.select(".featable .frow")
    feat_block = ""
    if feat_rows:
        rows_html = "".join(
            f'<tr>'
            f'<td width="150" valign="top" style="padding:16px 20px 16px 0;border-bottom:1px solid {pal.hair_dk};'
            f'font-family:{SANS};font-size:9.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;'
            f'color:{pal.accent};">{_text(r.select_one(".fk"))}</td>'
            f'<td valign="top" style="padding:16px 0;border-bottom:1px solid {pal.hair_dk};font-family:{SANS};'
            f'font-size:13.5px;line-height:1.6;color:#CFC6B7;">{_inner(r.select_one(".fv"), pal)}</td>'
            f'</tr>'
            for r in feat_rows
        )
        feat_block = (
            f"{divider}"
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows_html}</table>'
        )

    return f"""{_spacer(8)}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td bgcolor="{pal.ink}" style="background-color:{pal.ink};padding:34px 34px 28px;border-radius:14px;">
    <h3 style="margin:0 0 10px;font-family:{SERIF};font-weight:400;font-size:25px;line-height:1.25;
        color:#FFFFFF;">{_inner(h3, pal)}</h3>
    <p style="margin:0;font-family:{SANS};font-size:13.5px;line-height:1.6;color:#A8A49A;">{sub}</p>
    {divider}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{stat_rows}</table>
    {feat_block}
    {divider}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{card_rows}</table>
  </td></tr>
</table>{_spacer(6)}"""


def _quotes(pal: Palette, box) -> str:
    cards = box.select(".quote")
    tds = ""
    for i, q in enumerate(cards):
        if i:   # real gutter cell — border-spacing is ignored by Outlook
            tds += '<td width="16" style="width:16px;font-size:1px;line-height:1px;">&nbsp;</td>'
        tds += f"""
<td valign="top" bgcolor="{pal.paper}"
    style="background-color:{pal.paper};border:1px solid {pal.hair};border-top:2px solid {pal.accent};padding:20px 22px 18px;">
  <div style="font-family:{SERIF};font-size:16px;line-height:1.45;color:#2C2B25;">{_text(q.select_one("blockquote"))}</div>
  <div style="margin-top:14px;font-family:{MONO};font-size:10px;letter-spacing:.14em;
      text-transform:uppercase;color:{pal.accent};">{_text(q.select_one("figcaption"))}</div>
</td>"""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="border-collapse:separate;"><tr>{tds}</tr></table>')


def _footer(pal: Palette, soup) -> str:
    foot = soup.select_one("footer.foot")
    if foot is None:
        return ""
    assembled = _text(foot.select_one(".assembled"))
    sign = _text(foot.select_one(".sign"))
    meta = foot.select_one(".meta")
    for a in (meta.find_all("a") if meta else []):
        a["style"] = f"color:{pal.faint};text-decoration:underline;"

    btns = ""
    primary = foot.select_one("a.cta")
    if primary:
        btns += (
            f'<td style="padding:0 6px;"><a href="{primary.get("href", "#")}" target="_blank" '
            f'style="display:inline-block;background-color:{pal.accent};color:#FFFFFF;text-decoration:none;'
            f'font-family:{SANS};font-weight:600;font-size:14px;padding:12px 26px;border-radius:4px;">'
            f'{_text(primary)}</a></td>'
        )
    secondary = foot.select_one("a.cta2")
    if secondary:
        btns += (
            f'<td style="padding:0 6px;"><a href="{secondary.get("href", "#")}" target="_blank" '
            f'style="display:inline-block;color:#E7E4DB;text-decoration:none;font-family:{SANS};'
            f'font-weight:600;font-size:14px;padding:11px 24px;border-radius:4px;'
            f'border:1px solid #4A4844;">{_text(secondary)}</a></td>'
        )

    logo_src = _logo_src(pal)
    if logo_src:
        img_el = foot.select_one("img")
        w = (img_el.get("width") if img_el else None) or "30"
        h = (img_el.get("height") if img_el else None) or "30"
        mark = f'<img src="{logo_src}" width="{w}" height="{h}" alt="" style="display:inline-block;">'
    else:
        mark = (
            f'<span style="font-family:{SANS};font-size:20px;color:{pal.chalk};">&#10094;</span><span'
            f'      style="font-family:{SANS};font-size:20px;color:{pal.accent};">&#10095;</span>'
        )

    return f"""
<tr><td bgcolor="{pal.ink}" align="center" style="background-color:{pal.ink};padding:30px 40px 34px;">
  <div style="margin-bottom:14px;">
    {mark}
  </div>
  <p style="margin:0 0 16px;font-family:{SANS};font-size:11px;letter-spacing:.16em;
     text-transform:uppercase;color:{pal.faint};">{assembled}</p>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center"><tr>{btns}</tr></table>
  <p style="margin:20px 0 0;font-family:{SERIF};font-style:italic;font-size:14px;color:#E7E4DB;">{sign}</p>
  <p style="margin:6px 0 0;font-family:{SANS};font-size:11px;letter-spacing:.1em;
     text-transform:uppercase;color:{pal.faint};">{_inner(meta, pal)}</p>
</td></tr>"""


# ------------------------------------------------------------------ main --
def resolve_palette(html_or_brand: str | Palette) -> Palette:
    """Resolve a Palette from a brand name ("coherentconnect"/"coherentlead"), a
    Palette instance, or raw source HTML (auto-detected). Callers that need to attach
    the logo as a cid: inline part (e.g. send_brief.py) call this to find out whether
    a logo is expected at all (Palette.logo_path) and get its bytes via logo_bytes()."""
    if isinstance(html_or_brand, Palette):
        return html_or_brand
    if html_or_brand.strip().lower() in _BRANDS:
        return _BRANDS[html_or_brand.strip().lower()]
    return _detect_brand(BeautifulSoup(html_or_brand, "html.parser"))


def emailify(html: str, brand: str | Palette | None = None) -> str:
    """Convert a rendered brief to email-safe HTML.

    `brand` overrides auto-detection: pass "coherentconnect", "coherentlead", or a
    Palette instance directly. Leave unset to auto-detect from the source markup.

    If the resolved brand has a logo (Palette.logo_path), the output's <img> tags
    reference it via `cid:{LOGO_CID}` — the caller is responsible for attaching the
    actual image bytes (from `logo_bytes(pal)`) as a matching inline MIME part; see
    send_brief.py for the reference implementation.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("title"))

    if isinstance(brand, Palette):
        pal = brand
    elif isinstance(brand, str):
        pal = _BRANDS[brand.strip().lower()]
    else:
        pal = _detect_brand(soup)

    rows = [_masthead(soup, pal), _intro(soup, pal), _top3(soup, pal)]

    # Walk the body in document order so sections keep their template sequence.
    main = soup.select_one("main.body")
    body_parts: list[str] = []
    for el in (main.find_all(recursive=False) if main else []):
        cls = el.get("class") or []
        if el.name in ("p", "h1") and any(c in cls for c in ("datepill", "lede", "agentline", "hello")):
            continue          # already emitted by _intro
        if "top3" in cls:
            continue          # already emitted by _top3
        if "eyebrow" in cls:
            if body_parts:
                rows.append(_row(pal, "".join(body_parts)))
                body_parts = []
            rows.append(_eyebrow(pal, _text(el.select_one(".lbl"))))
        elif "prospect" in cls:
            body_parts.append(_prospect(pal, el))
        elif "planbox" in cls:
            body_parts.append(_planbox(pal, el))
        elif "story" in cls:
            body_parts.append(_story(pal, el))
        elif "take" in cls:
            body_parts.append(_take(pal, el))
        elif "seccta" in cls:
            body_parts.append(_seccta(pal, el))
        elif "caps" in cls:
            body_parts.append(_caps(pal, el))
        elif "quotes" in cls:
            body_parts.append(_quotes(pal, el))
    if body_parts:
        rows.append(_row(pal, "".join(body_parts)))
    rows.append(_row(pal, _spacer(40)))
    rows.append(_footer(pal, soup))

    sheet = "".join(r for r in rows if r)

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta name="x-apple-disable-message-reformatting" />
<meta name="color-scheme" content="light" />
<meta name="supported-color-schemes" content="light" />
<title>{title}</title>
<!--[if mso]><xml><o:OfficeDocumentSettings>
<o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch>
</o:OfficeDocumentSettings></xml><![endif]-->
<style type="text/css">
  :root {{ color-scheme: light; supported-color-schemes: light; }}
  body,table,td,p,h1,h2,h3,h4,a {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
  table {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }}
  img {{ border:0; outline:none; text-decoration:none; -ms-interpolation-mode:bicubic; }}
  /* Outlook.com / OWA force their own dark palette — pin ours back. */
  [data-ogsc] .sheet, [data-ogsb] .sheet {{ background-color:{pal.chalk} !important; }}
  @media only screen and (max-width:600px) {{
    .sheet {{ width:100% !important; }}
    .sheet td {{ padding-left:20px !important; padding-right:20px !important; }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:{pal.outer};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="{pal.outer}" style="background-color:{pal.outer};">
  <tr><td align="center" style="padding:32px 12px 64px;">
    <table role="presentation" class="sheet" width="{WIDTH}" cellpadding="0" cellspacing="0" border="0"
           bgcolor="{pal.chalk}" style="width:{WIDTH}px;max-width:{WIDTH}px;background-color:{pal.chalk};">
      {sheet}
    </table>
  </td></tr>
</table>
</body>
</html>"""


if __name__ == "__main__":
    import sys
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        out = emailify(f.read())
    with open(dst, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"{src} -> {dst} ({len(out):,} bytes)")
