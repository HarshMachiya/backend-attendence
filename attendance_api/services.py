import datetime
import io
from typing import Dict, Any, List
import pandas as pd
from django.db import transaction
from django.db.models import Count, Q
from .models import Department, Employee, Shift, Attendance, AbsenceReason, AuditLog

class ExcelService:
    """
    Excel Integration Service: Handles importing existing Excel attendance files,
    validating and cleaning records before database insertion, and exporting reports.
    """

    VALID_REASONS = [
        'Sick Leave', 'Casual Leave', 'Emergency', 'Personal Reason',
        'Transportation Problem', 'Family Emergency', 'Unapproved Absence', 'Other'
    ]

    @classmethod
    def validate_and_parse_excel(cls, file_obj) -> Dict[str, Any]:
        """
        Parses an uploaded Excel file, validates records, identifies errors,
        and returns validation summary along with clean records.
        Expected columns: Employee Code, Date, Status, Absence Reason (optional), Remarks (optional)
        """
        try:
            df = pd.read_excel(file_obj)
        except Exception as e:
            return {
                'success': False,
                'error': f"Failed to read Excel file. Please ensure it is a valid .xlsx or .xls file. Details: {str(e)}"
            }

        # Standardize column headers (lowercase, strip whitespace)
        df.columns = [str(col).strip().lower() for col in df.columns]

        # Column mapping support
        code_col = next((c for c in df.columns if 'code' in c or 'emp' in c or 'id' in c), None)
        date_col = next((c for c in df.columns if 'date' in c), None)
        status_col = next((c for c in df.columns if 'status' in c or 'present' in c or 'attendance' in c), None)
        reason_col = next((c for c in df.columns if 'reason' in c or 'absence' in c or 'leave' in c), None)
        remarks_col = next((c for c in df.columns if 'remark' in c or 'note' in c), None)

        if not code_col or not date_col or not status_col:
            return {
                'success': False,
                'error': f"Excel file must contain at least 'Employee Code', 'Date', and 'Status' columns. Found columns: {list(df.columns)}"
            }

        # Cache existing employees and valid reasons
        existing_employees = {emp.employee_code.upper(): emp for emp in Employee.objects.select_related('department', 'shift')}
        
        valid_records = []
        invalid_records = []
        processed_keys = set()

        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-indexed header is row 1
            raw_code = str(row[code_col]).strip() if pd.notna(row[code_col]) else ""
            raw_date = row[date_col]
            raw_status = str(row[status_col]).strip() if pd.notna(row[status_col]) else ""
            raw_reason = str(row[reason_col]).strip() if reason_col and pd.notna(row[reason_col]) else ""
            raw_remarks = str(row[remarks_col]).strip() if remarks_col and pd.notna(row[remarks_col]) else ""

            errors = []

            # 1. Validate Employee Code
            emp_obj = existing_employees.get(raw_code.upper())
            if not raw_code:
                errors.append("Employee Code is missing")
            elif not emp_obj:
                errors.append(f"Employee code '{raw_code}' not found in database")

            # 2. Validate Date
            formatted_date = None
            if pd.isna(raw_date) or str(raw_date).strip() == "":
                errors.append("Date is missing")
            else:
                try:
                    if isinstance(raw_date, (datetime.date, datetime.datetime, pd.Timestamp)):
                        formatted_date = raw_date.strftime('%Y-%m-%d')
                    else:
                        parsed_dt = pd.to_datetime(raw_date)
                        formatted_date = parsed_dt.strftime('%Y-%m-%d')
                except Exception:
                    errors.append(f"Invalid date format '{raw_date}'. Use YYYY-MM-DD or MM/DD/YYYY")

            # 3. Validate Status
            norm_status = raw_status.title()
            if norm_status not in ['Present', 'Absent', 'Half-Day', 'Half-day', 'On Leave']:
                errors.append(f"Invalid status '{raw_status}'. Allowed: Present, Absent, Half-day, On Leave")
            else:
                if norm_status == 'Half-Day':
                    norm_status = 'Half-day'

            # 4. Check Absence Reason requirement if status != Present
            norm_reason = None
            if norm_status in ['Absent', 'On Leave', 'Half-day']:
                if not raw_reason or raw_reason.lower() == 'nan':
                    errors.append(f"Absence reason required for status '{norm_status}'")
                else:
                    matched_reason = next((r for r in cls.VALID_REASONS if r.lower() in raw_reason.lower() or raw_reason.lower() in r.lower()), 'Other')
                    norm_reason = matched_reason
            elif norm_status == 'Present':
                norm_reason = None

            # 5. Check duplicate within file
            if emp_obj and formatted_date:
                key = (emp_obj.id, formatted_date)
                if key in processed_keys:
                    errors.append(f"Duplicate record for employee {raw_code} on date {formatted_date}")
                else:
                    processed_keys.add(key)

            if errors:
                invalid_records.append({
                    'row_number': row_num,
                    'employee_code': raw_code,
                    'date': str(raw_date),
                    'status': raw_status,
                    'reason': raw_reason,
                    'errors': errors
                })
            else:
                valid_records.append({
                    'row_number': row_num,
                    'employee': emp_obj,
                    'employee_code': emp_obj.employee_code,
                    'employee_name': emp_obj.full_name,
                    'department_name': emp_obj.department.name,
                    'date': formatted_date,
                    'status': norm_status,
                    'reason': norm_reason,
                    'remarks': raw_remarks
                })

        return {
            'success': True,
            'total_records': len(df),
            'valid_count': len(valid_records),
            'invalid_count': len(invalid_records),
            'valid_records': valid_records,
            'invalid_records': invalid_records
        }

    @classmethod
    @transaction.atomic
    def import_valid_records(cls, valid_records: List[Dict[str, Any]], marked_by: str = 'Excel Import') -> Dict[str, Any]:
        """
        Inserts/updates valid records into the database with audit tracking.
        """
        imported_count = 0
        updated_count = 0

        for rec in valid_records:
            emp = rec['employee']
            date_str = rec['date']
            att_status = rec['status']
            reason_category = rec['reason']
            remarks = rec['remarks']

            attendance, created = Attendance.objects.update_or_create(
                employee=emp,
                date=date_str,
                defaults={
                    'status': att_status,
                    'marked_by': marked_by,
                    'remarks': remarks
                }
            )

            if created:
                imported_count += 1
            else:
                updated_count += 1

            if att_status != 'Present':
                AbsenceReason.objects.update_or_create(
                    attendance=attendance,
                    defaults={
                        'reason_category': reason_category or 'Other',
                        'notes': f"Imported via Excel: {remarks}" if remarks else 'Imported via Excel'
                    }
                )
            else:
                AbsenceReason.objects.filter(attendance=attendance).delete()

            AuditLog.objects.create(
                attendance=attendance,
                employee_code=emp.employee_code,
                employee_name=emp.full_name,
                attendance_date=date_str,
                old_status='New Record' if created else 'Updated via Excel',
                new_status=att_status,
                changed_by=marked_by,
                notes=f"Bulk Excel Import (Row {rec['row_number']})"
            )

        return {
            'imported': imported_count,
            'updated': updated_count,
            'total': imported_count + updated_count
        }

    @classmethod
    def generate_excel_export(cls, start_date=None, end_date=None, department_id=None) -> bytes:
        """
        Generates formatted Excel report bytes with Attendance list and Summary statistics.
        """
        qs = Attendance.objects.select_related('employee', 'employee__department', 'employee__shift', 'reason_details')
        if start_date:
            qs = qs.filter(date__gte=start_date)
        if end_date:
            qs = qs.filter(date__lte=end_date)
        if department_id:
            qs = qs.filter(employee__department_id=department_id)

        records = []
        for att in qs:
            reason_str = att.reason_details.reason_category if hasattr(att, 'reason_details') and att.reason_details else ''
            notes_str = att.reason_details.notes if hasattr(att, 'reason_details') and att.reason_details else att.remarks or ''
            records.append({
                'Date': str(att.date),
                'Employee ID': att.employee.employee_code,
                'Employee Name': att.employee.full_name,
                'Department': att.employee.department.name,
                'Shift': att.employee.shift.shift_name if att.employee.shift else 'N/A',
                'Designation': att.employee.designation,
                'Status': att.status,
                'Absence Reason': reason_str,
                'Remarks / Notes': notes_str,
                'Marked By': att.marked_by
            })

        df_records = pd.DataFrame(records)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if not df_records.empty:
                df_records.to_excel(writer, sheet_name='Attendance Records', index=False)
                summary_df = df_records.groupby(['Department', 'Status']).size().unstack(fill_value=0)
                summary_df['Total Records'] = summary_df.sum(axis=1)
                if 'Present' in summary_df.columns:
                    summary_df['Attendance Rate (%)'] = (summary_df['Present'] / summary_df['Total Records'] * 100).round(1)
                summary_df.to_excel(writer, sheet_name='Department Summary')
            else:
                pd.DataFrame({'Message': ['No attendance records found for the selected period']}).to_excel(writer, sheet_name='Summary', index=False)

        output.seek(0)
        return output.getvalue()


class AnalyticsAlertService:
    """
    Analytics & Alert Engine for identifying absenteeism patterns, consecutive absence alerts,
    and threshold breaches.
    """

    @classmethod
    def get_consecutive_absence_alerts(cls, threshold_days=3) -> List[Dict[str, Any]]:
        """
        Identifies employees absent for N or more consecutive recorded work days.
        """
        active_employees = Employee.objects.filter(is_active=True).select_related('department', 'shift')
        alerts = []

        for emp in active_employees:
            recent_atts = list(
                Attendance.objects.filter(employee=emp)
                .order_by('-date')[:10]
            )
            if not recent_atts:
                continue

            consecutive_absent = 0
            absent_dates = []
            for att in recent_atts:
                if att.status in ['Absent', 'On Leave']:
                    consecutive_absent += 1
                    absent_dates.append(str(att.date))
                else:
                    break

            if consecutive_absent >= threshold_days:
                alerts.append({
                    'employee_id': emp.id,
                    'employee_code': emp.employee_code,
                    'employee_name': emp.full_name,
                    'department_name': emp.department.name,
                    'shift_name': emp.shift.shift_name if emp.shift else 'N/A',
                    'consecutive_days': consecutive_absent,
                    'absent_dates': absent_dates,
                    'severity': 'HIGH' if consecutive_absent >= 4 else 'MEDIUM',
                    'message': f"⚠ Attendance Alert: {emp.full_name} ({emp.employee_code}) has been absent for {consecutive_absent} consecutive days."
                })

        return sorted(alerts, key=lambda x: x['consecutive_days'], reverse=True)

    @classmethod
    def get_low_attendance_alerts(cls, threshold_pct=75.0) -> List[Dict[str, Any]]:
        """
        Identifies employees whose attendance percentage is below the target threshold (e.g. 75%).
        """
        active_employees = Employee.objects.filter(is_active=True).select_related('department', 'shift')
        alerts = []

        for emp in active_employees:
            atts = list(Attendance.objects.filter(employee=emp))
            total_days = len(atts)
            if total_days < 5:
                continue

            present_days = sum(1 for a in atts if a.status == 'Present') + sum(0.5 for a in atts if a.status == 'Half-day')
            rate = round((present_days / total_days) * 100.0, 1)

            if rate < threshold_pct:
                alerts.append({
                    'employee_id': emp.id,
                    'employee_code': emp.employee_code,
                    'employee_name': emp.full_name,
                    'department_name': emp.department.name,
                    'total_days': total_days,
                    'present_days': present_days,
                    'attendance_rate': rate,
                    'threshold_pct': threshold_pct,
                    'message': f"⚠ Low Attendance Alert: {emp.full_name} ({emp.employee_code}) attendance is {rate}% (Below target {threshold_pct}%)."
                })

        return sorted(alerts, key=lambda x: x['attendance_rate'])

    @classmethod
    def get_day_of_week_analysis(cls) -> List[Dict[str, Any]]:
        """
        Analyzes absenteeism trend by Day of Week (Monday through Saturday).
        """
        atts = Attendance.objects.all()
        dow_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        dow_counts = {dow: {'total': 0, 'absent': 0, 'present': 0} for dow in dow_names}

        for att in atts:
            day_name = att.date.strftime('%A')
            if day_name in dow_counts:
                dow_counts[day_name]['total'] += 1
                if att.status == 'Present':
                    dow_counts[day_name]['present'] += 1
                elif att.status in ['Absent', 'On Leave']:
                    dow_counts[day_name]['absent'] += 1

        result = []
        for day in dow_names[:6]:
            stat = dow_counts[day]
            tot = stat['total']
            absent_pct = round((stat['absent'] / tot * 100.0), 1) if tot > 0 else 0.0
            result.append({
                'day': day,
                'total_records': tot,
                'present': stat['present'],
                'absent': stat['absent'],
                'absence_rate': absent_pct
            })

        return result
