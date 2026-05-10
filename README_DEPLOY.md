# Ubuntu 배포 가이드

이 문서는 이 프로젝트를 Ubuntu 가상서버에서 24시간 실행하는 기준으로 정리한 배포 가이드입니다.

대상:
- `telegram_bot.py`를 서버에서 계속 실행
- 서버 재부팅 후에도 자동 실행
- 장애 발생 시 자동 재시작

기준 경로 예시:
- 프로젝트 경로: `/opt/stock-bot`
- 실행 사용자: `ubuntu`


## 1. Ubuntu 패키지 업데이트

```bash
sudo apt update
sudo apt upgrade -y
```


## 2. Python 설치

Ubuntu 22.04/24.04 기준으로 Python 3와 가상환경 패키지를 설치합니다.

```bash
sudo apt install -y python3 python3-pip python3-venv
```

설치 확인:

```bash
python3 --version
pip3 --version
```


## 3. 프로젝트 업로드

로컬 프로젝트를 서버에 업로드합니다.

예시:

```bash
scp -r "C:\Users\user\Documents\New project" ubuntu@SERVER_IP:/opt/stock-bot
```

또는 Git 저장소가 있으면 서버에서 바로 clone 해도 됩니다.

서버에서 경로 확인:

```bash
cd /opt/stock-bot
ls
```


## 4. 가상환경 생성

```bash
cd /opt/stock-bot
python3 -m venv .venv
source .venv/bin/activate
```

가상환경이 활성화되면 프롬프트 앞에 `(.venv)`가 보입니다.


## 5. requirements.txt 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

설치 확인:

```bash
pip list
```


## 6. .env 설정

`.env.example`을 복사해서 `.env`를 만듭니다.

```bash
cp .env.example .env
nano .env
```

예시:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
SCREEN_MODE=real
MAX_SYMBOLS=100
MAX_PER_SECTOR=1
FINAL_RECOMMENDATION_LIMIT=5
GRADE_A_THRESHOLD=60
GRADE_B_THRESHOLD=45
```

설명:
- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: `main.py` 직접 전송 시 사용하는 채팅 ID
- `SCREEN_MODE=real`: 실데이터 모드
- `MAX_SYMBOLS`: 조회 대상 종목 수

보안:
- `.env` 파일은 외부에 공개하지 않는 것이 맞습니다.


## 7. 수동 실행 확인

먼저 수동으로 정상 실행되는지 확인합니다.

```bash
cd /opt/stock-bot
source .venv/bin/activate
python telegram_bot.py
```

정상 실행되면 대기 상태로 들어갑니다.

종료:

```bash
Ctrl + C
```


## 8. screen으로 백그라운드 실행

`screen` 설치:

```bash
sudo apt install -y screen
```

새 세션 생성:

```bash
cd /opt/stock-bot
screen -S stockbot
source .venv/bin/activate
python telegram_bot.py
```

세션 분리:

```bash
Ctrl + A, D
```

세션 복구:

```bash
screen -r stockbot
```

실행 중 세션 목록:

```bash
screen -ls
```


## 9. tmux로 백그라운드 실행

`tmux` 설치:

```bash
sudo apt install -y tmux
```

새 세션 생성:

```bash
cd /opt/stock-bot
tmux new -s stockbot
source .venv/bin/activate
python telegram_bot.py
```

세션 분리:

```bash
Ctrl + B, D
```

세션 복구:

```bash
tmux attach -t stockbot
```

세션 목록:

```bash
tmux ls
```


## 10. systemd 서비스 등록

24시간 운영은 `screen/tmux`보다 `systemd`가 더 적절합니다.

서비스 파일 생성:

```bash
sudo nano /etc/systemd/system/stockbot.service
```

아래 내용을 넣습니다.

```ini
[Unit]
Description=Telegram Stock Recommendation Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/stock-bot
Environment="PATH=/opt/stock-bot/.venv/bin"
ExecStart=/opt/stock-bot/.venv/bin/python /opt/stock-bot/telegram_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

주의:
- `User=ubuntu`는 실제 실행 계정에 맞게 바꿔야 합니다.
- `WorkingDirectory`는 실제 프로젝트 경로로 맞춰야 합니다.


## 11. systemd 서비스 적용

서비스 리로드:

```bash
sudo systemctl daemon-reload
```

서비스 시작:

```bash
sudo systemctl start stockbot
```

상태 확인:

```bash
sudo systemctl status stockbot
```

로그 확인:

```bash
journalctl -u stockbot -f
```


## 12. 서버 재부팅 후 자동 실행 설정

부팅 시 자동 시작:

```bash
sudo systemctl enable stockbot
```

즉시 시작 + 부팅 자동 시작:

```bash
sudo systemctl enable --now stockbot
```

확인:

```bash
sudo systemctl is-enabled stockbot
```


## 13. 자동 재시작 설정

위 `systemd` 서비스 파일에 이미 아래 옵션이 포함되어 있습니다.

```ini
Restart=always
RestartSec=10
```

의미:
- 프로세스가 죽으면 자동 재시작
- 10초 후 재시도


## 14. 서비스 관리 명령어

시작:

```bash
sudo systemctl start stockbot
```

중지:

```bash
sudo systemctl stop stockbot
```

재시작:

```bash
sudo systemctl restart stockbot
```

상태 확인:

```bash
sudo systemctl status stockbot
```

로그 보기:

```bash
journalctl -u stockbot -n 100 --no-pager
```

실시간 로그:

```bash
journalctl -u stockbot -f
```


## 15. 배포 후 점검 체크리스트

1. `python telegram_bot.py` 수동 실행이 정상인지 확인
2. 텔레그램에서 `/start` 응답 확인
3. 텔레그램에서 `/recommend` 응답 확인
4. `systemd` 서비스 시작 확인
5. `journalctl -u stockbot -f`로 오류 여부 확인
6. 서버 재부팅 후 자동 실행 확인


## 16. 권장 운영 방식

운영 기준으로는 아래 순서가 적절합니다.

1. 개발/점검: 수동 실행
2. 임시 운영: `screen` 또는 `tmux`
3. 상시 운영: `systemd`

24시간 운영이 목표라면 최종적으로는 `systemd`를 쓰는 것이 맞습니다.
