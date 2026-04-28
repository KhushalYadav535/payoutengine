# from django.contrib import admin
from django.urls import path
from payouts import views

urlpatterns = [
    # path('admin/', admin.site.urls),
    path('api/v1/merchants/', views.list_merchants),
    path('api/v1/merchants/<uuid:merchant_id>/', views.merchant_dashboard),
    path('api/v1/merchants/<uuid:merchant_id>/payouts/', views.create_payout),
    path('api/v1/merchants/<uuid:merchant_id>/payouts/<uuid:payout_id>/', views.payout_detail),
]
