from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ShiftViewSet, DepartmentViewSet, EmployeeViewSet, AttendanceViewSet, AuditLogViewSet,
    analytics_overview, excel_validate_api, excel_import_api, excel_export_api,
    auth_login_api, seed_sample_data
)

router = DefaultRouter()
router.register(r'shifts', ShiftViewSet)
router.register(r'departments', DepartmentViewSet)
router.register(r'employees', EmployeeViewSet)
router.register(r'attendance', AttendanceViewSet)
router.register(r'audit-logs', AuditLogViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('analytics/overview/', analytics_overview, name='analytics_overview'),
    path('excel/validate/', excel_validate_api, name='excel_validate_api'),
    path('excel/import/', excel_import_api, name='excel_import_api'),
    path('excel/export/', excel_export_api, name='excel_export_api'),
    path('auth/login/', auth_login_api, name='auth_login_api'),
    path('seed/', seed_sample_data, name='seed_sample_data'),
]
