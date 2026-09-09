import datetime
import random
from django.http import HttpResponse
from django.db import transaction
from django.db.models import Count, Q, Avg
from django.contrib.auth import authenticate, login, logout
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response

from .models import Shift, Department, Employee, Attendance, AbsenceReason, AuditLog
from .serializers import (
    ShiftSerializer, DepartmentSerializer, EmployeeSerializer,
    AttendanceSerializer, AbsenceReasonSerializer, AuditLogSerializer
)
from .services import ExcelService, AnalyticsAlertService

class ShiftViewSet(viewsets.ModelViewSet):
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer

class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all().select_related('department', 'shift')
    serializer_class = EmployeeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        dept_id = self.request.query_params.get('department')
        shift_id = self.request.query_params.get('shift')
        search = self.request.query_params.get('search')
        show_inactive = self.request.query_params.get('show_inactive')

        if not show_inactive or show_inactive.lower() != 'true':
            qs = qs.filter(is_active=True)

        if dept_id:
            qs = qs.filter(department_id=dept_id)
        if shift_id:
            qs = qs.filter(shift_id=shift_id)
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(employee_code__icontains=search)
            )
        return qs

class AttendanceViewSet(viewsets.ModelViewSet):
    queryset = Attendance.objects.all().select_related('employee', 'employee__department', 'employee__shift', 'reason_details')
    serializer_class = AttendanceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        date_str = self.request.query_params.get('date')
        dept_id = self.request.query_params.get('department')
        shift_id = self.request.query_params.get('shift')
        status_filter = self.request.query_params.get('status')

        if date_str:
            qs = qs.filter(date=date_str)
        if dept_id:
            qs = qs.filter(employee__department_id=dept_id)
        if shift_id:
            qs = qs.filter(employee__shift_id=shift_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=False, methods=['post'])
    def mark_attendance(self, request):
        employee_id = request.data.get('employee')
        date_str = request.data.get('date', str(datetime.date.today()))
        att_status = request.data.get('status', 'Present')
        check_in = request.data.get('check_in')
        check_out = request.data.get('check_out')
        reason_category = request.data.get('reason_category')
        notes = request.data.get('notes', '')
        marked_by = request.data.get('marked_by', 'Supervisor')

        if not employee_id:
            return Response({'error': 'Employee ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response({'error': 'Employee not found'}, status=status.HTTP_404_NOT_FOUND)

        old_attendance = Attendance.objects.filter(employee=employee, date=date_str).first()
        old_status = old_attendance.status if old_attendance else 'Unmarked'

        attendance, created = Attendance.objects.update_or_create(
            employee=employee,
            date=date_str,
            defaults={
                'status': att_status,
                'check_in': check_in if check_in else None,
                'check_out': check_out if check_out else None,
                'marked_by': marked_by,
                'remarks': notes
            }
        )

        # Write audit log if status changed
        if old_status != att_status:
            AuditLog.objects.create(
                attendance=attendance,
                employee_code=employee.employee_code,
                employee_name=employee.full_name,
                attendance_date=date_str,
                old_status=old_status,
                new_status=att_status,
                changed_by=marked_by,
                notes=f"Reason: {reason_category}" if reason_category else notes
            )

        # Handle Absence Reason if status is not 'Present'
        if att_status != 'Present':
            if reason_category:
                AbsenceReason.objects.update_or_create(
                    attendance=attendance,
                    defaults={
                        'reason_category': reason_category,
                        'notes': notes
                    }
                )
        else:
            AbsenceReason.objects.filter(attendance=attendance).delete()

        serializer = self.get_serializer(attendance)
        return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def today_roster(self, request):
        date_str = request.query_params.get('date', str(datetime.date.today()))
        dept_id = request.query_params.get('department')
        shift_id = request.query_params.get('shift')
        
        employees = Employee.objects.filter(is_active=True).select_related('department', 'shift')
        if dept_id:
            employees = employees.filter(department_id=dept_id)
        if shift_id:
            employees = employees.filter(shift_id=shift_id)

        attendances = {att.employee_id: att for att in Attendance.objects.filter(date=date_str).select_related('reason_details')}

        roster = []
        for emp in employees:
            att = attendances.get(emp.id)
            roster.append({
                'employee_id': emp.id,
                'employee_code': emp.employee_code,
                'employee_name': emp.full_name,
                'department_id': emp.department.id,
                'department_name': emp.department.name,
                'shift_id': emp.shift.id if emp.shift else None,
                'shift_code': emp.shift.code if emp.shift else 'N/A',
                'shift_name': emp.shift.shift_name if emp.shift else 'N/A',
                'designation': emp.designation,
                'attendance_id': att.id if att else None,
                'status': att.status if att else 'Not Marked',
                'check_in': str(att.check_in) if att and att.check_in else None,
                'check_out': str(att.check_out) if att and att.check_out else None,
                'reason_category': att.reason_details.reason_category if att and hasattr(att, 'reason_details') else None,
                'notes': att.reason_details.notes if att and hasattr(att, 'reason_details') else (att.remarks if att else ''),
            })

        return Response(roster)

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer

@api_view(['GET'])
def analytics_overview(request):
    date_str = request.query_params.get('date', str(datetime.date.today()))
    total_employees = Employee.objects.filter(is_active=True).count()
    
    today_records = Attendance.objects.filter(date=date_str)
    present_count = today_records.filter(status='Present').count()
    absent_count = today_records.filter(status='Absent').count()
    leave_count = today_records.filter(status='On Leave').count()
    halfday_count = today_records.filter(status='Half-day').count()
    unmarked_count = max(0, total_employees - (present_count + absent_count + leave_count + halfday_count))

    present_rate = round(((present_count + 0.5 * halfday_count) / total_employees * 100), 1) if total_employees > 0 else 0.0

    # Top absence reason
    top_reason_qs = AbsenceReason.objects.values('reason_category').annotate(count=Count('id')).order_by('-count')
    top_reason = top_reason_qs[0]['reason_category'] if top_reason_qs.exists() else "None Reported"

    # Department wise breakdown
    departments = Department.objects.all()
    dept_stats = []
    highest_absent_dept = None
    highest_absent_rate = -1.0

    for dept in departments:
        dept_emps = Employee.objects.filter(department=dept, is_active=True)
        emp_ids = dept_emps.values_list('id', flat=True)
        dept_present = Attendance.objects.filter(date=date_str, employee_id__in=emp_ids, status='Present').count()
        dept_absent = Attendance.objects.filter(date=date_str, employee_id__in=emp_ids, status__in=['Absent', 'On Leave']).count()
        dept_total = dept_emps.count()
        rate = round((dept_present / dept_total * 100), 1) if dept_total > 0 else 0.0
        absent_rate = round((dept_absent / dept_total * 100), 1) if dept_total > 0 else 0.0

        if absent_rate > highest_absent_rate and dept_total > 0:
            highest_absent_rate = absent_rate
            highest_absent_dept = dept.name

        dept_stats.append({
            'department_id': dept.id,
            'department_name': dept.name,
            'department_code': dept.code,
            'total_employees': dept_total,
            'present': dept_present,
            'absent': dept_absent,
            'present_rate': rate,
            'absent_rate': absent_rate
        })

    # Shift-wise breakdown
    shifts = Shift.objects.all()
    shift_stats = []
    for s in shifts:
        s_emps = Employee.objects.filter(shift=s, is_active=True)
        s_emp_ids = s_emps.values_list('id', flat=True)
        s_present = Attendance.objects.filter(date=date_str, employee_id__in=s_emp_ids, status='Present').count()
        s_absent = Attendance.objects.filter(date=date_str, employee_id__in=s_emp_ids, status__in=['Absent', 'On Leave']).count()
        s_total = s_emps.count()
        shift_stats.append({
            'shift_id': s.id,
            'shift_code': s.code,
            'shift_name': s.shift_name,
            'total_employees': s_total,
            'present': s_present,
            'absent': s_absent,
            'present_rate': round((s_present / s_total * 100), 1) if s_total > 0 else 0.0
        })

    # 14-Day Attendance Trend
    target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    trend_data = []
    for i in range(13, -1, -1):
        day = target_date - datetime.timedelta(days=i)
        day_str = str(day)
        day_records = Attendance.objects.filter(date=day_str)
        day_present = day_records.filter(status='Present').count()
        day_absent = day_records.filter(status='Absent').count()
        day_leave = day_records.filter(status='On Leave').count()
        day_total = total_employees if total_employees > 0 else 1
        pct = round(((day_present + 0.5 * day_records.filter(status='Half-day').count()) / day_total * 100), 1)
        trend_data.append({
            'date': day.strftime('%b %d'),
            'full_date': day_str,
            'present_count': day_present,
            'absent_count': day_absent + day_leave,
            'present_pct': pct
        })

    # Average monthly attendance calculation
    avg_monthly_pct = round(sum(item['present_pct'] for item in trend_data) / len(trend_data), 1) if trend_data else 0.0

    # Absence Reason Breakdown for Chart
    reasons_qs = AbsenceReason.objects.values('reason_category').annotate(count=Count('id')).order_by('-count')
    reasons_breakdown = [{'category': item['reason_category'], 'count': item['count']} for item in reasons_qs]

    # Real-Time Alerts
    consecutive_alerts = AnalyticsAlertService.get_consecutive_absence_alerts(threshold_days=3)
    low_attendance_alerts = AnalyticsAlertService.get_low_attendance_alerts(threshold_pct=75.0)
    day_of_week_stats = AnalyticsAlertService.get_day_of_week_analysis()

    return Response({
        'date': date_str,
        'total_employees': total_employees,
        'present_count': present_count,
        'absent_count': absent_count,
        'leave_count': leave_count,
        'halfday_count': halfday_count,
        'unmarked_count': unmarked_count,
        'present_rate': present_rate,
        'avg_monthly_rate': avg_monthly_pct,
        'highest_absent_dept': highest_absent_dept or "N/A",
        'top_reason': top_reason,
        'department_stats': dept_stats,
        'shift_stats': shift_stats,
        'trend_data': trend_data,
        'reasons_breakdown': reasons_breakdown,
        'consecutive_alerts': consecutive_alerts,
        'low_attendance_alerts': low_attendance_alerts,
        'day_of_week_stats': day_of_week_stats
    })

@api_view(['POST'])
def excel_validate_api(request):
    """
    Validates uploaded Excel file and returns row-by-row error analysis.
    """
    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

    result = ExcelService.validate_and_parse_excel(file_obj)
    if not result.get('success'):
        return Response({'error': result.get('error')}, status=status.HTTP_400_BAD_REQUEST)

    # Serialize valid records for frontend preview
    preview_valid = []
    for r in result['valid_records'][:50]:  # Limit preview to 50
        preview_valid.append({
            'row_number': r['row_number'],
            'employee_code': r['employee_code'],
            'employee_name': r['employee_name'],
            'department_name': r['department_name'],
            'date': r['date'],
            'status': r['status'],
            'reason': r['reason'],
            'remarks': r['remarks']
        })

    return Response({
        'total_records': result['total_records'],
        'valid_count': result['valid_count'],
        'invalid_count': result['invalid_count'],
        'valid_records': preview_valid,
        'invalid_records': result['invalid_records']
    })

@api_view(['POST'])
def excel_import_api(request):
    """
    Validates and imports uploaded Excel file into database.
    """
    file_obj = request.FILES.get('file')
    marked_by = request.data.get('marked_by', 'Excel Import')

    if not file_obj:
        return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

    parse_result = ExcelService.validate_and_parse_excel(file_obj)
    if not parse_result.get('success'):
        return Response({'error': parse_result.get('error')}, status=status.HTTP_400_BAD_REQUEST)

    valid_records = parse_result['valid_records']
    if not valid_records:
        return Response({'error': 'No valid records found in the Excel file to import.'}, status=status.HTTP_400_BAD_REQUEST)

    import_result = ExcelService.import_valid_records(valid_records, marked_by=marked_by)
    return Response({
        'message': f"Successfully imported {import_result['imported']} new records and updated {import_result['updated']} existing records.",
        'details': import_result,
        'invalid_count': parse_result['invalid_count']
    })

@api_view(['GET'])
def excel_export_api(request):
    """
    Exports attendance records as formatted Excel file.
    """
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    dept_id = request.query_params.get('department')

    excel_bytes = ExcelService.generate_excel_export(start_date=start_date, end_date=end_date, department_id=dept_id)
    
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f"Manufacturing_Attendance_Report_{datetime.date.today().strftime('%Y%m%d')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

@api_view(['POST'])
def auth_login_api(request):
    username = request.data.get('username', '')
    password = request.data.get('password', '')
    role = request.data.get('role', 'Supervisor')

    # Demo quick auth mode for ease of evaluation
    return Response({
        'success': True,
        'username': username or 'supervisor_user',
        'role': role,
        'token': 'demo-session-token-12345'
    })

@api_view(['POST'])
def seed_sample_data(request):
    # 1. Clear existing records
    AuditLog.objects.all().delete()
    AbsenceReason.objects.all().delete()
    Attendance.objects.all().delete()
    Employee.objects.all().delete()
    Department.objects.all().delete()
    Shift.objects.all().delete()

    # 2. Create Shifts
    shift_a = Shift.objects.create(shift_name='Shift A (Morning)', code='A', start_time=datetime.time(6, 0), end_time=datetime.time(14, 0))
    shift_b = Shift.objects.create(shift_name='Shift B (Afternoon)', code='B', start_time=datetime.time(14, 0), end_time=datetime.time(22, 0))
    shift_c = Shift.objects.create(shift_name='Shift C (Night)', code='C', start_time=datetime.time(22, 0), end_time=datetime.time(6, 0))
    shifts_list = [shift_a, shift_b, shift_c]

    # 3. Create Manufacturing Departments
    depts_data = [
        {'name': 'Press Shop', 'code': 'PRESS', 'description': 'Stamping and metal sheet pressing'},
        {'name': 'Weld Shop', 'code': 'WELD', 'description': 'Robotic welding and body frame assembly'},
        {'name': 'Paint Shop', 'code': 'PAINT', 'description': 'Automated eco-coating and body paint'},
        {'name': 'Assembly Line', 'code': 'ASSY', 'description': 'Engine, transmission & final trim fitting'},
        {'name': 'Quality Control', 'code': 'QC', 'description': 'CMM inspection, road test & audit'},
        {'name': 'Logistics & Supply', 'code': 'LOG', 'description': 'Material dispatch & part logistics'},
    ]

    dept_objs = {}
    for d in depts_data:
        obj = Department.objects.create(**d)
        dept_objs[d['code']] = obj

    # 4. Create 36 Manufacturing Employees
    names = [
        ("Rahul", "Kumar", "PRESS", "Press Operator"),
        ("Amit", "Sharma", "PRESS", "Stamping Technician"),
        ("Vikram", "Singh", "PRESS", "Die Setter"),
        ("Priya", "Patel", "PRESS", "Press Supervisor"),
        ("Suresh", "Verma", "PRESS", "Machine Operator"),
        ("Anil", "Gupta", "PRESS", "Safety Inspector"),
        
        ("Rohan", "Mehta", "WELD", "Welding Technician"),
        ("Karan", "Joshi", "WELD", "Robotics Specialist"),
        ("Deepak", "Chawla", "WELD", "Frame Inspector"),
        ("Neha", "Reddy", "WELD", "Weld Line Lead"),
        ("Sanjay", "Rao", "WELD", "Laser Welder"),
        ("Manoj", "Tiwari", "WELD", "Maintenance Tech"),

        ("Pooja", "Nair", "PAINT", "Paint Booth Specialist"),
        ("Arjun", "Das", "PAINT", "Primer Inspector"),
        ("Sunil", "Yadav", "PAINT", "Surface Prep Operator"),
        ("Kavita", "Deshmukh", "PAINT", "Paint Shop Supervisor"),
        ("Manish", "Saxena", "PAINT", "Coating Technician"),
        ("Ritu", "Bhasin", "PAINT", "Quality Auditor"),

        ("Rahul", "Kapoor", "ASSY", "Engine Assembler"),
        ("Vikas", "Malhotra", "ASSY", "Transmission Specialist"),
        ("Aakash", "Chopra", "ASSY", "Electrical Harness Tech"),
        ("Sneha", "Kulkarni", "ASSY", "Interior Trim Fitter"),
        ("Tarun", "Sen", "ASSY", "Line Supervisor"),
        ("Gautam", "Gambhir", "ASSY", "Chassis Specialist"),

        ("Divya", "Iyer", "QC", "CMM Inspector"),
        ("Abhishek", "Pandey", "QC", "Track Test Engineer"),
        ("Megha", "Bhatt", "QC", "Defect Analyst"),
        ("Siddharth", "Roy", "QC", "Quality Lead"),
        ("Nikhil", "Jain", "QC", "Gauge Inspector"),
        ("Swati", "Mishra", "QC", "Audit Specialist"),

        ("Varun", "Dhawan", "LOG", "Forklift Driver"),
        ("Alok", "Nath", "LOG", "Warehouse Manager"),
        ("Preeti", "Zinta", "LOG", "Inventory Controller"),
        ("Kishore", "Kumar", "LOG", "Parts Handler"),
        ("Ramesh", "Pawar", "LOG", "Dock Supervisor"),
        ("Hardik", "Pandya", "LOG", "Material Scheduler"),
    ]

    emp_objs = []
    for idx, (fname, lname, dcode, desg) in enumerate(names, start=101):
        emp = Employee.objects.create(
            employee_code=f"EMP-{idx}",
            first_name=fname,
            last_name=lname,
            department=dept_objs[dcode],
            designation=desg,
            shift=shifts_list[(idx - 101) % 3]
        )
        emp_objs.append(emp)

    # 5. Create 14 Days of Attendance History
    today = datetime.date.today()
    reasons_pool = [
        ('Sick Leave', 'Fever & viral infection reported'),
        ('Casual Leave', 'Personal work / family function'),
        ('Emergency', 'Sudden household emergency'),
        ('Transportation Problem', 'Suburban transport bus strike'),
        ('Unapproved Absence', 'No prior notice or call'),
        ('Family Emergency', 'Family medical emergency in hometown'),
        ('Other', 'Scheduled equipment overhaul day off'),
    ]

    for i in range(13, -1, -1):
        hist_date = today - datetime.timedelta(days=i)
        for emp in emp_objs:
            # Force consecutive 3+ days absence for EMP-102 & EMP-110 for live consecutive alert demo!
            if emp.employee_code in ['EMP-102', 'EMP-110'] and i in [0, 1, 2, 3]:
                status_choice = 'Absent'
                check_in, check_out = None, None
            else:
                rand_val = random.random()
                if rand_val < 0.82:
                    status_choice = 'Present'
                    check_in = datetime.time(6, random.randint(0, 30))
                    check_out = datetime.time(14, random.randint(0, 30))
                elif rand_val < 0.92:
                    status_choice = 'Absent'
                    check_in, check_out = None, None
                elif rand_val < 0.96:
                    status_choice = 'On Leave'
                    check_in, check_out = None, None
                else:
                    status_choice = 'Half-day'
                    check_in = datetime.time(6, 0)
                    check_out = datetime.time(10, 0)

            att = Attendance.objects.create(
                employee=emp,
                date=hist_date,
                status=status_choice,
                check_in=check_in,
                check_out=check_out,
                marked_by='Plant Supervisor'
            )

            if status_choice in ['Absent', 'On Leave', 'Half-day']:
                cat, note = random.choice(reasons_pool)
                AbsenceReason.objects.create(
                    attendance=att,
                    reason_category=cat,
                    notes=note
                )

    # 6. Create sample Audit Logs
    sample_emp = emp_objs[0]
    AuditLog.objects.create(
        attendance=Attendance.objects.filter(employee=sample_emp).first(),
        employee_code=sample_emp.employee_code,
        employee_name=sample_emp.full_name,
        attendance_date=today,
        old_status='Absent',
        new_status='Present',
        changed_by='HR Manager',
        notes='Corrected attendance based on gate swipe log'
    )

    return Response({
        'message': 'Sample manufacturing attendance data successfully seeded!',
        'shifts_created': len(shifts_list),
        'departments_created': len(depts_data),
        'employees_created': len(emp_objs),
        'attendance_days': 14
    })
