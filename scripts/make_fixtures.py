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
    """Sanitized reproduction of the real bulletin layout and content."""
    p = PASTOR
    s = STAFF
    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif;
    font-size: 10.5px;
    color: #111;
  }}
  .page {{
    width: 356mm;
    padding: 8mm 10mm;
  }}
  .page-break {{ page-break-after: always; }}
  h1 {{ font-size: 14px; text-align: center; margin-bottom: 6px; }}
  h2 {{ font-size: 12px; margin: 6px 0 3px; border-bottom: 1px solid #555; }}
  h3 {{ font-size: 11px; margin: 4px 0 2px; }}
  .cols {{ display: flex; gap: 6mm; }}
  .col {{ flex: 1; }}
  .col-wide {{ flex: 1.4; }}
  .col-narrow {{ flex: 0.8; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 10px; }}
  td {{ padding: 1px 4px; vertical-align: top; }}
  td:first-child {{ white-space: nowrap; }}
  p {{ margin: 2px 0; line-height: 1.4; }}
  .small {{ font-size: 9.5px; color: #444; }}
  .indent {{ padding-left: 8px; }}
  hr {{ border: none; border-top: 1px solid #aaa; margin: 4px 0; }}
  .box {{ border: 1px solid #aaa; padding: 4px 6px; margin: 4px 0; font-size: 10px; }}
</style>
</head>
<body>

<!-- ════ PAGE 1 ════ -->
<div class="page">
  <h1>주일예배순서 &nbsp;·&nbsp; 교회소식 &nbsp;·&nbsp; 기도제목</h1>

  <div class="cols">

    <!-- Column 1: Worship order -->
    <div class="col">
      <p class="small">인도: {p}</p>
      <p class="small">노스필드 장로교회는 "성경적 리더를 세워 파송"하는 교회입니다.</p>
      <p class="small">오늘 우리 교회에 처음 오신 분들을 주님의 이름으로 환영합니다.</p>
      <p class="small">교인 등록을 원하시는 분들은 사무실에 말씀해 주세요.</p>
      <hr>

      <table>
        <tr><td>찬 양</td><td>마라나타</td></tr>
        <tr><td>예배의 부름</td><td>시 133:1-3 &nbsp; {p}</td></tr>
        <tr><td>고백의 찬양*</td><td>믿음으로 우리는 &nbsp; 다함께</td></tr>
        <tr><td>신앙고백*</td><td>사도신경 &nbsp; 다함께</td></tr>
        <tr><td>찬 양</td><td>사랑은 (윤학준 곡) &nbsp; 성가대</td></tr>
        <tr><td>봉 헌</td><td>피난처 있으니 (찬 70장) &nbsp; 다함께</td></tr>
        <tr><td>환영 및 인사*</td><td>다함께</td></tr>
        <tr><td>교회소식</td><td>{p}</td></tr>
        <tr><td>합심기도</td><td>다함께</td></tr>
        <tr><td>말 씀</td><td>이를 행하여 나를기념하라 (눅&nbsp;22:14-24) &nbsp; {p}</td></tr>
        <tr><td>파송의 노래*</td><td>축복의 통로 &nbsp; 다함께</td></tr>
        <tr><td>축 도*</td><td>{p}</td></tr>
      </table>
      <p class="small">(*표는 일어서서 하나님께 드립니다.)</p>

      <hr>
      <h3>다음 세대예배</h3>
      <table>
        <tr><td>영유아부</td><td>({s['영유아부']})</td></tr>
        <tr><td>초등부</td><td>Yes, Lord! (2 Kings 22:11) ({s['초등부']})</td></tr>
        <tr><td>중고등부</td><td>When the suffering overwhelms our lives<br>(Luke 8:22-25) ({s['중등부']})</td></tr>
        <tr><td>청년부</td><td>성경공부 초등부 연합 ({s['청년부']})</td></tr>
      </table>
    </div>

    <!-- Column 2: 교회소식 -->
    <div class="col-wide">
      <h2>교회소식</h2>

      <h3>1. 2026년도 24 나무 소그룹</h3>
      <p>2026년 24개 나무 소그룹 편성이 완료되었습니다.
      오늘부터 친교 시간에는 지정된 테이블로 이동하셔서 그룹 리더분들의 안내에 따라
      함께 친교해 주시기 바랍니다.</p>

      <h3>2. 교육부 오픈하우스 안내</h3>
      <p>5/17 (오늘) 교육부 오픈하우스가 열립니다. 초등부에서 중등부로 올라가는
      자녀를 둔 부모님들께서는 자녀와 함께 새로운 부서 예배에 참여하셔서
      은혜로운 시간 되시기를 바랍니다. 초등부는 추후에 오픈하우스를 가질
      예정이오니 양해 부탁드립니다.</p>

      <h3>3. 온세기 기도회</h3>
      <p>5/29 (금요일) 7:30 PM, 온세기 예배로 함께 모입니다.
      온 세대가 한마음으로 기도하는 은혜의 자리에 성도님들을 초대합니다.</p>

      <h3>4. 교육부 졸업 연합예배</h3>
      <p>5/31 (주일) 2부 예배시 교육부 졸업예배가 함께 진행됩니다.
      총 15명의 학생들이 유아부, 초등부, 중등부, 고등부를 졸업할 예정입니다.</p>

      <h3>5. 노스필드 여름성경학교 (VBS) 안내</h3>
      <p>더욱 알차고 체계적인 진행을 위해 영유아부와 초등부 프로그램이 따로 진행됩니다.</p>
      <p class="indent">· 영유아부: 8/3-8/4 (월-화) 9am-12pm</p>
      <p class="indent">· 초등부: 8/5-8/7 (수-금) 9am-3pm</p>
      <p>5/24부터는 Kindergarten 이상(5세 이상)부터 외부 학생들에게 온라인 등록이 진행될
      예정이오니 많은 관심 부탁드립니다.</p>

      <h3>6. 미디어 사역팀 팀원 모집</h3>
      <p>다음 세대예배 미디어 사역팀을 함께 섬겨주실 봉사자를 모집합니다.</p>
      <p class="small">(PPT 제작팀:4명, 조명팀: 1명, 음향팀: 1명, 방송팀: 1명, 카메라팀: 1명)</p>
    </div>

    <!-- Column 3: 기도제목 + 선교 + 헌금 + 봉사자 -->
    <div class="col-narrow">
      <h2>기도제목</h2>
      <p>1. 하나님의 임재와 영광이 가득한 예배를 위해서 기도해주세요.</p>
      <p>2. 영적 회복, 육적 회복 (지체 여러분), 교우, 주변 사람들과의 관계 회복을
      위해서</p>
      <p>3. 자녀들이 주님을 알고 믿으며 세상을 이기는 자들로 자라가도록.</p>

      <hr>
      <h3>NPC 선교</h3>
      <p class="small">노스필드장로교회 파송 선교사</p>
      <p class="small">선교지: 에디오피아</p>
      <p class="small">선교사: OOO 선교사 (명성의과대학 학장 &amp; 목사)</p>
      <p class="small">노스필드장로교회는 에티오피아 내에 무슬림들이 많은 (85%)
      Jimma 도시를 품고 있습니다. 먼저는 그곳에 Ajib Church와
      Bosa Addis Church(짐마 공과대학) 집중해서 섬기고 있습니다.</p>

      <div class="box small">
        <table>
          <tr><td colspan="2"><b>선교회 대상표</b></td></tr>
          <tr><td>아론회</td><td>70세 이상 남자 교우</td></tr>
          <tr><td>드보라회</td><td>70세 이상 여자 교우</td></tr>
          <tr><td>바울선교회</td><td>60-69세 남/여 교우</td></tr>
          <tr><td>여호수아회</td><td>50-59세 남/여 교우</td></tr>
          <tr><td>다윗선교회</td><td>50세 이하 남/여 교우</td></tr>
        </table>
      </div>

      <hr>
      <h3>헌금통계</h3>
      <table>
        <tr><td>십 일 조</td><td>무명 외 여러분</td></tr>
        <tr><td>감사헌금</td><td>무명 외 여러분</td></tr>
        <tr><td>선교헌금</td><td>무명 외 여러분</td></tr>
        <tr><td>구제헌금</td><td>무명 외 여러분</td></tr>
        <tr><td><b>합 계</b></td><td><b>$0.00</b></td></tr>
      </table>

      <hr>
      <h3>친교 봉사위원 &amp; 5월 봉헌위원 OOO 집사</h3>
      <table class="small">
        <tr><td>5월 3일</td><td>봉사자 일동</td></tr>
        <tr><td>5월 10일</td><td>봉사자 일동</td></tr>
        <tr><td>5월 17일</td><td>봉사자 일동</td></tr>
        <tr><td>5월 24일</td><td>봉사자 일동</td></tr>
        <tr><td>5월 31일</td><td>봉사자 일동</td></tr>
      </table>
    </div>

  </div><!-- .cols -->
</div><!-- .page -->


<div class="page-break"></div>

<!-- ════ PAGE 2 ════ -->
<div class="page">
  <div class="cols">

    <!-- Column 1: 예배 및 모임 안내 -->
    <div class="col">
      <h2>예배 및 모임 안내</h2>
      <p class="small">31권 20호 &nbsp; 2026년 5월 17일</p>

      <h3>주일 장년 예배</h3>
      <table>
        <tr><td>주일예배(한국어) 1부</td><td>오전 9:00</td></tr>
        <tr><td>주일예배(한국어) 2부</td><td>오전 11:00</td></tr>
        <tr><td>중보기도 모임</td><td>오전 10:20</td></tr>
      </table>

      <h3>주중 예배</h3>
      <table>
        <tr><td>새벽 기도회 (월-금)</td><td>오전 6:00</td></tr>
        <tr><td>새벽 기도회 (토요일)</td><td>오전 7:00</td></tr>
        <tr><td>금요 기도회 (금요일)</td><td>저녁 7:30</td></tr>
      </table>

      <h3>다음세대 예배</h3>
      <table>
        <tr><td>영유아부 (주일)</td><td>오전 11:00</td></tr>
        <tr><td>초등부 (주일)</td><td>오전 11:00</td></tr>
        <tr><td>중고등부 (주일)</td><td>오전 11:00</td></tr>
        <tr><td>청년부 (주일 성경공부)</td><td>오전 11:20</td></tr>
        <tr><td>(금요기도회)</td><td>오후 9:30</td></tr>
      </table>

      <h3>한국학교</h3>
      <p class="small">다니엘 지상사 한국학교 2/1/2026-5/31/2026 (2학기 14주)</p>
      <p class="small">(주일) 오후 1:10-3:40</p>
      <p class="small">유아반 (3-5세), 초등 1반 (1,2학년)</p>
      <p class="small">초등 2반 (3,4학년), 초등 3반 (4,5학년)</p>
      <p class="small">중고등부반 (6-8학년)</p>

      <hr>
      <h3>장년교육</h3>
      <table class="small">
        <tr><td>NPC 아카데미</td><td>GBS</td><td>일대일</td></tr>
      </table>
      <p class="small">금주 주중예배: 훈련은 약속된 일정입니다 / 말씀을 붙드는 기도 ({p})</p>
      <p class="small">'매일성경'을 따라 말씀을 각자 묵상합니다</p>
      <p class="small">새벽예배 {p}</p>
      <p class="small">세퍼드라이프 성경공부: 매주 수요일 저녁, 세퍼드라이프 2기를 모집합니다.</p>

      <h3>소그룹 성경공부</h3>
      <table class="small">
        <tr><td>창세기 강해</td><td>토요일 8:00 PM 회의실</td></tr>
        <tr><td>어! 성경이 읽어지네 (신약)</td><td>목요일 8:00 PM ZOOM</td></tr>
      </table>
    </div>

    <!-- Column 2: 섬기시는 분들 -->
    <div class="col">
      <h2>섬기시는 분들 (직분자)</h2>
      <table class="small">
        <tr><td>시무장로</td><td>OOO 장로</td></tr>
        <tr><td>협동장로</td><td>OOO 장로, OOO 장로</td></tr>
        <tr><td>시무권사</td><td>OOO 권사 외 여러분</td></tr>
        <tr><td>시무 안수집사</td><td>OOO 집사 외 여러분</td></tr>
        <tr><td>피택 임직자</td><td>OOO 외 여러분</td></tr>
      </table>

      <h3>사역자</h3>
      <table class="small">
        <tr><td>{p}</td><td>담임목사</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['영유아부']}</td><td>영유아부</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['초등부']}</td><td>초등부</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['중등부']}</td><td>중등부</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['고등부']}</td><td>고등부</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['청년부']}</td><td>청년부</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['worship_dir']}</td><td>Worship Director/성가대 지휘</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['music_dir']}</td><td>뮤직디렉터/찬양팀 리더</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['pianist']}</td><td>반주자 성가대 반주</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['admin']}</td><td>행정간사</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>OOO 사모</td><td>한국학교</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
        <tr><td>{s['driver']}</td><td>주일예배 차량운행</td><td>000-000-0000</td><td>xxx@example.com</td></tr>
      </table>

      <hr>
      <div class="small">
        <p>초등부 교사 모집 문의: {s['영유아부']}</p>
        <p>성가대원 모집 문의: {s['worship_dir']}</p>
        <p>미디어사역팀 모집 문의: OOO 집사</p>
        <p>주차안내 봉사자 문의: OOO 집사</p>
      </div>
    </div>

    <!-- Column 3: 사역 조직표 -->
    <div class="col">
      <h2>사역 조직표 / 팀사역 운영단</h2>
      <table class="small">
        <tr><td>예배 1팀</td><td>예배 준비팀 (OOO 권사)</td></tr>
        <tr><td>예배 2팀</td><td>미디어 사역팀 (OOO 집사)</td></tr>
        <tr><td>예배 3팀</td><td>음악 사역팀 (OOO 집사)</td></tr>
        <tr><td>선교 1팀</td><td>선교회 협력팀 (OOO 집사)</td></tr>
        <tr><td>선교 2팀</td><td>선교회 협력2팀 (OOO 장로)</td></tr>
        <tr><td>선교 3팀</td><td>선교팀 (OOO 집사)</td></tr>
        <tr><td>친교 1팀</td><td>새가족팀 (OOO 집사)</td></tr>
        <tr><td>친교 2팀</td><td>친교팀 (OOO 권사)</td></tr>
        <tr><td>친교 3팀</td><td>식사팀 (OOO 권사)</td></tr>
        <tr><td>교육 1팀</td><td>(OOO 집사)</td></tr>
        <tr><td>교육 2팀</td><td>2세 교육팀 (OOO 집사)</td></tr>
        <tr><td>교육 3팀</td><td>장년 교육팀 (OOO 집사)</td></tr>
        <tr><td>재단 관리팀</td><td>건물 관리팀 (OOO 집사)</td></tr>
        <tr><td>차량 관리팀</td><td>(OOO 집사)</td></tr>
        <tr><td>환경 미화팀</td><td>(OOO 집사)</td></tr>
        <tr><td>행정 1팀</td><td>행정 사역팀 (OOO 집사)</td></tr>
        <tr><td>행정 2팀</td><td>재정 사역팀 (OOO 집사)</td></tr>
      </table>

      <hr>
      <h3>팀사역 교육과정</h3>
      <table class="small">
        <tr><td>100</td><td>새가족</td><td>개념학교</td></tr>
        <tr><td>200</td><td>기초</td><td>어! 성경이 읽어지네 / 일대일성경공부</td></tr>
        <tr><td>300</td><td>제자</td><td>제자학교 / 로마서 강해 / 세퍼드라이프(KTEE)</td></tr>
        <tr><td>400</td><td>리더</td><td>리더학교 / 야고보서 강해 / 귀납적성경공부</td></tr>
        <tr><td>500</td><td>사도</td><td>사도학교</td></tr>
        <tr><td>600</td><td>중보기도</td><td>중보기도학교 / 구역 관리팀</td></tr>
      </table>
    </div>

  </div><!-- .cols -->
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
            margin={"top": "8mm", "bottom": "8mm", "left": "8mm", "right": "8mm"},
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

    print("Generating sample_template.key (needs Keynote) …")
    make_template_key(FIXTURES / "sample_template.key")

    print("\nDone. Commit the files in tests/fixtures/")


if __name__ == "__main__":
    main()
