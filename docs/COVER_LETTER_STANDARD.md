# Cover letter standard (set 2026-10-25)

Applies to every cover letter the engine writes, on the PC dashboard and in the online companion.
The code is in `coverletter.py`; `tailor.py` uses it. Facts always come from the master resume.

Built from two of Jay's approved letters (Talent Sam Back-End Developer, GhostTraders Junior UX/UI Designer).

- Length: 220-300 words, 5 short paragraphs, no bullets or headings.
- Opening: "Dear <Company> team," (the page adds name, contact line, date and the Re: line).
- P1: the role, why it fits as a remote hire from Cape Town, and what stood out about the company (only if the posting says it).
- P2: two concrete pieces of work from the resume, naming employer or client and tools, resume tools only.
- P3: how Jay works with people who cannot see his screen, and his hours overlap.
- P4: one honest gap line when relevant (for example no degree, then what he has instead); otherwise how design and build knowledge help him work with the other side of the team.
- P5: portfolio and CV included, thanks, invite a conversation.
- No years-of-experience figure and no number the resume and posting lack (guard_cover enforces this).
- Ending is fixed by the engine: "Kind regards," / name / Portfolio and LinkedIn links.

Roles already prepared keep their old letter until they are re-prepared.
