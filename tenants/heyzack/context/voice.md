# Voice

Source: `/Users/sheshnarayaniyer/.claude/skills/HeyZackBrandPdf/References/BRAND-PDF-GUIDE.md` (Palette, Type, Logo, Wording), `/Users/sheshnarayaniyer/.claude/skills/HeyZackBrandPdf/SKILL.md` (Hard rules). External skill; linked, not copied.

Wording:

- Calm, direct, formal « vous ». One idea per sentence.
- French first; the English variant mirrors the same structure. Real accents, real apostrophes, no-break spaces before €.
- Say what the document is: « Proposition préliminaire, sans engagement ». Never « devis final », « facture », « prix garanti ».
- No savings percentages, no « 100 % compatible », no availability promises. Compatibility and installation are « à confirmer avec un conseiller ».
- Capitals only for eyebrows and table heads.

Typeface: Brinnan only. Regular 400 for text, Bold 700 for headings, labels, values and the amount. No Light, no Space Grotesk, no Helvetica fallback in shipped documents.

Palette (print surface):

| Role | Token | Hex |
|---|---|---|
| Structure, section titles, amount | blue | #243984 |
| Accent (lines and borders only, never a fill behind text) | pink | #E82F89 |
| Secondary rule under h2 | indigo | #7986CB |
| Text | ink | #10131C |
| Muted text | mutedDark | #505B72 |
| Header band | night | #0D1018 |
| Panel | paper | #F7F8FC |
| Rules | rule | #D2D4DC |
| Table head | tableHead | #E6E9F5 |

Logo: one master, `logo.png`, 1240 x 228, pure white. Drawn on the night header band only; invisible on light surfaces by design. Never retyped as a wordmark, never recoloured or stretched, no dark variant exists and none may be created. Print minimum 30 mm; the PDF skill uses 42 mm. Running text says "HeyZack".

Type scale (pt): h1 24, h2 17 (blue with indigo rule), h3 13, body 10 at line height 1.5, captions 8.5, amount 30. A4, 16 mm margins.

FILL: voice for channels other than PDF documents (website, email, social, support).
FILL: the dark hub surface tokens for screens, which the guide says exist in `heyzack/brand-system` but are not in the skill.
