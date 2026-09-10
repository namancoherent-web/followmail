# One-off: render the CURRENT template with Recyclify content for a preview.
# Uses the same footer constants as the live builder so CTAs match production.
from jinja2 import Environment, FileSystemLoader
from brief_builder import DEMO_URL, SITE_URL

brief = {
    "brand": {
        "wordmark": "CoherentConnect",
        "issue_label": "Daily Signal Brief · India",
        "issue_date": "17 Jul 2026",
        "tagline": "Sales intelligence, made coherent.",
    },
    "recipient": {"first_name": "Sam"},
    "meta": {"date_pill": "Friday, July 17, 2026"},
    "intro": {
        "lede_html": "CoherentConnect watched your live source graph across "
                     "<b>waste management, recycling, sustainability and circular-economy</b> "
                     "signals in <b>India</b> overnight. Three cleared verification — a live "
                     "buying trigger, a market shift re-pricing what you sell, and a competitor "
                     "move worth answering.",
    },
    "top3": [
        {"category": "Potential Customer",
         "html": "<b>Steelbird scales helmet output toward 2.5 crore units by 2032</b> "
                 "— a manufacturing expansion that turns waste handling into a board-level line item, this quarter."},
        {"category": "Industry Outlook",
         "html": "<b>India formalises the circular economy faster than incumbents can adapt</b> "
                 "— new incubators and EPR rules reset what buyers expect from a waste partner."},
        {"category": "Competition Outlook",
         "html": "<b>Recykal banks a $23M bridge round</b> — a well-funded rival betting on "
                 "tech-led scale, which leaves the service-depth lane open for Recyclify."},
    ],
    "potential_customer": {
        "flag": "Live Trigger · Manufacturing",
        "company_name": "Steelbird Hi-Tech",
        "narrative_html": "Steelbird's new <b>Doodle</b> kids-helmet range and the manufacturing "
                          "expansion behind it push production targets toward <b>2.5 crore units by 2032</b>. "
                          "That scale creates a waste-and-compliance problem they don't yet have a partner for "
                          "— and a same-week opening for Recyclify to lead with sustainable end-to-end handling.",
        "left": {"h": "Trigger", "v": "Capacity expansion + new consumer line announced this week"},
        "right": {"h": "Who to target", "v": "VP Operations · Head of Sustainability · Plant procurement"},
        "action": {"h": "Recommended action",
                   "v": "Open with a complimentary waste-stream audit tied to the 2032 capacity plan — not a generic intro."},
        "plan": {"h": "Approach plan", "steps": [
            {"title": "Name the moment.",
             "body_html": "Reference the Doodle launch and the 2.5-crore target in the subject line, signalling you track their growth, not a mailing list."},
            {"title": "Lead with fit, not features.",
             "body_html": "Frame Recyclify as the sustainability layer that lets the expansion clear EPR obligations without slowing the line."},
            {"title": "Offer something usable today.",
             "body_html": "Attach a one-page waste-stream snapshot their ops team can drop straight into the capacity-planning deck."},
        ]},
    },
    "take_customer": {"body_html": "Steelbird is scaling into a category where <b>waste is a regulated cost, not an afterthought</b>. "
                                   "The company that names that cost first — before procurement runs an RFP — sets the terms. "
                                   "<span class=\"accent\">Move this week, not this quarter.</span>"},
    "industry_outlook": [
        {"headline": "India's circular economy gets an institutional backbone",
         "body_html": "IIM Calcutta Innovation Park's <b>Prakriti Incubation Launchpad</b> is seeding "
                      "sustainability-first ventures across North-East India, and tightening EPR enforcement "
                      "is pushing waste from a CSR line to an operating requirement. For Recyclify, a wave of "
                      "new enterprises now <b>need a credible waste partner from day one</b>.",
         "source": "IIM Calcutta Innovation Park", "date": "This week", "verified": True},
    ],
    "take_industry": {"body_html": "The floor for &ldquo;good enough&rdquo; waste handling is rising by regulation, not choice. "
                                   "That re-prices exactly what Recyclify sells — <span class=\"accent\">verified, auditable, end-to-end</span> "
                                   "— from a nice-to-have into the thing a compliance officer signs off on."},
    "competition_outlook": {
        "flag": "Competitor Move · Funding",
        "company_name": "Recykal",
        "narrative_html": "Recykal, the Hyderabad-based waste-commerce platform, closed a <b>$23M bridge round</b> "
                          "to extend its circular-economy tech and push global expansion. It's a bet on "
                          "<b>marketplace scale and automation</b> — breadth over depth, and a signal the category is heating up.",
        "left": {"h": "The move", "v": "$23M bridge round; tech + global expansion"},
        "right": {"h": "The gap it leaves", "v": "Platform breadth, thin on hands-on service and audit depth"},
        "action": {"h": "Recommended response",
                   "v": "Don't out-platform them. Win where a marketplace can't — accountable, verified, on-the-ground handling."},
    },
    "take_competition": {"body_html": "Recykal is buying reach. Recyclify's edge isn't more listings — it's "
                                      "<b>the part a marketplace can't verify for you</b>. Point every regulated-sector "
                                      "conversation at that gap before the buyer assumes all waste partners are interchangeable."},
    "footer": {
        "assembled_note": "Assembled & verified by CoherentConnect",
        "cta_text": "Book a Demo →", "cta_url": DEMO_URL,
        "site_text": "Visit the Site →", "site_url": SITE_URL,
        "tagline": "Sales intelligence, made coherent.",
        "subline": "Your autonomous sales intelligence agent",
        "unsubscribe_url": "#",
    },
}

env = Environment(loader=FileSystemLoader("templates"))
html = env.get_template("daily_brief.html").render(brief)
out = "output/daily_brief_recyclify_india_preview.html"
open(out, "w", encoding="utf8").write(html)
print("wrote", out, "|", len(html), "bytes")
