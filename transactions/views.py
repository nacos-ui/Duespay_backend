import json
import logging
from decimal import Decimal
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from association.models import Association, Session
from payers.models import Payer
from payments.models import PaymentItem, ReceiverBankAccount
from transactions.models import Transaction

print("DEBUG: Starting to import paystackServices")

from .paystackServices import (
    is_valid_paystack_signature,
    paystack_init_charge,
    calculate_paystack_charges,
)
from .models import Transaction, TransactionReceipt
from .serializers import TransactionReceiptDetailSerializer, TransactionSerializer

logger = logging.getLogger(__name__)

class TransactionPagination(PageNumberPagination):
    page_size = 7  
    page_size_query_param = 'page_size'  
    max_page_size = 1000

class TransactionViewSet(viewsets.ModelViewSet):
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = TransactionPagination

    def get_queryset(self):
        association = getattr(self.request.user, "association", None)
        queryset = Transaction.objects.none()

        if association:
            # Get session_id from query params or use current session
            session_id = self.request.query_params.get("session_id")

            if session_id:
                # Validate that session belongs to this association
                try:
                    session = Session.objects.get(
                        id=session_id, association=association
                    )
                    queryset = Transaction.objects.filter(session=session)
                except Session.DoesNotExist:
                    queryset = Transaction.objects.none()
            elif association.current_session:
                # Use current session if no session_id provided
                queryset = Transaction.objects.filter(
                    session=association.current_session
                )
            else:
                # No session available, return empty queryset
                queryset = Transaction.objects.none()

        # Filter by verification status (case-insensitive)
        status_param = self.request.query_params.get("status")
        if status_param is not None:
            if status_param.lower() == "verified":
                queryset = queryset.filter(is_verified=True)
            elif status_param.lower() == "unverified":
                queryset = queryset.filter(is_verified=False)

        # Search by payer name or reference id (case-insensitive)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                models.Q(reference_id__icontains=search)
                | models.Q(payer__first_name__icontains=search)
                | models.Q(payer__last_name__icontains=search)
                | models.Q(payer__matric_number__icontains=search)
            )

        return queryset

    def perform_create(self, serializer):
        association = getattr(self.request.user, "association", None)
        if not association or not association.current_session:
            raise ValidationError(
                "No current session available. Please create a session first."
            )

        serializer.save(
            payer=self.request.user.payer,
            association=association,
            session=association.current_session,  # Auto-assign current session
        )

    def list(self, request, *args, **kwargs):
        # Check if association has a current session
        association = getattr(self.request.user, "association", None)
        if not association:
            return Response(
                {"error": "No association found for user"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session_id = self.request.query_params.get("session_id")
        current_session = None

        if session_id:
            try:
                current_session = Session.objects.get(
                    id=session_id, association=association
                )
            except Session.DoesNotExist:
                return Response(
                    {
                        "error": "Session not found or does not belong to your association"
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
        elif association.current_session:
            current_session = association.current_session
        else:
            return Response(
                {
                    "error": "No session available. Please create a session first.",
                    "results": [],
                    "count": 0,
                    "next": None,
                    "previous": None,
                    "meta": {
                        "total_collections": 0,
                        "completed_payments": 0,
                        "pending_payments": 0,
                        "total_transactions": 0,
                        "percent_collections": "-",
                        "percent_completed": "-",
                        "percent_pending": "-",
                        "current_session": None,
                    },
                }
            )

        queryset = self.filter_queryset(self.get_queryset()).order_by("-submitted_at")
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            data = serializer.data
        else:
            serializer = self.get_serializer(queryset, many=True)
            data = serializer.data

        total_collections = (
            queryset.aggregate(total=models.Sum("amount_paid"))["total"] or 0
        )

        # Completed Payments (assuming is_verified=True means completed)
        completed_count = queryset.filter(is_verified=True).count()

        # Pending Payments (assuming is_verified=False means pending)
        pending_count = queryset.filter(is_verified=False).count()

        # Calculate percentages
        total_count = queryset.count()
        percent_completed = (
            round((completed_count / total_count * 100), 1) if total_count > 0 else 0
        )
        percent_pending = (
            round((pending_count / total_count * 100), 1) if total_count > 0 else 0
        )

        meta = {
            "total_collections": float(total_collections),
            "completed_payments": completed_count,
            "pending_payments": pending_count,
            "total_transactions": total_count,
            "percent_collections": "-",  # You can calculate this based on your business logic
            "percent_completed": f"{percent_completed}%",
            "percent_pending": f"{percent_pending}%",
            "current_session": (
                {
                    "id": current_session.id,
                    "title": current_session.title,
                    "start_date": current_session.start_date,
                    "end_date": current_session.end_date,
                    "is_active": current_session.is_active,
                }
                if current_session
                else None
            ),
        }

        if page is not None:
            paginated_response = self.get_paginated_response(data)
            response_data = paginated_response.data
            response_data["meta"] = meta
            return Response(response_data)
        else:
            return Response(
                {
                    "results": data,
                    "count": len(data),
                    "next": None,
                    "previous": None,
                    "meta": meta,
                }
            )


class TransactionReceiptDetailView(RetrieveAPIView):
    queryset = TransactionReceipt.objects.select_related(
        "transaction__payer", "transaction__association", "transaction__session"
    ).prefetch_related("transaction__payment_items")
    serializer_class = TransactionReceiptDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = "receipt_id"


class InitiatePaymentView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data or {}
        required = ["payer_id", "association_id", "session_id", "payment_item_ids"]
        missing = [k for k in required if k not in data]
        if missing:
            return Response(
                {"error": f"Missing fields: {', '.join(missing)}"}, status=400
            )

        try:
            payer = Payer.objects.get(pk=data["payer_id"])
            association = Association.objects.get(pk=data["association_id"])
            session = Session.objects.get(
                pk=data["session_id"], association=association
            )
        except (Payer.DoesNotExist, Association.DoesNotExist, Session.DoesNotExist):
            return Response(
                {"error": "Invalid payer_id, association_id, or session_id"}, status=400
            )

        item_ids = data.get("payment_item_ids") or []
        if not isinstance(item_ids, list) or not item_ids:
            return Response(
                {"error": "payment_item_ids must be a non-empty list"}, status=400
            )
        items_qs = PaymentItem.objects.filter(id__in=item_ids, session=session)
        if items_qs.count() != len(set(item_ids)):
            return Response(
                {"error": "One or more payment items not found for the session"},
                status=400,
            )

        # Calculate total amount from payment items (base amount without fees)
        base_amount = sum((item.amount for item in items_qs), Decimal("0.00"))

        # Calculate Paystack charges
        charge_breakdown = calculate_paystack_charges(base_amount)
        total_with_fees = charge_breakdown["total_amount"]
        transaction_fee = charge_breakdown["transaction_fee"]

        # Create pending transaction with BASE amount (what association receives)
        txn = Transaction.objects.create(
            payer=payer,
            association=association,
            amount_paid=base_amount,  # Store base amount, not total with fees
            is_verified=False,
            session=session,
        )
        txn.payment_items.set(items_qs)

        # Customer details - always use payer information
        full_name = f"{getattr(payer, 'first_name', '')} {getattr(payer, 'last_name', '')}".strip() or "DuesPay User"
        email = getattr(payer, "email", None) or getattr(settings, "PLATFORM_EMAIL", "justondev05@gmail.com")
        
        # Ensure valid email format
        if "@" not in str(email):
            email = getattr(settings, "PLATFORM_EMAIL", "justondev05@gmail.com")
        
        customer = {"name": full_name, "email": email}

        # Frontend redirect - Paystack will redirect to /pay after payment
        frontend = getattr(settings, "FRONTEND_URL", "https://nacos-duespay.vercel.app/")
        redirect_url = f"{str(frontend).rstrip('/')}/pay"

        # Metadata for reconciliation
        metadata = {
            "txn_ref": txn.reference_id,
            "association_id": association.id,
            "payer_id": payer.id,
            "base_amount": str(base_amount),
            "transaction_fee": str(transaction_fee),
            "total_amount": str(total_with_fees),
        }

        logger.info(
            f"[INITIATE] ref={txn.reference_id} base={base_amount} fee={transaction_fee} total={total_with_fees}"
        )
        print(
            f"[{timezone.now().isoformat()}] INITIATE ref={txn.reference_id} base={base_amount} fee={transaction_fee} total={total_with_fees}"
        )

        try:
            # Initialize payment with TOTAL amount (including fees)
            paystack_res = paystack_init_charge(
                amount=str(total_with_fees),  # Customer pays this
                currency="NGN",
                reference=txn.reference_id,
                customer=customer,
                redirect_url=redirect_url,
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                f"[INITIATE][ERROR] ref={txn.reference_id} Paystack init failed"
            )
            return Response({"error": "Failed to initialize payment"}, status=502)

        data_obj = paystack_res.get("data") or {}
        checkout_url = data_obj.get("authorization_url")
        if not checkout_url:
            logger.error(
                f"[INITIATE][ERROR] ref={txn.reference_id} Missing authorization_url resp={paystack_res}"
            )
            return Response(
                {
                    "error": "Paystack did not return an authorization URL",
                    "provider_response": paystack_res,
                },
                status=502,
            )

        logger.info(
            f"[INITIATE][OK] ref={txn.reference_id} authorization_url={checkout_url}"
        )
        
        # Return breakdown for frontend display
        return Response(
            {
                "reference_id": txn.reference_id,
                "base_amount": str(base_amount),
                "transaction_fee": str(transaction_fee),
                "total_amount": str(total_with_fees),
                "checkout_url": checkout_url,
            },
            status=201,
        )

# New Paystack Webhook
@csrf_exempt
@require_http_methods(["POST"])
def paystack_webhook(request):
    """
    Handles Paystack webhook events for payment verification
    """
    signature = request.headers.get("x-paystack-signature")
    if not is_valid_paystack_signature(request.body, signature):
        logger.warning("[PAYSTACK_WEBHOOK] invalid signature")
        return HttpResponseForbidden()

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.error("[PAYSTACK_WEBHOOK] invalid JSON")
        return HttpResponse(status=200)

    event = payload.get("event")
    data = payload.get("data") or {}
    logger.info(f"[PAYSTACK_WEBHOOK] event={event} data_keys={list(data.keys())}")
    print(f"[{timezone.now().isoformat()}] PAYSTACK_WEBHOOK event={event}")

    # Handle successful charge events
    if event not in ("charge.success", "transfer.success"):
        return HttpResponse(status=200)

    # Get reference from webhook data
    reference = data.get("reference")
    if not reference:
        logger.warning("[PAYSTACK_WEBHOOK] No reference in webhook data")
        return HttpResponse(status=200)

    try:
        txn = Transaction.objects.get(reference_id=reference)
    except Transaction.DoesNotExist:
        logger.warning(f"[PAYSTACK_WEBHOOK] No transaction found for ref={reference}")
        return HttpResponse(status=200)

    if txn.is_verified:
        logger.info(f"[PAYSTACK_WEBHOOK] Already verified ref={txn.reference_id}")
        return HttpResponse(status=200)

    # Get amount from webhook (in kobo, convert to naira) for logging
    amount_kobo = data.get("amount", 0)
    amount_paid_total = Decimal(str(amount_kobo)) / 100

    # Only update verification status, keep the base amount already stored
    # The transaction was created with base_amount (what association receives)
    # The webhook amount includes Paystack fees, which we don't want to store
    txn.is_verified = True
    txn.save(update_fields=["is_verified"])
    
    logger.info(f"[PAYSTACK_WEBHOOK][VERIFIED] ref={txn.reference_id} base_amount={txn.amount_paid} total_paid={amount_paid_total}")
    print(f"[{timezone.now().isoformat()}] PAYSTACK VERIFIED ref={txn.reference_id} base_amount={txn.amount_paid} total_paid={amount_paid_total}")

    return HttpResponse(status=200)


class PaymentStatusView(APIView):
    """
    Simple polling endpoint for frontend after redirect.
    """

    permission_classes = [AllowAny]

    def get(self, request, reference_id: str):
        try:
            txn = Transaction.objects.select_related(
                "payer", "association", "session"
            ).get(reference_id=reference_id)
        except Transaction.DoesNotExist:
            return Response({"exists": False}, status=200)

        receipt = getattr(txn, "receipt", None)
        payload = {
            "exists": True,
            "reference_id": txn.reference_id,
            "is_verified": txn.is_verified,
            "amount_paid": str(txn.amount_paid),
            "receipt_id": getattr(receipt, "receipt_id", None),
        }
        return Response(payload, status=200)
