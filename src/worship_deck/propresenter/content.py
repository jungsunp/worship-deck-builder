"""Fixed-wording deck content for the ProPresenter generator (v3 migration, #171/#178).

These are the parts of the deck that don't come from the weekly ``ServiceData``. Under Keynote
they never needed code at all: ``build()`` mutates ``master.key`` in place, so roughly half the
171-slide deck — the liturgy, the recurring section headings, the opening/closing cards — simply
rode along inside the template. The ``.pro`` generator builds a fresh ``Presentation`` every week
and has no template to ride on, so every one of those slides has to be authored here (#178).

Every string below is **copied verbatim from the church's own deck**, not composed: dumped with
``keynote.build.dump_slide_texts`` over ``templates/master.key`` (the slide numbers are noted per
constant). There are several Korean translations of 사도신경 and 주기도문 in circulation and the
congregation recites one of them from memory — inventing a variant would be worse than useless.

Non-sensitive (no member names/amounts) — safe to commit.
"""

from __future__ import annotations

# Section divider headings, matching the church's wording (the same landmark text
# keynote/anchors.py detects; see config/slide_map.yaml). Used as CueGroup labels + divider slides.
# Declared in service order — build() walks this liturgy top to bottom in place of the Keynote
# builder's landmark detection.
DIVIDER_LABELS = {
    "opening": "예배 시작",
    "call_to_worship": "예배의 부름",
    "repentance_call": "회개로의 초대",
    "absolution": "죄사함의 선포",
    "worship_songs": "찬양",
    "confession_song": "고백의 찬양",
    "apostles_creed": "사도신경",
    "choir_song": "성가대 찬양",
    "offering_hymn": "봉 헌",
    "welcome": "환영 및 인사",
    "announcements": "교회 소식",
    "united_prayer": "합심 기도",
    "sermon": "말씀",
    "sending": "파송의 노래",
    "benediction": "축도",
    "lords_prayer": "주기도문",
    "ending": "예배 마침",
}

# ── Opening / closing cards ───────────────────────────────────────────────────

# The two services share one deck, so every bookend slide exists twice (master slides 1–2, 167–168).
SERVICE_PARTS = ("1부", "2부")
OPENING_NOTICE = "앞자리부터 앉아주시기 바랍니다. 휴대폰은 꺼 주시거나 진동으로 전환해 주시기 바랍니다."
CLOSING_BLESSING = "*하나님안에서 사랑합니다*"

# 교회 표어 card (master slide 3). The second line splits: the quoted motto is gold, the 「입니다.」
# that closes the sentence is white — the operator set it that way restyling a draft (#178 review).
# master.key has a stray closing 」 after 교회, which they also dropped; it is a typo, not styling.
MOTTO = ["노스필드 장로교회는", ("“성경적 리더”를 세워 파송하는 교회 ", "입니다.")]

# Shown inside 교회 소식 (master slide 116). The 표어 line is per-YEAR — update it each January.
WELCOME_CARD = [
    "노스필드 장로교회는",
    "“성경적 리더”를 세워 파송하는 교회입니다",  # same stray 」 dropped as in MOTTO
    "2026표어  -  “가족”",
    "오늘 저희 교회에 처음 오신 분들을",
    "주님의 이름으로 환영합니다",
]

# Master slide 169.
CLOSING_NOTE = [
    "은혜 받은 말씀으로 잠시 기도하시고",
    "천천히 친교실로 이동해 주세요",
    "주 안에서 사랑합니다",
]

# Master slide 76 — a lighting cue for the booth, not congregation-facing. Carried as a slide
# *note* on the 성가대 divider cue rather than as a slide of its own.
CHOIR_LIGHT_NOTE = "성가대 시작 전 11번 불켜기 (Stage 1)"

# ── Fixed liturgy ─────────────────────────────────────────────────────────────

# 사도신경, responsive form (master slides 70–72) — leader asks, congregation answers.
APOSTLES_CREED_RESPONSIVE = [
    [
        "여러분은 하나님을 믿으십니까?",
        "예, 나는 전능하신 아버지 하나님,",
        "천지의 창조주를 믿습니다.",
        "나는 그의 유일하신 아들",
        "우리 주 예수 그리스도를 믿습니다.",
    ],
    [
        "예수님은 누구십니까?",
        "그는 성령으로 잉태하사, 동정녀 마리아에게 나시고,",
        "본디오 빌라도에게 고난을 받으사, 십자가에 못 박혀",
        "죽으시고 장사한 지 사흘만에",
        "죽은 자 가운데서 다시 살아나셨으며",
        "하늘에 오르사 전능하신 하나님 우편에 앉아 계시다가",
        "저리로서 산 자와 죽은 자를 심판하러 오십니다.",
    ],
    [
        "여러분은 성령님을 믿으십니까?",
        "예, 나는 성령을 믿사오며",
        "거룩한 공회와 성도가 서로 교통하는 것과",
        "죄를 사하여 주시는 것과",
        "몸이 다시 사는 것과",
        "영원히 사는 것을 믿사옵나이다. 아멘",
    ],
]

# 사도신경, traditional recitation (master slides 74–75). The deck carries BOTH forms and the
# operator uses whichever the service calls for, so the generator emits both (#178).
APOSTLES_CREED = [
    [
        "전능하사 천지를 만드신 하나님 아버지를 내가 믿사오며",
        "그 외아들 우리 주 예수 그리스도를 믿사오니",
        "이는 성령으로 잉태하사 동정녀 마리아에게 나시고",
        "본디오 빌라도에게 고난을 받으사",
        "십자가에 못박혀 죽으시고",
        "장사한 지 사흘 만에 죽은 자 가운데서 다시 살아나시며",
        "하늘에 오르사 전능하신 하나님 우편에 앉아 계시다가",
    ],
    [
        "저리로서 산 자와 죽은 자를 심판하러 오시리라",
        "성령을 믿사오며",
        "거룩한 공회와 성도가 서로 교통하는 것과",
        "죄를 사하여 주시는 것과",
        "몸이 다시 사는 것과",
        "영원히 사는 것을 믿사옵나이다",
        "아멘",
    ],
]

# 주기도문 (master slides 164–165).
LORDS_PRAYER = [
    [
        "하늘에 계신 우리 아버지여",
        "이름이 거룩히 여김을 받으시오며",
        "나라이 임하옵시며",
        "뜻이 하늘에서 이룬 것 같이 땅에서도 이루어지이다.",
    ],
    [
        "오늘날 우리에게 일용할 양식을 주옵시고",
        "우리가 우리에게 죄 지은 자를 사하여 준 것 같이",
        "우리의 죄를 사하여 주옵시고",
        "우리를 시험에 들게 하지 마옵시고",
        "다만 악에서 구하옵소서.",
        "대개 나라와 권세와 영광이 아버지께 영원히 있사옵나이다.",
        "아멘",
    ],
]

# ── 파송의 노래 ────────────────────────────────────────────────────────────────

# The same song closes every service (master slides 157–159), so it is fixed content rather than
# a ServiceData field. Shaped as a Song-as-dict so build.fill_song consumes it unchanged.
SENDING_SONG = {
    "title": "축복의 통로",
    "lines": [
        "당신은 하나님의 언약 안에 있는 축복의 통로",
        "당신을 통하여서 열방이 주께 돌아오게 되리",
        "당신은 하나님의 언약 안에 있는 축복의 통로",
        "당신을 통하여서 열방이 주께 예배하게 되리",
    ],
}

# It is sung twice — once before each of the two closing elements (master slides 155–156).
SENDING_CUES = ("축도 전 찬양", "주기도문 전 찬양")
