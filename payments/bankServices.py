import logging
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def _ts():
    return datetime.now(timezone.utc).isoformat()


class VerifyBankService:
    """
    Paystack bank list and account verification service
    """

    BASE_URL = "https://api.paystack.co"
    HEADERS = {
        # Paystack requires SECRET key for bank verification
        "Authorization": f"Bearer {getattr(settings, 'PAYSTACK_SECRET', '')}",
        "Content-Type": "application/json",
    }
    BANK_LIST_CACHE_KEY = "paystack_bank_list"
    BANK_LIST_CACHE_TIMEOUT = 60 * 60 * 24  # 24 hours

    @staticmethod
    def get_bank_list():
        """
        Fetch list of Nigerian banks and their codes from Paystack.
        Returns a list of { name, code } dicts.
        """
        print(f"[{_ts()}] [BANKS] Fetching bank list from Paystack...")
        cached_banks = cache.get(VerifyBankService.BANK_LIST_CACHE_KEY)
        if cached_banks:
            logger.info(
                f"[{_ts()}][BANKS] Using cached banks count={len(cached_banks)}"
            )
            print(f"[{_ts()}] [BANKS] Cached banks: {len(cached_banks)}")
            return cached_banks

        # Fallback list in case Paystack is unreachable
        fallback_banks = [
            {"name": "Access Bank", "code": "044"},
            {"name": "Zenith Bank", "code": "057"},
            {"name": "GTBank", "code": "058"},
            {"name": "First Bank of Nigeria", "code": "011"},
            {"name": "United Bank for Africa", "code": "033"},
            {"name": "Fidelity Bank", "code": "070"},
            {"name": "FCMB", "code": "214"},
            {"name": "Stanbic IBTC Bank", "code": "221"},
            {"name": "Sterling Bank", "code": "232"},
            {"name": "Unity Bank", "code": "215"},
            {"name": "Wema Bank", "code": "035"},
            {"name": "Union Bank", "code": "032"},
            {"name": "Polaris Bank", "code": "076"},
            {"name": "Ecobank Nigeria", "code": "050"},
        ]

        # Paystack endpoint: GET /bank
        url = f"{VerifyBankService.BASE_URL.rstrip('/')}/bank"
        params = {
            "country": "nigeria",  # Paystack uses 'country' parameter
            "perPage": 100  # Get more banks in one request
        }
        
        try:
            resp = requests.get(
                url, headers=VerifyBankService.HEADERS, params=params, timeout=15
            )
            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            
            # Paystack returns { status: true/false, message: "", data: [...] }
            if not resp.ok or not data.get("status"):
                logger.error(
                    f"[{_ts()}][BANKS][ERR] status={resp.status_code} body={data}"
                )
                print(f"[{_ts()}] [BANKS][ERR] status={resp.status_code}")
                raise RuntimeError("Paystack bank list error")

            banks_raw = data.get("data") or []
            # Map to {name, code} for frontend compatibility
            banks = [
                {"name": b.get("name"), "code": b.get("code")}
                for b in banks_raw
                if b.get("name") and b.get("code") and b.get("active")  # Only active banks
            ]
            
            cache.set(
                VerifyBankService.BANK_LIST_CACHE_KEY,
                banks,
                VerifyBankService.BANK_LIST_CACHE_TIMEOUT,
            )
            logger.info(f"[{_ts()}][BANKS][OK] fetched={len(banks)}")
            print(f"[{_ts()}] [BANKS][OK] fetched={len(banks)} banks from Paystack")
            return banks
            
        except Exception as e:
            logger.error(f"[{_ts()}][BANKS][EXC] {e}", exc_info=True)
            print(f"[{_ts()}] [BANKS] Using fallback banks: {len(fallback_banks)}")
            return fallback_banks

    @staticmethod
    def verify_account(account_number, bank_code):
        """
        Verify bank account using Paystack.
        Returns dict with keys: account_name, bank_name, account_number, bank_code.
        """
        print(f"[{_ts()}] [VERIFY] acct={account_number} bank={bank_code}")
        
        # Paystack endpoint: GET /bank/resolve
        url = f"{VerifyBankService.BASE_URL.rstrip('/')}/bank/resolve"
        params = {
            "account_number": str(account_number),
            "bank_code": str(bank_code)
        }

        try:
            resp = requests.get(
                url, headers=VerifyBankService.HEADERS, params=params, timeout=20
            )
            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            
            # Paystack returns { status: true/false, message: "", data: {...} }
            if not resp.ok or not data.get("status"):
                logger.error(
                    f"[{_ts()}][VERIFY][ERR] status={resp.status_code} body={data}"
                )
                print(f"[{_ts()}] [VERIFY][ERR] status={resp.status_code} msg={data.get('message', 'Unknown error')}")
                return None

            d = data.get("data") or {}
            if d.get("account_name"):
                result = {
                    "account_name": d.get("account_name"),
                    "account_number": str(account_number),
                    "bank_code": str(bank_code),
                    "bank_name": "",  # Paystack doesn't return bank name in resolve, we can look it up if needed
                    # Optional fields for compatibility
                    "first_name": "",
                    "last_name": "",
                    "other_name": "",
                }
                logger.info(
                    f"[{_ts()}][VERIFY][OK] acct={result['account_number']} name={result['account_name']}"
                )
                print(f"[{_ts()}] [VERIFY][OK] acct={result['account_number']} name={result['account_name']}")
                return result

            logger.warning(f"[{_ts()}][VERIFY] No account_name in response: {data}")
            print(f"[{_ts()}] [VERIFY] No account_name found")
            return None
            
        except Exception as e:
            logger.error(f"[{_ts()}][VERIFY][EXC] {e}", exc_info=True)
            print(f"[{_ts()}] [VERIFY][EXC] {str(e)}")
            return None
