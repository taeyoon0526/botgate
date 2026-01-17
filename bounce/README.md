# Bounce

Red-DiscordBot v3.5+용 커스텀 Cog입니다. 서버 입장 후 짧은 시간 내 퇴장하는 "들낙"을 감지해 DM 안내 후 임시 밴을 적용합니다.

## 기능 요약
- 설정된 시간 내 퇴장 감지(기본 60초)
- DM 안내(담당자 목록 포함, 최대 인원 제한)
- 임시 밴 + 만료 시 자동 해제(재시작 유지)
- 로그 채널 임베드 기록(선택)
- 봇 계정 제외/포함 토글

## 설치 방법 (로컬 단일 파일 기준)
1) 이 폴더를 Red의 로컬 cog 경로에 넣습니다.
2) Red 콘솔에서 로드:
```
[p]load bounce
```

## 필수 권한/인텐트 체크리스트
- Discord Developer Portal에서 **SERVER MEMBERS INTENT** ON
- Red 실행 인텐트에 `members` 활성화
- Red봇 권한:
  - `Ban Members`
  - `View Channel`, `Send Messages`, `Embed Links` (로그 채널 사용 시)

## 기본 사용 순서(권장)
1) `[p]bounce roles @담당자역할1,@담당자역할2`
2) `[p]bounce logchannel #로그채널`
3) `[p]bounce enable`

## 명령어
- `[p]bounce enable` : 기능 활성화
- `[p]bounce disable` : 기능 비활성화
- `[p]bounce status` : 현재 설정 요약
- `[p]bounce window <seconds>` : 판정 시간 설정
- `[p]bounce banduration <10m|12h|1d|7d>` : 기본 밴 기간 설정
- `[p]bounce roles <role1,role2>` : 담당자 역할 설정
- `[p]bounce roles list` : 담당자 역할 목록
- `[p]bounce roles clear` : 담당자 역할 초기화
- `[p]bounce logchannel <#channel|off>` : 로그 채널 설정/해제
- `[p]bounce maxcontacts <N>` : DM 최대 담당자 수
- `[p]bounce includebots <true|false>` : 봇 포함 여부

## 테스트 시나리오
1) `[p]bounce enable`
2) 테스트 계정이 서버에 들어온 뒤 60초 내 퇴장
3) 로그 채널 임베드/밴/DM 시도 여부 확인
4) 밴 만료 후 자동 unban 확인
