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
    .venv/bin/python scripts/make_pro_demo.py --candidates       # keyed-label plates, M1 vs A
    .venv/bin/python scripts/make_pro_demo.py --announcements --out /tmp/a1.pro

ProPresenter caches a ``.pro`` it has already read, so iterate by writing a *new* filename each
round (``--out``) rather than overwriting and restarting the app.
"""

import argparse
import json
from pathlib import Path

from worship_deck import store
from worship_deck.propresenter import announce, build, bundle, content, styles

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


# The keyed-label plates, one group each, both placements per group — arrow through them over a
# live camera to compare. #234 picked M1; A (Keynote's own watercolour) is kept so the church
# group can see the two side by side in the #241 style review.
KEYED_CANDIDATES = [
    ("M1 각진 바 + 금색 룰", "M1"),
    ("A 붓터치 (현행 Keynote)", "A"),
]


def make_candidates(out_pro: Path) -> Path:
    """A deck of keyed-label plates — nothing but section labels over chroma green (#234/#241)."""
    pres = build.new_presentation(out_pro.stem)
    for label, variant in KEYED_CANDIDATES:
        uuids = [
            build.add_cue(
                pres, styles.keyed_label(heading, placement, variant), f"{heading} ({placement})"
            )
            for heading in ("회개로의 초대", "죄사함의 선포")
            for placement in ("top", "bottom")
        ]
        build.add_group(pres, label, styles.SONG_COLORS[KEYED_CANDIDATES.index((label, variant))
                                                        % len(styles.SONG_COLORS)], uuids)
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
                    help="write the keyed-label plate comparison (M1 vs A) instead of the demo")
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
               else DEFAULT_OUT.with_name("Keyed Label Candidates.pro"))
        written = make_candidates(out)
        print(f"Wrote {written}")
    elif args.announcements:
        out = args.out if args.out != DEFAULT_OUT else DEFAULT_OUT.with_name("교회 소식 Review.pro")
        written = make_announcement_review(out, args.runs_dir)
        print(f"Wrote {written}")
    elif args.run:
        out = args.out if args.out != DEFAULT_OUT else DEFAULT_OUT.with_name(f"{args.run}.pro")
        out.parent.mkdir(parents=True, exist_ok=True)
        written, steps = build.build(store.load(args.run), str(out))
        print(f"Wrote {written} ({sum(steps.values()):.2f}s)")
    else:
        written = make_demo(args.out, args.image)
        print(f"Wrote {written}")
    if args.bundle:
        packed = bundle.write_bundle(written)
        print(f"Wrote {packed} ({packed.stat().st_size / 1e6:.1f} MB) — import this one file.")
    print("Open it in ProPresenter (restart PP if the library doesn't refresh).")
