import hashlib
import hmac
import json
import logging
import re
import traceback
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Any, Optional

import paystack
from paystack.api.transaction_ import Transaction
from django.conf import settings

logger = logging.getLogger(__name__)


def _ts():
    return datetime.now(dt_tz.utc).isoformat()


def get_paystack_webhook_secret() -> str:
    return getattr(settings, "PAYSTACK_WEBHOOK_SECRET", None) or getattr(
        settings, "PAYSTACK_SECRET", ""
    )


def compute_paystack_signature(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha512).hexdigest()


def is_valid_paystack_signature(raw_body: bytes, header_signature: str) -> bool:
    secret = get_paystack_webhook_secret()
    if not secret or not header_signature:
        return False
    expected = compute_paystack_signature(raw_body, secret)
    return hmac.compare_digest(expected, header_signature)


def _format_amount_2dp(amount: str | Decimal) -> str:
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d:.2f}"


def _sanitize_customer_name(name: str) -> str:
    if not name:
        return "DuesPay User"
    name = re.sub(r"<[^>]*>", "", name)
    name = re.sub(r"&[A-Za-z]+;", "", name)
    name = re.sub(r"[^A-Za-z0-9\s\.\,'\-]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "DuesPay User"


def _amount_to_kobo(amount: str | Decimal) -> int:
    """Convert naira amount to kobo (multiply by 100)"""
    d = Decimal(str(amount)).quantize(Decimal("0.01"))
    return int(d * 100)


def calculate_paystack_charges(amount: Decimal | str | float) -> dict:
    """
    Calculate Paystack transaction charges based on their pricing:
    - 1.5% + ₦100
    - ₦100 fee waived for transactions under ₦2,500
    - Maximum fee capped at ₦2,000
    
    Returns dict with:
    - base_amount: Original amount
    - transaction_fee: Paystack fee
    - total_amount: Amount + fee (what customer pays)
    """
    base_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    
    # Calculate 1.5% of amount
    percentage_fee = (base_amount * Decimal("0.015")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    # Add ₦100 flat fee
    flat_fee = Decimal("100.00")
    transaction_fee = percentage_fee + flat_fee
    
    # Waive ₦100 for transactions under ₦2,500
    if base_amount < Decimal("2500.00"):
        transaction_fee = percentage_fee
    
    # Cap fee at ₦2,000
    if transaction_fee > Decimal("2000.00"):
        transaction_fee = Decimal("2000.00")
    
    total_amount = base_amount + transaction_fee
    
    return {
        "base_amount": base_amount,
        "transaction_fee": transaction_fee,
        "total_amount": total_amount,
    }


class PaystackService:
    def __init__(self):
        """Initialize Paystack service with secret key"""
        print(f"[{_ts()}] PaystackService.__init__() called")
        
        try:
            self.secret_key = getattr(settings, 'PAYSTACK_SECRET', '')
            print(f"[{_ts()}] PAYSTACK_SECRET retrieved: '{self.secret_key[:20]}...' (showing first 20 chars)")
            
            if not self.secret_key:
                error_msg = 'PAYSTACK_SECRET not found in settings'
                logger.error(error_msg)
                print(f"[{_ts()}] ERROR: {error_msg}")
                # Print all available settings that start with PAYSTACK
                paystack_settings = {k: v for k, v in settings.__dict__.items() if 'PAYSTACK' in str(k)}
                print(f"[{_ts()}] Available PAYSTACK settings: {paystack_settings}")
            else:
                print(f"[{_ts()}] PAYSTACK_SECRET found, length: {len(self.secret_key)}")
            
            print(f"[{_ts()}] Setting paystack.api_key...")
            paystack.api_key = self.secret_key
            print(f"[{_ts()}] paystack.api_key set successfully")
            
        except Exception as e:
            error_msg = f"Error in PaystackService.__init__(): {str(e)}"
            logger.error(error_msg)
            print(f"[{_ts()}] CRITICAL ERROR: {error_msg}")
            print(f"[{_ts()}] Traceback: {traceback.format_exc()}")
            raise

    def _handle_response(self, response) -> Dict[str, Any]:
        """Handle API response object and convert to dict"""
        print(f"[{_ts()}] _handle_response called with type: {type(response)}")
        
        try:
            if hasattr(response, '_status') and hasattr(response, '_data'):
                print(f"[{_ts()}] Response has _status: {response._status}, _data: {type(response._data)}")
                if response._status:
                    return {
                        'status': True,
                        'data': response._data,
                        'message': getattr(response, '_message', 'Success')
                    }
                else:
                    return {
                        'status': False,
                        'message': getattr(response, '_message', 'Request failed'),
                        'error': response._data if response._data else 'Unknown error'
                    }

            if hasattr(response, 'data'):
                print(f"[{_ts()}] Response has data attribute: {type(response.data)}")
                if isinstance(response.data, str):
                    try:
                        parsed_data = json.loads(response.data)
                        print(f"[{_ts()}] Parsed JSON data keys: {list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'Not a dict'}")
                        if isinstance(parsed_data, dict) and 'authorization_url' in parsed_data:
                            return {
                                'status': True,
                                'data': parsed_data,
                                'message': 'Transaction initialized successfully'
                            }
                        return parsed_data
                    except json.JSONDecodeError as je:
                        print(f"[{_ts()}] JSON decode error: {str(je)}")
                        return {'error': 'Invalid JSON response', 'raw_data': response.data}

                elif isinstance(response.data, dict):
                    print(f"[{_ts()}] Response data is dict with keys: {list(response.data.keys())}")
                    if 'authorization_url' in response.data:
                        return {
                            'status': True,
                            'data': response.data,
                            'message': 'Transaction initialized successfully'
                        }
                    return response.data

            if hasattr(response, '__dict__'):
                response_dict = response.__dict__
                print(f"[{_ts()}] Response __dict__ keys: {list(response_dict.keys())}")
                if 'authorization_url' in str(response_dict):
                    return {
                        'status': True,
                        'data': response_dict,
                        'message': 'Transaction initialized successfully'
                    }
                return response_dict

            print(f"[{_ts()}] Fallback: returning raw response string")
            return {'raw_response': str(response), 'status': False}

        except Exception as e:
            error_msg = f"Response handling error: {str(e)}"
            logger.error(error_msg)
            print(f"[{_ts()}] ERROR in _handle_response: {error_msg}")
            print(f"[{_ts()}] Traceback: {traceback.format_exc()}")
            return {'status': False, 'error': str(e)}

    def initialize_payment(
        self,
        email: str,
        amount_naira: float,
        reference: str,
        metadata: Optional[Dict[str, Any]] = None,
        callback_url: Optional[str] = None,
        channels: Optional[list] = None
    ) -> Dict[str, Any]:
        """Initialize a payment transaction with Paystack"""
        print(f"[{_ts()}] initialize_payment called")
        print(f"[{_ts()}] Params: email={email}, amount_naira={amount_naira}, reference={reference}")
        print(f"[{_ts()}] Params: callback_url={callback_url}, channels={channels}")
        
        try:
            amount_kobo = _amount_to_kobo(str(amount_naira))
            print(f"[{_ts()}] Converted {amount_naira} naira to {amount_kobo} kobo")

            payment_params = {
                'email': email,
                'amount': amount_kobo,
                'currency': 'NGN',
                'reference': reference,
                'channels': channels or ['card', 'bank_transfer']
            }

            if callback_url:
                payment_params['callback_url'] = callback_url

            if metadata:
                payment_params['metadata'] = json.dumps(metadata)
                print(f"[{_ts()}] Metadata added: {metadata}")

            print(f"[{_ts()}] Final payment_params: {payment_params}")

            logger.info(
                f"[{_ts()}][PAYSTACK][REQ] ref={reference} amount_kobo={amount_kobo} email={email}"
            )
            print(
                f"[{_ts()}] PAYSTACK REQ ref={reference} amount_kobo={amount_kobo} email={email}"
            )

            print(f"[{_ts()}] About to call Transaction.initialize(**payment_params)")
            response = Transaction.initialize(**payment_params)
            print(f"[{_ts()}] Transaction.initialize returned: {type(response)}")

            response_data = self._handle_response(response)
            print(f"[{_ts()}] Handled response data: {response_data}")

            is_successful = (
                response_data.get('status') == True or
                'authorization_url' in response_data or
                (response_data.get('data') and 'authorization_url' in response_data.get('data', {}))
            )
            
            print(f"[{_ts()}] is_successful: {is_successful}")

            if not is_successful:
                error_message = response_data.get('message', 'Payment initialization failed')
                print(f"[{_ts()}] Payment failed with error: {error_message}")
                logger.error(f"[{_ts()}][PAYSTACK][ERR] ref={reference} error={error_message}")
                raise Exception(error_message)

            if 'data' in response_data and isinstance(response_data['data'], dict):
                data = response_data['data']
            elif 'authorization_url' in response_data:
                data = response_data
            else:
                data = response_data

            print(f"[{_ts()}] Final data to return: {data}")

            logger.info(f"[{_ts()}][PAYSTACK][OK] ref={reference} initialized")
            print(f"[{_ts()}] PAYSTACK OK ref={reference}")

            result = {
                'status': True,
                'data': {
                    'authorization_url': data.get('authorization_url'),
                    'access_code': data.get('access_code'),
                    'reference': data.get('reference', reference),
                }
            }
            
            print(f"[{_ts()}] Returning result: {result}")
            return result

        except Exception as e:
            error_msg = f"Error in initialize_payment: {str(e)}"
            logger.error(f"[{_ts()}][PAYSTACK][ERR] ref={reference} error={error_msg}")
            print(f"[{_ts()}] CRITICAL ERROR in initialize_payment: {error_msg}")
            print(f"[{_ts()}] Traceback: {traceback.format_exc()}")
            raise


# Service functions to match your existing pattern
def paystack_init_charge(
    *,
    amount: str,
    currency: str,
    reference: str,
    customer: dict,
    redirect_url: str,
    metadata: dict | None = None,
) -> dict:
    """Initialize Paystack payment charge"""
    print(f"[{_ts()}] paystack_init_charge called")
    print(f"[{_ts()}] Params: amount={amount}, currency={currency}, reference={reference}")
    print(f"[{_ts()}] Params: customer={customer}, redirect_url={redirect_url}")
    
    try:
        platform_name = getattr(settings, "PLATFORM_NAME", "Duespay")
        platform_email = getattr(settings, "PLATFORM_EMAIL", "justondev05@gmail.com")
        print(f"[{_ts()}] Platform: name={platform_name}, email={platform_email}")

        email = (customer or {}).get("email") or platform_email
        if "@" not in str(email):
            email = platform_email
        raw_name = (customer or {}).get("name") or platform_name
        name = _sanitize_customer_name(raw_name)
        print(f"[{_ts()}] Customer: name={name}, email={email}")

        # Prepare metadata
        meta = {"txn_ref": reference}
        if isinstance(metadata, dict):
            try:
                meta.update(
                    {
                        k: (str(v) if isinstance(v, (Decimal,)) else v)
                        for k, v in metadata.items()
                    }
                )
            except Exception as me:
                print(f"[{_ts()}] Metadata update error: {str(me)}")
                if metadata:
                    meta.update(metadata)

        print(f"[{_ts()}] Final metadata: {meta}")

        print(f"[{_ts()}] Creating PaystackService instance...")
        service = PaystackService()
        print(f"[{_ts()}] PaystackService instance created successfully")

        print(f"[{_ts()}] Calling service.initialize_payment...")
        result = service.initialize_payment(
            email=email,
            amount_naira=float(amount),
            reference=reference,
            metadata=meta,
            callback_url=redirect_url,
            channels=['card', 'bank_transfer']
        )
        
        print(f"[{_ts()}] service.initialize_payment returned: {result}")
        return result
        
    except Exception as e:
        error_msg = f"Error in paystack_init_charge: {str(e)}"
        logger.error(f"[{_ts()}][PAYSTACK_CHARGE][ERR] ref={reference} error={error_msg}")
        print(f"[{_ts()}] CRITICAL ERROR in paystack_init_charge: {error_msg}")
        print(f"[{_ts()}] Traceback: {traceback.format_exc()}")
        raise


