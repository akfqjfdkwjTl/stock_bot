# 국내주식 조건 기반 관심종목 텔레그램 봇

국내주식 종목을 조건으로 선별해서 텔레그램 명령으로 받아보는 프로그램입니다.

현재 구성은 아래 두 가지 실행 방식을 지원합니다.

- `python main.py`: 한 번 실행해서 결과를 콘솔과 텔레그램으로 전송
- `python telegram_bot.py`: 텔레그램 명령형 봇으로 계속 대기

## 기능

- `FinanceDataReader`로 국내주식 실데이터 조회
- `short`, `swing`, `mid` 3개 전략 점수 계산
- 최종 추천 단계에서 섹터 분산 적용
- 최종 결과를 `A급 추천`과 `관찰 후보` 기준으로 분류
- `results.csv` 저장
- `insta_post.png` 이미지 생성 코드는 유지하되 기본 실행에서는 비활성화
- 텔레그램 명령형 봇 지원
- 조회 실패 종목은 건너뛰고 계속 진행

## 파일 구조

- `main.py`: 기존 단발 실행 진입점, 메시지 생성
- `telegram_bot.py`: 텔레그램 명령 처리와 polling 실행
- `image_renderer.py`: 추천 결과를 1080x1080 이미지로 생성
- `stock_screener.py`: 실데이터/샘플 데이터 조회와 전략 실행
- `strategies.py`: 전략 조건 검사와 점수 계산
- `telegram_sender.py`: 텔레그램 전송 공통 함수
- `config.py`: 환경변수와 공통 설정 관리
- `requirements.txt`: 설치 패키지 목록
- `.env.example`: 환경변수 예시
- `DESIGN.md`: 전략 구조와 점수 기준 설명

## 설치 방법

1. Python 3.10 이상을 준비합니다.
2. 가상환경을 만들고 활성화합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3. 패키지를 설치합니다.

```powershell
pip install -r requirements.txt
```

4. `.env.example`을 참고해서 `.env` 파일을 만듭니다.

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
SCREEN_MODE=real
MAX_SYMBOLS=40
```

## 텔레그램 봇 실행 방법

아래 명령으로 봇을 실행합니다.

```powershell
python telegram_bot.py
```

실행 후 봇은 종료되지 않고 계속 대기합니다.

텔레그램에서 사용할 명령어:

- `/start`
- `/recommend`
- `/recommend short`
- `/recommend swing`
- `/recommend mid`

`/recommend` 실행 시 텍스트 추천 결과만 전송합니다.

`/start`를 입력하면:

```text
주식 추천 봇입니다. /recommend 입력 시 종목을 보내드립니다.
```

## 기존 단발 실행 방법

한 번만 실행해서 바로 결과를 받고 싶으면 아래 명령을 사용합니다.

```powershell
python main.py
```

## 참고 사항

- `TELEGRAM_BOT_TOKEN`은 반드시 필요합니다.
- `TELEGRAM_CHAT_ID`는 `main.py`에서 직접 전송할 때 사용합니다.
- `telegram_bot.py`는 사용자가 봇 대화창에서 명령을 입력하면 그 채팅으로 응답합니다.
- 이미지 생성 기능 코드는 남아 있지만 현재 기본 실행에서는 사용하지 않습니다.
- 실데이터 조회가 느리면 `.env`에서 `MAX_SYMBOLS` 값을 더 낮춰서 속도를 줄일 수 있습니다.
- 같은 섹터가 반복 추천되지 않도록 `MAX_PER_SECTOR` 설정값으로 섹터당 최대 추천 개수를 제한합니다. 기본값은 `1`입니다.
- 최종 추천은 최대 5개까지 보여주며, `A급 추천`을 먼저 출력하고 부족한 수는 `관찰 후보`로 보충합니다.
- `A급 추천`이 없으면 `현재 기준 강한 추천 종목 없음`을 출력하고, 그 대신 `관찰 후보`를 최대 5개까지 보여줍니다.
- 기준값:
  `A급 추천`: 60점 이상
  `관찰 후보`: 45점 이상 60점 미만
- 섹터 분산은 기본 1개를 유지하고, 후보가 부족할 때만 관찰 후보에서 같은 섹터를 최대 2개까지 허용합니다.
- `swing` 전략은 `20일 > 10일 > 5일` 변동성 축소, 5일 평균 거래량 증가, 박스 상단 근접/돌파를 모두 만족하는 경우만 통과합니다.
- 뉴스 점수는 종목명 또는 종목 별칭이 직접 들어간 기사만 반영해서, 업종과 무관한 억지 테마 연결을 줄였습니다.
- 이 프로그램은 자동매매 도구가 아니라 조건 기반 관심종목 선별기입니다.
