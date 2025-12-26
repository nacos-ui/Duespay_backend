from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AssociationProfileView,
    AssociationViewSet,
    GetSingleAssociationView,
    NotificationViewSet,
    RetrieveAssociationViewSet,
    SessionViewSet,
)

router = DefaultRouter()

router.register("profiles", AssociationViewSet)
router.register("notifications", NotificationViewSet)
router.register("sessions", SessionViewSet, basename="session")

urlpatterns = [
    path(
        "get-association/<str:association_short_name>/",
        RetrieveAssociationViewSet.as_view(),
        name="retrieve-association",
    ),
    path(
        "get-association/",
        GetSingleAssociationView.as_view(),
        name="get-single-association",
    ),
    path(
        "get-profile/",
        AssociationProfileView.as_view(),
        name="association-profile",
    ),
] + router.urls
