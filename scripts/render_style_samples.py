"""Render #189 sample slide-style options to PNG (1920x1080).

Lyric lower-thirds get 3 options (A 검정 스트립 / B 플레인 / C 블러 박스);
full-screen sections (verse / announce / divider / liturgy) get 5 options
(1 클래식 세리프 / 2 차콜 골드 / 3 네이비 프레임 / 4 로열 블루 / 5 버건디).
HTML/CSS mockups screenshotted with the already-installed Playwright Chromium.

Content mimics the actual 2026-07-05 service (data/runs/2026-07-05.json +
templates/master.key slide texts); announcement member names are scrubbed
because these PNGs are committed to docs/.

Inputs (git-ignored): data/style-samples/fonts/ and data/style-samples/bg/.
Output: docs/style-samples/{a,b,c}-lyric-*.png and f{1..5}-<section>.png

Usage: .venv/bin/python scripts/render_style_samples.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "data" / "style-samples"
# The Option 3 backdrop. Points at the committed #224 *source* photo, not the baked PNG: the CSS
# below applies the same blur/brightness/saturate the bake does, so a baked file would blur twice.
# It used to read `data/style-samples/bg/bg-band.jpg`, a church-livestream still that is
# git-ignored — meaning docs/style-samples/f3-*.png could not be re-rendered from a clean
# checkout. The keyed lyric slides still use that camera frame, and must: they key over live
# camera, so a flat colour would misrepresent them (#241).
BACKDROP_SRC = (
    ROOT / "src/worship_deck/propresenter/assets/backdrops/church-exterior.jpg"
).as_uri()
OUT = ROOT / "docs" / "style-samples"
HTML_DIR = ASSETS / "html"

# ------------------------------------------------------------------ content
# Real 2026-07-05 service (announcement member names scrubbed).

LYRIC_KO = ["다시 한 번 외쳐 부르니", "예수여 나를 돌아 보소서"]  # 다시 한 번, C1
LYRIC_BI_KO = "주 하나님 지으신 모든 세계"  # 2026-06-28 service
LYRIC_BI_EN = "O Lord my God, when I in awesome wonder"

VERSE_LABEL_KO = "[요 1:9-12, 개역한글]"
VERSE_KO = [
    (9, "참 빛 곧 세상에 와서 각 사람에게 비취는 빛이 있었나니"),
    (10, "그가 세상에 계셨으며 세상은 그로 말미암아 지은 바 되었으되 세상이 그를 알지 못하였고"),
]
VERSE_LABEL_EN = "[John 1:9-12, ESV]"
VERSE_EN = [
    (9, "The true light, which gives light to everyone, was coming into the world."),
    (10, "He was in the world, and the world was made through him, yet the world did not know him."),
]

ANNOUNCE_TITLE = "교회 소식"
ANNOUNCE_ITEMS = [
    ("성찬식", "7/5 (오늘) 성찬식이 있습니다."),
    ("제직회", "7/5 (오늘) 1:30 PM 친교실에서 제직회가 있습니다."),
    ("에티오피아 단기선교", "7/9 (목) – 7/19 (주일) 에티오피아 단기선교를 위해 계속해서 기도 부탁드립니다."),
    ("노스필드 여름성경학교 (VBS)", "영유아부 8/3 (월) – 8/4 (화) 9am–12pm · 초등부 8/5 (수) – 8/7 (금) 9am–3pm"),
]

DIVIDER_KO = "봉 헌"
DIVIDER_SUB = "[ 나 속죄함을 받은 후 ]  (찬 283장)"

LITURGY_TITLE = "사도신경"
LITURGY_KO = [
    "전능하사 천지를 만드신 하나님 아버지를 내가 믿사오며",
    "그 외아들 우리 주 예수 그리스도를 믿사오니",
    "이는 성령으로 잉태하사 동정녀 마리아에게 나시고",
    "본디오 빌라도에게 고난을 받으사",
    "십자가에 못박혀 죽으시고",
    "장사한 지 사흘 만에 죽은 자 가운데서 다시 살아나시며",
    "하늘에 오르사 전능하신 하나님 우편에 앉아 계시다가",
]

# ------------------------------------------------------------------ styles

FONT_FACES = """
@font-face { font-family: Pretendard; src: url('../fonts/PretendardVariable.woff2') format('woff2-variations'); font-weight: 45 920; }
@font-face { font-family: SUIT; src: url('../fonts/SUIT-Variable.woff2') format('woff2-variations'); font-weight: 100 900; }
@font-face { font-family: 'Noto Sans KR'; src: url('../fonts/NotoSansKR.ttf') format('truetype-variations'); font-weight: 100 900; }
@font-face { font-family: 'Noto Serif KR'; src: url('../fonts/NotoSerifKR-VF.otf') format('opentype-variations'); font-weight: 200 900; }
"""

BASE_CSS = (
    FONT_FACES
    + """
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1920px; height: 1080px; overflow: hidden; }
body { position: relative; color: #fff; }
.cam { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.fs { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.badge { position: absolute; top: 34px; right: 44px; z-index: 10; font-size: 30px; font-weight: 700;
  color: rgba(255,255,255,.4); letter-spacing: 2px; }
"""
)

# Lyric lower-third options (over live camera). 3 options per the team's ask.
LYRIC_STYLES = {
    "a": {"name": "A — 검정 스트립", "font": "Pretendard"},
    "b": {"name": "B — 플레인", "font": "SUIT"},
    "c": {"name": "C — 블러 박스", "font": "'Noto Sans KR'"},
}

# Full-screen options. All white-on-dark (confirmed); span classic ↔ modern —
# the church (npcwheeling.com) reads modern-traditional hybrid, navy-leaning,
# so no black+red: palettes are navy/charcoal/burgundy families.
FS_STYLES = {
    "f1": {  # 전통 예식서/찬송가 느낌: 세리프 + 상아색 + 금색 괘선
        "name": "1 — 클래식 세리프",
        "font": "'Noto Serif KR'",
        "accent": "#C9A557",
        "ink": "#F2ECDD",
        "muted": "rgba(242,236,221,.62)",
        "bg": "background: linear-gradient(165deg, #1C2C4E 0%, #131E38 55%, #0D1526 100%);",
        "photo": False,
    },
    "f2": {  # 따뜻한 차콜 + 골드 (구 B)
        "name": "2 — 차콜 골드",
        "font": "SUIT",
        "accent": "#D9A441",
        "ink": "#FFFFFF",
        "muted": "rgba(255,255,255,.66)",
        "bg": "background: radial-gradient(ellipse at 50% 38%, #2A2620 0%, #1B1916 62%, #131110 100%);",
        "photo": False,
    },
    "f3": {  # 현재 덱과 가장 비슷: 네이비 + 흐린 사진 + 프레임 박스 (구 C)
        "name": "3 — 네이비 프레임",
        "font": "'Noto Sans KR'",
        "accent": "#FFD447",
        "ink": "#FFFFFF",
        "muted": "rgba(255,255,255,.72)",
        "bg": "background: #10203B;",
        "photo": True,
    },
    "f4": {  # 베델(어바인)식 로열 블루 그라데이션 — 모던하지만 교회색
        "name": "4 — 로열 블루",
        "font": "Pretendard",
        "accent": "#9DC1F0",
        "ink": "#FFFFFF",
        "muted": "rgba(255,255,255,.7)",
        "bg": "background: linear-gradient(120deg, #0B1A43 0%, #1D3C8C 52%, #101F4E 100%);",
        "photo": False,
    },
    "f5": {  # 버건디 클래식 — 전통 교회색(포도주) + 크림, 세리프
        "name": "5 — 버건디 클래식",
        "font": "'Noto Serif KR'",
        "accent": "#D8A874",
        "ink": "#F4E9DA",
        "muted": "rgba(244,233,218,.62)",
        "bg": "background: linear-gradient(160deg, #3A1420 0%, #260E15 60%, #1A0A0F 100%);",
        "photo": False,
    },
}

SERIF_STYLES = ("f1", "f5")


def page(font: str, extra_css: str, body: str, badge: str = "") -> str:
    badge_html = f"<div class='badge'>{badge}</div>" if badge else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + BASE_CSS
        + f"body {{ font-family: {font}, 'Apple SD Gothic Neo', sans-serif; }}"
        + extra_css
        + "</style></head><body>"
        + body
        + badge_html
        + "</body></html>"
    )


# photo-blur backdrop used by f3 (Box Blur look, current-deck modernization)
PHOTO_BG = """
.photo { position: absolute; inset: -40px; width: calc(100% + 80px); height: calc(100% + 80px);
  object-fit: cover; filter: blur(26px) brightness(.32) saturate(.75); }
.tint { position: absolute; inset: 0; background: rgba(16,32,59,.62); }
.frame { position: relative; border: 1.5px solid rgba(255,255,255,.32); border-radius: 10px;
  padding: 64px 100px; max-width: 1640px; background: rgba(10,20,40,.35); }
"""


def fs_wrap(style_id: str, inner: str, bg_img: str = BACKDROP_SRC) -> str:
    s = FS_STYLES[style_id]
    if s["photo"]:
        return (
            f"<img class='photo' src='{bg_img}'><div class='tint'></div>"
            f"<div class='fs'><div class='frame'>{inner}</div></div>"
        )
    return f"<div class='fs' style=\"{s['bg']}\">{inner}</div>"


def fs_page(style_id: str, extra_css: str, inner: str, bg_img: str = BACKDROP_SRC) -> str:
    s = FS_STYLES[style_id]
    css = (PHOTO_BG if s["photo"] else "") + f"body {{ color: {s['ink']}; }}" + extra_css
    return page(s["font"], css, fs_wrap(style_id, inner, bg_img), badge=style_id[1])


# ------------------------------------------------------------- lyric slides


def lyric_ko(style_id: str) -> str:
    s = LYRIC_STYLES[style_id]
    lines = "".join(f"<div class='ko'>{ln}</div>" for ln in LYRIC_KO)
    if style_id == "a":
        css = """
/* Hillsong style (ref-hillsong.png): per-line black strip hugging the text,
   not a full-width bar */
.zone { position: absolute; left: 0; right: 0; bottom: 72px; text-align: center; }
.ko { font-size: 68px; font-weight: 800; letter-spacing: -.5px; }
.ko span { display: inline-block; background: #000; padding: 10px 34px 14px; margin-top: 10px; }
"""
        lines = "".join(f"<div class='ko'><span>{ln}</span></div>" for ln in LYRIC_KO)
        body = f"<img class='cam' src='../bg/bg-band.jpg'><div class='zone'>{lines}</div>"
    elif style_id == "b":
        css = """
.scrim { position: absolute; left: 0; right: 0; bottom: 0; height: 420px;
  background: linear-gradient(to top, rgba(0,0,0,.72), rgba(0,0,0,0)); }
.zone { position: absolute; left: 0; right: 0; bottom: 88px; text-align: center; }
.ko { font-size: 74px; font-weight: 700; line-height: 1.45;
  text-shadow: 0 2px 8px rgba(0,0,0,.95), 0 10px 44px rgba(0,0,0,.75); }
"""
        body = f"<img class='cam' src='../bg/bg-band.jpg'><div class='scrim'></div><div class='zone'>{lines}</div>"
    else:
        css = """
.zone { position: absolute; left: 0; right: 0; bottom: 64px; display: flex; justify-content: center; }
.box { background: rgba(16,32,59,.55); backdrop-filter: blur(18px); border: 1px solid rgba(255,255,255,.18);
  border-radius: 18px; padding: 38px 96px; text-align: center; }
.ko { font-size: 68px; font-weight: 700; line-height: 1.5; }
"""
        body = f"<img class='cam' src='../bg/bg-band.jpg'><div class='zone'><div class='box'>{lines}</div></div>"
    return page(s["font"], css, body, badge=style_id.upper())


def lyric_bi(style_id: str) -> str:
    s = LYRIC_STYLES[style_id]
    if style_id == "a":
        css = """
.zone { position: absolute; left: 0; right: 0; bottom: 64px; text-align: center; }
.ko { font-size: 66px; font-weight: 800; letter-spacing: -.5px; }
.ko span { display: inline-block; background: #000; padding: 10px 34px 14px; }
.en { font-size: 34px; font-weight: 500; margin-top: 10px;
  text-transform: uppercase; letter-spacing: 1.5px; }
.en span { display: inline-block; background: #000; color: rgba(255,255,255,.78); padding: 8px 26px 11px; }
"""
        inner = (
            f"<div class='ko'><span>{LYRIC_BI_KO}</span></div>"
            f"<div class='en'><span>{LYRIC_BI_EN}</span></div>"
        )
        body = f"<img class='cam' src='../bg/bg-band.jpg'><div class='zone'>{inner}</div>"
    elif style_id == "b":
        css = """
.scrim { position: absolute; left: 0; right: 0; bottom: 0; height: 420px;
  background: linear-gradient(to top, rgba(0,0,0,.72), rgba(0,0,0,0)); }
.zone { position: absolute; left: 0; right: 0; bottom: 84px; text-align: center;
  text-shadow: 0 2px 8px rgba(0,0,0,.95), 0 10px 44px rgba(0,0,0,.75); }
.ko { font-size: 72px; font-weight: 700; }
.en { font-size: 38px; font-weight: 400; color: rgba(255,255,255,.85); margin-top: 16px; }
"""
        inner = f"<div class='ko'>{LYRIC_BI_KO}</div><div class='en'>{LYRIC_BI_EN}</div>"
        body = f"<img class='cam' src='../bg/bg-band.jpg'><div class='scrim'></div><div class='zone'>{inner}</div>"
    else:
        css = """
.zone { position: absolute; left: 0; right: 0; bottom: 60px; display: flex; justify-content: center; }
.box { background: rgba(16,32,59,.55); backdrop-filter: blur(18px); border: 1px solid rgba(255,255,255,.18);
  border-radius: 18px; padding: 34px 90px; text-align: center; }
.ko { font-size: 66px; font-weight: 700; }
.en { font-size: 36px; font-weight: 400; color: rgba(255,255,255,.8); margin-top: 14px; }
"""
        inner = f"<div class='ko'>{LYRIC_BI_KO}</div><div class='en'>{LYRIC_BI_EN}</div>"
        body = f"<img class='cam' src='../bg/bg-band.jpg'><div class='zone'><div class='box'>{inner}</div></div>"
    return page(s["font"], css, body, badge=style_id.upper())


# -------------------------------------------------------- full-screen slides


def verse(style_id: str) -> str:
    s = FS_STYLES[style_id]
    serif = style_id in SERIF_STYLES
    ko = "".join(
        f"<div class='kline'><span class='vn'>{n}</span>{t}</div>" for n, t in VERSE_KO
    )
    en = "".join(
        f"<div class='eline'><span class='vn'>{n}</span>{t}</div>" for n, t in VERSE_EN
    )
    css = f"""
.wrap {{ max-width: 1560px; }}
.label {{ font-size: 31px; color: {s['accent']}; margin-bottom: 42px;
  font-weight: {600 if serif else 700}; letter-spacing: {'0' if serif else '1px'}; }}
.kline {{ font-size: 47px; font-weight: {600 if serif else 600}; line-height: 1.66; }}
.vn {{ font-size: .55em; color: {s['accent']}; vertical-align: .5em; margin-right: 16px; font-weight: 700; }}
.gap {{ width: {'96px' if serif else '84px'}; height: {'2px' if serif else '1px'};
  background: {s['accent']}; opacity: .8; margin: 46px auto 36px; }}
.elabel {{ font-size: 25px; font-weight: 500; color: {s['accent']}; opacity: .8; margin-bottom: 20px; }}
.eline {{ font-size: 31px; font-weight: {400 if serif else 350}; line-height: 1.6; color: {s['muted']}; }}
"""
    inner = (
        f"<div class='wrap'><div class='label'>{VERSE_LABEL_KO}</div><div>{ko}</div>"
        f"<div class='gap'></div>"
        f"<div class='elabel'>{VERSE_LABEL_EN}</div><div>{en}</div></div>"
    )
    return fs_page(style_id, css, inner)


def announce(style_id: str) -> str:
    s = FS_STYLES[style_id]
    serif = style_id in SERIF_STYLES
    items = "".join(
        f"<li><div class='it'><span class='num'>{i + 1}.</span>{t}</div><div class='ib'>{b}</div></li>"
        for i, (t, b) in enumerate(ANNOUNCE_ITEMS)
    )
    css = f"""
.title {{ font-size: 58px; font-weight: {700 if serif else 700};
  letter-spacing: {'4px' if serif else '8px'}; text-indent: {'4px' if serif else '8px'}; }}
.title::after {{ content: ''; display: block; width: 96px; height: {'2px' if serif else '3px'};
  background: {s['accent']}; margin: 30px auto 0; opacity: .9; }}
ul {{ list-style: none; margin-top: 66px; max-width: 1460px; text-align: left; }}
li {{ margin-bottom: 44px; }}
.it {{ font-size: 41px; font-weight: 700; }}
.num {{ color: {s['accent']}; margin-right: 22px; }}
.ib {{ font-size: 33px; font-weight: {400 if serif else 400}; line-height: 1.45;
  color: {s['muted']}; margin: 10px 0 0 58px; }}
"""
    inner = f"<div class='title'>{ANNOUNCE_TITLE}</div><ul>{items}</ul>"
    return fs_page(style_id, css, inner)


def divider(style_id: str) -> str:
    serif = style_id in SERIF_STYLES
    s = FS_STYLES[style_id]
    css = f"""
.frame {{ padding: 96px 200px; }}
.ko {{ font-size: 136px; font-weight: {700 if serif else 700}; letter-spacing: 30px; text-indent: 30px; }}
.rule {{ width: {'110px' if serif else '90px'}; height: {'2px' if serif else '3px'};
  background: {s['accent']}; margin: 58px auto 46px; opacity: .9; }}
.sub {{ font-size: 37px; font-weight: {500 if serif else 500}; color: {s['muted']}; letter-spacing: 2px; }}
.sub b {{ color: {s['accent']}; font-weight: inherit; }}
"""
    inner = f"<div class='ko'>{DIVIDER_KO}</div><div class='rule'></div><div class='sub'>{DIVIDER_SUB}</div>"
    return fs_page(style_id, css, inner)


def liturgy(style_id: str) -> str:
    s = FS_STYLES[style_id]
    serif = style_id in SERIF_STYLES
    ko = "".join(f"<div class='kline'>{ln}</div>" for ln in LITURGY_KO)
    css = f"""
.title {{ font-size: 38px; font-weight: {600 if serif else 600}; color: {s['accent']};
  letter-spacing: {'8px' if serif else '12px'}; text-indent: {'8px' if serif else '12px'}; margin-bottom: 58px; }}
.kline {{ font-size: 46px; font-weight: {500 if serif else 500}; line-height: 1.82; }}
"""
    inner = f"<div class='title'>{LITURGY_TITLE}</div><div>{ko}</div>"
    return fs_page(style_id, css, inner)


LYRIC_SECTIONS = {"lyric-ko": lyric_ko, "lyric-bi": lyric_bi}
FS_SECTIONS = {"verse": verse, "announce": announce, "divider": divider, "liturgy": liturgy}

# ------------------------------------------------- meeting-deck label slides

LABELS_DIR = ASSETS / "labels"
LYRIC_LEGEND = "가사 A 검정 스트립 · B 플레인 · C 블러 박스"
FS_LEGEND = "전체화면 1 클래식 세리프 · 2 차콜 골드 · 3 네이비 프레임 · 4 로열 블루 · 5 버건디"
LABEL_SLIDES = {
    "00-title": ("슬라이드 스타일 샘플", LYRIC_LEGEND + "<br>" + FS_LEGEND),
    "10-lyric-ko": ("1. 예배 찬양 — 한글 2줄", "lower-third · 옵션 A / B / C"),
    "20-lyric-bi": ("2. 예배 찬양 — 한글 + 영어", "lower-third · 옵션 A / B / C"),
    "30-verse": ("3. 성경 봉독", "full-screen · 옵션 1 – 5"),
    "40-announce": ("4. 교회 소식", "full-screen · 옵션 1 – 5"),
    "50-divider": ("5. 섹션 표제 (봉헌)", "full-screen · 옵션 1 – 5"),
    "60-liturgy": ("6. 사도신경", "full-screen · 옵션 1 – 5"),
}


def label_slide(title: str, sub: str) -> str:
    css = """
.t { font-size: 88px; font-weight: 700; }
.s { font-size: 34px; font-weight: 400; color: rgba(255,255,255,.55); margin-top: 44px; line-height: 1.7; }
"""
    body = f"<div class='fs' style='background:#15171B'><div class='t'>{title}</div><div class='s'>{sub}</div></div>"
    return page("Pretendard", css, body)


# ------------------------------------------------------------------ render


def main() -> None:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for style_id in LYRIC_STYLES:
        for section, fn in LYRIC_SECTIONS.items():
            name = f"{style_id}-{section}"
            html_path = HTML_DIR / f"{name}.html"
            html_path.write_text(fn(style_id), encoding="utf-8")
            jobs.append((name, html_path, OUT))
    for style_id in FS_STYLES:
        for section, fn in FS_SECTIONS.items():
            name = f"{style_id}-{section}"
            html_path = HTML_DIR / f"{name}.html"
            html_path.write_text(fn(style_id), encoding="utf-8")
            jobs.append((name, html_path, OUT))
    for name, (title, sub) in LABEL_SLIDES.items():
        html_path = HTML_DIR / f"label-{name}.html"
        html_path.write_text(label_slide(title, sub), encoding="utf-8")
        jobs.append((name, html_path, LABELS_DIR))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        for name, html_path, out_dir in jobs:
            pg.goto(html_path.as_uri())
            pg.evaluate("document.fonts.ready.then(() => {})")
            pg.wait_for_function("document.fonts.status === 'loaded'")
            pg.wait_for_timeout(120)
            pg.screenshot(path=str(out_dir / f"{name}.png"))
            print(f"rendered {out_dir.name}/{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
