#!/usr/bin/env python3
"""
=============================================================================
format_check.py  —  STAGE 0: technical & formatting review (check + correct)
=============================================================================

This is Part 1 of your master prompt, implemented deterministically. It runs
BEFORE the script is judged Good/Bad. It does three things:

    CHECK     every formatting rule and return PASS / WARN / FAIL
    CORRECT   the things that can be fixed mechanically (episode & scene
              renumbering) and write a cleaned copy of the script
    RECOMMEND a concrete fix for everything it can't safely auto-edit
              (over-long dialogue, action walls, emotion-as-action)

Checks implemented
------------------
  1. Episode numbering   — sequential, no gaps, no duplicates
  2. Scene numbering     — restarts each episode, sequential, no gaps/dups
  3. Runtime             — per-episode estimate; flag > ~4 min (split it)
  4. Dialogue length     — flag any dialogue block > 2.5 lines (with location)
  5. Action walls        — flag action paragraphs longer than 5 lines
  6. Emotion-as-action   — action lines that *explain* emotion; suggest CUE form
  7. Readability         — 1-5 score derived from the issues above

DESIGN NOTES (honest)
---------------------
Micro-drama scripts have no single rigid format, so parsing uses heuristics:
a short ALL-CAPS line is treated as a character cue; the lines under it (until
a blank line / next cue / scene / episode header) are that character's dialogue.
Runtime uses 140 spoken words/min + a small per-action-beat allowance. All
thresholds live in the CONFIG block so you can tune them to your house style.

USAGE
    python format_check.py script.pdf                  # report only
    python format_check.py script.txt --fix out.txt    # also write corrected
    python format_check.py script.txt --json report.json
=============================================================================
"""
from __future__ import annotations
import os, re, sys, json, argparse, subprocess, tempfile

# ── CONFIG (tune to house style) ─────────────────────────────────────────────
CONFIG = {
    "words_per_minute": 140,      # spoken-dialogue rate for runtime estimate
    "seconds_per_action_beat": 2.0,
    "max_runtime_min": 4.0,       # flag episodes longer than this
    "chars_per_line": 60,         # for converting dialogue length to "lines"
    "max_dialogue_lines": 2.5,    # flag dialogue blocks longer than this
    "max_action_lines": 5,        # flag action paragraphs longer than this
}

# ── episode / scene header patterns ──────────────────────────────────────────
# Episode headers are matched FUZZILY: a leading "epi" stem followed by any
# letters and then a number. This tolerates every real-world misspelling seen in
# scripts — "Episode", "EPISODE", "Epiosde", "Episosde", "Epsiode", "EEpisode",
# leading control chars (^L) and trailing zero-width spaces — instead of an
# explicit (and inevitably incomplete) list of typos.
# "episode" stem, optional "no./number", optional separators (- – — : .), then the number.
# Handles: "Episode 7", "Episode-2", "Episode - 3", "Episode – 4", "EPISODE: 5",
# "Episode No. 6", misspellings (Epiosde/Episosde), hidden chars.
_EP = re.compile(r"^[\s\f​]*e?epi[a-z]*\s*(?:no\.?|number)?\s*[-–—:.]*\s*0*(\d+)\b", re.I)
_EP_CLEAN = re.compile(r"^[\s\f​]*episode\s*0*\d+\s*$", re.I)  # the "correct" form
_EP_TOKEN = re.compile(r"\be?epi[a-z]*\s*(?:no\.?|number)?\s*[-–—:.]*\s*0*(\d+)\b", re.I)
_FREEZE = re.compile(r"^\s*(\d+)\s+freeze\b", re.I)


_EP_INLINE = re.compile(r"^(?:\d{1,3}\s*[.\-:)]\s*|[^.!?]{0,40}?[-–—:]\s*)e?epi[a-z]*\s*[-–—:.]*\s*0*(\d+)\b", re.I)


def episode_num(line):
    """
    Episode number if `line` is a genuine episode header, else None.
    Handles start-of-line headers ("Episode 7", "Episode - 3", "Episode-2",
    "EPISODE: 5", "Episode No. 6", misspellings, hidden chars) AND inline headers
    ("SPERM-MAN — EPISODE 01 (note)"). REJECTS prose references such as
    "Episode 1, scene no 1, Beena places…" or "flashback of Episode 1" so a
    mention inside a sentence is never mistaken for a header.
    """
    s = line.replace("​", "").strip()
    # "EPISODES : 96" (plural + count) is a title/summary line, not an episode header
    if re.match(r"^[\s\f]*episodes\b", s, re.I):
        return None
    m = _EP.match(s)
    if m:
        num, end = int(m.group(1)), m.end()
    else:
        m2 = _EP_INLINE.match(s)
        if not m2:
            return None
        num, end = int(m2.group(1)), m2.end()
    tail = re.sub(r"\([^)]*\)", "", s[end:]).strip()      # ignore a parenthetical note
    # an "EPISODE N ENDS / OVER / KHATAM" line is a CLOSING marker, not a new header
    if re.match(r"^[-–—:]*\s*(ends?|over|finish|samapt|khatam|concludes?)\b", tail, re.I):
        return None
    if tail.startswith(",") or re.match(r"^(scene|sc\b)", tail, re.I) or len(tail.split()) > 6:
        return None                                        # prose, not a header
    return num
_SCENE = re.compile(r"^[\s\f​]*(?:scene|seen|sc)\s*\.?\s*0*(\d+)\b", re.I)
_SLUG = re.compile(r"^\s*(?:INT|EXT|INT\./EXT|I/E)[\.\s]", re.I)
_CUE_CAPS = re.compile(r"^[\s\f​]*([A-Z][A-Z0-9 .'\-]{1,28})(\([^)]*\))?:?\s*$")


def is_cue(line):
    """
    Return the character name if `line` is a dialogue cue, else None.
    Handles BOTH all-caps cues (RAJ, MYRA) and Title-case cues (Myra, Manav) —
    many micro-drama scripts use the latter. A cue is a short, punctuation-free,
    name-like line that is not a scene/episode/freeze header.
    """
    s = line.replace("​", "").strip()
    if not s or len(s) > 28:
        return None
    if _EP.match(s) or _SCENE.match(s) or _SLUG.match(s) or _FREEZE.match(s):
        return None
    m = _CUE_CAPS.match(s)
    if m:
        return m.group(1).strip()
    # Title-case: 1–3 alphabetic words, optional (parenthetical), no end punctuation
    core = re.sub(r"\([^)]*\)", "", s).strip()
    if re.search(r"[.!?,:;]", core):
        return None
    words = core.split()
    if 1 <= len(words) <= 3 and all(re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", w) for w in words):
        return core
    return None


def _pdf_text_pdfplumber(path):
    """Pure-Python PDF text extraction (no external binary)."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def extract_text(path):
    if path.lower().endswith(".pdf"):
        # Prefer `pdftotext -layout` (best layout fidelity) but DON'T require it —
        # fall back to pdfplumber (pure Python) when the poppler binary is absent,
        # so this works on hosts like Streamlit Cloud without extra system packages.
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.txt")
            try:
                r = subprocess.run(["pdftotext", "-layout", path, out],
                                   capture_output=True, text=True)
                if r.returncode == 0:
                    txt = open(out, encoding="utf-8", errors="ignore").read()
                    if txt.strip():
                        return txt
            except FileNotFoundError:
                pass  # poppler not installed → fall through to pdfplumber
        return _pdf_text_pdfplumber(path)
    return open(path, encoding="utf-8", errors="ignore").read()


# ─────────────────────────────────────────────────────────────────────────────
def parse(text):
    """
    Parse into a list of episodes:
      [{ep_label, ep_num, scenes:[{scene_num,...}], lines:[...],
         dialogue:[{character, text, n_lines, scene}], actions:[{text,n_lines}] }]
    """
    lines = text.split("\n")
    episodes, cur = [], None
    cur_scene = None
    front_matter = []  # lines before the first real episode header (title page etc.)

    def new_ep(num, label):
        return {"ep_num": num, "ep_label": label, "scenes": [], "lines": [],
                "dialogue": [], "actions": []}

    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        epn = episode_num(s)
        if epn is not None:
            cur = new_ep(epn, s.strip())
            episodes.append(cur); cur_scene = None; i += 1; continue
        if _FREEZE.match(s):
            i += 1; continue  # freeze closes an episode; not a new one
        if cur is None:
            front_matter.append(ln); i += 1; continue  # not a phantom Episode 1
        cur["lines"].append(ln)
        msc = _SCENE.match(s)
        if msc:
            cur_scene = int(msc.group(1))
            cur["scenes"].append(("explicit", cur_scene)); i += 1; continue
        if _SLUG.match(s):
            cur_scene = (cur_scene or 0) + 1
            cur["scenes"].append(("slug", cur_scene)); i += 1; continue
        # character cue -> collect the dialogue block beneath it
        name = is_cue(ln)
        if name:
            block, j = [], i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt or is_cue(lines[j]) or _SCENE.match(nxt) \
                        or _EP.match(nxt) or _SLUG.match(nxt):
                    break
                block.append(nxt); j += 1
            if block:
                txt = " ".join(block)
                nlines = max(1, round(len(txt) / CONFIG["chars_per_line"], 1))
                cur["dialogue"].append({"character": name, "text": txt,
                                        "n_lines": nlines, "scene": cur_scene})
                i = j; continue
        # otherwise an action line; group consecutive non-empty action lines
        if s:
            block, j = [s], i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt or is_cue(lines[j]) or _SCENE.match(nxt) \
                        or _EP.match(nxt) or _SLUG.match(nxt):
                    break
                block.append(nxt); j += 1
            txt = " ".join(block)
            cur["actions"].append({"text": txt, "n_lines": len(block), "scene": cur_scene})
            i = j; continue
        i += 1
    return episodes


# ── individual checks ────────────────────────────────────────────────────────
def _seq_issues(nums):
    """Return (missing, duplicates) for a list of ints expected to be 1..N."""
    seen, dups = set(), []
    for n in nums:
        if n in seen: dups.append(n)
        seen.add(n)
    if not nums: return [], []
    missing = [x for x in range(1, max(nums) + 1) if x not in seen]
    return missing, sorted(set(dups))


def check_episodes(eps):
    nums = [e["ep_num"] for e in eps]
    if not nums:
        return {"check": "Episode numbering", "status": "FAIL",
                "detail": "0 episode headers detected",
                "recommendation": "No 'Episode N' headers found — add clear episode headers."}
    if len(nums) == 1:
        return {"check": "Episode numbering", "status": "PASS",
                "detail": f"single episode (Episode {nums[0]})",
                "recommendation": "Single-episode script — numbering not applicable."}
    missing, dups = _seq_issues(nums)
    # header spelling/case consistency is a SEPARATE, advisory concern — the
    # episode is not "missing" just because the word is misspelled.
    misspelled = [e["ep_label"] for e in eps
                  if not _EP_CLEAN.match(e["ep_label"].replace("​", "").strip())]
    if missing or dups:
        status = "FAIL"
        rec = ""
        if missing: rec += f"Missing episode numbers: {missing}. "
        if dups: rec += f"Duplicate episode numbers: {dups}. "
    elif misspelled:
        status = "WARN"
        rec = (f"Numbering is complete and sequential (1–{max(nums)}). "
               f"Minor: {len(misspelled)} header(s) are misspelled/inconsistent "
               f"(e.g. {', '.join(repr(m) for m in misspelled[:3])}); normalise to 'Episode N'.")
    else:
        status = "PASS"
        rec = f"Episode numbering is sequential and complete (1–{max(nums)})."
    return {"check": "Episode numbering", "status": status,
            "detail": f"{len(nums)} episodes, range 1–{max(nums) if nums else 0}",
            "recommendation": rec.strip()}


def check_scenes(eps):
    # A script may legitimately use EITHER convention:
    #   (a) scenes restart at 1 each episode, or
    #   (b) one continuous scene sequence across the whole series (Sc 1..N).
    # Both are valid. We only flag genuine gaps or duplicate scene numbers within
    # whichever convention the script is actually using.
    per_ep = [[n for kind, n in e["scenes"] if kind == "explicit"] for e in eps]
    all_scenes = [n for ep in per_ep for n in ep]
    if not all_scenes:
        return {"check": "Scene numbering", "status": "PASS",
                "detail": "No explicit scene numbers (slug-line scenes only).",
                "recommendation": "No scene-numbering issues."}

    starts_at_one = [ep[0] for ep in per_ep if ep]
    restarts = sum(1 for s in starts_at_one if s == 1)
    # Classify the convention by behaviour, not by perfection: if essentially only
    # the first episode starts at scene 1 (others continue upward), it's continuous
    # numbering. A few local duplicates shouldn't flip the classification — they're
    # reported as minor issues *within* the continuous scheme.
    continuous = restarts <= 1

    if continuous:
        missing, dups = _seq_issues(all_scenes)
        convention = f"continuous across the series (Sc 1–{max(all_scenes)})"
        if not missing and not dups:
            return {"check": "Scene numbering", "status": "PASS",
                    "detail": f"Continuous numbering, sequential, no gaps/dupes "
                              f"(Sc 1–{max(all_scenes)}).",
                    "recommendation": f"Scene numbers are {convention} — internally consistent."}
        rec = f"Convention: {convention}."
        if dups: rec += f" Duplicate scene numbers: {sorted(set(dups))}."
        if missing: rec += f" Gaps in the sequence: {missing[:15]}{'…' if len(missing) > 15 else ''}."
        return {"check": "Scene numbering", "status": "WARN",
                "detail": f"{len(dups)} duplicate(s), {len(missing)} gap(s) in continuous numbering",
                "recommendation": rec}

    # otherwise treat as per-episode restart and check each episode
    bad = []
    for e, snums in zip(eps, per_ep):
        if not snums: continue
        missing, dups = _seq_issues(snums)
        if missing or dups or snums[0] != 1:
            bad.append((e["ep_num"], snums, dups))
    if not bad:
        return {"check": "Scene numbering", "status": "PASS",
                "detail": "Scenes restart per episode and are sequential.",
                "recommendation": "No scene-numbering issues."}
    rec = "; ".join(f"Ep{ep}: {sn}" + (f" dup {d}" if d else "") for ep, sn, d in bad[:8])
    return {"check": "Scene numbering", "status": "WARN",
            "detail": f"{len(bad)} episode(s) with scene issues",
            "recommendation": rec}


def estimate_runtime_min(ep):
    words = sum(len(d["text"].split()) for d in ep["dialogue"])
    secs = words / CONFIG["words_per_minute"] * 60.0
    secs += len(ep["actions"]) * CONFIG["seconds_per_action_beat"]
    return round(secs / 60.0, 2)


def check_runtime(eps):
    over = [(e["ep_num"], estimate_runtime_min(e)) for e in eps
            if estimate_runtime_min(e) > CONFIG["max_runtime_min"]]
    status = "PASS" if not over else "WARN"
    detail = "; ".join(f"Ep{n}≈{m}min" for n, m in
                       [(e["ep_num"], estimate_runtime_min(e)) for e in eps])
    rec = ("All episodes within ~%.0f min." % CONFIG["max_runtime_min"] if not over
           else "Episodes over %.0f min (consider splitting): %s"
                % (CONFIG["max_runtime_min"], ", ".join(f"Ep{n} (~{m}min)" for n, m in over)))
    return {"check": "Runtime", "status": status, "detail": detail, "recommendation": rec}


def check_dialogue(eps):
    long_blocks = []
    for e in eps:
        for d in e["dialogue"]:
            if d["n_lines"] > CONFIG["max_dialogue_lines"]:
                short = d["text"][:90].rsplit(" ", 1)[0] + "…"
                long_blocks.append({"episode": e["ep_num"], "scene": d["scene"],
                                    "character": d["character"], "n_lines": d["n_lines"],
                                    "excerpt": d["text"][:120],
                                    "suggestion": f"Trim to ≤2 lines, e.g. '{short}'"})
    status = "PASS" if not long_blocks else "WARN"
    return {"check": "Dialogue length", "status": status,
            "detail": f"{len(long_blocks)} dialogue block(s) over {CONFIG['max_dialogue_lines']} lines",
            "recommendation": ("Dialogue blocks are concise." if not long_blocks
                               else "Shorten the flagged blocks (see items)."),
            "items": long_blocks}


def check_action_walls(eps):
    walls = [{"episode": e["ep_num"], "scene": a["scene"], "n_lines": a["n_lines"],
              "excerpt": a["text"][:120]}
             for e in eps for a in e["actions"] if a["n_lines"] > CONFIG["max_action_lines"]]
    status = "PASS" if not walls else "WARN"
    return {"check": "Action formatting", "status": status,
            "detail": f"{len(walls)} action paragraph(s) over {CONFIG['max_action_lines']} lines",
            "recommendation": ("Action blocks are well broken up." if not walls
                               else "Break long action paragraphs into beats."),
            "items": walls}


_EMO = re.compile(r"\b(angry|angrily|sad|sadly|happy|happily|nervous|nervously|"
                  r"furious|crying|smiling|gusse|udaas|khush|naraz|rote|hChappy)\b", re.I)


def check_emotion_cues(eps):
    flagged = []
    for e in eps:
        for a in e["actions"]:
            if _EMO.search(a["text"]) and len(a["text"].split()) > 6:
                flagged.append({"episode": e["ep_num"], "scene": a["scene"],
                                "excerpt": a["text"][:110]})
    status = "PASS" if not flagged else "WARN"
    return {"check": "Emotional-cue formatting", "status": status,
            "detail": f"{len(flagged)} action line(s) explain emotion in prose",
            "recommendation": ("Emotions are cued concisely." if not flagged
                               else "Prefer a short parenthetical cue, e.g. RAJ (angry), "
                                    "instead of an action sentence describing the emotion."),
            "items": flagged}


def readability(checks):
    """
    1–5 ease-of-production score. Genuine structural breakage (missing/duplicate
    episodes, real scene gaps) costs the most; cosmetic issues (a misspelled
    header, prose-heavy action) cost little. A clean script scores 5; a script
    that is merely "tidy this up" stays in the 3–4 band rather than failing.
    """
    weight = {"Episode numbering": 2.0, "Scene numbering": 1.5,
              "Dialogue length": 1.5, "Runtime": 0.8,
              "Action formatting": 0.6, "Emotional-cue formatting": 0.5}
    severity = {"FAIL": 1.0, "WARN": 0.34, "PASS": 0.0}
    score = 5.0
    for c in checks:
        score -= weight.get(c["check"], 0.4) * severity.get(c["status"], 0.0)
    return max(1, int(score + 0.5))


# ── auto-correction (numbering only — safe to do mechanically) ───────────────
def autocorrect(text):
    """
    Return a cleaned copy of the script:
      - every episode header normalised to a clean "EPISODE N" (its true number),
        which also fixes styles like "40. EPISODE 12", "EPISODE - 7", misspellings;
      - a missing "EPISODE 1" inserted if the script opens with content before the
        first header and the first detected episode is > 1;
      - scene numbers restarted sequentially within each episode.
    Creative content (dialogue/action wording) is never changed.
    """
    lines = text.split("\n")
    first_idx = first_num = None
    for i, ln in enumerate(lines):
        n = episode_num(ln.strip())
        if n is not None:
            first_idx, first_num = i, n
            break
    need_ep1 = first_num is not None and first_num > 1
    out, inserted, sc = [], False, 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if need_ep1 and not inserted and (_SCENE.match(s) or _SLUG.match(s)) \
                and (first_idx is None or i < first_idx):
            out.append("EPISODE 1"); inserted = True; sc = 0
        n = episode_num(s)
        if n is not None:
            out.append(f"EPISODE {n}"); sc = 0; continue
        if _SCENE.match(s):
            sc += 1
            out.append(re.sub(r"\d+", str(sc), s, count=1)); continue
        out.append(ln)
    if need_ep1 and not inserted:
        out.insert(0, "EPISODE 1")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
def run(path, fix_path=None):
    text = extract_text(path)
    eps = parse(text)
    checks = [check_episodes(eps), check_scenes(eps), check_runtime(eps),
              check_dialogue(eps), check_action_walls(eps), check_emotion_cues(eps)]
    rscore = readability(checks)
    # readability is a derived score, advisory only — it never escalates to FAIL
    # on its own (FAIL is reserved for structural breakage like missing episodes).
    checks.append({"check": "Readability score",
                   "status": "PASS" if rscore >= 4 else "WARN",
                   "detail": f"{rscore}/5", "recommendation":
                   "Production-ready formatting." if rscore >= 4 else
                   "Tidy the WARN items above to raise readability."})
    worst = "FAIL" if any(c["status"] == "FAIL" for c in checks) else \
            ("WARN" if any(c["status"] == "WARN" for c in checks) else "PASS")
    summary = {"PASS": "Formatting is correct — no changes needed.",
               "WARN": "Formatting is usable but has issues to clean up before production (see WARN items).",
               "FAIL": "Formatting has structural errors that must be fixed (see FAIL items)."}[worst]
    result = {"file": os.path.basename(path), "n_episodes": len(eps),
              "format_status": worst, "readability": rscore, "summary": summary,
              "format_ready": worst != "FAIL", "checks": checks}
    if fix_path:
        open(fix_path, "w", encoding="utf-8").write(autocorrect(text))
        result["corrected_file"] = fix_path
    return result


def print_report(r):
    bar = "=" * 74
    print(f"\n{bar}\n  FORMATTING REVIEW — {r['file']}   [{r['format_status']}]  "
          f"readability {r['readability']}/5\n{bar}")
    for c in r["checks"]:
        print(f"  [{c['status']:<4}] {c['check']}: {c['detail']}")
        print(f"         → {c['recommendation']}")
        for it in c.get("items", [])[:6]:
            loc = f"Ep{it.get('episode')}/Sc{it.get('scene')}"
            who = f" {it['character']}:" if it.get("character") else ""
            print(f"           - {loc}{who} \"{it['excerpt']}\"")
    print(f"\n  SUMMARY: {r['summary']}")
    if r.get("corrected_file") and r["format_status"] != "PASS":
        print(f"  Corrected script written -> {r['corrected_file']}")
    print(bar)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--fix", help="write an auto-renumbered copy to this path")
    ap.add_argument("--json", help="write the full report JSON here")
    args = ap.parse_args()
    r = run(args.path, fix_path=args.fix)
    print_report(r)
    if args.json:
        json.dump(r, open(args.json, "w"), indent=2)
        print(f"JSON -> {args.json}")


if __name__ == "__main__":
    main()
