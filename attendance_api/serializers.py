from rest_framework import serializers
from .models import Shift, Department, Employee, Attendance, AbsenceReason, AuditLog

class ShiftSerializer(serializers.ModelSerializer):
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = '__all__'

    def get_employee_count(self, obj):
        return obj.employees.filter(is_active=True).count()

class DepartmentSerializer(serializers.ModelSerializer):
    employee_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = '__all__'

    def get_employee_count(self, obj):
        return obj.employees.filter(is_active=True).count()

class EmployeeSerializer(serializers.ModelSerializer):
    employee_code = serializers.CharField(read_only=True)
    department_name = serializers.ReadOnlyField(source='department.name')
    department_code = serializers.ReadOnlyField(source='department.code')
    shift_name = serializers.ReadOnlyField(source='shift.shift_name')
    shift_code = serializers.ReadOnlyField(source='shift.code')
    full_name = serializers.ReadOnlyField()

    class Meta:
        model = Employee
        fields = '__all__'

class AbsenceReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = AbsenceReason
        fields = ['id', 'reason_category', 'notes']

class AttendanceSerializer(serializers.ModelSerializer):
    employee_code = serializers.ReadOnlyField(source='employee.employee_code')
    employee_name = serializers.ReadOnlyField(source='employee.full_name')
    department_name = serializers.ReadOnlyField(source='employee.department.name')
    department_id = serializers.ReadOnlyField(source='employee.department.id')
    designation = serializers.ReadOnlyField(source='employee.designation')
    shift_code = serializers.ReadOnlyField(source='employee.shift.code')
    shift_name = serializers.ReadOnlyField(source='employee.shift.shift_name')
    reason_details = AbsenceReasonSerializer(read_only=True)

    class Meta:
        model = Attendance
        fields = '__all__'

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'

