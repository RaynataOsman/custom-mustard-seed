"""The cover letter standard for every role the engine prepares (PC dashboard and online companion alike).

Set by Jay on 2026-10-25 from two of his own approved letters (Talent Sam Back-End Developer, GhostTraders
Junior UX/UI Designer). It lives in a tracked file so it is shared through GitHub; masters/ and config.json are
git-ignored and never carry it. The letter layout (name, contact line, date, "Re:" line) is added by
pipeline._cover_files, so the text we generate runs from "Dear ... team," to the links line.

Facts always come from the resume (tailor.guard_cover enforces it). The examples set structure and voice only.
"""
import re

STANDARD = {
    "words": "220-300",
    "paragraphs": "5 short paragraphs",
    "sign_off": "Kind regards",
    "rules": [
        "Open with 'Dear <Company> team,' (use the company name exactly as given; if it is missing use 'Dear hiring team,').",
        "P1 (2-3 sentences): name the role and say plainly why you fit it as a remote hire from Cape Town. If the posting "
        "says something specific about the company, product or mission, say what stood out to you in your own words. "
        "Never invent anything about the company that the posting does not say.",
        "P2 (3-4 sentences): two concrete pieces of work from the resume that match the posting's main requirements. "
        "Name the employer or client, what you actually did, and the tools, using only tools the resume names. "
        "Talk about the work itself, not about yourself.",
        "P3 (2-3 sentences): how you work with people who cannot see your screen - turning a loose brief into something "
        "specific enough to build, flagging problems early, the hours you overlap. Tie it to how this role or employer "
        "works (client team, employer of record, distributed team) only if the posting says so.",
        "P4 (1-2 sentences, only when it is true and relevant): one honest line about a gap the posting asks for, such as "
        "no degree, stated plainly and followed by what you have instead (continuously shipped paid work and the portfolio). "
        "If there is no gap to address, use this paragraph for how design and build knowledge help you work with the "
        "other side of the team (design with implementation in mind, or code with the user in mind).",
        "P5 (1-2 sentences): say the portfolio and CV are included, thank them, and invite a conversation. "
        "Keep it plain and short.",
        "Do not state a number of years of experience anywhere. Do not state any other figure the resume and posting do not contain.",
        "Plain, specific, first person. Short paragraphs. No bullet points. No headings inside the letter.",
        "Do not write the signature, the contact line, the date or the Re: line - the engine adds them.",
    ],
}

EXAMPLES = {
    "backend_dev": (
        "Dear Talent Sam team,\n\n"
        "I am applying for the Back-End Developer role. I am based in Cape Town, which I understand is the talent pool "
        "you build from, and I have spent the last few years writing server-side code for companies that were not in "
        "the same country as me.\n\n"
        "Most of that work has been the unglamorous middle of the stack. At Woodlane Furniture I maintained the back end "
        "of an e-commerce platform through a migration off WordPress, which meant rebuilding order-management integrations "
        "without losing data or downtime along the way. At DevSmartSolutions I have been building REST APIs that connect "
        "client front-ends to third-party services, deploying them on AWS EC2 and S3, and automating the test-and-release "
        "path with GitHub Actions. The databases have mostly been MySQL, with PostgreSQL and MongoDB where the shape of "
        "the data called for it.\n\n"
        "What I would bring beyond the stack itself is the habit of working with people who cannot see my screen. Every "
        "role I have held has been remote and client-facing, so I am used to turning a vague business requirement into "
        "something specific enough to build, and to saying early when a plan will not survive contact with production. "
        "That translates directly to working inside a client team through an Employer of Record arrangement.\n\n"
        "I do not hold a degree. What I have instead is continuously shipped, paid work, and a portfolio that shows it.\n\n"
        "I would welcome the chance to talk about what your clients are building."
    ),
    "junior_uxui": (
        "Dear GhostTraders Team,\n\n"
        "I came across the Junior UX/UI Designer role at GhostTraders and immediately felt aligned with the type of work "
        "and environment you are building.\n\n"
        "What stood out to me most was the balance between product design, education, and real-world usability. I enjoy "
        "working on digital experiences that are practical, intuitive, and genuinely useful to the people using them daily, "
        "which is why this opportunity caught my attention.\n\n"
        "Over the last few years, I have worked across freelance and contract projects designing and building responsive "
        "websites, e-commerce platforms, landing pages, and front-end user experiences using tools like Figma, React, "
        "WordPress, Shopify, and Canva. My workflow usually involves moving from wireframes and design concepts into "
        "functional interfaces while collaborating closely with clients and stakeholders throughout the process.\n\n"
        "I particularly enjoy refining layouts, simplifying user flows, improving responsiveness across devices, and making "
        "sure interfaces feel clean and easy to navigate. Alongside design work, I also have hands-on front-end "
        "implementation experience with HTML, CSS, JavaScript, React, and WordPress, which helps me communicate effectively "
        "with development teams and design with implementation in mind.\n\n"
        "I have included my portfolio and CV for review and would appreciate the opportunity to discuss how my background "
        "could support the GhostTraders team. Thank you for your time and consideration."
    ),
}


def style_examples():
    """Both approved letters, as one block for the model (structure and voice only)."""
    return "\n\n=====\n\n".join(EXAMPLES.values())


def rules_text(job, cfg):
    """The instruction sent to the model for the letter."""
    p = cfg.get("profile", {})
    cl = cfg.get("cover_letter", {})
    words = STANDARD["words"]  # the standard wins over any per-PC setting
    return (f"Write the cover letter in {words} words, {STANDARD['paragraphs']}, to this standard: "
            + " ".join(f"({i + 1}) {r}" for i, r in enumerate(STANDARD["rules"]))
            + f" The candidate works from {p.get('location', '')}. Follow the STRUCTURE, TONE and SENTENCE STYLE of "
              "cover_letter_style_examples, but NEVER copy a fact, number, employer, tool or claim from them - "
              "every fact must come from resume_full_text.")


_SIGN = re.compile(r"\n+\s*(kind regards|best regards|regards|sincerely|best wishes|warm regards|yours (sincerely|faithfully))\b.*$",
                   re.I | re.S)


def finish(text, cfg):
    """Apply the fixed ending: strip any sign-off the model wrote, then add 'Kind regards,', the name and the links line."""
    p = cfg.get("profile", {})
    cl = cfg.get("cover_letter", {})
    body = _SIGN.sub("", (text or "").strip()).rstrip()
    if not body:
        return body
    sign = cl.get("sign_off") or STANDARD["sign_off"]
    links = " | ".join(x for x in (
        f"Portfolio: {p['portfolio']}" if p.get("portfolio") else "",
        f"LinkedIn: {p['linkedin']}" if p.get("linkedin") else "") if x)
    out = f"{body}\n\n{sign},\n{p.get('name', '')}"
    if links:
        out += f"\n{links}"
    return out
