"""Write a demo ProPresenter ``.pro`` exercising every slide style (#172).

One cue per ``styles.STYLE_KEYS`` entry, grouped by service section, using the same
2026-07-05 sample content as ``scripts/render_style_samples.py`` (member names scrubbed).
This is the eyeball check for the serialization library: open it in ProPresenter and confirm
Korean renders (the RTF escaping risk), the Option A strips hug each lyric line, and the
Option 3 frame/gold rules match ``docs/style-samples/f3-*.png`` (minus the blurred backdrop,
which needs the #224 background images).

``--run YYYY-MM-DD`` instead builds the **whole weekly deck** from that run's reviewed
``ServiceData`` (#178) — the end-to-end eyeball, and the only way to see the section order,
the verse packing and the liturgy as the operator will click through them.

``--announcements`` builds a 교회 소식-only deck out of **every distinct shape of notice the
church has actually published**, gathered from the reviewed runs under ``data/runs/`` (#233):
the bare one-liner, the date+time+문의, the 5-row rail, the ones with no liftable field at all,
and the ones long enough to run onto a second plate. One review pass covers what a year of
Sundays would otherwise take. The runs are git-ignored real bulletins, so the deck it writes
carries member names — keep it out of the repo.

Usage:

    .venv/bin/python scripts/make_pro_demo.py                    # -> the local PP library
    .venv/bin/python scripts/make_pro_demo.py --out /tmp/x.pro
    .venv/bin/python scripts/make_pro_demo.py --run 2026-08-23   # the full weekly deck
    .venv/bin/python scripts/make_pro_demo.py --candidates \
        --over data/style-samples/bg/band-45.jpg                 # the #247 comparison deck
    .venv/bin/python scripts/make_pro_demo.py --fonts \
        --over data/style-samples/bg/band-45.jpg                 # the #247 font comparison
    .venv/bin/python scripts/make_pro_demo.py --run 2026-09-06 --font suit   # that week, in SUIT
    .venv/bin/python scripts/make_pro_demo.py --announcements --out /tmp/a1.pro

ProPresenter caches a ``.pro`` it has already read, so iterate by writing a *new* filename each
round (``--out``) rather than overwriting and restarting the app.
"""

import argparse
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path

from worship_deck import store
from worship_deck.bible import layout
from worship_deck.propresenter import announce, build, bundle, content, styles
from worship_deck.propresenter import elements as el

DEFAULT_OUT = Path.home() / "Documents/ProPresenter/Libraries/Default/Style Demo.pro"

LYRIC_KO = ["다시 한 번 외쳐 부르니", "예수여 나를 돌아 보소서"]
LYRIC_BI = ("주 하나님 지으신 모든 세계", "O Lord my God, when I in awesome wonder")
VERSE_KO = [
    (9, "참 빛 곧 세상에 와서 각 사람에게 비취는 빛이 있었나니"),
    (10, "그가 세상에 계셨으며 세상은 그로 말미암아 지은 바 되었으되 세상이 그를 알지 못하였고"),
]
VERSE_EN = [
    (9, "The true light, which gives light to everyone, was coming into the world."),
    (10, "He was in the world, and the world was made through him, yet the world did not know him."),
]
ANNOUNCEMENTS = [
    "1. 성찬식\n\n7/5 (오늘) 성찬식이 있습니다.",
    "2. 제직회\n\n7/5 (오늘) 1:30 PM 친교실에서 제직회가 있습니다.",
    "3. 에티오피아 단기선교\n\n7/9 (목) – 7/19 (주일) 단기선교를 위해 기도 부탁드립니다.",
]
CREED = [
    "전능하사 천지를 만드신 하나님 아버지를 내가 믿사오며",
    "그 외아들 우리 주 예수 그리스도를 믿사오니",
    "이는 성령으로 잉태하사 동정녀 마리아에게 나시고",
    "본디오 빌라도에게 고난을 받으사",
    "십자가에 못박혀 죽으시고",
]
# The 문답 form's shape: the leader's question, then the congregation's answer (#244).
CREED_RESPONSIVE = content.APOSTLES_CREED_RESPONSIVE[0]


# ── the #247 comparison deck ──────────────────────────────────────────────────
# What #247 settled, kept runnable so the choice can be re-argued at #225 without rebuilding the
# harness. Arrow through the groups in ProPresenter at full output size — a still PNG cannot settle
# either of these.

# How strongly the backdrop reads (#224). `gentle` is the shipped pick (2026-09-05): `open` turned
# out too flat to make the church out at all, and `moderate` read better still but put a busier
# ground under 84pt scripture, which a largely elderly congregation reads across the sanctuary.
# `scripts/make_backdrop.py` owns the numbers — these are its keys.
BACKDROP_CANDIDATES = ["open", "gentle", "moderate", "strong"]

# The keyed-label plates. `""` is the shipped one — drawn from `FRAME_BOX` at label size, so the
# label is made of the same furniture as every full-screen slide (#247). `M1` is what #234's
# bake-off picked and the deck carried until 2026-09-05, `A` is Keynote's own watercolour; both are
# artwork, and both are here only so #241 can put the drawn plate beside what it replaced.
KEYED_CANDIDATES = [
    ("현행 드로운 프레임 플레이트", ""),
    ("M1 각진 바 + 금색 룰 (구)", "M1"),
    ("A 붓터치 (Keynote)", "A"),
]

# Korean faces (#247). It started as a plate-only question — the plate is the one place the deck
# sets type inside a rounded box, and Apple SD Gothic Neo's squared terminals read as a different
# design language there — and became a deck-wide one on review: six faces went into a plate
# bake-off, three of those into full weekly decks, and **NanumSquare Round won**. What is left here
# is the shipped face plus the runner-up and the old one, kept so the #241 style review can put the
# choice beside the rest of the deck's decisions rather than taking it on trust. Pretendard, IBM
# Plex Sans KR and Gothic A1 were dropped at the plate stage.
#
# Every face here has to be installed on the church mini before a deck set in it renders there
# (#191/#197): ProPresenter substitutes silently, so a missing face looks like a style bug.
#
# label, family, regular, bold, then the face's own CoreText metrics straight out of
# `scripts/measure_advance.swift`: Hangul body advance, Latin advance, inter-line pitch.
#
# The metrics are applied as **ratios** against Apple SD Gothic Neo's, not as replacements. The
# deck's `layout` constants each sit a little off what that face really measures (0.83 vs 0.6737,
# 1.21 vs 1.2000), and the offset is deliberate — the estimate has to stay conservative against
# `measure_text.swift`. Scaling keeps that margin; substituting would spend it.
FONT_CANDIDATES = {
    "nanum": ("NanumSquare Round (현행)", styles.FONT_FAMILY,
              styles.FONT_REGULAR, styles.FONT_BOLD, 0.7042, 0.5010, 1.1350),
    "suit": ("SUIT", "SUIT", "SUIT-Regular", "SUIT-Bold", 0.6726, 0.4728, 1.2480),
    "apple": ("Apple SD Gothic Neo (구)", "Apple SD Gothic Neo",
              "AppleSDGothicNeo-Regular", "AppleSDGothicNeo-Bold", 0.6737, 0.4500, 1.2000),
}
APPLE_SD = FONT_CANDIDATES["apple"][4:]


def _use_font(key: str):
    """``styles.use_font`` for a candidate, its metrics scaled onto the deck's own estimates."""
    _label, family, regular, bold, ko_advance, latin, pitch = FONT_CANDIDATES[key]
    return styles.use_font(
        family, regular, bold,
        layout.CHAR_W_KO * ko_advance / APPLE_SD[0],
        latin,  # measured, not scaled — see styles.CHAR_W_EN
        max(layout.LINE_PITCH, layout.LINE_PITCH * pitch / APPLE_SD[2]),
    )


# One long heading in each placement — the two the deck emits today (#234).
KEYED_HEADINGS = [("회개로의 초대", "top"), ("죄사함의 선포", "bottom")]


def _keyed_cues(pres, still: Path | None, headings, make_slide) -> list[str]:
    """One keyed cue per heading, optionally over a camera still, and their uuids."""
    uuids = []
    for heading, placement in headings:
        slide = make_slide(heading, placement)
        if still:
            # Last, which is the *back* of ProPresenter's front-to-back element list.
            el.image(slide, (0.0, 0.0, *styles.CANVAS), str(still))
        uuids.append(build.add_cue(pres, slide, f"{heading} ({placement})"))
    return uuids


def _backdrop(strength: str) -> styles.Backdrop:
    """The candidate backdrop for ``strength``, straight out of the bake script's own table.

    Read from ``make_backdrop`` rather than ``styles.BACKDROPS`` because only the *shipped*
    strength is committed — the others are rendered locally by ``make_backdrop.py --all`` and
    would otherwise have to be duplicated into the style module to be nameable here.
    """
    spec = importlib.util.spec_from_file_location(
        "make_backdrop", Path(__file__).with_name("make_backdrop.py")
    )
    make_backdrop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_backdrop)
    _blur, _brightness, tint = make_backdrop.STRENGTHS[strength]
    image = Path(styles.BACKDROP.image).with_name(
        Path(styles.BACKDROP.image).name.replace(f"-{styles.BACKDROP_STRENGTH}", f"-{strength}")
    )
    if not image.exists():
        raise SystemExit(f"{image.name} not baked — run: python scripts/make_backdrop.py --all")
    return styles.Backdrop(str(image), tint)


def make_candidates(out_pro: Path, still: Path | None = None) -> Path:
    """The #247 comparison deck: backdrop strengths, then keyed-label plates.

    ``still`` puts a live-camera frame *under* each keyed slide instead of leaving it on chroma
    green. Green is the contract (#192) and what the generator actually ships; a green rectangle
    just cannot be judged on a ProPresenter screen, so the still is a meeting aid and the group
    names say so (#241). It goes on last, which is the *back* of ProPresenter's front-to-back
    element list, so it sits under the plate rather than over it.
    """
    pres = build.new_presentation(out_pro.stem)

    for index, strength in enumerate(BACKDROP_CANDIDATES):
        with styles.use_backdrop(_backdrop(strength)):
            slides = [
                # The scripture slide first: it is the densest white text in the deck and so the
                # worst case for a backdrop that has been let up.
                ("성경 봉독", styles.verse_fullscreen(
                    "[요 1:9-12, 개역한글]", VERSE_KO, "[John 1:9-12, ESV]", VERSE_EN)),
                ("섹션 디바이더", styles.section_divider("봉 헌", "나 속죄함을 받은 후")),
                ("인트로", styles.service_intro(
                    "2부", "한 사람의 용기와 믿음의 파급력", "삼상 14:1-23", "2026년 9월 6일")),
            ]
        label = f"배경 {strength}" + (" (현행)" if strength == styles.BACKDROP_STRENGTH else "")
        build.add_group(
            pres, label, styles.SONG_COLORS[index % len(styles.SONG_COLORS)],
            [build.add_cue(pres, slide, name) for name, slide in slides],
        )

    for index, (label, variant) in enumerate(KEYED_CANDIDATES):
        build.add_group(
            pres, f"라벨 {label}" + (" [카메라 스틸, 리뷰용]" if still else ""),
            styles.SONG_COLORS[index % len(styles.SONG_COLORS)],
            _keyed_cues(pres, still, KEYED_HEADINGS,
                        lambda h, p, v=variant: styles.keyed_label(h, p, v)),
        )

    out_pro.parent.mkdir(parents=True, exist_ok=True)
    build.serialize(pres, str(out_pro))
    return out_pro


def make_font_candidates(out_pro: Path, still: Path | None = None) -> Path:
    """The #247 follow-up deck: the same drawn plate, one group per candidate Korean face.

    Only the face changes between groups — fill, corner, padding, size and tracking are the ones
    the operator's restyle settled. 합심 기도 is in the set because it is the shortest heading the
    deck emits, and the plate hugs its heading: a face's advance shows up as plate width there
    before it shows up anywhere else.
    """
    pres = build.new_presentation(out_pro.stem)
    for index, key in enumerate(FONT_CANDIDATES):
        with _use_font(key):
            uuids = _keyed_cues(pres, still, KEYED_HEADINGS + [("합심 기도", "top")],
                                styles.keyed_label)
        label = FONT_CANDIDATES[key][0]
        build.add_group(
            pres, f"서체 {label}" + (" [카메라 스틸, 리뷰용]" if still else ""),
            styles.SONG_COLORS[index % len(styles.SONG_COLORS)], uuids,
        )
    out_pro.parent.mkdir(parents=True, exist_ok=True)
    build.serialize(pres, str(out_pro))
    return out_pro


def _announcement_sampler(runs_dir: Path) -> list[str]:
    """One real notice per distinct *shape* the church has published, simplest shape first.

    "Shape" is what the plate has to cope with — which labels the rail ends up carrying, how many
    plates the notice splits into, and whether any prose is left under the rail — not what the
    notice says. Deduplicating on that turns 112 near-identical past notices into the ~30 worth
    looking at, while guaranteeing every awkward one is in the deck: the five-row rail, the one
    with nothing liftable at all, the one long enough to need three plates, and each distinct
    rail vocabulary the bulletin has used (날짜/시간/장소/문의, but also 대상/비용/주제/영유아부…),
    since an unfamiliar label is exactly where a two-column rail can fall over. The most recent
    notice of each shape wins, so the deck reads like the weeks ahead rather than last spring.
    """
    seen: dict[tuple, str] = {}
    for path in sorted(runs_dir.glob("*.json")):
        try:
            blocks = json.loads(path.read_text()).get("announcements") or []
        except (json.JSONDecodeError, OSError):
            continue
        for block in blocks:
            item = announce.parse_item(block)
            shape = (
                len(item.rows),
                len(styles.split_announcement(item)),
                bool(item.paragraphs),
                tuple(label for label, _ in item.rows),
            )
            seen[shape] = block
    return [seen[shape] for shape in sorted(seen)]


def make_announcement_review(out_pro: Path, runs_dir: Path) -> Path:
    """A 교회 소식-only deck built from the real past notices ``_announcement_sampler`` picks."""
    blocks = _announcement_sampler(runs_dir)
    if not blocks:
        raise SystemExit(f"no reviewed runs with announcements under {runs_dir}")
    pres = build.new_presentation(out_pro.stem)
    build.fill_announcements(pres, blocks)
    out_pro.parent.mkdir(parents=True, exist_ok=True)
    build.serialize(pres, str(out_pro))
    print(f"{len(blocks)} notices -> {len(pres.cues) - 2} plates")
    return out_pro


def make_demo(out_pro: Path, image: Path | None = None) -> Path:
    pres = build.new_presentation(out_pro.stem)

    def section(label: str, slides: list[tuple[str, object]]) -> None:
        """Add one cue per slide and wrap them in a named, colored ProPresenter group."""
        uuids = [build.add_cue(pres, slide, name) for name, slide in slides]
        build.add_group(pres, label, styles.GROUP_COLORS.get(label), uuids)

    lyric = styles.worship_lyric_ko(LYRIC_KO)
    bilingual = styles.worship_lyric_bilingual(*LYRIC_BI)

    section(
        "예배의 부름",
        [
            ("예배의 부름", styles.section_divider("예배의 부름", "[ 요 1:9-12 ]")),
            ("요 1:9-10", styles.verse_fullscreen(
                "[요 1:9-12, 개역한글]", VERSE_KO, "[John 1:9-12, ESV]", VERSE_EN)),
        ],
    )
    section(
        "찬양",
        [
            ("다시 한 번", styles.song_banner("다시 한 번")),
            ("C1", lyric),
            ("C1 (KO+EN)", bilingual),  # the pre-filled bilingual lyric style (#228)
            ("blank", styles.blank_green()),
        ],
    )
    section(
        "성가대 찬양",
        [("주 은혜라", styles.song_title("주 은혜라", "(노희석 편곡)"))],
    )
    section("사도신경", [
        ("사도신경 문답 1", styles.liturgy_responsive("사도신경", *CREED_RESPONSIVE)),
        ("blank", styles.blank_green()),  # the break between the two forms (#244)
        ("사도신경 1", styles.liturgy("사도신경", CREED)),
    ])
    section(
        "봉 헌",
        [("봉 헌", styles.section_divider("봉 헌", "[ 나 속죄함을 받은 후 ]  (찬 283장)"))]
        + ([("hymn page", styles.image(str(image)))] if image else []),
    )
    section("교회 소식", [
        (block.partition("\n")[0], styles.announcement("교회 소식", item, number, len(ANNOUNCEMENTS)))
        for number, block in enumerate(ANNOUNCEMENTS, start=1)
        for item in [announce.parse_item(block)]
    ])

    out_pro.parent.mkdir(parents=True, exist_ok=True)
    build.serialize(pres, str(out_pro))
    return out_pro


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="destination .pro")
    ap.add_argument("--image", type=Path, help="a PNG to place on a full-bleed image slide")
    ap.add_argument("--run", help="build the full weekly deck from this run date (YYYY-MM-DD)")
    ap.add_argument("--candidates", action="store_true",
                    help="write the #247 comparison deck — backdrop strengths + keyed-label plates")
    ap.add_argument("--fonts", action="store_true",
                    help="write the #247 font deck — the drawn plate in each candidate Korean face")
    ap.add_argument("--font", choices=sorted(FONT_CANDIDATES),
                    help="set the whole deck in this candidate face (#247); pairs with --run")
    ap.add_argument("--over", type=Path,
                    help="a camera still to put under the keyed slides so they read in PP (#241)")
    ap.add_argument(
        "--bundle", action="store_true",
        help="also pack the .pro and its media into a single-file .probundle (#236)",
    )
    ap.add_argument("--announcements", action="store_true",
                    help="build a 교회 소식-only deck covering every past notice shape (#233)")
    ap.add_argument("--runs-dir", type=Path, default=store.RUNS_DIR,
                    help="where the reviewed runs live (default: data/runs)")
    args = ap.parse_args()

    if args.candidates:
        out = (args.out if args.out != DEFAULT_OUT
               else DEFAULT_OUT.with_name("Style Candidates 247.pro"))
        written = make_candidates(out, args.over)
        print(f"Wrote {written}")
    elif args.fonts:
        out = (args.out if args.out != DEFAULT_OUT
               else DEFAULT_OUT.with_name("Style Candidates 247 서체.pro"))
        written = make_font_candidates(out, args.over)
        print(f"Wrote {written}")
    elif args.announcements:
        out = args.out if args.out != DEFAULT_OUT else DEFAULT_OUT.with_name("교회 소식 Review.pro")
        written = make_announcement_review(out, args.runs_dir)
        print(f"Wrote {written}")
    elif args.run:
        suffix = f" {FONT_CANDIDATES[args.font][0]}" if args.font else ""
        out = (args.out if args.out != DEFAULT_OUT
               else DEFAULT_OUT.with_name(f"{args.run}{suffix}.pro"))
        out.parent.mkdir(parents=True, exist_ok=True)
        with _use_font(args.font) if args.font else nullcontext():
            written, steps = build.build(store.load(args.run), str(out))
        print(f"Wrote {written} ({sum(steps.values()):.2f}s)")
    else:
        written = make_demo(args.out, args.image)
        print(f"Wrote {written}")
    if args.bundle:
        packed = bundle.write_bundle(written)
        print(f"Wrote {packed} ({packed.stat().st_size / 1e6:.1f} MB) — import this one file.")
    print("Open it in ProPresenter (restart PP if the library doesn't refresh).")
