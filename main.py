
import os
import json
import time
import requests
from web3 import Web3
from dotenv import load_dotenv
from web3.middleware import geth_poa_middleware

# Cargar variables de entorno
load_dotenv()

# Configuración principal
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = Web3.to_checksum_address(os.getenv("WALLET_ADDRESS"))
CHAIN_ID = int(os.getenv("CHAIN_ID"))
AMOUNT = Web3.to_wei(float(os.getenv("AMOUNT_TO_BUY")), "ether")
SLIPPAGE = float(os.getenv("SLIPPAGE", 10))
GAS_PRICE = int(os.getenv("GAS_PRICE")) * (10 ** 9)
GAS_LIMIT = int(os.getenv("GAS_LIMIT"))
AUTO_SELL = os.getenv("AUTO_SELL", "false").lower() == "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Telegram
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# Inicializar web3
web3 = Web3(Web3.HTTPProvider(RPC_URL))
web3.middleware_onion.inject(geth_poa_middleware, layer=0)
assert web3.is_connected(), "❌ No conectado a RPC"

# Cargar ABI de router
with open("router_abi.json") as f:
    router_abi = json.load(f)

# Direcciones importantes
ROUTER_ADDRESS = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
FACTORY_ADDRESS = Web3.to_checksum_address("0xCA143Ce32Fe78f1f7019d7d551a6402fC5350c73")  # Pancake Factory

router = web3.eth.contract(address=ROUTER_ADDRESS, abi=router_abi)

# ABI mínima del factory
factory_abi = [{
    "anonymous": False,
    "inputs": [
        {"indexed": True, "internalType": "address", "name": "token0", "type": "address"},
        {"indexed": True, "internalType": "address", "name": "token1", "type": "address"},
        {"indexed": False, "internalType": "address", "name": "pair", "type": "address"}
    ],
    "name": "PairCreated",
    "type": "event"
}]

factory = web3.eth.contract(address=FACTORY_ADDRESS, abi=factory_abi)

WBNB = Web3.to_checksum_address(router.functions.WETH().call())

def send_telegram_message(message):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")

def build_and_send_tx(target_token):
    path = [WBNB, target_token]
    try:
        amounts_out = router.functions.getAmountsOut(AMOUNT, path).call()
        min_tokens = int(amounts_out[1] * (1 - SLIPPAGE / 100))
        if DEBUG:
            print(f"Min tokens after slippage: {min_tokens}")

        nonce = web3.eth.get_transaction_count(WALLET_ADDRESS)
        tx = router.functions.swapExactETHForTokens(
            min_tokens,
            path,
            WALLET_ADDRESS,
            int(time.time()) + 120
        ).build_transaction({
            "from": WALLET_ADDRESS,
            "value": AMOUNT,
            "gas": GAS_LIMIT,
            "gasPrice": GAS_PRICE,
            "nonce": nonce,
            "chainId": CHAIN_ID,
        })

        signed_tx = web3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        message = f"🚀 Compra automática:
Token: {target_token}\nTx: https://bscscan.com/tx/{web3.to_hex(tx_hash)}"
        print(message)
        send_telegram_message(message)
    except Exception as e:
        print(f"❌ Error TX: {e}")
        send_telegram_message(f"❌ Error: {e}")

def handle_new_pair(event):
    token0 = event["args"]["token0"]
    token1 = event["args"]["token1"]
    pair_address = event["args"]["pair"]

    token_address = token0 if token1 == WBNB else (token1 if token0 == WBNB else None)
    if not token_address:
        return

    msg = f"🆕 *Nueva Memecoin Detectada:*
Token: `{token_address}`
Par: `{pair_address}`"
    print(msg)
    send_telegram_message(msg)
    build_and_send_tx(Web3.to_checksum_address(token_address))

def watch_pairs():
    print("🔍 Esperando nuevos pares...")
    event_filter = factory.events.PairCreated.create_filter(fromBlock="latest")
    while True:
        for event in event_filter.get_new_entries():
            handle_new_pair(event)
        time.sleep(2)

# Iniciar watcher de nuevas memecoins
watch_pairs()
