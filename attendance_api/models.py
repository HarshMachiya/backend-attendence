from django.db import models

class Shift(models.Model):
    shift_name = models.CharField(max_length=50)  # e.g. Shift A, Shift B, Shift C
    code = models.CharField(max_length=10, unique=True)  # e.g. A, B, C
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.shift_name} ({self.code}) [{self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}]"

class Department(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

class Employee(models.Model):
    employee_code = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='employees')
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    designation = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    joined_date = models.DateField(auto_now_add=True)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        if not self.employee_code:
            last_employee = Employee.objects.all().order_by('id').last()
            if not last_employee:
                self.employee_code = 'EMP-001'
            else:
                self.employee_code = f'EMP-{last_employee.id + 1:03d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee_code} - {self.full_name}"

class Attendance(models.Model):
    STATUS_CHOICES = [
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Half-day', 'Half-day'),
        ('On Leave', 'On Leave'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Present')
    check_in = models.TimeField(blank=True, null=True)
    check_out = models.TimeField(blank=True, null=True)
    marked_by = models.CharField(max_length=100, default='Supervisor')
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'date')
        ordering = ['-date', 'employee__employee_code']

    def __str__(self):
        return f"{self.employee.employee_code} | {self.date} | {self.status}"

class AbsenceReason(models.Model):
    REASON_CHOICES = [
        ('Sick Leave', 'Sick Leave'),
        ('Casual Leave', 'Casual Leave'),
        ('Emergency', 'Emergency'),
        ('Personal Reason', 'Personal Reason'),
        ('Transportation Problem', 'Transportation Problem'),
        ('Family Emergency', 'Family Emergency'),
        ('Unapproved Absence', 'Unapproved Absence'),
        ('Other', 'Other'),
    ]

    attendance = models.OneToOneField(Attendance, on_delete=models.CASCADE, related_name='reason_details')
    reason_category = models.CharField(max_length=50, choices=REASON_CHOICES)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.attendance.employee.employee_code} - {self.reason_category}"

class AuditLog(models.Model):
    attendance = models.ForeignKey(Attendance, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    employee_code = models.CharField(max_length=50)
    employee_name = models.CharField(max_length=100)
    attendance_date = models.DateField()
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.CharField(max_length=100, default='Supervisor')
    changed_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.employee_code} | {self.attendance_date}: {self.old_status} -> {self.new_status} by {self.changed_by}"


