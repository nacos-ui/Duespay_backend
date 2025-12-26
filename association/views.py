from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Association, Notification, Session
from .serializers import (
    AdminProfileSerializer,
    AssociationSerializer,
    NotificationSerializer,
    SessionSerializer,
)

class NotificationPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 10

class AssociationViewSet(viewsets.ModelViewSet):
    queryset = Association.objects.all()
    serializer_class = AssociationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # The authenticated user should be an AdminUser
        try:
            # Since Association has OneToOneField to AdminUser with related_name='association'
            # We can access it directly if the user IS an AdminUser
            if hasattr(self.request.user, "association"):
                return Association.objects.filter(pk=self.request.user.association.pk)
            return Association.objects.none()
        except (AttributeError, Association.DoesNotExist):
            return Association.objects.none()

class RetrieveAssociationViewSet(generics.RetrieveAPIView):
    queryset = Association.objects.all()
    serializer_class = AssociationSerializer
    lookup_field = "association_short_name"
    permission_classes = [AllowAny]


class GetSingleAssociationView(generics.RetrieveAPIView):
    """
    Get the single association without requiring shortname parameter.
    Since only one association can exist, this returns the first (and only) association.
    """
    serializer_class = AssociationSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        """Get the single association instance"""
        association = Association.objects.first()
        if not association:
            raise ValidationError("No association found in the system")
        return association



class NotificationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    queryset = Notification.objects.all()
    pagination_class = NotificationPagination  # Custom pagination

    def get_queryset(self):
        """
        Get notifications for the authenticated AdminUser's association
        """
        try:
            # Since the user should be an AdminUser with a related Association
            if hasattr(self.request.user, "association"):
                return Notification.objects.filter(
                    association=self.request.user.association
                ).order_by("-created_at")
            return Notification.objects.none()
        except (AttributeError, Association.DoesNotExist):
            return Notification.objects.none()

    def perform_create(self, serializer):
        """
        Automatically set the association when creating a notification
        """
        try:
            if hasattr(self.request.user, "association"):
                serializer.save(association=self.request.user.association)
            else:
                raise ValidationError("User has no associated association")
        except (AttributeError, Association.DoesNotExist):
            raise ValidationError("Unable to determine user's association")

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        """
        Mark all notifications as read for the authenticated user's association
        """
        try:
            if hasattr(request.user, "association"):
                association = request.user.association

                # Get count of unread notifications before updating
                unread_count = Notification.objects.filter(
                    association=association, is_read=False
                ).count()

                # Mark all as read
                updated_count = Notification.objects.filter(
                    association=association, is_read=False
                ).update(is_read=True)

                return Response(
                    {
                        "success": True,
                        "message": f"Marked {updated_count} notifications as read",
                        "updated_count": updated_count,
                        "total_unread_before": unread_count,
                    },
                    status=status.HTTP_200_OK,
                )

            else:
                return Response(
                    {"success": False, "message": "User has no associated association"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except (AttributeError, Association.DoesNotExist):
            return Response(
                {"success": False, "message": "Unable to determine user's association"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": f"Error marking notifications as read: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """
        Get count of unread notifications for the authenticated user's association
        """
        try:
            if hasattr(request.user, "association"):
                association = request.user.association

                unread_count = Notification.objects.filter(
                    association=association, is_read=False
                ).count()

                return Response(
                    {"unread_count": unread_count}, status=status.HTTP_200_OK
                )

            else:
                return Response({"unread_count": 0}, status=status.HTTP_200_OK)

        except (AttributeError, Association.DoesNotExist):
            return Response({"unread_count": 0}, status=status.HTTP_200_OK)


class SessionViewSet(viewsets.ModelViewSet):
    serializer_class = SessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        association = getattr(self.request.user, "association", None)
        if association:
            return Session.objects.filter(association=association).order_by(
                "-created_at"
            )
        return Session.objects.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["association"] = getattr(self.request.user, "association", None)
        return context

    def perform_create(self, serializer):
        # When creating a new session, it becomes active and current
        association = getattr(self.request.user, "association", None)
        if association:
            # Deactivate all other sessions for this association
            Session.objects.filter(association=association, is_active=True).update(is_active=False)
            
            # Create the new session as active
            session = serializer.save(is_active=True)
            
            # Set as current session for the association
            association.current_session = session
            association.save()
        else:
            session = serializer.save()

    @action(detail=True, methods=["post"])
    def set_current(self, request, pk=None):
        """Set this session as the current session for the association"""
        try:
            session = self.get_object()
            association = request.user.association

            # Verify session belongs to this association
            if session.association != association:
                return Response(
                    {"error": "Session does not belong to your association"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Deactivate all other sessions for this association
            Session.objects.filter(association=association, is_active=True).exclude(
                pk=session.pk
            ).update(is_active=False)

            # Activate this session
            session.is_active = True
            session.save()

            # Set as current session
            association.current_session = session
            association.save()

            return Response(
                {
                    "success": True,
                    "message": f'Session "{session.title}" is now the current active session',
                    "current_session": SessionSerializer(session).data,
                }
            )

        except Session.DoesNotExist:
            return Response(
                {"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"Error setting current session: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def current(self, request):
        """Get the current session for the association"""
        association = getattr(request.user, "association", None)
        if not association:
            return Response(
                {"error": "No association found"}, status=status.HTTP_400_BAD_REQUEST
            )

        if association.current_session:
            return Response(SessionSerializer(association.current_session).data)
        else:
            return Response(
                {
                    "error": "No current session set. Please create and set a session first.",
                    "current_session": None,
                }
            )


class AssociationProfileView(generics.RetrieveAPIView):
    """Get admin profile with association details"""

    serializer_class = AdminProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return getattr(self.request.user, "association", None)

    def retrieve(self, request, *args, **kwargs):
        association = self.get_object()
        if not association:
            return Response(
                {"error": "No association found for this admin user"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get all sessions for this association
        sessions = Session.objects.filter(association=association).order_by(
            "-created_at"
        )

        serializer = self.get_serializer(association)
        data = serializer.data

        # Add sessions list
        data["sessions"] = SessionSerializer(sessions, many=True).data

        return Response(data)
