# blockchain
카카오페이(결제) + FastAPI(백엔드) + Streamlit(프론트) + Web3(온체인) 통합 예제입니다.

## 준비
- 가상환경 생성/활성화
  - macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`
  - Windows: `py -m venv .venv && .venv\Scripts\activate`
- 패키지 설치: `pip install -r requirements.txt`

## 실행 모드

### 1) 오프라인(모의) 모드
- 외부 카카오 API 없이 전체 흐름을 로컬에서 검증합니다.
- 백엔드: `MOCK_KAKAO=1 uvicorn backend:app --reload --port 8000`
- 프론트: `streamlit run frontend.py --server.port 8501`
- 브라우저: `http://localhost:8501` → 금액 입력 → 기부하기 → 자동 승인 → 결과 확인

포트 변경 시 프론트에 백엔드 주소 지정
- 예) 백엔드 8010 포트: `BACKEND_BASE=http://localhost:8010/api/v1 streamlit run frontend.py`

## API 빠른 테스트(모의)
- Ready: `curl -X POST http://127.0.0.1:8000/api/v1/kakaopay/ready -H "Content-Type: application/json" -d '{"amountWon":10000,"nickname":"t","memo":"m","returnUrl":"http://localhost:8501"}'`
- Approve: `curl -X POST http://127.0.0.1:8000/api/v1/kakaopay/approve -H "Content-Type: application/json" -H "Idempotency-Key: idem-<orderId>" -d '{"orderId":"<orderId>","pgToken":"OFFLINE"}'`

## 트러블슈팅
- Invalid contract address format
  - 컨트랙트 주소는 길이 42(0x+40hex). 트랜잭션 해시(66자)와 혼동 금지.
- Web3 not connected
  - `RPC_URL` 오타/권한 문제. 헬스 체크 `connected`가 true여야 함.
- No contract code at address
  - 네트워크/주소 불일치. 헬스 체크 `hasContractCode`가 true여야 함.
- Invalid private key
  - 주소가 아닌 “개인키”를 설정. 헬스 체크 `account` 확인.
- insufficient funds for gas
  - 계정에 Sepolia ETH 충전 필요.
- execution reverted (NotWriter/Paused 등)
  - 권한/상태 문제. 컨트랙트 설정(Writer/Unpause) 필요.
- Etherscan에서 Invalid Txn hash
  - 0x 접두사/네트워크 불일치/전파 지연. 본 레포는 자동 보정과 체인 매핑을 적용함.
- 포트 충돌
  - 다른 포트 사용: `--port 8010` / 프론트는 `BACKEND_BASE`로 주소 지정.