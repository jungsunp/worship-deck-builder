"""Generate synthetic test fixtures for CI.

Run once on a Mac whenever the bulletin layout changes; commit the outputs.

    python scripts/make_fixtures.py

Requires: playwright + chromium (already core deps); Pillow only as fallback for
the sheet PNG when data/real-sheet.png is absent.
The Keynote step requires macOS + Keynote (AppleScript).

Sanitization rules applied to the bulletin:
  - All member names (기도제목, 헌금자 명단, 봉사자) → 무명/OOO
  - Offering total → $0.00
  - Staff phone numbers & emails → 000-000-0000 / xxx@example.com
  - Pastor/staff names → fixed pseudonyms (홍길동 목사, etc.)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
DATA = Path(__file__).parent.parent / "data"

# ── Staff pseudonyms (consistent across tests) ───────────────────────────────
# These replace real staff names so the fixture doesn't contain anyone's identity.
PASTOR = "홍길동 목사"
STAFF = {
    "영유아부": "이믿음 전도사",
    "초등부": "박소망 전도사",
    "중등부": "김사랑 전도사",
    "고등부": "최은혜 전도사",
    "청년부": "조성실 전도사",
    "worship_dir": "이경배 집사",
    "music_dir": "박찬양 형제",
    "pianist": "류음악 집사",
    "admin": "강행정 집사",
    "driver": "신운전 집사",
}


# ── Bulletin PDF ─────────────────────────────────────────────────────────────

def _bulletin_html() -> str:
    """Sanitized reproduction of the real bulletin layout and content.

    Columns are absolutely positioned so their PDF x-coordinates match the real
    bulletin (CSS px × 0.75 = PDF pt): left order column ≈26–309pt, middle 교회소식
    ≈348–688pt, right 기도제목 ≈694–980pt. The worship order is a bordered grid (its
    row rules anchor _parse_worship_order); the 교회소식 list ends at the bordered
    봉사자 footer boxes; each detail line is pre-broken so it renders as one row.
    Generated at margin:0 with a 1344×816px page (= 14in×8.5in at 96dpi).
    """
    p = PASTOR
    s = STAFF
    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ width: 1344px; }}
  body {{
    font-family: "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif;
    color: #111;
  }}
  .page {{ position: relative; width: 1344px; height: 816px; overflow: hidden; }}
  .page-break {{ page-break-after: always; }}
  .col {{ position: absolute; }}
  /* x-positions chosen so px×0.75 lands on the real bulletin's pt columns */
  #c1 {{ left: 34px; width: 380px; top: 36px; }}    /* order     ≈26–309pt */
  #c2 {{ left: 464px; width: 453px; top: 36px; }}   /* 교회소식  ≈348–688pt */
  #c3 {{ left: 925px; width: 381px; top: 36px; }}   /* 기도제목  ≈694–980pt */
  .colhead {{ font-size: 15px; font-weight: bold; margin-bottom: 6px; }}
  .lead {{ font-size: 13px; margin-bottom: 4px; }}

  /* single-column rows: each border spans the full width → one wide rule per row,
     like the real bulletin. The part name is a fixed-width inline span so the content
     text still starts past _X_SPLIT (≈105pt). The leader (.who) is pushed to the right
     so it lands in its own sub-column with a clear horizontal gap — the real bulletin's
     layout, which _split_performer separates by x-position (not by token vocabulary). */
  table.order {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  table.order td {{ border-top: 1px solid #555; border-bottom: 1px solid #555;
                    padding: 4px 2px; display: flex; }}
  table.order .part {{ flex: 0 0 120px; white-space: nowrap; }}
  table.order .title {{ white-space: nowrap; }}
  table.order .who {{ margin-left: auto; white-space: nowrap; padding-left: 24px; }}
  .foot {{ font-size: 12px; margin-top: 3px; }}

  .nextgen {{ margin-top: 60px; }}
  .nextgen .colhead {{ font-size: 13px; margin-bottom: 4px; }}
  table.ng {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  table.ng td {{ border-top: 1px solid #888; border-bottom: 1px solid #888;
                 padding: 3px 2px; vertical-align: top; }}
  table.ng td.part {{ width: 88px; white-space: nowrap; }}

  .ann h3 {{ font-size: 13px; font-weight: bold; margin: 7px 0 1px; }}
  .ann p {{ font-size: 12px; line-height: 1.35; margin: 0; }}

  .pray p {{ font-size: 12px; line-height: 1.35; margin: 1px 0; }}
  .pray .colhead {{ font-size: 13px; }}
  .small {{ font-size: 11px; color: #333; }}
  hr {{ border: none; border-top: 1px solid #aaa; margin: 5px 0; }}
  .box {{ border: 1px solid #888; padding: 4px 6px; margin: 5px 0; font-size: 11px; }}

  /* 봉사자 모집 footer — bordered boxes below the 교회소식 list (≈540pt) */
  .footer {{ position: absolute; left: 464px; width: 453px; top: 700px;
             display: flex; gap: 8px; }}
  .fbox {{ flex: 1; border: 1px solid #777; padding: 5px; font-size: 11px; }}

  .date-display {{ font-size: 18px; font-weight: bold; margin: 2px 0 6px; }}
</style>
</head>
<body>

<!-- ════ PAGE 1 ════ -->
<div class="page">

  <!-- Column 1: 주일예배순서 (worship order) — bordered grid -->
  <div class="col" id="c1">
    <div class="colhead">주일예배순서</div>
    <div class="lead">인도: {p}</div>
    <table class="order">
      <!-- 마라나타 is the worship BAND NAME (matches the real bulletin), not a song title:
           it sits in the right performer sub-column (.who), so it parses as the row's
           leader, not its content. The bulletin lists no opening-worship songs; they come
           from the band lead sheet into the top-level worship_songs field at assemble time.
           봉 헌 is sung by 남성 중창단 — an ensemble outside any token vocabulary, so it
           exercises _split_performer's x-position split (the #142-style regression). -->
      <tr><td><span class="part">찬 양</span><span class="who">마라나타</span></td></tr>
      <tr><td><span class="part">예배의 부름</span><span class="title">시 133:1-3</span><span class="who">{p}</span></td></tr>
      <tr><td><span class="part">고백의 찬양*</span><span class="title">믿음으로 우리는</span><span class="who">다함께</span></td></tr>
      <tr><td><span class="part">신앙고백*</span><span class="title">사도신경</span><span class="who">다함께</span></td></tr>
      <tr><td><span class="part">찬 양</span><span class="title">사랑은 (윤학준 곡)</span><span class="who">성가대</span></td></tr>
      <tr><td><span class="part">봉 헌</span><span class="title">피난처 있으니 (찬 70장)</span><span class="who">남성 중창단</span></td></tr>
      <tr><td><span class="part">환영 및 인사*</span><span class="who">다함께</span></td></tr>
      <tr><td><span class="part">교회소식</span><span class="who">{p}</span></td></tr>
      <tr><td><span class="part">합심기도</span><span class="who">다함께</span></td></tr>
      <tr><td><span class="part">말 씀</span><span class="title">설득된 믿음 (요한복음 4:43-54)</span><span class="who">{p}</span></td></tr>
      <tr><td><span class="part">파송의 노래*</span><span class="title">축복의 통로</span><span class="who">다함께</span></td></tr>
      <tr><td><span class="part">축 도*</span><span class="who">{p}</span></td></tr>
    </table>
    <div class="foot">(*표는 일어서서 하나님께 드립니다.)</div>

    <div class="nextgen">
      <div class="colhead">다음 세대예배</div>
      <table class="ng">
        <tr><td class="part">영유아부</td><td>({s['영유아부']})</td></tr>
        <tr><td class="part">초등부</td><td>Yes, Lord! (2 Kings 22:11) ({s['초등부']})</td></tr>
        <tr><td class="part">중고등부</td><td>Worship (Luke 8:22-25) ({s['중등부']})</td></tr>
        <tr><td class="part">청년부</td><td>성경공부 연합 ({s['청년부']})</td></tr>
      </table>
    </div>
  </div>

  <!-- Column 2: 교회소식 (announcements) -->
  <div class="col ann" id="c2">
    <div class="colhead">교회소식</div>
    <p>노스필드 장로교회는 "성경적 리더를 세워 파송"하는 교회입니다.</p>
    <p>오늘 우리 교회에 처음 오신 분들을 주님의 이름으로 환영합니다.</p>
    <p>교인 등록을 원하시는 분들은 사무실에 말씀해 주세요.</p>

    <h3>1. 2026년도 24 나무 소그룹</h3>
    <p>오늘부터 친교 시간에는 지정된 테이블로 이동하셔서</p>
    <p>그룹 리더분들의 안내에 따라 함께 친교해 주시기 바랍니다.</p>

    <h3>2. 교육부 오픈하우스 안내</h3>
    <p>5/17 (오늘) 교육부 오픈하우스가 열립니다.</p>
    <p>초등부에서 중등부로 올라가는 자녀를 둔 부모님들께서는</p>
    <p>자녀와 함께 새로운 부서 예배에 참여하시기 바랍니다.</p>

    <h3>3. 온세기 기도회</h3>
    <p>5/29 (금요일) 7:30 PM, 온세기 예배로 함께 모입니다.</p>
    <p>온 세대가 한마음으로 기도하는 자리에 성도님들을 초대합니다.</p>

    <h3>4. 교육부 졸업 연합예배</h3>
    <p>5/31 (주일) 2부 예배시 교육부 졸업예배가 함께 진행됩니다.</p>
    <p>총 15명의 학생들이 유아부, 초등부, 중등부, 고등부를 졸업합니다.</p>

    <h3>5. 노스필드 여름성경학교 (VBS) 안내</h3>
    <p>영유아부와 초등부 프로그램이 따로 진행됩니다.</p>
    <p>· 영유아부: 8/3-8/4 (월-화) 9am-12pm</p>
    <p>· 초등부: 8/5-8/7 (수-금) 9am-3pm</p>
    <p>5/24부터 5세 이상 외부 학생 온라인 등록이 진행됩니다.</p>

    <h3>6. 미디어 사역팀 팀원 모집</h3>
    <p>다음 세대예배 미디어 사역팀 봉사자를 모집합니다.</p>
    <p>(PPT 4명, 조명 1명, 음향 1명, 방송 1명, 카메라 1명)</p>
  </div>

  <!-- 봉사자 모집 footer boxes (bordered → bound the 교회소식 scan) -->
  <div class="footer">
    <div class="fbox">초등부 교사 모집<br>문의: {s['영유아부']}</div>
    <div class="fbox">성가대원 모집<br>문의: {s['worship_dir']}</div>
    <div class="fbox">미디어팀 모집<br>문의: OOO 집사</div>
    <div class="fbox">주차안내 봉사자<br>문의: OOO 집사</div>
  </div>

  <!-- Column 3: 기도제목 + 선교 + 헌금 -->
  <div class="col pray" id="c3">
    <div class="colhead">기도제목</div>
    <p>1. 하나님의 임재와 영광이 가득한 예배를 위해서 기도해주세요.</p>
    <p>2. 영적 회복, 육적 회복, 관계 회복을 위해서 기도해주세요.</p>
    <p>3. 자녀들이 주님을 알고 믿으며 자라가도록 기도해주세요.</p>

    <hr>
    <div class="colhead small">NPC 선교</div>
    <p class="small">노스필드장로교회 파송 선교사</p>
    <p class="small">선교지: 에디오피아</p>
    <p class="small">선교사: OOO 선교사 (명성의과대학 학장 &amp; 목사)</p>

    <div class="box">
      <b>선교회 대상표</b><br>
      아론회 70세 이상 남자 교우<br>
      드보라회 70세 이상 여자 교우<br>
      바울선교회 60-69세 남/여 교우
    </div>

    <hr>
    <div class="colhead small">헌금통계</div>
    <p class="small">십일조 무명 외 여러분</p>
    <p class="small">감사헌금 무명 외 여러분</p>
    <p class="small">합 계 $0.00</p>
  </div>

</div><!-- .page -->


<div class="page-break"></div>

<!-- ════ PAGE 2 ════ -->
<div class="page">
  <div class="col" id="c1">
    <div class="colhead">예배 및 모임 안내</div>
    <p class="small">주일예배(한국어) 1부 오전 9:00 / 2부 오전 11:00</p>
    <p class="small">새벽 기도회 (월-금) 오전 6:00</p>
    <p class="small">금요 기도회 (금요일) 저녁 7:30</p>
    <p class="small">세퍼드라이프 성경공부: 매주 수요일 저녁 ({p})</p>
  </div>
  <div class="col" id="c2">
    <div class="colhead">섬기시는 분들 (직분자)</div>
    <p class="small">{p} 담임목사</p>
    <p class="small">{s['영유아부']} / {s['초등부']} / {s['중등부']}</p>
    <p class="small">{s['고등부']} / {s['청년부']}</p>
    <p class="small">{s['worship_dir']} (Worship Director)</p>
  </div>
  <div class="col" id="c3">
    <p class="small">31권 20호</p>
    <p class="date-display">2026년 5월 17일</p>
  </div>
</div><!-- .page -->

</body>
</html>
"""


def make_bulletin_pdf(out: Path) -> None:
    from playwright.sync_api import sync_playwright

    html = _bulletin_html()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        pdf_bytes = page.pdf(
            width="14in",
            height="8.5in",
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            print_background=True,
        )
        browser.close()

    out.write_bytes(pdf_bytes)
    print(f"  wrote {out}")


# ── Lyric sheet PNG ──────────────────────────────────────────────────────────

def make_sheet_png(out: Path) -> None:
    """Copy the public band sheet from data/ if available; else generate a placeholder."""
    real = DATA / "real-sheet.png"
    if real.exists():
        shutil.copy2(real, out)
        print(f"  copied {real} → {out}")
        return

    # Fallback: generate a minimal placeholder with Pillow
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (800, 600), color="white")
        draw = ImageDraw.Draw(img)
        font_candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/Library/Fonts/NanumGothic.ttf",
        ]
        font_path = next((p for p in font_candidates if Path(p).exists()), None)
        font = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()
        draw.text((40, 40), "날 구원하신 주  (샘플 악보)", fill="black", font=font)
        img.save(str(out))
        print(f"  generated placeholder → {out}")
    except ImportError:
        sys.exit("Pillow not installed and data/real-sheet.png not found. "
                 "pip install Pillow or place real-sheet.png in data/")


# ── Synthetic medley band sheet ──────────────────────────────────────────────

def make_medley_sheet_png(out: Path) -> None:
    """Draw a synthetic two-song medley sheet bearing the red arrangement marks.

    The real band sheets carry third-party blog watermarks/copyright, so they live in
    git-ignored data/ and can't be committed. This synthetic stand-in lets CI exercise
    the transcribe path (mocked) and documents the marks #52 must read: section labels,
    a ×N repeat, an X-out skip, and a → segue between songs.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        sys.exit("Pillow not installed. pip install Pillow")

    font_candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/NanumGothic.ttf",
    ]
    font_path = next((p for p in font_candidates if Path(p).exists()), None)

    def fnt(size: int):
        return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    img = Image.new("RGB", (800, 600), color="white")
    d = ImageDraw.Draw(img)
    red = (210, 30, 30)
    black = (20, 20, 20)

    # Song 1: title + red arrangement shorthand, with a ×2 repeat and an X-out skip.
    d.text((40, 24), "주께 드리네", fill=black, font=fnt(28))
    d.text((40, 70), "V1  C×2  B  → 부르신 곳에서", fill=red, font=fnt(22))
    d.text((60, 120), "[Verse 1]  나의 모든 것을 주께", fill=black, font=fnt(20))
    d.text((60, 160), "[Chorus]  주께 드리네 나의 삶을", fill=black, font=fnt(20))
    d.text((60, 200), "[Bridge]  영원토록 주를 찬양해", fill=black, font=fnt(20))
    # X-out a dropped 간주 (skip): drawn then struck through in red.
    skip = "[간주]  (instrumental)"
    d.text((60, 240), skip, fill=black, font=fnt(20))
    w = d.textlength(skip, font=fnt(20))
    d.line((60, 250, 60 + w, 250), fill=red, width=3)

    # Song 2 (after the → segue): its own title + shorthand.
    d.text((40, 320), "부르신 곳에서", fill=black, font=fnt(28))
    d.text((40, 366), "C  B×2 (키업E)", fill=red, font=fnt(22))
    d.text((60, 416), "[Chorus]  나는 예배하네 어떤 상황에도", fill=black, font=fnt(20))
    d.text((60, 456), "[Bridge]  걸어갈 때 길이 되고", fill=black, font=fnt(20))
    d.text((60, 520), "(synthetic fixture — see scripts/make_fixtures.py)",
           fill=(150, 150, 150), font=fnt(14))

    img.save(str(out))
    print(f"  generated synthetic medley → {out}")


# ── Keynote template ─────────────────────────────────────────────────────────

def make_template_key(out: Path) -> None:
    script = f"""\
tell application "Keynote"
    set d to make new document with properties {{document theme: theme "White"}}
    save d in POSIX file "{out}"
    close d saving no
end tell
"""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"AppleScript failed:\n{result.stderr}")
    print(f"  wrote {out}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    print("Generating sample_bulletin.pdf …")
    make_bulletin_pdf(FIXTURES / "sample_bulletin.pdf")

    print("Generating sample_sheet.png …")
    make_sheet_png(FIXTURES / "sample_sheet.png")

    print("Generating sample_medley_sheet.png …")
    make_medley_sheet_png(FIXTURES / "sample_medley_sheet.png")

    print("Generating sample_template.key (needs Keynote) …")
    make_template_key(FIXTURES / "sample_template.key")

    print("\nDone. Commit the files in tests/fixtures/")


if __name__ == "__main__":
    main()
