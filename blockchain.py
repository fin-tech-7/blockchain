# blockchain.py
from web3 import Web3
import json

# --- Step 1에서 준비한 정보들을 여기에 입력하세요 ---
# 1. RPC URL
RPC_URL = "여기에_Infura나_Alchemy에서_받은_RPC_URL을_입력하세요"
# 2. 배포된 스마트 컨트랙트 주소
CONTRACT_ADDRESS = "여기에_팀원에게_받은_스마트컨트랙트_주소를_입력하세요"
# 3. 트랜잭션 발생용 지갑의 비밀키
WALLET_PRIVATE_KEY = "여기에_테스트용_지갑의_비밀키를_입력하세요"
# 4. 스마트 컨트랙트 ABI
CONTRACT_ABI = """
여기에_팀원에게_받은_ABI_JSON_내용을_그대로_붙여넣으세요
"""
# ----------------------------------------------------

# Web3 인스턴스 생성 및 컨트랙트 연결
w3 = Web3(Web3.HTTPProvider(RPC_URL))
contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)
account = w3.eth.account.from_key(WALLET_PRIVATE_KEY)

def record_donation_on_chain(amount, user_address="Anonymous", memo=""):
    """스마트 컨트랙트의 recordDonation 함수를 호출하여 기부 내역을 기록합니다."""
    try:
        # 1. 트랜잭션 생성
        nonce = w3.eth.get_transaction_count(account.address)
        tx = contract.functions.recordDonation(
            amount, memo
        ).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': 300000,  # 가스 한도 (충분하게 설정)
            'gasPrice': w3.eth.gas_price,
        })
        
        # 2. 트랜잭션 서명
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=WALLET_PRIVATE_KEY)
        
        # 3. 트랜잭션 전송
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        
        # 4. 트랜잭션 처리 대기
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        print(f"블록체인 기록 성공! 트랜잭션 해시: {tx_hash.hex()}")
        return tx_hash.hex()
        
    except Exception as e:
        print(f"블록체인 기록 중 오류 발생: {e}")
        return None